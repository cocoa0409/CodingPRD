"""Payload factories — one per creatable entity, input fields only."""

DEFAULTS = {
    "PROGRAM_NAME": "Cards",
    "SERVICE_LINE": "CARDIOLOGY",
    "PERIOD_START": "2026-09-08",
    "PERIOD_END": "2026-09-08",
    "PAYROLL_BUDGET_CENTS": 1_000_000,
    "PHYSICIAN_NAME": "Dr Alvarez",
    "SPECIALTY": "CARDIOLOGY",
    "EMPLOYMENT_TYPE": "STAFF",
    "WINDOW_START": "2026-09-08",
    "WINDOW_END": "2026-09-08",
    "WINDOW_KIND": "VACATION",
    "ACTIVATION_REASON": "PRIMARY_NO_SHOW",
    "FAIL_REASON": "license mismatch",
}


def create_program_payload(**overrides) -> dict:
    """CallProgram create payload. Required: name, service_line, period_start,
    period_end, payroll_budget_cents. All staffing counts default to the
    single-weekday-primary shape unless overridden."""
    defaults = {
        "name": DEFAULTS["PROGRAM_NAME"],
        "service_line": DEFAULTS["SERVICE_LINE"],
        "period_start": DEFAULTS["PERIOD_START"],
        "period_end": DEFAULTS["PERIOD_END"],
        "payroll_budget_cents": DEFAULTS["PAYROLL_BUDGET_CENTS"],
        "weekday_primary_required": 1,
        "weekend_primary_required": 0,
        "holiday_primary_required": 0,
        "weekday_backup_required": 0,
        "weekend_backup_required": 0,
        "holiday_backup_required": 0,
    }
    defaults.update(overrides)
    return defaults


def create_physician_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["PHYSICIAN_NAME"],
        "specialty": DEFAULTS["SPECIALTY"],
        "employment_type": DEFAULTS["EMPLOYMENT_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_window_payload(physician_id, **overrides) -> dict:
    defaults = {
        "physician_id": physician_id,
        "start_date": DEFAULTS["WINDOW_START"],
        "end_date": DEFAULTS["WINDOW_END"],
        "kind": DEFAULTS["WINDOW_KIND"],
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(slot_id, physician_id, **overrides) -> dict:
    defaults = {"slot_id": slot_id, "physician_id": physician_id}
    defaults.update(overrides)
    return defaults


def create_swap_payload(assignment_id, **overrides) -> dict:
    defaults = {"assignment_id": assignment_id}
    defaults.update(overrides)
    return defaults


def create_requisition_payload(gap_id, **overrides) -> dict:
    defaults = {"gap_id": gap_id}
    defaults.update(overrides)
    return defaults


def activate_backup_payload(reason=DEFAULTS["ACTIVATION_REASON"]) -> dict:
    return {"reason": reason}
