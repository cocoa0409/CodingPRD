"""Composite setup helpers for multi-step test prerequisites.

All fixtures build preconditions from scratch against a freshly restarted
server, using only PRD-declared endpoints. Setup calls use get_success_data()
so failures surface as clear "Setup step failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_DEFAULT_ISO, DATES
from .factories import (
    create_policy_payload, create_employee_payload, create_vendor_payload,
    create_case_payload, create_assignment_payload, create_booking_payload,
    create_claim_payload, create_home_sale_payload,
    create_exception_request_payload,
)
from .test_users import TEST_USERS, make_employee_headers, make_vendor_headers

MC = TEST_USERS["coordinator_headers"]
FIN = TEST_USERS["finance_headers"]
PM = TEST_USERS["program_manager_headers"]


# ---------------------------------------------------------------------------
# Tier 1: base entity creation + simple state progression
# ---------------------------------------------------------------------------

def create_policy(**overrides):
    """Create a policy tier (default MANAGER/DOMESTIC/RENTER, flat gross-up)."""
    return get_success_data(api_client.create_policy(create_policy_payload(**overrides), MC))


def create_employee(**overrides):
    """Create an employee (default MANAGER/RENTER, ACTIVE)."""
    return get_success_data(api_client.create_employee(create_employee_payload(**overrides), MC))


def create_vendor(**overrides):
    """Register a household-goods vendor (ACTIVE)."""
    return get_success_data(api_client.create_vendor(create_vendor_payload(**overrides), MC))


def set_clock(to_iso8601=CLOCK_DEFAULT_ISO):
    """Set the server logical clock (MobilityCoordinator)."""
    resp = api_client.set_clock(to_iso8601, MC)
    assert 200 <= resp.status_code < 300, (
        f"Setup step failed setting clock to {to_iso8601}: HTTP {resp.status_code}")


def create_case(employee_id, **overrides):
    """Open a relocation case (DRAFT) for an employee."""
    return get_success_data(api_client.create_case(
        create_case_payload(employee_id, **overrides), MC))


def authorize_case(case_id):
    """DRAFT -> AUTHORIZED. Returns the updated case."""
    return get_success_data(api_client.authorize_case(case_id, MC))


def start_case(case_id):
    """AUTHORIZED -> IN_PROGRESS. Returns the updated case."""
    return get_success_data(api_client.start_case(case_id, MC))


def get_case(case_id):
    """Read back a case."""
    return get_success_data(api_client.get_case(case_id, MC))


def get_case_version(case_id):
    """Read back a case and return its current version (OCC captures)."""
    return get_case(case_id)["version"]


def create_case_in_progress(policy_overrides=None, employee_overrides=None,
                            case_overrides=None, policy=None):
    """Policy (unless supplied) + employee + case authorized and started.

    Returns dict with keys: policy, employee, case.
    """
    if policy is None:
        policy = create_policy(**(policy_overrides or {}))
    employee = create_employee(**(employee_overrides or {}))
    case = create_case(employee["id"], **(case_overrides or {}))
    authorize_case(case["id"])
    case = start_case(case["id"])
    return {"policy": policy, "employee": employee, "case": case}


# ---------------------------------------------------------------------------
# Tier 2: vendors + move assignments through the commercial lifecycle
# ---------------------------------------------------------------------------

def setup_case_with_vendor(vendor_overrides=None, **kwargs):
    """Case IN_PROGRESS plus one ACTIVE vendor.

    Returns dict with keys: policy, employee, case, vendor.
    """
    ctx = create_case_in_progress(**kwargs)
    ctx["vendor"] = create_vendor(**(vendor_overrides or {}))
    return ctx


def create_assignment(case_id, vendor_id):
    """Assign a vendor to a case. Returns the REQUESTED assignment."""
    return get_success_data(api_client.create_move_assignment(
        create_assignment_payload(case_id, vendor_id), MC))


def schedule_survey(assignment_id, survey_at="2026-08-10T10:00:00Z"):
    """REQUESTED -> SURVEY_SCHEDULED."""
    return get_success_data(api_client.schedule_survey(
        assignment_id, {"survey_at": survey_at}, MC))


def submit_estimate(assignment_id, vendor_id, estimated_cents=80000):
    """SURVEY_SCHEDULED -> ESTIMATE_SUBMITTED, as the owning vendor."""
    return get_success_data(api_client.submit_estimate(
        assignment_id, {"estimated_cents": estimated_cents},
        make_vendor_headers(vendor_id)))


def approve_estimate(assignment_id, case_id):
    """ESTIMATE_SUBMITTED -> ESTIMATE_APPROVED with a fresh OCC case version."""
    version = get_case_version(case_id)
    return get_success_data(api_client.approve_estimate(
        assignment_id, {"expected_case_version": version}, MC))


def create_assignment_in_state(case_id, vendor_id, state, estimated_cents=80000,
                               final_invoice_cents=None,
                               survey_at="2026-08-10T10:00:00Z"):
    """Walk an assignment to the requested state.

    One of: REQUESTED, SURVEY_SCHEDULED, ESTIMATE_SUBMITTED, ESTIMATE_APPROVED,
    DELIVERED, INVOICED, PAID. Returns the assignment dict.
    """
    ma = create_assignment(case_id, vendor_id)
    if state == "REQUESTED":
        return ma
    ma = schedule_survey(ma["id"], survey_at)
    if state == "SURVEY_SCHEDULED":
        return ma
    ma = submit_estimate(ma["id"], vendor_id, estimated_cents)
    if state == "ESTIMATE_SUBMITTED":
        return ma
    ma = approve_estimate(ma["id"], case_id)
    if state == "ESTIMATE_APPROVED":
        return ma
    ma = get_success_data(api_client.mark_delivered(ma["id"], make_vendor_headers(vendor_id)))
    if state == "DELIVERED":
        return ma
    ma = get_success_data(api_client.submit_invoice(
        ma["id"], {"final_invoice_cents": final_invoice_cents or estimated_cents},
        make_vendor_headers(vendor_id)))
    if state == "INVOICED":
        return ma
    ma = get_success_data(api_client.mark_paid(ma["id"], FIN))
    if state == "PAID":
        return ma
    raise ValueError(f"Unsupported target assignment state: {state}")


# ---------------------------------------------------------------------------
# Tier 2: service bookings (temp housing + travel)
# ---------------------------------------------------------------------------

def create_travel_booking(case_id, employee_id, amount_cents=30000,
                          start_date="2026-08-15T00:00:00Z", as_employee=True):
    """Create a TRAVEL booking (HELD)."""
    headers = make_employee_headers(employee_id) if as_employee else MC
    return get_success_data(api_client.create_service_booking(
        create_booking_payload(case_id, kind="TRAVEL", start_date=start_date,
                               amount_cents=amount_cents), headers))


def create_housing_booking(case_id, employee_id,
                           start_date="2026-10-01T00:00:00Z",
                           end_date="2026-10-04T00:00:00Z",
                           nightly_cents=10000, as_employee=True):
    """Create a TEMP_HOUSING booking (HELD)."""
    headers = make_employee_headers(employee_id) if as_employee else MC
    return get_success_data(api_client.create_service_booking(
        create_booking_payload(case_id, kind="TEMP_HOUSING", start_date=start_date,
                               end_date=end_date, amount_cents=nightly_cents), headers))


def confirm_booking(booking_id):
    """HELD -> CONFIRMED (commits total_cents to the case ledger)."""
    return get_success_data(api_client.confirm_booking(booking_id, MC))


def complete_booking(booking_id):
    """CONFIRMED -> COMPLETED (converts committed into paid)."""
    return get_success_data(api_client.complete_booking(booking_id, MC))


def cancel_booking(booking_id, headers=None):
    """HELD|CONFIRMED -> CANCELLED."""
    return get_success_data(api_client.cancel_booking(booking_id, headers or MC))


def create_confirmed_booking(case_id, employee_id, kind="TRAVEL", **kwargs):
    """Create a booking and confirm it."""
    if kind == "TRAVEL":
        booking = create_travel_booking(case_id, employee_id, **kwargs)
    else:
        booking = create_housing_booking(case_id, employee_id, **kwargs)
    return confirm_booking(booking["id"])


def create_completed_travel_booking(case_id, employee_id, amount_cents=61000,
                                    start_date="2026-08-15T00:00:00Z"):
    """TRAVEL booking confirmed then completed: lands amount_cents in paid."""
    booking = create_travel_booking(case_id, employee_id, amount_cents, start_date)
    confirm_booking(booking["id"])
    return complete_booking(booking["id"])


# ---------------------------------------------------------------------------
# Tier 2: expense claims
# ---------------------------------------------------------------------------

def create_claim(case_id, employee_id, amount_cents=10000, category="MEALS",
                 payment_method="REIMBURSEMENT", **overrides):
    """Submit an expense claim as the owning employee (SUBMITTED)."""
    return get_success_data(api_client.create_expense_claim(
        create_claim_payload(case_id, amount_cents, category, payment_method,
                             **overrides),
        make_employee_headers(employee_id)))


def approve_claim(claim_id, case_id):
    """SUBMITTED -> APPROVED with a fresh OCC case version (FinanceSpecialist)."""
    version = get_case_version(case_id)
    return get_success_data(api_client.approve_claim(
        claim_id, {"expected_case_version": version}, FIN))


def reject_claim(claim_id, reason="insufficient documentation"):
    """SUBMITTED -> REJECTED with a reason."""
    return get_success_data(api_client.reject_claim(
        claim_id, {"reject_reason": reason}, FIN))


def pay_claim(claim_id):
    """APPROVED -> PAID (runs the tax gross-up)."""
    return get_success_data(api_client.pay_claim(claim_id, FIN))


def create_approved_claim(case_id, employee_id, **kwargs):
    """Claim submitted and approved (amount committed to the case ledger)."""
    claim = create_claim(case_id, employee_id, **kwargs)
    return approve_claim(claim["id"], case_id)


# ---------------------------------------------------------------------------
# Tier 2: home sale program
# ---------------------------------------------------------------------------

def create_home_sale(case_id, **overrides):
    """Open the home-sale assistance program (LISTED)."""
    return get_success_data(api_client.create_home_sale(
        create_home_sale_payload(case_id, **overrides), MC))


# ---------------------------------------------------------------------------
# Tier 2: exception requests
# ---------------------------------------------------------------------------

def create_exception_request(case_id, employee_id=None, **overrides):
    """File an exception request (PENDING, appeal_count 0).

    Filed as the owning employee when employee_id is given, else as a
    coordinator (both roles share the operation).
    """
    headers = make_employee_headers(employee_id) if employee_id else MC
    return get_success_data(api_client.create_exception_request(
        create_exception_request_payload(case_id, **overrides), headers))


def approve_exception(request_id, case_id, decision_note="approved"):
    """PENDING -> APPROVED with a fresh OCC case version (ProgramManager)."""
    version = get_case_version(case_id)
    return get_success_data(api_client.approve_exception(
        request_id, {"expected_case_version": version, "decision_note": decision_note},
        PM))


def reject_exception(request_id, decision_note="no"):
    """PENDING -> REJECTED with a note."""
    return get_success_data(api_client.reject_exception(
        request_id, {"decision_note": decision_note}, PM))


# ---------------------------------------------------------------------------
# Tier 4/5: early departure -> repayment agreement (signed and ACTIVE)
# ---------------------------------------------------------------------------

def terminate_employee(employee_id):
    """ACTIVE -> TERMINATED; stamps termination_date from the logical clock."""
    return get_success_data(api_client.terminate_employee(employee_id, MC))


def terminate_case_early(case_id):
    """IN_PROGRESS -> CLOSED_EARLY with the full child cascade."""
    return get_success_data(api_client.terminate_early_case(case_id, MC))


def get_case_repayment_agreement(case_id):
    """Read the case's single repayment agreement (assumes exactly one)."""
    data = get_success_data(api_client.list_case_repayment_agreements(case_id, MC))
    assert isinstance(data, list) and len(data) == 1, (
        f"Setup step failed: expected exactly 1 repayment agreement, got {data}")
    return data[0]


def setup_repayment_case(paid_amount=61000, repayment_window_months=24,
                         terminate_at=None, sign=True, sign_at=None,
                         create_new_policy=True, policy=None):
    """Drive a case to CLOSED_EARLY with a repayment obligation.

    Builds: policy (window = repayment_window_months) -> employee -> case
    authorized at the 2026-08-01 default clock -> IN_PROGRESS -> a TRAVEL
    booking of paid_amount confirmed and completed (so the case paid column
    holds exactly paid_amount) -> clock to terminate_at -> employee terminated
    -> terminate-early (creates the DRAFT agreement) -> optionally clock to
    sign_at and the owning employee signs (ACTIVE).

    Returns dict with keys: policy, employee, case, agreement.
    """
    terminate_at = terminate_at or DATES["TERMINATE_AT"]
    sign_at = sign_at or DATES["SIGN_AT"]
    if policy is None and create_new_policy:
        policy = create_policy(repayment_window_months=repayment_window_months)
    set_clock(CLOCK_DEFAULT_ISO)
    employee = create_employee()
    case = create_case(employee["id"])
    authorize_case(case["id"])
    case = start_case(case["id"])
    if paid_amount:
        create_completed_travel_booking(case["id"], employee["id"], paid_amount)
    set_clock(terminate_at)
    terminate_employee(employee["id"])
    case = terminate_case_early(case["id"])
    agreement = get_case_repayment_agreement(case["id"])
    if sign:
        set_clock(sign_at)
        agreement = get_success_data(api_client.sign_agreement(
            agreement["id"], make_employee_headers(employee["id"])))
    return {"policy": policy, "employee": employee, "case": case,
            "agreement": agreement}


# ---------------------------------------------------------------------------
# Tier 3: full move lifecycle shortcut (for vendor rating scenarios)
# ---------------------------------------------------------------------------

def setup_paid_move(vendor_name="Rating Movers", first_estimate=80000,
                    first_invoice=None, survey_at="2026-08-10T10:00:00Z"):
    """Case IN_PROGRESS + vendor + one assignment walked to PAID.

    Returns dict with keys: policy, employee, case, vendor, assignment.
    """
    ctx = setup_case_with_vendor({"name": vendor_name})
    ma = create_assignment_in_state(
        ctx["case"]["id"], ctx["vendor"]["id"], "PAID",
        estimated_cents=first_estimate, final_invoice_cents=first_invoice,
        survey_at=survey_at)
    ctx["assignment"] = ma
    return ctx


def rate_assignment(assignment_id, employee_id, rating):
    """Record the owning employee's satisfaction rating on a PAID move."""
    return get_success_data(api_client.rate_assignment(
        assignment_id, {"rating": rating}, make_employee_headers(employee_id)))
