"""Entity assertions and domain invariant checkers.

Field names are PRD-exact. Computed fields are validated only where the PRD
states their presence/value on the response object.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_PRODUCTION_STATUSES = {"DRAFT", "PRE_PRODUCTION", "ACTIVE", "WRAPPED", "CLOSED"}
_DAY_STATUSES = {"PLANNED", "CALLED", "IN_PROGRESS", "WRAPPED", "CANCELLED"}
_ATTENDANCE = {"SCHEDULED", "CHECKED_IN", "WRAPPED", "NO_SHOW"}
_PAYMENT = {"UNPAID", "APPROVED", "PAID", "VOID"}
_CALLSHEET_STATUSES = {"DRAFT", "PUBLISHED", "REVISED", "FINALIZED", "CANCELLED"}
_PERMIT_STATUSES = {"REQUESTED", "APPROVED", "ACTIVE", "EXPIRED", "DENIED", "REVOKED"}
_DAILIES_STATUSES = {"PENDING", "IN_REVIEW", "APPROVED", "FLAGGED", "ARCHIVED"}
_BUDGET_CATEGORIES = {"ABOVE_THE_LINE", "BELOW_THE_LINE_LABOR", "LOCATIONS", "POST", "FRINGES"}
_UNION_CODES = {"SAG_AFTRA", "IATSE", "DGA", "NONE"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_production(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["production_type"] in {"FEATURE", "EPISODIC"}
    assert data["status"] in _PRODUCTION_STATUSES, f"unexpected status {data['status']!r}"
    assert isinstance(data["total_budget_cents"], int) and data["total_budget_cents"] >= 0
    assert isinstance(data["committed_cost_cents"], int)
    assert isinstance(data["actual_cost_cents"], int)
    assert isinstance(data["residual_reserve_cents"], int)


def assert_budget_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("production_id", "")), "production_id must be a UUID"
    assert data["category"] in _BUDGET_CATEGORIES
    assert isinstance(data["estimated_cents"], int) and data["estimated_cents"] >= 0
    assert isinstance(data["actual_cents"], int)
    assert isinstance(data["variance_cents"], int)
    assert data["variance_cents"] == data["estimated_cents"] - data["actual_cents"], \
        "variance_cents must equal estimated_cents - actual_cents"


def assert_shooting_day(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("production_id", "")), "production_id must be a UUID"
    assert isinstance(data["shoot_date"], str) and len(data["shoot_date"]) > 0
    assert isinstance(data["day_number"], int) and data["day_number"] >= 1
    assert data["unit"] in {"MAIN", "SECOND", "SPLINTER"}
    assert data["status"] in _DAY_STATUSES
    assert isinstance(data["estimated_page_eighths"], int) and data["estimated_page_eighths"] >= 0


def assert_scene(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("production_id", "")), "production_id must be a UUID"
    assert data["shooting_day_id"] is None or is_valid_uuid(data["shooting_day_id"])
    assert isinstance(data["scene_number"], str) and len(data["scene_number"]) > 0
    assert isinstance(data["page_eighths"], int) and data["page_eighths"] >= 1
    assert data["int_ext"] in {"INT", "EXT"}
    assert data["day_night"] in {"DAY", "NIGHT"}


def assert_crew_member(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("production_id", "")), "production_id must be a UUID"
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["role_title"], str) and len(data["role_title"]) > 0
    assert isinstance(data["is_sag_aftra"], bool)
    assert isinstance(data["daily_rate_cents"], int) and data["daily_rate_cents"] >= 0
    assert data["union_code"] in _UNION_CODES


def assert_assignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("shooting_day_id", "")), "shooting_day_id must be a UUID"
    assert is_valid_uuid(data.get("crew_member_id", "")), "crew_member_id must be a UUID"
    assert isinstance(data["call_time"], str) and len(data["call_time"]) > 0
    assert data["attendance_status"] in _ATTENDANCE
    assert data["payment_status"] in _PAYMENT
    assert isinstance(data["estimated_cost_cents"], int)
    assert isinstance(data["meal_penalty_cents"], int)
    assert isinstance(data["turnaround_penalty_cents"], int)
    assert isinstance(data["fringe_cents"], int)
    assert isinstance(data["paid_cost_cents"], int)


def assert_call_sheet(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("shooting_day_id", "")), "shooting_day_id must be a UUID"
    assert data["status"] in _CALLSHEET_STATUSES
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 0
    assert isinstance(data["general_call_time"], str) and len(data["general_call_time"]) > 0


def assert_location(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("production_id", "")), "production_id must be a UUID"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["address"], str) and len(data["address"]) > 0


def assert_location_permit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("location_id", "")), "location_id must be a UUID"
    assert isinstance(data["permit_number"], str) and len(data["permit_number"]) > 0
    assert isinstance(data["window_start"], str) and len(data["window_start"]) > 0
    assert isinstance(data["window_end"], str) and len(data["window_end"]) > 0
    assert data["status"] in _PERMIT_STATUSES


def assert_union_fringe(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("production_id", "")), "production_id must be a UUID"
    assert data["union_code"] in {"SAG_AFTRA", "IATSE", "DGA"}
    assert isinstance(data["fringe_rate_bps"], int) and 0 <= data["fringe_rate_bps"] <= 10000
    assert isinstance(data["pension_health_flat_cents"], int) and data["pension_health_flat_cents"] >= 0


def assert_dailies(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("shooting_day_id", "")), "shooting_day_id must be a UUID"
    assert isinstance(data["reel_label"], str) and len(data["reel_label"]) > 0
    assert data["status"] in _DAILIES_STATUSES


def assert_residual_event(data: dict):
    """ResidualEvent is immutable: id + created_at only, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("production_id", "")), "production_id must be a UUID"
    assert data["market"] in {"THEATRICAL", "SVOD", "BASIC_CABLE", "NETWORK", "HOME_VIDEO"}
    assert isinstance(data["gross_receipts_cents"], int) and data["gross_receipts_cents"] >= 0
    assert isinstance(data["residual_amount_cents"], int)
