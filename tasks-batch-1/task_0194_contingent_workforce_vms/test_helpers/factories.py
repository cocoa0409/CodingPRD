"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "PROGRAM_NAME": "Test Program",
    "CLIENT_NAME": "Test Client",
    "DEFAULT_MARKUP_PCT": 0.45,
    "MAX_MARKUP_PCT": 0.60,
    "TENURE_LIMIT_DAYS": 180,
    "TENURE_WARNING_DAYS": 120,
    "SUPPLIER_NAME": "Acme Staffing",
    "WORKER_NAME": "Worker One",
    "REQ_TITLE": "Engineer",
    "MAX_PAY_RATE_CENTS": 20000,
    "PAY_RATE_CENTS": 8000,
    "SOW_TITLE": "Build",
    "TOTAL_VALUE_CENTS": 100000,
    "MILESTONE_NAME": "Milestone",
}


def create_program_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PROGRAM_NAME"],
        "client_name": DEFAULTS["CLIENT_NAME"],
        "default_markup_pct": DEFAULTS["DEFAULT_MARKUP_PCT"],
        "max_markup_pct": DEFAULTS["MAX_MARKUP_PCT"],
        "coemployment_tenure_limit_days": DEFAULTS["TENURE_LIMIT_DAYS"],
        "tenure_warning_threshold_days": DEFAULTS["TENURE_WARNING_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_supplier_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "name": DEFAULTS["SUPPLIER_NAME"],
        "tier": 1,
    }
    defaults.update(overrides)
    return defaults


def create_worker_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "full_name": DEFAULTS["WORKER_NAME"],
        "national_id_hash": "h1",
    }
    defaults.update(overrides)
    return defaults


def create_requisition_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "title": DEFAULTS["REQ_TITLE"],
        "openings": 1,
        "max_pay_rate_cents": DEFAULTS["MAX_PAY_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_submittal_payload(requisition_id, supplier_id, worker_profile_id, **overrides) -> dict:
    defaults = {
        "requisition_id": requisition_id,
        "supplier_id": supplier_id,
        "worker_profile_id": worker_profile_id,
        "pay_rate_cents": DEFAULTS["PAY_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def hire_payload(expected_requisition_version, start_date, planned_end_date, **overrides) -> dict:
    defaults = {
        "expected_requisition_version": expected_requisition_version,
        "start_date": start_date,
        "planned_end_date": planned_end_date,
    }
    defaults.update(overrides)
    return defaults


def create_sow_payload(program_id, supplier_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "supplier_id": supplier_id,
        "title": DEFAULTS["SOW_TITLE"],
        "total_value_cents": DEFAULTS["TOTAL_VALUE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_milestone_payload(statement_of_work_id, **overrides) -> dict:
    defaults = {
        "statement_of_work_id": statement_of_work_id,
        "name": DEFAULTS["MILESTONE_NAME"],
        "milestone_amount_cents": 40000,
        "sequence": 1,
    }
    defaults.update(overrides)
    return defaults


def create_timesheet_payload(assignment_id, week_start_date, **overrides) -> dict:
    defaults = {
        "assignment_id": assignment_id,
        "week_start_date": week_start_date,
        "regular_hours": 40,
    }
    defaults.update(overrides)
    return defaults


def create_expense_payload(assignment_id, category, amount_cents, **overrides) -> dict:
    defaults = {
        "assignment_id": assignment_id,
        "category": category,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults
