"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_room(data: dict):
    """Assert all required fields on a Room entity."""
    assert is_valid_uuid(data.get("id", "")), f"Room id must be valid UUID, got {data.get('id')}"
    assert isinstance(data.get("name"), str) and len(data["name"]) > 0, "Room name must be non-empty string"
    assert isinstance(data.get("capacity"), int) and data["capacity"] > 0, f"Room capacity must be positive int, got {data.get('capacity')}"
    assert isinstance(data.get("floor"), int), f"Room floor must be int, got {data.get('floor')}"
    assert data.get("tier") in ("STANDARD", "PREMIUM"), f"Room tier must be STANDARD or PREMIUM, got {data.get('tier')}"
    assert data.get("status") in ("ACTIVE", "MAINTENANCE", "DECOMMISSIONED"), f"Room status invalid: {data.get('status')}"
    assert isinstance(data.get("hourly_rate_cents"), int), f"hourly_rate_cents must be int, got {data.get('hourly_rate_cents')}"
    assert isinstance(data.get("ops_run_index"), int), f"ops_run_index must be int, got {data.get('ops_run_index')}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, f"version must be int >= 1, got {data.get('version')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"created_at must be ISO 8601, got {data.get('created_at')}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"updated_at must be ISO 8601, got {data.get('updated_at')}"
    # amenities is optional (list)
    if "amenities" in data and data["amenities"] is not None:
        assert isinstance(data["amenities"], list), f"amenities must be a list, got {type(data.get('amenities'))}"
    # peak_multiplier defaults to 1.0
    if "peak_multiplier" in data and data["peak_multiplier"] is not None:
        assert isinstance(data["peak_multiplier"], (int, float)), f"peak_multiplier must be numeric, got {data.get('peak_multiplier')}"


def assert_booking(data: dict):
    """Assert all required fields on a Booking entity."""
    assert is_valid_uuid(data.get("id", "")), f"Booking id must be valid UUID, got {data.get('id')}"
    assert is_valid_uuid(data.get("room_id", "")), f"Booking room_id must be valid UUID, got {data.get('room_id')}"
    assert isinstance(data.get("organizer_id"), str) and len(data["organizer_id"]) > 0, "organizer_id must be non-empty"
    assert isinstance(data.get("title"), str) and len(data["title"]) > 0, "title must be non-empty string"
    assert is_iso8601_timestamp(data.get("start_time", "")), f"start_time must be ISO 8601, got {data.get('start_time')}"
    assert is_iso8601_timestamp(data.get("end_time", "")), f"end_time must be ISO 8601, got {data.get('end_time')}"
    assert isinstance(data.get("attendee_count"), int), f"attendee_count must be int, got {data.get('attendee_count')}"
    valid_statuses = ("TENTATIVE", "PENDING_APPROVAL", "CONFIRMED", "CHECKED_IN", "COMPLETED", "CANCELLED", "NO_SHOW")
    assert data.get("status") in valid_statuses, f"Booking status invalid: {data.get('status')}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, f"version must be int >= 1, got {data.get('version')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"created_at must be ISO 8601, got {data.get('created_at')}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"updated_at must be ISO 8601, got {data.get('updated_at')}"
    # cost_cents is computed on confirmation
    if data.get("status") in ("CONFIRMED", "CHECKED_IN", "COMPLETED"):
        assert isinstance(data.get("cost_cents"), int), f"cost_cents must be int when confirmed, got {data.get('cost_cents')}"
    # checked_in_at set when checked in
    if data.get("status") in ("CHECKED_IN", "COMPLETED"):
        if data.get("checked_in_at") is not None:
            assert is_iso8601_timestamp(data["checked_in_at"]), f"checked_in_at must be ISO 8601, got {data.get('checked_in_at')}"


def assert_series(data: dict):
    """Assert all required fields on a Series entity."""
    assert is_valid_uuid(data.get("id", "")), f"Series id must be valid UUID, got {data.get('id')}"
    assert is_valid_uuid(data.get("room_id", "")), f"Series room_id must be valid UUID, got {data.get('room_id')}"
    assert isinstance(data.get("organizer_id"), str) and len(data["organizer_id"]) > 0, "organizer_id must be non-empty"
    assert isinstance(data.get("title"), str) and len(data["title"]) > 0, "title must be non-empty string"
    assert data.get("recurrence_rule") in ("DAILY", "WEEKLY", "BIWEEKLY"), f"recurrence_rule invalid: {data.get('recurrence_rule')}"
    assert isinstance(data.get("duration_minutes"), int), f"duration_minutes must be int, got {data.get('duration_minutes')}"
    assert isinstance(data.get("attendee_count"), int), f"attendee_count must be int, got {data.get('attendee_count')}"
    assert data.get("status") in ("ACTIVE", "CANCELLED"), f"Series status invalid: {data.get('status')}"
    assert isinstance(data.get("total_bookings"), int), f"total_bookings must be int, got {data.get('total_bookings')}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, f"version must be int >= 1, got {data.get('version')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"created_at must be ISO 8601, got {data.get('created_at')}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"updated_at must be ISO 8601, got {data.get('updated_at')}"


def assert_waitlist(data: dict):
    """Assert all required fields on a Waitlist entity."""
    assert is_valid_uuid(data.get("id", "")), f"Waitlist id must be valid UUID, got {data.get('id')}"
    assert is_valid_uuid(data.get("room_id", "")), f"Waitlist room_id must be valid UUID, got {data.get('room_id')}"
    assert isinstance(data.get("requester_id"), str) and len(data["requester_id"]) > 0, "requester_id must be non-empty"
    assert isinstance(data.get("title"), str) and len(data["title"]) > 0, "title must be non-empty string"
    assert is_iso8601_timestamp(data.get("start_time", "")), f"start_time must be ISO 8601, got {data.get('start_time')}"
    assert is_iso8601_timestamp(data.get("end_time", "")), f"end_time must be ISO 8601, got {data.get('end_time')}"
    assert isinstance(data.get("attendee_count"), int), f"attendee_count must be int, got {data.get('attendee_count')}"
    assert data.get("status") in ("WAITING", "PROMOTED", "EXPIRED", "CANCELLED"), f"Waitlist status invalid: {data.get('status')}"
    assert isinstance(data.get("position"), int), f"position must be int, got {data.get('position')}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, f"version must be int >= 1, got {data.get('version')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"created_at must be ISO 8601, got {data.get('created_at')}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"updated_at must be ISO 8601, got {data.get('updated_at')}"


def assert_audit_log(data: dict):
    """Assert all required fields on an AuditLog entity."""
    assert is_valid_uuid(data.get("id", "")), f"AuditLog id must be valid UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(data.get("timestamp", "")), f"timestamp must be ISO 8601, got {data.get('timestamp')}"
    assert isinstance(data.get("actor_id"), str) and len(data["actor_id"]) > 0, "actor_id must be non-empty"
    assert data.get("actor_role") in ("employee", "manager", "facility_admin"), f"actor_role invalid: {data.get('actor_role')}"
    assert isinstance(data.get("action"), str) and len(data["action"]) > 0, "action must be non-empty string"
    assert isinstance(data.get("resource_type"), str) and len(data["resource_type"]) > 0, "resource_type must be non-empty"
    assert isinstance(data.get("resource_id"), str) and len(data["resource_id"]) > 0, "resource_id must be non-empty"
    assert isinstance(data.get("details"), dict), f"details must be dict, got {type(data.get('details'))}"
