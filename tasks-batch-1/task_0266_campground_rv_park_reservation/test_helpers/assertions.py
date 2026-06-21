"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)

_SITE_TYPES = {"TENT", "RV", "CABIN"}
_HOOKUP_LEVELS = {"NONE", "PARTIAL", "FULL"}
_SITE_STATUSES = {"ACTIVE", "MAINTENANCE", "RETIRED"}
_HOLD_STATUSES = {"ACTIVE", "CLEARED"}
_RESERVATION_STATUSES = {"REQUESTED", "CONFIRMED", "CHECKED_IN", "CHECKED_OUT", "CANCELLED"}
_PAYMENT_STATUSES = {"UNPAID", "DEPOSIT_PAID", "PAID_IN_FULL", "REFUNDED"}
_STAY_CLASSES = {"SHORT_TERM", "LONG_TERM"}
_ADDON_KINDS = {"FIREWOOD", "EXTRA_VEHICLE", "PET_FEE", "EARLY_CHECKIN"}
_ADDON_STATUSES = {"ACTIVE", "REMOVED"}
_PAYMENT_TYPES = {"DEPOSIT", "BALANCE", "REFUND"}


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_park(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["deposit_pct"], (int, float)) and 0 <= data["deposit_pct"] <= 1
    assert isinstance(data["tax_rate"], (int, float)) and 0 <= data["tax_rate"] <= 1
    assert isinstance(data["long_stay_nights_threshold"], int)


def assert_rate_plan(data: dict):
    _assert_common_fields(data)
    assert data["site_type"] in _SITE_TYPES
    assert isinstance(data["nightly_rate_cents"], int)
    assert isinstance(data["weekly_rate_cents"], int)
    assert isinstance(data["monthly_rate_cents"], int)


def assert_season(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)


def assert_cancellation_policy(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_refund_min_days"], int)
    assert isinstance(data["half_refund_min_days"], int)
    assert data["full_refund_min_days"] >= data["half_refund_min_days"] >= 0


def assert_site(data: dict):
    _assert_common_fields(data)
    assert data["site_type"] in _SITE_TYPES
    assert data["hookup_level"] in _HOOKUP_LEVELS
    assert data["status"] in _SITE_STATUSES
    assert isinstance(data["max_length_of_stay_nights"], int)
    assert isinstance(data["booked_night_count"], int) and data["booked_night_count"] >= 0


def assert_maintenance_hold(data: dict):
    _assert_common_fields(data)
    assert data["status"] in _HOLD_STATUSES
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)


def assert_guest(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["completed_stays_count"], int) and data["completed_stays_count"] >= 0
    assert isinstance(data["lifetime_spend_cents"], int) and data["lifetime_spend_cents"] >= 0


def assert_reservation(data: dict):
    _assert_common_fields(data)
    assert data["reservation_status"] in _RESERVATION_STATUSES
    assert data["payment_status"] in _PAYMENT_STATUSES
    assert data["stay_class"] in _STAY_CLASSES
    assert isinstance(data["nights"], int) and data["nights"] >= 1
    for fld in (
        "stay_charge_cents", "season_surcharge_cents", "addon_total_cents",
        "discount_cents", "tax_cents", "total_due_cents", "deposit_due_cents",
        "amount_paid_cents", "balance_cents",
    ):
        assert isinstance(data[fld], int), f"{fld} must be an integer (cents)"
    # balance is always total - amount_paid.
    assert data["balance_cents"] == data["total_due_cents"] - data["amount_paid_cents"], (
        "balance_cents must equal total_due_cents - amount_paid_cents"
    )


def assert_add_on(data: dict):
    _assert_common_fields(data)
    assert data["kind"] in _ADDON_KINDS
    assert data["status"] in _ADDON_STATUSES
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert isinstance(data["taxable"], bool)


def assert_payment(data: dict):
    """Payment is append-only: id + created_at present, no version field."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["type"] in _PAYMENT_TYPES
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert "version" not in data, "Payment is an immutable ledger row and must not carry a version"
    assert "updated_at" not in data, "Payment is an immutable ledger row and must not carry updated_at"
