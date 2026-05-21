"""Composite setup helpers — multi-step preambles tests can reuse.

The FMLA / PFL lifecycle takes 5–15 API calls to reach interesting
states (an Employer + Worksite + Employee with eligibility cleared, a
PENDING_CERTIFICATION case with a MedicalCertification ACCEPTED, an
APPROVED case with PROPOSED instances promoted and a BenefitInvoice
issued, a case advanced into ACTIVE and then COMPLETED via clock
sweeps, a quota near 480 hours for boundary tests). Each fixture
composes the lower-level steps so test bodies focus on the rule under
assertion.

IDENTITY THREADING — PRD §2.1:

    "When `X-User-Role` is `Employee`, `X-User-ID` is the `id` of the
    acting `Employee`; ownership checks on any resource that references
    an `Employee` ... compare the resource's owning `employee_id` to
    `X-User-ID`. A mismatch surfaces as `ERR_NOT_OWNER`."

After an Employee is created, fixtures act as that employee by minting
headers via `make_employee_headers(employee["id"])` whenever the call
is ownership-gated (e.g., POST /employees/{id}/leave-cases). HR-acted
calls use the shared HR_SPECIALIST_SHARED_ID via TEST_USERS["hr_specialist_headers"].
ComplianceOfficer is opaque so the shared constant is canonical.

CLOCK ANCHORING — PRD §2.10:

    "Time-gated transitions — a case becoming active on its requested
    start date, a case completing on its expected end date, an invoice
    aging through grace and into forfeiture, a certification deadline
    expiring — are driven by the server clock rather than by direct
    client calls. A dedicated administrative capability advances that
    clock to a supplied target instant".

Fixtures advance the clock to deterministic moments using the
ComplianceOfficer headers via `advance_clock_to(target_iso)` and never
rely on wall-clock time. The default clock anchor
(TEST_DEFAULTS['INITIAL_CLOCK_ISO']) is well past the default Employee
hire_date so 12-month tenure is satisfied by default.

Setup calls use `get_success_data` (lenient 2xx validator) so a failed
setup surfaces as 'Setup failed' rather than a confusing assertion
failure downstream.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CERT_DEADLINE_DAYS,
    FMLA_ENTITLEMENT_HOURS,
    TEST_DEFAULTS,
)
from .factories import (
    add_days,
    cancel_leave_case_payload,
    clock_advance_payload,
    create_certification_payload,
    create_employee_payload,
    create_employer_payload,
    create_leave_case_payload,
    create_leave_instance_payload,
    create_pfl_claim_payload,
    create_worksite_payload,
    date_str,
    hours_snapshot_payload,
    patch_worksite_payload,
    review_certification_payload,
    review_leave_case_payload,
)
from .test_users import (
    HR_SPECIALIST_SHARED_ID,
    TEST_USERS,
    make_employee_headers,
)


# ===========================================================================
# Clock helpers — PRD §2.10
# ===========================================================================
def advance_clock_to(target_iso: str) -> Dict[str, Any]:
    """Advance the logical clock to `target_iso` (PRD §2.10)."""
    resp = api_client.clock_advance(
        clock_advance_payload(to_timestamp=target_iso),
        TEST_USERS["compliance_officer_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Read helpers
# ===========================================================================
def get_leave_case(leave_case_id: str,
                   headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TEST_USERS["hr_specialist_headers"]
    return get_success_data(api_client.get_leave_case(leave_case_id, h))


def get_employer(employer_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_employer(
            employer_id, TEST_USERS["compliance_officer_headers"],
        ),
    )


def get_employee(employee_id: str,
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TEST_USERS["hr_specialist_headers"]
    return get_success_data(api_client.get_employee(employee_id, h))


def get_pfl_claim(pfl_claim_id: str,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TEST_USERS["hr_specialist_headers"]
    return get_success_data(api_client.get_pfl_claim(pfl_claim_id, h))


def get_quota_balance(
    employee_id: str,
    *,
    as_of_date: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    h = headers or TEST_USERS["hr_specialist_headers"]
    params = {"as_of_date": as_of_date} if as_of_date else None
    return get_success_data(
        api_client.get_quota_balance(employee_id, h, params=params),
    )


def list_benefit_invoices(
    leave_case_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    h = headers or TEST_USERS["hr_specialist_headers"]
    body = get_success_data(
        api_client.list_benefit_invoices(
            leave_case_id, h, params={"limit": 100},
        ),
    )
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("items", "results", "data", "invoices"):
            v = body.get(key)
            if isinstance(v, list):
                return v
    return []


def list_audit_events(
    leave_case_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    h = headers or TEST_USERS["hr_specialist_headers"]
    body = get_success_data(
        api_client.list_audit_events(
            leave_case_id, h, params={"limit": 100},
        ),
    )
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("items", "results", "data", "events"):
            v = body.get(key)
            if isinstance(v, list):
                return v
    return []


def list_leave_cases(
    employee_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    h = headers or TEST_USERS["hr_specialist_headers"]
    body = get_success_data(
        api_client.list_leave_cases(
            employee_id, h, params=params or {"limit": 100},
        ),
    )
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("items", "results", "data", "cases"):
            v = body.get(key)
            if isinstance(v, list):
                return v
    return []


# ===========================================================================
# Tier 0 — Foundation creators
# ===========================================================================
def create_employer(
    *,
    leave_year_basis: str = "CALENDAR",
    state_pfl_program: str = "NONE",
    benefit_premium_share_cents: Optional[int] = None,
    legal_name: Optional[str] = None,
) -> Dict[str, Any]:
    """ComplianceOfficer creates an Employer (PRD §3.1)."""
    payload = create_employer_payload(
        legal_name=legal_name,
        leave_year_basis=leave_year_basis,
        state_pfl_program=state_pfl_program,
        benefit_premium_share_cents=benefit_premium_share_cents,
    )
    return get_success_data(
        api_client.create_employer(
            payload, TEST_USERS["compliance_officer_headers"],
        ),
    )


def create_worksite(
    *,
    employer_id: str,
    employee_count_within_75_miles: Optional[int] = None,
    address_line: Optional[str] = None,
) -> Dict[str, Any]:
    """ComplianceOfficer creates a Worksite (PRD §3.1)."""
    payload = create_worksite_payload(
        address_line=address_line,
        employee_count_within_75_miles=employee_count_within_75_miles,
    )
    return get_success_data(
        api_client.create_worksite(
            employer_id, payload,
            TEST_USERS["compliance_officer_headers"],
        ),
    )


def create_employee(
    *,
    employer_id: str,
    worksite_id: str,
    hire_date: Optional[str] = None,
    hours_worked_trailing_12mo: Optional[int] = None,
    monthly_wage_cents: Optional[int] = None,
    full_name: Optional[str] = None,
) -> Dict[str, Any]:
    """HR or Compliance creates an Employee (PRD §3.1: shared
    POST /employers/{id}/employees endpoint)."""
    payload = create_employee_payload(
        worksite_id=worksite_id,
        full_name=full_name,
        hire_date=hire_date,
        hours_worked_trailing_12mo=hours_worked_trailing_12mo,
        monthly_wage_cents=monthly_wage_cents,
    )
    return get_success_data(
        api_client.create_employee(
            employer_id, payload,
            TEST_USERS["hr_specialist_headers"],
        ),
    )


def patch_worksite_headcount(
    *,
    worksite_id: str,
    employee_count_within_75_miles: int,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    payload = patch_worksite_payload(
        employee_count_within_75_miles=employee_count_within_75_miles,
        version=version,
    )
    return get_success_data(
        api_client.patch_worksite(
            worksite_id, payload,
            TEST_USERS["compliance_officer_headers"],
        ),
    )


def post_hours_snapshot(
    *,
    employee_id: str,
    hours_worked_trailing_12mo: int,
) -> Dict[str, Any]:
    """HR posts an hours-feed snapshot (PRD §3.1)."""
    return get_success_data(
        api_client.post_hours_snapshot(
            employee_id,
            hours_snapshot_payload(
                hours_worked_trailing_12mo=hours_worked_trailing_12mo,
            ),
            TEST_USERS["hr_specialist_headers"],
        ),
    )


# ===========================================================================
# Tier 1 — Employer + worksite + employee bundle
# ===========================================================================
def setup_employer_worksite_employee(
    *,
    leave_year_basis: str = "CALENDAR",
    state_pfl_program: str = "NONE",
    benefit_premium_share_cents: Optional[int] = None,
    worksite_headcount: int = 80,
    hire_date: Optional[str] = None,
    hours_worked_trailing_12mo: Optional[int] = None,
    monthly_wage_cents: Optional[int] = None,
    initial_clock_iso: Optional[str] = TEST_DEFAULTS["INITIAL_CLOCK_ISO"],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build (Employer, Worksite, Employee), anchored at INITIAL_CLOCK_ISO.

    Defaults satisfy all three eligibility thresholds (PRD §3.2):
        - hire_date 2023-01-01 vs clock 2026-03-01 = 38 months >= 12
        - hours_worked_trailing_12mo 2080 >= 1250
        - worksite_headcount 80 >= 50

    Returns (employer, worksite, employee).
    """
    if initial_clock_iso is not None:
        advance_clock_to(initial_clock_iso)
    employer = create_employer(
        leave_year_basis=leave_year_basis,
        state_pfl_program=state_pfl_program,
        benefit_premium_share_cents=benefit_premium_share_cents,
    )
    worksite = create_worksite(
        employer_id=employer["id"],
        employee_count_within_75_miles=worksite_headcount,
    )
    employee = create_employee(
        employer_id=employer["id"],
        worksite_id=worksite["id"],
        hire_date=hire_date,
        hours_worked_trailing_12mo=hours_worked_trailing_12mo,
        monthly_wage_cents=monthly_wage_cents,
    )
    return employer, worksite, employee


# ===========================================================================
# Tier 2 — LeaveCase lifecycle helpers
# ===========================================================================
def submit_leave_case(
    *,
    employee_id: str,
    reason: str = "OWN_SERIOUS_HEALTH",
    leave_pattern: str = "INTERMITTENT",
    requested_start_date: str = "2026-05-01",
    expected_end_date: str = "2026-05-31",
    pfl_claim_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Employee submits a leave case (PRD §3.3: POST as the acting
    Employee with X-User-ID = employee.id)."""
    h = make_employee_headers(employee_id)
    payload = create_leave_case_payload(
        reason=reason,
        leave_pattern=leave_pattern,
        requested_start_date=requested_start_date,
        expected_end_date=expected_end_date,
        pfl_claim_id=pfl_claim_id,
    )
    return get_success_data(
        api_client.create_leave_case(employee_id, payload, h),
    )


def submit_certification(
    *,
    leave_case_id: str,
    employee_id: str,
    serious_health_condition: bool = True,
    estimated_frequency_per_month: Optional[int] = None,
    estimated_duration_hours: Optional[int] = None,
) -> Dict[str, Any]:
    """Employee submits a MedicalCertification (PRD §3.5)."""
    h = make_employee_headers(employee_id)
    payload = create_certification_payload(
        serious_health_condition=serious_health_condition,
        estimated_frequency_per_month=estimated_frequency_per_month,
        estimated_duration_hours=estimated_duration_hours,
    )
    return get_success_data(
        api_client.create_certification(leave_case_id, payload, h),
    )


def review_certification(
    *,
    leave_case_id: str,
    cert_id: str,
    decision: str,
) -> Dict[str, Any]:
    """HRSpecialist reviews a MedicalCertification (PRD §3.5)."""
    payload = review_certification_payload(decision=decision)
    return get_success_data(
        api_client.review_certification(
            leave_case_id, cert_id, payload,
            TEST_USERS["hr_specialist_headers"],
        ),
    )


def review_leave_case(
    *,
    leave_case_id: str,
    decision: str,
) -> Dict[str, Any]:
    """HRSpecialist decides APPROVE / DENY on a leave case (PRD §3.6)."""
    payload = review_leave_case_payload(decision=decision)
    return get_success_data(
        api_client.review_leave_case(
            leave_case_id, payload,
            TEST_USERS["hr_specialist_headers"],
        ),
    )


def log_instance(
    *,
    leave_case_id: str,
    employee_id: str,
    instance_date: str,
    hours_used: int = 8,
    as_role: str = "Employee",
) -> Dict[str, Any]:
    """Log a LeaveInstance under a case (PRD §3.4)."""
    if as_role == "Employee":
        h = make_employee_headers(employee_id)
    else:
        h = TEST_USERS["hr_specialist_headers"]
    payload = create_leave_instance_payload(
        instance_date=instance_date, hours_used=hours_used,
    )
    return get_success_data(
        api_client.create_leave_instance(leave_case_id, payload, h),
    )


def void_instance(*, leave_case_id: str, instance_id: str) -> None:
    """HRSpecialist voids a LeaveInstance (PRD §3.4)."""
    resp = api_client.void_leave_instance(
        leave_case_id, instance_id,
        TEST_USERS["hr_specialist_headers"],
    )
    # 204 No Content — lenient validator accepts this.
    assert 200 <= resp.status_code < 300, (
        f"void_instance setup failed with HTTP {resp.status_code}: "
        f"{resp.text}"
    )


def cancel_case(
    *,
    leave_case_id: str,
    employee_id: str,
    version: Optional[int] = None,
) -> None:
    """Employee cancels a DRAFT or PENDING_CERTIFICATION case (PRD §3.11)."""
    h = make_employee_headers(employee_id)
    payload = cancel_leave_case_payload(version=version)
    resp = api_client.cancel_leave_case(leave_case_id, payload, h)
    assert 200 <= resp.status_code < 300, (
        f"cancel_case setup failed with HTTP {resp.status_code}: "
        f"{resp.text}"
    )


def return_case(
    *,
    leave_case_id: str,
    employee_id: str,
) -> Dict[str, Any]:
    """Employee posts return-to-work (PRD §3.10)."""
    h = make_employee_headers(employee_id)
    return get_success_data(
        api_client.return_leave_case(leave_case_id, None, h),
    )


def restore_job(*, leave_case_id: str) -> Dict[str, Any]:
    """HRSpecialist restores the job (PRD §3.10)."""
    return get_success_data(
        api_client.restore_job(
            leave_case_id, None, TEST_USERS["hr_specialist_headers"],
        ),
    )


def pay_invoice(*, invoice_id: str, employee_id: str) -> Dict[str, Any]:
    """Employee pays a BenefitInvoice (PRD §3.9)."""
    h = make_employee_headers(employee_id)
    return get_success_data(
        api_client.pay_benefit_invoice(invoice_id, None, h),
    )


def create_pfl_claim(
    *,
    employee_id: str,
    claim_type: str = "BABY_BONDING",
    weeks_authorized: int = 8,
) -> Dict[str, Any]:
    """Employee creates a state PFL claim (PRD §3.8)."""
    h = make_employee_headers(employee_id)
    payload = create_pfl_claim_payload(
        employee_id=employee_id,
        claim_type=claim_type,
        weeks_authorized=weeks_authorized,
    )
    return get_success_data(
        api_client.create_pfl_claim(payload, h),
    )


# ===========================================================================
# Tier 3 — Composite scenarios
# ===========================================================================
def setup_eligible_employee(
    *,
    leave_year_basis: str = "CALENDAR",
    state_pfl_program: str = "NONE",
    benefit_premium_share_cents: Optional[int] = None,
    worksite_headcount: int = 80,
    hire_date: Optional[str] = None,
    hours_worked_trailing_12mo: Optional[int] = None,
    monthly_wage_cents: Optional[int] = None,
    initial_clock_iso: Optional[str] = TEST_DEFAULTS["INITIAL_CLOCK_ISO"],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build an Employer/Worksite/Employee that clears all three
    eligibility thresholds.

    Returns (employer, worksite, employee).
    """
    return setup_employer_worksite_employee(
        leave_year_basis=leave_year_basis,
        state_pfl_program=state_pfl_program,
        benefit_premium_share_cents=benefit_premium_share_cents,
        worksite_headcount=worksite_headcount,
        hire_date=hire_date,
        hours_worked_trailing_12mo=hours_worked_trailing_12mo,
        monthly_wage_cents=monthly_wage_cents,
        initial_clock_iso=initial_clock_iso,
    )


def setup_pending_certification_case(
    *,
    reason: str = "OWN_SERIOUS_HEALTH",
    leave_pattern: str = "INTERMITTENT",
    requested_start_date: str = "2026-05-01",
    expected_end_date: str = "2026-05-31",
    leave_year_basis: str = "CALENDAR",
    state_pfl_program: str = "NONE",
    pfl_claim_id: Optional[str] = None,
    initial_clock_iso: Optional[str] = TEST_DEFAULTS["INITIAL_CLOCK_ISO"],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build employer/worksite/employee and submit a LeaveCase, leaving
    it in PENDING_CERTIFICATION.

    Returns (employer, worksite, employee, leave_case).
    """
    employer, worksite, employee = setup_eligible_employee(
        leave_year_basis=leave_year_basis,
        state_pfl_program=state_pfl_program,
        initial_clock_iso=initial_clock_iso,
    )
    case = submit_leave_case(
        employee_id=employee["id"],
        reason=reason,
        leave_pattern=leave_pattern,
        requested_start_date=requested_start_date,
        expected_end_date=expected_end_date,
        pfl_claim_id=pfl_claim_id,
    )
    return employer, worksite, employee, case


def setup_case_with_complete_certification(
    *,
    reason: str = "OWN_SERIOUS_HEALTH",
    leave_pattern: str = "INTERMITTENT",
    requested_start_date: str = "2026-05-01",
    expected_end_date: str = "2026-05-31",
    leave_year_basis: str = "CALENDAR",
    state_pfl_program: str = "NONE",
    pfl_claim_id: Optional[str] = None,
    initial_clock_iso: Optional[str] = TEST_DEFAULTS["INITIAL_CLOCK_ISO"],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any]]:
    """Build through a case whose MedicalCertification has been
    ACCEPTED, so certification_status == COMPLETE (PRD §3.5).

    Returns (employer, worksite, employee, case, certification).
    Case remains in PENDING_CERTIFICATION (case-level review not yet
    done).
    """
    employer, worksite, employee, case = setup_pending_certification_case(
        reason=reason,
        leave_pattern=leave_pattern,
        requested_start_date=requested_start_date,
        expected_end_date=expected_end_date,
        leave_year_basis=leave_year_basis,
        state_pfl_program=state_pfl_program,
        pfl_claim_id=pfl_claim_id,
        initial_clock_iso=initial_clock_iso,
    )
    cert = submit_certification(
        leave_case_id=case["id"],
        employee_id=employee["id"],
        serious_health_condition=True,
    )
    cert = review_certification(
        leave_case_id=case["id"], cert_id=cert["id"], decision="ACCEPT",
    )
    return employer, worksite, employee, case, cert


def setup_approved_case(
    *,
    reason: str = "OWN_SERIOUS_HEALTH",
    leave_pattern: str = "INTERMITTENT",
    requested_start_date: str = "2026-05-01",
    expected_end_date: str = "2026-05-31",
    instance_dates_and_hours: Optional[List[Tuple[str, int]]] = None,
    leave_year_basis: str = "CALENDAR",
    state_pfl_program: str = "NONE",
    benefit_premium_share_cents: Optional[int] = None,
    pfl_claim_id: Optional[str] = None,
    initial_clock_iso: Optional[str] = TEST_DEFAULTS["INITIAL_CLOCK_ISO"],
) -> Dict[str, Any]:
    """Build through to an APPROVED LeaveCase.

    For OWN_SERIOUS_HEALTH/FAMILY_SERIOUS_HEALTH the workflow goes
    submit → submit cert → ACCEPT cert (cert_status COMPLETE) → log
    PROPOSED instances → APPROVE case. For BABY_BONDING / MILITARY
    no certification is required (PRD §3.3: NOT_REQUIRED).

    Returns dict with keys: employer, worksite, employee, case, cert,
    instances (list).
    """
    requires_cert = reason in ("OWN_SERIOUS_HEALTH", "FAMILY_SERIOUS_HEALTH")
    if requires_cert:
        employer, worksite, employee, case, cert = (
            setup_case_with_complete_certification(
                reason=reason,
                leave_pattern=leave_pattern,
                requested_start_date=requested_start_date,
                expected_end_date=expected_end_date,
                leave_year_basis=leave_year_basis,
                state_pfl_program=state_pfl_program,
                pfl_claim_id=pfl_claim_id,
                initial_clock_iso=initial_clock_iso,
            )
        )
    else:
        # NOT_REQUIRED branch.
        employer, worksite, employee, case = setup_pending_certification_case(
            reason=reason,
            leave_pattern=leave_pattern,
            requested_start_date=requested_start_date,
            expected_end_date=expected_end_date,
            leave_year_basis=leave_year_basis,
            state_pfl_program=state_pfl_program,
            pfl_claim_id=pfl_claim_id,
            initial_clock_iso=initial_clock_iso,
        )
        cert = None

    if benefit_premium_share_cents is not None:
        # Re-create employer to override premium — not supported; we
        # accept the default from setup_eligible_employee. Tests that
        # need a specific premium pass it via initial setup_employer in
        # bespoke fixtures rather than via setup_approved_case.
        pass

    # Log PROPOSED LeaveInstances for intermittent / reduced-schedule
    # cases. CONTINUOUS cases do not allow manual instance logging
    # (PRD §3.4).
    instances: List[Dict[str, Any]] = []
    if leave_pattern in ("INTERMITTENT", "REDUCED_SCHEDULE"):
        if instance_dates_and_hours is None:
            instance_dates_and_hours = [
                (requested_start_date, 8),
            ]
        for inst_date, hours in instance_dates_and_hours:
            inst = log_instance(
                leave_case_id=case["id"],
                employee_id=employee["id"],
                instance_date=inst_date,
                hours_used=hours,
            )
            instances.append(inst)

    # HR approves the case.
    case = review_leave_case(
        leave_case_id=case["id"], decision="APPROVE",
    )
    return {
        "employer": employer,
        "worksite": worksite,
        "employee": employee,
        "case": case,
        "cert": cert,
        "instances": instances,
    }


def setup_active_case(
    *,
    requested_start_date: str = "2026-05-01",
    expected_end_date: str = "2026-05-31",
    leave_pattern: str = "INTERMITTENT",
    instance_dates_and_hours: Optional[List[Tuple[str, int]]] = None,
    leave_year_basis: str = "CALENDAR",
    state_pfl_program: str = "NONE",
    initial_clock_iso: Optional[str] = TEST_DEFAULTS["INITIAL_CLOCK_ISO"],
) -> Dict[str, Any]:
    """Build through APPROVED → ACTIVE by advancing clock past
    requested_start_date (PRD §3.10)."""
    ctx = setup_approved_case(
        requested_start_date=requested_start_date,
        expected_end_date=expected_end_date,
        leave_pattern=leave_pattern,
        instance_dates_and_hours=instance_dates_and_hours,
        leave_year_basis=leave_year_basis,
        state_pfl_program=state_pfl_program,
        initial_clock_iso=initial_clock_iso,
    )
    advance_clock_to(f"{requested_start_date}T12:00:00.000Z")
    case = get_leave_case(ctx["case"]["id"])
    ctx["case"] = case
    return ctx


def setup_completed_case(
    *,
    requested_start_date: str = "2026-05-01",
    expected_end_date: str = "2026-05-31",
    leave_pattern: str = "CONTINUOUS",
    leave_year_basis: str = "CALENDAR",
    state_pfl_program: str = "NONE",
    initial_clock_iso: Optional[str] = TEST_DEFAULTS["INITIAL_CLOCK_ISO"],
) -> Dict[str, Any]:
    """Build through to COMPLETED. Defaults to CONTINUOUS so the
    clock-cross-end_date path completes without instance bookkeeping.

    For intermittent cases tests must arrange instances and use return.

    PRD §3.9: an unpaid invoice ages into GRACE (30 days) then
    FORFEITED (45 days), and forfeiture cascades into the parent
    `LeaveCase.job_restoration_status`. To keep the COMPLETED case
    cleanly PROTECTED, this fixture pays every invoice on the case
    BEFORE advancing the clock past expected_end_date.
    """
    ctx = setup_approved_case(
        requested_start_date=requested_start_date,
        expected_end_date=expected_end_date,
        leave_pattern=leave_pattern,
        leave_year_basis=leave_year_basis,
        state_pfl_program=state_pfl_program,
        initial_clock_iso=initial_clock_iso,
    )
    # Pay any invoices issued at approval so the invoice-forfeit
    # cascade does not flip job_restoration_status to FORFEITED while
    # advancing the clock past expected_end_date.
    for inv in list_benefit_invoices(ctx["case"]["id"]):
        if inv.get("invoice_status") in {"ISSUED", "GRACE"}:
            pay_invoice(
                invoice_id=inv["id"], employee_id=ctx["employee"]["id"],
            )
    # Advance past end_date so the clock sweep completes a CONTINUOUS case.
    advance_clock_to(add_days(f"{expected_end_date}T00:00:00.000Z", 1))
    ctx["case"] = get_leave_case(ctx["case"]["id"])
    return ctx


# ===========================================================================
# Tier 4 — Difficulty-design specific composite fixtures
# ===========================================================================
def setup_two_employees_same_basis_diff_employer(
    *,
    initial_clock_iso: Optional[str] = "2026-03-01T00:00:00.000Z",
    monthly_wage_cents: int = 500_000,
    benefit_premium_share_cents: int = 30_000,
    hours_worked_trailing_12mo: int = 2080,
    hire_date: str = "2023-01-01",
) -> Dict[str, Any]:
    """Build two parallel (Employer, Worksite, Employee) trios — one
    CALENDAR, one ROLLING_BACKWARD — with identical employee inputs.

    Used by quota_balance_calendar_vs_rolling difficulty instance.
    """
    if initial_clock_iso is not None:
        advance_clock_to(initial_clock_iso)
    employer_cal = create_employer(
        leave_year_basis="CALENDAR",
        state_pfl_program="NONE",
        benefit_premium_share_cents=benefit_premium_share_cents,
    )
    employer_rb = create_employer(
        leave_year_basis="ROLLING_BACKWARD",
        state_pfl_program="NONE",
        benefit_premium_share_cents=benefit_premium_share_cents,
    )
    worksite_cal = create_worksite(
        employer_id=employer_cal["id"],
        employee_count_within_75_miles=80,
    )
    worksite_rb = create_worksite(
        employer_id=employer_rb["id"],
        employee_count_within_75_miles=80,
    )
    employee_cal = create_employee(
        employer_id=employer_cal["id"],
        worksite_id=worksite_cal["id"],
        hire_date=hire_date,
        hours_worked_trailing_12mo=hours_worked_trailing_12mo,
        monthly_wage_cents=monthly_wage_cents,
    )
    employee_rb = create_employee(
        employer_id=employer_rb["id"],
        worksite_id=worksite_rb["id"],
        hire_date=hire_date,
        hours_worked_trailing_12mo=hours_worked_trailing_12mo,
        monthly_wage_cents=monthly_wage_cents,
    )
    return {
        "employer_calendar": employer_cal,
        "employer_rolling": employer_rb,
        "worksite_calendar": worksite_cal,
        "worksite_rolling": worksite_rb,
        "employee_calendar": employee_cal,
        "employee_rolling": employee_rb,
    }


def approve_case_with_specific_instances(
    *,
    employee_id: str,
    reason: str,
    leave_pattern: str,
    requested_start_date: str,
    expected_end_date: str,
    instance_dates: List[str],
    hours_per_instance: int = 8,
    pfl_claim_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Submit a LeaveCase, complete certification if needed, log
    PROPOSED instances with given dates, then APPROVE.

    Returns dict with keys: case, cert, instances.
    """
    requires_cert = reason in ("OWN_SERIOUS_HEALTH", "FAMILY_SERIOUS_HEALTH")
    case = submit_leave_case(
        employee_id=employee_id,
        reason=reason,
        leave_pattern=leave_pattern,
        requested_start_date=requested_start_date,
        expected_end_date=expected_end_date,
        pfl_claim_id=pfl_claim_id,
    )
    cert = None
    if requires_cert:
        cert = submit_certification(
            leave_case_id=case["id"],
            employee_id=employee_id,
            serious_health_condition=True,
        )
        cert = review_certification(
            leave_case_id=case["id"], cert_id=cert["id"],
            decision="ACCEPT",
        )
    instances: List[Dict[str, Any]] = []
    for d in instance_dates:
        inst = log_instance(
            leave_case_id=case["id"],
            employee_id=employee_id,
            instance_date=d,
            hours_used=hours_per_instance,
        )
        instances.append(inst)
    case = review_leave_case(
        leave_case_id=case["id"], decision="APPROVE",
    )
    return {"case": case, "cert": cert, "instances": instances}


def setup_quota_near_threshold(
    *,
    consumed_hours: int,
    leave_year_basis: str = "CALENDAR",
    requested_start_date: str = "2026-07-01",
    expected_end_date: str = "2026-07-31",
    initial_clock_iso: str = "2026-01-02T00:00:00.000Z",
) -> Dict[str, Any]:
    """Build an Employee whose APPROVED instances already consume
    `consumed_hours` of the FMLA bucket in the same leave year as
    requested_start_date.

    Internally: creates employer/worksite/employee anchored at the
    start of the leave year (2026-01-02 by default), submits and
    approves a baseline LeaveCase whose APPROVED instances sum to
    `consumed_hours`. Then submits a SECOND case at the supplied
    `requested_start_date` (still PENDING_CERTIFICATION with a COMPLETE
    certification) so boundary tests can post instances on it.

    Clock is advanced to a point inside the baseline range so the
    `requested_start_date >= now()` precondition holds for both case
    submissions, and the baseline case's instances can be approved.

    Returns dict with keys: employer, worksite, employee, baseline_case,
    new_case, baseline_instances.
    """
    employer, worksite, employee = setup_eligible_employee(
        leave_year_basis=leave_year_basis,
        state_pfl_program="NONE",
        initial_clock_iso=initial_clock_iso,
    )
    # Build a baseline APPROVED case whose APPROVED instances sum to
    # consumed_hours. Use 8h chunks (allowed per PRD §3.4).
    chunks = consumed_hours // 8
    remainder = consumed_hours - chunks * 8
    # Build a baseline window inside the same calendar year as the
    # new case (2026) and AFTER the current clock — 2026-01-05..
    # several months in.
    base_dates: List[str] = []
    base_year, base_month, base_day = 2026, 1, 5
    cur_day, cur_month = base_day, base_month
    for _ in range(chunks):
        base_dates.append(date_str(base_year, cur_month, cur_day))
        cur_day += 1
        if cur_day > 28:
            cur_day = 1
            cur_month += 1
    baseline_start = date_str(base_year, base_month, base_day)
    baseline_end = date_str(base_year, cur_month, max(cur_day - 1, base_day))

    baseline = approve_case_with_specific_instances(
        employee_id=employee["id"],
        reason="OWN_SERIOUS_HEALTH",
        leave_pattern="INTERMITTENT",
        requested_start_date=baseline_start,
        expected_end_date=baseline_end,
        instance_dates=base_dates,
        hours_per_instance=8,
    )
    if remainder > 0:
        # PRD §3.4: 1 <= hours_used <= 24 — log one more instance on a
        # distinct calendar day with the remainder hours. The
        # baseline case is now APPROVED; logging a NEW instance under
        # an APPROVED parent auto-becomes APPROVED per §2.8 cascade
        # narrative. Choose a date after the last existing instance.
        cur_day += 1
        extra_date = date_str(base_year, cur_month, cur_day)
        extra_inst = log_instance(
            leave_case_id=baseline["case"]["id"],
            employee_id=employee["id"],
            instance_date=extra_date,
            hours_used=remainder,
            as_role="HRSpecialist",
        )
        baseline["instances"].append(extra_inst)

    # Now submit a NEW PENDING_CERTIFICATION case with COMPLETE cert.
    new_case = submit_leave_case(
        employee_id=employee["id"],
        reason="OWN_SERIOUS_HEALTH",
        leave_pattern="INTERMITTENT",
        requested_start_date=requested_start_date,
        expected_end_date=expected_end_date,
    )
    new_cert = submit_certification(
        leave_case_id=new_case["id"],
        employee_id=employee["id"],
        serious_health_condition=True,
    )
    review_certification(
        leave_case_id=new_case["id"],
        cert_id=new_cert["id"],
        decision="ACCEPT",
    )
    new_case = get_leave_case(new_case["id"])
    return {
        "employer": employer,
        "worksite": worksite,
        "employee": employee,
        "baseline_case": baseline["case"],
        "baseline_instances": baseline["instances"],
        "new_case": new_case,
    }


def setup_invoice_forfeit_cascade(
    *,
    initial_clock_iso: str = "2026-01-01T00:00:00.000Z",
    requested_start_date: str = "2026-01-15",
    expected_end_date: str = "2026-04-30",
    benefit_premium_share_cents: int = 30_000,
) -> Dict[str, Any]:
    """Build a CONTINUOUS APPROVED case so a BenefitInvoice is issued
    at approval; record the invoice's created_at for downstream clock
    advances.

    Returns dict with keys: employer, worksite, employee, case, invoice.
    """
    advance_clock_to(initial_clock_iso)
    employer = create_employer(
        leave_year_basis="CALENDAR",
        state_pfl_program="NONE",
        benefit_premium_share_cents=benefit_premium_share_cents,
    )
    worksite = create_worksite(
        employer_id=employer["id"],
        employee_count_within_75_miles=80,
    )
    employee = create_employee(
        employer_id=employer["id"],
        worksite_id=worksite["id"],
        hire_date="2023-01-01",
        hours_worked_trailing_12mo=2080,
        monthly_wage_cents=500_000,
    )
    case = submit_leave_case(
        employee_id=employee["id"],
        reason="OWN_SERIOUS_HEALTH",
        leave_pattern="CONTINUOUS",
        requested_start_date=requested_start_date,
        expected_end_date=expected_end_date,
    )
    cert = submit_certification(
        leave_case_id=case["id"],
        employee_id=employee["id"],
        serious_health_condition=True,
    )
    review_certification(
        leave_case_id=case["id"], cert_id=cert["id"], decision="ACCEPT",
    )
    case = review_leave_case(
        leave_case_id=case["id"], decision="APPROVE",
    )
    invoices = list_benefit_invoices(case["id"])
    assert invoices, (
        f"Setup failed: expected at least one BenefitInvoice on APPROVE; "
        f"got none for case {case['id']!r}"
    )
    return {
        "employer": employer,
        "worksite": worksite,
        "employee": employee,
        "case": case,
        "invoice": invoices[0],
    }


__all__ = [
    # Clock
    "advance_clock_to",
    # Read helpers
    "get_leave_case", "get_employer", "get_employee", "get_pfl_claim",
    "get_quota_balance",
    "list_benefit_invoices", "list_audit_events", "list_leave_cases",
    # Tier 0
    "create_employer", "create_worksite", "create_employee",
    "patch_worksite_headcount", "post_hours_snapshot",
    # Tier 2 actions
    "submit_leave_case",
    "submit_certification", "review_certification",
    "review_leave_case",
    "log_instance", "void_instance",
    "cancel_case", "return_case", "restore_job",
    "pay_invoice", "create_pfl_claim",
    # Tier 1 + 3 composites
    "setup_employer_worksite_employee",
    "setup_eligible_employee",
    "setup_pending_certification_case",
    "setup_case_with_complete_certification",
    "setup_approved_case",
    "setup_active_case",
    "setup_completed_case",
    # Tier 4 difficulty-design helpers
    "setup_two_employees_same_basis_diff_employer",
    "approve_case_with_specific_instances",
    "setup_quota_near_threshold",
    "setup_invoice_forfeit_cascade",
]
