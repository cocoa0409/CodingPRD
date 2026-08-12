"""Mill endpoints."""
from flask import Blueprint

from .domain import MILL_BUSY_STATES, ser_batch, ser_mill
from .errors import conflict, invalid_state, not_found
from .store import store
from .util import auth, body, list_response, new_record, success, touch, v_int, v_str

bp = Blueprint("mills", __name__)

ALL = ("PlantManager", "LabTechnician", "ProductionOperator", "QCInspector", "RegulatoryClerk", "Dealer")


@bp.post("/coatings/mills")
def create_mill():
    auth(("PlantManager",))
    b = body()
    mill_code = v_str(b, "mill_code")
    capacity = v_int(b, "capacity_gallons", minv=1)
    for m in store.mills.values():
        if m["mill_code"] == mill_code:
            raise conflict("ERR_DUPLICATE_CODE", "mill_code already exists")
    rec = new_record()
    rec.update({"mill_code": mill_code, "capacity_gallons": capacity, "status": "ACTIVE"})
    store.mills[rec["id"]] = rec
    return success(ser_mill(rec), 201)


@bp.get("/coatings/mills/<mid>")
def get_mill(mid):
    auth(ALL)
    rec = store.mills.get(mid)
    if rec is None:
        raise not_found()
    return success(ser_mill(rec), 200)


@bp.post("/coatings/mills/<mid>/enter-maintenance")
def enter_maintenance(mid):
    auth(("PlantManager",))
    rec = store.mills.get(mid)
    if rec is None:
        raise not_found()
    if rec["status"] != "ACTIVE":
        raise invalid_state("Mill is not ACTIVE")
    for b in store.batches.values():
        if b["mill_id"] == mid and b["status"] in MILL_BUSY_STATES:
            raise conflict("ERR_MILL_BUSY", "Mill has in-flight batches")
    rec["status"] = "MAINTENANCE"
    touch(rec)
    return success(ser_mill(rec), 200)


@bp.post("/coatings/mills/<mid>/return-to-service")
def return_to_service(mid):
    auth(("PlantManager",))
    rec = store.mills.get(mid)
    if rec is None:
        raise not_found()
    if rec["status"] != "MAINTENANCE":
        raise invalid_state("Mill is not in MAINTENANCE")
    rec["status"] = "ACTIVE"
    touch(rec)
    return success(ser_mill(rec), 200)


@bp.get("/coatings/mills/<mid>/batches")
def mill_batches(mid):
    auth(ALL)
    if mid not in store.mills:
        raise not_found()
    recs = [b for b in store.batches.values() if b["mill_id"] == mid]
    return list_response(recs, ser_batch)
