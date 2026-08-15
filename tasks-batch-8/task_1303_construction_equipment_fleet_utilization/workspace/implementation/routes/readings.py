from flask import Blueprint

from db import new_sub, pub, store, touch
from errors import ApiError, not_found
from logic import eval_threshold_after_accept, eval_threshold_after_void
from middleware import require_roles
from response import ok
from util import as_date, as_int, as_str, body_json, req_field

bp = Blueprint("readings", __name__)


@bp.post("/fleet/equipment/<eid>/readings")
@require_roles("FleetAdmin")
def ingest_reading(eid):
    e = store.equipment.get(eid)
    if e is None:
        raise not_found("Equipment")
    body = body_json()
    rec_d, rec_raw = as_date(req_field(body, "recorded_date"), "recorded_date")
    delta = as_int(req_field(body, "engine_hours_delta_milli"), "engine_hours_delta_milli",
                   minimum=0, maximum=24000)
    fuel = as_int(req_field(body, "fuel_used_milliliters"), "fuel_used_milliliters", minimum=0)
    dup = any(r for r in store.readings.values()
              if r["equipment_id"] == e["id"] and r["recorded_date"] == rec_raw
              and r["status"] == "ACCEPTED")
    if dup:
        raise ApiError("ERR_DUPLICATE_READING", 409,
                       "An ACCEPTED reading already exists for this unit and recorded_date")
    r = new_sub()
    r.update({
        "equipment_id": e["id"],
        "recorded_date": rec_raw,
        "engine_hours_delta_milli": delta,
        "fuel_used_milliliters": fuel,
        "status": "ACCEPTED",
        "void_reason": None,
    })
    store.readings[r["id"]] = r
    changed = False
    if delta != 0:
        e["engine_hours_milli"] += delta
        changed = True
    if eval_threshold_after_accept(e):
        changed = True
    if changed:
        touch(e)
    return ok(pub(r), "object", 201)


@bp.post("/fleet/readings/<rid>/void")
@require_roles("FleetAdmin")
def void_reading(rid):
    r = store.readings.get(rid)
    if r is None:
        raise not_found("TelematicsReading")
    body = body_json()
    reason = as_str(req_field(body, "void_reason"), "void_reason")
    if r["status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only an ACCEPTED reading can be voided")
    r["status"] = "VOIDED"
    r["void_reason"] = reason
    e = store.equipment[r["equipment_id"]]
    changed = False
    if r["engine_hours_delta_milli"] != 0:
        e["engine_hours_milli"] -= r["engine_hours_delta_milli"]
        changed = True
    if eval_threshold_after_void(e):
        changed = True
    if changed:
        touch(e)
    return ok(pub(r), "object", 200)
