"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["phone"], str)
    assert isinstance(data["store_credit_cents"], int)
    assert data["store_credit_cents"] >= 0, "store_credit_cents must never be negative"


def assert_fabric_sku(data: dict):
    _assert_common(data)
    assert isinstance(data["sku_code"], str) and len(data["sku_code"]) > 0
    assert isinstance(data["price_cents_per_yard"], int) and data["price_cents_per_yard"] >= 0
    assert data["roll_width_inches"] > 0
    assert data["status"] in ("LISTED", "DISCONTINUED")


def assert_foam_spec(data: dict):
    _assert_common(data)
    assert isinstance(data["grade_code"], str) and len(data["grade_code"]) > 0
    assert data["density_lb"] > 0
    assert isinstance(data["price_cents_per_board_foot"], int) and data["price_cents_per_board_foot"] >= 0
    assert data["status"] in ("LISTED", "DISCONTINUED")


def assert_work_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["customer_id"]), "customer_id must be a UUID"
    assert data["service_type"] in ("REUPHOLSTERY", "REFINISH", "REPAIR")
    assert isinstance(data["rush_requested"], bool)
    assert isinstance(data["estimate_total_cents"], int)
    assert isinstance(data["final_invoice_cents"], int)
    assert isinstance(data["amount_paid_cents"], int)
    assert isinstance(data["balance_due_cents"], int)
    assert isinstance(data["materials_committed_cents"], int)
    assert data["status"] in (
        "INTAKE", "ESTIMATING", "AWAITING_APPROVAL", "REVISION_REQUESTED",
        "APPROVED", "IN_PRODUCTION", "READY_FOR_FULFILLMENT", "COMPLETED",
        "DECLINED", "CANCELLED",
    )


def assert_line_item(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["work_order_id"])
    assert isinstance(data["piece_label"], str) and len(data["piece_label"]) > 0
    assert data["labor_hours"] > 0
    assert data["yardage_required"] >= 0
    assert data["board_feet_required"] >= 0
    assert isinstance(data["piece_subtotal_cents"], int)


def assert_estimate(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["work_order_id"])
    assert isinstance(data["version_no"], int) and data["version_no"] >= 1
    assert isinstance(data["labor_total_cents"], int)
    assert isinstance(data["materials_total_cents"], int)
    assert isinstance(data["rush_surcharge_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert data["status"] in ("ACTIVE", "SUPERSEDED", "APPROVED", "DECLINED")


def assert_material_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["work_order_id"])
    assert isinstance(data["provisional_cost_cents"], int)
    assert isinstance(data["finalized_cost_cents"], int)
    assert data["status"] in ("ORDERED", "RECEIVED", "CANCELLED")


def assert_shop_day(data: dict):
    _assert_common(data)
    assert isinstance(data["work_date"], str)
    assert data["labor_capacity_hours"] > 0
    assert data["booked_hours"] >= 0
    assert data["status"] in ("OPEN", "FULL", "CLOSED")


def assert_fulfillment_leg(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["work_order_id"])
    assert data["kind"] in ("PRODUCTION", "PICKUP", "DELIVERY")
    assert data["status"] in ("PLANNED", "DISPATCHED", "COMPLETED", "CANCELLED")


def assert_warranty_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["work_order_id"])
    assert isinstance(data["defect_note"], str)
    assert isinstance(data["covered"], bool)
    assert data["status"] in ("OPEN", "APPROVED", "DENIED", "RESOLVED")


def assert_payment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["work_order_id"])
    assert data["kind"] in ("DEPOSIT", "SETTLEMENT", "REFUND")
    assert data["amount_cents"] > 0
    assert data["status"] == "RECORDED"


def assert_condition_photo(data: dict):
    """ConditionPhoto is immutable: id + created_at only, no updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["work_order_id"])
    assert isinstance(data["image_uri"], str) and len(data["image_uri"]) > 0
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
