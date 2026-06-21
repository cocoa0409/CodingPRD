"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the response structure against the PRD contract.
Entities with the standard quartet (PRD §2.4) carry id/created_at/updated_at/version;
Settlement and LedgerEntry carry only id and created_at.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_LOUNGE_STATUSES = ["OPEN", "OVERFLOW", "CLOSED"]
_VISIT_STATUSES = [
    "HELD", "CHECKED_IN", "COMPLETED", "NO_SHOW", "CANCELLED", "ABANDONED",
]
_ENTRY_MODES = ["ALLOTMENT", "OVERAGE", "DAY_PASS"]
_MEMBER_STANDINGS = ["GOOD", "SUSPENDED"]
_CARD_STATUSES = ["BASIC", "SILVER", "GOLD"]
_FARE_CLASSES = ["ECONOMY", "BUSINESS", "FIRST"]
_PLAN_TIERS = ["STANDARD", "PRESTIGE", "PRESTIGE_PLUS"]
_DAY_PASS_STATUSES = ["ISSUED", "REDEEMED", "REFUNDED", "EXPIRED"]
_GUEST_FUNDING = ["GUEST_ALLOTMENT", "GUEST_CHARGE"]
_SETTLEMENT_STATUSES = ["PAYABLE", "PAID", "REVERSED"]
_LEDGER_KINDS = [
    "OVERAGE", "GUEST_CHARGE", "LOUNGE_GUEST_FEE", "DAY_PASS",
    "OVERAGE_REVERSAL", "DAY_PASS_REFUND",
]
_LEDGER_STATUSES = ["POSTED", "VOID"]
_SHOWER_RESERVATION_STATUSES = ["BOOKED", "CANCELLED", "COMPLETED"]


def _assert_quartet(data: dict):
    """Standard system-managed quartet (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an int"
    assert data["version"] >= 1, "version starts at 1"


def _assert_event_record(data: dict):
    """Append-only event record (PRD §2.4): id + created_at only."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only record must not expose updated_at"
    assert "version" not in data, "append-only record must not expose version"


def assert_plan(data: dict):
    _assert_quartet(data)
    assert data["tier"] in _PLAN_TIERS
    assert isinstance(data["included_visits_per_year"], int)
    assert isinstance(data["included_guest_visits_per_year"], int) and data["included_guest_visits_per_year"] >= 0
    assert isinstance(data["overage_charge_cents"], int) and data["overage_charge_cents"] >= 0
    assert isinstance(data["guest_charge_cents"], int) and data["guest_charge_cents"] >= 0
    assert data["min_card_status"] in _CARD_STATUSES
    assert isinstance(data["annual_fee_cents"], int) and data["annual_fee_cents"] >= 0


def assert_lounge(data: dict):
    _assert_quartet(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["airport_code"], str)
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["settlement_rate_cents"], int) and data["settlement_rate_cents"] >= 0
    assert isinstance(data["guest_fee_cents"], int) and data["guest_fee_cents"] >= 0
    assert isinstance(data["day_pass_price_cents"], int) and data["day_pass_price_cents"] >= 0
    assert data["status"] in _LOUNGE_STATUSES
    assert isinstance(data["current_occupancy"], int) and data["current_occupancy"] >= 0
    assert data["current_occupancy"] <= data["capacity"], "current_occupancy never exceeds capacity"
    assert isinstance(data["held_occupancy"], int) and data["held_occupancy"] >= 0
    assert isinstance(data["settlement_balance_cents"], int) and data["settlement_balance_cents"] >= 0


def assert_member(data: dict):
    _assert_quartet(data)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["membership_year_start"], str)
    assert isinstance(data["visits_used"], int) and data["visits_used"] >= 0
    assert isinstance(data["guest_visits_used"], int) and data["guest_visits_used"] >= 0
    assert data["standing"] in _MEMBER_STANDINGS
    assert isinstance(data["no_show_strikes"], int) and data["no_show_strikes"] >= 0
    assert isinstance(data["wallet_balance_cents"], int)


def assert_card(data: dict):
    _assert_quartet(data)
    assert isinstance(data["member_id"], str)
    assert data["card_status"] in _CARD_STATUSES
    assert data["fare_class"] in _FARE_CLASSES
    assert isinstance(data["active"], bool)
    assert isinstance(data["valid_until"], str)


def assert_visit(data: dict):
    _assert_quartet(data)
    assert isinstance(data["lounge_id"], str)
    assert data["entry_mode"] in _ENTRY_MODES
    assert isinstance(data["guest_count"], int) and data["guest_count"] >= 0
    assert isinstance(data["occupant_count"], int) and data["occupant_count"] >= 1
    assert data["occupant_count"] == data["guest_count"] + 1, "occupant_count == 1 + guest_count"
    assert isinstance(data["allotment_consumed"], bool)
    assert isinstance(data["guest_allotment_consumed"], int) and data["guest_allotment_consumed"] >= 0
    assert data["status"] in _VISIT_STATUSES
    assert isinstance(data["held_at"], str)
    assert isinstance(data["hold_expires_at"], str)
    assert isinstance(data["member_charge_cents"], int) and data["member_charge_cents"] >= 0
    assert isinstance(data["settlement_amount_cents"], int) and data["settlement_amount_cents"] >= 0


def assert_guest(data: dict):
    _assert_quartet(data)
    assert isinstance(data["visit_id"], str)
    assert isinstance(data["full_name"], str)
    assert data["funded_by"] in _GUEST_FUNDING
    assert isinstance(data["charge_cents"], int) and data["charge_cents"] >= 0


def assert_day_pass(data: dict):
    _assert_quartet(data)
    assert isinstance(data["lounge_id"], str)
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert data["status"] in _DAY_PASS_STATUSES
    assert isinstance(data["valid_until"], str)


def assert_shower_suite(data: dict):
    _assert_quartet(data)
    assert isinstance(data["lounge_id"], str)
    assert isinstance(data["label"], str)
    assert isinstance(data["turnover_minutes"], int) and data["turnover_minutes"] >= 0
    assert isinstance(data["out_of_service"], bool)


def assert_shower_reservation(data: dict):
    _assert_quartet(data)
    assert isinstance(data["shower_suite_id"], str)
    assert isinstance(data["visit_id"], str)
    assert isinstance(data["start_at"], str)
    assert isinstance(data["end_at"], str)
    assert data["status"] in _SHOWER_RESERVATION_STATUSES


def assert_settlement(data: dict):
    _assert_event_record(data)
    assert isinstance(data["lounge_id"], str)
    assert isinstance(data["visit_id"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["status"] in _SETTLEMENT_STATUSES


def assert_ledger_entry(data: dict):
    _assert_event_record(data)
    assert isinstance(data["member_id"], str)
    assert data["kind"] in _LEDGER_KINDS
    assert isinstance(data["amount_cents"], int)
    assert data["amount_cents"] != 0, "ledger amount is non-zero"
    assert data["status"] in _LEDGER_STATUSES
