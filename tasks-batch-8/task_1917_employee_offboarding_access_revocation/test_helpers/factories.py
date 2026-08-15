"""Payload factories — input fields only (no computed/system fields)."""

DEFAULTS = {
    "EMPLOYEE_REF": "E-001",
    "CASE_TYPE": "RESIGNATION",
    "WORK_STATE_CODE": "CA",
    "NOTICE_RECEIVED_DATE": "2026-08-01T00:00:00Z",
    "REQUESTED_LAST_DAY": "2026-08-10T00:00:00Z",
    "PTO_BALANCE_HOURS": 0.0,
    "TENURE_YEARS": 1.0,
    "HOURLY_WAGE_CENTS": 5000,
    "INTAKE_HR_REF": "hr-intake-1",
}


def create_case_payload(**overrides) -> dict:
    defaults = {
        "employee_ref": DEFAULTS["EMPLOYEE_REF"],
        "case_type": DEFAULTS["CASE_TYPE"],
        "work_state_code": DEFAULTS["WORK_STATE_CODE"],
        "notice_received_date": DEFAULTS["NOTICE_RECEIVED_DATE"],
        "requested_last_day": DEFAULTS["REQUESTED_LAST_DAY"],
        "pto_balance_hours": DEFAULTS["PTO_BALANCE_HOURS"],
        "tenure_years": DEFAULTS["TENURE_YEARS"],
        "hourly_wage_cents": DEFAULTS["HOURLY_WAGE_CENTS"],
        "intake_hr_ref": DEFAULTS["INTAKE_HR_REF"],
    }
    defaults.update(overrides)
    return defaults


def create_revocation_task_payload(**overrides) -> dict:
    defaults = {
        "offboarding_case_id": "",
        "system_name": "EMAIL",
        "sequence_rank": 1,
    }
    defaults.update(overrides)
    return defaults


def create_asset_item_payload(**overrides) -> dict:
    defaults = {
        "offboarding_case_id": "",
        "asset_tag": "ASSET-1",
        "asset_kind": "LAPTOP",
        "replacement_cost_cents": 100000,
        "issued_date": "2026-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_exit_interview_payload(**overrides) -> dict:
    defaults = {
        "offboarding_case_id": "",
        "interviewer_ref": "hr-int-1",
        "scheduled_start": "2026-08-05T10:00:00Z",
        "scheduled_end": "2026-08-05T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_kt_session_payload(**overrides) -> dict:
    defaults = {
        "knowledge_transfer_plan_id": "",
        "topic": "session topic",
        "scheduled_start": "2026-08-05T10:00:00Z",
        "scheduled_end": "2026-08-05T11:00:00Z",
        "successor_ref": "succ-1",
    }
    defaults.update(overrides)
    return defaults


def create_benefits_notice_payload(**overrides) -> dict:
    defaults = {
        "offboarding_case_id": "",
        "notice_kind": "COBRA_ELECTION",
    }
    defaults.update(overrides)
    return defaults


def create_covenant_ack_payload(**overrides) -> dict:
    defaults = {
        "offboarding_case_id": "",
        "covenant_kind": "NON_COMPETE",
    }
    defaults.update(overrides)
    return defaults


def submit_rehire_review_payload(**overrides) -> dict:
    defaults = {
        "recommended_code": "ELIGIBLE",
        "rationale": "solid performer",
    }
    defaults.update(overrides)
    return defaults
