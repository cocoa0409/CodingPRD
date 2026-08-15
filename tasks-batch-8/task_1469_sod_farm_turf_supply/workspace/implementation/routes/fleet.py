"""Truck blocks (fleet holds) and the test-driving logical clock."""
from flask import Blueprint, request

import calc
import db
from auth import require_roles
from db import common_fields
from errors import (err, ERR_CAPACITY_EXCEEDED, ERR_INVALID_REQUEST)
from serialize import pub_truck_block
from util import (as_int, as_str, body, ok, ok_list, paged, pagination,
                  parse_dt, require, sort_created)

bp = Blueprint("fleet", __name__)


@bp.route("/truck-blocks", methods=["POST"])
def create_truck_block():
    require_roles("FleetManager")
    payload = body()
    zone = as_int(require(payload, "freight_zone"), "freight_zone", minimum=1, maximum=3)
    window_start = parse_dt(require(payload, "window_start"), "window_start")
    window_end = parse_dt(require(payload, "window_end"), "window_end")
    if (window_start.minute != 0 or window_start.second != 0
            or window_start.microsecond != 0):
        raise err(ERR_INVALID_REQUEST, "window_start must be hour-aligned")
    if window_end <= window_start:
        raise err(ERR_INVALID_REQUEST, "window_end must be after window_start")
    reason = ""
    if payload.get("reason") is not None:
        reason = as_str(payload["reason"], "reason")
    cfg = calc.config_or_defaults(calc.current_config())
    if calc.zone_consumers(zone, window_start, window_end) >= int(cfg["zone_truck_capacity"]):
        raise err(ERR_CAPACITY_EXCEEDED, "zone truck capacity reached for this window")
    block = common_fields()
    block.update({
        "freight_zone": zone,
        "window_start": window_start,
        "window_end": window_end,
        "reason": reason,
    })
    db.store.truck_blocks[block["id"]] = block
    return ok(pub_truck_block(block), 201)


@bp.route("/truck-blocks", methods=["GET"])
def list_truck_blocks():
    require_roles("FleetManager", "FarmManager")
    limit, offset = pagination()
    zone = request.args.get("freight_zone")
    items = sort_created(db.store.truck_blocks.values())
    if zone is not None:
        try:
            zone_int = int(zone)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "freight_zone filter must be an integer")
        items = [t for t in items if t["freight_zone"] == zone_int]
    page, total = paged(items, limit, offset)
    return ok_list([pub_truck_block(t) for t in page], total, limit, offset)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("FarmManager")
    payload = body()
    target = parse_dt(require(payload, "to_iso8601"), "to_iso8601")
    db.store.clock = target
    return ok({}, 200)
