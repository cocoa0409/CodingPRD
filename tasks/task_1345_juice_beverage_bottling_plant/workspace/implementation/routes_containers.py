"""ContainerLot endpoints."""
from flask import Blueprint, request

from domain import CONTAINER_TYPES, ser_container_lot
from errors import err
from store import db, stamp, touch
from util import body, ok, paginate, req_enum, req_field, require_any, require_roles

bp = Blueprint("container_lots", __name__)


def get_container_lot_or_404(lot_id):
    lot = db.container_lots.get(lot_id)
    if lot is None:
        raise err("ERR_CONTAINER_LOT_NOT_FOUND", f"ContainerLot {lot_id} not found")
    return lot


@bp.post("/v1/container-lots")
def create_container_lot():
    require_roles("WarehouseLead")
    data = body()
    container_type = req_enum(data, "container_type", CONTAINER_TYPES)
    quantity_received = req_field(data, "quantity_received", "int")
    supplier_lot_code = req_field(data, "supplier_lot_code", "str")
    lot = {
        "container_type": container_type,
        "quantity_received": quantity_received,
        "supplier_lot_code": supplier_lot_code,
        "quantity_reserved": 0,
        "quantity_consumed": 0,
        "status": "RECEIVED",
    }
    stamp(lot)
    db.container_lots[lot["id"]] = lot
    return ok(ser_container_lot(lot), 201)


@bp.get("/v1/container-lots")
def list_container_lots():
    require_any()
    container_type = request.args.get("container_type")
    status = request.args.get("status")
    items = list(db.container_lots.values())
    if container_type is not None:
        items = [l for l in items if l["container_type"] == container_type]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    return paginate(items, ser_container_lot)


@bp.get("/v1/container-lots/<lot_id>")
def get_container_lot(lot_id):
    require_any()
    return ok(ser_container_lot(get_container_lot_or_404(lot_id)))


@bp.post("/v1/container-lots/<lot_id>/qc-verdict")
def container_qc_verdict(lot_id):
    require_roles("QAInspector")
    lot = get_container_lot_or_404(lot_id)
    data = body()
    verdict = req_field(data, "verdict", "str")
    if verdict not in ("PASS", "FAIL"):
        raise err("ERR_INVALID_REQUEST", "verdict must be PASS or FAIL")
    if lot["status"] != "RECEIVED":
        raise err("ERR_CONTAINER_LOT_STATE_INVALID", "qc-verdict requires status RECEIVED")
    lot["status"] = "QC_PASSED" if verdict == "PASS" else "QC_FAILED"
    touch(lot)
    return ok(ser_container_lot(lot))


@bp.post("/v1/container-lots/<lot_id>/return")
def return_container_lot(lot_id):
    require_roles("WarehouseLead")
    lot = get_container_lot_or_404(lot_id)
    if lot["status"] != "QC_FAILED" or lot["quantity_reserved"] != 0 or lot["quantity_consumed"] != 0:
        raise err("ERR_CONTAINER_LOT_STATE_INVALID",
                  "return requires a QC_FAILED lot with zero reserved and consumed")
    lot["status"] = "RETURNED"
    touch(lot)
    return ok(ser_container_lot(lot))
