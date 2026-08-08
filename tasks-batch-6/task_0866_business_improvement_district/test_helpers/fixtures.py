"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared endpoints
(the harness restarts the server against an empty DB before each test). Setup calls use
get_success_data() (lenient) so a broken precondition surfaces as a clear "Setup failed".
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client as api
from .test_users import (
    TEST_USERS, make_property_owner_headers, make_ambassador_headers,
    make_board_member_headers,
)
from .factories import (
    create_bid_payload, create_parcel_payload, create_fiscal_year_payload,
    create_budget_payload, create_work_plan_line_payload,
    create_renewal_petition_payload, create_signature_payload,
    create_ambassador_payload, create_service_request_payload,
)

ADMIN = TEST_USERS["district_administrator_headers"]
BOARD = TEST_USERS["board_member_headers"]
COLLECTOR = TEST_USERS["tax_collector_headers"]


def _data(resp):
    return resp.json()["data"]


# --- Primitives -------------------------------------------------------------

def set_clock(iso, headers=ADMIN):
    return get_success_data(api.set_clock(iso, headers))


def new_bid(**overrides):
    return get_success_data(api.create_bid(create_bid_payload(**overrides), ADMIN))


def add_parcel(bid_id, **overrides):
    return get_success_data(api.create_parcel(bid_id, create_parcel_payload(**overrides), ADMIN))


def activate(bid_id):
    return get_success_data(api.activate_bid(bid_id, BOARD))


def new_fiscal_year(bid_id, **overrides):
    return get_success_data(api.create_fiscal_year(bid_id, create_fiscal_year_payload(**overrides), ADMIN))


def new_budget(fy_id, **overrides):
    return get_success_data(api.create_budget(fy_id, create_budget_payload(**overrides), ADMIN))


def add_line(budget_id, category, amount):
    return get_success_data(api.create_work_plan_line(
        budget_id, create_work_plan_line_payload(category=category, allocated_amount_cents=amount), ADMIN))


def propose(budget_id):
    return get_success_data(api.propose_budget(budget_id, ADMIN))


def adopt(budget_id):
    return get_success_data(api.adopt_budget(budget_id, BOARD))


def find_assessment(parcel_id, fy_id):
    resp = api.list_assessments(ADMIN, params={"parcel_id": parcel_id, "fiscal_year_id": fy_id})
    rows = _data(resp)
    assert rows, f"Setup failed: no assessment for parcel {parcel_id} in fy {fy_id}"
    return rows[0]


def account_for(assessment_id):
    resp = api.get_assessment_collection_account(assessment_id, COLLECTOR)
    rows = _data(resp)
    assert rows, f"Setup failed: no collection account for assessment {assessment_id}"
    return rows[0]


# --- Composite: single-parcel certified ------------------------------------

def setup_single_parcel_certified(clock="2027-06-01T00:00:00Z",
                                  assessment_due_date="2027-08-01T00:00:00Z",
                                  total_expenditure=4025000,
                                  other_revenue=0,
                                  bid_overrides=None):
    """Active single-parcel district; DRAFT->PROPOSED->ADOPTED budget so the parcel's
    assessment is CERTIFIED and a BILLED CollectionAccount exists.

    Canonical parcel weighted_base = 700; with total_expenditure=other_revenue-free
    4025000 the certified amount and billed amount are 4025000.
    Returns dict: bid, parcel, fy, budget, assessment, account.
    """
    set_clock(clock)
    bid = new_bid(**(bid_overrides or {}))
    parcel = add_parcel(bid["id"])
    activate(bid["id"])
    fy = new_fiscal_year(bid["id"], assessment_due_date=assessment_due_date)
    budget = new_budget(fy["id"], total_expenditure_cents=total_expenditure,
                        other_revenue_cents=other_revenue)
    add_line(budget["id"], "CLEAN", total_expenditure)
    propose(budget["id"])
    adopt(budget["id"])
    assessment = find_assessment(parcel["id"], fy["id"])
    account = account_for(assessment["id"])
    return {
        "bid": bid, "parcel": parcel, "fy": fy, "budget": budget,
        "assessment": assessment, "account": account,
    }


# --- Composite: single-parcel with a delinquent account --------------------

def setup_delinquent_account(delinquency_clock="2027-09-10T00:00:00Z"):
    """As setup_single_parcel_certified (due 2027-08-01), then advance the clock and
    mark the account DELINQUENT. At 2027-09-10 (due+40) penalty=402500, interest at
    that instant on 4025000 principal = 80500.
    Returns the same dict plus a refreshed `account`.
    """
    ctx = setup_single_parcel_certified()
    set_clock(delinquency_clock, COLLECTOR)
    acct = get_success_data(api.assess_delinquency(ctx["account"]["id"], COLLECTOR))
    ctx["account"] = acct
    return ctx


# --- Composite: single-parcel CERTIFIED then dispute at UNDER_REVIEW --------

def setup_dispute_under_review(paid_in_full=False):
    """Certified single parcel (4025000); optionally pay the account in full; then file a
    dispute (as the owning PropertyOwner) and move it SUBMITTED->UNDER_REVIEW.
    Returns dict with bid/parcel/fy/budget/assessment/account/dispute.
    """
    ctx = setup_single_parcel_certified()
    owner = make_property_owner_headers(ctx["parcel"]["id"])
    if paid_in_full:
        get_success_data(api.create_payment(ctx["account"]["id"], {"amount_cents": 4025000}, owner))
    dispute = get_success_data(api.create_dispute(
        ctx["assessment"]["id"], {"claimed_value_cents": 40000000, "requested_amount_cents": 3000000}, owner))
    dispute = get_success_data(api.transition_dispute(dispute["id"], {"action": "REVIEW"}, ADMIN))
    ctx["dispute"] = dispute
    return ctx


# --- Composite: two equal parcels, adopted (petition basis year) -----------

def setup_two_equal_parcels_adopted(clock="2027-06-01T00:00:00Z"):
    """Active district with weights value=0/frontage=0/sqft=1.0 and two COMMERCIAL parcels
    of building_sqft=10000 (weighted_base 10000 each). Budget total_expenditure=20000000
    adopted, so each parcel is CERTIFIED at 10000000. Returns bid, pa, pb, fy, budget.
    """
    set_clock(clock)
    bid = new_bid(assessment_weight_value=0, assessment_weight_frontage=0,
                  assessment_weight_sqft=1.0, min_assessment_cents=1,
                  max_assessment_cents=100000000)
    pa = add_parcel(bid["id"], apn="PA-1", owner_name="PA",
                    assessed_value_cents=0, linear_frontage_ft=0, building_sqft=10000)
    pb = add_parcel(bid["id"], apn="PB-1", owner_name="PB",
                    assessed_value_cents=0, linear_frontage_ft=0, building_sqft=10000)
    activate(bid["id"])
    fy = new_fiscal_year(bid["id"])
    budget = new_budget(fy["id"], total_expenditure_cents=20000000, other_revenue_cents=0)
    add_line(budget["id"], "CLEAN", 20000000)
    propose(budget["id"])
    adopt(budget["id"])
    return {"bid": bid, "pa": pa, "pb": pb, "fy": fy, "budget": budget}


def setup_petition_submitted(support=True, threshold=0.50, sign=True):
    """Two-equal-parcel adopted district; open a petition (deadline 2027-06-20),
    optionally record parcel PA's signature with the given support flag, then submit.
    Returns dict: bid, pa, pb, fy, petition.
    """
    ctx = setup_two_equal_parcels_adopted()
    petition = get_success_data(api.create_renewal_petition(
        ctx["bid"]["id"],
        create_renewal_petition_payload(circulation_deadline="2027-06-20T00:00:00Z",
                                        required_threshold_pct=threshold),
        ADMIN))
    if sign:
        owner = make_property_owner_headers(ctx["pa"]["id"])
        get_success_data(api.create_signature(
            petition["id"], create_signature_payload(parcel_id=ctx["pa"]["id"], support=support), owner))
    get_success_data(api.submit_petition(petition["id"], ADMIN))
    ctx["petition"] = petition
    return ctx


def setup_petition_verified(verifier_id="board-verifier", threshold=0.50):
    """As setup_petition_submitted with a SUPPORT signature (50% support), then verify as
    `verifier_id` so the petition is VERIFIED. Returns dict: bid, pa, pb, fy, petition.
    """
    ctx = setup_petition_submitted(support=True, threshold=threshold, sign=True)
    petition = get_success_data(api.verify_petition(
        ctx["petition"]["id"], make_board_member_headers(verifier_id)))
    ctx["petition"] = petition
    return ctx


# --- Composite: draft budget with named lines (reallocation / balance) ------

def setup_draft_budget_with_lines(lines, total_expenditure, other_revenue=0,
                                  with_parcel=False):
    """DRAFT budget on a fresh district. `lines` is a list of (category, amount_cents).
    Returns dict: bid, fy, budget, version (current budget version after adding lines).
    """
    set_clock("2027-06-01T00:00:00Z")
    bid = new_bid()
    if with_parcel:
        add_parcel(bid["id"])
    fy = new_fiscal_year(bid["id"])
    budget = new_budget(fy["id"], total_expenditure_cents=total_expenditure,
                        other_revenue_cents=other_revenue)
    for category, amount in lines:
        add_line(budget["id"], category, amount)
    refreshed = get_success_data(api.get_budget(budget["id"], ADMIN))
    return {"bid": bid, "fy": fy, "budget": refreshed, "version": refreshed["version"]}


# --- Composite: ambassador with a scheduled shift --------------------------

def setup_ambassador_with_shift(clock="2026-05-15T00:00:00Z"):
    """District with one ambassador holding a SCHEDULED shift 2026-06-01T08:00-12:00Z.
    Returns dict: bid, ambassador.
    """
    set_clock(clock)
    bid = new_bid()
    amb = get_success_data(api.create_ambassador(bid["id"], create_ambassador_payload(name="Amy"), ADMIN))
    get_success_data(api.create_shift(
        amb["id"], {"zone": "Z1", "start_at": "2026-06-01T08:00:00Z", "end_at": "2026-06-01T12:00:00Z"}, ADMIN))
    return {"bid": bid, "ambassador": amb}


# --- Composite: in-progress service request (for RESOLVE reconciliation) ----

def setup_service_request_in_progress(category="CLEAN"):
    """Active district with an ADOPTED budget carrying a CLEAN work-plan line, one ACTIVE
    ambassador, and a service request ASSIGNED to and STARTED by that ambassador.
    Returns dict: bid, budget, ambassador, service_request.
    """
    ctx = setup_single_parcel_certified()
    amb = get_success_data(api.create_ambassador(
        ctx["bid"]["id"], create_ambassador_payload(name="Amy", service_role="CLEAN"), ADMIN))
    sr = get_success_data(api.create_service_request(
        ctx["bid"]["id"],
        create_service_request_payload(category=category, source="THREE_ONE_ONE", external_ref="311-1"),
        ADMIN))
    get_success_data(api.transition_service_request(
        sr["id"], {"action": "ASSIGN", "ambassador_id": amb["id"]}, ADMIN))
    amb_headers = make_ambassador_headers(amb["id"])
    sr = get_success_data(api.transition_service_request(sr["id"], {"action": "START"}, amb_headers))
    return {"bid": ctx["bid"], "budget": ctx["budget"], "ambassador": amb, "service_request": sr}
