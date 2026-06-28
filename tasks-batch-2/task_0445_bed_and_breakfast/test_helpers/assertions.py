"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the response structure against the PRD contract.
Entities with the standard quartet (§2.5) carry id/created_at/updated_at/version;
Guest and PaymentLedgerEntry carry only id and created_at.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_ROOM_STATUSES = ["ACTIVE", "RETIRED"]
_PACKAGE_STATUSES = ["ACTIVE", "RETIRED"]
_GIFT_STATUSES = ["ACTIVE", "DEPLETED", "EXPIRED", "VOID"]
_RESERVATION_STATUSES = [
    "PENDING", "CONFIRMED", "CHECKED_IN", "CHECKED_OUT", "CANCELLED", "NO_SHOW",
]
_PAYMENT_STATUSES = ["UNPAID", "DEPOSIT_HELD", "SETTLED", "REFUNDED", "FORFEITED"]
_CHANNELS = ["DIRECT", "OTA"]
_BREAKFAST_STATUSES = ["REQUESTED", "CONFIRMED", "CANCELLED"]
_HOUSEKEEPING_STATUSES = ["PENDING", "IN_PROGRESS", "DONE", "SKIPPED"]
_REMITTANCE_STATUSES = ["OPEN", "FILED"]
_REMITTANCE_VARIANTS = ["ESTIMATED", "FINAL"]
_LEDGER_KINDS = ["DEPOSIT", "REFUND", "REDEMPTION", "FORFEIT"]


def _assert_quartet(data: dict):
    """Standard system-managed quartet (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an int"
    assert data["version"] >= 1, "version starts at 1"


def assert_inn(data: dict):
    _assert_quartet(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["lodging_tax_rate_bps"], int)
    assert isinstance(data["checkin_time"], str)
    assert isinstance(data["checkout_time"], str)
    assert isinstance(data["gift_cert_expiry_days"], int)
    assert isinstance(data["turnover_minutes"], int)


def assert_room(data: dict):
    _assert_quartet(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["base_rate_cents"], int) and data["base_rate_cents"] >= 0
    assert isinstance(data["max_occupancy"], int) and data["max_occupancy"] >= 1
    assert isinstance(data["is_taxable"], bool)
    assert data["status"] in _ROOM_STATUSES


def assert_rate_period(data: dict):
    _assert_quartet(data)
    assert isinstance(data["label"], str)
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert isinstance(data["rate_multiplier_bps"], int) and data["rate_multiplier_bps"] >= 0
    assert isinstance(data["min_nights"], int) and data["min_nights"] >= 1


def assert_package(data: dict):
    _assert_quartet(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["flat_add_cents"], int) and data["flat_add_cents"] >= 0
    assert isinstance(data["per_night_add_cents"], int) and data["per_night_add_cents"] >= 0
    assert isinstance(data["is_taxable"], bool)
    assert data["status"] in _PACKAGE_STATUSES


def assert_guest(data: dict):
    """Guest is leaner (PRD §2.5): id + created_at only, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "Guest must not expose updated_at"
    assert "version" not in data, "Guest must not expose version"
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and "@" in data["email"]


def assert_gift_certificate(data: dict):
    _assert_quartet(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["face_value_cents"], int) and data["face_value_cents"] >= 1
    assert isinstance(data["remaining_cents"], int) and data["remaining_cents"] >= 0
    assert isinstance(data["issued_on"], str)
    assert isinstance(data["expires_on"], str)
    assert data["status"] in _GIFT_STATUSES


def assert_booking(data: dict):
    _assert_quartet(data)
    assert data["channel"] in _CHANNELS
    assert isinstance(data["checkin_date"], str)
    assert isinstance(data["checkout_date"], str)
    assert isinstance(data["guest_count"], int) and data["guest_count"] >= 1
    assert isinstance(data["nights"], int) and data["nights"] >= 1
    for money_field in (
        "room_charge_cents", "package_charge_cents", "taxable_base_cents",
        "lodging_tax_cents", "total_cents", "deposit_due_cents",
        "deposit_paid_cents", "refund_cents",
    ):
        assert isinstance(data[money_field], int), f"{money_field} must be integer cents"
        assert data[money_field] >= 0, f"{money_field} must be non-negative"
    assert data["reservation_status"] in _RESERVATION_STATUSES
    assert data["payment_status"] in _PAYMENT_STATUSES
    assert isinstance(data["remitted"], bool)


def assert_breakfast_plan(data: dict):
    _assert_quartet(data)
    assert isinstance(data["party_size"], int) and data["party_size"] >= 1
    assert isinstance(data["dietary_flags"], list)
    assert data["status"] in _BREAKFAST_STATUSES


def assert_housekeeping_task(data: dict):
    _assert_quartet(data)
    assert is_valid_uuid(data.get("booking_id", "")), "booking_id must be a valid UUID"
    assert is_valid_uuid(data.get("room_id", "")), "room_id must be a valid UUID"
    assert isinstance(data["ready_after"], str)
    assert data["status"] in _HOUSEKEEPING_STATUSES


def assert_tax_remittance(data: dict):
    _assert_quartet(data)
    assert data["variant"] in _REMITTANCE_VARIANTS
    assert isinstance(data["swept_booking_count"], int) and data["swept_booking_count"] >= 0
    assert isinstance(data["tax_total_cents"], int) and data["tax_total_cents"] >= 0
    assert data["status"] in _REMITTANCE_STATUSES


def assert_ledger_entry(data: dict):
    """PaymentLedgerEntry is append-only (PRD §2.5): id + created_at only."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "PaymentLedgerEntry must not expose updated_at"
    assert "version" not in data, "PaymentLedgerEntry must not expose version"
    assert data["source_kind"] in _LEDGER_KINDS
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["occurred_on"], str)
