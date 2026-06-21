"""DormancyWaiver create/read/list (PRD §3.8). Closed interval [start, end]."""

from flask import Blueprint, request

from db import db
from core import get_body, stamp_new, paginate, check_str, parse_iso
from errors import err
from middleware import get_identity, require_role
from response import success
from lookups import get_dormancy_waiver
import serialize

bp = Blueprint("waivers", __name__)


@bp.post("/v1/dormancy-waivers")
def create_waiver():
    _uid, role = get_identity()
    require_role(role, {"ProgramAdmin", "FraudAnalyst"})
    body = get_body()
    card_id = check_str(body, "card_id")
    window_start = check_str(body, "window_start")
    window_end = check_str(body, "window_end")

    # Body FK existence (priority 5).
    if card_id not in db.cards:
        raise err("ERR_REFERENCE_NOT_FOUND", "card_id does not exist.")

    try:
        new_start = parse_iso(window_start)
        new_end = parse_iso(window_end)
    except (ValueError, TypeError):
        raise err("ERR_VALIDATION", "window_start/window_end must be ISO 8601.")

    # Overlap with an existing ACTIVE waiver on the same card (priority 12).
    # Closed intervals overlap iff new_start <= ex_end and ex_start <= new_end.
    for w in db.dormancy_waivers.values():
        if w["card_id"] != card_id or w["status"] != "ACTIVE":
            continue
        ex_start = parse_iso(w["window_start"])
        ex_end = parse_iso(w["window_end"])
        if new_start <= ex_end and ex_start <= new_end:
            raise err("ERR_WAIVER_OVERLAP", "Waiver overlaps an existing ACTIVE waiver.")

    w = {
        "card_id": card_id,
        "window_start": window_start,
        "window_end": window_end,
        "status": "ACTIVE",
    }
    stamp_new(w)
    db.dormancy_waivers[w["id"]] = w
    return success(serialize.dormancy_waiver(w), status=201)


@bp.get("/v1/dormancy-waivers/<waiver_id>")
def read_waiver(waiver_id):
    _uid, role = get_identity()
    require_role(role, {"ProgramAdmin", "FraudAnalyst", "StoreAssociate"})
    w = get_dormancy_waiver(waiver_id)
    return success(serialize.dormancy_waiver(w))


@bp.get("/v1/dormancy-waivers")
def list_waivers():
    _uid, role = get_identity()
    require_role(role, {"ProgramAdmin", "FraudAnalyst", "StoreAssociate"})
    items = list(db.dormancy_waivers.values())
    for key in ("card_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [w for w in items if w.get(key) == val]
    page, pg = paginate(items)
    return success([serialize.dormancy_waiver(w) for w in page], pagination=pg)
