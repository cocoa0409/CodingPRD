"""Operating days: schedule, read, list, begin-checklists, open-gates, resume-day,
close-gates (projected settlement), reconcile (recognized settlement + breakage)."""
from flask import Blueprint

import db
from db import store, serialize, touch
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_FAIR_INVALID_STATE,
    ERR_INVALID_DAY_POSTURE,
    ERR_DAY_NOT_TODAY,
    ERR_DUPLICATE_OPERATING_DAY,
    ERR_CAPACITY_ABOVE_MIDWAY,
    ERR_RIDES_NOT_CLEARED,
    ERR_WIND_ABOVE_LIMIT,
)
from helpers import get_or_404, paginate, qparam, _parse_date
from middleware import authenticate, scope_to_fair
from response import ok
from services.calculations import (
    projected_settlement,
    recognized_settlement,
    FAIR_WIND_RESUME_MPH,
    RECONCILIATION_FLAG_THRESHOLD_CENTS,
)
from services.cascades import close_gates_cascade
from validators import get_body, reject_unknown, req_str, req_int, req_date

bp = Blueprint("days", __name__)

ALL = ["StateProgramAdmin", "StateInspector", "FairManager", "RideOperator", "TicketClerk", "CrewMember"]


@bp.post("/operating-days")
def create_day():
    ctx = authenticate(["FairManager"])
    body = get_body()
    reject_unknown(body, {"fair_id", "date", "max_attendance"})
    fair_id = req_str(body, "fair_id")
    date_str = req_str(body, "date")
    date_val = req_date(body, "date")
    max_attendance = req_int(body, "max_attendance", lo=1)
    scope_to_fair(ctx, fair_id if db.get("fairs", fair_id) else None)
    fair = get_or_404("fairs", fair_id)
    scope_to_fair(ctx, fair["id"])
    if fair["status"] != "PERMITTED":
        raise_err(ERR_FAIR_INVALID_STATE, "Operating days can only be scheduled while the fair is PERMITTED")
    if not (_parse_date(fair["opening_date"]) <= date_val <= _parse_date(fair["closing_date"])):
        raise_err(ERR_INVALID_REQUEST, "date must fall between opening_date and closing_date inclusive")
    if date_val < db.today_date():
        raise_err(ERR_INVALID_REQUEST, "date must not be in the past")
    for existing in store["operating_days"].values():
        if existing["fair_id"] == fair_id and existing["date"] == date_str:
            raise_err(ERR_DUPLICATE_OPERATING_DAY, "An operating day already exists for this fair and date")
    if max_attendance > fair["midway_capacity"]:
        raise_err(ERR_CAPACITY_ABOVE_MIDWAY, "max_attendance exceeds the fair's midway_capacity")
    day = db.register(
        "operating_days",
        {
            "fair_id": fair_id,
            "date": date_str,
            "max_attendance": max_attendance,
            "posture": "SCHEDULED",
            "attendance_count": 0,
            "gross_sales_cents": None,
            "voided_cents": None,
            "projected_revenue_cents": None,
            "recognized_revenue_cents": None,
            "breakage_cents": None,
            "reconciliation_flagged": None,
        },
    )
    return ok(serialize(day), 201)


@bp.get("/operating-days/<did>")
def get_day(did):
    ctx = authenticate(ALL)
    day = get_or_404("operating_days", did)
    scope_to_fair(ctx, day["fair_id"])
    return ok(serialize(day))


@bp.get("/operating-days")
def list_days():
    authenticate(ALL)
    return paginate(
        "operating_days",
        {"fair_id": qparam("fair_id"), "posture": qparam("posture"), "date": qparam("date")},
    )


@bp.post("/operating-days/<did>/begin-checklists")
def begin_checklists(did):
    ctx = authenticate(["FairManager"])
    day = get_or_404("operating_days", did)
    scope_to_fair(ctx, day["fair_id"])
    body = get_body()
    reject_unknown(body, set())
    if day["posture"] != "SCHEDULED":
        raise_err(ERR_INVALID_DAY_POSTURE, "begin-checklists requires posture SCHEDULED")
    if day["date"] != db.today_str():
        raise_err(ERR_DAY_NOT_TODAY, "begin-checklists requires the day to be the current date")
    day["posture"] = "CHECKLIST_PHASE"
    touch(day)
    for ride in store["rides"].values():
        if ride["fair_id"] == day["fair_id"] and ride["minor_incidents_today"] != 0:
            ride["minor_incidents_today"] = 0
            touch(ride)
    return ok(serialize(day))


@bp.post("/operating-days/<did>/open-gates")
def open_gates(did):
    ctx = authenticate(["FairManager"])
    day = get_or_404("operating_days", did)
    scope_to_fair(ctx, day["fair_id"])
    body = get_body()
    reject_unknown(body, set())
    if day["posture"] != "CHECKLIST_PHASE":
        raise_err(ERR_INVALID_DAY_POSTURE, "open-gates requires posture CHECKLIST_PHASE")
    gated = [
        r
        for r in store["rides"].values()
        if r["fair_id"] == day["fair_id"]
        and r["setup_status"] == "SETUP_VERIFIED"
        and r["license_status"] == "LICENSED"
    ]
    for ride in gated:
        cleared = any(
            c
            for c in store["checklists"].values()
            if c["ride_id"] == ride["id"]
            and c["operating_day_id"] == day["id"]
            and c["status"] == "COUNTERSIGNED"
        )
        if not cleared:
            raise_err(ERR_RIDES_NOT_CLEARED, "Every SETUP_VERIFIED and LICENSED ride needs a COUNTERSIGNED checklist")
    day["posture"] = "OPEN"
    touch(day)
    for ride in gated:
        if ride["daily_status"] == "CLOSED":
            ride["daily_status"] = "OPEN"
            touch(ride)
    return ok(serialize(day))


@bp.post("/operating-days/<did>/resume-day")
def resume_day(did):
    ctx = authenticate(["FairManager"])
    day = get_or_404("operating_days", did)
    scope_to_fair(ctx, day["fair_id"])
    body = get_body()
    reject_unknown(body, set())
    if day["posture"] != "WEATHER_HOLD":
        raise_err(ERR_INVALID_DAY_POSTURE, "resume-day requires posture WEATHER_HOLD")
    latest = _latest_observation(day["id"])
    if latest is None or latest["wind_speed_mph"] > FAIR_WIND_RESUME_MPH:
        raise_err(ERR_WIND_ABOVE_LIMIT, "Latest wind reading is above the day resume threshold")
    day["posture"] = "OPEN"
    touch(day)
    # Rides deliberately remain WEATHER_HOLD; each reopens via POST /midway/rides/{id}/resume.
    return ok(serialize(day))


@bp.post("/operating-days/<did>/close-gates")
def close_gates(did):
    ctx = authenticate(["FairManager"])
    day = get_or_404("operating_days", did)
    scope_to_fair(ctx, day["fair_id"])
    body = get_body()
    reject_unknown(body, set())
    if day["posture"] not in ("OPEN", "WEATHER_HOLD"):
        raise_err(ERR_INVALID_DAY_POSTURE, "close-gates requires posture OPEN or WEATHER_HOLD")
    close_gates_cascade(day)
    gross, voided, projected = projected_settlement(day["id"])
    day["posture"] = "CLOSED"
    day["gross_sales_cents"] = gross
    day["voided_cents"] = voided
    day["projected_revenue_cents"] = projected
    touch(day)
    return ok(serialize(day))


@bp.post("/operating-days/<did>/reconcile")
def reconcile(did):
    ctx = authenticate(["FairManager"])
    day = get_or_404("operating_days", did)
    scope_to_fair(ctx, day["fair_id"])
    body = get_body()
    reject_unknown(body, set())
    if day["posture"] != "CLOSED":
        raise_err(ERR_INVALID_DAY_POSTURE, "reconcile requires posture CLOSED")
    recognized = recognized_settlement(day["id"])
    day["recognized_revenue_cents"] = recognized
    day["breakage_cents"] = day["projected_revenue_cents"] - recognized
    day["reconciliation_flagged"] = day["breakage_cents"] > RECONCILIATION_FLAG_THRESHOLD_CENTS
    day["posture"] = "RECONCILED"
    touch(day)
    return ok(serialize(day))


def _latest_observation(day_id):
    obs = [o for o in store["observations"].values() if o["operating_day_id"] == day_id]
    if not obs:
        return None
    obs.sort(key=lambda o: (o["created_at"], o["_seq"]))
    return obs[-1]
