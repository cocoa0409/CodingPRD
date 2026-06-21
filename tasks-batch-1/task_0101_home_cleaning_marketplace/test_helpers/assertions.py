"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)

_HOME_SIZES = ["STUDIO", "ONE_BR", "TWO_BR", "THREE_BR", "FOUR_PLUS_BR"]
_BOOKING_STATES = ["SCHEDULED", "RESCHEDULED", "COMPLETED", "CANCELLED",
                   "RECLEAN_REQUESTED", "RECLEAN_SCHEDULED"]
_CLEANER_STATES = ["APPLIED", "CHECK_PENDING", "CHECK_PASSED", "ACTIVE",
                   "CHECK_FAILED", "SUSPENDED"]
_SERIES_STATES = ["ACTIVE", "PAUSED", "CANCELLED"]
_LEDGER_KINDS = ["CHARGE", "REFUND", "RECLEAN_CREDIT", "CHANGE_FEE"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def _assert_append_only_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only record must NOT carry updated_at"
    assert "version" not in data, "append-only record must NOT carry version"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["wallet_credit_cents"], int)
    assert data["wallet_credit_cents"] >= 0, "wallet_credit_cents must never be negative"
    assert isinstance(data["lifetime_booking_count"], int)
    assert data["lifetime_booking_count"] >= 0


def assert_address(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["line1"], str)
    assert isinstance(data["postal_code"], str)
    assert data["home_size"] in _HOME_SIZES
    assert isinstance(data["archived"], bool)


def assert_cleaner(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str)
    assert isinstance(data["service_postal_codes"], list)
    assert data["status"] in _CLEANER_STATES
    assert isinstance(data["rating_sum"], int) and data["rating_sum"] >= 0
    assert isinstance(data["rating_count"], int) and data["rating_count"] >= 0
    assert isinstance(data["completed_job_count"], int) and data["completed_job_count"] >= 0


def assert_background_check(data: dict):
    _assert_common(data)
    assert isinstance(data["cleaner_id"], str)
    assert data["result"] in ["PENDING", "CLEAR", "ADVERSE"]


def assert_pricing_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["base_price_cents"], dict)
    assert isinstance(data["active"], bool)


def assert_booking_series(data: dict):
    _assert_common(data)
    assert data["status"] in _SERIES_STATES
    assert data["cadence"] in ["WEEKLY", "BIWEEKLY"]


def assert_booking(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["address_id"], str)
    assert isinstance(data["pricing_plan_id"], str)
    assert data["home_size"] in _HOME_SIZES
    assert data["status"] in _BOOKING_STATES
    assert isinstance(data["quoted_price_cents"], int)
    assert isinstance(data["change_fee_cents"], int)
    assert isinstance(data["is_reclean"], bool)
    assert isinstance(data["add_ons"], list)
    assert data["supplies_provided_by"] in ["CUSTOMER", "CLEANER"]


def assert_preferred_pro(data: dict):
    _assert_common(data)
    assert isinstance(data["priority"], int) and data["priority"] >= 1


def assert_cleaner_payout(data: dict):
    _assert_common(data)
    assert isinstance(data["base_payout_cents"], int)
    assert isinstance(data["tip_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert data["total_cents"] == data["base_payout_cents"] + data["tip_cents"], \
        "total_cents must equal base_payout_cents + tip_cents"


def assert_tip(data: dict):
    _assert_append_only_common(data)
    assert isinstance(data["booking_id"], str)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["cleaner_id"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


def assert_ledger_entry(data: dict):
    _assert_append_only_common(data)
    assert isinstance(data["customer_id"], str)
    assert data["kind"] in _LEDGER_KINDS
    assert isinstance(data["amount_cents"], int)
