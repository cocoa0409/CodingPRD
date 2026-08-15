"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_common(data: dict, entity_label: str):
    """PRD §2.4: every persisted entity carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity_label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity_label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_label}.version must be a positive integer"
    )


def assert_program(data: dict):
    _assert_common(data, "FlushingProgram")
    assert isinstance(data["program_year"], int), "program_year must be an integer"
    assert data["season"] in ["SPRING", "FALL"], f"unexpected season {data.get('season')}"
    assert data["status"] in ["OPEN", "CLOSED"], f"unexpected program status {data.get('status')}"
    assert isinstance(data["hydrants_out_of_service_count"], int)
    assert isinstance(data["unacknowledged_notification_count"], int)
    assert data["hydrants_out_of_service_count"] >= 0
    assert data["unacknowledged_notification_count"] >= 0


def assert_zone(data: dict):
    _assert_common(data, "PressureZone")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["cooldown_minutes"], int)


def assert_private_owner(data: dict):
    _assert_common(data, "PrivateOwner")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["contact_email"], str) and len(data["contact_email"]) > 0


def assert_hydrant(data: dict):
    _assert_common(data, "Hydrant")
    assert isinstance(data["hydrant_number"], str) and len(data["hydrant_number"]) > 0
    assert is_valid_uuid(data.get("program_id", "")), "program_id must be a UUID"
    assert is_valid_uuid(data.get("zone_id", "")), "zone_id must be a UUID"
    assert data["ownership"] in ["MUNICIPAL", "PRIVATE"], f"unexpected ownership {data.get('ownership')}"
    if data["ownership"] == "PRIVATE":
        assert is_valid_uuid(data.get("private_owner_id", "")), (
            "private_owner_id must be a UUID when ownership is PRIVATE"
        )
    else:
        assert data.get("private_owner_id") in (None, ""), (
            "private_owner_id must be absent/null when ownership is MUNICIPAL"
        )
    assert isinstance(data["required_fire_flow_gpm"], int)
    assert data["status"] in ["IN_SERVICE", "OUT_OF_SERVICE", "DECOMMISSIONED"]
    assert data["inspection_tier"] in ["CURRENT", "DUE_SOON", "OVERDUE", "CRITICAL"]
    assert data.get("provisional_fire_flow_gpm") is None or isinstance(data["provisional_fire_flow_gpm"], int)
    assert data.get("approved_fire_flow_gpm") is None or isinstance(data["approved_fire_flow_gpm"], int)
    assert isinstance(data["targeted_flush_pending"], bool)


def assert_inspection(data: dict):
    _assert_common(data, "Inspection")
    assert is_valid_uuid(data.get("hydrant_id", "")), "hydrant_id must be a UUID"
    assert data["status"] in ["SCHEDULED", "PENDING_VERIFICATION", "VERIFIED", "REJECTED"]
    assert data["result"] in ["NONE", "PASS", "FAIL"]


def assert_flow_test(data: dict):
    _assert_common(data, "FlowTest")
    assert is_valid_uuid(data.get("hydrant_id", "")), "hydrant_id must be a UUID"
    assert data["status"] in [
        "SCHEDULED", "RESULTS_SUBMITTED", "APPROVED", "REJECTED", "CANCELLED", "MISSED",
    ]
    assert data["classification"] in ["NONE", "PASS", "FAIL"]
    assert data.get("pitot_flow_gpm") is None or isinstance(data["pitot_flow_gpm"], (int, float))
    assert data.get("flow_at_20psi_gpm") is None or isinstance(data["flow_at_20psi_gpm"], int)
    if data["status"] == "CANCELLED":
        assert data.get("cancel_reason") in ["OPERATOR_CANCEL", "OUTAGE_AUTO_CANCEL"]


def assert_flush_sequence(data: dict):
    _assert_common(data, "FlushSequence")
    assert is_valid_uuid(data.get("program_id", "")), "program_id must be a UUID"
    assert is_valid_uuid(data.get("zone_id", "")), "zone_id must be a UUID"
    assert is_valid_uuid(data.get("hydrant_id", "")), "hydrant_id must be a UUID"
    assert data["origin"] in ["SCHEDULED_PROGRAM", "COMPLAINT_AUTO"]
    assert data["status"] in ["PLANNED", "IN_PROGRESS", "COMPLETED", "ABORTED"]
    assert isinstance(data["steps"], list) and len(data["steps"]) >= 1
    for step in data["steps"]:
        assert isinstance(step["step_index"], int) and step["step_index"] >= 1
        assert step["action"] in ["OPEN", "CLOSE"]
        assert step["status"] in ["PENDING", "EXECUTED"]
    assert data.get("total_flushed_gallons") is None or isinstance(data["total_flushed_gallons"], int)
    assert data.get("dechlorination_tablets_required") is None or isinstance(
        data["dechlorination_tablets_required"], int
    )


def assert_complaint(data: dict):
    _assert_common(data, "WaterQualityComplaint")
    assert is_valid_uuid(data.get("hydrant_id", "")), "hydrant_id must be a UUID"
    assert data["category"] in ["DISCOLORED_WATER", "ODOR", "TASTE", "PRESSURE"]
    assert data["status"] in ["OPEN", "LINKED", "RESOLVED", "DISMISSED"]
    if data["status"] == "LINKED":
        assert is_valid_uuid(data.get("flush_sequence_id", "")), (
            "LINKED complaint must carry flush_sequence_id"
        )


def assert_outage(data: dict):
    _assert_common(data, "HydrantOutage")
    assert is_valid_uuid(data.get("hydrant_id", "")), "hydrant_id must be a UUID"
    assert data["reason"] in ["VALVE_FAILURE", "LEAK", "DAMAGE", "OTHER"]
    assert data["status"] in ["ACTIVE", "CLOSED"]
    assert data["notification_status"] in ["PENDING", "ACKNOWLEDGED"]
    assert is_iso8601_timestamp(data.get("notified_at", "")), "notified_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("ack_deadline", "")), "ack_deadline must be ISO 8601"
    assert isinstance(data["escalated"], bool)


def assert_work_order(data: dict):
    _assert_common(data, "RepairWorkOrder")
    assert is_valid_uuid(data.get("hydrant_id", "")), "hydrant_id must be a UUID"
    assert data["status"] in ["DRAFT", "SUBMITTED", "APPROVED", "COMPLETED", "CANCELLED"]
    assert isinstance(data.get("part_lines"), list)
    for line in data["part_lines"]:
        assert is_valid_uuid(line.get("part_id", "")), "part line part_id must be a UUID"
        assert isinstance(line["qty"], int) and line["qty"] > 0, "part line qty must be > 0"
        assert line["status"] in ["PENDING", "RESERVED", "CONSUMED", "RELEASED"]
    for field in (
        "quoted_subtotal_cents", "quoted_discount_cents", "quoted_fee_cents",
        "quoted_total_cents", "actual_total_cents",
    ):
        assert data.get(field) is None or isinstance(data[field], int), (
            f"{field} must be integer cents or null"
        )


def assert_part(data: dict):
    _assert_common(data, "Part")
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["on_hand_qty"], int) and data["on_hand_qty"] >= 0
    assert isinstance(data["available_qty"], int)
    assert data["available_qty"] <= data["on_hand_qty"], (
        "available_qty must never exceed on_hand_qty (reserved stock subtracts)"
    )


def assert_iso_snapshot(data: dict):
    _assert_common(data, "ISOSnapshot")
    assert is_valid_uuid(data.get("program_id", "")), "program_id must be a UUID"
    assert data["weighting_profile"] in ["MUNICIPAL_ONLY", "ALL_HYDRANTS_HALF_PRIVATE"]
    assert data["status"] in ["DRAFT", "PUBLISHED", "SUPERSEDED"]
    for field in ("total_hydrants_in_scope", "flow_coverage_pct", "inspection_compliance_pct", "iso_points"):
        assert data.get(field) is None or isinstance(data[field], (int, float)), (
            f"{field} must be numeric or null"
        )


def assert_part_available_invariant(part: dict, expected_reserved_qty: int = 0):
    """PRD §3.7: available_qty = on_hand_qty - SUM(qty over RESERVED lines)."""
    assert part["available_qty"] == part["on_hand_qty"] - expected_reserved_qty, (
        f"available_qty {part['available_qty']} != on_hand {part['on_hand_qty']} "
        f"- reserved {expected_reserved_qty}"
    )


def assert_program_counters(program: dict, out_of_service: int, unacknowledged: int):
    """PRD §2.7: the two maintained program counters."""
    assert program["hydrants_out_of_service_count"] == out_of_service, (
        f"hydrants_out_of_service_count expected {out_of_service}, "
        f"got {program['hydrants_out_of_service_count']}"
    )
    assert program["unacknowledged_notification_count"] == unacknowledged, (
        f"unacknowledged_notification_count expected {unacknowledged}, "
        f"got {program['unacknowledged_notification_count']}"
    )
