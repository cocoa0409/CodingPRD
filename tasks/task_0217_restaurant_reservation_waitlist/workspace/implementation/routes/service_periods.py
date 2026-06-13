"""ServicePeriod routes (PRD §3.1, §2.5)."""
from flask import Blueprint, request

import db
from errors import err, ERR_VALIDATION
from middleware import require_roles
from response import object_response, array_response
from services.lookup import get_or_404
from validators import (
    get_body, require_str, require_time_str, opt_int, require_int, paginate,
)

bp = Blueprint("service_periods", __name__)


def _hhmm(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


@bp.post("/service-periods")
def create_service_period():
    require_roles({"Manager"})
    body = get_body()
    restaurant_id = require_str(body, "restaurant_id")
    get_or_404(db.restaurants, restaurant_id)
    name = require_str(body, "name")
    start_local = require_time_str(body, "start_local_time")
    end_local = require_time_str(body, "end_local_time")
    if _hhmm(end_local) <= _hhmm(start_local):
        raise err(ERR_VALIDATION, "end_local_time must be strictly after start_local_time")
    slot_interval = opt_int(body, "slot_interval_minutes", 30)
    if slot_interval not in (15, 30, 60):
        raise err(ERR_VALIDATION, "slot_interval_minutes must be one of 15, 30, 60")
    pacing = require_int(body, "pacing_max_covers_per_slot", minimum=1)

    rec = db.base_fields()
    rec.update({
        "restaurant_id": restaurant_id,
        "name": name,
        "start_local_time": start_local,
        "end_local_time": end_local,
        "slot_interval_minutes": slot_interval,
        "pacing_max_covers_per_slot": pacing,
    })
    db.service_periods[rec["id"]] = rec
    return object_response(db.serialize(rec), 201)


@bp.get("/service-periods/<sid>")
def read_service_period(sid):
    require_roles({"Manager", "Host", "Customer"})
    rec = get_or_404(db.service_periods, sid)
    return object_response(db.serialize(rec), 200)


@bp.get("/service-periods")
def list_service_periods():
    require_roles({"Manager", "Host", "Customer"})
    restaurant_id = request.args.get("restaurant_id")
    records = [s for s in db.service_periods.values()
               if restaurant_id is None or s["restaurant_id"] == restaurant_id]
    page, pagination = paginate(records)
    return array_response([db.serialize(r) for r in page], pagination, 200)
