"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(str(data.get("id", ""))), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(str(data.get("created_at", ""))), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(str(data.get("updated_at", ""))), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), f"{entity}.version must be an int"


def assert_customer(data: dict):
    _assert_common_fields(data, "Customer")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0
    assert data["discount_tier"] in ("STANDARD", "SILVER", "GOLD", "PLATINUM")
    assert data["overrun_policy"] in (
        "EXACT_ONLY", "ACCEPT_AND_BILL_10", "ACCEPT_ALL_AND_BILL"
    )
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["trailing_billed_cents"], int)


def assert_release(data: dict):
    _assert_common_fields(data, "Release")
    assert is_valid_uuid(str(data["customer_id"]))
    assert isinstance(data["catalog_number"], str) and data["catalog_number"]
    assert data["format"] in ("LP", "EP", "SINGLE_7")
    assert data["weight_gram"] in (140, 180)
    assert isinstance(data["release_date"], str)
    assert data["status"] in ("SETUP", "IN_PRODUCTION", "FULFILLED")
    assert data["risk_level"] in ("ON_TRACK", "AT_RISK", "LATE")


def assert_press_order(data: dict):
    _assert_common_fields(data, "PressOrder")
    assert is_valid_uuid(str(data["release_id"]))
    assert isinstance(data["quantity_ordered"], int) and data["quantity_ordered"] >= 100
    assert data["sides"] in (1, 2)
    assert data["plating_route"] in ("TWO_STEP", "THREE_STEP")
    assert isinstance(data["variants"], list) and len(data["variants"]) >= 1
    for v in data["variants"]:
        assert v["color_config"] in (
            "BLACK", "SOLID_COLOR", "SPLATTER", "MARBLED", "PICTURE_DISC"
        )
        assert isinstance(v["quantity"], int)
    assert data["production_status"] in (
        "DRAFT", "QUOTED", "CONFIRMED", "TOOLING", "AWAITING_TP_APPROVAL",
        "QUEUED", "SCHEDULED", "PRESSING", "QC_REVIEW", "COMPLETED", "CANCELLED",
    )
    assert data["billing_status"] in (
        "UNBILLED", "INVOICED", "PARTIALLY_PAID", "PAID", "CREDIT_CLOSED"
    )
    assert isinstance(data["intake_seq"], int)
    for f in ("quote_pressing_cents", "quote_surcharge_cents", "quote_tooling_cents",
              "quote_setup_cents", "quote_subtotal_cents", "quote_discount_cents",
              "quote_total_cents", "tp_round", "repress_round",
              "pressed_units_total", "rejected_units_total", "accepted_units",
              "cancel_fee_cents"):
        assert isinstance(data[f], int), f"PressOrder.{f} must be an int"
    assert data["repress_fault"] in ("NONE", "PLANT", "CUSTOMER")


def assert_tooling_job(data: dict):
    _assert_common_fields(data, "ToolingJob")
    assert is_valid_uuid(str(data["press_order_id"]))
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert data["status"] in (
        "QUEUED", "CUTTING", "AWAITING_BATH", "PLATING", "STAMPER_READY",
        "FAILED", "SUPERSEDED", "CANCELLED",
    )
    assert isinstance(data["attempt_count"], int) and data["attempt_count"] >= 0


def assert_test_pressing(data: dict):
    _assert_common_fields(data, "TestPressing")
    assert is_valid_uuid(str(data["press_order_id"]))
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert isinstance(data["quantity"], int) and 1 <= data["quantity"] <= 20
    assert data["status"] in (
        "PRODUCED", "UNDER_REVIEW", "APPROVED", "REVISION_REQUESTED", "SUPERSEDED"
    )


def assert_print_job(data: dict):
    _assert_common_fields(data, "PrintJob")
    assert is_valid_uuid(str(data["press_order_id"]))
    assert data["component"] in ("JACKET", "INNER_SLEEVE", "INSERT", "LABEL")
    assert isinstance(data["quantity"], int)
    assert isinstance(data["printer_name"], str)
    assert isinstance(data["due_date"], str)
    assert isinstance(data["proof_round"], int) and data["proof_round"] >= 0
    assert data["status"] in (
        "CREATED", "AT_PRINTER", "PROOF_REVIEW", "PRINTING", "DELIVERED", "CANCELLED"
    )


def assert_press_line(data: dict):
    _assert_common_fields(data, "PressLine")
    assert isinstance(data["line_code"], str) and data["line_code"]
    assert data["tonnage_class"] in ("STANDARD", "HEAVY")
    assert isinstance(data["hours_per_day"], int) and data["hours_per_day"] > 0
    assert isinstance(data["daily_unit_capacity"], int) and data["daily_unit_capacity"] > 0


def assert_press_slot(data: dict):
    _assert_common_fields(data, "PressSlot")
    assert is_valid_uuid(str(data["press_line_id"]))
    assert data["slot_kind"] in ("PRODUCTION", "MAINTENANCE")
    assert isinstance(data["date"], str)
    assert isinstance(data["start_hour"], int)
    assert isinstance(data["end_hour"], int)
    assert isinstance(data["planned_units"], int)
    assert isinstance(data["freed"], bool)


def assert_plating_bath(data: dict):
    _assert_common_fields(data, "PlatingBath")
    assert isinstance(data["bath_code"], str) and data["bath_code"]
    assert isinstance(data["rinse_gap_minutes"], int)


def assert_qc_report(data: dict):
    _assert_common_fields(data, "QCReport")
    assert is_valid_uuid(str(data["press_order_id"]))
    assert isinstance(data["units_pressed"], int) and data["units_pressed"] > 0
    assert isinstance(data["units_rejected"], int) and data["units_rejected"] >= 0
    assert data["units_rejected"] <= data["units_pressed"]
    assert data["outcome"] in ("PASS", "HOLD")
    assert data["status"] in ("FILED", "DECIDED")
    assert data["decision"] in ("NONE", "ACCEPT", "REPRESS")
    assert data["fault"] in ("NONE", "PLANT", "CUSTOMER")
    assert isinstance(data["filed_by"], str) and data["filed_by"]


def assert_inventory_lot(data: dict):
    _assert_common_fields(data, "InventoryLot")
    assert is_valid_uuid(str(data["release_id"]))
    assert data["zone"] in ("A", "B", "C")
    assert isinstance(data["receipt_seq"], int)
    for f in ("on_hand_units", "allocated_units", "shipped_units_cum",
              "damaged_units_cum", "received_units_cum"):
        assert isinstance(data[f], int) and data[f] >= 0, f"InventoryLot.{f} must be >= 0"


def assert_shipment(data: dict):
    _assert_common_fields(data, "Shipment")
    assert is_valid_uuid(str(data["release_id"]))
    assert is_valid_uuid(str(data["distributor_customer_id"]))
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert data["status"] in ("PLANNED", "ALLOCATED", "PICKED", "SHIPPED", "CANCELLED")
    assert isinstance(data["allocations"], list)


def assert_delay_notice(data: dict):
    """DelayNotice is append-only: id + created_at only among common fields."""
    assert is_valid_uuid(str(data.get("id", ""))), "DelayNotice.id must be a valid UUID"
    assert is_iso8601_timestamp(str(data.get("created_at", ""))), (
        "DelayNotice.created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "DelayNotice must not carry updated_at"
    assert "version" not in data, "DelayNotice must not carry version"
    assert data["cause"] in ("TP_REVISION", "REPRESS", "SCHEDULE", "DATE_REVISION")
    assert data["prior_level"] in ("ON_TRACK", "AT_RISK", "LATE")
    assert data["new_level"] in ("ON_TRACK", "AT_RISK", "LATE")
    assert isinstance(data["message"], str) and data["message"]


def assert_invoice(data: dict):
    _assert_common_fields(data, "Invoice")
    assert is_valid_uuid(str(data["press_order_id"]))
    assert is_valid_uuid(str(data["customer_id"]))
    assert data["kind"] in ("STANDARD", "CANCELLATION_FEE", "CREDIT_MEMO")
    for f in ("gross_cents", "discount_cents", "net_cents", "paid_cents", "credited_cents"):
        assert isinstance(data[f], int), f"Invoice.{f} must be an int"
    assert isinstance(data["lines"], list)
    for line in data["lines"]:
        assert isinstance(line["label"], str)
        assert isinstance(line["gross_cents"], int)
        assert isinstance(line["discount_cents"], int)
        assert isinstance(line["net_cents"], int)
    assert data["status"] in ("ISSUED", "PARTIALLY_PAID", "PAID", "CREDITED")
    assert data["gross_cents"] - data["discount_cents"] == data["net_cents"], (
        "Invoice net must equal gross minus discount"
    )


def assert_lot_invariants(data: dict):
    """Physical-unit conservation: received == on_hand + allocated + shipped + damaged."""
    assert_inventory_lot(data)
    assert data["received_units_cum"] == (
        data["on_hand_units"] + data["allocated_units"]
        + data["shipped_units_cum"] + data["damaged_units_cum"]
    ), (
        f"Lot conservation violated: received {data['received_units_cum']} != "
        f"on_hand {data['on_hand_units']} + allocated {data['allocated_units']} + "
        f"shipped {data['shipped_units_cum']} + damaged {data['damaged_units_cum']}"
    )
