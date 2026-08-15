"""Entity assertions and domain invariant checkers (PRD §2.5, §2.8)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_customer_account(data: dict):
    _assert_common(data)
    assert data["account_type"] in ("FLEET", "RETAIL")
    assert data["fleet_tier"] in ("STANDARD", "GOLD", "PLATINUM")
    assert data["status"] in ("ACTIVE", "CREDIT_HOLD", "CLOSED")
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["open_ar_cents"], int)
    assert isinstance(data["account_name"], str) and data["account_name"]


def assert_factory_build_slot(data: dict):
    _assert_common(data)
    assert data["vocation_group"] in ("STANDARD", "SEVERE")
    assert data["status"] in ("OPEN", "LOCKED", "CLOSED")
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert data["slots_available"] == data["capacity"] - data["held_count"] - data["committed_count"]
    assert data["slots_available"] >= 0


def assert_factory_order(data: dict):
    _assert_common(data)
    assert data["chassis_model"] in ("CASCADIA_126", "M2_106", "SD_114")
    assert data["engine_option"] in ("DD13", "DD15", "CUMMINS_X15")
    assert data["axle_config"] in ("A4X2", "A6X4")
    assert data["status"] in (
        "SLOT_HELD", "COMMITTED", "IN_PRODUCTION", "SHIPPED",
        "DELIVERED", "CANCELLED", "EXPIRED",
    )
    assert isinstance(data["provisional_total_cents"], int)


def assert_unit(data: dict):
    _assert_common(data)
    assert data["unit_kind"] in ("NEW", "USED")
    assert data["status"] in ("IN_STOCK", "RECONDITIONING", "READY", "SOLD", "WHOLESALED")
    assert data["aging_bucket"] in ("B0_90", "B91_180", "B181_270", "B271_365", "OVER_365")
    assert isinstance(data["invoice_cost_cents"], int)
    assert isinstance(data["floorplan_balance_cents"], int)
    assert isinstance(data["days_in_stock"], int)
    assert isinstance(data["floorplan_active"], bool)


def assert_floor_plan_entry(data: dict):
    # Append-only ledger line: id + created_at, and neither updated_at nor version.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "FloorPlanEntry must not carry updated_at"
    assert "version" not in data, "FloorPlanEntry must not carry version"
    assert data["entry_type"] in ("ADVANCE", "INTEREST_ACCRUAL", "CURTAILMENT", "PAYOFF", "ADJUSTMENT")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["resulting_balance_cents"], int)


def assert_trade_appraisal(data: dict):
    _assert_common(data)
    assert data["condition_grade"] in ("A", "B", "C")
    assert data["status"] in (
        "DRAFT", "OFFERED", "NEGOTIATING", "ACCEPTED", "DECLINED", "EXPIRED", "CONSUMED",
    )
    assert isinstance(data["book_estimate_cents"], int)
    assert isinstance(data["offer_round"], int)


def assert_service_bay(data: dict):
    _assert_common(data)
    assert data["bay_type"] in ("STANDARD", "HEAVY_ALIGNMENT")
    assert data["status"] in ("ACTIVE", "OUT_OF_SERVICE")
    assert data["close_hour"] > data["open_hour"]


def assert_mobile_service_unit(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "OUT_OF_SERVICE")
    assert isinstance(data["default_travel_minutes"], int)


def assert_repair_order(data: dict):
    _assert_common(data)
    assert data["auth_status"] in ("DRAFT", "PENDING_APPROVAL", "APPROVED", "DECLINED", "CANCELLED")
    assert data["work_status"] in (
        "OPEN", "SCHEDULED", "IN_PROGRESS", "COMPLETED", "INVOICED", "PAID", "CANCELLED",
    )
    for f in ("labor_sum_cents", "parts_sum_cents", "discount_cents",
              "shop_supplies_fee_cents", "warranty_covered_cents",
              "customer_due_cents", "downtime_penalty_cents"):
        assert isinstance(data[f], int), f"{f} must be integer cents"
    assert data["customer_due_cents"] >= 0, "customer_due_cents is floored at zero"


def assert_repair_order_line(data: dict):
    _assert_common(data)
    assert data["line_type"] in ("LABOR", "PART")
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["line_total_cents"], int)


def assert_service_booking(data: dict):
    _assert_common(data)
    assert data["status"] in ("BOOKED", "CHECKED_IN", "COMPLETED", "CANCELLED", "NO_SHOW")
    # Exactly one resource referenced
    assert (data.get("service_bay_id") is None) != (data.get("mobile_service_unit_id") is None)


def assert_warranty_claim(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "APPROVED", "SHORT_PAID", "DENIED",
        "APPEALED", "PAID", "CLOSED", "WRITTEN_OFF",
    )
    assert isinstance(data["claimed_labor_cents"], int)
    assert isinstance(data["claimed_parts_cents"], int)
    assert isinstance(data["paid_cents"], int)
    assert isinstance(data["appeal_count"], int)


def assert_part(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "DISCONTINUED")
    assert data["list_price_cents"] > 0
    assert data["cost_cents"] >= 0
    assert isinstance(data["on_hand"], int)


def assert_parts_sale(data: dict):
    _assert_common(data)
    assert data["status"] in ("INVOICED", "PARTIALLY_RETURNED", "FULLY_RETURNED")
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["core_total_cents"], int)
    assert data["total_cents"] == data["subtotal_cents"] + data["core_total_cents"]


def assert_parts_sale_line(data: dict):
    _assert_common(data)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_net_price_cents"], int)
    assert data["line_total_cents"] == data["unit_net_price_cents"] * data["quantity"]
    assert isinstance(data["returned_quantity"], int)
    assert isinstance(data["return_credit_cents"], int)


def assert_ledger_invariant(unit: dict, entries: list):
    """PRD §2.8: floorplan_balance_cents equals the signed sum of entry amounts."""
    assert sum(e["amount_cents"] for e in entries) == unit["floorplan_balance_cents"], (
        "ledger invariant violated: balance must equal the signed sum of entries"
    )
    if entries:
        assert entries[-1]["resulting_balance_cents"] == unit["floorplan_balance_cents"]
