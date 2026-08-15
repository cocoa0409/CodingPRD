"""CheckIn endpoints: create, list, submit, acknowledge."""
from datetime import timedelta

from flask import Blueprint

import db
import errors as E
import middleware as mw
from middleware import (get_auth, require_roles, require_family_scope,
                        require_coach_scope, get_body, require_fields, get_entity,
                        touch, new_common, checkin_pub, list_response)
from response import success_object

bp = Blueprint("checkins", __name__)

GRACE = timedelta(hours=72)


@bp.post("/plans/<pid>/checkins")
def create_checkin(pid):
    auth = get_auth()
    require_roles(auth, ["Coach"])
    plan = get_entity("plan", pid)
    require_coach_scope(auth, plan["coach_id"])
    body = get_body()
    require_fields(body, ["due_at"])
    due = mw.parse_dt(body["due_at"], "due_at")
    if due <= db.clock:
        E.raise_error(E.ERR_VALIDATION, "due_at must be strictly in the future")
    if plan["status"] != "ACTIVE":
        E.raise_error(E.ERR_PLAN_NOT_ACTIVE, "Plan is not ACTIVE")
    c = new_common()
    c.update({
        "plan_id": pid,
        "due_at": db.iso(due),
        "due_at_dt": due,
        "submitted_at": None,
        "submitted_at_dt": None,
        "outcome_note": None,
        "status": "PENDING",
    })
    db.checkins[c["id"]] = c
    return success_object(checkin_pub(c), 201)


@bp.get("/plans/<pid>/checkins")
def list_checkins(pid):
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin", "Coach", "FamilyMember"])
    plan = get_entity("plan", pid)
    client = db.clients[plan["client_id"]]
    require_family_scope(auth, client["family_id"])
    rows = [c for c in db.checkins.values() if c["plan_id"] == pid]
    return list_response(rows, checkin_pub, paginate=False)


@bp.post("/checkins/<cid>/submit")
def submit_checkin(cid):
    auth = get_auth()
    require_roles(auth, ["FamilyMember"])
    c = get_entity("checkin", cid)
    plan = db.plans[c["plan_id"]]
    client = db.clients[plan["client_id"]]
    require_family_scope(auth, client["family_id"])
    if c["status"] != "PENDING":
        E.raise_error(E.ERR_INVALID_STATE,
                      "Check-in is %s, not PENDING" % c["status"])
    if plan["status"] != "ACTIVE":
        E.raise_error(E.ERR_PLAN_NOT_ACTIVE, "Plan is not ACTIVE")
    if db.clock > c["due_at_dt"] + GRACE:
        E.raise_error(E.ERR_CHECKIN_EXPIRED,
                      "Check-in grace window has elapsed")

    body = get_body()
    if "outcome_note" in body:
        c["outcome_note"] = body["outcome_note"]
    c["submitted_at"] = db.now_iso()
    c["submitted_at_dt"] = db.clock
    if db.clock <= c["due_at_dt"]:
        c["status"] = "SUBMITTED_ON_TIME"
        client["checkin_streak"] += 1
    else:
        c["status"] = "SUBMITTED_LATE"
        client["checkin_streak"] = 0
    touch(client)
    touch(c)
    return success_object(checkin_pub(c), 200)


@bp.post("/checkins/<cid>/acknowledge")
def acknowledge_checkin(cid):
    auth = get_auth()
    require_roles(auth, ["Coach"])
    c = get_entity("checkin", cid)
    plan = db.plans[c["plan_id"]]
    require_coach_scope(auth, plan["coach_id"])
    if c["status"] not in ("SUBMITTED_ON_TIME", "SUBMITTED_LATE"):
        E.raise_error(E.ERR_INVALID_STATE,
                      "Check-in is %s; only SUBMITTED check-ins can be acknowledged"
                      % c["status"])
    c["status"] = "ACKNOWLEDGED"
    touch(c)
    return success_object(checkin_pub(c), 200)
