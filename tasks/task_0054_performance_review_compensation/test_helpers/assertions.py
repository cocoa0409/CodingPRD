"""Entity assertions and domain invariant checkers.

Validates response shape against the PRD contract. RatingBand carries only
id + created_at (PRD Section 2.4); all other resources carry the full
id/created_at/updated_at/version set.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_CYCLE_STATES = ["DRAFT", "OPEN", "CALIBRATION", "COMP_PLANNING", "CLOSED"]
_REVIEW_STATES = [
    "DRAFT", "SELF_REVIEW", "MANAGER_REVIEW", "SUBMITTED",
    "RETURNED", "CALIBRATED", "FINALIZED",
]
_GOAL_STATES = ["OPEN", "SCORED"]
_FEEDBACK_STATES = ["PENDING", "SUBMITTED", "DECLINED"]
_SESSION_STATES = ["OPEN", "BALANCED", "FINALIZED"]
_PLAN_STATES = ["DRAFT", "PROPOSED", "APPROVED", "REJECTED"]
_PIP_STATES = ["OPEN", "ACTIVE", "CURED", "FAILED"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_review_cycle(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["cadence"] in ["ANNUAL", "SEMI_ANNUAL"]
    assert data["status"] in _CYCLE_STATES
    assert isinstance(data["merit_budget_pct"], (int, float))
    assert isinstance(data["equity_refresh_pool"], (int, float))
    assert isinstance(data["bell_curve_target"], dict)
    assert isinstance(data["merit_committed_total"], (int, float))
    assert isinstance(data["equity_committed_total"], (int, float))


def assert_employee(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["department"], str)
    assert isinstance(data["is_active"], bool)


def assert_review(data: dict):
    _assert_common(data)
    assert data["status"] in _REVIEW_STATES
    assert is_valid_uuid(data.get("cycle_id", "")), "cycle_id must be a valid UUID"
    assert is_valid_uuid(data.get("employee_id", "")), "employee_id must be a valid UUID"
    assert is_valid_uuid(data.get("reviewer_id", "")), "reviewer_id must be a valid UUID"
    assert isinstance(data["base_salary"], (int, float)) and data["base_salary"] > 0


def assert_goal(data: dict):
    _assert_common(data)
    assert data["status"] in _GOAL_STATES
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert isinstance(data["weight"], (int, float))


def assert_feedback_request(data: dict):
    _assert_common(data)
    assert data["status"] in _FEEDBACK_STATES
    assert data["relationship"] in ["PEER", "REPORT", "MANAGER", "SELF"]


def assert_calibration_session(data: dict):
    _assert_common(data)
    assert data["status"] in _SESSION_STATES
    assert isinstance(data["department"], str)


def assert_comp_plan(data: dict):
    _assert_common(data)
    assert data["status"] in _PLAN_STATES
    assert data["plan_type"] in ["MERIT_ONLY", "MERIT_AND_PROMO"]


def assert_pip_case(data: dict):
    _assert_common(data)
    assert data["status"] in _PIP_STATES


def assert_rating_band(data: dict):
    """RatingBand carries only id + created_at (PRD Section 2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["label"], str) and len(data["label"]) > 0
    assert isinstance(data["min_score"], (int, float))
    assert isinstance(data["max_score"], (int, float))
