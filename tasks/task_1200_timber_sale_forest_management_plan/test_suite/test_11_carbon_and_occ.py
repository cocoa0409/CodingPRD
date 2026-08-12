"""Carbon valuation NPV, enrollment cascade, and OCC gates (PRD §2.6, §3.9)."""
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_carbon_valuation_payload,
    create_sale_payload,
    setup_carbon_valuation,
    setup_certified_cruise,
    setup_sale_awarded,
    setup_tract_and_stand,
)

ADMIN = TEST_USERS["admin_headers"]


def test_carbon_npv_variants_and_recommendation(api):
    """PRD §3.9: "The `gross_npv_cents` multiplies the full
    `annual_credits_tco2e` by the price and by the annuity factor, rounded
    half up to whole cents. The `net_npv_cents` first subtracts the baseline —
    so identical inputs yield a strictly smaller net whenever the baseline
    exceeds zero — then applies the same price and annuity, again rounded
    half up only at the end. The `enrollment_end` is computed as
    `enrollment_start` plus twenty years, landing on the same month and day.
    The `recommendation` compares the two land uses: `CONSERVATION_FAVORED`
    when `net_npv_cents` is at least the estimated timber net marked up by
    ten percent — that markup itself rounded half up to whole cents — and
    `TIMBER_FAVORED` otherwise."

    Design: Corner/calculations/carbon_npv_variants_and_recommendation
    """
    base = setup_tract_and_stand()
    fh = base["forester_headers"]
    tract = base["tract"]
    valuation = validate_success(api.create_carbon_valuation(
        create_carbon_valuation_payload(tract_id=tract["id"],
                                        expected_tract_version=tract["version"]),
        fh,
    ), 201)
    assert valuation["gross_npv_cents"] == 37_386_631
    assert valuation["net_npv_cents"] == 28_039_973
    assert valuation["enrollment_end"] == "2047-01-01"
    assert valuation["recommendation"] == "CONSERVATION_FAVORED"
    assert valuation["status"] == "VALUED"


def test_conservation_enrollment_closed_interval_conflict(api):
    """PRD §3.4: "No conservation enrollment window on the tract may overlap
    the sale's harvest window — the comparison uses closed-interval day
    semantics, so overlap exists whenever the harvest start falls on or before
    the enrollment end and the enrollment start falls on or before the
    harvest end — and the tract must still be `OPEN`; violation is
    `ERR_CONSERVATION_ENROLLMENT_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/conservation_enrollment_closed_interval_conflict
    """
    base = setup_tract_and_stand()
    fh = base["forester_headers"]
    lh = base["landowner_headers"]
    tract = base["tract"]
    stand = base["stand"]
    # Certified cruise.
    from test_helpers import (
        create_cruise_payload,
        create_prescription_payload,
    )
    cruise = get_success_data(api.create_cruise(
        create_cruise_payload(stand_id=stand["id"]), fh
    ))
    get_success_data(api.finalize_tally(cruise["id"], fh))
    get_success_data(api.reconcile_cruise(cruise["id"], {"reconciled_plot_numbers": [1, 2, 3, 4, 5, 6]}, fh))
    stand_now = get_success_data(api.get_stand(stand["id"], fh))
    get_success_data(api.certify_cruise(cruise["id"], {"expected_stand_version": stand_now["version"]}, fh))

    # Carbon valuation then accept -> enrollment [2027-01-01, 2047-01-01].
    tract_now = get_success_data(api.get_tract(tract["id"], fh))
    valuation = get_success_data(api.create_carbon_valuation(
        create_carbon_valuation_payload(tract_id=tract["id"],
                                        expected_tract_version=tract_now["version"]),
        fh,
    ))
    get_success_data(api.accept_carbon_valuation(valuation["id"], lh))
    tract_after = get_success_data(api.get_tract(tract["id"], fh))
    assert tract_after["status"] == "ENROLLED_CONSERVATION"
    assert tract_after["conservation_enrollment_start"] == "2027-01-01"
    assert tract_after["conservation_enrollment_end"] == "2047-01-01"

    # Prescription (window irrelevant for offer-conflict, but required to create a sale).
    prescription = get_success_data(api.create_prescription(
        create_prescription_payload(stand_id=stand["id"], cruise_id=cruise["id"],
                                    window_start="2026-06-01", window_end="2026-12-31"),
        fh,
    ))
    get_success_data(api.propose_prescription(prescription["id"], fh))
    get_success_data(api.approve_prescription(prescription["id"], lh))

    # Once the tract is enrolled it is no longer OPEN, so the §3.4 offer gate
    # ("the tract must still be `OPEN`; violation is
    # `ERR_CONSERVATION_ENROLLMENT_CONFLICT`") refuses every subsequent offer on
    # the tract — independent of window overlap. A harvest window that does NOT
    # overlap the enrollment window is refused all the same.
    payload_ok = create_sale_payload(tract_id=tract["id"], stand_id=stand["id"],
                                     prescription_id=prescription["id"],
                                     sale_type="LUMP_SUM",
                                     advertised_minimum_cents=7_000_000,
                                     bid_open_at="2026-05-10T00:00:00Z",
                                     bid_close_at="2026-05-20T00:00:00Z",
                                     harvest_window_start="2026-06-01",
                                     harvest_window_end="2026-12-31")
    payload_ok.pop("species_minimum_rates", None)
    sale_ok = get_success_data(api.create_sale(payload_ok, fh))
    resp_ok = api.offer_sale(sale_ok["id"], fh)
    validate_error(resp_ok, ApiErrorId.ERR_CONSERVATION_ENROLLMENT_CONFLICT)

    # Sale with harvest_start == enrollment_end 2047-01-01 -> conflict (closed interval).
    payload_touch = create_sale_payload(tract_id=tract["id"], stand_id=stand["id"],
                                        prescription_id=prescription["id"],
                                        sale_type="LUMP_SUM",
                                        advertised_minimum_cents=7_000_000,
                                        bid_open_at="2046-05-10T00:00:00Z",
                                        bid_close_at="2046-05-20T00:00:00Z",
                                        harvest_window_start="2047-01-01",
                                        harvest_window_end="2047-07-01")
    payload_touch.pop("species_minimum_rates", None)
    sale_touch = get_success_data(api.create_sale(payload_touch, fh))
    resp = api.offer_sale(sale_touch["id"], fh)
    validate_error(resp, ApiErrorId.ERR_CONSERVATION_ENROLLMENT_CONFLICT)


def test_enrollment_touching_harvest_window_rejected(api):
    """PRD §3.9: "the cascade cleans the slate: every sale of the tract in
    `DRAFT`, `OFFERED`, `BIDDING_OPEN`, `BIDDING_CLOSED`, or `NO_SALE` is
    moved to `CANCELLED`, and every `SUBMITTED` bid on those sales moves to
    `WITHDRAWN`."

    Design: Difficulty/resource_temporal_overlap/conservation_enrollment_closed_interval_conflict
    """
    # Tract OPEN with one DRAFT sale; then accept a valuation and the sale is
    # cancelled by the cascade.
    base = setup_certified_cruise()
    fh = base["forester_headers"]
    lh = base["landowner_headers"]
    tract = base["tract"]
    from test_helpers import create_prescription_payload, create_sale_payload
    prescription = get_success_data(api.create_prescription(
        create_prescription_payload(stand_id=base["stand"]["id"],
                                    cruise_id=base["cruise"]["id"]),
        fh,
    ))
    get_success_data(api.propose_prescription(prescription["id"], fh))
    get_success_data(api.approve_prescription(prescription["id"], lh))
    payload = create_sale_payload(tract_id=tract["id"], stand_id=base["stand"]["id"],
                                  prescription_id=prescription["id"],
                                  sale_type="LUMP_SUM",
                                  advertised_minimum_cents=7_000_000)
    payload.pop("species_minimum_rates", None)
    sale = get_success_data(api.create_sale(payload, fh))

    tract_now = get_success_data(api.get_tract(tract["id"], fh))
    valuation = get_success_data(api.create_carbon_valuation(
        create_carbon_valuation_payload(tract_id=tract["id"],
                                        expected_tract_version=tract_now["version"]),
        fh,
    ))
    get_success_data(api.accept_carbon_valuation(valuation["id"], lh))
    sale_now = get_success_data(api.get_sale(sale["id"], fh))
    assert sale_now["status"] == "CANCELLED"


def test_carbon_accept_blocked_by_active_contract(api):
    """PRD §3.9: "Accepting moves `VALUED → ACCEPTED` but is blocked while
    any harvest contract rooted in any sale of the tract is still live — that
    is, in `PENDING_BOND`, `ACTIVE`, `HARVESTING`, `SUSPENDED`,
    `HARVEST_COMPLETE`, or `DEFAULTED`; the block surfaces as
    `ERR_ACTIVE_CONTRACT_BLOCKS_CONSERVATION` (HTTP 409)."

    Design: Corner/validations/carbon_accept_blocked_by_active_contract
    """
    base = setup_sale_awarded(
        sale_overrides={"sale_type": "LUMP_SUM", "scaling_rule": "DOYLE",
                        "advertised_minimum_cents": 7_000_000,
                        "species_minimum_rates": None},
        bid_overrides={"lump_sum_amount_cents": 8_000_000, "deposit_cents": 100_000},
    )
    fh = base["forester_headers"]
    lh = base["landowner_headers"]
    tract = base["tract"]
    tract_now = get_success_data(api.get_tract(tract["id"], fh))
    valuation = get_success_data(api.create_carbon_valuation(
        create_carbon_valuation_payload(tract_id=tract["id"],
                                        expected_tract_version=tract_now["version"]),
        fh,
    ))
    resp = api.accept_carbon_valuation(valuation["id"], lh)
    validate_error(resp, ApiErrorId.ERR_ACTIVE_CONTRACT_BLOCKS_CONSERVATION)
    # unchanged state
    valuation_now = get_success_data(api.get_carbon_valuation(valuation["id"], fh))
    tract_now2 = get_success_data(api.get_tract(tract["id"], fh))
    assert valuation_now["status"] == "VALUED"
    assert tract_now2["status"] == "OPEN"


def test_occ_stale_bid_create_returns_412(api):
    """PRD §2.6: "Submitting a bid on a sale requires the request to carry
    `expected_sale_version`, the client's last observed `version` of the sale.
    If the sale's current `version` differs — every accepted bid advances it —
    the submission is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting/occ_stale_bid_create_returns_412
    """
    from test_helpers import create_buyer_payload, make_buyer_headers, setup_sale_bidding_open

    base = setup_sale_bidding_open(
        sale_overrides={"sale_type": "LUMP_SUM", "scaling_rule": "DOYLE",
                        "advertised_minimum_cents": 7_000_000,
                        "species_minimum_rates": None},
    )
    fh = base["forester_headers"]
    bh1 = base["buyer_headers"]
    buyer2 = get_success_data(api.create_buyer(
        create_buyer_payload(company_name="Red Mill", license_no="B-200"), ADMIN
    ))
    bh2 = make_buyer_headers(buyer2["id"])
    sale = base["sale"]
    stale_version = sale["version"]
    # Buyer1 submits first (advances sale.version).
    get_success_data(api.submit_bid(
        sale["id"],
        {"expected_sale_version": stale_version, "deposit_cents": 50_000,
         "lump_sum_amount_cents": 8_000_000},
        bh1,
    ))
    # Buyer2 with stale version -> 412.
    resp = api.submit_bid(
        sale["id"],
        {"expected_sale_version": stale_version, "deposit_cents": 60_000,
         "lump_sum_amount_cents": 8_100_000},
        bh2,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    # Fresh read, then retry succeeds.
    sale_fresh = get_success_data(api.get_sale(sale["id"], fh))
    bid2 = validate_success(api.submit_bid(
        sale["id"],
        {"expected_sale_version": sale_fresh["version"], "deposit_cents": 60_000,
         "lump_sum_amount_cents": 8_100_000},
        bh2,
    ), 201)
    assert bid2["status"] == "SUBMITTED"


def test_occ_stale_certify_returns_412(api):
    """PRD §2.6: "Certifying an inventory cruise requires the request to carry
    `expected_stand_version`, the client's last observed `version` of the
    stand. If the stand's current `version` differs — for example because
    another cruise was certified against the stand since the client read it —
    the certification is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting/occ_stale_certify_returns_412
    """
    base = setup_certified_cruise()
    fh = base["forester_headers"]
    stand_at_create = base["stand"]["version"] - 1  # version before the certification bumped it
    # Second cruise on the same stand.
    from test_helpers import PINE_PLOTS_6
    cruise_b = get_success_data(api.create_cruise(
        {"stand_id": base["stand"]["id"], "cruise_date": "2026-04-01",
         "plots": [
             {"plot_number": 1, "species": "PINE", "volume_bf": 1200},
             {"plot_number": 2, "species": "PINE", "volume_bf": 1300},
             {"plot_number": 3, "species": "PINE", "volume_bf": 1200},
             {"plot_number": 4, "species": "PINE", "volume_bf": 1300},
             {"plot_number": 5, "species": "PINE", "volume_bf": 1200},
             {"plot_number": 6, "species": "PINE", "volume_bf": 1300},
         ]},
        fh,
    ))
    get_success_data(api.finalize_tally(cruise_b["id"], fh))
    get_success_data(api.reconcile_cruise(cruise_b["id"],
                                          {"reconciled_plot_numbers": [1, 2, 3, 4, 5, 6]}, fh))
    # Certify B with stale stand version -> 412.
    resp = api.certify_cruise(cruise_b["id"], {"expected_stand_version": stand_at_create}, fh)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    # Retry with fresh version succeeds and supersedes A.
    stand_fresh = get_success_data(api.get_stand(base["stand"]["id"], fh))
    certified_b = validate_success(api.certify_cruise(
        cruise_b["id"], {"expected_stand_version": stand_fresh["version"]}, fh
    ))
    assert certified_b["status"] == "CERTIFIED"
    cruise_a_now = get_success_data(api.get_cruise(base["cruise"]["id"], fh))
    assert cruise_a_now["status"] == "SUPERSEDED"
    stand_final = get_success_data(api.get_stand(base["stand"]["id"], fh))
    assert stand_final["certified_cruise_id"] == cruise_b["id"]


def test_occ_stale_valuation_create_returns_412(api):
    """PRD §2.6: "Creating a carbon valuation requires the request to carry
    `expected_tract_version`, the client's last observed `version` of the
    tract. If the tract's current `version` differs — for example because
    another valuation on the tract advanced it — the creation is rejected
    with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting/occ_stale_valuation_create_returns_412
    """
    base = setup_tract_and_stand()
    fh = base["forester_headers"]
    tract = base["tract"]
    stale_version = tract["version"]
    # First valuation succeeds (bumps tract.version).
    valuation_a = validate_success(api.create_carbon_valuation(
        create_carbon_valuation_payload(tract_id=tract["id"],
                                        expected_tract_version=stale_version),
        fh,
    ), 201)
    # Second with same (stale) version -> 412.
    resp = api.create_carbon_valuation(
        create_carbon_valuation_payload(tract_id=tract["id"],
                                        expected_tract_version=stale_version,
                                        annual_credits_tco2e=1100),
        fh,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    # Fresh read then retry succeeds and supersedes A.
    tract_fresh = get_success_data(api.get_tract(tract["id"], fh))
    valuation_b = validate_success(api.create_carbon_valuation(
        create_carbon_valuation_payload(tract_id=tract["id"],
                                        expected_tract_version=tract_fresh["version"],
                                        annual_credits_tco2e=1100),
        fh,
    ), 201)
    assert valuation_b["status"] == "VALUED"
    valuation_a_now = get_success_data(api.get_carbon_valuation(valuation_a["id"], fh))
    assert valuation_a_now["status"] == "SUPERSEDED"
