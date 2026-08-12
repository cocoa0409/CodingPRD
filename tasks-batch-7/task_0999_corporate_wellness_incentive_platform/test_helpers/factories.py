"""Payload factories — one per creatable resource, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "EMPLOYER_NAME": "Acme",
    "PROGRAM_NAME": "PY2026",
    "PLAN_YEAR_START": "2026-01-01",
    "PLAN_YEAR_END": "2027-01-01",
    "DEPARTMENT": "ENG",
    "HIRE_DATE": "2024-03-01",
    "DEVICE_SOURCE": "fitbit",
    "CLINIC_LOCATION": "HQ",
    "VENDOR_NAME": "WellCo",
    "VENDOR_PERIOD_START": "2026-05-01",
    "VENDOR_PERIOD_END": "2026-05-31",
}


def create_employer_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["EMPLOYER_NAME"],
        "annual_self_only_premium_cents": 120000,
        "tobacco_surcharge_cents": 50000,
        "pmpm_fee_cents": 10000,
        "coaching_session_fee_cents": 7500,
        "k_anonymity_threshold": 5,
        "kiosk_capacity": 2,
        "invoice_approval_limit_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_program_payload(employer_id: str, **overrides) -> dict:
    defaults = {
        "employer_id": employer_id,
        "name": DEFAULTS["PROGRAM_NAME"],
        "plan_year_start": DEFAULTS["PLAN_YEAR_START"],
        "plan_year_end": DEFAULTS["PLAN_YEAR_END"],
        "bronze_threshold": 500,
        "silver_threshold": 1500,
        "gold_threshold": 3000,
        "bronze_award_cents": 10000,
        "silver_award_cents": 30000,
        "gold_award_cents": 60000,
        "premium_cap_pct": 0.30,
        "coaching_required_sessions": 4,
    }
    defaults.update(overrides)
    return defaults


def create_employee_payload(employer_id: str, n: int = 1, **overrides) -> dict:
    defaults = {
        "employer_id": employer_id,
        "email": f"e{n}@acme.com",
        "full_name": f"Employee {n}",
        "department": DEFAULTS["DEPARTMENT"],
        "hire_date": DEFAULTS["HIRE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(program_id: str, employee_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "employee_id": employee_id,
    }
    defaults.update(overrides)
    return defaults


def create_hra_payload(enrollment_id: str, answers=None, **overrides) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "answers": answers if answers is not None else [2] * 10,
    }
    defaults.update(overrides)
    return defaults


def create_screening_payload(enrollment_id: str, **overrides) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "clinic_location": DEFAULTS["CLINIC_LOCATION"],
        "slot_start": "2026-04-20T10:00:00Z",
        "slot_end": "2026-04-20T10:30:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_screening_result_payload(**overrides) -> dict:
    defaults = {
        "bmi": 29.0,
        "systolic_bp": 139,
        "total_cholesterol": 199,
        "glucose": 110,
    }
    defaults.update(overrides)
    return defaults


def create_challenge_payload(program_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "name": "Spring Steps",
        "activity_type": "STEPS",
        "goal_quantity": 100000,
        "points_reward": 250,
        "starts_at": "2026-04-01T00:00:00Z",
        "ends_at": "2026-06-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_participation_payload(challenge_id: str, enrollment_id: str, **overrides) -> dict:
    defaults = {
        "challenge_id": challenge_id,
        "enrollment_id": enrollment_id,
    }
    defaults.update(overrides)
    return defaults


def create_activity_event_payload(enrollment_id: str, external_event_id: str, **overrides) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "device_source": DEFAULTS["DEVICE_SOURCE"],
        "external_event_id": external_event_id,
        "activity_type": "STEPS",
        "quantity": 100000,
        "occurred_at": "2026-04-15T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_adjustment_payload(points_delta: int, reason: str, expected_enrollment_version: int,
                              **overrides) -> dict:
    defaults = {
        "points_delta": points_delta,
        "reason": reason,
        "expected_enrollment_version": expected_enrollment_version,
    }
    defaults.update(overrides)
    return defaults


def create_referral_payload(enrollment_id: str, reason: str = "HIGH_RISK", **overrides) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "reason": reason,
    }
    defaults.update(overrides)
    return defaults


def create_session_payload(session_date: str = "2026-04-02", duration_minutes: int = 30,
                           **overrides) -> dict:
    defaults = {
        "session_date": session_date,
        "duration_minutes": duration_minutes,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(program_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "vendor_name": DEFAULTS["VENDOR_NAME"],
        "period_start": DEFAULTS["VENDOR_PERIOD_START"],
        "period_end": DEFAULTS["VENDOR_PERIOD_END"],
    }
    defaults.update(overrides)
    return defaults


def create_invoice_adjustment_payload(amount_cents: int, note: str, **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
        "note": note,
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(program_id: str, department: str = None, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "department": department or DEFAULTS["DEPARTMENT"],
    }
    defaults.update(overrides)
    return defaults


def compute_awards_payload(program_id: str, **overrides) -> dict:
    defaults = {"program_id": program_id}
    defaults.update(overrides)
    return defaults
