"""Cooler inventory endpoints."""
from flask import Blueprint, request

from db import DB, new_id
from middleware import auth
from response import ok
from services import get_cooler, ser_cooler, ser_reservation, stamp
from util import as_int, as_str, body, paginate, reject_unknown, required

bp = Blueprint("coolers", __name__)


@bp.post("/api/coolers")
def create_cooler():
    auth(["DispatchAdmin"])
    data = body()
    reject_unknown(data, {"label", "capacity_liters"})
    label = as_str(required(data, "label"), "label")
    capacity_liters = as_int(
        required(data, "capacity_liters"), "capacity_liters", minimum=1
    )
    rec = {
        "id": new_id(),
        "label": label,
        "capacity_liters": capacity_liters,
        "status": "AVAILABLE",
        "cleaning_ends_at": None,
    }
    stamp(rec)
    DB["coolers"][rec["id"]] = rec
    return ok(ser_cooler(rec), status=201)


@bp.get("/api/coolers/<cid>")
def get_one_cooler(cid):
    auth(["DispatchAdmin"])
    return ok(ser_cooler(get_cooler(cid)))


@bp.get("/api/coolers/<cid>/cooler-reservations")
def list_cooler_reservations(cid):
    auth(["DispatchAdmin"])
    cooler = get_cooler(cid)
    items = [r for r in DB["reservations"].values() if r["cooler_id"] == cooler["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return paginate(items, ser_reservation)
