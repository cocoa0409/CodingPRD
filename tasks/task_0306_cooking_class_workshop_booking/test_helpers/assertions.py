"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators (is_valid_uuid, is_iso8601_timestamp)
internally. Field names are PRD-exact.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version (entities with common_fields:true)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at creation (>= 1)"


def _assert_ledger_common(data: dict):
    """id + created_at only (append-only entities; NO updated_at, NO version)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_instructor(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert data["max_skill_level"] in [
        "BEGINNER", "INTERMEDIATE", "ADVANCED", "PROFESSIONAL",
    ]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["dietary_flags"], list)
    assert isinstance(data["wallet_credit_cents"], int)
    assert data["wallet_credit_cents"] >= 0, "wallet_credit_cents never falls below 0"
    assert isinstance(data["reliability_score"], int)
    assert 0 <= data["reliability_score"] <= 100, "reliability_score clamped to [0,100]"
    assert data["booking_status"] in ["GOOD_STANDING", "BLOCKED"]


def assert_template(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["skill_level"] in [
        "BEGINNER", "INTERMEDIATE", "ADVANCED", "PROFESSIONAL",
    ]
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert 1 <= data["default_capacity"] <= 40
    assert isinstance(data["station_fixed_cost_cents"], int) and data["station_fixed_cost_cents"] >= 0
    assert 0 <= data["prep_minutes"] <= 480
    assert 0 <= data["cleanup_minutes"] <= 240
    assert data["status"] in ["DRAFT", "PUBLISHED", "RETIRED"]


def assert_series(data: dict):
    _assert_common(data)
    assert data["cadence"] in ["WEEKLY", "BIWEEKLY", "MONTHLY"]
    assert 1 <= data["occurrence_count"] <= 52
    assert data["status"] in ["DRAFT", "PUBLISHED", "CANCELLED"]
    assert isinstance(data["active_session_count"], int) and data["active_session_count"] >= 0


def assert_session(data: dict):
    _assert_common(data)
    assert data["event_type"] in ["GROUP", "PRIVATE"]
    assert 1 <= data["planned_seats"] <= 40
    assert isinstance(data["confirmed_seats"], int) and data["confirmed_seats"] >= 0
    assert isinstance(data["prep_cost_per_seat_cents"], int) and data["prep_cost_per_seat_cents"] >= 0
    assert isinstance(data["private_event_fee_cents"], int) and data["private_event_fee_cents"] >= 0
    assert data["status"] in [
        "SCHEDULED", "OPEN", "FULL", "LOCKED", "COMPLETED", "CANCELLED",
    ]
    assert data["confirmed_seats"] <= data["planned_seats"], (
        "confirmed_seats never exceeds planned_seats"
    )


def assert_ingredient_line(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert float(data["qty_per_seat"]) >= 0
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 0
    assert data["dietary_tag"] in [
        "NEUTRAL", "CONTAINS_GLUTEN", "CONTAINS_NUT", "CONTAINS_DAIRY", "ANIMAL_PRODUCT",
    ]


def assert_booking(data: dict):
    _assert_common(data)
    assert 1 <= data["seats_requested"] <= 40
    assert isinstance(data["charge_cents"], int) and data["charge_cents"] >= 0
    assert isinstance(data["gift_card_applied_cents"], int) and data["gift_card_applied_cents"] >= 0
    assert isinstance(data["wallet_applied_cents"], int) and data["wallet_applied_cents"] >= 0
    assert isinstance(data["card_applied_cents"], int) and data["card_applied_cents"] >= 0
    assert isinstance(data["refund_cents"], int) and data["refund_cents"] >= 0
    assert isinstance(data["refilled_from_waitlist"], bool)
    assert data["lifecycle_status"] in [
        "PENDING", "CONFIRMED", "CANCELLED", "NO_SHOW", "ATTENDED",
    ]
    assert data["payment_status"] in [
        "UNPAID", "PAID", "REFUNDED", "PARTIALLY_REFUNDED",
    ]


def assert_waitlist_entry(data: dict):
    _assert_common(data)
    assert 1 <= data["seats_requested"] <= 40
    assert data["queue_status"] in ["WAITING", "PROMOTED", "EXPIRED", "WITHDRAWN"]


def assert_substitution(data: dict):
    _assert_common(data)
    assert isinstance(data["alternate_unit_cost_cents"], int) and data["alternate_unit_cost_cents"] >= 0
    assert isinstance(data["surcharge_cents"], int) and data["surcharge_cents"] >= 0
    assert data["status"] in ["REQUESTED", "APPROVED", "REJECTED", "REVERTED"]


def assert_gift_card(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["initial_value_cents"], int) and data["initial_value_cents"] >= 1
    assert isinstance(data["balance_cents"], int) and data["balance_cents"] >= 0
    assert data["status"] in ["ACTIVE", "DEPLETED", "VOIDED"]


def assert_gift_card_txn(data: dict):
    """Append-only ledger entry: id + created_at only, no updated_at/version."""
    _assert_ledger_common(data)
    assert "updated_at" not in data, "GiftCardTxn is append-only — no updated_at"
    assert "version" not in data, "GiftCardTxn is append-only — no version"
    assert data["kind"] in ["ISSUE", "REDEEM", "RELOAD", "REVERSAL"]
    assert isinstance(data["amount_cents"], int)


def assert_no_show_record(data: dict):
    """Append-only strike record: id + created_at only, no updated_at/version."""
    _assert_ledger_common(data)
    assert "updated_at" not in data, "NoShowRecord is append-only — no updated_at"
    assert "version" not in data, "NoShowRecord is append-only — no version"
    assert data["kind"] in ["NO_SHOW", "LATE_CANCEL"]
    assert data["settlement_status"] in ["PENDING", "SETTLED", "WAIVED"]


def assert_payment_split_sums_to(booking: dict, amount_due: int):
    """The three applied funding fields sum exactly to amount_due (PRD §3.6)."""
    total = (
        booking["gift_card_applied_cents"]
        + booking["wallet_applied_cents"]
        + booking["card_applied_cents"]
    )
    assert total == amount_due, (
        f"gift_card + wallet + card applied ({total}) must equal amount_due ({amount_due})"
    )
