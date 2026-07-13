from flask import Blueprint, g

import db
import core
import ser
import find
from core import ApiError

bp = Blueprint("deliveries", __name__)

OUTCOMES = {"DELIVERED", "NO_ANSWER", "SKIPPED"}


def _delivery_meal_count(plan):
    if plan["meal_type"] == "FROZEN":
        return plan["weekly_meal_count"]
    return plan["meals_per_day"]


@bp.post("/deliveries")
@core.require_auth(["RouteManager"])
def create_delivery():
    body = core.get_body()
    meal_plan_id = core.require_field(body, "meal_plan_id", "str")
    scheduled_date = core.require_field(body, "scheduled_date", "str")

    sd = core.parse_date(scheduled_date)
    if sd is None:
        core.invalid_value("scheduled_date is not a valid date")

    plan = find.meal_plan(meal_plan_id)
    client = db.clients.get(plan["client_id"])
    route = db.routes.get(plan["route_id"])

    if client is None or client["enrollment_status"] != "ACTIVE":
        raise ApiError("ERR_CLIENT_NOT_ACTIVE", 409, "client must be ACTIVE to schedule a delivery")
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_MEAL_PLAN_NOT_ACTIVE", 409, "meal plan must be ACTIVE")

    if core.weekday_name(sd) not in set(plan["delivery_days"]):
        raise ApiError("ERR_DELIVERY_DAY_MISMATCH", 422, "scheduled_date weekday not in delivery_days")

    meal_count = _delivery_meal_count(plan)
    existing = 0
    for d in db.deliveries.values():
        if d["route_id"] == plan["route_id"] and d["status"] == "SCHEDULED":
            od = core.parse_date(d["scheduled_date"])
            if od == sd:
                existing += d["meal_count"]
    if existing + meal_count > route["max_meals_per_run"]:
        raise ApiError("ERR_ROUTE_CAPACITY_EXCEEDED", 409, "route capacity exceeded for this date")

    rec = db.base_record()
    rec.update({
        "meal_plan_id": meal_plan_id,
        "client_id": plan["client_id"],
        "route_id": plan["route_id"],
        "scheduled_date": scheduled_date,
        "meal_type": plan["meal_type"],
        "meal_count": meal_count,
        "oaa_units_accrued": 0,
        "status": "SCHEDULED",
        "delivered_at": None,
    })
    db.deliveries[rec["id"]] = rec
    return core.ok_object(ser.delivery(rec), 201)


@bp.get("/deliveries/<did>")
@core.require_auth(core.ALL_ROLES)
def get_delivery(did):
    d = find.delivery(did)
    return core.ok_object(ser.delivery(d))


@bp.get("/deliveries")
@core.require_auth(core.ALL_ROLES)
def list_deliveries():
    args = core.request.args
    items = list(db.deliveries.values())
    for key in ("meal_plan_id", "client_id", "route_id", "status"):
        val = args.get(key)
        if val is not None:
            items = [d for d in items if d[key] == val]
    sched = args.get("scheduled_date")
    if sched is not None:
        target = core.parse_date(sched)
        items = [d for d in items if core.parse_date(d["scheduled_date"]) == target]
    items = ser.sorted_by_seq(items)
    limit, offset = core.get_pagination()
    page, total = core.paginate(items, limit, offset)
    return core.ok_array([ser.delivery(d) for d in page], limit, offset, total)


@bp.post("/deliveries/<did>/complete")
@core.require_auth(["VolunteerDriver"])
def complete_delivery(did):
    d = find.delivery(did)

    # route-ownership check (precedence before request-shape / state)
    route = db.routes.get(d["route_id"])
    if route is None or route["driver_id"] != g.user_id:
        raise ApiError("ERR_NOT_ROUTE_DRIVER", 403, "acting driver does not own this route")

    body = core.get_body()
    outcome = core.require_field(body, "outcome", "str")
    wellness_notes = core.optional_field(body, "wellness_notes", "str")
    core.check_enum(outcome, OUTCOMES, "invalid outcome")

    if d["status"] != "SCHEDULED":
        raise ApiError("ERR_DELIVERY_NOT_SCHEDULED", 409, "delivery must be SCHEDULED to complete")

    client = db.clients.get(d["client_id"])

    if outcome == "DELIVERED":
        d["status"] = "DELIVERED"
        d["oaa_units_accrued"] = d["meal_count"]
        d["delivered_at"] = db.iso(db.now())
        if client is not None:
            client["consecutive_no_answer"] = 0
        _create_wellness_check(d, "OK", wellness_notes)
        db.touch(d)
        if client is not None:
            db.touch(client)

    elif outcome == "NO_ANSWER":
        d["status"] = "NO_ANSWER"
        wc = _create_wellness_check(d, "NO_ANSWER", wellness_notes)
        if client is not None:
            client["consecutive_no_answer"] += 1
            severity = core.compute_welfare_severity(client["consecutive_no_answer"])
        else:
            severity = core.compute_welfare_severity(1)
        _open_welfare_alert(d["client_id"], wc["id"], severity)
        db.touch(d)
        if client is not None:
            db.touch(client)

    else:  # SKIPPED
        d["status"] = "SKIPPED"
        db.touch(d)

    return core.ok_object(ser.delivery(d))


@bp.post("/deliveries/<did>/void")
@core.require_auth(["RouteManager"])
def void_delivery(did):
    d = find.delivery(did)
    if d["status"] != "DELIVERED":
        raise ApiError("ERR_DELIVERY_NOT_DELIVERED", 409, "delivery must be DELIVERED to void")
    d["status"] = "VOIDED"
    d["oaa_units_accrued"] = 0
    db.touch(d)
    client = db.clients.get(d["client_id"])
    if client is not None:
        db.touch(client)
    return core.ok_object(ser.delivery(d))


def _create_wellness_check(delivery, outcome, notes):
    wc = {
        "id": db.new_id(),
        "created_at": db.iso(db.now()),
        "_seq": db.next_seq(),
        "delivery_id": delivery["id"],
        "client_id": delivery["client_id"],
        "outcome": outcome,
        "notes": notes,
    }
    db.wellness_checks[wc["id"]] = wc
    return wc


def _open_welfare_alert(client_id, wellness_check_id, severity):
    rec = db.base_record()
    rec.update({
        "client_id": client_id,
        "triggering_wellness_check_id": wellness_check_id,
        "severity": severity,
        "status": "OPEN",
        "acknowledged_by": None,
    })
    db.welfare_alerts[rec["id"]] = rec
    return rec
