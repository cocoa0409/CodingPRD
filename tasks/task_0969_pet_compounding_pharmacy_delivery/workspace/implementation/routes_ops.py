from datetime import timedelta

from flask import Blueprint

import db
from errors import ApiError
from middleware import auth, body
from response import success
from services import (create_compound_order, cancel_schedules_for_prescription,
                      update_lot_exhaustion)
from util import (touch, req, as_datetime_str, parse_datetime, parse_date,
                  clock_date, now_iso)

bp = Blueprint("ops", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth("PharmacyAdmin")
    d = body()
    to_iso = as_datetime_str(req(d, "to_iso8601"), "to_iso8601")
    db.set_clock(parse_datetime(to_iso))
    return success({}, 200)


@bp.route("/_ops/auto_ship_run", methods=["POST"])
def auto_ship_run():
    auth("PharmacyAdmin")
    today = clock_date()
    due = sorted(
        (s for s in db.auto_ship_schedules.values()
         if s["status"] == "ACTIVE"
         and parse_date(s["next_run_date"]) is not None
         and parse_date(s["next_run_date"]) <= today),
        key=lambda s: s["_seq"])
    for s in due:
        rx = db.prescriptions.get(s["prescription_id"])
        try:
            if rx is None:
                raise ApiError("ERR_NOT_FOUND", "prescription not found", 404)
            create_compound_order(rx, None, True)
        except ApiError:
            s["consecutive_failures"] += 1
            if s["consecutive_failures"] >= 3:
                s["status"] = "PAUSED"
        else:
            s["next_run_date"] = (parse_date(s["next_run_date"])
                                  + timedelta(days=s["interval_days"])).isoformat()
            s["consecutive_failures"] = 0
            s["last_fired_at"] = now_iso()
        touch(s)
    return success({}, 200)


@bp.route("/_ops/expiration_sweep", methods=["POST"])
def expiration_sweep():
    auth("PharmacyAdmin")
    today = clock_date()
    # expire lots
    for lot in sorted(db.lots.values(), key=lambda l: l["_seq"]):
        if lot["status"] != "ACTIVE":
            continue
        exp = parse_date(lot["expiration_date"])
        if exp is None or exp >= today:
            continue
        lot["status"] = "EXPIRED"
        for a in sorted(db.lot_allocations.values(), key=lambda x: x["_seq"]):
            if a["lot_id"] == lot["id"] and a["status"] == "RESERVED":
                a["status"] = "RELEASED"
                touch(a)
                lot["qty_reserved"] -= a["qty_allocated"]
                lot["qty_on_hand"] += a["qty_allocated"]
        touch(lot)
    # revert under-allocated orders back to CREATED
    for order in sorted(db.compound_orders.values(), key=lambda o: o["_seq"]):
        if order["status"] != "ALLOCATED":
            continue
        covered = sum(a["qty_allocated"] for a in db.lot_allocations.values()
                      if a["compound_order_id"] == order["id"]
                      and a["status"] == "RESERVED")
        if covered < order["quantity_snapshot"]:
            order["status"] = "CREATED"
            touch(order)
    # expire prescriptions
    for rx in sorted(db.prescriptions.values(), key=lambda r: r["_seq"]):
        if rx["status"] != "VERIFIED":
            continue
        exp = parse_date(rx["expiration_date"])
        if exp is None or exp >= today:
            continue
        rx["status"] = "EXPIRED"
        cancel_schedules_for_prescription(rx["id"])
        touch(rx)
    return success({}, 200)
