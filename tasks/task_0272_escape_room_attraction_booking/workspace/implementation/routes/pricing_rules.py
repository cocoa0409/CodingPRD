from flask import Blueprint, request

import errors
from errors import err
from db import db, new_id, now_iso
from middleware import require_roles, get_json
from response import created, ok, listing
from services import validate as V
from services.entities import get_venue, get_room, get_pricing_rule, ser_pricing_rule

bp = Blueprint("pricing_rules", __name__)


@bp.post("/pricing-rules")
def create_pricing_rule():
    require_roles({"VenueManager"})
    body = get_json()
    # Named body references first, resolved before other scalar validation
    # (PRD §2.9: existence precedes request-shape).
    venue_id = V.req_str(body, "venue_id")
    room_id = V.req_str(body, "room_id")
    get_venue(venue_id)
    get_room(room_id)

    peak_dow_mask = V.req_int(body, "peak_dow_mask", min_v=0, max_v=127)
    peak_start = V.req_int(body, "peak_start_minute_of_day", min_v=0, max_v=1439)
    peak_end = V.req_int(body, "peak_end_minute_of_day", min_v=1, max_v=1440)
    large_group_threshold = V.req_int(body, "large_group_threshold", min_v=1)
    peak_multiplier_bps = V.opt_int(body, "peak_multiplier_bps", default=10000, min_v=10000)
    large_group_multiplier_bps = V.opt_int(body, "large_group_multiplier_bps", default=10000, min_v=10000)
    if not (peak_start < peak_end):
        raise err(errors.ERR_INVALID_REQUEST, "peak_start_minute_of_day must be < peak_end_minute_of_day")

    ts = now_iso()
    pid = new_id()
    rule = {
        "id": pid,
        "venue_id": venue_id,
        "room_id": room_id,
        "peak_dow_mask": peak_dow_mask,
        "peak_start_minute_of_day": peak_start,
        "peak_end_minute_of_day": peak_end,
        "peak_multiplier_bps": peak_multiplier_bps,
        "large_group_threshold": large_group_threshold,
        "large_group_multiplier_bps": large_group_multiplier_bps,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.pricing_rules[pid] = rule
    return created(ser_pricing_rule(rule))


@bp.get("/pricing-rules/<pricing_rule_id>")
def read_pricing_rule(pricing_rule_id):
    require_roles({"PlatformAdmin", "VenueManager", "Customer"})
    rule = get_pricing_rule(pricing_rule_id)
    return ok(ser_pricing_rule(rule))


@bp.get("/pricing-rules")
def list_pricing_rules():
    require_roles({"PlatformAdmin", "VenueManager", "Customer"})
    limit, offset = V.parse_pagination()
    venue_id = request.args.get("venue_id")
    room_id = request.args.get("room_id")
    rows = list(db.pricing_rules.values())
    if venue_id is not None:
        rows = [r for r in rows if r["venue_id"] == venue_id]
    if room_id is not None:
        rows = [r for r in rows if r["room_id"] == room_id]
    page, total = V.paginate(rows, limit, offset)
    return listing([ser_pricing_rule(r) for r in page], limit, offset, total)
