"""OpsAdmin test-driving endpoints: logical clock + ops sweep."""

from flask import Blueprint

import errors
import validate as V
from db import DB, clock_now, parse_dt
from middleware import require_role
from response import success_object
from services.show import touch, revoke_authorization_cascade

bp = Blueprint("ops", __name__)


@bp.route("/api/_clock/set_current_utc", methods=["POST"])
def set_clock():
    body = V.get_body()
    V.reject_system_fields(body)
    V.req_fields(body, ["to_iso8601"])
    require_role("OpsAdmin")
    raw, _dt = V.req_dt(body, "to_iso8601")
    # "the response echoes the new reading" — preserve the client's spelling
    DB.clock = raw
    return success_object({"current_utc": DB.clock})


@bp.route("/api/_ops/run_sweep", methods=["POST"])
def run_sweep():
    body = V.get_body()
    V.reject_system_fields(body)
    require_role("OpsAdmin")
    now = clock_now()
    expired_ids = []
    downgraded_show_ids = []
    for aid in DB.insertion_order["authorizations"]:
        a = DB.authorizations[aid]
        if a["status"] == "APPROVED" and parse_dt(a["window_end"]) < now:
            a["status"] = "EXPIRED"
            touch(a)
            expired_ids.append(a["id"])
            # cascade: shows pinning this auth drop to PLANNING
            from services.show import downgrade_show_to_planning
            for sid in DB.insertion_order["show_events"]:
                s = DB.show_events[sid]
                if s.get("pinned_authorization_id") == a["id"] and s["lifecycle_status"] in (
                        "DESIGN_LOCKED", "AUTHORIZED", "READY", "GO_CERTIFIED"):
                    downgrade_show_to_planning(s)
                    if s["id"] not in downgraded_show_ids:
                        downgraded_show_ids.append(s["id"])
    return success_object({
        "expired_authorization_ids": expired_ids,
        "downgraded_show_ids": downgraded_show_ids,
    })
