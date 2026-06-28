"""Entity assertions and domain invariant checkers (Food Safety Inspection API)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Every primary resource carries id, created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1 and increments"


def assert_fda_food_code(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["title"], str)
    assert data["classification"] in ("CRITICAL", "NON_CRITICAL")
    assert isinstance(data["base_demerit_points"], int)
    assert isinstance(data["repeat_surcharge_points"], int)
    assert isinstance(data["is_active"], bool)


def assert_inspector(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["badge_number"], str) and len(data["badge_number"]) > 0
    assert isinstance(data["max_daily_route_stops"], int)
    assert isinstance(data["is_active"], bool)


def assert_establishment(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["address"], str)
    assert isinstance(data["seating_capacity"], int)
    assert data["risk_category"] in ("CATEGORY_1", "CATEGORY_2", "CATEGORY_3")
    assert isinstance(data["routine_interval_days"], int)
    assert data["status"] in ("PRELICENSE", "PERMITTED", "SUSPENDED", "REVOKED")
    assert isinstance(data["open_critical_count"], int)


def assert_plan_review(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("establishment_id", "")), "establishment_id must be UUID"
    assert isinstance(data["submitted_layout_sqft"], int)
    assert isinstance(data["equipment_count"], int)
    assert isinstance(data["plan_fee_cents"], int)
    assert isinstance(data["revision_round"], int)
    assert data["status"] in ("SUBMITTED", "APPROVED", "REJECTED")


def assert_permit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("establishment_id", ""))
    assert is_valid_uuid(data.get("plan_review_id", ""))
    assert isinstance(data["issued_index"], int)
    assert isinstance(data["expires_index"], int)
    assert isinstance(data["annual_fee_cents"], int)
    assert data["status"] in ("ACTIVE", "EXPIRED", "VOID")


def assert_inspection_route(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("inspector_id", ""))
    assert isinstance(data["route_date_index"], int)
    assert isinstance(data["planned_stop_count"], int)
    assert data["status"] in ("PLANNED", "DISPATCHED", "COMPLETED")


def assert_inspection(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("establishment_id", ""))
    assert is_valid_uuid(data.get("inspector_id", ""))
    assert data["inspection_type"] in ("ROUTINE", "REINSPECTION", "COMPLAINT")
    assert isinstance(data["scheduled_index"], int)
    assert isinstance(data["critical_count"], int)
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "AMENDING", "FINALIZED")


def assert_violation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("inspection_id", ""))
    assert is_valid_uuid(data.get("fda_code_id", ""))
    assert data["classification"] in ("CRITICAL", "NON_CRITICAL")
    assert isinstance(data["corrected_on_site"], bool)
    assert isinstance(data["demerit_points_observed"], int)
    assert isinstance(data["demerit_points_final"], int)
    assert data["resolution_status"] in ("OPEN", "RESOLVED")


def assert_closure_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("establishment_id", ""))
    assert data["reason_code"] in ("GRADE_C_AUTOCLOSE", "CRITICAL_THRESHOLD", "IMMINENT_HEALTH_HAZARD")
    assert isinstance(data["issued_index"], int)
    assert data["status"] in ("ACTIVE", "LIFTED", "VACATED")


def assert_complaint(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("establishment_id", ""))
    assert data["complaint_type"] in ("FOODBORNE_ILLNESS", "SANITATION", "OTHER")
    assert isinstance(data["reported_ill_count"], int)
    assert data["status"] in ("RECEIVED", "TRIAGED", "DISPATCHED", "CLOSED")


def assert_enforcement_case(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("establishment_id", ""))
    assert isinstance(data["alleged_penalty_cents"], int)
    assert data["status"] in ("OPENED", "HEARING_SCHEDULED", "HEARD", "CLOSED")


def assert_score_in_range(score: int):
    """Scores are integers clamped to [0, 100] (PRD §2.9)."""
    assert isinstance(score, int), f"score must be an integer, got {type(score)}"
    assert 0 <= score <= 100, f"score must be within [0, 100], got {score}"
