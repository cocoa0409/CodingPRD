from flask import Blueprint

import db
import core
import ser
import find
import cascade
from core import ApiError

bp = Blueprint("holds", __name__)


@bp.post("/clients/<cid>/vacation-holds")
@core.require_auth(["IntakeCoordinator"])
def create_hold(cid):
    body = core.get_body()
    start_date = core.require_field(body, "start_date", "str")
    end_date = core.require_field(body, "end_date", "str")

    start_d = core.parse_date(start_date)
    end_d = core.parse_date(end_date)
    if start_d is None or end_d is None:
        core.invalid_value("start_date/end_date must be valid dates")
    if end_d < start_d:
        core.invalid_value("end_date must be on or after start_date")

    client = find.client(cid)

    if client["enrollment_status"] != "ACTIVE":
        raise ApiError("ERR_CLIENT_NOT_ACTIVE", 409, "client must be ACTIVE to place a hold")

    # overlap check against ACTIVE or COMPLETED holds (touching endpoints overlap)
    for h in db.vacation_holds.values():
        if h["client_id"] != cid or h["status"] not in ("ACTIVE", "COMPLETED"):
            continue
        h_start = core.parse_date(h["start_date"])
        h_end = core.parse_date(h["end_date"])
        if start_d <= h_end and h_start <= end_d:
            raise ApiError("ERR_HOLD_OVERLAP", 409, "hold window overlaps an existing hold")

    rec = db.base_record()
    rec.update({
        "client_id": cid,
        "start_date": start_date,
        "end_date": end_date,
        "status": "ACTIVE",
    })
    db.vacation_holds[rec["id"]] = rec

    # cascade: client ACTIVE -> ON_HOLD, plan ACTIVE -> SUSPENDED, in-window deliveries cancelled
    plan = ser.active_meal_plan(cid)
    if plan is not None:
        plan["status"] = "SUSPENDED"
        db.touch(plan)
        cascade.cancel_scheduled_deliveries_of_plan(plan["id"], within=(start_d, end_d))

    client["enrollment_status"] = "ON_HOLD"
    db.touch(client)

    return core.ok_object(ser.vacation_hold(rec), 201)


@bp.get("/vacation-holds/<hid>")
@core.require_auth(core.ALL_ROLES)
def get_hold(hid):
    h = find.vacation_hold(hid)
    return core.ok_object(ser.vacation_hold(h))


@bp.get("/vacation-holds")
@core.require_auth(core.ALL_ROLES)
def list_holds():
    args = core.request.args
    items = list(db.vacation_holds.values())
    for key in ("client_id", "status"):
        val = args.get(key)
        if val is not None:
            items = [h for h in items if h[key] == val]
    items = ser.sorted_by_seq(items)
    limit, offset = core.get_pagination()
    page, total = core.paginate(items, limit, offset)
    return core.ok_array([ser.vacation_hold(h) for h in page], limit, offset, total)


@bp.post("/vacation-holds/<hid>/end")
@core.require_auth(["IntakeCoordinator"])
def end_hold(hid):
    h = find.vacation_hold(hid)
    if h["status"] != "ACTIVE":
        raise ApiError("ERR_HOLD_NOT_ACTIVE", 409, "hold must be ACTIVE to end")

    h["status"] = "COMPLETED"
    db.touch(h)

    cid = h["client_id"]
    other_active = any(
        o["client_id"] == cid and o["status"] == "ACTIVE" and o["id"] != hid
        for o in db.vacation_holds.values()
    )
    if not other_active:
        client = db.clients.get(cid)
        if client is not None and client["enrollment_status"] == "ON_HOLD":
            plan = ser.suspended_meal_plan(cid)
            if plan is not None:
                plan["status"] = "ACTIVE"
                db.touch(plan)
            client["enrollment_status"] = "ACTIVE"
            db.touch(client)

    return core.ok_object(ser.vacation_hold(h))
