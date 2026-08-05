"""Composite setup helpers for the Eviction Diversion Portal.

Each helper builds a multi-step precondition state from scratch using only
PRD-declared endpoints (the harness restarts the server with an empty DB before
every test). Fixtures use get_success_data() so setup failures surface clearly.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS, make_landlord_headers, make_tenant_headers,
    make_mediator_headers, make_judge_headers, make_program_admin_headers,
    make_sheriff_headers,
)
from . import factories as f

CLERK = TEST_USERS["clerk_headers"]


# --------------------------------------------------------------------------- #
# Primitive helpers                                                            #
# --------------------------------------------------------------------------- #
def set_clock(api, iso: str):
    return get_success_data(api.set_clock(iso, CLERK))


def seed_parties(api, court_capacity=2, income_cents=200000, household_size=3):
    """Register a court, a landlord, and a tenant. Returns their full records."""
    court = get_success_data(api.create_court(
        f.create_court_payload(hearing_daily_capacity=court_capacity), CLERK))
    landlord = get_success_data(api.create_landlord(f.create_landlord_payload(), CLERK))
    tenant = get_success_data(api.create_tenant(
        f.create_tenant_payload(household_income_cents=income_cents,
                                household_size=household_size), CLERK))
    return {"court": court, "landlord": landlord, "tenant": tenant}


def seed_officer(api, badge="B1"):
    return get_success_data(api.create_officer(
        f.create_officer_payload(badge_number=badge), CLERK))


def ll_headers(ctx):
    return make_landlord_headers(ctx["landlord"]["id"])


def tn_headers(ctx):
    return make_tenant_headers(ctx["tenant"]["id"])


def file_case(api, ctx, claimed_arrears_cents=600000, filing_type="NONPAYMENT"):
    """File a NONPAYMENT case as its owning Landlord. Returns the Case record."""
    payload = f.create_case_payload(
        ctx["court"]["id"], ctx["landlord"]["id"], ctx["tenant"]["id"],
        filing_type=filing_type)
    if claimed_arrears_cents is not None:
        payload["claimed_arrears_cents"] = claimed_arrears_cents
    return get_success_data(api.create_case(payload, ll_headers(ctx)))


def serve_case(api, case_id):
    return get_success_data(api.transition_case(case_id, {"to_status": "SERVED"}, CLERK))


def answer_case(api, ctx, case_id, defenses=None):
    return get_success_data(api.create_answer(
        f.create_answer_payload(case_id, defenses=defenses), tn_headers(ctx)))


def case_to_in_litigation(api, case_id):
    return get_success_data(api.transition_case(case_id, {"to_status": "IN_LITIGATION"}, CLERK))


def fetch_case(api, case_id):
    return get_success_data(api.get_case(case_id, CLERK))


def case_version(api, case_id):
    return fetch_case(api, case_id)["version"]


def installments_of(api, plan_id):
    """Return the plan's installments sorted by sequence ascending."""
    resp = api.list_installments(CLERK, params={"payment_plan_id": plan_id})
    data = get_success_data(resp)
    rows = data if isinstance(data, list) else data.get("data", data)
    return sorted(rows, key=lambda i: i["sequence"])


# --------------------------------------------------------------------------- #
# Tier: answered case                                                         #
# --------------------------------------------------------------------------- #
def setup_answered_case(api, claimed_arrears_cents=600000, court_capacity=2,
                        income_cents=200000, household_size=3, filing_type="NONPAYMENT"):
    """Court + landlord + tenant + a case advanced FILED -> SERVED -> ANSWERED."""
    ctx = seed_parties(api, court_capacity=court_capacity,
                       income_cents=income_cents, household_size=household_size)
    case = file_case(api, ctx, claimed_arrears_cents=claimed_arrears_cents,
                     filing_type=filing_type)
    serve_case(api, case["id"])
    answer_case(api, ctx, case["id"])
    ctx["case"] = fetch_case(api, case["id"])
    return ctx


def setup_served_case(api, claimed_arrears_cents=600000):
    """Court + parties + a case advanced FILED -> SERVED (no answer)."""
    ctx = seed_parties(api)
    case = file_case(api, ctx, claimed_arrears_cents=claimed_arrears_cents)
    serve_case(api, case["id"])
    ctx["case"] = fetch_case(api, case["id"])
    return ctx


def setup_in_litigation_case(api, claimed_arrears_cents=600000):
    """Answered case then moved to IN_LITIGATION."""
    ctx = setup_answered_case(api, claimed_arrears_cents=claimed_arrears_cents)
    case_to_in_litigation(api, ctx["case"]["id"])
    ctx["case"] = fetch_case(api, ctx["case"]["id"])
    return ctx


# --------------------------------------------------------------------------- #
# Tier: payment plans / installments                                          #
# --------------------------------------------------------------------------- #
def open_plan(api, ctx, total_cents, installment_count,
              first_due_date="2026-05-20T00:00:00Z", proposed_by="LANDLORD",
              expected_case_version=None):
    """Open a PROPOSED plan on the ctx case (Landlord proposer by default)."""
    case_id = ctx["case"]["id"]
    if expected_case_version is None:
        expected_case_version = case_version(api, case_id)
    headers = ll_headers(ctx) if proposed_by == "LANDLORD" else tn_headers(ctx)
    payload = f.create_payment_plan_payload(
        case_id, total_cents, installment_count, expected_case_version,
        proposed_by=proposed_by, first_due_date=first_due_date)
    return get_success_data(api.create_payment_plan(payload, headers))


def accept_plan_as_tenant(api, ctx, plan_id):
    return get_success_data(api.respond_payment_plan(
        plan_id, {"decision": "ACCEPT"}, tn_headers(ctx)))


def setup_accepted_plan(api, claimed_arrears_cents=600000, total_cents=600000,
                        installment_count=6, first_due_date="2026-05-20T00:00:00Z"):
    """Answered case + an ACCEPTED plan; installments generated. Adds keys:
    plan, installments to the returned ctx."""
    ctx = setup_answered_case(api, claimed_arrears_cents=claimed_arrears_cents)
    plan = open_plan(api, ctx, total_cents, installment_count, first_due_date=first_due_date)
    accept_plan_as_tenant(api, ctx, plan["id"])
    ctx["plan"] = get_success_data(api.get_payment_plan(plan["id"], CLERK))
    ctx["installments"] = installments_of(api, plan["id"])
    ctx["case"] = fetch_case(api, ctx["case"]["id"])
    return ctx


# --------------------------------------------------------------------------- #
# Tier: rental-assistance referrals                                           #
# --------------------------------------------------------------------------- #
def submit_referral(api, ctx, referral_type, provider_name="Aid Program"):
    return get_success_data(api.create_referral(
        f.create_referral_payload(ctx["case"]["id"], referral_type,
                                  provider_name=provider_name),
        tn_headers(ctx)))


def approve_referral(api, referral_id):
    return get_success_data(api.transition_referral(
        referral_id, {"to_status": "APPROVED"}, TEST_USERS["program_admin_headers"]))


def disburse_referral(api, referral_id):
    return get_success_data(api.transition_referral(
        referral_id, {"to_status": "DISBURSED"}, TEST_USERS["program_admin_headers"]))


def setup_approved_rental_assistance(api, claimed_arrears_cents=600000,
                                     income_cents=200000, household_size=3):
    """Answered case (IN_DIVERSION via RA referral) with the referral APPROVED.
    Adds key: referral."""
    ctx = setup_answered_case(api, claimed_arrears_cents=claimed_arrears_cents,
                              income_cents=income_cents, household_size=household_size)
    ref = submit_referral(api, ctx, "RENTAL_ASSISTANCE")
    ctx["referral"] = approve_referral(api, ref["id"])
    ctx["case"] = fetch_case(api, ctx["case"]["id"])
    return ctx


# --------------------------------------------------------------------------- #
# Tier: hearings                                                              #
# --------------------------------------------------------------------------- #
def schedule_hearing(api, ctx, scheduled_start, scheduled_end, hearing_type="INITIAL"):
    return get_success_data(api.create_hearing(
        f.create_hearing_payload(ctx["case"]["id"], ctx["court"]["id"],
                                 scheduled_start, scheduled_end,
                                 hearing_type=hearing_type),
        CLERK))


def setup_case_with_scheduled_hearing(api, court_capacity=2, claimed_arrears_cents=600000,
                                      scheduled_start="2026-06-01T10:00:00Z",
                                      scheduled_end="2026-06-01T11:00:00Z",
                                      answered=False):
    """A case (FILED by default, or ANSWERED) + one SCHEDULED hearing on its court.
    Adds key: hearing."""
    if answered:
        ctx = setup_answered_case(api, claimed_arrears_cents=claimed_arrears_cents,
                                  court_capacity=court_capacity)
    else:
        ctx = seed_parties(api, court_capacity=court_capacity)
        case = file_case(api, ctx, claimed_arrears_cents=claimed_arrears_cents)
        ctx["case"] = case
    ctx["hearing"] = schedule_hearing(api, ctx, scheduled_start, scheduled_end)
    ctx["court"] = get_success_data(api.get_court(ctx["court"]["id"], CLERK))
    return ctx


# --------------------------------------------------------------------------- #
# Tier: judgments / lockouts                                                  #
# --------------------------------------------------------------------------- #
def enter_judgment(api, ctx, judgment_type, judge_user_id="judge-1"):
    return get_success_data(api.create_judgment(
        f.create_judgment_payload(ctx["case"]["id"], judgment_type),
        make_judge_headers(judge_user_id)))


def setup_possession_judgment(api, claimed_arrears_cents=600000):
    """IN_LITIGATION case + a POSSESSION judgment ENTERED. Adds key: judgment,
    and refreshes case (now JUDGMENT_ENTERED)."""
    ctx = setup_in_litigation_case(api, claimed_arrears_cents=claimed_arrears_cents)
    ctx["judgment"] = enter_judgment(api, ctx, "POSSESSION")
    ctx["case"] = fetch_case(api, ctx["case"]["id"])
    return ctx


def request_lockout(api, ctx, judgment_id):
    return get_success_data(api.create_lockout_order(
        f.create_lockout_order_payload(ctx["case"]["id"], judgment_id),
        ll_headers(ctx)))


def setup_requested_lockout(api, claimed_arrears_cents=600000):
    """POSSESSION judgment ENTERED + an officer + a REQUESTED lockout order.
    Adds keys: officer, judgment, lockout."""
    ctx = setup_possession_judgment(api, claimed_arrears_cents=claimed_arrears_cents)
    ctx["officer"] = seed_officer(api)
    ctx["lockout"] = request_lockout(api, ctx, ctx["judgment"]["id"])
    return ctx


def schedule_lockout(api, lockout_id, officer_id, scheduled_at):
    return get_success_data(api.transition_lockout_order(
        lockout_id,
        {"to_status": "SCHEDULED", "officer_id": officer_id, "scheduled_at": scheduled_at},
        make_sheriff_headers()))


def setup_scheduled_lockout(api, claimed_arrears_cents=600000,
                            scheduled_at="2026-06-01T10:00:00Z"):
    """POSSESSION judgment + officer + a SCHEDULED lockout at scheduled_at.
    Adds keys: officer, judgment, lockout (SCHEDULED)."""
    ctx = setup_requested_lockout(api, claimed_arrears_cents=claimed_arrears_cents)
    ctx["lockout"] = schedule_lockout(api, ctx["lockout"]["id"],
                                      ctx["officer"]["id"], scheduled_at)
    ctx["case"] = fetch_case(api, ctx["case"]["id"])
    return ctx


# --------------------------------------------------------------------------- #
# Tier: terminal / sealing                                                    #
# --------------------------------------------------------------------------- #
def setup_dismissed_case(api, claimed_arrears_cents=600000):
    """Case DISMISSED via a DISMISSAL judgment (closed_at stamped at current clock).
    Adds key: judgment; refreshes case (DISMISSED)."""
    ctx = setup_in_litigation_case(api, claimed_arrears_cents=claimed_arrears_cents)
    ctx["judgment"] = enter_judgment(api, ctx, "DISMISSAL")
    ctx["case"] = fetch_case(api, ctx["case"]["id"])
    return ctx


def request_sealing(api, ctx, basis="DISMISSAL"):
    return get_success_data(api.create_sealing_request(
        f.create_sealing_request_payload(ctx["case"]["id"], basis), tn_headers(ctx)))


def setup_sealed_case(api, claimed_arrears_cents=600000):
    """Full path to a sealed case: DISMISSED (clock default 2026-05-01), clock
    advanced past +90d, sealing REQUESTED then GRANTED. Adds keys: judgment,
    sealing (GRANTED); refreshes case (sealed=true)."""
    ctx = setup_dismissed_case(api, claimed_arrears_cents=claimed_arrears_cents)
    set_clock(api, "2026-08-01T00:00:00Z")
    sealing = request_sealing(api, ctx, basis="DISMISSAL")
    ctx["sealing"] = get_success_data(api.transition_sealing_request(
        sealing["id"], {"to_status": "GRANTED"}, make_judge_headers("judge-1")))
    ctx["case"] = fetch_case(api, ctx["case"]["id"])
    return ctx
