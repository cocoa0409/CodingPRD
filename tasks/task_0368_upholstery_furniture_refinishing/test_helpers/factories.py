"""Payload factories — one per entity, input fields only."""
import uuid


def _unique_email(prefix="cust"):
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Customer",
        "email": _unique_email(),
        "phone": "555-0100",
    }
    defaults.update(overrides)
    return defaults


def create_fabric_sku_payload(**overrides) -> dict:
    defaults = {
        "sku_code": f"FAB-{uuid.uuid4().hex[:8].upper()}",
        "name": "Test Fabric",
        "price_cents_per_yard": 1800,
        "roll_width_inches": 54,
        "in_stock_yards": 100,
    }
    defaults.update(overrides)
    return defaults


def create_foam_spec_payload(**overrides) -> dict:
    defaults = {
        "grade_code": f"FOAM-{uuid.uuid4().hex[:8].upper()}",
        "density_lb": 2.0,
        "price_cents_per_board_foot": 350,
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "service_type": "REPAIR",
        "rush_requested": False,
    }
    defaults.update(overrides)
    return defaults


def create_condition_photo_payload(work_order_id, **overrides) -> dict:
    defaults = {
        "work_order_id": work_order_id,
        "image_uri": "s3://photos/test.jpg",
        "damage_note": "test condition note",
    }
    defaults.update(overrides)
    return defaults


def create_line_item_payload(**overrides) -> dict:
    """Defaults to a non-reupholstery (REPAIR/REFINISH) piece: no fabric, yardage 0.
    Override fabric_sku_id / yardage_required for REUPHOLSTERY pieces."""
    defaults = {
        "piece_label": "Test Piece",
        "yardage_required": 0,
        "labor_hours": 2,
    }
    defaults.update(overrides)
    return defaults


def create_estimate_payload(expected_work_order_version, **overrides) -> dict:
    defaults = {
        "expected_work_order_version": expected_work_order_version,
    }
    defaults.update(overrides)
    return defaults


def approve_payload(expected_work_order_version, deposit_amount_cents, **overrides) -> dict:
    defaults = {
        "expected_work_order_version": expected_work_order_version,
        "deposit_amount_cents": deposit_amount_cents,
    }
    defaults.update(overrides)
    return defaults


def cancel_payload(expected_work_order_version, **overrides) -> dict:
    defaults = {
        "expected_work_order_version": expected_work_order_version,
    }
    defaults.update(overrides)
    return defaults


def create_material_order_payload(work_order_id, **overrides) -> dict:
    defaults = {
        "work_order_id": work_order_id,
    }
    defaults.update(overrides)
    return defaults


def create_shop_day_payload(work_date, labor_capacity_hours, **overrides) -> dict:
    defaults = {
        "work_date": work_date,
        "labor_capacity_hours": labor_capacity_hours,
    }
    defaults.update(overrides)
    return defaults


def create_fulfillment_leg_payload(work_order_id, kind, **overrides) -> dict:
    defaults = {
        "work_order_id": work_order_id,
        "kind": kind,
    }
    defaults.update(overrides)
    return defaults


def file_warranty_claim_payload(filed_at, **overrides) -> dict:
    defaults = {
        "defect_note": "reported defect",
        "filed_at": filed_at,
    }
    defaults.update(overrides)
    return defaults
