"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_course(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Course.id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert 55.0 <= float(data["course_rating"]) <= 85.0
    assert 55 <= int(data["slope_rating"]) <= 155
    assert int(data["peak_fee_cents"]) >= 0
    assert int(data["offpeak_fee_cents"]) >= 0
    assert 0 <= int(data["peak_start_hour"]) <= 23
    assert 0 <= int(data["peak_end_hour"]) <= 23
    assert int(data["peak_end_hour"]) > int(data["peak_start_hour"])
    assert 0.0 <= float(data["member_discount_pct"]) <= 1.0
    assert int(data["version"]) >= 1


def assert_golfer(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Golfer.id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["membership_tier"] in ("MEMBER", "PUBLIC")
    assert int(data["handicap_revision"]) >= 0
    assert int(data["version"]) >= 1


def assert_score(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Score.id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["golfer_id"])
    assert is_valid_uuid(data["course_id"])
    assert 50 <= int(data["adjusted_gross_score"]) <= 150
    assert data["status"] in ("POSTED", "VOID")
    assert int(data["version"]) >= 1


def assert_tee_time(data: dict):
    assert is_valid_uuid(data.get("id", "")), "TeeTime.id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["course_id"])
    assert data["group_type"] in ("TWOSOME", "FOURSOME")
    assert int(data["capacity"]) in (2, 4)
    assert data["status"] in ("OPEN", "FULL", "CLOSED")
    assert int(data["confirmed_count"]) >= 0
    assert int(data["confirmed_count"]) <= int(data["capacity"])
    assert int(data["version"]) >= 1


def assert_booking(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Booking.id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["tee_time_id"])
    assert is_valid_uuid(data["golfer_id"])
    assert data["status"] in ("CONFIRMED", "STANDBY", "CANCELLED")
    assert int(data["green_fee_cents"]) >= 0
    assert int(data["standby_rank"]) >= 0
    assert int(data["version"]) >= 1


def assert_handicap_revision(data: dict):
    """HandicapRevision is append-only: id + created_at only, plus business fields.
    It carries NO version and NO updated_at field."""
    assert is_valid_uuid(data.get("id", "")), "HandicapRevision.id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert int(data["revision_number"]) >= 1


def assert_seat_conservation(tee_time: dict):
    """Slot occupancy invariant: confirmed_count never exceeds capacity (PRD §3.6)."""
    assert int(tee_time["confirmed_count"]) <= int(tee_time["capacity"]), (
        f"confirmed_count {tee_time['confirmed_count']} exceeds capacity {tee_time['capacity']}"
    )
