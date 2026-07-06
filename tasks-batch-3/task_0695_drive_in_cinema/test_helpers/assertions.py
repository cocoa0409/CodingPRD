"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_venue(data: dict):
    assert is_valid_uuid(data.get("id", "")), "venue id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["fm_channel_pool"], list) and len(data["fm_channel_pool"]) >= 1
    assert isinstance(data["turnaround_buffer_minutes"], int)
    assert isinstance(data["no_show_grace_minutes"], int)
    assert isinstance(data["version"], int)


def assert_lot(data: dict):
    assert is_valid_uuid(data.get("id", "")), "lot id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["stall_count"], int) and data["stall_count"] >= 1
    assert isinstance(data["person_capacity"], int) and data["person_capacity"] >= 1
    assert data["status"] in ("OPEN", "CLOSED")


def assert_film(data: dict):
    assert is_valid_uuid(data.get("id", "")), "film id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["title"], str)
    assert isinstance(data["runtime_minutes"], int) and data["runtime_minutes"] >= 1
    assert data["rating"] in ("G", "PG", "PG13", "R")
    # common_fields:false — no version, no updated_at.
    assert "version" not in data, "Film must not expose version (common_fields:false)"


def assert_showtime(data: dict):
    assert is_valid_uuid(data.get("id", "")), "showtime id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("end_utc", "")), "end_utc must be ISO 8601"
    assert data["pricing_mode"] in ("PER_CAR", "PER_PERSON")
    assert data["status"] in ("SCHEDULED", "WEATHER_HOLD", "CANCELLED", "COMPLETED")
    assert isinstance(data["reserved_stall_count"], int)
    assert isinstance(data["reserved_person_count"], int)
    assert isinstance(data["version"], int)


def assert_reservation(data: dict):
    assert is_valid_uuid(data.get("id", "")), "reservation id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert data["occupancy_status"] in (
        "CONFIRMED", "CHECKED_IN", "SCANNED", "NO_SHOW", "CANCELLED",
    )
    assert data["payment_status"] in ("UNPAID", "PAID", "REFUNDED")
    assert isinstance(data["amount_due_cents"], int)
    assert isinstance(data["amount_paid_cents"], int)
    assert isinstance(data["stalls_used"], int)
    assert isinstance(data["occupant_count"], int) and data["occupant_count"] >= 1
    assert isinstance(data["version"], int)


def assert_concession_order(data: dict):
    assert is_valid_uuid(data.get("id", "")), "order id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert data["status"] in ("PENDING", "PAID", "FULFILLED", "CANCELLED")
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["tax_cents"], int)
    assert isinstance(data["service_fee_cents"], int)
    assert isinstance(data["total_cents"], int)


def assert_season_pass(data: dict):
    assert is_valid_uuid(data.get("id", "")), "pass id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert data["tier"] in ("SILVER", "GOLD")
    assert data["status"] in ("ACTIVE", "REVOKED")
    assert isinstance(data["max_redemptions"], int) and data["max_redemptions"] >= 1
    assert isinstance(data["redemptions_used"], int)


def assert_private_rental(data: dict):
    assert is_valid_uuid(data.get("id", "")), "rental id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert data["status"] in ("REQUESTED", "APPROVED", "REJECTED", "CANCELLED")
    assert isinstance(data["quote_cents"], int)


def assert_fm_channel_assignment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "fm assignment id must be valid UUID"
    assert isinstance(data["frequency"], str)
    assert data["status"] in ("ACTIVE", "RELEASED")


def assert_refund_record(data: dict):
    assert is_valid_uuid(data.get("id", "")), "refund id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert data["source_type"] in ("RESERVATION", "CONCESSION_ORDER")
    assert data["reason"] in ("WEATHER", "VOLUNTARY_CANCEL", "RESERVATION_CASCADE")
    assert isinstance(data["amount_cents"], int)
    # common_fields:false — no version.
    assert "version" not in data, "RefundRecord must not expose version (common_fields:false)"
