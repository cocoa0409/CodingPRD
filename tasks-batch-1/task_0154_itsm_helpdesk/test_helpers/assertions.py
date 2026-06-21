"""Entity assertions and domain invariant checkers.

Field names are PRD-exact. Append-only records (CabVote) are checked for id +
created_at only — they carry no updated_at and no version per PRD §2.4.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_TICKET_LIFECYCLE = {
    "NEW", "ASSIGNED", "IN_PROGRESS", "PENDING_CHANGE", "ON_HOLD",
    "RESOLVED", "CLOSED", "CANCELLED",
}
_TICKET_SLA = {"RUNNING", "PAUSED", "RESPONSE_BREACHED", "RESOLVE_BREACHED", "MET"}
_PRIORITIES = {"P1", "P2", "P3", "P4"}
_PROBLEM_STATES = {"OPEN", "ROOT_CAUSE_IDENTIFIED", "KNOWN_ERROR", "RESOLVED"}
_CHANGE_STATES = {"DRAFT", "PENDING_CAB", "APPROVED", "REJECTED", "IMPLEMENTED", "FAILED"}
_ASSET_KINDS = {"SERVER", "LAPTOP", "NETWORK_DEVICE", "APPLICATION"}
_ASSET_STATUSES = {"OPERATIONAL", "DEGRADED", "RETIRED"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be int >= 1, got {data.get('version')!r}"


def assert_category(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["default_priority"] in _PRIORITIES
    assert is_valid_uuid(data["sla_policy_id"])
    assert is_valid_uuid(data["default_assignment_group_id"])
    assert isinstance(data["active"], bool)


def assert_sla_policy(data: dict):
    _assert_common(data)
    assert data["response_target_minutes"] >= 1
    assert data["resolve_target_minutes"] >= data["response_target_minutes"]
    assert data["ola_target_minutes"] >= 1
    assert isinstance(data["priority_multipliers"], dict)


def assert_assignment_group(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["is_fulfilment_group"], bool)
    assert isinstance(data["queue_depth"], int) and data["queue_depth"] >= 0


def assert_ticket(data: dict):
    _assert_common(data)
    assert isinstance(data["short_description"], str) and data["short_description"]
    assert isinstance(data["requester_id"], str) and data["requester_id"]
    assert is_valid_uuid(data["category_id"])
    assert data["priority"] in _PRIORITIES
    assert data["lifecycle_state"] in _TICKET_LIFECYCLE
    assert data["sla_state"] in _TICKET_SLA
    assert isinstance(data["reopen_count"], int) and data["reopen_count"] >= 0
    assert isinstance(data["paused_total_minutes"], int) and data["paused_total_minutes"] >= 0
    assert is_iso8601_timestamp(data["opened_at"]), "opened_at must be ISO 8601"
    assert isinstance(data["deflected"], bool)


def assert_problem(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["owner_user_id"], str) and data["owner_user_id"]
    assert data["state"] in _PROBLEM_STATES
    assert isinstance(data["linked_ticket_count"], int) and data["linked_ticket_count"] >= 0


def assert_known_error(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["problem_id"])
    assert isinstance(data["symptom"], str) and data["symptom"]
    assert isinstance(data["workaround"], str) and data["workaround"]
    assert isinstance(data["published"], bool)


def assert_kb_article(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str) and data["title"]
    assert is_valid_uuid(data["category_id"])
    assert isinstance(data["view_count"], int) and data["view_count"] >= 0
    assert isinstance(data["deflection_count"], int) and data["deflection_count"] >= 0


def assert_change_request(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str) and data["title"]
    assert is_valid_uuid(data["ticket_id"])
    assert isinstance(data["raised_by_user_id"], str) and data["raised_by_user_id"]
    assert data["risk"] in {"LOW", "MEDIUM", "HIGH"}
    assert data["state"] in _CHANGE_STATES
    assert isinstance(data["approve_count"], int) and data["approve_count"] >= 0
    assert isinstance(data["reject_count"], int) and data["reject_count"] >= 0


def assert_csat_survey(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["ticket_id"])
    assert isinstance(data["score"], int) and 1 <= data["score"] <= 5
    assert isinstance(data["counts_toward_index"], bool)


def assert_asset(data: dict):
    _assert_common(data)
    assert isinstance(data["asset_tag"], str) and data["asset_tag"]
    assert data["kind"] in _ASSET_KINDS
    assert data["status"] in _ASSET_STATUSES
    assert isinstance(data["open_incident_count"], int) and data["open_incident_count"] >= 0


def assert_cab_vote(data: dict):
    """Append-only event record: only id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "vote id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "vote created_at must be ISO 8601"
    assert "updated_at" not in data or data.get("updated_at") is None, \
        "CabVote is append-only and must not carry updated_at"
    assert "version" not in data or data.get("version") is None, \
        "CabVote is append-only and must not carry version"
