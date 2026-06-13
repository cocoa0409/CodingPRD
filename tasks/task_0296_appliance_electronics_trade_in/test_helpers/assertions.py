"""Entity assertions and domain invariant checkers for the Trade-In API.

Each assert_{entity} validates the structural contract (id/created_at, plus the
PRD-declared fields and enum domains). Money invariants use integer cents.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

_GRADES = ["FLAWLESS", "GOOD", "FAIR", "POOR"]
_CATEGORIES = ["SMARTPHONE", "LAPTOP", "TABLET", "REFRIGERATOR", "WASHER", "TV", "WEARABLE"]
_TRADE_IN_STATES = [
    "DRAFT", "QUOTED", "KIT_SENT", "RECEIVED", "INSPECTED", "REQUOTED",
    "ACCEPTED", "PAID", "REJECTED", "RECYCLED", "CANCELLED", "EXPIRED",
]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_catalog(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["currency"], str)
    assert isinstance(data["price_lock_hours"], int)
    assert isinstance(data["requote_tolerance_pct"], (int, float))
    assert isinstance(data["data_wipe_required_categories"], list)
    assert isinstance(data["recycle_floor_value_cents"], int)


def assert_device_model(data: dict):
    _assert_common(data)
    assert isinstance(data["manufacturer"], str)
    assert isinstance(data["model_code"], str)
    assert data["category"] in _CATEGORIES
    assert isinstance(data["base_value_cents"], int)
    assert isinstance(data["condition_multipliers"], dict)
    assert isinstance(data["defect_deductions"], dict)
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_promotion_campaign(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str)
    assert data["status"] in ("ACTIVE", "EXPIRED")
    assert isinstance(data["bonus_cap_cents"], int)


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["wallet_balance_cents"], int)
    assert isinstance(data["lifetime_payout_cents"], int)
    assert data["wallet_balance_cents"] >= 0, "wallet_balance_cents must never be negative"


def assert_trade_in(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["device_model_id"], str)
    assert data["declared_grade"] in _GRADES
    assert isinstance(data["declared_defects"], list)
    assert isinstance(data["declared_powers_on"], bool)
    assert data["status"] in _TRADE_IN_STATES


def assert_quote(data: dict):
    _assert_common(data)
    assert data["kind"] in ("INITIAL", "REQUOTE")
    assert isinstance(data["graded_subtotal_cents"], int)
    assert isinstance(data["promo_bonus_cents"], int)
    assert isinstance(data["amount_cents"], int)
    assert data["amount_cents"] >= 0
    assert data["status"] in ("DRAFT", "LOCKED", "SUPERSEDED", "EXPIRED", "HONORED")


def assert_shipping_kit(data: dict):
    _assert_common(data)
    assert data["status"] in ("DISPATCHED", "IN_TRANSIT", "DELIVERED_TO_HUB")


def assert_inspection(data: dict):
    _assert_common(data)
    assert data["verified_grade"] in _GRADES
    assert isinstance(data["verified_defects"], list)
    assert isinstance(data["verified_powers_on"], bool)
    assert isinstance(data["inspected_value_cents"], int)
    assert data["outcome"] in ("MATCH", "REQUOTE", "RECYCLE")


def assert_inspection_slot(data: dict):
    _assert_common(data)
    assert data["lane_category"] in _CATEGORIES
    assert data["status"] in ("BOOKED", "RELEASED")


def assert_payout(data: dict):
    _assert_common(data)
    assert data["method"] in ("STORE_CREDIT", "ACH", "CHECK")
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("PAID", "REVERSED")


def assert_data_wipe_certificate(data: dict):
    _assert_common(data)
    assert data["method"] in ("CRYPTO_ERASE", "NIST_PURGE", "PHYSICAL_DESTROY")
    assert data["result"] in ("PASS", "FAIL")
    assert isinstance(data["certificate_serial"], str) and len(data["certificate_serial"]) > 0


def assert_disposition_record(data: dict):
    _assert_common(data)
    assert data["disposition"] in ("RETURN_TO_CUSTOMER", "RECYCLE", "REFURBISH_INVENTORY")


# ─── Helpers for reading child collections back ───────

def find_quote(quotes: list, *, kind=None, status=None, amount_cents=None):
    """Return the single quote matching the given filters, or raise if not exactly one."""
    matches = [
        q for q in quotes
        if (kind is None or q["kind"] == kind)
        and (status is None or q["status"] == status)
        and (amount_cents is None or q["amount_cents"] == amount_cents)
    ]
    assert len(matches) == 1, (
        f"Expected exactly one quote matching kind={kind} status={status} "
        f"amount_cents={amount_cents}; got {len(matches)} from {[(q['kind'], q['status'], q['amount_cents']) for q in quotes]}"
    )
    return matches[0]
