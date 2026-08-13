"""Fraction sessions (PRD 3.6 booking, 3.7 delivery & chart-round governance)."""
from datetime import timedelta

from flask import Blueprint

from db import store, new_entity, touch, sorted_all
from errors import (err, ERR_NOT_FOUND, ERR_PLAN_COURSE_MISMATCH,
                    ERR_MACHINE_TYPE_MISMATCH, ERR_MACHINE_NOT_OPERATIONAL,
                    ERR_WEEKEND_NOT_PERMITTED, ERR_MACHINE_SLOT_CONFLICT,
                    ERR_FRACTION_COUNT_EXCEEDED, ERR_SESSION_NOT_SCHEDULED,
                    ERR_COURSE_NOT_ON_TREATMENT, ERR_CHART_REVIEW_OVERDUE)
from middleware import require_roles, ALL_ROLES, get_body
from response import success, paginate
from serializers import session_json
from services import calc
from services.billing import draft_claim, append_line, auto_reopen_finalized
from timeutil import new_id, is_weekend_dt
from validate import req_str, req_enum, req_dt_pair, opt_bool

bp = Blueprint("fractions", __name__)

TURNOVER = timedelta(minutes=calc.LINAC_TURNOVER_MINUTES)
CANCEL_REASONS = {"PATIENT", "OTHER"}


def get_session_or_404(sid):
    s = store.sessions.get(sid)
    if s is None:
        err(ERR_NOT_FOUND, "fraction session not found")
    return s


@bp.post("/oncology/treatment-courses/<cid>/fraction-sessions")
@require_roles("Scheduler")
def book_fraction(cid, user_id):
    course = store.courses.get(cid)
    if course is None:
        err(ERR_NOT_FOUND, "treatment course not found")
    body = get_body()
    # p3 existence: body-referenced ids
    plan_id = body.get("plan_id")
    machine_id = body.get("machine_id")
    if isinstance(plan_id, str) and plan_id not in store.plans:
        err(ERR_NOT_FOUND, "treatment plan not found")
    if isinstance(machine_id, str) and machine_id not in store.machines:
        err(ERR_NOT_FOUND, "machine not found")
    # p4 schema
    plan_id = req_str(body, "plan_id")
    machine_id = req_str(body, "machine_id")
    s_raw, e_raw, s, e = req_dt_pair(body)
    igrt = opt_bool(body, "igrt_planned", default=False)
    # p10 cross-reference: plan belongs to the path course and is treatable
    plan = store.plans[plan_id]
    if plan["course_id"] != cid:
        err(ERR_PLAN_COURSE_MISMATCH,
            "plan_id does not belong to the course in the path")
    if plan["status"] not in ("APPROVED_FOR_DELIVERY", "ACTIVE"):
        err(ERR_PLAN_COURSE_MISMATCH,
            "plan must be APPROVED_FOR_DELIVERY or ACTIVE")
    # p11 machine constraints: LINAC type, operational, weekend allowance
    machine = store.machines[machine_id]
    if machine["machine_type"] != "LINAC":
        err(ERR_MACHINE_TYPE_MISMATCH, "Fraction delivery requires a LINAC")
    if machine["status"] != "OPERATIONAL":
        err(ERR_MACHINE_NOT_OPERATIONAL, "Machine is DOWN")
    weekend = is_weekend_dt(s)
    if weekend and course["weekend_makeup_allowance"] <= 0:
        err(ERR_WEEKEND_NOT_PERMITTED,
            "Weekend booking requires weekend_makeup_allowance > 0")
    # p12 LINAC turnover-buffered overlap (SCHEDULED/DELIVERED occupy the machine)
    for other in store.sessions.values():
        if other["machine_id"] == machine_id \
                and other["status"] in ("SCHEDULED", "DELIVERED"):
            if s < other["_end"] + TURNOVER and other["_start"] < e + TURNOVER:
                err(ERR_MACHINE_SLOT_CONFLICT,
                    "LINAC booking collides within the turnover buffer")
    # p13 per-plan fraction-count ceiling (SCHEDULED + DELIVERED < planned)
    booked = sum(1 for x in store.sessions.values()
                 if x["plan_id"] == plan_id and x["status"] in ("SCHEDULED", "DELIVERED"))
    if booked >= plan["planned_fractions"]:
        err(ERR_FRACTION_COUNT_EXCEEDED,
            "Booking would exceed plan.planned_fractions")
    # per-course fraction_number: 1 + max over all sessions, never reused
    existing = [x for x in store.sessions.values() if x["course_id"] == cid]
    number = 1 + max((x["fraction_number"] for x in existing), default=0)
    sess = new_entity()
    sess.update({
        "id": new_id(), "course_id": cid, "plan_id": plan_id,
        "machine_id": machine_id, "fraction_number": number,
        "start_time": s_raw, "end_time": e_raw, "_start": s, "_end": e,
        "igrt_planned": igrt,
        "is_first_fraction": number == 1,
        "is_weekend": weekend,
        "dose_delivered_cGy": None, "cancellation_reason": None,
        "status": "SCHEDULED",
    })
    store.sessions[sess["id"]] = sess
    if weekend:
        course["weekend_makeup_allowance"] -= 1
        touch(course)
    return success(session_json(sess), 201)


@bp.get("/oncology/treatment-courses/<cid>/fraction-sessions")
@require_roles(*ALL_ROLES)
def list_fractions(cid, user_id):
    from flask import request
    if cid not in store.courses:
        err(ERR_NOT_FOUND, "treatment course not found")
    items = [s for s in store.sessions.values() if s["course_id"] == cid]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [s for s in items if s["status"] == status_filter]
    items = sorted_all(items)
    page, meta = paginate(items)
    return success([session_json(s) for s in page], 200, pagination=meta)


@bp.post("/oncology/fraction-sessions/<sid>/deliver")
@require_roles("RadiationTherapist")
def deliver_fraction(sid, user_id):
    sess = get_session_or_404(sid)
    get_body()
    # p6 state gates
    if sess["status"] != "SCHEDULED":
        err(ERR_SESSION_NOT_SCHEDULED, "Session is not SCHEDULED")
    course = store.courses[sess["course_id"]]
    if course["status"] not in ("TREATMENT_READY", "ON_TREATMENT"):
        err(ERR_COURSE_NOT_ON_TREATMENT,
            "Delivery requires course TREATMENT_READY or ON_TREATMENT")
    # p8 chart-review gate: the LIMIT-th delivery arms the gate; LIMIT+1 rejected
    if course["fractions_since_chart_review"] >= calc.CHART_REVIEW_FRACTION_LIMIT:
        err(ERR_CHART_REVIEW_OVERDUE,
            "A PASS chart review is required before further delivery")
    # p11 machine must be OPERATIONAL
    machine = store.machines[sess["machine_id"]]
    if machine["status"] != "OPERATIONAL":
        err(ERR_MACHINE_NOT_OPERATIONAL, "Machine is DOWN")
    plan = store.plans[sess["plan_id"]]
    # dose allocation: base for every fraction but the plan's last remaining one
    dose = calc.next_delivery_dose(plan)
    first_delivery = course["status"] == "TREATMENT_READY"
    sess["status"] = "DELIVERED"
    sess["dose_delivered_cGy"] = dose
    touch(sess)
    course["delivered_fractions"] += 1
    course["delivered_dose_cGy"] += dose
    course["fractions_since_chart_review"] += 1
    if first_delivery:
        course["status"] = "ON_TREATMENT"
        if plan["status"] == "APPROVED_FOR_DELIVERY":
            plan["status"] = "ACTIVE"
            touch(plan)
    touch(course)
    # billing: FINALIZED auto-reopens, then lines append to the DRAFT claim
    auto_reopen_finalized(course["id"])
    claim = draft_claim(course["id"])
    if claim is not None:
        rate = calc.FRACTION_DELIVERY_RATE_CENTS[course["technique"]]
        append_line(claim, "FRACTION_DELIVERY",
                    f"Fraction delivery #{sess['fraction_number']}", rate, sess["id"])
        if sess["igrt_planned"]:
            append_line(claim, "IGRT", "Image guidance",
                        calc.IGRT_FEE_CENTS, sess["id"])
        if sess["is_first_fraction"]:
            append_line(claim, "FIRST_FRACTION_SETUP", "First fraction setup",
                        calc.FIRST_FRACTION_SETUP_FEE_CENTS, sess["id"])
    return success(session_json(sess), 200)


@bp.post("/oncology/fraction-sessions/<sid>/cancel")
@require_roles("Scheduler")
def cancel_fraction(sid, user_id):
    sess = get_session_or_404(sid)
    body = get_body()
    reason = req_enum(body, "reason", CANCEL_REASONS)
    if sess["status"] != "SCHEDULED":
        err(ERR_SESSION_NOT_SCHEDULED, "Session is not SCHEDULED")
    sess["status"] = "CANCELLED"
    sess["cancellation_reason"] = reason
    touch(sess)
    return success(session_json(sess), 200)


@bp.post("/oncology/fraction-sessions/<sid>/mark-no-show")
@require_roles("RadiationTherapist")
def no_show_fraction(sid, user_id):
    sess = get_session_or_404(sid)
    get_body()
    if sess["status"] != "SCHEDULED":
        err(ERR_SESSION_NOT_SCHEDULED, "Session is not SCHEDULED")
    sess["status"] = "NO_SHOW"
    touch(sess)
    course = store.courses[sess["course_id"]]
    auto_reopen_finalized(course["id"])
    claim = draft_claim(course["id"])
    if claim is not None:
        append_line(claim, "NO_SHOW_FEE", "No-show fee",
                    calc.NO_SHOW_FEE_CENTS, sess["id"])
    return success(session_json(sess), 200)
