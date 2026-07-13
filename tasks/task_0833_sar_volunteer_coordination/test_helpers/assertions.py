"""Entity assertions and domain invariant checkers (PRD-exact field names)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_incident(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert data["status"] in [
        "PLANNING", "ACTIVE", "DEMOBILIZING", "CLOSED", "CANCELLED",
    ]
    assert isinstance(data["active_task_count"], int)
    assert isinstance(data["total_approved_reimbursement_cents"], int)


def assert_task(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "DRAFT", "ASSIGNED", "IN_PROGRESS", "SUSPENDED", "DEBRIEFED", "CANCELLED",
    ]
    assert data["segment_area_sqkm"] > 0


def assert_team(data: dict):
    _assert_common(data)
    assert data["status"] in ["ACTIVE", "INACTIVE"]


def assert_member(data: dict):
    _assert_common(data)
    assert data["status"] in ["ACTIVE", "STANDBY", "DEPLOYED"]


def assert_certification(data: dict):
    _assert_common(data)
    assert data["status"] in ["VALID", "EXPIRED"]


def assert_callout(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "REQUESTED", "ACKNOWLEDGED", "STANDBY", "DEPLOYED",
        "DEMOBILIZED", "DECLINED", "NO_RESPONSE",
    ]


def assert_resource(data: dict):
    _assert_common(data)
    assert data["status"] in ["AVAILABLE", "ASSIGNED", "OUT_OF_SERVICE"]
    assert isinstance(data["active_assignment_count"], int)
    assert data["active_assignment_count"] >= 0


def assert_resource_assignment(data: dict):
    _assert_common(data)
    assert data["status"] in ["RESERVED", "ACTIVE", "RELEASED", "CANCELLED"]


def assert_clue(data: dict):
    _assert_common(data)
    assert data["status"] in ["LOGGED", "ACTIONABLE", "DISMISSED", "RESOLVED"]


def assert_claim(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "RETURNED", "APPROVED", "REJECTED", "PAID",
    ]


def assert_after_action_report(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "FINALIZED"]


def assert_ground_track(data: dict):
    """Append-only log: only id + created_at, no updated_at / version."""
    _assert_common(data)
    assert "updated_at" not in data, "GroundTrack is append-only (no updated_at)"
    assert "version" not in data, "GroundTrack is append-only (no version)"


def assert_resource_count_invariant(data: dict):
    """Resource.active_assignment_count never drifts below zero and status is
    consistent with the count when the asset is in service."""
    assert data["active_assignment_count"] >= 0
    if not data.get("out_of_service", False):
        if data["active_assignment_count"] > 0:
            assert data["status"] == "ASSIGNED"
        else:
            assert data["status"] == "AVAILABLE"
