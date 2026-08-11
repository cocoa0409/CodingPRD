"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared endpoints
(the harness restarts the server before every test, so each test starts empty).
Setup calls use get_success_data() so a setup failure surfaces as a clear error.

Common vocabulary:
- trustee headers default to the case's assigned trustee_user_id ("trust-0001").
- creditor calls that are ownership-gated use make_creditor_headers(creditor_id).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_case_payload, create_creditor_payload, file_claim_payload,
    create_objection_payload, create_asset_payload, create_sale_payload,
    create_avoidance_action_payload, create_fee_application_payload,
)
from .test_users import TEST_USERS, make_trustee_headers, make_creditor_headers

TRUSTEE = TEST_USERS["trustee_headers"]
CLERK = TEST_USERS["clerk_headers"]
COURT = TEST_USERS["court_headers"]

DEFAULT_FILED_ON = "2026-01-15T00:00:00Z"
DEFAULT_BAR_DATE = "2026-06-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 0: primitive creators
# ---------------------------------------------------------------------------

def create_creditor(legal_name="Test Creditor", creditor_ref="CR-0001",
                    insider=None, contact_email="creditor@example.com") -> dict:
    payload = create_creditor_payload(legal_name=legal_name, creditor_ref=creditor_ref,
                                      contact_email=contact_email)
    if insider is not None:
        payload["insider"] = insider
    resp = api_client.create_creditor(payload, CLERK)
    return get_success_data(resp)


def create_case(case_number="26-00001", trustee_user_id="trust-0001",
                filed_on=DEFAULT_FILED_ON, debtor_name=None, district=None,
                objection_window_days=None,
                scheduled_unsecured_total_cents=None) -> dict:
    overrides = {}
    if debtor_name is not None:
        overrides["debtor_name"] = debtor_name
    if district is not None:
        overrides["district"] = district
    if objection_window_days is not None:
        overrides["objection_window_days"] = objection_window_days
    if scheduled_unsecured_total_cents is not None:
        overrides["scheduled_unsecured_total_cents"] = scheduled_unsecured_total_cents
    payload = create_case_payload(case_number=case_number,
                                  trustee_user_id=trustee_user_id,
                                  filed_on=filed_on, **overrides)
    resp = api_client.create_case(payload, CLERK)
    return get_success_data(resp)


def create_asset(case_id, description="Test asset", scheduled_value_cents=100000,
                 exempt=None, encumbered_claim_id=None) -> dict:
    overrides = {}
    if exempt is not None:
        overrides["exempt"] = exempt
    if encumbered_claim_id is not None:
        overrides["encumbered_claim_id"] = encumbered_claim_id
    payload = create_asset_payload(description=description,
                                   scheduled_value_cents=scheduled_value_cents,
                                   **overrides)
    resp = api_client.create_asset(case_id, payload, TRUSTEE)
    return get_success_data(resp)


def file_claim(case_id, creditor_id, received_at="2026-02-01T00:00:00Z",
               filed_amount_cents=100000, priority_class="GENERAL_UNSECURED",
               secured_by_asset_id=None, as_clerk=False) -> dict:
    """File a proof of claim. Default channel: the creditor files its own claim
    (X-User-ID == creditor_id, per PRD §2.1 ownership semantics)."""
    overrides = {}
    if secured_by_asset_id is not None:
        overrides["secured_by_asset_id"] = secured_by_asset_id
    payload = file_claim_payload(creditor_id=creditor_id, received_at=received_at,
                                 filed_amount_cents=filed_amount_cents,
                                 priority_class=priority_class, **overrides)
    headers = CLERK if as_clerk else make_creditor_headers(creditor_id)
    resp = api_client.file_claim(case_id, payload, headers)
    return get_success_data(resp)


def get_case(case_id) -> dict:
    return get_success_data(api_client.get_case(case_id, TRUSTEE))


def get_case_version(case_id) -> int:
    return get_case(case_id)["version"]


def set_clock(to_iso8601: str):
    get_success_data(api_client.set_clock(to_iso8601, COURT))


def review_claim(claim_id) -> dict:
    return get_success_data(api_client.review_claim(claim_id, TRUSTEE))


def allow_claim(claim_id) -> dict:
    return get_success_data(api_client.allow_claim(claim_id, TRUSTEE))


def review_and_allow_claim(claim_id) -> dict:
    review_claim(claim_id)
    return allow_claim(claim_id)


def object_to_claim(claim_id, grounds="AMOUNT_DISPUTED",
                    proposed_allowed_amount_cents=0,
                    proposed_priority_class="GENERAL_UNSECURED") -> dict:
    payload = create_objection_payload(
        grounds=grounds,
        proposed_allowed_amount_cents=proposed_allowed_amount_cents,
        proposed_priority_class=proposed_priority_class)
    resp = api_client.create_objection(claim_id, payload, TRUSTEE)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: case posture progression
# ---------------------------------------------------------------------------

def setup_case_in_claims_administration(case_number="26-00001",
                                        objection_window_days=None,
                                        scheduled_value_cents=100000,
                                        filed_on=DEFAULT_FILED_ON,
                                        bar_date=DEFAULT_BAR_DATE,
                                        creditor_ref="CR-0001",
                                        asset=True) -> dict:
    """Case driven OPEN -> ASSET_INVESTIGATION -> CLAIMS_ADMINISTRATION.

    Returns {"case", "creditor", "asset" (or None), "trustee"}.
    """
    creditor = create_creditor(creditor_ref=creditor_ref)
    case = create_case(case_number=case_number, filed_on=filed_on,
                       objection_window_days=objection_window_days)
    asset_row = None
    if asset:
        asset_row = create_asset(case["id"], scheduled_value_cents=scheduled_value_cents)
    get_success_data(api_client.begin_investigation(case["id"], TRUSTEE))
    case = get_success_data(api_client.set_bar_date(case["id"], bar_date, CLERK))
    return {"case": case, "creditor": creditor, "asset": asset_row,
            "trustee": TRUSTEE}


def setup_case_in_liquidation(case_number="26-00002",
                              objection_window_days=1,
                              scheduled_value_cents=100000,
                              claim_amount_cents=100000,
                              with_claim=True,
                              bar_date=DEFAULT_BAR_DATE) -> dict:
    """CLAIMS_ADMINISTRATION + (optionally) one ALLOWED claim + clock past the
    bar date -> LIQUIDATION. Returns the setup dict with "claim"."""
    ctx = setup_case_in_claims_administration(
        case_number=case_number, objection_window_days=objection_window_days,
        scheduled_value_cents=scheduled_value_cents, bar_date=bar_date)
    claim = None
    if with_claim:
        claim = file_claim(ctx["case"]["id"], ctx["creditor"]["id"],
                           filed_amount_cents=claim_amount_cents)
        review_and_allow_claim(claim["id"])
    set_clock("2026-06-02T00:00:00Z")
    ctx["case"] = get_success_data(api_client.begin_liquidation(ctx["case"]["id"], TRUSTEE))
    ctx["claim"] = claim
    return ctx


def setup_case_with_consummated_sale(case_number="26-00003",
                                     objection_window_days=1,
                                     scheduled_value_cents=150000,
                                     claim_amount_cents=100000,
                                     hammer_price_cents=100000,
                                     sale_costs_cents=0,
                                     approve_clock="2026-06-02T12:00:00Z",
                                     consummate_clock="2026-06-04T00:00:00Z") -> dict:
    """LIQUIDATION + asset MARKED_FOR_SALE + sale APPROVED + CONSUMMATED
    (proceeds POSTED; estate cash credited with net proceeds)."""
    ctx = setup_case_in_liquidation(
        case_number=case_number, objection_window_days=objection_window_days,
        scheduled_value_cents=scheduled_value_cents,
        claim_amount_cents=claim_amount_cents)
    case_id = ctx["case"]["id"]
    asset_id = ctx["asset"]["id"]
    get_success_data(api_client.mark_asset_for_sale(asset_id, TRUSTEE))
    sale = get_success_data(api_client.create_sale(
        case_id, create_sale_payload(asset_id=asset_id,
                                     hammer_price_cents=hammer_price_cents,
                                     sale_costs_cents=sale_costs_cents), TRUSTEE))
    set_clock(approve_clock)
    get_success_data(api_client.approve_sale(sale["id"], COURT))
    set_clock(consummate_clock)
    sale = get_success_data(api_client.consummate_sale(sale["id"], TRUSTEE))
    ctx["sale"] = sale
    ctx["case"] = get_case(case_id)
    return ctx


def setup_case_in_distribution(case_number="26-00004",
                               objection_window_days=1,
                               scheduled_value_cents=150000,
                               claim_amount_cents=100000,
                               hammer_price_cents=100000,
                               sale_costs_cents=0) -> dict:
    """Full walk to DISTRIBUTION posture with sale proceeds posted."""
    ctx = setup_case_with_consummated_sale(
        case_number=case_number, objection_window_days=objection_window_days,
        scheduled_value_cents=scheduled_value_cents,
        claim_amount_cents=claim_amount_cents,
        hammer_price_cents=hammer_price_cents, sale_costs_cents=sale_costs_cents)
    ctx["case"] = get_success_data(api_client.begin_distribution(ctx["case"]["id"], TRUSTEE))
    return ctx


# ---------------------------------------------------------------------------
# Tier 2/3: plans, dividends, fees
# ---------------------------------------------------------------------------

def propose_plan(case_id) -> dict:
    return get_success_data(api_client.create_plan(case_id, TRUSTEE))


def confirm_plan(plan_id, case_id) -> dict:
    """Confirm with the case's current version (OCC, PRD §2.9)."""
    version = get_case_version(case_id)
    return get_success_data(api_client.confirm_plan(plan_id, version, COURT))


def get_plan_dividends(plan_id) -> list:
    """Return the plan's dividend rows as a plain list."""
    resp = api_client.list_plan_dividends(plan_id, TRUSTEE)
    body = resp.json()
    return body["data"]


def dividend_for_claim(plan_id, claim_id) -> list:
    """All dividend rows of the plan paying the given claim (a claim can appear
    in two classes when a secured deficiency spills into GENERAL_UNSECURED)."""
    resp = api_client.list_plan_dividends(plan_id, TRUSTEE,
                                          params={"claim_id": claim_id})
    return resp.json()["data"]


def setup_confirmed_plan(case_number="26-00005", objection_window_days=1,
                         scheduled_value_cents=150000, claim_amount_cents=100000,
                         hammer_price_cents=100000, sale_costs_cents=0) -> dict:
    """DISTRIBUTION + plan PROPOSED + CONFIRMED (dividends materialized)."""
    ctx = setup_case_in_distribution(
        case_number=case_number, objection_window_days=objection_window_days,
        scheduled_value_cents=scheduled_value_cents,
        claim_amount_cents=claim_amount_cents,
        hammer_price_cents=hammer_price_cents, sale_costs_cents=sale_costs_cents)
    plan = propose_plan(ctx["case"]["id"])
    plan = confirm_plan(plan["id"], ctx["case"]["id"])
    ctx["plan"] = plan
    ctx["dividends"] = get_plan_dividends(plan["id"])
    ctx["case"] = get_case(ctx["case"]["id"])
    return ctx


def file_fee_application(case_id, applicant_role="COUNSEL",
                         requested_amount_cents=100000,
                         commission_basis=None) -> dict:
    """File a fee application with the case's current version (OCC)."""
    payload = create_fee_application_payload(
        applicant_role=applicant_role,
        requested_amount_cents=requested_amount_cents)
    if commission_basis is not None:
        payload["commission_basis"] = commission_basis
    payload["expected_case_version"] = get_case_version(case_id)
    headers = TRUSTEE if applicant_role == "TRUSTEE" else CLERK
    resp = api_client.create_fee_application(case_id, payload, headers)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 4: avoidance actions
# ---------------------------------------------------------------------------

def create_demanded_action(case_id, creditor_id,
                           transfer_date="2025-12-01T00:00:00Z",
                           transfer_amount_cents=100000,
                           demand_amount_cents=100000,
                           action_type="PREFERENCE_547") -> dict:
    """Avoidance action walked IDENTIFIED -> ANALYZED -> DEMANDED."""
    payload = create_avoidance_action_payload(
        transferee_creditor_id=creditor_id, transfer_date=transfer_date,
        transfer_amount_cents=transfer_amount_cents, action_type=action_type,
        demand_amount_cents=demand_amount_cents)
    action = get_success_data(api_client.create_avoidance_action(case_id, payload, TRUSTEE))
    get_success_data(api_client.analyze_action(action["id"], TRUSTEE))
    action = get_success_data(api_client.demand_action(action["id"], TRUSTEE))
    return action


def create_judgment_action(case_id, creditor_id,
                           transfer_date="2025-12-01T00:00:00Z",
                           transfer_amount_cents=100000,
                           demand_amount_cents=100000) -> dict:
    """Avoidance action walked to JUDGMENT (recovery deposit POSTED)."""
    action = create_demanded_action(
        case_id, creditor_id, transfer_date=transfer_date,
        transfer_amount_cents=transfer_amount_cents,
        demand_amount_cents=demand_amount_cents)
    return get_success_data(api_client.enter_judgment(action["id"], COURT))
