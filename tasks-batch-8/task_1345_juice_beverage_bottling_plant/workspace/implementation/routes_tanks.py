"""BlendingTank endpoints including clean-in-place."""
from datetime import timedelta

from flask import Blueprint

from domain import (ALLERGEN_CIP_HOURS, STANDARD_CIP_HOURS, ser_batch, ser_tank)
from errors import err
from store import db, stamp, touch, trunc_minute
from util import body, ok, paginate, req_field, require_any, require_roles

bp = Blueprint("tanks", __name__)


def get_tank_or_404(tank_id):
    tank = db.tanks.get(tank_id)
    if tank is None:
        raise err("ERR_TANK_NOT_FOUND", f"BlendingTank {tank_id} not found")
    return tank


@bp.post("/v1/blending-tanks")
def create_tank():
    require_roles("PlantManager")
    data = body()
    tank_code = req_field(data, "tank_code", "str")
    capacity_liters = req_field(data, "capacity_liters", "int")
    tank = {
        "tank_code": tank_code,
        "capacity_liters": capacity_liters,
        "allergen_group": "NONE",
        "posture": "AVAILABLE",
        "occupying_batch_id": None,
        "cip_started_at": None,
        "cip_required_hours": None,
        "_cip_started_dt": None,
    }
    stamp(tank)
    db.tanks[tank["id"]] = tank
    return ok(ser_tank(tank), 201)


@bp.get("/v1/blending-tanks")
def list_tanks():
    require_any()
    return paginate(list(db.tanks.values()), ser_tank)


@bp.get("/v1/blending-tanks/<tank_id>")
def get_tank(tank_id):
    require_any()
    return ok(ser_tank(get_tank_or_404(tank_id)))


@bp.post("/v1/blending-tanks/<tank_id>/start-cip")
def start_cip(tank_id):
    require_roles("BlendOperator")
    tank = get_tank_or_404(tank_id)
    if tank["posture"] != "AWAITING_CIP":
        raise err("ERR_TANK_STATE_INVALID", "start-cip requires posture AWAITING_CIP")
    tank["posture"] = "IN_CIP"
    from store import iso_ms
    tank["cip_started_at"] = iso_ms(db.clock)
    tank["_cip_started_dt"] = db.clock
    tank["cip_required_hours"] = (ALLERGEN_CIP_HOURS
                                  if tank["allergen_group"] != "NONE"
                                  else STANDARD_CIP_HOURS)
    touch(tank)
    return ok(ser_tank(tank))


@bp.post("/v1/blending-tanks/<tank_id>/complete-cip")
def complete_cip(tank_id):
    require_roles("BlendOperator")
    tank = get_tank_or_404(tank_id)
    if tank["posture"] != "IN_CIP":
        raise err("ERR_TANK_STATE_INVALID", "complete-cip requires posture IN_CIP")
    ready_at = trunc_minute(tank["_cip_started_dt"]) + timedelta(hours=tank["cip_required_hours"])
    if trunc_minute(db.clock) < ready_at:
        raise err("ERR_CIP_DURATION_INSUFFICIENT",
                  "CIP has not yet run for the required duration")
    tank["posture"] = "AVAILABLE"
    tank["allergen_group"] = "NONE"
    tank["cip_started_at"] = None
    tank["_cip_started_dt"] = None
    touch(tank)
    return ok(ser_tank(tank))


@bp.get("/v1/blending-tanks/<tank_id>/batches")
def tank_batches(tank_id):
    require_any()
    get_tank_or_404(tank_id)
    items = [b for b in db.batches.values() if b["tank_id"] == tank_id]
    return paginate(items, ser_batch)
