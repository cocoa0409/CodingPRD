"""Composite setup helpers (multi-step fixtures).

Every test starts against an empty DB (the runner restarts the server before
each test), so fixtures build their full preconditions from scratch using
only PRD-declared endpoints.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    PINE_PLOTS_6,
    create_bid_payload,
    create_buyer_payload,
    create_carbon_valuation_payload,
    create_contractor_payload,
    create_cruise_payload,
    create_forester_payload,
    create_landowner_payload,
    create_prescription_payload,
    create_record_planting_payload,
    create_sale_payload,
    create_scale_ticket_payload,
    create_settlement_payload,
    create_stand_payload,
    create_survey_payload,
    create_tract_payload,
)
from .test_users import (
    TEST_USERS,
    make_buyer_headers,
    make_contractor_headers,
    make_forester_headers,
    make_landowner_headers,
)

ADMIN = TEST_USERS["admin_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]


def _clean(payload: dict) -> dict:
    """Drop keys explicitly set to None so they are omitted from the request."""
    return {k: v for k, v in payload.items() if v is not None}


# ---------------------------------------------------------------------------
# Tier 1: registry parties + land base
# ---------------------------------------------------------------------------


def setup_registry(buyer_overrides=None, with_buyer=True, with_contractor=True):
    """Create one forester + one landowner (+ optional buyer/contractor).
    Returns a dict of the created entities."""
    out = {}
    forester = get_success_data(api_client.create_forester(create_forester_payload(), ADMIN))
    landowner = get_success_data(api_client.create_landowner(create_landowner_payload(), ADMIN))
    out["forester"] = forester
    out["landowner"] = landowner
    out["forester_headers"] = make_forester_headers(forester["id"])
    out["landowner_headers"] = make_landowner_headers(landowner["id"])
    if with_buyer:
        buyer = get_success_data(
            api_client.create_buyer(create_buyer_payload(**(buyer_overrides or {})), ADMIN)
        )
        out["buyer"] = buyer
        out["buyer_headers"] = make_buyer_headers(buyer["id"])
    if with_contractor:
        contractor = get_success_data(
            api_client.create_contractor(create_contractor_payload(), ADMIN)
        )
        out["contractor"] = contractor
        out["contractor_headers"] = make_contractor_headers(contractor["id"])
    return out


def setup_tract_and_stand(acres=50, tract_acres=100, with_buyer=True, with_contractor=True,
                          buyer_overrides=None, species="PINE"):
    """Registry + tract + stand. Returns dict with all entities plus headers."""
    reg = setup_registry(buyer_overrides=buyer_overrides, with_buyer=with_buyer,
                         with_contractor=with_contractor)
    fh = reg["forester_headers"]
    tract = get_success_data(api_client.create_tract(
        create_tract_payload(total_acres=tract_acres,
                             landowner_id=reg["landowner"]["id"],
                             forester_id=reg["forester"]["id"]),
        fh,
    ))
    stand = get_success_data(api_client.create_stand(
        create_stand_payload(tract_id=tract["id"], acres=acres, primary_species=species),
        fh,
    ))
    reg.update({"tract": tract, "stand": stand})
    return reg


# ---------------------------------------------------------------------------
# Tier 2: cruise pipeline (DRAFT → TALLIED → RECONCILED → CERTIFIED)
# ---------------------------------------------------------------------------


def setup_tallied_cruise(plots=None, **registry_kwargs):
    """Stand + one TALLIED cruise (no reconcile yet). Returns dict."""
    base = setup_tract_and_stand(**registry_kwargs)
    fh = base["forester_headers"]
    cruise = get_success_data(api_client.create_cruise(
        create_cruise_payload(stand_id=base["stand"]["id"],
                              plots=plots if plots is not None else PINE_PLOTS_6),
        fh,
    ))
    get_success_data(api_client.finalize_tally(cruise["id"], fh))
    base["cruise"] = cruise
    return base


def setup_reconciled_cruise(plots=None, reconciled_plot_numbers=None, **registry_kwargs):
    """Stand + one RECONCILED cruise. Returns dict."""
    base = setup_tallied_cruise(plots=plots, **registry_kwargs)
    fh = base["forester_headers"]
    n = reconciled_plot_numbers if reconciled_plot_numbers is not None else [1, 2, 3, 4, 5, 6]
    cruise = get_success_data(api_client.reconcile_cruise(
        base["cruise"]["id"], {"reconciled_plot_numbers": n}, fh
    ))
    base["cruise"] = cruise
    return base


def setup_certified_cruise(plots=None, reconciled_plot_numbers=None, **registry_kwargs):
    """Stand + one CERTIFIED cruise. Returns dict with stand_version refreshed."""
    base = setup_reconciled_cruise(plots=plots,
                                   reconciled_plot_numbers=reconciled_plot_numbers,
                                   **registry_kwargs)
    fh = base["forester_headers"]
    stand = get_success_data(api_client.get_stand(base["stand"]["id"], fh))
    cruise = get_success_data(api_client.certify_cruise(
        base["cruise"]["id"], {"expected_stand_version": stand["version"]}, fh
    ))
    base["cruise"] = cruise
    base["stand"] = get_success_data(api_client.get_stand(base["stand"]["id"], fh))
    return base


# ---------------------------------------------------------------------------
# Tier 3: prescription pipeline
# ---------------------------------------------------------------------------


def setup_approved_prescription(plots=None, **registry_kwargs):
    """Certified cruise + APPROVED prescription on the stand. Returns dict."""
    base = setup_certified_cruise(plots=plots, **registry_kwargs)
    fh = base["forester_headers"]
    lh = base["landowner_headers"]
    prescription = get_success_data(api_client.create_prescription(
        create_prescription_payload(stand_id=base["stand"]["id"],
                                    cruise_id=base["cruise"]["id"]),
        fh,
    ))
    get_success_data(api_client.propose_prescription(prescription["id"], fh))
    prescription = get_success_data(api_client.approve_prescription(prescription["id"], lh))
    base["prescription"] = prescription
    return base


def setup_active_prescription(plots=None, **registry_kwargs):
    """APPROVED → ACTIVE prescription. Returns dict."""
    base = setup_approved_prescription(plots=plots, **registry_kwargs)
    fh = base["forester_headers"]
    prescription = get_success_data(
        api_client.activate_prescription(base["prescription"]["id"], fh)
    )
    base["prescription"] = prescription
    return base


# ---------------------------------------------------------------------------
# Tier 4: sale pipeline
# ---------------------------------------------------------------------------


def setup_sale_draft(sale_overrides=None, plots=None, **registry_kwargs):
    """Certified cruise + APPROVED prescription + DRAFT sale."""
    base = setup_approved_prescription(plots=plots, **registry_kwargs)
    fh = base["forester_headers"]
    sale = get_success_data(api_client.create_sale(
        _clean(create_sale_payload(tract_id=base["tract"]["id"],
                                   stand_id=base["stand"]["id"],
                                   prescription_id=base["prescription"]["id"],
                                   **(sale_overrides or {}))),
        fh,
    ))
    base["sale"] = sale
    return base


def setup_sale_offered(sale_overrides=None, plots=None, **registry_kwargs):
    """Sale → OFFERED."""
    base = setup_sale_draft(sale_overrides=sale_overrides, plots=plots, **registry_kwargs)
    fh = base["forester_headers"]
    sale = get_success_data(api_client.offer_sale(base["sale"]["id"], fh))
    base["sale"] = sale
    return base


def setup_sale_bidding_open(sale_overrides=None, plots=None,
                            clock_iso="2026-05-12T00:00:00Z", **registry_kwargs):
    """Sale → BIDDING_OPEN with logical clock advanced inside the bid window."""
    base = setup_sale_offered(sale_overrides=sale_overrides, plots=plots, **registry_kwargs)
    fh = base["forester_headers"]
    get_success_data(api_client.set_clock({"to_iso8601": clock_iso}, ADMIN))
    sale = get_success_data(api_client.open_bidding(base["sale"]["id"], fh))
    base["sale"] = sale
    return base


def setup_sale_bidding_closed(bid_overrides=None, sale_overrides=None, plots=None,
                              **registry_kwargs):
    """Sale → BIDDING_CLOSED with one qualifying bid submitted then window closed."""
    base = setup_sale_bidding_open(sale_overrides=sale_overrides, plots=plots,
                                   **registry_kwargs)
    fh = base["forester_headers"]
    bh = base["buyer_headers"]
    sale = base["sale"]
    bid_payload = create_bid_payload(expected_sale_version=sale["version"],
                                     **(bid_overrides or {}))
    if sale["sale_type"] == "LUMP_SUM":
        bid_payload.pop("species_rates", None)
        bid_payload.setdefault("lump_sum_amount_cents", 8_000_000)
    else:
        bid_payload.pop("lump_sum_amount_cents", None)
    bid_payload = _clean(bid_payload)
    bid = get_success_data(api_client.submit_bid(sale["id"], bid_payload, bh))
    get_success_data(api_client.set_clock({"to_iso8601": "2026-05-21T00:00:00Z"}, ADMIN))
    sale = get_success_data(api_client.close_bidding(sale["id"], fh))
    base["sale"] = sale
    base["bid"] = bid
    return base


def setup_sale_awarded(bid_overrides=None, sale_overrides=None, plots=None,
                       **registry_kwargs):
    """Sale → AWARDED; contract PENDING_BOND exists. Returns dict with contract."""
    base = setup_sale_bidding_closed(bid_overrides=bid_overrides,
                                     sale_overrides=sale_overrides, plots=plots,
                                     **registry_kwargs)
    fh = base["forester_headers"]
    sale = get_success_data(
        api_client.award_sale(base["sale"]["id"], {"bid_id": base["bid"]["id"]}, fh)
    )
    base["sale"] = sale
    contracts_data = get_success_data(
        api_client.list_contracts(fh, params={"sale_id": sale["id"]})
    )
    contract = contracts_data[0]
    base["contract"] = contract
    return base


# ---------------------------------------------------------------------------
# Tier 5: contract lifecycle
# ---------------------------------------------------------------------------


def setup_contract_active(bond_amount_cents=None, bid_overrides=None,
                          sale_overrides=None, plots=None, **registry_kwargs):
    """Contract ACTIVE (bond posted, contractor assigned)."""
    base = setup_sale_awarded(bid_overrides=bid_overrides, sale_overrides=sale_overrides,
                              plots=plots, **registry_kwargs)
    bh = base["buyer_headers"]
    contract = base["contract"]
    get_success_data(api_client.assign_contractor(
        contract["id"], {"contractor_id": base["contractor"]["id"]}, bh
    ))
    amount = bond_amount_cents if bond_amount_cents is not None else contract["required_bond_amount_cents"]
    bond = get_success_data(api_client.post_bond(contract["id"], {"amount_cents": amount}, bh))
    base["bond"] = bond
    base["contract"] = get_success_data(
        api_client.get_contract(contract["id"], base["forester_headers"])
    )
    return base


def setup_contract_harvesting(clock_iso="2026-06-15T00:00:00Z", **kwargs):
    """Contract HARVESTING (harvest started by contractor)."""
    base = setup_contract_active(**kwargs)
    get_success_data(api_client.set_clock({"to_iso8601": clock_iso}, ADMIN))
    contract = get_success_data(api_client.start_harvest(
        base["contract"]["id"], base["contractor_headers"]
    ))
    base["contract"] = contract
    return base


def setup_contract_harvest_complete(clock_iso="2026-08-01T00:00:00Z", **kwargs):
    """Contract HARVEST_COMPLETE; obligation IMPOSED exists."""
    base = setup_contract_harvesting(**kwargs)
    get_success_data(api_client.set_clock({"to_iso8601": clock_iso}, ADMIN))
    contract = get_success_data(api_client.complete_harvest(
        base["contract"]["id"], base["contractor_headers"]
    ))
    base["contract"] = contract
    obligations_data = get_success_data(api_client.list_obligations(
        base["forester_headers"], params={"contract_id": contract["id"]}
    ))
    base["obligation"] = obligations_data[0]
    return base


# ---------------------------------------------------------------------------
# Tier 6: scale tickets and settlements
# ---------------------------------------------------------------------------


def add_verified_ticket(base, scaled_date="2026-06-20", log_count=1, length_ft=16,
                        diameter_in=14, species="PINE"):
    """Create + verify a scale ticket against base['contract']; returns ticket."""
    ch = base["contractor_headers"]
    fh = base["forester_headers"]
    ticket = get_success_data(api_client.create_scale_ticket(
        create_scale_ticket_payload(contract_id=base["contract"]["id"],
                                    scaled_date=scaled_date, species=species,
                                    small_end_diameter_in=diameter_in,
                                    length_ft=length_ft, log_count=log_count),
        ch,
    ))
    ticket = get_success_data(api_client.verify_scale_ticket(ticket["id"], fh))
    return ticket


def setup_per_unit_settlement_draft(period_start="2026-06-01", period_end="2026-09-01",
                                    ticket_specs=None, **kwargs):
    """PER_UNIT contract HARVESTING + N verified tickets + DRAFT settlement."""
    base = setup_contract_harvesting(**kwargs)
    if ticket_specs is None:
        ticket_specs = [
            {"scaled_date": "2026-06-20", "log_count": 10},
            {"scaled_date": "2026-06-21", "log_count": 10},
            {"scaled_date": "2026-06-22", "log_count": 5},
        ]
    tickets = [add_verified_ticket(base, **spec) for spec in ticket_specs]
    fh = base["forester_headers"]
    settlement = get_success_data(api_client.create_settlement(
        create_settlement_payload(contract_id=base["contract"]["id"],
                                  kind="PER_UNIT_PERIOD",
                                  period_start=period_start, period_end=period_end),
        fh,
    ))
    base["tickets"] = tickets
    base["settlement"] = settlement
    return base


# ---------------------------------------------------------------------------
# Tier 7: reforestation + survival surveys
# ---------------------------------------------------------------------------


def setup_obligation_planted(planted_date="2027-03-01", seedlings_planted=1000, **kwargs):
    """Obligation PLANTED with the given seedling count."""
    base = setup_contract_harvest_complete(**kwargs)
    get_success_data(api_client.set_clock({"to_iso8601": f"{planted_date}T00:00:00Z"}, ADMIN))
    obligation = get_success_data(api_client.record_planting(
        base["obligation"]["id"],
        create_record_planting_payload(planted_date=planted_date,
                                       seedlings_planted=seedlings_planted),
        base["contractor_headers"],
    ))
    base["obligation"] = obligation
    return base


def setup_survey_recorded(survey_date="2028-04-01", live_seedlings_count=900, **kwargs):
    """Obligation SURVEYED with a RECORDED survey."""
    base = setup_obligation_planted(**kwargs)
    get_success_data(api_client.set_clock({"to_iso8601": f"{survey_date}T00:00:00Z"}, ADMIN))
    survey = get_success_data(api_client.create_survey(
        base["obligation"]["id"],
        create_survey_payload(survey_date=survey_date,
                              live_seedlings_count=live_seedlings_count),
        base["forester_headers"],
    ))
    base["survey"] = survey
    base["obligation"] = get_success_data(api_client.get_obligation(
        base["obligation"]["id"], base["forester_headers"]
    ))
    return base


# ---------------------------------------------------------------------------
# Tier 8: carbon valuations
# ---------------------------------------------------------------------------


def setup_carbon_valuation(valuation_overrides=None):
    """Tract OPEN + one VALUED carbon valuation. Returns dict."""
    base = setup_tract_and_stand()
    fh = base["forester_headers"]
    tract = base["tract"]
    valuation = get_success_data(api_client.create_carbon_valuation(
        create_carbon_valuation_payload(tract_id=tract["id"],
                                        expected_tract_version=tract["version"],
                                        **(valuation_overrides or {})),
        fh,
    ))
    base["valuation"] = valuation
    return base
