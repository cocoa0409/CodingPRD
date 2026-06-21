"""Payload factories — one per entity, input fields only (PRD §3.1–§3.7)."""


def create_employer_payload(**overrides) -> dict:
    """POST /leave/employers payload (PRD §3.1)."""
    defaults = {
        "legal_name": "Test Co",
        "state_code": "FED",
        "employer_premium_share_pct": 0.50,
        "monthly_premium_total_cents": 80000,
    }
    defaults.update(overrides)
    return defaults


def create_employee_payload(employer_id: str, **overrides) -> dict:
    """POST /leave/employees payload (PRD §3.3)."""
    defaults = {
        "employer_id": employer_id,
        "email": "worker@example.com",
        "full_name": "Test Worker",
        "hire_date": "2024-01-01T00:00:00.000Z",
        "hours_worked_trailing_12mo": 2000,
        "home_state_code": "FED",
    }
    defaults.update(overrides)
    return defaults


def create_provider_payload(**overrides) -> dict:
    """POST /leave/providers payload (PRD §3.5)."""
    defaults = {
        "license_id": "L-TEST-1",
        "full_name": "Dr Test",
        "specialty": "internal",
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(employee_id: str, **overrides) -> dict:
    """POST /leave/cases payload (PRD §3.4)."""
    defaults = {
        "employee_id": employee_id,
        "qualifying_reason": "OWN_SERIOUS_HEALTH_CONDITION",
        "leave_type": "CONTINUOUS",
        "requested_start_at": "2026-06-01T00:00:00.000Z",
        "requested_end_at": "2026-07-01T00:00:00.000Z",
    }
    defaults.update(overrides)
    return defaults


def create_certification_payload(
    leave_case_id: str, provider_id: str, **overrides
) -> dict:
    """POST /leave/certifications payload (PRD §3.5)."""
    defaults = {
        "leave_case_id": leave_case_id,
        "provider_id": provider_id,
        "expected_duration_weeks": 4,
        "provider_attestation_signed_at": "2026-05-15T00:00:00.000Z",
    }
    defaults.update(overrides)
    return defaults


def approve_case_payload(expected_leave_case_version: int) -> dict:
    """POST /leave/cases/{id}/approve payload (PRD §2.8, §3.4)."""
    return {"expected_leave_case_version": expected_leave_case_version}


def patch_health_enrollment_payload(
    health_plan_enrolled: bool, expected_employee_version: int
) -> dict:
    """PATCH /leave/employees/{id}/health-enrollment payload (PRD §2.8, §3.3)."""
    return {
        "health_plan_enrolled": health_plan_enrolled,
        "expected_employee_version": expected_employee_version,
    }


def mark_insufficient_payload(insufficient_reason: str) -> dict:
    """POST /leave/certifications/{id}/mark-insufficient payload (PRD §3.5)."""
    return {"insufficient_reason": insufficient_reason}


def create_interval_payload(
    leave_case_id: str,
    start_datetime: str,
    end_datetime: str,
    hours_taken: float,
) -> dict:
    """POST /leave/intervals payload (PRD §3.6)."""
    return {
        "leave_case_id": leave_case_id,
        "start_datetime": start_datetime,
        "end_datetime": end_datetime,
        "hours_taken": hours_taken,
    }


def apply_payment_payload(amount_cents: int) -> dict:
    """POST /leave/benefit-ledgers/{id}/apply-payment payload (PRD §3.7)."""
    return {"amount_cents": amount_cents}


def set_clock_payload(to_iso8601: str) -> dict:
    """POST /_clock/set_current_utc payload (PRD §3.8)."""
    return {"to_iso8601": to_iso8601}


def seed_historic_interval_payload(
    leave_case_id: str,
    start_datetime: str,
    end_datetime: str,
    hours_taken: float,
    fmla_hours_charged: float,
    pfl_hours_charged: float,
) -> dict:
    """POST /_intervals/seed-historic payload (PRD §3.8)."""
    return {
        "leave_case_id": leave_case_id,
        "start_datetime": start_datetime,
        "end_datetime": end_datetime,
        "hours_taken": hours_taken,
        "fmla_hours_charged": fmla_hours_charged,
        "pfl_hours_charged": pfl_hours_charged,
    }
