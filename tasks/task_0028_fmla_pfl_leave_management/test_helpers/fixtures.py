"""Composite setup helpers for the FMLA/PFL Leave Management benchmark.

Every helper builds its preconditions from scratch through PRD-declared endpoints
(see PRD §3.1–§3.8). The runner restarts the API server before every individual
pytest test, so each test starts from an empty database — no entities, no clock
state. These helpers use `get_success_data()` (lenient validator) so a setup
failure surfaces as a clear "Setup failed" trace rather than a cryptic assertion
deep inside a test.

Identity threading (PRD §2.1): HRAdmin and PlatformAdmin are opaque roles; their
shared TEST_USERS headers are canonical. Employee and HealthcareProvider are
entity_backed: ownership-gated calls MUST use make_employee_headers(employee_id)
or make_provider_headers(provider_id).
"""
from dataclasses import dataclass
from typing import Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    apply_payment_payload,
    approve_case_payload,
    create_case_payload,
    create_certification_payload,
    create_employee_payload,
    create_employer_payload,
    create_interval_payload,
    create_provider_payload,
    mark_insufficient_payload,
    patch_health_enrollment_payload,
    seed_historic_interval_payload,
    set_clock_payload,
)
from .test_users import (
    make_hr_admin_headers,
    make_platform_admin_headers,
    make_provider_headers,
)


# ─── Tier 0: clock control (PRD §3.8) ───────────────────────────────────────


def set_clock(iso8601: str) -> dict:
    """POST /_clock/set_current_utc as PlatformAdmin (PRD §3.8)."""
    res = api_client.set_clock(set_clock_payload(iso8601), make_platform_admin_headers())
    return get_success_data(res)


# ─── Tier 1: bootstrap base entities (PRD §3.1, §3.3, §3.5) ─────────────────


def create_employer(**overrides) -> dict:
    """POST /leave/employers as PlatformAdmin (PRD §3.1)."""
    res = api_client.create_employer(
        create_employer_payload(**overrides), make_platform_admin_headers()
    )
    return get_success_data(res)


def create_employee(employer_id: str, **overrides) -> dict:
    """POST /leave/employees as HRAdmin (PRD §3.3)."""
    res = api_client.create_employee(
        create_employee_payload(employer_id, **overrides), make_hr_admin_headers()
    )
    return get_success_data(res)


def create_provider(**overrides) -> dict:
    """POST /leave/providers as PlatformAdmin (PRD §3.5)."""
    res = api_client.create_provider(
        create_provider_payload(**overrides), make_platform_admin_headers()
    )
    return get_success_data(res)


# ─── Tier 2: case lifecycle building blocks (PRD §3.4–§3.6) ─────────────────


def submit_case(employee_id: str, **overrides) -> dict:
    """POST /leave/cases as HRAdmin (PRD §3.4)."""
    res = api_client.create_case(
        create_case_payload(employee_id, **overrides), make_hr_admin_headers()
    )
    return get_success_data(res)


def evaluate_eligibility(case_id: str) -> dict:
    """POST /leave/cases/{id}/evaluate-eligibility as HRAdmin (PRD §3.3)."""
    res = api_client.evaluate_eligibility(case_id, make_hr_admin_headers())
    return get_success_data(res)


def submit_certification(
    case_id: str, provider_id: str, **overrides
) -> dict:
    """POST /leave/certifications as HealthcareProvider bound to provider_id (PRD §2.1, §3.5)."""
    res = api_client.create_certification(
        create_certification_payload(case_id, provider_id, **overrides),
        make_provider_headers(provider_id),
    )
    return get_success_data(res)


def receive_certification(cert_id: str) -> dict:
    """POST /leave/certifications/{id}/receive as HRAdmin (PRD §3.5)."""
    res = api_client.receive_certification(cert_id, make_hr_admin_headers())
    return get_success_data(res)


def mark_certification_complete(cert_id: str) -> dict:
    """POST /leave/certifications/{id}/mark-complete as HRAdmin (PRD §3.5)."""
    res = api_client.mark_certification_complete(cert_id, make_hr_admin_headers())
    return get_success_data(res)


def mark_certification_insufficient(cert_id: str, reason: str) -> dict:
    """POST /leave/certifications/{id}/mark-insufficient as HRAdmin (PRD §3.5)."""
    res = api_client.mark_certification_insufficient(
        cert_id, mark_insufficient_payload(reason), make_hr_admin_headers()
    )
    return get_success_data(res)


def approve_case(case_id: str, expected_version: int) -> dict:
    """POST /leave/cases/{id}/approve as HRAdmin (PRD §2.8, §3.4)."""
    res = api_client.approve_case(
        case_id, approve_case_payload(expected_version), make_hr_admin_headers()
    )
    return get_success_data(res)


def deny_case(case_id: str) -> dict:
    """POST /leave/cases/{id}/deny as HRAdmin (PRD §3.4)."""
    res = api_client.deny_case(case_id, make_hr_admin_headers())
    return get_success_data(res)


def record_interval(
    case_id: str, start_dt: str, end_dt: str, hours_taken: float
) -> dict:
    """POST /leave/intervals as HRAdmin (PRD §3.6)."""
    res = api_client.create_interval(
        create_interval_payload(case_id, start_dt, end_dt, hours_taken),
        make_hr_admin_headers(),
    )
    return get_success_data(res)


def reverse_interval(interval_id: str) -> dict:
    """POST /leave/intervals/{id}/reverse as HRAdmin (PRD §3.6)."""
    res = api_client.reverse_interval(interval_id, make_hr_admin_headers())
    return get_success_data(res)


def complete_case(case_id: str) -> dict:
    """POST /leave/cases/{id}/complete as HRAdmin (PRD §3.6)."""
    res = api_client.complete_case(case_id, make_hr_admin_headers())
    return get_success_data(res)


def restore_case(case_id: str) -> dict:
    """POST /leave/cases/{id}/restore as HRAdmin (PRD §3.6)."""
    res = api_client.restore_case(case_id, make_hr_admin_headers())
    return get_success_data(res)


def forfeit_restoration(case_id: str) -> dict:
    """POST /leave/cases/{id}/forfeit-restoration as HRAdmin (PRD §3.6)."""
    res = api_client.forfeit_restoration(case_id, make_hr_admin_headers())
    return get_success_data(res)


def request_recertification(case_id: str) -> dict:
    """POST /leave/cases/{id}/request-recertification as HRAdmin (PRD §3.5)."""
    res = api_client.request_recertification(case_id, make_hr_admin_headers())
    return get_success_data(res)


def seed_historic_interval(
    case_id: str,
    start_dt: str,
    end_dt: str,
    hours_taken: float,
    fmla_hours_charged: float,
    pfl_hours_charged: float,
) -> dict:
    """POST /_intervals/seed-historic as PlatformAdmin (PRD §3.8)."""
    res = api_client.seed_historic_interval(
        seed_historic_interval_payload(
            case_id,
            start_dt,
            end_dt,
            hours_taken,
            fmla_hours_charged,
            pfl_hours_charged,
        ),
        make_platform_admin_headers(),
    )
    return get_success_data(res)


def get_case(case_id: str) -> dict:
    """GET /leave/cases/{id} as HRAdmin (PRD §3.4)."""
    res = api_client.get_case(case_id, make_hr_admin_headers())
    return get_success_data(res)


def get_employee(employee_id: str) -> dict:
    """GET /leave/employees/{id} as HRAdmin (PRD §3.3)."""
    res = api_client.get_employee(employee_id, make_hr_admin_headers())
    return get_success_data(res)


def get_certification(cert_id: str) -> dict:
    """GET /leave/certifications/{id} as HRAdmin (PRD §3.5)."""
    res = api_client.get_certification(cert_id, make_hr_admin_headers())
    return get_success_data(res)


def list_benefit_ledgers_for_case(case_id: str) -> list:
    """GET /leave/benefit-ledgers?leave_case_id=... as HRAdmin (PRD §3.7)."""
    res = api_client.list_benefit_ledgers(
        make_hr_admin_headers(), params={"leave_case_id": case_id}
    )
    return get_success_data(res)


def list_notices_for_case(case_id: str, notice_type: Optional[str] = None) -> list:
    """GET /leave/notices?leave_case_id=... as HRAdmin (PRD §2.10)."""
    params = {"leave_case_id": case_id}
    if notice_type is not None:
        params["notice_type"] = notice_type
    res = api_client.list_notices(make_hr_admin_headers(), params=params)
    return get_success_data(res)


def apply_payment(ledger_id: str, amount_cents: int) -> dict:
    """POST /leave/benefit-ledgers/{id}/apply-payment as HRAdmin (PRD §3.7)."""
    res = api_client.apply_payment(
        ledger_id, apply_payment_payload(amount_cents), make_hr_admin_headers()
    )
    return get_success_data(res)


def patch_health_enrollment(
    employee_id: str, health_plan_enrolled: bool, expected_version: int
) -> dict:
    """PATCH /leave/employees/{id}/health-enrollment as HRAdmin (PRD §3.3)."""
    res = api_client.patch_employee_health_enrollment(
        employee_id,
        patch_health_enrollment_payload(health_plan_enrolled, expected_version),
        make_hr_admin_headers(),
    )
    return get_success_data(res)


def terminate_employee(employee_id: str) -> dict:
    """POST /leave/employees/{id}/terminate as HRAdmin (PRD §3.3)."""
    res = api_client.terminate_employee(employee_id, make_hr_admin_headers())
    return get_success_data(res)


# ─── Tier 3: composite scenarios ─────────────────────────────────────────────


@dataclass
class ApprovedCaseBundle:
    """Bundle returned by setup_approved_case — every primary id captured."""

    employer: dict
    provider: dict
    employee: dict
    case: dict  # state == APPROVED
    certification: dict  # certification_status == COMPLETE
    case_version_post_eligibility: int


def setup_approved_case(
    *,
    employer_state: str = "FED",
    fmla_method: Optional[str] = None,
    employer_premium_share_pct: float = 0.50,
    monthly_premium_total_cents: int = 80000,
    employee_home_state: Optional[str] = None,
    hire_date: str = "2024-01-01T00:00:00.000Z",
    hours_worked: int = 2000,
    health_plan_enrolled: Optional[bool] = None,
    qualifying_reason: str = "OWN_SERIOUS_HEALTH_CONDITION",
    leave_type: str = "CONTINUOUS",
    requested_start_at: str = "2026-06-01T00:00:00.000Z",
    requested_end_at: str = "2026-07-01T00:00:00.000Z",
    submission_clock: str = "2026-05-01T00:00:00.000Z",
    cert_expected_duration_weeks: float = 4,
    cert_signed_at: str = "2026-05-15T00:00:00.000Z",
    cert_intermittent_frequency_per_month: Optional[int] = None,
    cert_intermittent_hours_per_episode: Optional[float] = None,
) -> ApprovedCaseBundle:
    """Build an APPROVED LeaveCase from scratch.

    Sequence (PRD §3.1, §3.3, §3.4, §3.5):
      1. PlatformAdmin creates an Employer.
      2. PlatformAdmin creates a HealthcareProvider.
      3. HRAdmin creates an Employee (default 2000 hours, hire_date well past 12 months).
      4. PlatformAdmin sets the clock to a pre-leave instant so requested_start_at is future.
      5. HRAdmin submits the case → auto-advances to ELIGIBILITY_PENDING.
      6. HRAdmin evaluates eligibility → CERTIFICATION_PENDING.
      7. HealthcareProvider submits a certification → PENDING.
      8. HRAdmin marks it RECEIVED, then COMPLETE.
      9. HRAdmin approves the case carrying expected_leave_case_version.
    """
    if employee_home_state is None:
        employee_home_state = employer_state

    emp_overrides = {
        "state_code": employer_state,
        "employer_premium_share_pct": employer_premium_share_pct,
        "monthly_premium_total_cents": monthly_premium_total_cents,
    }
    if fmla_method is not None:
        emp_overrides["fmla_method"] = fmla_method
    employer = create_employer(**emp_overrides)

    provider = create_provider()

    employee_overrides = {
        "hire_date": hire_date,
        "hours_worked_trailing_12mo": hours_worked,
        "home_state_code": employee_home_state,
    }
    if health_plan_enrolled is not None:
        employee_overrides["health_plan_enrolled"] = health_plan_enrolled
    employee = create_employee(employer["id"], **employee_overrides)

    set_clock(submission_clock)

    case = submit_case(
        employee["id"],
        qualifying_reason=qualifying_reason,
        leave_type=leave_type,
        requested_start_at=requested_start_at,
        requested_end_at=requested_end_at,
    )

    case_after_elig = evaluate_eligibility(case["id"])
    version_post_elig = case_after_elig["version"]

    cert_overrides = {
        "expected_duration_weeks": cert_expected_duration_weeks,
        "provider_attestation_signed_at": cert_signed_at,
    }
    if cert_intermittent_frequency_per_month is not None:
        cert_overrides["intermittent_frequency_per_month"] = (
            cert_intermittent_frequency_per_month
        )
    if cert_intermittent_hours_per_episode is not None:
        cert_overrides["intermittent_hours_per_episode"] = (
            cert_intermittent_hours_per_episode
        )
    certification = submit_certification(case["id"], provider["id"], **cert_overrides)

    receive_certification(certification["id"])
    cert_complete = mark_certification_complete(certification["id"])

    case_approved = approve_case(case["id"], version_post_elig)

    return ApprovedCaseBundle(
        employer=employer,
        provider=provider,
        employee=employee,
        case=case_approved,
        certification=cert_complete,
        case_version_post_eligibility=version_post_elig,
    )


def setup_active_case_with_first_interval(
    *,
    employer_state: str = "FED",
    fmla_method: Optional[str] = None,
    employer_premium_share_pct: float = 0.50,
    monthly_premium_total_cents: int = 80000,
    qualifying_reason: str = "OWN_SERIOUS_HEALTH_CONDITION",
    leave_type: str = "CONTINUOUS",
    requested_start_at: str = "2026-06-01T00:00:00.000Z",
    requested_end_at: str = "2026-08-15T00:00:00.000Z",
    submission_clock: str = "2026-05-01T00:00:00.000Z",
    interval_start: str = "2026-06-01T00:00:00.000Z",
    interval_end: str = "2026-06-08T00:00:00.000Z",
    interval_hours: float = 40,
    cert_expected_duration_weeks: float = 10,
    cert_signed_at: str = "2026-05-15T00:00:00.000Z",
) -> dict:
    """Approved case + clock advanced to requested_start_at + first interval recorded.

    The first interval transitions the case from APPROVED → ACTIVE and the Employee
    from ACTIVE → ON_LEAVE (PRD §3.6). Returns dict containing employer, provider,
    employee, case (post-interval), interval, and certification.
    """
    bundle = setup_approved_case(
        employer_state=employer_state,
        fmla_method=fmla_method,
        employer_premium_share_pct=employer_premium_share_pct,
        monthly_premium_total_cents=monthly_premium_total_cents,
        qualifying_reason=qualifying_reason,
        leave_type=leave_type,
        requested_start_at=requested_start_at,
        requested_end_at=requested_end_at,
        submission_clock=submission_clock,
        cert_expected_duration_weeks=cert_expected_duration_weeks,
        cert_signed_at=cert_signed_at,
    )
    set_clock(interval_start)
    interval = record_interval(bundle.case["id"], interval_start, interval_end, interval_hours)
    case_after = get_case(bundle.case["id"])
    return {
        "employer": bundle.employer,
        "provider": bundle.provider,
        "employee": bundle.employee,
        "case": case_after,
        "interval": interval,
        "certification": bundle.certification,
        "case_version_post_eligibility": bundle.case_version_post_eligibility,
    }


def setup_case_in_certification_pending(
    *,
    qualifying_reason: str = "OWN_SERIOUS_HEALTH_CONDITION",
    leave_type: str = "CONTINUOUS",
    requested_start_at: str = "2026-06-01T00:00:00.000Z",
    requested_end_at: str = "2026-07-01T00:00:00.000Z",
    submission_clock: str = "2026-05-01T00:00:00.000Z",
    employer_state: str = "FED",
    hours_worked: int = 2000,
) -> dict:
    """Build case all the way to CERTIFICATION_PENDING (eligible) — no cert yet.

    Returns dict with employer, provider, employee, case, version (post-elig).
    """
    employer = create_employer(state_code=employer_state)
    provider = create_provider()
    employee = create_employee(
        employer["id"],
        hours_worked_trailing_12mo=hours_worked,
        home_state_code=employer_state,
    )
    set_clock(submission_clock)
    case = submit_case(
        employee["id"],
        qualifying_reason=qualifying_reason,
        leave_type=leave_type,
        requested_start_at=requested_start_at,
        requested_end_at=requested_end_at,
    )
    case_after_elig = evaluate_eligibility(case["id"])
    return {
        "employer": employer,
        "provider": provider,
        "employee": employee,
        "case": case_after_elig,
        "case_version_post_eligibility": case_after_elig["version"],
    }


def setup_case_in_eligibility_pending(
    *,
    qualifying_reason: str = "OWN_SERIOUS_HEALTH_CONDITION",
    leave_type: str = "CONTINUOUS",
    requested_start_at: str = "2026-06-01T00:00:00.000Z",
    requested_end_at: str = "2026-07-01T00:00:00.000Z",
    submission_clock: str = "2026-05-01T00:00:00.000Z",
    employer_state: str = "FED",
    hours_worked: int = 2000,
    hire_date: str = "2024-01-01T00:00:00.000Z",
) -> dict:
    """Submit a case and stop after the auto-advance to ELIGIBILITY_PENDING."""
    employer = create_employer(state_code=employer_state)
    employee = create_employee(
        employer["id"],
        hours_worked_trailing_12mo=hours_worked,
        hire_date=hire_date,
        home_state_code=employer_state,
    )
    set_clock(submission_clock)
    case = submit_case(
        employee["id"],
        qualifying_reason=qualifying_reason,
        leave_type=leave_type,
        requested_start_at=requested_start_at,
        requested_end_at=requested_end_at,
    )
    return {
        "employer": employer,
        "employee": employee,
        "case": case,
    }


def setup_case_with_received_insufficient_certification(
    *,
    qualifying_reason: str = "OWN_SERIOUS_HEALTH_CONDITION",
    leave_type: str = "CONTINUOUS",
    requested_start_at: str = "2026-06-01T00:00:00.000Z",
    requested_end_at: str = "2026-07-01T00:00:00.000Z",
    submission_clock: str = "2026-05-01T00:00:00.000Z",
    insufficient_reason: str = "Missing expected duration",
) -> dict:
    """Case in CERTIFICATION_PENDING with a RECEIVED→INSUFFICIENT cert."""
    base = setup_case_in_certification_pending(
        qualifying_reason=qualifying_reason,
        leave_type=leave_type,
        requested_start_at=requested_start_at,
        requested_end_at=requested_end_at,
        submission_clock=submission_clock,
    )
    cert = submit_certification(
        base["case"]["id"],
        base["provider"]["id"],
        expected_duration_weeks=4,
        provider_attestation_signed_at="2026-05-15T00:00:00.000Z",
    )
    receive_certification(cert["id"])
    cert_insuff = mark_certification_insufficient(cert["id"], insufficient_reason)
    return {**base, "certification": cert_insuff}
