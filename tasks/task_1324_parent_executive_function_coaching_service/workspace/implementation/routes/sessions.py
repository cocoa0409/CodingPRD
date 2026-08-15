"""Session endpoints: schedule, list, read, complete, cancel, mark-no-show."""
from decimal import Decimal

from flask import Blueprint

import db
import errors as E
import middleware as mw
from middleware import (get_auth, require_roles, require_family_scope,
                        require_coach_scope, get_body, require_fields, get_entity,
                        touch, new_common, session_pub, list_response)
from response import success_object
from services import billing
from services import sessions as sess_svc

bp = Blueprint("sessions", __name__)

FREE_NOTICE_SECONDS = 24 * 3600
HALF_NOTICE_SECONDS = 4 * 3600
MAX_DURATION_SECONDS = 120 * 60


@bp.post("/plans/<pid>/sessions")
def create_session(pid):
    auth = get_auth()
    require_roles(auth, ["Coach"])
    plan = get_entity("plan", pid)
    require_coach_scope(auth, plan["coach_id"])
    body = get_body()
    require_fields(body, ["package_id", "scheduled_start", "scheduled_end"])
    pkg = get_entity("package", body["package_id"])
    start = mw.parse_dt(body["scheduled_start"], "scheduled_start")
    end = mw.parse_dt(body["scheduled_end"], "scheduled_end")
    # Shape (priority 5): end after start, duration <= 120 minutes.
    if end <= start:
        E.raise_error(E.ERR_VALIDATION, "scheduled_end must be after scheduled_start")
    if (end - start).total_seconds() > MAX_DURATION_SECONDS:
        E.raise_error(E.ERR_VALIDATION, "Session duration exceeds 120 minutes")

    client = db.clients[plan["client_id"]]
    fam = db.families[client["family_id"]]
    # State gates (priority 8-14)
    if fam["status"] != "ACTIVE":
        E.raise_error(E.ERR_FAMILY_NOT_ACTIVE, "Family is not ACTIVE")
    if client["status"] != "ACTIVE":
        E.raise_error(E.ERR_CLIENT_NOT_ACTIVE, "Client is not ACTIVE")
    if plan["status"] != "ACTIVE":
        E.raise_error(E.ERR_PLAN_NOT_ACTIVE, "Plan is not ACTIVE")
    if pkg["status"] != "ACTIVE":
        E.raise_error(E.ERR_PACKAGE_NOT_ACTIVE, "Package is not ACTIVE")
    # Cadence window (priority 18, ordered before temporal per §2.8).
    sess_svc.check_cadence(plan, start)
    # Temporal (priority 19): start strictly in the future.
    if start <= db.clock:
        E.raise_error(E.ERR_SESSION_IN_PAST,
                      "scheduled_start must be strictly in the future")
    # Coach schedule conflicts (priority 20).
    sess_svc.check_coach_conflicts(plan["coach_id"], start, end)
    # Linkage (priority 22): individual sessions draw INDIVIDUAL credits.
    if pkg["track"] != "INDIVIDUAL":
        E.raise_error(E.ERR_TRACK_MISMATCH,
                      "Sessions cannot be funded by a GROUP package")
    # Credit availability (priority 23).
    if billing.package_credits_remaining(pkg) - pkg["reserved_count"] < 1:
        E.raise_error(E.ERR_NO_CREDITS_AVAILABLE,
                      "Package has no credit available for reservation")

    s = new_common()
    s.update({
        "plan_id": pid,
        "coach_id": plan["coach_id"],
        "package_id": pkg["id"],
        "scheduled_start": db.iso(start),
        "scheduled_end": db.iso(end),
        "scheduled_start_dt": start,
        "scheduled_end_dt": end,
        "attendance_state": "SCHEDULED",
        "billing_state": "RESERVED",
        "cancellation_fee_cents": 0,
        "resolved_at": None,
    })
    db.sessions[s["id"]] = s
    pkg["reserved_count"] += 1
    touch(pkg)
    billing.recompute_plan_posture(plan)
    return success_object(session_pub(s), 201)


@bp.get("/plans/<pid>/sessions")
def list_sessions(pid):
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin", "Coach", "FamilyMember"])
    plan = get_entity("plan", pid)
    client = db.clients[plan["client_id"]]
    require_family_scope(auth, client["family_id"])
    rows = [s for s in db.sessions.values() if s["plan_id"] == pid]
    return list_response(rows, session_pub, paginate=False)


@bp.get("/sessions/<sid>")
def get_session(sid):
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin", "Coach", "FamilyMember"])
    s = get_entity("session", sid)
    plan = db.plans[s["plan_id"]]
    client = db.clients[plan["client_id"]]
    require_family_scope(auth, client["family_id"])
    return success_object(session_pub(s), 200)


def _family_of_session(s):
    plan = db.plans[s["plan_id"]]
    client = db.clients[plan["client_id"]]
    return db.families[client["family_id"]], plan


@bp.post("/sessions/<sid>/complete")
def complete_session(sid):
    auth = get_auth()
    require_roles(auth, ["Coach"])
    s = get_entity("session", sid)
    require_coach_scope(auth, s["coach_id"])
    if s["attendance_state"] != "SCHEDULED":
        E.raise_error(E.ERR_INVALID_STATE,
                      "Session is %s, not SCHEDULED" % s["attendance_state"])
    if db.clock < s["scheduled_start_dt"]:
        E.raise_error(E.ERR_SESSION_NOT_STARTED, "Session has not started")
    fam, plan = _family_of_session(s)
    pkg = db.packages[s["package_id"]]
    s["attendance_state"] = "COMPLETED"
    s["billing_state"] = "CONSUMED"
    s["resolved_at"] = db.now_iso()
    touch(s)
    pkg["credits_consumed"] += 1
    if pkg["reserved_count"] > 0:
        pkg["reserved_count"] -= 1
    touch(pkg)
    billing.recompute_package_status(pkg)
    billing.recompute_plan_posture(plan)
    return success_object(session_pub(s), 200)


@bp.post("/sessions/<sid>/cancel")
def cancel_session(sid):
    auth = get_auth()
    require_roles(auth, ["FamilyMember", "Coach"])
    s = get_entity("session", sid)
    fam, plan = _family_of_session(s)
    if auth["role"] == "Coach":
        require_coach_scope(auth, s["coach_id"])
    else:
        require_family_scope(auth, fam["id"])
    if s["attendance_state"] != "SCHEDULED":
        E.raise_error(E.ERR_INVALID_STATE,
                      "Session is %s, not SCHEDULED" % s["attendance_state"])
    if db.clock >= s["scheduled_start_dt"]:
        E.raise_error(E.ERR_SESSION_ALREADY_STARTED,
                      "Session has already started and cannot be cancelled")

    notice_seconds = (s["scheduled_start_dt"] - db.clock).total_seconds()
    pkg = db.packages[s["package_id"]]
    s["resolved_at"] = db.now_iso()
    if notice_seconds >= FREE_NOTICE_SECONDS:
        s["attendance_state"] = "CANCELLED_EARLY"
        s["billing_state"] = "RETURNED"
        s["cancellation_fee_cents"] = 0
        touch(s)
        if pkg["reserved_count"] > 0:
            pkg["reserved_count"] -= 1
            touch(pkg)
            billing.recompute_package_status(pkg)
    else:
        if notice_seconds >= HALF_NOTICE_SECONDS:
            fee = mw.rhu(Decimal("0.50") * pkg["per_credit_value_cents"])
        else:
            fee = pkg["per_credit_value_cents"]
        s["attendance_state"] = "CANCELLED_LATE"
        s["billing_state"] = "FORFEITED"
        s["cancellation_fee_cents"] = fee
        touch(s)
        pkg["credits_forfeited"] += 1
        if pkg["reserved_count"] > 0:
            pkg["reserved_count"] -= 1
        touch(pkg)
        billing.recompute_package_status(pkg)
        billing.charge_family(fam, fee)
        touch(fam)
        billing.maybe_auto_suspend(fam)  # fee-triggered auto-suspension
    billing.recompute_plan_posture(plan)
    return success_object(session_pub(s), 200)


@bp.post("/sessions/<sid>/mark-no-show")
def mark_no_show(sid):
    auth = get_auth()
    require_roles(auth, ["Coach"])
    s = get_entity("session", sid)
    require_coach_scope(auth, s["coach_id"])
    if s["attendance_state"] != "SCHEDULED":
        E.raise_error(E.ERR_INVALID_STATE,
                      "Session is %s, not SCHEDULED" % s["attendance_state"])
    if db.clock < s["scheduled_start_dt"]:
        E.raise_error(E.ERR_SESSION_NOT_STARTED, "Session has not started")
    fam, plan = _family_of_session(s)
    pkg = db.packages[s["package_id"]]
    fee = pkg["per_credit_value_cents"]  # 100% tier
    s["attendance_state"] = "NO_SHOW"
    s["billing_state"] = "FORFEITED"
    s["cancellation_fee_cents"] = fee
    s["resolved_at"] = db.now_iso()
    touch(s)
    pkg["credits_forfeited"] += 1
    if pkg["reserved_count"] > 0:
        pkg["reserved_count"] -= 1
    touch(pkg)
    billing.recompute_package_status(pkg)
    billing.charge_family(fam, fee)
    touch(fam)
    billing.maybe_auto_suspend(fam)  # fee-triggered auto-suspension
    billing.recompute_plan_posture(plan)
    return success_object(session_pub(s), 200)
