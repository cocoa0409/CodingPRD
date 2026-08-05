"""Composite setup helpers.

Each helper builds its preconditions from scratch through PRD-declared endpoints,
using the lenient get_success_data() validator so setup failures surface clearly.
The test harness restarts the server (empty DB, clock reset to 2026-05-01T00:00:00Z)
before every test, so these helpers never assume pre-existing state.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    clerk_headers, supervisor_headers, finance_headers, admin_headers,
)
from . import factories as f


# --------------------------------------------------------------------------- #
# Primitive builders
# --------------------------------------------------------------------------- #
def set_clock(iso: str):
    """Advance the server logical clock to an ISO-8601 instant."""
    resp = api_client.set_clock(f.clock_payload(iso), admin_headers())
    return get_success_data(resp)


def make_case(case_number="C-TEST", defendant_name="Test Defendant"):
    resp = api_client.create_case(
        f.create_case_payload(case_number=case_number, defendant_name=defendant_name),
        clerk_headers(),
    )
    return get_success_data(resp)


def make_victim(name="Test Victim"):
    resp = api_client.create_victim(f.create_victim_payload(name=name), clerk_headers())
    return get_success_data(resp)


def make_obligation(case_id, obligation_type="COURT_FEE", assessed_amount_cents=10000,
                    victim_id=None, priority_rank=None):
    payload = f.create_obligation_payload(
        case_id=case_id,
        obligation_type=obligation_type,
        assessed_amount_cents=assessed_amount_cents,
    )
    if victim_id is not None:
        payload["victim_id"] = victim_id
    if priority_rank is not None:
        payload["priority_rank"] = priority_rank
    resp = api_client.create_obligation(payload, clerk_headers())
    return get_success_data(resp)


def get_case_version(case_id):
    resp = api_client.get_case(case_id, clerk_headers())
    return get_success_data(resp)["version"]


def make_payment_plan(case_id, monthly_income_cents=400000, monthly_expenses_cents=250000,
                      ability_to_pay_method="NET_DISPOSABLE", expected_case_version=None):
    if expected_case_version is None:
        expected_case_version = get_case_version(case_id)
    resp = api_client.create_payment_plan(
        f.create_payment_plan_payload(
            case_id=case_id,
            monthly_income_cents=monthly_income_cents,
            monthly_expenses_cents=monthly_expenses_cents,
            ability_to_pay_method=ability_to_pay_method,
            expected_case_version=expected_case_version,
        ),
        clerk_headers(),
    )
    return get_success_data(resp)


def post_payment(case_id, amount_cents, allocation_method="STATUTORY_PRIORITY"):
    resp = api_client.create_payment(
        f.create_payment_payload(
            case_id=case_id, amount_cents=amount_cents, allocation_method=allocation_method,
        ),
        clerk_headers(),
    )
    return get_success_data(resp)


def make_amnesty(name="Test Amnesty", start_date="2026-01-01T00:00:00Z",
                 end_date="2026-12-01T00:00:00Z", waiver_pct=1.0):
    resp = api_client.create_amnesty_program(
        f.create_amnesty_program_payload(
            name=name, start_date=start_date, end_date=end_date, waiver_pct=waiver_pct,
        ),
        admin_headers(),
    )
    return get_success_data(resp)


def make_wage_assignment(case_id, employer_name="Acme Co", monthly_withhold_cents=10000,
                         effective_start_date="2026-06-01T00:00:00Z",
                         effective_end_date="2026-12-31T00:00:00Z"):
    resp = api_client.create_wage_assignment(
        f.create_wage_assignment_payload(
            case_id=case_id,
            employer_name=employer_name,
            monthly_withhold_cents=monthly_withhold_cents,
            effective_start_date=effective_start_date,
            effective_end_date=effective_end_date,
        ),
        finance_headers(),
    )
    return get_success_data(resp)


# --------------------------------------------------------------------------- #
# Composite scenarios
# --------------------------------------------------------------------------- #
def setup_case_with_obligation(case_number="C-CO", assessed_amount_cents=10000,
                               obligation_type="COURT_FEE"):
    """Case + one obligation. Returns (case, obligation)."""
    case = make_case(case_number=case_number)
    obl = make_obligation(case["id"], obligation_type=obligation_type,
                          assessed_amount_cents=assessed_amount_cents)
    return case, obl


def setup_case_with_restitution(case_number="C-REST", assessed_amount_cents=10000,
                                victim_name="Test Victim"):
    """Case + victim + one RESTITUTION obligation. Returns (case, victim, obligation)."""
    case = make_case(case_number=case_number)
    victim = make_victim(name=victim_name)
    obl = make_obligation(case["id"], obligation_type="RESTITUTION",
                          assessed_amount_cents=assessed_amount_cents, victim_id=victim["id"])
    return case, victim, obl


def setup_active_plan(case_number="C-ACTPLAN", assessed_amount_cents=100000,
                      monthly_income_cents=400000, monthly_expenses_cents=250000,
                      ability_to_pay_method="NET_DISPOSABLE"):
    """Case + obligation + PROPOSED plan activated to ACTIVE. Returns (case, obligation, plan).
    Assumes the clock has already been set by the caller if a specific due date is needed.
    """
    case = make_case(case_number=case_number)
    obl = make_obligation(case["id"], obligation_type="COURT_FEE",
                          assessed_amount_cents=assessed_amount_cents)
    plan = make_payment_plan(
        case["id"],
        monthly_income_cents=monthly_income_cents,
        monthly_expenses_cents=monthly_expenses_cents,
        ability_to_pay_method=ability_to_pay_method,
    )
    resp = api_client.activate_payment_plan(plan["id"], supervisor_headers())
    plan = get_success_data(resp)
    return case, obl, plan


def setup_defaulted_case(case_number="C-DEFAULT", assessed_amount_cents=100000,
                         plan_start="2026-06-01T00:00:00Z",
                         sweep_clock="2026-07-31T00:00:00Z"):
    """Drive a case all the way to DEFAULTED via the delinquency sweep.

    Sets the clock to plan_start, creates case+obligation, creates and activates
    a plan (next_due_date = plan_start + 30 days), advances the clock to
    sweep_clock, and runs the delinquency sweep. Returns (case, obligation, plan,
    sweep_result) where sweep_result is the sweep endpoint's data payload.
    """
    set_clock(plan_start)
    case, obl, plan = setup_active_plan(
        case_number=case_number, assessed_amount_cents=assessed_amount_cents,
    )
    set_clock(sweep_clock)
    resp = api_client.delinquency_sweep(admin_headers())
    sweep = get_success_data(resp)
    return case, obl, plan, sweep


def setup_enforcement_actions(case_number="C-ENF", assessed_amount_cents=100000):
    """A defaulted case with its two cascade-created enforcement actions.
    Returns (case, plan, [enforcement_action, ...]) sorted as returned by the list.
    """
    case, obl, plan, sweep = setup_defaulted_case(
        case_number=case_number, assessed_amount_cents=assessed_amount_cents,
    )
    resp = api_client.list_enforcement_actions(admin_headers(), params={"case_id": case["id"]})
    actions, _meta = _paginate(resp)
    return case, plan, actions


def setup_waiver_requested(case_number="C-WR", assessed_amount_cents=10000,
                           requested_amount_cents=10000, requester_id="clerk-1",
                           clock="2026-06-01T00:00:00Z", amnesty_pct=1.0,
                           with_amnesty=True):
    """Clock set; optional amnesty covering the clock; case + COURT_FEE obligation;
    a REQUESTED waiver filed by requester_id. Returns (case, obligation, waiver, amnesty)."""
    set_clock(clock)
    amnesty = None
    if with_amnesty:
        amnesty = make_amnesty(name=f"Amnesty {case_number}", waiver_pct=amnesty_pct)
    case = make_case(case_number=case_number)
    obl = make_obligation(case["id"], obligation_type="COURT_FEE",
                          assessed_amount_cents=assessed_amount_cents)
    resp = api_client.create_waiver_request(
        f.create_waiver_request_payload(
            case_id=case["id"], obligation_id=obl["id"],
            requested_amount_cents=requested_amount_cents,
        ),
        clerk_headers(requester_id),
    )
    waiver = get_success_data(resp)
    return case, obl, waiver, amnesty


def setup_disbursement_pending(case_number="C-DISB", assessed_amount_cents=10000,
                               disburse_cents=4000):
    """Restitution fully collected for a victim, then one PENDING disbursement.
    Returns (case, victim, obligation, payment, disbursement)."""
    case, victim, obl = setup_case_with_restitution(
        case_number=case_number, assessed_amount_cents=assessed_amount_cents,
    )
    payment = post_payment(case["id"], assessed_amount_cents, "STATUTORY_PRIORITY")
    resp = api_client.create_disbursement(
        f.create_disbursement_payload(
            victim_id=victim["id"], case_id=case["id"], amount_cents=disburse_cents,
        ),
        finance_headers(),
    )
    disb = get_success_data(resp)
    return case, victim, obl, payment, disb


# --------------------------------------------------------------------------- #
# Internal
# --------------------------------------------------------------------------- #
def _paginate(resp):
    """Lenient extraction of (data_list, meta) from a list response."""
    body = resp.json()
    return body.get("data", []), body.get("meta", {})
