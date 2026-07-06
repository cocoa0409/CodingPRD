"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface
as clear "setup failed" errors rather than confusing assertion failures.

The dominant pipeline in this domain is:
    account -> rfp -> service-areas -> bid-estimate -> price -> proposal ->
    send -> accept -> contract -> sign -> (startup plan) -> crew -> mark-ready
    -> go-live  (=> SERVICING contract, ACTIVE billing, ACTIVE_CUSTOMER account)

Reference monetary anchors used by tests:
  * STANDARD area set (two MEDIUM 10000@5/wk + one HEAVY 4000@5/wk), LOADED,
    base_wage 1800, margin 0.20:
      monthly_labor_hours = 187.62, total_cost_cents = 554042,
      base_bid_cents = 692553, proposal monthly_price_cents = 671776.
  * SINGLE area (one LIGHT 4000@1/wk), LOADED, base_wage 1800, margin 0.20:
      contract monthly_value_cents = 29976.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_account_payload, create_rfp_payload, create_site_contact_payload,
    create_walkthrough_payload, create_service_area_payload,
    create_bid_estimate_payload, create_proposal_payload, create_contract_payload,
    create_crew_payload, create_crew_shift_payload, create_supply_budget_payload,
    create_requisition_payload, create_renewal_cycle_payload,
)
from .test_users import TEST_USERS, make_account_manager_headers

# The user id threaded as the AccountManager identity for ownership-gated calls.
AM_USER_ID = "test-account-manager-1"

_SALES = TEST_USERS["sales_rep_headers"]
_BID = TEST_USERS["bid_estimator_headers"]
_OPS = TEST_USERS["operations_manager_headers"]
_AM = make_account_manager_headers(AM_USER_ID)

# The "standard" area set that produces the canonical anchor figures.
STANDARD_AREAS = [
    {"label": "Floor 1", "sqft": 10000, "soil_level": "MEDIUM", "frequency_per_week": 5},
    {"label": "Floor 2", "sqft": 10000, "soil_level": "MEDIUM", "frequency_per_week": 5},
    {"label": "Restrooms", "sqft": 4000, "soil_level": "HEAVY", "frequency_per_week": 5},
]
# A small single-area set used where a low contract value is needed.
SINGLE_LIGHT_AREA = [
    {"label": "Lobby", "sqft": 4000, "soil_level": "LIGHT", "frequency_per_week": 1},
]


# ─── Primitive builders ───────────────────────────────────────────────
def create_account(legal_name="Test Account", industry="OFFICE"):
    """Create a PROSPECT account. Returns the account dict."""
    return get_success_data(api_client.create_account(
        create_account_payload(legal_name=legal_name, industry=industry), _SALES))


def create_rfp(account_id, **overrides):
    """Create an OPEN RFP under the account."""
    return get_success_data(api_client.create_rfp(
        account_id, create_rfp_payload(**overrides), _SALES))


def add_service_areas(account_id, rfp_id, areas):
    """Add a list of service-area payload dicts; returns list of created areas."""
    created = []
    for area in areas:
        created.append(get_success_data(api_client.create_service_area(
            account_id, rfp_id, create_service_area_payload(**area), _BID)))
    return created


def create_and_price_bid(account_id, rfp_id, loading_method="LOADED",
                         base_wage_cents=1800, target_margin_pct=0.20):
    """Create a draft bid estimate and price it. Returns the PRICED estimate."""
    bid = get_success_data(api_client.create_bid_estimate(
        account_id, rfp_id,
        create_bid_estimate_payload(loading_method=loading_method,
                                    base_wage_cents=base_wage_cents,
                                    target_margin_pct=target_margin_pct),
        _BID))
    return get_success_data(api_client.price_bid_estimate(account_id, rfp_id, bid["id"], _BID))


# ─── Tier 2/3: Pipeline composites ────────────────────────────────────
def setup_priced_bid(areas=None, loading_method="LOADED", base_wage_cents=1800,
                     target_margin_pct=0.20, legal_name="Bid Co"):
    """account -> rfp -> service-areas -> PRICED bid.

    Returns (account, rfp, bid).
    """
    areas = STANDARD_AREAS if areas is None else areas
    acct = create_account(legal_name=legal_name)
    rfp = create_rfp(acct["id"], estimated_total_sqft=24000)
    add_service_areas(acct["id"], rfp["id"], areas)
    bid = create_and_price_bid(acct["id"], rfp["id"], loading_method,
                               base_wage_cents, target_margin_pct)
    return acct, rfp, bid


def setup_draft_proposal(areas=None, loading_method="LOADED", base_wage_cents=1800,
                         target_margin_pct=0.20, legal_name="Prop Co"):
    """...PRICED bid -> create proposal (DRAFT). Returns (account, rfp, bid, proposal)."""
    acct, rfp, bid = setup_priced_bid(areas, loading_method, base_wage_cents,
                                      target_margin_pct, legal_name)
    prop = get_success_data(api_client.create_proposal(
        acct["id"], rfp["id"], create_proposal_payload(bid["id"]), _SALES))
    return acct, rfp, bid, prop


def setup_sent_proposal(areas=None, loading_method="LOADED", base_wage_cents=1800,
                        target_margin_pct=0.20, legal_name="Sent Co",
                        with_walkthrough=True):
    """...DRAFT proposal -> send (SENT, RFP PROPOSED).

    Per PRD §3.4, sending a proposal requires the parent opportunity to be in
    BIDDING ("its parent opportunity must be in BIDDING, otherwise
    ERR_INVALID_STATE"), and BIDDING is only reached by completing a walkthrough
    (PRD §3.2: completing the walkthrough "advances the opportunity from
    WALKTHROUGH_SCHEDULED to BIDDING"). So a site contact + scheduled + completed
    walkthrough are interposed by default so the RFP reaches BIDDING via the real
    path and the send actually succeeds.
    Returns (account, rfp, bid, proposal).
    """
    areas = STANDARD_AREAS if areas is None else areas
    acct = create_account(legal_name=legal_name)
    rfp = create_rfp(acct["id"], estimated_total_sqft=24000)
    if with_walkthrough:
        sc = get_success_data(api_client.create_site_contact(
            acct["id"], create_site_contact_payload(), _SALES))
        wt = get_success_data(api_client.create_walkthrough(
            acct["id"], rfp["id"], create_walkthrough_payload(sc["id"]), _SALES))
        api_client.complete_walkthrough(acct["id"], rfp["id"], wt["id"], _SALES)
    add_service_areas(acct["id"], rfp["id"], areas)
    bid = create_and_price_bid(acct["id"], rfp["id"], loading_method,
                               base_wage_cents, target_margin_pct)
    prop = get_success_data(api_client.create_proposal(
        acct["id"], rfp["id"], create_proposal_payload(bid["id"]), _SALES))
    api_client.send_proposal(acct["id"], rfp["id"], prop["id"], _SALES)
    prop = get_success_data(api_client.get_proposal(acct["id"], rfp["id"], prop["id"], _SALES))
    return acct, rfp, bid, prop


def setup_signed_contract(areas=None, legal_name="Sign Co", term_months=12):
    """Full pipeline through a SIGNED contract with a PLANNING startup plan.

    Returns (account, rfp, bid, proposal, contract, plan).
    """
    areas = SINGLE_LIGHT_AREA if areas is None else areas
    acct, rfp, bid, prop = setup_sent_proposal(areas=areas, legal_name=legal_name)
    api_client.accept_proposal(acct["id"], rfp["id"], prop["id"], _SALES)
    ctr = get_success_data(api_client.create_contract(
        acct["id"], create_contract_payload(prop["id"], term_months=term_months), _SALES))
    ctr = get_success_data(api_client.sign_contract(acct["id"], ctr["id"], _SALES))
    plans = get_success_data(api_client.list_startup_plans(acct["id"], _OPS))
    plan = plans[0]
    return acct, rfp, bid, prop, ctr, plan


def create_available_crew(name="Test Crew", weekly_capacity_hours=50):
    """Create an AVAILABLE crew. Returns the crew dict."""
    return get_success_data(api_client.create_crew(
        create_crew_payload(name=name, weekly_capacity_hours=weekly_capacity_hours), _OPS))


def setup_crewed_plan(areas=None, legal_name="Crew Co",
                      shift_start="2026-03-03T09:00:00Z", shift_end="2026-03-03T14:00:00Z",
                      crew_capacity=50):
    """Signed contract -> one assigned crew shift (plan CREWED, contract STARTUP).

    Returns (account, rfp, contract, plan, crew, shift).
    """
    areas = SINGLE_LIGHT_AREA if areas is None else areas
    acct, rfp, bid, prop, ctr, plan = setup_signed_contract(areas=areas, legal_name=legal_name)
    crew = create_available_crew(weekly_capacity_hours=crew_capacity)
    shift = get_success_data(api_client.assign_crew_shift(
        acct["id"], plan["id"],
        create_crew_shift_payload(crew["id"], start_at=shift_start, end_at=shift_end), _OPS))
    return acct, rfp, ctr, plan, crew, shift


def setup_servicing_contract(areas=None, legal_name="Svc Co"):
    """Full pipeline through SERVICING contract / ACTIVE billing / ACTIVE_CUSTOMER.

    Uses the SINGLE_LIGHT_AREA set by default (contract monthly_value 29976);
    pass areas=STANDARD_AREAS for the 671776 anchor.
    Returns (account, rfp, contract, plan).
    """
    areas = SINGLE_LIGHT_AREA if areas is None else areas
    acct, rfp, ctr, plan, crew, shift = setup_crewed_plan(areas=areas, legal_name=legal_name)
    api_client.mark_ready(acct["id"], plan["id"], _OPS)
    api_client.go_live(acct["id"], plan["id"], _OPS)
    ctr = get_success_data(api_client.get_contract(acct["id"], ctr["id"], _SALES))
    plan = get_success_data(api_client.get_startup_plan(acct["id"], plan["id"], _OPS))
    return acct, rfp, ctr, plan


# ─── Tier 4: Supply-budget composites ─────────────────────────────────
def setup_budget_with_requisition(total_cents=50000, amount_cents=20000,
                                   approve=False, legal_name="Budget Co"):
    """Servicing-or-later contract -> supply budget -> one requisition.

    Returns (account, contract, budget, requisition, budget_version_pre).
    The budget is created after the contract exists (PRD only requires a
    contract; this fixture leaves the contract in DRAFT to minimise steps).
    """
    acct, rfp, bid, prop = setup_sent_proposal(areas=SINGLE_LIGHT_AREA, legal_name=legal_name)
    api_client.accept_proposal(acct["id"], rfp["id"], prop["id"], _SALES)
    ctr = get_success_data(api_client.create_contract(
        acct["id"], create_contract_payload(prop["id"]), _SALES))
    budget = get_success_data(api_client.create_supply_budget(
        acct["id"], ctr["id"], create_supply_budget_payload(total_cents=total_cents), _OPS))
    budget_v = get_success_data(api_client.get_supply_budget(acct["id"], budget["id"], _OPS))["version"]
    req = get_success_data(api_client.create_requisition(
        acct["id"], budget["id"], create_requisition_payload(amount_cents=amount_cents), _OPS))
    if approve:
        api_client.approve_requisition(
            acct["id"], req["id"], {"expected_supply_budget_version": budget_v}, _OPS)
        budget_v = get_success_data(
            api_client.get_supply_budget(acct["id"], budget["id"], _OPS))["version"]
        req = get_success_data(api_client.get_requisition(acct["id"], req["id"], _OPS))
    return acct, ctr, budget, req, budget_v


# ─── Tier 5: Renewal composites ───────────────────────────────────────
def setup_offered_renewal(escalation_method="FLAT", areas=None, legal_name="Renew Co"):
    """Servicing contract -> renewal cycle (DRAFT) -> offer (OFFERED).

    Returns (account, contract, renewal_cycle, contract_version_after_offer).
    """
    areas = SINGLE_LIGHT_AREA if areas is None else areas
    acct, rfp, ctr, plan = setup_servicing_contract(areas=areas, legal_name=legal_name)
    rc = get_success_data(api_client.create_renewal_cycle(
        acct["id"], ctr["id"], create_renewal_cycle_payload(escalation_method), _AM))
    api_client.offer_renewal(acct["id"], rc["id"], _AM)
    rc = get_success_data(api_client.get_renewal_cycle(acct["id"], rc["id"], _AM))
    ctr_v = get_success_data(api_client.get_contract(acct["id"], ctr["id"], _AM))["version"]
    return acct, ctr, rc, ctr_v
