"""Stop endpoints (PRD §3.1)."""

from flask import Blueprint, request

from db import DB
from middleware import authenticate, require_role
from response import ok, ok_list
from errors import (
    err, ERR_INVALID_REQUEST, ERR_INVALID_REFERENCE, ERR_DUPLICATE,
    ERR_STOP_TIME_ORDER,
)
from services import validate as v
from services.common import (
    stamp_create, parse_pagination, sorted_by_creation, paginate,
)
from services.calc import parse_iso
from services.domain import stop_public
from services.lookup import get_stop

bp = Blueprint("stops", __name__)


@bp.post("/stops")
def create_stop():
    p = authenticate()
    require_role(p, {"TransportAdmin"})
    body = v.get_body()

    route_id = v.require_str(body, "route_id")
    label = v.require_str(body, "label")
    lat = v.require_number(body, "lat")
    lng = v.require_number(body, "lng")
    sequence = v.require_int(body, "sequence")
    if sequence < 1:
        raise err(ERR_INVALID_REQUEST, "sequence must be >= 1")
    scheduled_departure = v.require_str(body, "scheduled_departure")

    # Body FK resolution — priority 5.
    if route_id not in DB.routes:
        raise err(ERR_INVALID_REFERENCE, "route_id does not resolve")

    existing = [s for s in DB.stops.values() if s["route_id"] == route_id]

    # Uniqueness of sequence within route — priority 6.
    for s in existing:
        if s["sequence"] == sequence:
            raise err(ERR_DUPLICATE, "Stop.sequence already used on this Route")

    # Strictly-increasing stop-time timeline — priority 6.5.
    new_dep = parse_iso(scheduled_departure)
    for s in existing:
        s_dep = parse_iso(s["scheduled_departure"])
        if s["sequence"] < sequence and not (s_dep < new_dep):
            raise err(ERR_STOP_TIME_ORDER, "scheduled_departure must be after lower-sequence stops")
        if s["sequence"] > sequence and not (new_dep < s_dep):
            raise err(ERR_STOP_TIME_ORDER, "scheduled_departure must be before higher-sequence stops")

    rec = {
        "route_id": route_id,
        "label": label,
        "lat": lat,
        "lng": lng,
        "sequence": sequence,
        "scheduled_departure": scheduled_departure,
    }
    stamp_create(rec)
    DB.stops[rec["id"]] = rec
    return ok(stop_public(rec), 201)


@bp.get("/stops")
def list_stops():
    p = authenticate()
    require_role(p, {"TransportAdmin", "Parent", "Driver"})
    limit, offset = parse_pagination(request.args)

    route_id = request.args.get("route_id")
    records = list(DB.stops.values())
    if route_id is not None:
        records = [s for s in records if s["route_id"] == route_id]

    records = sorted_by_creation(records)
    page, total = paginate(records, limit, offset)
    return ok_list([stop_public(s) for s in page], limit, offset, total)


@bp.get("/stops/<stop_id>")
def get_stop_ep(stop_id):
    p = authenticate()
    require_role(p, {"TransportAdmin", "Parent", "Driver"})
    rec = get_stop(stop_id)
    return ok(stop_public(rec), 200)
