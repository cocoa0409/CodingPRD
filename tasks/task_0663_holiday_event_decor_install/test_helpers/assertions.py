"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_quartet(data: dict):
    """Every resource carries id / created_at / updated_at / version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an int"
    assert data["version"] >= 1, "version begins at 1"


def assert_client(data: dict):
    _assert_common_quartet(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert data["account_type"] in ("COMMERCIAL", "HOA", "EVENT")
    assert isinstance(data["contact_email"], str)
    assert isinstance(data["site_address"], str)
    assert data["status"] == "ACTIVE"


def assert_contract(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be a valid UUID"
    assert data["contract_type"] in ("COMMERCIAL", "HOA", "EVENT")
    assert isinstance(data["season_year"], int)
    assert data["status"] in (
        "DRAFT", "PROPOSED", "SIGNED", "ACTIVE", "RENEWAL_OFFERED", "EXPIRED", "CANCELLED",
    )
    assert isinstance(data["custom_design_surcharge_cents"], int)
    assert data["custom_design_surcharge_cents"] >= 0


def assert_design_proposal(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data.get("contract_id", ""))
    assert isinstance(data["theme"], str)
    assert isinstance(data["total_unit_count"], int)
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED", "SUPERSEDED")


def assert_proposal_line_item(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data.get("proposal_id", ""))
    assert is_valid_uuid(data.get("inventory_item_id", ""))
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_install_cents"], int) and data["unit_install_cents"] >= 0


def assert_inventory_item(data: dict):
    _assert_common_quartet(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert data["category"] in ("TREE", "WREATH", "GARLAND", "LIGHTING")
    assert isinstance(data["unit_replacement_cents"], int) and data["unit_replacement_cents"] >= 0
    assert isinstance(data["on_hand_qty"], int) and data["on_hand_qty"] >= 0
    assert isinstance(data["reorder_threshold"], int) and data["reorder_threshold"] >= 0


def assert_crew(data: dict):
    _assert_common_quartet(data)
    assert isinstance(data["crew_name"], str)
    assert isinstance(data["daily_capacity_minutes"], int) and data["daily_capacity_minutes"] >= 1
    assert isinstance(data["home_base_zip"], str)
    assert isinstance(data["planned_utilization_pct"], int)
    assert isinstance(data["actual_utilization_pct"], int)


def assert_work_order(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data.get("contract_id", ""))
    assert data["job_type"] in ("INSTALL", "REFRESH", "TAKEDOWN")
    assert data["schedule_status"] in (
        "UNSCHEDULED", "SCHEDULED", "DISPATCHED", "COMPLETED", "CANCELLED",
    )
    assert data["billing_status"] in ("PENDING", "INVOICED", "PAID")


def assert_visit(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data.get("work_order_id", ""))
    assert isinstance(data["stop_sequence"], int) and data["stop_sequence"] >= 1
    assert data["visit_status"] in ("PLANNED", "COMPLETED", "SKIPPED")


def assert_storage_bay(data: dict):
    _assert_common_quartet(data)
    assert isinstance(data["bay_code"], str)
    assert isinstance(data["capacity_units"], int) and data["capacity_units"] >= 1


def assert_storage_lot(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data.get("contract_id", ""))
    assert is_valid_uuid(data.get("storage_bay_id", ""))
    assert isinstance(data["unit_count"], int) and data["unit_count"] >= 1
    assert data["status"] in ("RESERVED", "STORED", "RELEASED")


def assert_damage_report(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data.get("work_order_id", ""))
    assert is_valid_uuid(data.get("inventory_item_id", ""))
    assert isinstance(data["damaged_qty"], int) and data["damaged_qty"] >= 1
    assert data["status"] in ("OPEN", "ASSESSED", "SETTLED", "VOID")


def assert_restock_order(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data.get("inventory_item_id", ""))
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["status"] in ("REQUESTED", "FULFILLED")


def assert_renewal_offer(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data.get("contract_id", ""))
    assert data["status"] in ("DRAFT", "SENT", "ACCEPTED", "DECLINED", "EXPIRED")
