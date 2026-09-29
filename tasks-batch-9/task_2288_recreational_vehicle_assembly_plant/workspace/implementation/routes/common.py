"""Shared route plumbing: entity lookup with the right 404 code, list pagination."""
import db
import response
import validation
from db import store
from errors import ApiError
from services import serialize

NOT_FOUND_ID = {
    "suppliers": "ERR_SUPPLIER_NOT_FOUND",
    "floor_plans": "ERR_FLOOR_PLAN_NOT_FOUND",
    "option_items": "ERR_OPTION_ITEM_NOT_FOUND",
    "dealers": "ERR_DEALER_NOT_FOUND",
    "unit_orders": "ERR_UNIT_ORDER_NOT_FOUND",
    "production_lines": "ERR_PRODUCTION_LINE_NOT_FOUND",
    "production_slots": "ERR_PRODUCTION_SLOT_NOT_FOUND",
    "chassis_receipts": "ERR_CHASSIS_RECEIPT_NOT_FOUND",
    "component_lots": "ERR_COMPONENT_LOT_NOT_FOUND",
    "unit_builds": "ERR_UNIT_BUILD_NOT_FOUND",
    "component_installations": "ERR_COMPONENT_INSTALLATION_NOT_FOUND",
    "test_booths": "ERR_TEST_BOOTH_NOT_FOUND",
    "quality_inspections": "ERR_QUALITY_INSPECTION_NOT_FOUND",
    "warranty_claims": "ERR_WARRANTY_CLAIM_NOT_FOUND",
    "recall_campaigns": "ERR_RECALL_CAMPAIGN_NOT_FOUND",
}

LABEL = {
    "suppliers": "Supplier",
    "floor_plans": "Floor plan",
    "option_items": "Option item",
    "dealers": "Dealer",
    "unit_orders": "Unit order",
    "production_lines": "Production line",
    "production_slots": "Production slot",
    "chassis_receipts": "Chassis receipt",
    "component_lots": "Component lot",
    "unit_builds": "Unit build",
    "component_installations": "Component installation",
    "test_booths": "Test booth",
    "quality_inspections": "Quality inspection",
    "warranty_claims": "Warranty claim",
    "recall_campaigns": "Recall campaign",
}


def collection(name):
    return getattr(store, name)


def must_find(name, row_id):
    row = collection(name).get(row_id)
    if row is None:
        raise ApiError(
            NOT_FOUND_ID[name], "{} '{}' does not exist.".format(LABEL[name], row_id)
        )
    return row


def insert(name, row):
    collection(name)[row["id"]] = row
    return row


def object_out(name, row, status=200):
    return response.object_response(serialize.SERIALIZERS[name](row), status)


def list_out(name, rows):
    limit, offset = validation.pagination()
    rows = db.ordered(rows)
    total = len(rows)
    page = rows[offset : offset + limit]
    items = [serialize.SERIALIZERS[name](row) for row in page]
    return response.list_response(items, limit, offset, total)
