"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), \
        f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be a positive integer, got {data.get('version')!r}"


def normalize_timestamp(ts: str) -> str:
    """Strip fractional seconds so '...T10:00:00.000Z' compares equal to
    '...T10:00:00Z'. The PRD pins instants, not the fractional-digit rendering
    of datetime fields such as start_at / end_at / hold_expires_at."""
    if isinstance(ts, str) and ts.endswith("Z") and "." in ts:
        head, _, _frac = ts.partition(".")
        return head + "Z"
    return ts


def assert_room(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["floor"], int)
    assert isinstance(data["capacity_max"], int) and data["capacity_max"] >= 1
    assert isinstance(data["safety_max_party"], int) and data["safety_max_party"] >= 1
    assert data["collection_tier"] in ("STANDARD", "LIGHT_SENSITIVE", "HIGH_VALUE")
    assert data["status"] in ("OPEN", "CLOSED_RESTORATION")


def assert_tour_route(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["kind"] in ("STANDARD", "SCHOOL", "CANDLELIGHT")
    assert isinstance(data["room_ids"], list) and len(data["room_ids"]) >= 1
    for rid in data["room_ids"]:
        assert is_valid_uuid(rid), f"room_ids entries must be UUIDs, got {rid!r}"
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] >= 10
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert data["status"] in ("DRAFT", "ACTIVE", "RETIRED")
    assert "published_script_id" in data, "published_script_id must be present"
    if data["published_script_id"] is not None:
        assert is_valid_uuid(data["published_script_id"])


def assert_script_version(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["route_id"])
    assert isinstance(data["version_no"], int) and data["version_no"] >= 1
    assert isinstance(data["content_text"], str)
    assert isinstance(data["curriculum_standards"], list)
    assert data["status"] in (
        "DRAFT", "IN_REVIEW", "APPROVED", "PUBLISHED", "SUPERSEDED", "REJECTED",
    )


def assert_tour_slot(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["route_id"])
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["seats_reserved"], int) and data["seats_reserved"] >= 0
    assert isinstance(data["seats_confirmed"], int) and data["seats_confirmed"] >= 0
    assert isinstance(data["seats_available"], int) and data["seats_available"] >= 0
    assert isinstance(data["revenue_committed_cents"], int)
    assert isinstance(data["revenue_projected_cents"], int)
    assert data["staffing_status"] in ("STAFFED", "NEEDS_LEAD", "UNSTAFFED")
    assert data["status"] in (
        "SCHEDULED", "OPEN", "FULL", "IN_PROGRESS", "COMPLETED", "CANCELLED",
    )


def assert_docent(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert data["status"] in ("APPLICANT", "TRAINEE", "CERTIFIED", "INACTIVE")
    assert isinstance(data["training_hours"], int) and data["training_hours"] >= 0
    assert isinstance(data["shadow_tours_completed"], int) \
        and data["shadow_tours_completed"] >= 0
    assert "quiz_score" in data
    if data["quiz_score"] is not None:
        assert isinstance(data["quiz_score"], int) and 0 <= data["quiz_score"] <= 100
    assert isinstance(data["certified_route_ids"], list)
    assert isinstance(data["readiness_standard_score"], int)
    assert 0 <= data["readiness_standard_score"] <= 100
    assert isinstance(data["readiness_apprentice_score"], int)
    assert 0 <= data["readiness_apprentice_score"] <= 100


def assert_shift_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["docent_id"])
    assert is_valid_uuid(data["slot_id"])
    assert data["shift_role"] in ("LEAD", "SHADOW")
    assert data["status"] in (
        "ASSIGNED", "CONFIRMED", "DECLINED", "COMPLETED", "NO_SHOW", "CANCELLED",
    )


def assert_member(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["member_number"], str) and len(data["member_number"]) > 0
    assert isinstance(data["renews_on"], str) and len(data["renews_on"]) == 10
    assert data["status"] in ("ACTIVE", "LAPSED", "EXPIRED")


def assert_booking(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["slot_id"])
    assert data["booking_kind"] in ("GENERAL", "MEMBER", "SCHOOL")
    assert isinstance(data["visitor_name"], str) and len(data["visitor_name"]) > 0
    assert isinstance(data["party_size"], int) and data["party_size"] >= 1
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["total_price_cents"], int) and data["total_price_cents"] >= 0
    assert isinstance(data["refund_cents"], int) and data["refund_cents"] >= 0
    assert is_iso8601_timestamp(data["hold_expires_at"])
    assert data["status"] in ("RESERVED", "CONFIRMED", "CANCELLED", "EXPIRED")
    if data["booking_kind"] == "MEMBER":
        assert data.get("member_id"), \
            "member_id is required and non-null for MEMBER bookings"
        assert is_valid_uuid(data["member_id"])


def assert_safety_incident(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["room_id"])
    if data.get("slot_id") is not None:
        assert is_valid_uuid(data["slot_id"])
    assert data["severity"] in ("MINOR", "MAJOR", "CRITICAL")
    assert isinstance(data["description"], str)
    assert data["status"] in ("REPORTED", "RESOLVED")


def assert_visitor_survey(data: dict):
    """Surveys are append-only: id + created_at, and per PRD section 2.4
    'Both `updated_at` and `version` are absent from surveys'."""
    assert is_valid_uuid(data.get("id", "")), \
        f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert "version" not in data, "survey must not carry a version field"
    assert "updated_at" not in data, "survey must not carry an updated_at field"
    assert is_valid_uuid(data["booking_id"])
    assert is_valid_uuid(data["slot_id"])
    assert isinstance(data["overall_rating"], int) and 1 <= data["overall_rating"] <= 5
    assert isinstance(data["interpretation_clarity"], int) \
        and 1 <= data["interpretation_clarity"] <= 5
    assert isinstance(data["would_recommend"], bool)
    assert data["status"] in ("SUBMITTED", "REVIEWED")


def assert_slot_seat_conservation(slot: dict):
    """Seat buckets never leak: reserved + confirmed + available == capacity."""
    total = slot["seats_reserved"] + slot["seats_confirmed"] + slot["seats_available"]
    assert total == slot["capacity"], (
        f"seat buckets {slot['seats_reserved']}+{slot['seats_confirmed']}"
        f"+{slot['seats_available']} != capacity {slot['capacity']}"
    )
