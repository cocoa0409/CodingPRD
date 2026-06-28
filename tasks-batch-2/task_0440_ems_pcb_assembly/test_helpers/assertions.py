"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common fields carried by every entity (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be a positive int, got {data.get('version')!r}"


def assert_part(data: dict):
    _assert_common(data)
    assert isinstance(data["internal_pn"], str) and len(data["internal_pn"]) > 0
    assert isinstance(data["description"], str)
    assert data["package_type"] in ["0402", "0603", "0805", "SOT23", "QFN", "BGA", "THT"]
    assert isinstance(data["is_rohs_required"], bool)
    assert isinstance(data["contains_conflict_minerals"], bool)
    assert isinstance(data["standard_cost_cents"], int) and data["standard_cost_cents"] >= 0
    assert isinstance(data["total_on_hand_qty"], int) and data["total_on_hand_qty"] >= 0
    assert isinstance(data["available_qty"], int)


def assert_vendor(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert isinstance(data["is_rohs_certified"], bool)


def assert_avl_entry(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["part_id"])
    assert is_valid_uuid(data["vendor_id"])
    assert data["approval_rank"] >= 1
    assert data["status"] in ["APPROVED", "REVOKED"]


def assert_inventory_lot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["part_id"])
    assert is_valid_uuid(data["avl_entry_id"])
    assert isinstance(data["lot_code"], str) and len(data["lot_code"]) > 0
    assert isinstance(data["received_qty"], int) and data["received_qty"] > 0
    assert isinstance(data["remaining_qty"], int) and data["remaining_qty"] >= 0
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 0
    assert isinstance(data["is_rohs_compliant"], bool)
    assert isinstance(data["has_cmrt"], bool)
    assert data["status"] in ["AVAILABLE", "QUARANTINED", "DEPLETED"]


def assert_bom(data: dict):
    _assert_common(data)
    assert isinstance(data["product_code"], str) and len(data["product_code"]) > 0
    assert isinstance(data["revision"], str) and len(data["revision"]) > 0
    assert data["status"] in ["DRAFT", "RELEASED", "OBSOLETE"]
    assert isinstance(data["line_count"], int) and data["line_count"] >= 0


def assert_bom_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["bom_id"])
    assert is_valid_uuid(data["part_id"])
    assert isinstance(data["ref_designators"], list) and len(data["ref_designators"]) > 0
    assert isinstance(data["qty_per_assembly"], int) and data["qty_per_assembly"] > 0
    assert isinstance(data["is_dnp"], bool)


def assert_work_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["bom_id"])
    assert isinstance(data["planned_qty"], int) and data["planned_qty"] > 0
    assert data["status"] in [
        "PLANNED", "KITTED", "SETUP", "RUNNING", "AT_TEST",
        "PASSED", "FAILED", "CLOSED", "CANCELLED",
    ]
    assert isinstance(data["kit_shortage_count"], int) and data["kit_shortage_count"] >= 0
    assert isinstance(data["built_qty"], int) and data["built_qty"] >= 0
    assert isinstance(data["passed_qty"], int) and data["passed_qty"] >= 0
    assert isinstance(data["material_cost_cents"], int) and data["material_cost_cents"] >= 0
    assert isinstance(data["first_pass_yield_pct"], (int, float))


def assert_kit_requirement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["work_order_id"])
    assert is_valid_uuid(data["part_id"])
    assert data["status"] in ["PENDING", "RESERVED", "SHORT", "CONSUMED", "RELEASED"]
    assert isinstance(data["required_qty"], int)
    assert isinstance(data["reserved_qty"], int)
    assert isinstance(data["consumed_qty"], int)


def assert_line_program(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["bom_id"])
    assert isinstance(data["line_code"], str) and len(data["line_code"]) > 0
    assert isinstance(data["feeder_slot_count"], int) and data["feeder_slot_count"] > 0
    assert data["status"] in ["UNVERIFIED", "VERIFIED"]


def assert_unit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["work_order_id"])
    assert isinstance(data["serial_number"], str) and len(data["serial_number"]) > 0
    assert data["quality_status"] in ["BUILT", "PASS", "FAIL", "REWORKED"]
    assert data["disposition"] in ["IN_PROCESS", "SHIPPED", "SCRAPPED", "RETURNED"]
    assert isinstance(data["rework_count"], int) and data["rework_count"] >= 0


def assert_rework_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["unit_id"])
    assert isinstance(data["defect_code"], str) and len(data["defect_code"]) > 0
    assert isinstance(data["added_material_cost_cents"], int) and data["added_material_cost_cents"] >= 0
    assert data["status"] in ["OPEN", "CLOSED", "ABANDONED"]


def assert_eco(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert is_valid_uuid(data["bom_id"])
    assert data["status"] in ["DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "IMPLEMENTED"]


def assert_rma(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["unit_id"])
    assert isinstance(data["reported_defect_code"], str)
    assert data["status"] in ["RECEIVED", "TRIAGED", "REPAIRED", "SCRAPPED", "CLOSED"]
    assert isinstance(data["warranty_credit_cents"], int) and data["warranty_credit_cents"] >= 0
