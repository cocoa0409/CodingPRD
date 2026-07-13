"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version must start at 1+, got {data['version']}"


def assert_funeral_home(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert isinstance(data["stream_credit_balance"], int)
    assert data["stream_credit_balance"] >= 0, "stream_credit_balance is never negative"
    assert isinstance(data["donations_pledged_cents"], int)
    assert isinstance(data["donations_net_cents"], int)


def assert_venue(data: dict):
    _assert_common(data)
    assert isinstance(data["home_id"], str) and data["home_id"]
    assert isinstance(data["capacity"], int)
    assert isinstance(data["turnaround_minutes"], int)


def assert_operator(data: dict):
    _assert_common(data)
    assert data["skill"] in ("CAMERA", "AUDIO", "SUPPORT")
    assert data["duty_status"] in ("OFF_DUTY", "ON_DUTY")


def assert_service_order(data: dict):
    _assert_common(data)
    assert data["broadcast_status"] in ("DRAFT", "SCHEDULED", "LIVE", "ENDED", "CANCELLED")
    assert data["settlement_status"] in ("UNBILLED", "INVOICED", "PAID", "VOID")
    assert data["stream_status"] in ("PENDING", "READY", "FAILED")
    assert data["recording_status"] in ("NONE", "RAW", "EDITING", "READY", "DELIVERED")
    assert data["memorial_status"] in ("DRAFT", "PUBLISHED", "ARCHIVED")
    assert isinstance(data["camera_count"], int)
    assert isinstance(data["failed_access_count"], int)
    assert isinstance(data["access_locked"], bool)


def assert_venue_booking(data: dict):
    _assert_common(data)
    assert data["status"] in ("HELD", "CONFIRMED", "RELEASED")


def assert_camera_assignment(data: dict):
    _assert_common(data)
    assert data["status"] in ("ASSIGNED", "RELEASED")
    assert data["role"] in ("CAMERA", "AUDIO", "SUPPORT")


def assert_guestbook_entry(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "APPROVED", "HIDDEN")


def assert_donation(data: dict):
    _assert_common(data)
    assert data["status"] in ("PLEDGED", "SETTLED", "REFUNDED")
    assert isinstance(data["gross_amount_cents"], int)


def assert_tribute_video(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "CHANGES_REQUESTED", "APPROVED", "PUBLISHED")
    assert isinstance(data["revision_count"], int)
