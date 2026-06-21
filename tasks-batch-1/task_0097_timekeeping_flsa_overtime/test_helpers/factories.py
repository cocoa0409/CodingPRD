"""Payload factories — one per entity, input fields only.

Optional fields (those the PRD declares with a default) are omitted from the
defaults so factories exercise the server-side defaults; pass them via overrides
when a test needs a specific value.
"""

DEFAULTS = {
    "EMPLOYER_NAME": "Acme",
    "WORKSITE_NAME": "CA site",
    "EMPLOYEE_NAME": "Cathy",
    "BASE_RATE_CENTS": 2000,
}


def create_employer_payload(**overrides) -> dict:
    """Required: legal_name. Optional: workweek_start_dow, federal_min_wage_cents,
    federal_tipped_cash_wage_cents."""
    payload = {"legal_name": DEFAULTS["EMPLOYER_NAME"]}
    payload.update(overrides)
    return payload


def create_wage_ruleset_payload(employer_id, state_code="CA", **overrides) -> dict:
    """Required: employer_id, state_code. All thresholds/switches optional."""
    payload = {"employer_id": employer_id, "state_code": state_code}
    payload.update(overrides)
    return payload


def create_worksite_payload(employer_id, state_code="CA", **overrides) -> dict:
    """Required: employer_id, name, state_code."""
    payload = {
        "employer_id": employer_id,
        "name": DEFAULTS["WORKSITE_NAME"],
        "state_code": state_code,
    }
    payload.update(overrides)
    return payload


def create_employee_payload(employer_id, home_worksite_id,
                            classification="NON_EXEMPT", **overrides) -> dict:
    """Required: employer_id, home_worksite_id, full_name, classification,
    base_rate_cents. Optional: is_tipped (default false)."""
    payload = {
        "employer_id": employer_id,
        "home_worksite_id": home_worksite_id,
        "full_name": DEFAULTS["EMPLOYEE_NAME"],
        "classification": classification,
        "base_rate_cents": DEFAULTS["BASE_RATE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_shift_payload(employee_id, worksite_id, scheduled_start, scheduled_end,
                         **overrides) -> dict:
    """Required: employee_id, worksite_id, scheduled_start, scheduled_end."""
    payload = {
        "employee_id": employee_id,
        "worksite_id": worksite_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    payload.update(overrides)
    return payload


def open_punch_payload(clock_in, **overrides) -> dict:
    """Required: clock_in."""
    payload = {"clock_in": clock_in}
    payload.update(overrides)
    return payload


def close_punch_payload(clock_out, **overrides) -> dict:
    """Required: clock_out."""
    payload = {"clock_out": clock_out}
    payload.update(overrides)
    return payload


def edit_punch_payload(field, new_value, reason="badge log correction", **overrides) -> dict:
    """Required: field, new_value, reason."""
    payload = {"field": field, "new_value": new_value, "reason": reason}
    payload.update(overrides)
    return payload


def create_break_record_payload(shift_id, employee_id, kind, taken, **overrides) -> dict:
    """Required: shift_id, employee_id, kind, taken. Optional: minutes (default 0)."""
    payload = {
        "shift_id": shift_id,
        "employee_id": employee_id,
        "kind": kind,
        "taken": taken,
    }
    payload.update(overrides)
    return payload


def create_tip_declaration_payload(employee_id, workday_date, declared_cents,
                                   **overrides) -> dict:
    """Required: employee_id, workday_date, declared_cents. Optional: pool_id (default null)."""
    payload = {
        "employee_id": employee_id,
        "workday_date": workday_date,
        "declared_cents": declared_cents,
    }
    payload.update(overrides)
    return payload


def create_tip_pool_payload(worksite_id, workday_date, **overrides) -> dict:
    """Required: worksite_id, workday_date."""
    payload = {"worksite_id": worksite_id, "workday_date": workday_date}
    payload.update(overrides)
    return payload


def create_timesheet_week_payload(employee_id, workweek_start, **overrides) -> dict:
    """Required: employee_id, workweek_start."""
    payload = {"employee_id": employee_id, "workweek_start": workweek_start}
    payload.update(overrides)
    return payload


def approve_week_payload(expected_timesheet_week_version, **overrides) -> dict:
    """Required: expected_timesheet_week_version."""
    payload = {"expected_timesheet_week_version": expected_timesheet_week_version}
    payload.update(overrides)
    return payload


def create_payroll_run_payload(employer_id, period_start, period_end, **overrides) -> dict:
    """Required: employer_id, period_start, period_end."""
    payload = {
        "employer_id": employer_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    payload.update(overrides)
    return payload


def include_week_payload(timesheet_week_id, expected_timesheet_week_version, **overrides) -> dict:
    """Required: timesheet_week_id, expected_timesheet_week_version."""
    payload = {
        "timesheet_week_id": timesheet_week_id,
        "expected_timesheet_week_version": expected_timesheet_week_version,
    }
    payload.update(overrides)
    return payload
