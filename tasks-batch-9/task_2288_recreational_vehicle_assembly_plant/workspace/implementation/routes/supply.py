"""Supply intake: chassis receipts and component lots."""
import constants as C
import db
import validation as V
from db import store
from errors import bad_request
from flask import Blueprint
from middleware import authorize
from routes.common import insert, list_out, must_find, object_out

bp = Blueprint("supply", __name__)


# ---------------------------------------------------------------------------
# chassis receipts
# ---------------------------------------------------------------------------
@bp.post("/chassis-receipts")
@authorize("PlantAdmin")
def create_chassis_receipt():
    body = V.body_dict()
    supplier_id = V.field_string(body, "supplier_id", required=True, min_len=1)
    serial = V.field_string(body, "chassis_serial", required=True, min_len=1)
    chassis_class = V.field_enum(body, "chassis_class", C.CHASSIS_CLASSES, required=True)
    gvwr = V.field_int(body, "gvwr_lbs", required=True, minimum=1)
    wheelbase = V.field_int(body, "wheelbase_in", required=True, minimum=1)
    V.unique_or_400(store.chassis_receipts, "chassis_serial", serial, "chassis_serial")
    must_find("suppliers", supplier_id)
    row = db.new_row(
        {
            "supplier_id": supplier_id,
            "chassis_serial": serial,
            "chassis_class": chassis_class,
            "gvwr_lbs": gvwr,
            "wheelbase_in": wheelbase,
            "received_at": db.now(),
            "matched_unit_order_id": None,
            "status": "RECEIVED",
        }
    )
    insert("chassis_receipts", row)
    return object_out("chassis_receipts", row, 201)


@bp.get("/chassis-receipts/<row_id>")
@authorize("PlantAdmin", "ProductionScheduler")
def get_chassis_receipt(row_id):
    return object_out("chassis_receipts", must_find("chassis_receipts", row_id))


@bp.get("/chassis-receipts")
@authorize("PlantAdmin", "ProductionScheduler")
def list_chassis_receipts():
    supplier_id = V.query_string("supplier_id")
    matched = V.query_string("matched_unit_order_id")
    status = V.query_enum("status", ["RECEIVED", "MATCHED", "INSTALLED"])
    chassis_class = V.query_enum("chassis_class", C.CHASSIS_CLASSES)
    rows = list(store.chassis_receipts.values())
    if supplier_id is not None:
        rows = [r for r in rows if r["supplier_id"] == supplier_id]
    if matched is not None:
        rows = [r for r in rows if r.get("matched_unit_order_id") == matched]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if chassis_class is not None:
        rows = [r for r in rows if r["chassis_class"] == chassis_class]
    return list_out("chassis_receipts", rows)


# ---------------------------------------------------------------------------
# component lots
# ---------------------------------------------------------------------------
@bp.post("/component-lots")
@authorize("PlantAdmin")
def create_component_lot():
    body = V.body_dict()
    supplier_id = V.field_string(body, "supplier_id", required=True, min_len=1)
    part_number = V.field_string(body, "part_number", required=True, min_len=1)
    lot_code = V.field_string(body, "lot_code", required=True, min_len=1)
    category = V.field_enum(body, "category", C.COMPONENT_CATEGORIES, required=True)
    quantity = V.field_int(body, "quantity_received", required=True, minimum=1)
    for existing in store.component_lots.values():
        if (
            existing["supplier_id"] == supplier_id
            and existing["part_number"] == part_number
            and existing["lot_code"] == lot_code
        ):
            raise bad_request(
                "lot_code '{}' is already registered for this supplier and part number.".format(
                    lot_code
                )
            )
    supplier = must_find("suppliers", supplier_id)
    if category not in supplier["component_categories"]:
        raise bad_request(
            "Category '{}' is not among the supplier's approved component categories.".format(
                category
            )
        )
    row = db.new_row(
        {
            "supplier_id": supplier_id,
            "part_number": part_number,
            "lot_code": lot_code,
            "category": category,
            "quantity_received": quantity,
            "quantity_available": quantity,
            "quantity_installed": 0,
            "quantity_quarantined": 0,
            "status": "AVAILABLE",
        }
    )
    insert("component_lots", row)
    return object_out("component_lots", row, 201)


@bp.get("/component-lots/<row_id>")
@authorize("PlantAdmin", "LineSupervisor", "RecallCoordinator")
def get_component_lot(row_id):
    return object_out("component_lots", must_find("component_lots", row_id))


@bp.get("/component-lots")
@authorize("PlantAdmin", "LineSupervisor", "RecallCoordinator")
def list_component_lots():
    supplier_id = V.query_string("supplier_id")
    part_number = V.query_string("part_number")
    lot_code = V.query_string("lot_code")
    status = V.query_enum("status", ["AVAILABLE", "DEPLETED", "QUARANTINED"])
    rows = list(store.component_lots.values())
    if supplier_id is not None:
        rows = [r for r in rows if r["supplier_id"] == supplier_id]
    if part_number is not None:
        rows = [r for r in rows if r["part_number"] == part_number]
    if lot_code is not None:
        rows = [r for r in rows if r["lot_code"] == lot_code]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_out("component_lots", rows)
