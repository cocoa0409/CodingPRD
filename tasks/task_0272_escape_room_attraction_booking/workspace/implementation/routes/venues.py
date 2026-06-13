from flask import Blueprint

import errors
from errors import err
from db import db, new_id, now_iso
from middleware import require_roles, get_json
from response import created, ok
from services import validate as V
from services.entities import get_venue, ser_venue

bp = Blueprint("venues", __name__)


@bp.post("/venues")
def create_venue():
    require_roles({"PlatformAdmin"})
    body = get_json()
    name = V.req_str(body, "name")
    timezone_ = V.req_str(body, "timezone")
    open_m = V.req_int(body, "open_minute_of_day", min_v=0, max_v=1439)
    close_m = V.req_int(body, "close_minute_of_day", min_v=1, max_v=1440)
    if not (open_m < close_m):
        raise err(errors.ERR_INVALID_REQUEST, "open_minute_of_day must be < close_minute_of_day")
    no_show_fee_pct = V.opt_number(body, "no_show_fee_pct", default=0.5, min_v=0.0, max_v=1.0)
    no_show_strike_limit = V.opt_int(body, "no_show_strike_limit", default=3, min_v=1)

    ts = now_iso()
    vid = new_id()
    venue = {
        "id": vid,
        "name": name,
        "timezone": timezone_,
        "open_minute_of_day": open_m,
        "close_minute_of_day": close_m,
        "no_show_fee_pct": no_show_fee_pct,
        "no_show_strike_limit": no_show_strike_limit,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.venues[vid] = venue
    return created(ser_venue(venue))


@bp.get("/venues/<venue_id>")
def read_venue(venue_id):
    require_roles({"PlatformAdmin", "VenueManager", "GameMaster", "Customer"})
    venue = get_venue(venue_id)
    return ok(ser_venue(venue))
