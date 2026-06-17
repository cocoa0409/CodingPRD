"""Entity assertions and domain invariant checkers (Trampoline Park API)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id/created_at/updated_at/version present for full common_fields entities."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version int >= 1"


def assert_park(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["grip_sock_price_cents"] >= 0
    assert data["minor_age_threshold"] >= 1
    assert data["walkin_surcharge_cents"] >= 0
    assert 0 <= data["party_deposit_pct"] <= 1
    assert data["cancellation_cutoff_minutes"] >= 0


def assert_slot(data: dict):
    _assert_common(data)
    assert data["jump_capacity"] >= 1
    assert data["base_price_cents"] >= 0
    assert data["seats_taken"] >= 0
    assert data["status"] in ("OPEN", "FULL", "CLOSED")
    assert isinstance(data["closed"], bool)


def assert_slot_invariants(data: dict):
    """Derived slot posture must be internally consistent (PRD §3.2)."""
    assert data["seats_taken"] >= 0, "seats_taken never negative"
    if data["closed"]:
        assert data["status"] == "CLOSED"
    elif data["seats_taken"] >= data["jump_capacity"]:
        assert data["status"] == "FULL"
    else:
        assert data["status"] == "OPEN"


def assert_participant(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["is_minor"], bool)


def assert_waiver(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("signed_at", "")), "signed_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("expires_at", "")), "expires_at must be ISO 8601"
    assert data["status"] in ("SIGNED", "VOIDED")


def assert_jump_pass(data: dict):
    _assert_common(data)
    assert data["channel"] in ("RESERVATION", "WALKIN")
    assert data["sock_count"] >= 1
    assert data["admission_status"] in (
        "RESERVED", "CHECKED_IN", "COMPLETED", "CANCELLED", "NO_SHOW")
    assert data["payment_status"] in (
        "UNPAID", "PAID", "REFUNDED", "PARTIALLY_REFUNDED")
    assert data["base_charge_cents"] >= 0
    assert data["amount_paid_cents"] >= 0
    assert data["amount_refunded_cents"] >= 0
    assert isinstance(data["included_visit_consumed"], bool)


def assert_add_on(data: dict):
    """PassAddOn is immutable (common_fields:false): id + created_at only."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "PassAddOn must not carry updated_at"
    assert "version" not in data, "PassAddOn must not carry version"
    assert data["sku"] in ("ARM_SLEEVES", "LOCKER", "FAST_PASS", "PHOTO_PKG")
    assert data["quantity"] >= 1
    assert data["unit_price_cents"] >= 0
    assert data["line_total_cents"] == data["unit_price_cents"] * data["quantity"]


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["full_name"], str)


def assert_membership(data: dict):
    _assert_common(data)
    assert data["tier"] in ("BRONZE", "SILVER", "GOLD")
    assert data["status"] in ("ACTIVE", "PAST_DUE", "CANCELLED")
    assert data["included_visits_remaining"] >= 0
    assert data["current_cycle_index"] >= 0


def assert_room(data: dict):
    _assert_common(data)
    assert data["room_capacity"] >= 1
    assert data["turnover_buffer_minutes"] >= 0


def assert_package(data: dict):
    _assert_common(data)
    assert data["per_guest_cents"] >= 0
    assert data["base_room_fee_cents"] >= 0
    assert data["min_guests"] >= 1


def assert_party_booking(data: dict):
    _assert_common(data)
    assert data["guest_count"] >= 1
    assert data["booking_status"] in (
        "PENDING", "DEPOSIT_HELD", "CONFIRMED", "CHECKED_IN", "COMPLETED", "CANCELLED")
    assert data["total_cents"] >= 0
    assert data["deposit_cents"] >= 0
    assert data["balance_paid_cents"] >= 0


def assert_incident(data: dict):
    _assert_common(data)
    assert data["severity"] in ("MINOR", "MODERATE", "SEVERE")
    assert data["status"] in ("FILED", "REVIEWED", "SIGNED_OFF", "VOIDED")
