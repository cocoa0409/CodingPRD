"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_product_model(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int)
    assert isinstance(data["model_code"], str) and data["model_code"]
    assert data["category"] in ("SOFA", "CHAIR", "SECTIONAL", "OTTOMAN")
    assert data["flammability_standard"] in ("TB117_2013", "UFAC", "TB133")
    assert data["status"] in ("ACTIVE", "DISCONTINUED")


def assert_fabric_spec(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data["fabric_code"], str) and data["fabric_code"]
    assert data["origin"] in ("PLANT", "CUSTOMER")
    assert data["grade"] in ("A", "B", "C", "D", "COM")


def assert_dealer_account(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data["dealer_code"], str) and data["dealer_code"]
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["sample_allowance_cents"], int)
    assert isinstance(data["outstanding_sample_value_cents"], int)


def assert_customer_order(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data["order_number"], str) and data["order_number"]
    assert data["delivery_method"] in ("LTL_FREIGHT", "WHITE_GLOVE")
    assert data["status"] in (
        "DRAFT", "CONFIRMED", "MATERIAL_HOLD", "IN_PRODUCTION",
        "QUALITY_REVIEW", "READY_TO_SHIP", "SHIPPED", "DELIVERED", "CANCELLED",
    )
    assert data["quality_result"] in ("NONE", "PASSED", "FAILED")
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["com_credit_cents"], int)
    assert isinstance(data["total_cents"], int)


def assert_order_line(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["fabric_source"] in ("PLANT_STOCK", "COM")
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert data["status"] in (
        "PENDING", "MATERIAL_SHORTFALL", "ALLOCATED", "CUT",
        "SEWN", "UPHOLSTERED", "COMPLETED", "CANCELLED",
    )


def assert_material_lot(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["ownership"] in ("PLANT", "CUSTOMER")
    assert data["status"] in (
        "EXPECTED", "RECEIVED", "AVAILABLE", "REJECTED", "DEPLETED", "RETURNED",
    )


def assert_material_allocation(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["status"] in ("ACTIVE", "CONSUMED", "RELEASED")
    assert data["yards"] > 0


def assert_cut_plan(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["status"] in ("DRAFT", "APPROVED", "CUT", "SUPERSEDED", "VOID")


def assert_cell(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data["cell_code"], str) and data["cell_code"]
    assert data["cell_type"] in ("CUTTING", "SEWING", "UPHOLSTERY")
    assert data["status"] in ("ACTIVE", "DOWN")
    assert isinstance(data["capacity_slots"], int) and data["capacity_slots"] >= 1


def assert_cell_booking(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["operation"] in ("CUT", "SEW", "UPHOLSTER")
    assert data["status"] in ("BOOKED", "IN_PROGRESS", "COMPLETED", "RELEASED")


def assert_compliance_certificate(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["standard"] in ("TB117_2013", "UFAC", "TB133")
    assert data["status"] in ("DRAFT", "CERTIFIED", "VOID")


def assert_supply_requisition(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["source_type"] in ("CONTAINER", "DOMESTIC")
    assert data["status"] in ("OPEN", "PLACED", "RECEIVED", "CANCELLED")


def assert_showroom_sample(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["disposition"] in ("ON_LOAN", "RETURNED", "SOLD", "WRITTEN_OFF")


def assert_shipment(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["method"] in ("LTL", "WHITE_GLOVE")
    assert data["status"] in ("DRAFT", "RATED", "TENDERED", "PICKED_UP", "DELIVERED")
