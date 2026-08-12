"""Medication schedules and dose events."""
from flask import Blueprint, request

import db
import errors
from middleware import (require_roles, get_body, req_str, req_int, req_enum,
                        req_date, req_times_of_day, query_enum,
                        check_senior_scope, scoped_list, CRITICALITIES,
                        SCHED_STATUSES, DOSE_STATUSES)
from response import ok, list_ok
from services import (create_record, touch, ser, current_subscription,
                      materialize_doses, end_schedule, confirm_dose)

bp = Blueprint("meds", __name__)


@bp.post("/v1/medication-schedules")
def create_schedule():
    role, uid = require_roles(["PlatformAdmin", "Caregiver"])
    b = get_body()
    senior_id = req_str(b, "senior_id")
    medication_name = req_str(b, "medication_name")
    times_of_day = req_times_of_day(b, "times_of_day")
    window_minutes = req_int(b, "window_minutes", lo=15, hi=240)
    criticality = req_enum(b, "criticality", CRITICALITIES)
    start_date = req_date(b, "start_date")
    expected_version = req_int(b, "expected_senior_version")
    senior = db.seniors.get(senior_id)
    if senior is None:
        raise errors.not_found("Senior not found")
    if role == "Caregiver":
        check_senior_scope(role, uid, senior_id)
    # pinned order: subscription-active -> stale-version -> feature gate
    sub = current_subscription(senior_id)
    if sub is None or sub["service_status"] != "ACTIVE":
        raise errors.subscription_not_active()
    if expected_version != senior["version"]:
        raise errors.stale_version()
    plan = db.plans.get(sub["plan_id"])
    if plan is None or not plan["medication_reminders_enabled"]:
        raise errors.feature_gated()
    # uniqueness-by-replacement: supersede same-name ACTIVE schedule
    for s in list(db.medication_schedules.values()):
        if (s["senior_id"] == senior_id and s["medication_name"] == medication_name
                and s["status"] == "ACTIVE"):
            end_schedule(s)
    rec = create_record(db.medication_schedules, {
        "senior_id": senior_id,
        "medication_name": medication_name,
        "times_of_day": times_of_day,
        "window_minutes": window_minutes,
        "criticality": criticality,
        "start_date": start_date,
        "missed_streak": 0,
        "status": "ACTIVE",
    })
    materialize_doses(rec)
    touch(senior)
    return ok(ser(rec), 201)


def _get_schedule(schedule_id):
    s = db.medication_schedules.get(schedule_id)
    if s is None:
        raise errors.not_found("Medication schedule not found")
    return s


@bp.get("/v1/medication-schedules/<schedule_id>")
def get_schedule(schedule_id):
    role, uid = require_roles(["PlatformAdmin", "MonitoringAgent", "Caregiver"])
    s = _get_schedule(schedule_id)
    check_senior_scope(role, uid, s["senior_id"])
    return ok(ser(s))


@bp.get("/v1/medication-schedules")
def list_schedules():
    role, uid = require_roles(["PlatformAdmin", "MonitoringAgent", "Caregiver"])
    recs = list(db.medication_schedules.values())
    recs = scoped_list(role, uid, recs, request.args.get("senior_id"))
    st = query_enum("status", SCHED_STATUSES)
    if st is not None:
        recs = [r for r in recs if r["status"] == st]
    return list_ok(recs, ser)


@bp.post("/v1/medication-schedules/<schedule_id>/end")
def end_schedule_route(schedule_id):
    role, uid = require_roles(["PlatformAdmin", "Caregiver"])
    s = _get_schedule(schedule_id)
    if role == "Caregiver":
        check_senior_scope(role, uid, s["senior_id"])
    if s["status"] != "ACTIVE":
        raise errors.invalid_state("Schedule is not ACTIVE")
    end_schedule(s)
    return ok(ser(s))


# ------------------------------------------------------------ dose events --

def _get_dose(dose_id):
    d = db.doses.get(dose_id)
    if d is None:
        raise errors.not_found("Dose event not found")
    return d


@bp.get("/v1/dose-events/<dose_id>")
def get_dose(dose_id):
    role, uid = require_roles(["PlatformAdmin", "MonitoringAgent", "Caregiver", "Senior"])
    d = _get_dose(dose_id)
    check_senior_scope(role, uid, d["senior_id"])
    return ok(ser(d))


@bp.get("/v1/dose-events")
def list_doses():
    role, uid = require_roles(["PlatformAdmin", "MonitoringAgent", "Caregiver", "Senior"])
    recs = list(db.doses.values())
    recs = scoped_list(role, uid, recs, request.args.get("senior_id"))
    sid = request.args.get("schedule_id")
    if sid is not None:
        recs = [r for r in recs if r["schedule_id"] == sid]
    st = query_enum("status", DOSE_STATUSES)
    if st is not None:
        recs = [r for r in recs if r["status"] == st]
    return list_ok(recs, ser)


@bp.post("/v1/dose-events/<dose_id>/confirm")
def confirm_dose_route(dose_id):
    role, uid = require_roles(["Senior", "Caregiver"])
    d = _get_dose(dose_id)
    check_senior_scope(role, uid, d["senior_id"])
    if d["status"] != "PENDING":
        raise errors.dose_not_pending()
    confirm_dose(d, db.clock)
    return ok(ser(d))
