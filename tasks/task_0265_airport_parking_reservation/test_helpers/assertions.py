"""Entity assertions and domain invariant checkers.

Per-entity assert_{entity}() validate the response shape against the PRD contract.
Invariant checkers express rules that must hold after any operation (PRD §2.5, §2.7).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_OCCUPANCY = {"BOOKED", "CHECKED_IN", "OUT_TEMP", "CHECKED_OUT", "NO_SHOW", "CANCELLED"}
_SETTLEMENT = {"UNSETTLED", "AUTHORIZED", "SETTLED", "REFUNDED"}
_STALL_CLASS = {"STANDARD", "OVERSIZED", "EV"}
_HOLD_STATUS = {"HELD", "OCCUPIED", "RELEASED"}
_TRIP_STATUS = {"SCHEDULED", "BOARDING", "DEPARTED", "CANCELLED"}
_TXN_KIND = {"AUTHORIZATION", "CAPTURE", "REFUND", "FEE_RETAIN"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an int"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["no_show_strikes"], int) and data["no_show_strikes"] >= 0
    assert data["status"] in {"ACTIVE", "SUSPENDED"}, f"unexpected status {data['status']!r}"


def assert_vehicle(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["plate"], str) and len(data["plate"]) > 0
    assert data["size_class"] in {"STANDARD", "OVERSIZED"}
    assert isinstance(data["is_ev"], bool)


def assert_lot(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert data["kind"] in {"SURFACE_LOT", "GARAGE", "VALET_GARAGE"}
    for cap in ("standard_capacity", "oversized_capacity", "ev_capacity"):
        assert isinstance(data[cap], int) and data[cap] >= 0
    for avail in ("available_standard_count", "available_oversized_count", "available_ev_count"):
        assert isinstance(data[avail], int) and data[avail] >= 0, \
            f"{avail} must be a non-negative int"
    assert isinstance(data["in_out_allowed"], bool)
    assert_lot_availability_invariants(data)


def assert_lot_availability_invariants(data: dict):
    """PRD §2.5: each available counter is its capacity minus active holds, never
    below zero and never above capacity."""
    pairs = [
        ("available_standard_count", "standard_capacity"),
        ("available_oversized_count", "oversized_capacity"),
        ("available_ev_count", "ev_capacity"),
    ]
    for avail, cap in pairs:
        assert 0 <= data[avail] <= data[cap], \
            f"{avail}={data[avail]} must be within [0, {cap}={data[cap]}]"


def assert_rate_plan(data: dict):
    _assert_common(data)
    assert data["rate_mode"] in {"DAILY", "HOURLY", "VALET"}
    assert isinstance(data["active"], bool)
    assert data["oversized_multiplier_bps"] >= 10000
    for f in ("hourly_cents", "daily_cap_cents", "valet_surcharge_cents",
              "ev_surcharge_cents_per_day"):
        assert isinstance(data[f], int) and data[f] >= 0


def assert_cancellation_policy(data: dict):
    _assert_common(data)
    assert data["free_cancel_hours"] >= 0
    assert 0 <= data["late_cancel_fee_bps"] <= 10000
    assert 0 <= data["prepay_discount_bps"] <= 10000


def assert_reservation(data: dict):
    _assert_common(data)
    assert data["occupancy_status"] in _OCCUPANCY
    assert data["settlement_status"] in _SETTLEMENT
    assert data["stall_class"] in _STALL_CLASS
    assert isinstance(data["prepaid"], bool)
    assert isinstance(data["provisional_quote_cents"], int)
    assert isinstance(data["overstay_cents"], int) and data["overstay_cents"] >= 0
    # final_charge_cents is null until check-out
    if data.get("final_charge_cents") is not None:
        assert isinstance(data["final_charge_cents"], int)


def assert_stall_hold(data: dict):
    _assert_common(data)
    assert data["stall_class"] in _STALL_CLASS
    assert data["status"] in _HOLD_STATUS


def assert_shuttle_trip(data: dict):
    _assert_common(data)
    assert data["status"] in _TRIP_STATUS
    assert isinstance(data["seat_capacity"], int) and data["seat_capacity"] >= 1
    assert isinstance(data["seats_taken"], int) and 0 <= data["seats_taken"] <= data["seat_capacity"]


def assert_payment_txn(data: dict):
    """PRD §2.4: a payment transaction is immutable — only id and created_at; no
    updated_at and no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "PaymentTxn must NOT carry updated_at"
    assert "version" not in data, "PaymentTxn must NOT carry version"
    assert data["kind"] in _TXN_KIND
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0


def find_txn(txns: list, kind: str, amount_cents: int = None):
    """Return the first PaymentTxn of the given kind (and optional amount), or None."""
    for t in txns:
        if t["kind"] != kind:
            continue
        if amount_cents is not None and t["amount_cents"] != amount_cents:
            continue
        return t
    return None
