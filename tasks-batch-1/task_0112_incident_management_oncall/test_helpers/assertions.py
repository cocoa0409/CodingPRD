"""Entity assertions and domain invariant checkers.

Field names are PRD-exact. Append-only logs (PageAttempt, WarRoomMessage) are
asserted to carry only id + created_at (no version / updated_at).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an int"


def _assert_append_only(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "append-only log must not expose version"
    assert "updated_at" not in data, "append-only log must not expose updated_at"


def assert_service(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["tier"] in ("TIER_1", "TIER_2", "TIER_3")
    assert isinstance(data["error_budget_minutes"], int)
    assert data["budget_status"] in ("HEALTHY", "WARNING", "EXHAUSTED")
    assert isinstance(data["error_budget_consumed_minutes"], int)
    assert isinstance(data["error_budget_remaining_minutes"], int)


def assert_service_budget_invariants(data: dict):
    """Invariants that must hold on a service after any budget recompute."""
    assert data["error_budget_consumed_minutes"] >= 0
    assert data["error_budget_remaining_minutes"] >= 0
    assert data["error_budget_remaining_minutes"] == max(
        0, data["error_budget_minutes"] - data["error_budget_consumed_minutes"]
    ), "remaining must equal max(0, budget - consumed)"


def assert_responder(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and "@" in data["email"]


def assert_on_call_schedule(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert is_valid_uuid(data["service_id"])


def assert_schedule_shift(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["schedule_id"])
    assert is_valid_uuid(data["responder_id"])
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])


def assert_escalation_policy(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["service_id"])
    assert isinstance(data["repeat_rounds"], int)


def assert_escalation_tier(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["policy_id"])
    assert is_valid_uuid(data["schedule_id"])
    assert isinstance(data["tier_level"], int) and data["tier_level"] >= 1
    assert isinstance(data["delay_minutes"], int) and data["delay_minutes"] >= 0


def assert_maintenance_window(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["service_id"])
    assert data["status"] in ("SCHEDULED", "ACTIVE", "ENDED", "CANCELLED")
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])


def assert_incident(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["service_id"])
    assert is_valid_uuid(data["policy_id"])
    assert isinstance(data["title"], str)
    assert data["severity"] in ("SEV1", "SEV2", "SEV3", "SEV4")
    assert data["lifecycle_status"] in ("TRIGGERED", "ACKNOWLEDGED", "RESOLVED", "SUPPRESSED")
    assert data["escalation_status"] in ("PENDING", "ESCALATING", "EXHAUSTED")
    assert isinstance(data["current_tier_level"], int)
    assert is_iso8601_timestamp(data["triggered_at"])
    assert is_iso8601_timestamp(data["ack_deadline_at"])
    assert is_iso8601_timestamp(data["resolve_deadline_at"])
    assert isinstance(data["ack_sla_breached"], bool)
    assert isinstance(data["counts_against_budget"], bool)


def assert_page_attempt(data: dict):
    _assert_append_only(data)
    assert is_valid_uuid(data["incident_id"])
    assert is_valid_uuid(data["responder_id"])
    assert isinstance(data["tier_level"], int)
    assert data["channel"] in ("SMS", "VOICE", "PUSH", "EMAIL")
    assert isinstance(data["round_index"], int)


def assert_war_room(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["incident_id"])
    assert data["status"] in ("OPEN", "CLOSED")


def assert_war_room_message(data: dict):
    _assert_append_only(data)
    assert is_valid_uuid(data["war_room_id"])
    assert isinstance(data["author_role"], str)
    assert isinstance(data["body"], str)


def assert_postmortem(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["incident_id"])
    assert data["status"] in ("DRAFT", "IN_REVIEW", "PUBLISHED")
    assert isinstance(data["summary"], str)
    assert isinstance(data["open_action_item_count"], int)
    assert data["open_action_item_count"] >= 0


def assert_action_item(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["postmortem_id"])
    assert is_valid_uuid(data["owner_responder_id"])
    assert isinstance(data["description"], str)
    assert data["status"] in ("OPEN", "IN_PROGRESS", "DONE", "CANCELLED")
