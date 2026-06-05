"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates the shape and field types of a returned entity.
Append-only entities (DepositLedgerEntry, WeatherEvent) carry only id + created_at;
their assertions deliberately do NOT demand updated_at or version.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_CATEGORIES = ["TENT", "TABLE", "CHAIR", "LINEN", "BOUNCE_HOUSE"]
_ZONES = ["LOCAL", "EXTENDED", "REMOTE"]
_BOOKING = ["DRAFT", "CONFIRMED", "FULFILLED", "RETURNED", "CANCELLED"]
_SETTLEMENT = ["UNSETTLED", "DEPOSIT_HELD", "DEPOSIT_RELEASED", "DEPOSIT_FORFEITED"]
_LINE_STATUS = ["PENDING", "RESERVED", "RELEASED"]
_RUN_STATUS = ["SCHEDULED", "ATTEMPTED", "COMPLETED", "CANCELLED"]
_CERT_STATUS = ["SUBMITTED", "APPROVED", "REJECTED", "REVOKED"]
_COI_STATUS = ["NONE", "PENDING", "VALID", "EXPIRED"]
_LEDGER_KINDS = ["HOLD", "RELEASE", "FORFEIT"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def _assert_appendonly_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "append-only entity must NOT carry version"
    assert "updated_at" not in data, "append-only entity must NOT carry updated_at"


def assert_catalog_item(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert isinstance(data["name"], str)
    assert data["category"] in _CATEGORIES, f"bad category {data['category']!r}"
    assert isinstance(data["total_units"], int) and data["total_units"] >= 1
    assert isinstance(data["daily_rate_cents"], int) and data["daily_rate_cents"] >= 0
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str)
    assert isinstance(data["account_credit_cents"], int)
    assert data["account_credit_cents"] >= 0, "account_credit_cents is never negative"


def assert_venue(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_id"], str)
    assert data["delivery_zone"] in _ZONES
    assert data["coi_status"] in _COI_STATUS


def assert_certificate(data: dict):
    _assert_common(data)
    assert isinstance(data["venue_id"], str)
    assert data["status"] in _CERT_STATUS
    assert isinstance(data["coverage_amount_cents"], int) and data["coverage_amount_cents"] >= 0


def assert_rental_order(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_id"], str)
    assert data["fulfillment"] in ["WILL_CALL", "DELIVERY"]
    assert data["booking_status"] in _BOOKING
    assert data["settlement_status"] in _SETTLEMENT
    assert isinstance(data["rental_days"], int) and data["rental_days"] >= 1
    for fld in (
        "rental_subtotal_cents",
        "delivery_fee_cents",
        "cleaning_fee_total_cents",
        "deposit_total_cents",
        "grand_total_cents",
    ):
        assert isinstance(data[fld], int) and data[fld] >= 0, f"{fld} must be non-negative int"
    assert isinstance(data["weather_cancellable"], bool)


def assert_order_line(data: dict):
    _assert_common(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["item_id"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["status"] in _LINE_STATUS


def assert_delivery_run(data: dict):
    _assert_common(data)
    assert isinstance(data["order_id"], str)
    assert data["leg"] in ["DROP_OFF", "PICK_UP"]
    assert data["status"] in _RUN_STATUS
    assert isinstance(data["attempt_count"], int) and data["attempt_count"] >= 0


def assert_crew(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["turnaround_minutes"], int) and data["turnaround_minutes"] >= 0


def assert_deposit_ledger_entry(data: dict):
    _assert_appendonly_common(data)
    assert isinstance(data["order_id"], str)
    assert data["kind"] in _LEDGER_KINDS
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0, (
        "ledger amount_cents is a non-negative magnitude"
    )


def assert_weather_event(data: dict):
    _assert_appendonly_common(data)
    assert data["delivery_zone"] in _ZONES
    assert data["severity"] in ["ADVISORY", "WARNING"]


# ─── Domain invariants ────────────────────────────────

def assert_grand_total_excludes_deposit(order: dict):
    """grand_total = rental_subtotal + delivery_fee + cleaning_fee_total;
    the deposit is held separately and is NOT part of grand_total (PRD §3.3)."""
    expected = (
        order["rental_subtotal_cents"]
        + order["delivery_fee_cents"]
        + order["cleaning_fee_total_cents"]
    )
    assert order["grand_total_cents"] == expected, (
        f"grand_total {order['grand_total_cents']} != "
        f"subtotal+delivery+cleaning {expected}"
    )


def compute_held_balance(entries: list) -> int:
    """Replay the deposit ledger in created_at ASC order: HOLD adds, RELEASE
    and FORFEIT subtract; balance is never negative (PRD §3.7)."""
    ordered = sorted(entries, key=lambda e: e["created_at"])
    held = 0
    for e in ordered:
        if e["kind"] == "HOLD":
            held += e["amount_cents"]
        else:  # RELEASE or FORFEIT
            held -= e["amount_cents"]
    return held
