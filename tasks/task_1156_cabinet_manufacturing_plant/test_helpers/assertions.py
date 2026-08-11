"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(str(data.get("id", ""))), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(str(data.get("created_at", ""))), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(str(data.get("updated_at", ""))), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer >= 1"
    )


def assert_dealer(data: dict):
    _assert_common_fields(data, "Dealer")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["dealer_code"], str) and data["dealer_code"]
    assert data["price_level"] in ["L1", "L2", "L3", "L4", "L5"]
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0


def assert_door_style(data: dict):
    _assert_common_fields(data, "DoorStyle")
    assert isinstance(data["style_code"], str) and data["style_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["construction"] in ["SLAB", "SHAKER", "RAISED_PANEL", "GLASS"]
    assert isinstance(data["base_list_price_cents"], int) and data["base_list_price_cents"] > 0
    assert isinstance(data["active"], bool)


def assert_finish_spec(data: dict):
    _assert_common_fields(data, "FinishSpec")
    assert isinstance(data["finish_code"], str) and data["finish_code"]
    assert isinstance(data["color_name"], str) and data["color_name"]
    assert data["sheen"] in ["MATTE", "SATIN", "SEMI_GLOSS", "HIGH_GLOSS"]
    assert data["upcharge_pct"] >= 0
    assert data["delta_e_tolerance"] > 0
    assert isinstance(data["active"], bool)


def assert_component(data: dict):
    _assert_common_fields(data, "Component")
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["kind"] in ["SHEET_GOODS", "DOOR_BLANK", "HARDWARE"]
    if data["kind"] == "SHEET_GOODS":
        assert isinstance(data["sheet_width_in"], int) and data["sheet_width_in"] > 0
        assert isinstance(data["sheet_height_in"], int) and data["sheet_height_in"] > 0
    assert isinstance(data["on_hand_qty"], int) and data["on_hand_qty"] >= 0
    assert isinstance(data["reserved_qty"], int)
    # Read-only derived figure: available == on_hand - reserved (PRD §3.1).
    assert data["available_qty"] == data["on_hand_qty"] - data["reserved_qty"], (
        f"available_qty {data['available_qty']} != on_hand {data['on_hand_qty']} - reserved {data['reserved_qty']}"
    )


def assert_order(data: dict):
    _assert_common_fields(data, "Order")
    assert is_valid_uuid(str(data.get("dealer_id", ""))), "Order.dealer_id must be a UUID"
    assert data["price_level_snapshot"] in ["L1", "L2", "L3", "L4", "L5"]
    assert data["status"] in ["DRAFT", "SUBMITTED", "IN_PRODUCTION", "READY_TO_SHIP", "SHIPPED", "CANCELLED"]
    assert data["hold_status"] in ["NONE", "ON_HOLD"]


def assert_order_line(data: dict):
    _assert_common_fields(data, "OrderLine")
    assert is_valid_uuid(str(data.get("order_id", ""))), "OrderLine.order_id must be a UUID"
    assert data["line_type"] in ["BOX", "DOOR"]
    if data["line_type"] == "DOOR":
        assert data.get("door_style_id"), "DOOR line must reference a door style"
        assert data["depth_in"] == 1, "DOOR line depth_in must equal 1"
    assert data["width_in"] > 0 and data["height_in"] > 0 and data["depth_in"] > 0
    assert data["qty"] > 0
    assert data["unit_list_price_cents"] > 0
    assert data["line_list_cents"] == data["unit_list_price_cents"] * data["qty"]
    assert data["status"] in ["PENDING", "QUOTED", "IN_PROGRESS", "COMPLETED", "SHIPPED", "CANCELLED"]


def assert_modification(data: dict):
    _assert_common_fields(data, "ModificationRequest")
    assert is_valid_uuid(str(data.get("order_line_id", ""))), "ModificationRequest.order_line_id must be a UUID"
    assert data["mod_code"] in [
        "REDUCED_DEPTH", "INCREASED_DEPTH", "REDUCED_WIDTH",
        "INCREASED_WIDTH", "TOE_KICK_NOTCH", "CUSTOM_BORE",
    ]
    assert data["new_dimension_in"] > 0
    assert isinstance(data["surcharge_cents"], int) and data["surcharge_cents"] >= 0
    assert isinstance(data["revision"], int) and data["revision"] >= 1
    assert data["status"] in ["UNDER_REVIEW", "CHANGES_REQUESTED", "APPROVED", "REJECTED"]


def assert_finish_batch(data: dict):
    _assert_common_fields(data, "FinishBatch")
    assert is_valid_uuid(str(data.get("finish_id", ""))), "FinishBatch.finish_id must be a UUID"
    assert isinstance(data["sheen_lot_no"], str) and data["sheen_lot_no"]
    assert isinstance(data["capacity_doors"], int) and data["capacity_doors"] > 0
    assert isinstance(data["assigned_door_count"], int) and data["assigned_door_count"] >= 0
    assert isinstance(data["remix_count"], int) and data["remix_count"] >= 0
    assert data["status"] in ["MIXING", "RELEASED", "FAILED"]


def assert_nesting_station(data: dict):
    _assert_common_fields(data, "NestingStation")
    assert isinstance(data["station_code"], str) and data["station_code"]
    assert isinstance(data["changeover_minutes"], int) and data["changeover_minutes"] >= 0
    assert isinstance(data["active"], bool)


def assert_nesting_run(data: dict):
    _assert_common_fields(data, "NestingRun")
    assert is_valid_uuid(str(data.get("station_id", ""))), "NestingRun.station_id must be a UUID"
    assert is_valid_uuid(str(data.get("sheet_component_id", ""))), "NestingRun.sheet_component_id must be a UUID"
    assert isinstance(data["door_line_ids"], list)
    assert 0 <= data["start_minute"] <= 1439
    assert data["start_minute"] < data["end_minute"] <= 1440
    assert data["status"] in ["DRAFT", "RELEASED", "CANCELLED"]


def assert_part(data: dict):
    # Append-only generated record: id + created_at only (PRD §2.4). The
    # representation must NOT carry updated_at or version.
    assert is_valid_uuid(str(data.get("id", ""))), "Part.id must be a valid UUID"
    assert is_iso8601_timestamp(str(data.get("created_at", ""))), "Part.created_at must be ISO 8601"
    assert "updated_at" not in data, "Part must not carry updated_at"
    assert "version" not in data, "Part must not carry version"
    assert is_valid_uuid(str(data.get("nesting_run_id", ""))), "Part.nesting_run_id must be a UUID"
    assert is_valid_uuid(str(data.get("order_line_id", ""))), "Part.order_line_id must be a UUID"
    assert is_valid_uuid(str(data.get("component_id", "")), ), "Part.component_id must be a UUID"
    assert data["part_kind"] == "DOOR_BLANK"
    assert data["width_in"] > 0 and data["height_in"] > 0 and data["qty"] > 0
    assert isinstance(data["part_seq"], int) and data["part_seq"] >= 1


def assert_assembly_line(data: dict):
    _assert_common_fields(data, "AssemblyLine")
    assert isinstance(data["line_code"], str) and data["line_code"]
    assert data["capacity_minutes_per_day"] > 0
    assert data["standard_minutes_per_box"] > 0
    assert data["setup_minutes_per_sub_lot"] >= 0
    assert isinstance(data["active"], bool)


def assert_sub_lot(data: dict):
    _assert_common_fields(data, "SubLot")
    assert is_valid_uuid(str(data.get("order_id", ""))), "SubLot.order_id must be a UUID"
    assert is_valid_uuid(str(data.get("order_line_id", ""))), "SubLot.order_line_id must be a UUID"
    assert is_valid_uuid(str(data.get("assembly_line_id", ""))), "SubLot.assembly_line_id must be a UUID"
    assert 0 <= data["start_minute"] <= 1439
    assert data["qty"] > 0
    assert data["end_minute"] == data["start_minute"] + data["work_minutes"]
    assert data["end_minute"] <= 1440
    assert data["status"] in ["SCHEDULED", "COMPLETE", "CANCELLED"]


def assert_replacement_claim(data: dict):
    _assert_common_fields(data, "ReplacementClaim")
    assert is_valid_uuid(str(data.get("dealer_id", ""))), "ReplacementClaim.dealer_id must be a UUID"
    assert is_valid_uuid(str(data.get("original_order_line_id", ""))), (
        "ReplacementClaim.original_order_line_id must be a UUID"
    )
    assert data["claim_type"] in ["FREIGHT_DAMAGE", "MANUFACTURING_DEFECT", "DEALER_ERROR"]
    assert data["qty"] > 0
    assert isinstance(data["credit_basis_cents"], int) and data["credit_basis_cents"] >= 0
    assert data["status"] in ["SUBMITTED", "APPROVED_NO_CHARGE", "APPROVED_CHARGED", "DENIED"]


def assert_delivery_route(data: dict):
    _assert_common_fields(data, "DeliveryRoute")
    assert isinstance(data["route_code"], str) and data["route_code"]
    assert data["capacity_cu_ft"] > 0
    assert isinstance(data["assigned_order_count"], int) and data["assigned_order_count"] >= 0
    assert data["status"] in ["PLANNED", "LOCKED", "DISPATCHED"]


def assert_order_hold(data: dict):
    _assert_common_fields(data, "OrderHold")
    assert is_valid_uuid(str(data.get("order_id", ""))), "OrderHold.order_id must be a UUID"
    assert data["reason"] in ["COMPONENT_SHORTAGE", "FINISH_QC"]
    assert data["status"] in ["PLACED", "RELEASED"]
