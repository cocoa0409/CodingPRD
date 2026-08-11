"""Entity assertions and domain invariant checkers (PRD §2.4, §2.6, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    BookingStatus,
    ColdChainStatus,
    CreditMemoStatus,
    CustomerStatus,
    EthyleneClass,
    HoldReason,
    InspectionResult,
    InspectionStatus,
    InvoiceStatus,
    LotStatus,
    OrderStatus,
    ShipperStatus,
    ShrinkReason,
    ShrinkStatus,
    TicketType,
)


def _assert_common(data: dict, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), (
            f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
        )
        assert isinstance(data.get("version"), int) and data["version"] >= 1, (
            f"version must be an integer >= 1, got {data.get('version')!r}"
        )
    else:
        # Append-only ledger rows must not carry updated_at / version (PRD §2.4).
        assert "updated_at" not in data, "append-only row must not expose updated_at"
        assert "version" not in data, "append-only row must not expose version"


def _enum_values(enum_cls):
    return [member.value for member in enum_cls]


def assert_shipper(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["paca_license"], str) and data["paca_license"]
    assert data["status"] in _enum_values(ShipperStatus)
    assert isinstance(data["trust_exposure_cents"], int)


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["terms_days"], int)
    assert isinstance(data["paca_special_agreement"], bool)
    assert data["status"] in _enum_values(CustomerStatus)
    assert isinstance(data["credit_exposure_cents"], int)


def assert_commodity(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["ethylene_class"] in _enum_values(EthyleneClass)
    assert data["temp_min_f"] < data["temp_max_f"], "cold-chain band must be ordered"
    assert isinstance(data["max_violation_minutes"], int)


def assert_daily_price(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("commodity_id", ""))
    assert isinstance(data["market_date"], str)
    assert isinstance(data["low_price"], (int, float))
    assert isinstance(data["high_price"], (int, float))
    assert isinstance(data["mid_price"], (int, float))


def assert_purchase_lot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("shipper_id", ""))
    assert is_valid_uuid(data.get("commodity_id", ""))
    assert data["status"] in _enum_values(LotStatus)
    assert data["cold_chain_status"] in _enum_values(ColdChainStatus)
    for field in ("quantity_units", "provisional_cost_cents", "adjusted_cost_cents",
                  "payable_cents", "dumped_units", "reserved_units", "sold_units",
                  "available_units", "violation_minutes"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_inspection(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("purchase_lot_id", ""))
    assert data["result"] in _enum_values(InspectionResult)
    assert data["status"] in _enum_values(InspectionStatus)


def assert_temperature_reading(data: dict):
    _assert_common(data, with_version=False)
    assert is_valid_uuid(data.get("purchase_lot_id", ""))
    assert isinstance(data["temp_f"], (int, float))
    assert isinstance(data["duration_minutes"], int)
    assert isinstance(data["out_of_range"], bool)


def assert_ripening_room(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["capacity_pallets"], int)
    assert isinstance(data["ethylene_capable"], bool)


def assert_ripening_booking(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("room_id", ""))
    assert is_valid_uuid(data.get("purchase_lot_id", ""))
    assert isinstance(data["pallet_count"], int)
    assert isinstance(data["ethylene_enabled"], bool)
    assert data["status"] in _enum_values(BookingStatus)


def assert_shrink_record(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("purchase_lot_id", ""))
    assert isinstance(data["quantity"], int)
    assert data["reason"] in _enum_values(ShrinkReason)
    assert data["status"] in _enum_values(ShrinkStatus)


def assert_credit_memo(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("purchase_lot_id", ""))
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in _enum_values(CreditMemoStatus)


def assert_sales_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data["lines"], list) and len(data["lines"]) >= 1
    assert isinstance(data["subtotal_cents"], int)
    assert data["status"] in _enum_values(OrderStatus)
    if data["status"] == OrderStatus.ON_HOLD.value:
        assert data["hold_reason"] in _enum_values(HoldReason)


def assert_invoice(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("sales_order_id", ""))
    assert is_valid_uuid(data.get("customer_id", ""))
    for field in ("subtotal_cents", "deposit_cents", "total_cents",
                  "discount_taken_cents", "paid_cents", "balance_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert data["status"] in _enum_values(InvoiceStatus)


def assert_payment(data: dict):
    _assert_common(data, with_version=False)
    assert is_valid_uuid(data.get("invoice_id", ""))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


def assert_labor_ticket(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("purchase_lot_id", ""))
    assert data["ticket_type"] in _enum_values(TicketType)
    assert isinstance(data["charge_cents"], int)


# --- Domain invariants -------------------------------------------------------

def assert_lot_unit_conservation(lot: dict):
    """quantity_units == dumped + reserved + sold + available (PRD §3.2 field relations)."""
    total = (lot["dumped_units"] + lot["reserved_units"]
             + lot["sold_units"] + lot["available_units"])
    assert total == lot["quantity_units"], (
        f"unit conservation broken: {lot['dumped_units']} dumped + "
        f"{lot['reserved_units']} reserved + {lot['sold_units']} sold + "
        f"{lot['available_units']} available != {lot['quantity_units']} purchased"
    )


def assert_payable_invariant(lot: dict, issued_memo_total_cents: int):
    """payable + sum(ISSUED memos) == adjusted_cost for non-REJECTED lots (PRD §3.8)."""
    if lot["status"] == LotStatus.REJECTED.value:
        assert lot["payable_cents"] == 0, "REJECTED lot payable must be pinned at 0"
    else:
        assert lot["payable_cents"] + issued_memo_total_cents == lot["adjusted_cost_cents"], (
            f"payable {lot['payable_cents']} + issued memos {issued_memo_total_cents} "
            f"!= adjusted_cost {lot['adjusted_cost_cents']}"
        )
