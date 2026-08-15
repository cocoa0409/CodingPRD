"""Usage summary report (PRD 3.9): de-identified aggregates over an inclusive window."""
from datetime import datetime, time, timedelta, timezone

from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_INVALID_REQUEST
from middleware import authenticate, authorize
from response import success_object
from util import parse_datetime, parse_date

bp = Blueprint("reports", __name__)

REFERRAL_STATUSES = ["INITIATED", "SENT", "ACKNOWLEDGED", "APPOINTMENT_BOOKED",
                     "SERVICE_RECEIVED", "DECLINED", "WITHDRAWN", "EXPIRED"]
SCREENING_PROGRAMS = ["SNAP", "CHILDCARE", "HOUSING"]


def _parse_bound(raw, field):
    if raw is None or raw == "":
        return None
    try:
        return parse_date(raw)
    except Exception:
        raise_error(ERR_INVALID_REQUEST, f"invalid ISO date: {field}")


@bp.get("/reports/usage-summary")
def usage_summary():
    caller = authenticate()
    authorize(caller, ["HubAdmin"])
    from_d = _parse_bound(request.args.get("from_date"), "from_date")
    to_d = _parse_bound(request.args.get("to_date"), "to_date")
    # Inclusive window: [from_date 00:00:00.000Z, to_date 23:59:59.999Z]; open-ended when omitted
    from_dt = datetime.combine(from_d, time.min, tzinfo=timezone.utc) if from_d else None
    to_dt = datetime.combine(to_d, time.max, tzinfo=timezone.utc) if to_d else None
    to_dt = to_dt.replace(microsecond=999000) if to_dt else None

    def dt_in_window(ts):
        if ts is None:
            return False
        dt = parse_datetime(ts)
        if from_dt and dt < from_dt:
            return False
        if to_dt and dt > to_dt:
            return False
        return True

    def date_in_window(ds):
        if ds is None:
            return False
        d = parse_date(ds)
        if from_d and d < from_d:
            return False
        if to_d and d > to_d:
            return False
        return True

    # clients_active is point-in-time and window-agnostic
    clients_active = sum(1 for c in db["clients"].values() if c["status"] == "ACTIVE")

    completed = [v for v in db["pantry_visits"].values()
                 if v["status"] == "COMPLETED" and dt_in_window(v["visit_date"])]
    visits_completed = len(completed)
    points_redeemed = sum(v["points_spent"] for v in completed)

    screenings_by_program = {}
    for p in SCREENING_PROGRAMS:
        screenings_by_program[p] = sum(
            1 for s in db["screenings"].values()
            if s["program"] == p and dt_in_window(s["created_at"]))

    grants_approved_cents = sum(
        g["approved_cents"] for g in db["grant_applications"].values()
        if dt_in_window(g.get("approved_at")))
    grants_disbursed_cents = sum(
        g["approved_cents"] for g in db["grant_applications"].values()
        if dt_in_window(g.get("disbursed_at")))

    referrals_by_status = {}
    for st in REFERRAL_STATUSES:
        referrals_by_status[st] = sum(
            1 for r in db["referrals"].values()
            if r["status"] == st and dt_in_window(r["created_at"]))

    shelter_nights_served = 0
    for s in db["shelter_stays"].values():
        if s["status"] == "CHECKED_OUT" and date_in_window(s.get("actual_check_out_date")):
            nights = (parse_date(s["actual_check_out_date"]) - parse_date(s["check_in_date"])).days
            shelter_nights_served += nights

    event_attendance = 0
    for reg in db["event_registrations"].values():
        if reg["status"] != "ATTENDED":
            continue
        event = db["outreach_events"].get(reg["event_id"])
        if event is not None and dt_in_window(event["event_date"]):
            event_attendance += 1

    return success_object({
        "clients_active": clients_active,
        "visits_completed": visits_completed,
        "points_redeemed": points_redeemed,
        "screenings_by_program": screenings_by_program,
        "grants_approved_cents": grants_approved_cents,
        "grants_disbursed_cents": grants_disbursed_cents,
        "referrals_by_status": referrals_by_status,
        "shelter_nights_served": shelter_nights_served,
        "event_attendance": event_attendance,
    })
