"""Clock + ops epoch endpoints (SystemAdmin)."""
from flask import Blueprint

import clock
import db
import middleware as mw
import response as resp
import serializers as ser
import services as svc
from errors import err_invalid_request

bp = Blueprint("ops", __name__)

ROLE_SYSADMIN = ["SystemAdmin"]


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    caller = mw.authenticate()
    mw.authorize(caller, ROLE_SYSADMIN)
    body = mw.get_json_body(required=True)
    to = mw.req_datetime(body, "to_iso8601")
    now_iso = clock.set_to(to.isoformat())
    return resp.ok({"now_iso8601": now_iso})


@bp.route("/ops/run_epoch", methods=["POST"])
def run_epoch():
    caller = mw.authenticate()
    mw.authorize(caller, ROLE_SYSADMIN)
    today = clock.today_date()

    activated = 0
    lifted = 0
    expired_contracts = 0
    completed_supply = 0
    defaulted_supply = 0
    shipments_cancelled = 0

    # Cold snaps: activate DECLARED with start_date <= today (skip if the
    # terminal already has an ACTIVE event — the no-double-activation rule)
    for e in list(db.cold_snap_events.values()):
        if e["status"] == "DECLARED" and e["start_date"] <= today:
            terminal = db.terminals[e["terminal_id"]]
            if any(
                other["id"] != e["id"]
                and other["terminal_id"] == e["terminal_id"]
                and other["status"] == "ACTIVE"
                for other in db.cold_snap_events.values()
            ):
                continue
            e["status"] = "ACTIVE"
            svc.touch(e)
            svc.terminal_curtail(terminal)
            activated += 1

    # Lift ACTIVE with end_date < today
    for e in list(db.cold_snap_events.values()):
        if e["status"] == "ACTIVE" and e["end_date"] < today:
            terminal = db.terminals[e["terminal_id"]]
            e["status"] = "LIFTED"
            svc.touch(e)
            svc.terminal_restore(terminal)
            lifted += 1

    # Expire ACTIVE dealer contracts whose window_end has passed
    for c in list(db.dealer_contracts.values()):
        if c["status"] == "ACTIVE" and c["window_end"] < today:
            c["status"] = "EXPIRED"
            svc.touch(c)
            expired_contracts += 1

    # Settle ACTIVE supply contracts whose receipt window has passed
    for c in list(db.supply_contracts.values()):
        if c["status"] == "ACTIVE" and c["receipt_window_end"] < today:
            if c["delivered_volume_gal"] >= c["contracted_volume_gal"]:
                c["status"] = "COMPLETED"
                completed_supply += 1
            else:
                c["status"] = "DEFAULTED"
                defaulted_supply += 1
            svc.touch(c)
            # cancel its TENDERED / IN_TRANSIT shipments
            for s in db.rail_shipments.values():
                if s["supply_contract_id"] == c["id"] and s["status"] in ("TENDERED", "IN_TRANSIT"):
                    s["status"] = "CANCELLED"
                    svc.touch(s)
                    shipments_cancelled += 1

    # Every terminal's ops_epoch increments (bumps version)
    for t in db.terminals.values():
        t["ops_epoch"] += 1
        svc.touch(t)

    return resp.ok(
        {
            "cold_snaps_activated": activated,
            "cold_snaps_lifted": lifted,
            "dealer_contracts_expired": expired_contracts,
            "supply_contracts_completed": completed_supply,
            "supply_contracts_defaulted": defaulted_supply,
            "shipments_cancelled": shipments_cancelled,
        }
    )
