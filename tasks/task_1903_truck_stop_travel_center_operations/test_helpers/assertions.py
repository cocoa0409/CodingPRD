"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be an integer starting at 1"


def _assert_ledger(data: dict):
    """Ledger-style records carry only id + created_at bookkeeping."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 timestamp"


def assert_site(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["parking_total_spaces"], int)
    assert isinstance(data["parking_paid_capacity"], int)
    assert data["parking_paid_capacity"] <= data["parking_total_spaces"]
    assert isinstance(data["shower_units_count"], int)
    assert isinstance(data["laundry_machines_count"], int)
    assert isinstance(data["water_usage_gallons"], (int, float))


def assert_fleet_account(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["current_balance_cents"], int)
    assert data["pricing_tier"] in ("T1", "T2", "T3")
    assert isinstance(data["rolling_30d_gallons"], (int, float))
    assert data["status"] in ("ACTIVE", "CREDIT_HOLD", "CLOSED")


def assert_contract(data: dict):
    _assert_common(data)
    assert data["pricing_tier"] in ("T1", "T2", "T3")
    assert data["status"] in ("PENDING", "ACTIVE", "SUSPENDED", "EXPIRED",
                              "TERMINATED")
    assert isinstance(data["volume_delivered_gallons"], (int, float))
    assert isinstance(data["applicable_fuel_types"], list)


def assert_loyalty_member(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["stack_cap_points"], int)
    assert isinstance(data["points_balance"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CLOSED")


def assert_registered_vehicle(data: dict):
    _assert_common(data)
    assert isinstance(data["plate"], str) and data["plate"]
    assert data["vehicle_type"] in ("TRACTOR", "BOX_TRUCK", "RV", "AUTO")


def assert_discount_network(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "RETIRED")
    assert isinstance(data["program_cap"], int) and data["program_cap"] >= 1


def assert_enrollment(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "ACTIVE", "SUSPENDED", "RETIRED",
                              "CANCELLED")


def assert_fuel_price(data: dict):
    _assert_common(data)
    assert data["fuel_type"] in ("DIESEL", "GAS_REGULAR", "GAS_PREMIUM", "DEF")
    assert isinstance(data["retail_cents_per_gallon"], int)
    assert data["status"] in ("ACTIVE", "SUPERSEDED")


def assert_pump(data: dict):
    _assert_common(data)
    assert isinstance(data["pump_number"], int)
    assert isinstance(data["fuel_types"], list)
    assert data["status"] in ("IDLE", "IN_USE", "OUT_OF_SERVICE")


def assert_fuel_sale(data: dict):
    _assert_common(data)
    assert data["pricing_mode"] in ("RETAIL", "CONTRACT")
    assert data["fuel_type"] in ("DIESEL", "GAS_REGULAR", "GAS_PREMIUM", "DEF")
    assert data["tender_type"] in ("CASH", "CARD", "FLEET_BILLING")
    assert data["status"] in ("AUTHORIZED", "FUELING", "PENDING_FINALIZE",
                              "COMPLETED", "VOIDED")
    assert data["payment_status"] in ("UNPAID", "PAID", "BILLED", "REFUNDED")
    assert isinstance(data["max_gallons"], (int, float))
    assert isinstance(data["requested_redeem_points"], int)
    assert isinstance(data["authorized_quote_cents_per_gallon"], int)
    assert isinstance(data["provisional_fuel_total_cents"], int)
    assert data["tax_cents"] == 0


def assert_parking_space(data: dict):
    _assert_common(data)
    assert data["space_type"] in ("STANDARD", "OVERSIZED")
    assert isinstance(data["is_reservable"], bool)
    assert data["status"] in ("ACTIVE", "OUT_OF_SERVICE")


def assert_parking_reservation(data: dict):
    _assert_common(data)
    assert data["space_type"] in ("STANDARD", "OVERSIZED")
    assert data["status"] in ("CONFIRMED", "ACTIVE", "COMPLETED", "CANCELLED",
                              "NO_SHOW")
    assert data["payment_status"] in ("UNPAID", "PAID", "REFUNDED")
    assert isinstance(data["paid_minutes"], int)
    assert isinstance(data["billed_hours"], int)
    assert isinstance(data["amount_cents"], int)


def assert_service_ticket(data: dict):
    _assert_common(data)
    assert data["service_type"] in ("SHOWER", "LAUNDRY")
    assert data["status"] in ("QUEUED", "CALLED", "ACTIVE", "COMPLETED",
                              "CANCELLED", "NO_SHOW")
    assert data["payment_status"] in ("UNPAID", "PAID", "REFUNDED")
    assert isinstance(data["queue_position"], int) and data["queue_position"] >= 1
    assert isinstance(data["base_price_cents"], int)
    assert isinstance(data["total_price_cents"], int)


def assert_scale_ticket(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "PAID", "CLOSED", "CANCELLED", "REFUNDED")
    assert isinstance(data["reweigh_count"], int)
    assert isinstance(data["total_paid_cents"], int)
    assert isinstance(data["refund_total_cents"], int)


def assert_weigh_event(data: dict):
    _assert_ledger(data)
    assert data["weigh_kind"] in ("GROSS", "TARE", "REWEIGH")
    assert isinstance(data["weight_lbs"], int)
    assert isinstance(data["sequence"], int) and data["sequence"] >= 1


def assert_stock_item(data: dict):
    _assert_common(data)
    assert data["category"] in ("RESTAURANT", "RETAIL", "SHOP_PART",
                                "PACKAGED_OIL")
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["on_hand_quantity"], int)
    assert data["on_hand_quantity"] >= 0, "stock may never go negative"
    assert isinstance(data["reorder_point"], int)
    assert isinstance(data["is_low_stock"], bool)
    assert data["is_low_stock"] == (data["on_hand_quantity"] <= data["reorder_point"]), \
        "is_low_stock must equal (on_hand_quantity <= reorder_point)"


def assert_vendor(data: dict):
    _assert_common(data)
    assert data["category"] in ("FUEL", "DEF_OIL", "FOOD", "GENERAL")


def assert_vendor_price(data: dict):
    _assert_common(data)
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["pack_size"], int)


def assert_purchase_order(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "APPROVED", "PARTIALLY_RECEIVED",
                              "RECEIVED", "CANCELLED")
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["lines"], list)


def assert_technician(data: dict):
    _assert_common(data)
    assert isinstance(data["hourly_rate_cents"], int)
    assert data["status"] in ("AVAILABLE", "OFF_DUTY")


def assert_bay(data: dict):
    _assert_common(data)
    assert isinstance(data["bay_number"], int)
    assert data["status"] in ("IDLE", "OCCUPIED", "MAINTENANCE")
    assert isinstance(data["maintenance_blocks"], list)


def assert_work_order(data: dict):
    _assert_common(data)
    assert data["status"] in ("CREATED", "ESTIMATED", "APPROVED", "SCHEDULED",
                              "IN_SHOP", "IN_PROGRESS", "WAITING_VENDOR",
                              "READY_FOR_PICKUP", "CLOSED", "CANCELLED")
    assert data["payment_status"] in ("UNPAID", "PAID", "BILLED", "REFUNDED")
    assert isinstance(data["is_road_service"], bool)


def assert_work_order_part(data: dict):
    _assert_common(data)
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert isinstance(data["returned_quantity"], int)
    assert isinstance(data["unit_price_cents"], int)
    assert data["status"] in ("ISSUED", "RETURNED")


def assert_register(data: dict):
    _assert_common(data)
    assert isinstance(data["float_cents"], int)
    assert data["posture"] in ("OK", "NEEDS_DROP", "LOW_FLOAT")


def assert_shift(data: dict):
    _assert_common(data)
    assert data["shift_label"] in ("DAY", "NIGHT", "GRAVEYARD")
    assert data["status"] in ("OPEN", "CLOSED", "RECONCILED", "LOCKED")
    assert isinstance(data["opening_float_cents"], int)
    assert isinstance(data["expected_cash_cents"], int)


def assert_cash_drop(data: dict):
    _assert_ledger(data)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] == "POSTED"


def assert_reconciliation(data: dict):
    _assert_ledger(data)
    assert isinstance(data["expected_cash_cents"], int)
    assert isinstance(data["counted_cash_cents"], int)
    assert isinstance(data["variance_cents"], int)
    assert data["variance_cents"] == data["counted_cash_cents"] - data["expected_cash_cents"], \
        "variance must be counted minus expected"
    assert data["resolution"] in ("BALANCED", "OVERAGE", "SHORTAGE")
    assert isinstance(data["deposit_total_cents"], int)
    assert data["deposit_total_cents"] >= 0


def assert_safe_deposit(data: dict):
    _assert_ledger(data)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] == "RECORDED"


def assert_store_sale(data: dict):
    _assert_common(data)
    assert data["tender_type"] in ("CASH", "CARD")
    assert data["status"] in ("COMPLETED", "REFUNDED")
    assert data["payment_status"] in ("PAID", "REFUNDED")
    assert isinstance(data["subtotal_cents"], int)
    assert data["total_cents"] == data["subtotal_cents"], \
        "store total equals subtotal (no store tax)"


def assert_bulk_tank(data: dict):
    _assert_common(data)
    assert data["product_type"] in ("DIESEL", "DEF", "OIL")
    assert isinstance(data["current_gallons"], (int, float))
    assert isinstance(data["is_low_stock"], bool)
    assert data["is_low_stock"] == (
        data["current_gallons"] <= data["reorder_threshold_gallons"]), \
        "tank is_low_stock must equal (current_gallons <= reorder_threshold_gallons)"


def assert_bulk_delivery(data: dict):
    _assert_ledger(data)
    assert isinstance(data["gallons_delivered"], (int, float))
    assert data["status"] == "DELIVERED"


def assert_points_lot(data: dict):
    _assert_ledger(data)
    assert isinstance(data["points"], int)
    assert isinstance(data["remaining_points"], int)
    assert data["source_type"] in ("FUEL_SALE", "STORE_SALE", "SERVICE",
                                   "PARKING", "ADJUSTMENT")


def assert_shift_cash_identity(shift: dict, drops_cents: int, receipts_cents: int,
                               payouts_cents: int):
    """Drawer identity: expected + posted drops - opening float equals
    attributed receipts minus approved payouts."""
    left = shift["expected_cash_cents"] + drops_cents - shift["opening_float_cents"]
    right = receipts_cents - payouts_cents
    assert left == right, (
        f"Drawer cash identity broken: {left} != {right} "
        f"(expected {shift['expected_cash_cents']}, drops {drops_cents}, "
        f"float {shift['opening_float_cents']}, receipts {receipts_cents}, "
        f"payouts {payouts_cents})"
    )
