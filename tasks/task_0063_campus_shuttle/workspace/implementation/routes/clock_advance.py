"""Clock advance endpoint — fires deferred transitions (vehicle maintenance auto-complete)."""
from flask import Blueprint

import db
from clock import set_now, now, iso
from errors import err
from middleware import require_auth, get_json_body
from response import success
from services.util import parse_dt


bp = Blueprint("clock_advance", __name__)


@bp.route("/shuttle/_clock/advance", methods=["POST"])
@require_auth(roles={"Dispatcher", "Auditor"})
def advance_clock():
    body = get_json_body()
    to_ts = body.get("to_timestamp")
    if not isinstance(to_ts, str) or not to_ts:
        raise err("ERR_VALIDATION", "to_timestamp is required")
    new_dt = parse_dt(to_ts, "to_timestamp")
    set_now(new_dt)

    # Vehicle MAINTENANCE -> ACTIVE when maintenance_window_end <= new clock
    n = now()
    transitions = []
    for v in db.vehicles.values():
        if v.get("status") != "MAINTENANCE":
            continue
        me = v.get("maintenance_window_end")
        if not me:
            continue
        try:
            me_dt = parse_dt(me)
        except Exception:
            continue
        if me_dt <= n:
            v["status"] = "ACTIVE"
            v["maintenance_window_start"] = None
            v["maintenance_window_end"] = None
            db.stamp_update(v)
            transitions.append({"vehicle_id": v["id"]})

    return success({
        "clock": iso(n),
        "transitions": transitions,
    })
