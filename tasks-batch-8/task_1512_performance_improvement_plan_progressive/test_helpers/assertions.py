"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_org_unit(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert is_iso8601_timestamp(data.get("current_utc", "")), "current_utc must be ISO 8601"
    assert isinstance(data["pip_policy_version"], int)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_employee(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("hr_org_unit_id", ""))
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert data["job_family"] in [
        "ENGINEERING",
        "SALES",
        "OPERATIONS",
        "SUPPORT",
        "FINANCE",
    ]
    assert isinstance(data["job_level"], int)
    assert data["employment_status"] in [
        "ACTIVE",
        "ON_NOTICE",
        "TERMINATED",
        "RESIGNED",
    ]
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int)


def assert_rating_cycle(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data["label"], str) and len(data["label"]) > 0
    assert is_iso8601_timestamp(data.get("window_start", ""))
    assert is_iso8601_timestamp(data.get("window_end", ""))
    assert data["status"] in ["OPEN", "CALIBRATION", "PUBLISHED", "ARCHIVED"]


def assert_coaching_log_entry(data: dict):
    """Append-only record: carries id + created_at; NO updated_at, NO version."""
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "append-only entry must not carry updated_at"
    assert "version" not in data, "append-only entry must not carry version"
    assert data["category"] in [
        "QUALITY",
        "VELOCITY",
        "ATTENDANCE",
        "CONDUCT",
        "COLLABORATION",
    ]
    assert data["severity"] in ["INFORMAL", "DOCUMENTED", "ESCALATED"]
    assert isinstance(data["narrative"], str)


def assert_concern(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["status"] in [
        "DRAFT",
        "SUBMITTED",
        "ACCEPTED",
        "REJECTED_INSUFFICIENT",
        "SUPERSEDED_BY_PIP",
    ]
    assert isinstance(data["coaching_log_entry_ids"], list)
    assert isinstance(data["version"], int)


def assert_pip_template(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["template_status"] in ["DRAFT", "PUBLISHED", "RETIRED"]
    assert isinstance(data["goal_blueprints"], list)
    assert 30 <= data["duration_days"] <= 180
    assert 7 <= data["check_in_cadence_days"] <= 30


def assert_pip(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["status"] in [
        "DRAFT",
        "ISSUED",
        "ACTIVE",
        "EXTENDED",
        "CLOSED_SUCCESS",
        "CLOSED_FAILED",
        "CLOSED_TERMINATED",
        "CLOSED_WITHDRAWN",
    ]
    assert isinstance(data["extension_count"], int)
    assert isinstance(data["version"], int)
    assert is_iso8601_timestamp(data.get("start_date", ""))
    assert is_iso8601_timestamp(data.get("end_date", ""))


def assert_pip_goal(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("pip_id", ""))
    assert isinstance(data["metric_key"], str)
    assert isinstance(data["weight"], int)
    assert data["goal_status"] in [
        "PENDING",
        "ON_TRACK",
        "AT_RISK",
        "MET",
        "NOT_MET",
        "WAIVED",
    ]


def assert_check_in(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("pip_id", ""))
    assert is_iso8601_timestamp(data.get("scheduled_for", ""))
    assert data["status"] in ["SCHEDULED", "HELD", "MISSED", "CANCELLED"]


def assert_evidence_item(data: dict):
    """Append-only record: carries id + created_at; NO updated_at, NO version."""
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "append-only evidence must not carry updated_at"
    assert "version" not in data, "append-only evidence must not carry version"
    assert data["admissibility"] in ["PENDING_REVIEW", "ADMISSIBLE", "INADMISSIBLE"]
    assert data["source"] in [
        "MANAGER_OBSERVATION",
        "SYSTEM_REPORT",
        "PEER_FEEDBACK",
        "SELF_REPORT",
    ]


def assert_legal_review(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["status"] in ["REQUESTED", "IN_REVIEW", "SUBMITTED", "OVERRIDDEN"]


def assert_outcome_decision(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["proposed_outcome"] in ["SUCCESS", "EXTENSION", "TERMINATION"]
    assert data["status"] in ["PROPOSED", "APPROVED", "REJECTED", "SUPERSEDED"]


def assert_rebuttal(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["status"] in ["SUBMITTED", "UNDER_REVIEW", "UPHELD", "OVERRULED"]
    assert isinstance(data["body"], str)


def assert_consistency_review(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["status"] in [
        "OPEN",
        "ADJUDICATED_CONSISTENT",
        "ADJUDICATED_INCONSISTENT",
    ]


def assert_rating_cycle_outcome_link(data: dict):
    """Append-only record: carries id + created_at; NO updated_at, NO version."""
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data
    assert "version" not in data
    assert data["pip_outcome_at_link"] in ["SUCCESS", "EXTENSION", "TERMINATION"]


def assert_pip_goal_weight_sum(goals: list):
    """Domain invariant: goal weights within a plan always sum to 100."""
    total = sum(g["weight"] for g in goals)
    assert total == 100, f"PIP goal weights must sum to 100, got {total}"
