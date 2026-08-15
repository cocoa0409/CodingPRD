"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer >= 1"
    )


def _assert_append_only_fields(data: dict, entity: str):
    # PRD §2.4: DimensionerScan and ServiceStandardReport carry only id + created_at.
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )


def assert_terminal(data: dict):
    _assert_common_fields(data, "Terminal")
    assert isinstance(data["code"], str) and len(data["code"]) == 3
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["dock_doors"], int) and data["dock_doors"] >= 1
    assert data["status"] in ("ACTIVE", "CLOSED")


def assert_shipment(data: dict):
    _assert_common_fields(data, "Shipment")
    assert isinstance(data["pro_number"], str) and data["pro_number"].startswith("PRO-")
    assert data["nmfc_class"] in (
        "CLASS_50", "CLASS_55", "CLASS_60", "CLASS_65",
        "CLASS_70", "CLASS_85", "CLASS_100", "CLASS_125",
    )
    assert isinstance(data["actual_weight_lbs"], int) and data["actual_weight_lbs"] >= 1
    assert isinstance(data["chargeable_weight_lbs"], int)
    assert isinstance(data["dim_weight_lbs"], int)
    assert isinstance(data["rated_amount_cents"], int)
    assert isinstance(data["billed_amount_cents"], int)
    assert data["rating_status"] in (
        "UNRATED", "RATED", "INSPECTION_PENDING", "RERATED", "BILLED"
    )
    assert data["handling_status"] in (
        "TENDERED", "ON_DOCK", "MANIFESTED", "IN_LINEHAUL", "DELIVERED", "CANCELLED"
    )
    assert isinstance(data["osd_hold"], bool)


def assert_pickup_route(data: dict):
    _assert_common_fields(data, "PickupRoute")
    assert isinstance(data["shift_start_minute"], int)
    assert isinstance(data["shift_end_minute"], int)
    assert data["status"] in ("PLANNED", "DISPATCHED", "COMPLETED", "RECALLED")


def assert_pickup_stop(data: dict):
    _assert_common_fields(data, "PickupStop")
    assert isinstance(data["stop_sequence"], int) and data["stop_sequence"] >= 1
    assert isinstance(data["planned_arrival_minute"], int)
    assert data["status"] in ("PLANNED", "ARRIVED", "PICKED_UP", "SKIPPED")


def assert_dock_door(data: dict):
    _assert_common_fields(data, "DockDoor")
    assert isinstance(data["door_number"], int) and data["door_number"] >= 1
    assert data["door_kind"] in ("INBOUND", "OUTBOUND")
    assert data["status"] in ("AVAILABLE", "RESERVED", "OCCUPIED", "OUT_OF_SERVICE")


def assert_sortation_batch(data: dict):
    _assert_common_fields(data, "SortationBatch")
    assert data["status"] in ("OPEN", "CLOSED", "DISPOSITIONED")


def assert_outbound_trailer(data: dict):
    _assert_common_fields(data, "OutboundTrailer")
    assert isinstance(data["max_weight_lbs"], int) and data["max_weight_lbs"] >= 1
    assert isinstance(data["max_cube_cuft"], int) and data["max_cube_cuft"] >= 1
    assert isinstance(data["loaded_weight_lbs"], int) and data["loaded_weight_lbs"] >= 0
    assert isinstance(data["loaded_cube_cuft"], int) and data["loaded_cube_cuft"] >= 0
    assert data["posture"] in (
        "LOADING", "READY", "SEALED", "DISPATCHED", "ARRIVED", "VOIDED"
    )


def assert_manifest_entry(data: dict):
    _assert_common_fields(data, "ManifestEntry")
    assert isinstance(data["load_position"], int) and data["load_position"] >= 1
    assert data["status"] in ("ACTIVE", "REMOVED")


def assert_linehaul_leg(data: dict):
    _assert_common_fields(data, "LinehaulLeg")
    assert isinstance(data["relay_sequence"], int) and data["relay_sequence"] >= 1
    assert data["status"] in ("PLANNED", "EN_ROUTE", "ARRIVED", "CANCELLED")


def assert_dimensioner_scan(data: dict):
    _assert_append_only_fields(data, "DimensionerScan")
    assert isinstance(data["measured_length_in"], int) and data["measured_length_in"] >= 1
    assert isinstance(data["measured_width_in"], int) and data["measured_width_in"] >= 1
    assert isinstance(data["measured_height_in"], int) and data["measured_height_in"] >= 1
    assert isinstance(data["measured_weight_lbs"], int) and data["measured_weight_lbs"] >= 1
    assert isinstance(data["scanned_by"], str) and len(data["scanned_by"]) > 0


def assert_inspection(data: dict):
    _assert_common_fields(data, "Inspection")
    assert data["outcome"] in ("PENDING", "CONFIRMED_RECLASS", "REJECTED")
    assert isinstance(data["adjustment_cents"], int)


def assert_osd_case(data: dict):
    _assert_common_fields(data, "OsdCase")
    assert data["case_kind"] in ("OVERAGE", "SHORTAGE", "DAMAGE")
    assert isinstance(data["claimed_amount_cents"], int) and data["claimed_amount_cents"] >= 0
    assert isinstance(data["item_amounts_cents"], list) and len(data["item_amounts_cents"]) >= 1
    assert isinstance(data["awarded_amount_cents"], int)
    assert data["status"] in ("OPEN", "UNDER_REVIEW", "RESOLVED", "DENIED")


def assert_service_standard_report(data: dict):
    _assert_append_only_fields(data, "ServiceStandardReport")
    assert isinstance(data["shipments_due"], int) and data["shipments_due"] >= 0
    assert isinstance(data["shipments_on_time"], int) and data["shipments_on_time"] >= 0
    assert isinstance(data["service_level_met"], bool)


def assert_trailer_ledger_invariants(trailer: dict):
    """PRD §2.7: utilization reports the more constraining of the two fill ratios."""
    expected = max(
        trailer["loaded_weight_lbs"] / trailer["max_weight_lbs"],
        trailer["loaded_cube_cuft"] / trailer["max_cube_cuft"],
    ) * 100
    assert abs(trailer["utilization_pct"] - round(expected, 1)) < 0.051, (
        f"utilization_pct {trailer['utilization_pct']} inconsistent with ledger "
        f"{trailer['loaded_weight_lbs']}/{trailer['max_weight_lbs']} lbs and "
        f"{trailer['loaded_cube_cuft']}/{trailer['max_cube_cuft']} cuft"
    )
