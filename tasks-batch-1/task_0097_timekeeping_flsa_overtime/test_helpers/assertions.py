"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates structural shape (UUID id, ISO timestamps,
enum membership) plus the entity-specific fields the PRD declares.
The append-only TimeEdit record is asserted WITHOUT updated_at/version
(PRD §2.4: it carries only id and created_at).
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def _assert_common(data: dict):
    """id + created_at + updated_at + version for common_fields:true entities."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"


def assert_employer(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert data["workweek_start_dow"] in ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
    assert isinstance(data["federal_min_wage_cents"], int)
    assert isinstance(data["federal_tipped_cash_wage_cents"], int)


def assert_wage_ruleset(data: dict):
    _assert_common(data)
    assert isinstance(data["state_code"], str)
    assert is_valid_uuid(data["employer_id"])
    assert isinstance(data["daily_ot_enabled"], bool)
    assert isinstance(data["seventh_day_rule_enabled"], bool)
    assert isinstance(data["meal_break_premium_enabled"], bool)
    assert isinstance(data["rest_break_premium_enabled"], bool)


def assert_worksite(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["employer_id"])
    assert isinstance(data["name"], str)
    assert isinstance(data["state_code"], str)


def assert_employee(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["employer_id"])
    assert is_valid_uuid(data["home_worksite_id"])
    assert isinstance(data["full_name"], str)
    assert data["classification"] in ("EXEMPT", "NON_EXEMPT")
    assert isinstance(data["base_rate_cents"], int) and data["base_rate_cents"] >= 0
    assert isinstance(data["is_tipped"], bool)
    assert data["status"] == "ACTIVE"


def assert_shift(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["employee_id"])
    assert is_valid_uuid(data["worksite_id"])
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert data["status"] in ("SCHEDULED", "OPEN", "CLOSED", "CANCELLED")
    assert isinstance(data["detention_minutes"], int) and data["detention_minutes"] >= 0
    assert isinstance(data["detention_flagged"], bool)


def assert_time_punch(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["employee_id"])
    assert is_valid_uuid(data["shift_id"])
    assert is_iso8601_timestamp(data["clock_in"])
    assert data["status"] in ("OPEN", "CLOSED", "VOIDED")
    assert isinstance(data["worked_minutes"], int)


def assert_time_edit(data: dict):
    """Append-only audit record: id + created_at only (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["punch_id"])
    assert isinstance(data["editor_user_id"], str)
    assert data["field"] in ("CLOCK_IN", "CLOCK_OUT")
    assert isinstance(data["new_value"], str)
    assert isinstance(data["reason"], str)
    # PRD §2.4: time edit has neither updated_at nor version.
    assert "updated_at" not in data, "TimeEdit must not expose updated_at"
    assert "version" not in data, "TimeEdit must not expose version"


def assert_break_record(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["shift_id"])
    assert is_valid_uuid(data["employee_id"])
    assert data["kind"] in ("MEAL", "REST")
    assert isinstance(data["taken"], bool)
    assert isinstance(data["minutes"], int)
    assert isinstance(data["premium_owed"], bool)


def assert_tip_declaration(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["employee_id"])
    assert isinstance(data["workday_date"], str)
    assert isinstance(data["declared_cents"], int) and data["declared_cents"] >= 0


def assert_tip_pool(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["worksite_id"])
    assert isinstance(data["workday_date"], str)
    assert data["status"] in ("OPEN", "DISTRIBUTED", "CANCELLED")
    assert isinstance(data["pooled_cents"], int)
    assert isinstance(data["distributed_cents"], int)


def assert_timesheet_week(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["employee_id"])
    assert isinstance(data["workweek_start"], str)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "LOCKED")
    assert isinstance(data["regular_minutes"], int)
    assert isinstance(data["ot_minutes"], int)
    assert isinstance(data["dt_minutes"], int)
    assert isinstance(data["break_premium_hours"], int)
    assert isinstance(data["gross_wages_cents"], int)
    assert isinstance(data["tip_true_up_cents"], int)


def assert_payroll_run(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["employer_id"])
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert data["status"] in ("OPEN", "FINALIZED", "CANCELLED")
    assert isinstance(data["total_gross_cents"], int)
    assert isinstance(data["included_week_count"], int)


def assert_wage_components_sum(data: dict):
    """Gross wages must equal the round-then-sum of the five components
    (PRD §3.6): straight + OT premium + DT premium + break premium + tip true-up.
    Used only as a non-negativity / consistency invariant; exact component
    values are asserted per-test from PRD-pinned literals."""
    assert data["gross_wages_cents"] >= 0
    assert data["regular_minutes"] >= 0
    assert data["ot_minutes"] >= 0
    assert data["dt_minutes"] >= 0
    assert data["break_premium_hours"] >= 0
    assert data["tip_true_up_cents"] >= 0
