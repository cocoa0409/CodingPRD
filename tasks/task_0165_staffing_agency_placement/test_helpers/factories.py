"""Payload factories — one per entity, input fields only.

Each factory provides sensible PRD-valid defaults and accepts **overrides for
the values a test needs to control.
"""

DEFAULTS = {
    "CLIENT_NAME": "Acme",
    "CREDIT_LIMIT_CENTS": 100_000_000,
    "SKILL_CODE": "JAVA",
    "SKILL_CATEGORY": "TECH",
    "CANDIDATE_NAME": "Cara Dev",
    "BASE_PAY_RATE_CENTS": 8000,
    "JOB_TITLE": "Dev",
    "BILL_RATE_CENTS": 12000,
    "TARGET_PAY_RATE_CENTS": 8000,
    "SUBMITTED_PAY_RATE_CENTS": 8000,
    "STANDARD_WEEKLY_HOURS": 40,
    "START_DATE": "2026-06-15T00:00:00Z",
    "END_DATE": "2026-12-15T00:00:00Z",
    "INTERVIEW_START": "2026-06-10T14:00:00Z",
    "INTERVIEW_END": "2026-06-10T15:00:00Z",
    "WEEK_START": "2026-06-15T00:00:00Z",
    "WEEK_END": "2026-06-22T00:00:00Z",
    "HOURS": 40,
}


def create_client_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["CLIENT_NAME"],
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_skill_payload(**overrides) -> dict:
    payload = {
        "code": DEFAULTS["SKILL_CODE"],
        "category": DEFAULTS["SKILL_CATEGORY"],
    }
    payload.update(overrides)
    return payload


def create_candidate_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["CANDIDATE_NAME"],
        "skill_codes": [DEFAULTS["SKILL_CODE"]],
        "base_pay_rate_cents": DEFAULTS["BASE_PAY_RATE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_job_order_payload(client_id: str, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "title": DEFAULTS["JOB_TITLE"],
        "employment_type": "TEMP",
        "required_skill_code": DEFAULTS["SKILL_CODE"],
        "openings": 1,
        "bill_rate_cents": DEFAULTS["BILL_RATE_CENTS"],
        "target_pay_rate_cents": DEFAULTS["TARGET_PAY_RATE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_submission_payload(job_order_id: str, candidate_id: str, **overrides) -> dict:
    payload = {
        "job_order_id": job_order_id,
        "candidate_id": candidate_id,
        "submitted_pay_rate_cents": DEFAULTS["SUBMITTED_PAY_RATE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_interview_payload(**overrides) -> dict:
    payload = {
        "scheduled_start": DEFAULTS["INTERVIEW_START"],
        "scheduled_end": DEFAULTS["INTERVIEW_END"],
    }
    payload.update(overrides)
    return payload


def create_placement_payload(submission_id: str, expected_job_order_version: int, **overrides) -> dict:
    payload = {
        "submission_id": submission_id,
        "start_date": DEFAULTS["START_DATE"],
        "end_date": DEFAULTS["END_DATE"],
        "expected_job_order_version": expected_job_order_version,
        "standard_weekly_hours": DEFAULTS["STANDARD_WEEKLY_HOURS"],
    }
    payload.update(overrides)
    return payload


def create_timesheet_payload(placement_id: str, **overrides) -> dict:
    payload = {
        "placement_id": placement_id,
        "week_start": DEFAULTS["WEEK_START"],
        "week_end": DEFAULTS["WEEK_END"],
        "hours": DEFAULTS["HOURS"],
    }
    payload.update(overrides)
    return payload


def create_invoice_payload(client_id: str, **overrides) -> dict:
    payload = {"client_id": client_id}
    payload.update(overrides)
    return payload


def create_line_item_payload(timesheet_id: str, **overrides) -> dict:
    payload = {"timesheet_id": timesheet_id}
    payload.update(overrides)
    return payload


def convert_payload(annual_salary_cents: int, **overrides) -> dict:
    payload = {"annual_salary_cents": annual_salary_cents}
    payload.update(overrides)
    return payload
