"""Entity assertions and domain invariant checkers (PRD §2.4, §2.5)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# Score-bearing fields are constrained to [0, 1] inclusive (PRD §2.5).
def assert_score_in_range(value, label="score"):
    assert value is None or (0.0 <= float(value) <= 1.0), \
        f"{label}={value} must be in [0, 1] inclusive"


def assert_4dp(value, label="value"):
    """Numeric must serialize to at most 4 decimal places (PRD §2.5)."""
    if value is None:
        return
    s = f"{float(value):.10f}".rstrip("0").rstrip(".")
    if "." in s:
        decimals = len(s.split(".")[1])
        assert decimals <= 4, f"{label}={value} has {decimals} decimal places, expected <= 4"


def assert_common_fields(data: dict, has_version=True):
    """Asserts id, created_at, updated_at, version (if has_version)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')}"
    if has_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), \
            f"updated_at must be ISO 8601, got {data.get('updated_at')}"
        assert isinstance(data.get("version"), int) and data["version"] >= 1, \
            f"version must be int >= 1, got {data.get('version')}"


def assert_append_only_fields(data: dict):
    """Append-only entities (ProgressUpdate, AuditLog, ExternalEvent): id + created_at only."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')}"


# --- Per-entity ---

def assert_department(data: dict):
    assert_common_fields(data, has_version=True)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert "parent_department_id" in data


def assert_user(data: dict):
    assert_common_fields(data, has_version=True)
    assert isinstance(data["email"], str)
    assert data["role_type"] in {"EMPLOYEE", "MANAGER"}
    assert data["status"] in {"ACTIVE", "SUSPENDED"}


def assert_cycle(data: dict):
    assert_common_fields(data, has_version=True)
    assert isinstance(data["cycle_code"], str)
    assert isinstance(data["year"], int)
    assert 1 <= data["quarter"] <= 4
    assert data["status"] in {"DRAFT", "OPEN", "IN_REVIEW", "LOCKED", "ARCHIVED"}
    assert "start_date" in data and "end_date" in data
    if "completion_rate" in data and data["completion_rate"] is not None:
        assert 0.0 <= float(data["completion_rate"]) <= 1.0
        assert_4dp(data["completion_rate"], "completion_rate")


def assert_objective(data: dict):
    assert_common_fields(data, has_version=True)
    assert data["level"] in {"COMPANY", "DEPARTMENT", "TEAM", "INDIVIDUAL"}
    assert data["status"] in {"DRAFT", "ACTIVE", "IN_REVIEW", "LOCKED", "ARCHIVED"}
    assert isinstance(data["title"], str)
    assert isinstance(data["weight"], (int, float))
    assert 0.0 <= float(data["weight"]) <= 1.0
    assert isinstance(data["confidential"], bool)
    if "progress" in data and data["progress"] is not None:
        assert_score_in_range(data["progress"], "progress")
        assert_4dp(data["progress"], "progress")
    if "final_score" in data and data["final_score"] is not None:
        assert_score_in_range(data["final_score"], "final_score")
        assert_4dp(data["final_score"], "final_score")


def assert_key_result(data: dict):
    assert_common_fields(data, has_version=True)
    assert data["measurement_type"] in {"NUMERIC", "PERCENTAGE", "MILESTONE"}
    assert data["status"] in {"ACTIVE", "ARCHIVED"}
    assert isinstance(data["weight"], (int, float))
    assert 0.0 <= float(data["weight"]) <= 1.0
    if "score" in data and data["score"] is not None:
        assert_score_in_range(data["score"], "score")
        assert_4dp(data["score"], "score")


def assert_progress_update(data: dict):
    """Append-only — id + created_at only."""
    assert_append_only_fields(data)
    assert "key_result_id" in data
    assert data["update_type"] in {"VALUE_CHANGE", "MILESTONE_TOGGLE"}
    if "score_at_update" in data and data["score_at_update"] is not None:
        assert_score_in_range(data["score_at_update"], "score_at_update")


def assert_alignment_link(data: dict):
    assert_common_fields(data, has_version=True)
    assert data["dependency_type"] in {"SUPPORTS", "BLOCKS", "INFORMS"}
    assert data["status"] in {"PENDING", "ACCEPTED", "REJECTED", "BROKEN"}
    if data["status"] == "ACCEPTED":
        if data.get("forward_impact_score") is not None:
            assert_score_in_range(data["forward_impact_score"], "forward_impact_score")
        if data.get("backward_impact_score") is not None:
            assert_score_in_range(data["backward_impact_score"], "backward_impact_score")


def assert_co_ownership(data: dict):
    assert_common_fields(data, has_version=True)
    assert data["status"] in {"ACTIVE", "REMOVED"}
    assert isinstance(data["contribution_weight"], (int, float))
    assert 0.0 <= float(data["contribution_weight"]) <= 1.0


def assert_review_score(data: dict):
    assert_common_fields(data, has_version=True)
    assert data["status"] in {"PENDING_SELF", "PENDING_MANAGER", "PENDING_CALIBRATION", "LOCKED"}
    for f in ("self_score", "manager_score", "calibration_score", "final_score"):
        if data.get(f) is not None:
            assert_score_in_range(data[f], f)
            assert_4dp(data[f], f)
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0


def assert_access_grant(data: dict):
    assert_common_fields(data, has_version=True)
    assert data["status"] in {"ACTIVE", "REVOKED"}


def assert_audit_log(data: dict):
    """Append-only — id + created_at only."""
    assert_append_only_fields(data)
    assert data["entity_type"] in {
        "OBJECTIVE", "KEY_RESULT", "REVIEW_SCORE", "ALIGNMENT_LINK",
        "CO_OWNERSHIP", "ACCESS_GRANT", "OKR_CYCLE",
    }
    assert data["action"] in {"CREATE", "UPDATE", "DELETE", "STATE_TRANSITION", "SCORE_CHANGE", "CALIBRATION"}


def assert_external_event(data: dict):
    """Append-only — id + created_at only."""
    assert_append_only_fields(data)
    assert data["source_system"] in {"HR", "PROJECT_MGMT", "IM"}
    assert data["processing_status"] in {"RECEIVED", "PROCESSED", "DUPLICATE", "INVALID"}
