"""Entity assertions and domain invariant checkers.

Each assert_* checks the system-managed common properties (id, created_at,
updated_at, version per PRD §2.4) plus the entity's PRD-declared fields and
status membership.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_call_program(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["service_line"], str) and data["service_line"]
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert isinstance(data["holiday_dates"], list)
    assert data["status"] in ("DRAFT", "GENERATED", "PUBLISHED", "RECONCILED")
    assert isinstance(data["payroll_reserved_cents"], int)
    assert isinstance(data["payroll_accrued_cents"], int)
    assert isinstance(data["payroll_budget_cents"], int)
    assert isinstance(data["swap_cutoff_hours"], int)
    assert isinstance(data["credentialing_lead_hours"], int)


def assert_physician(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["specialty"], str) and data["specialty"]
    assert data["employment_type"] in ("STAFF", "LOCUM")
    assert isinstance(data["moonlight_cap_hours"], int) and data["moonlight_cap_hours"] > 0
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_unavailability_window(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("physician_id", ""))
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert data["kind"] in ("VACATION", "CME", "PERSONAL")
    assert data["status"] in ("REQUESTED", "APPROVED", "CANCELLED")


def assert_call_slot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert isinstance(data["date"], str)
    assert data["call_type"] in ("PRIMARY", "BACKUP")
    assert isinstance(data["position_index"], int) and data["position_index"] >= 1
    assert data["date_type"] in ("WEEKDAY", "WEEKEND", "HOLIDAY")
    assert is_iso8601_timestamp(data.get("window_start", "")), "window_start must be ISO 8601"
    assert is_iso8601_timestamp(data.get("window_end", "")), "window_end must be ISO 8601"
    assert data["status"] in ("OPEN", "ASSIGNED", "COVERED", "UNCOVERED")


def assert_call_assignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("slot_id", ""))
    assert is_valid_uuid(data.get("physician_id", ""))
    assert is_valid_uuid(data.get("program_id", ""))
    assert data["origin"] in ("GENERATED", "MANUAL", "SWAP", "LOCUM_FILL")
    assert data["call_hours"] == 24
    assert isinstance(data["projected_pay_cents"], int)
    assert data["status"] in ("SCHEDULED", "ACTIVATED", "SERVED", "SWAPPED", "CANCELLED")


def assert_swap_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert is_valid_uuid(data.get("assignment_id", ""))
    assert is_valid_uuid(data.get("offerer_physician_id", ""))
    assert data["status"] in ("POSTED", "CLAIMED", "APPROVED", "EXECUTED", "CANCELLED")


def assert_coverage_gap(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert is_valid_uuid(data.get("slot_id", ""))
    assert data["reason"] in (
        "GENERATION_SHORTFALL",
        "ASSIGNMENT_CANCELLED",
        "PHYSICIAN_DEACTIVATED",
    )
    assert is_iso8601_timestamp(data.get("detected_at", "")), "detected_at must be ISO 8601"
    assert data["status"] in ("OPEN", "REQUISITIONED", "RESOLVED")


def assert_locum_requisition(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("gap_id", ""))
    assert is_valid_uuid(data.get("program_id", ""))
    assert data["status"] in (
        "OPEN",
        "SOURCED",
        "CREDENTIALING",
        "READY",
        "FILLED",
        "CANCELLED",
    )


def assert_credentialing_case(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("requisition_id", ""))
    assert is_valid_uuid(data.get("locum_physician_id", ""))
    assert is_iso8601_timestamp(data.get("clear_by", "")), "clear_by must be ISO 8601"
    assert isinstance(data["items"], dict)
    for item in (
        "license_verification",
        "malpractice_verification",
        "privileges_granting",
        "health_screening",
        "orientation",
    ):
        assert item in data["items"], f"credentialing items must include {item}"
    assert data["status"] in (
        "INITIATED",
        "IN_PROGRESS",
        "CLEARED",
        "FAILED",
        "EXPIRED",
        "CANCELLED",
    )


def assert_pay_entry(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("assignment_id", ""))
    assert is_valid_uuid(data.get("physician_id", ""))
    assert is_valid_uuid(data.get("program_id", ""))
    assert isinstance(data["slot_date"], str)
    assert data["call_type"] in ("PRIMARY", "BACKUP")
    assert data["date_type"] in ("WEEKDAY", "WEEKEND", "HOLIDAY")
    assert isinstance(data["base_rate_cents"], int)
    assert isinstance(data["activation_applied"], bool)
    assert isinstance(data["premium_applied"], bool)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("ACCRUED", "FINALIZED")


def assert_program_payroll_invariants(program: dict):
    """Domain invariants on the dual payroll ledger (PRD §2.7)."""
    assert program["payroll_reserved_cents"] >= 0, "reserve must never go negative"
    assert program["payroll_accrued_cents"] >= 0, "accrual must never go negative"
    assert isinstance(program["payroll_reserved_cents"], int)
    assert isinstance(program["payroll_accrued_cents"], int)
