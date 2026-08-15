"""Coach endpoints: create, read, list, transition, sub-resource lists."""
from flask import Blueprint

import db
import errors as E
import middleware as mw
from middleware import (get_auth, require_roles, require_coach_scope, get_body,
                        require_fields, get_entity, touch, new_common, coach_pub,
                        plan_pub, session_pub, note_pub, workshop_pub, list_response)
from response import success_object
from services import billing, supervision

bp = Blueprint("coaches", __name__)


@bp.post("/coaches")
def create_coach():
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin"])
    body = get_body()
    require_fields(body, ["full_name", "credential_level"])
    mw.enum_check(body["credential_level"], ["ASSOCIATE", "CERTIFIED", "SUPERVISOR"],
                  "credential_level")
    c = new_common()
    c.update({
        "full_name": body["full_name"],
        "credential_level": body["credential_level"],
        "status": "AVAILABLE",
        "active_caseload": 0,
        "caseload_cap": supervision.CASELOAD_CAP[body["credential_level"]],
        "required_supervision_hours": 0,
        "verified_supervision_hours_30d": 0,
    })
    db.coaches[c["id"]] = c
    return success_object(coach_pub(c), 201)


@bp.get("/coaches/<cid>")
def get_coach(cid):
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin", "Coach"])
    require_coach_scope(auth, cid)
    c = get_entity("coach", cid)
    return success_object(coach_pub(c), 200)


@bp.get("/coaches")
def list_coaches():
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin"])
    return list_response(list(db.coaches.values()), coach_pub, paginate=True)


@bp.post("/coaches/<cid>/transition")
def coach_transition(cid):
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin"])
    c = get_entity("coach", cid)
    body = get_body()
    require_fields(body, ["to_state"])
    to = body["to_state"]
    mw.enum_check(to, ["INACTIVE", "AVAILABLE"], "to_state")

    if to == "INACTIVE":
        if c["status"] not in ("AVAILABLE", "SUPERVISION_DEFICIT"):
            E.raise_error(E.ERR_INVALID_STATE,
                          "Cannot transition coach from %s to INACTIVE" % c["status"])
        c["active_caseload"] = sum(
            1 for p in db.plans.values()
            if p["coach_id"] == cid and p["status"] == "ACTIVE"
        )
        if c["active_caseload"] != 0:
            E.raise_error(E.ERR_COACH_HAS_ACTIVE_PLANS,
                          "Coach has ACTIVE plans and cannot be deactivated")
        c["status"] = "INACTIVE"
        touch(c)
        # Posture recompute for this coach's DRAFT/PROPOSED plans.
        for p in db.plans.values():
            if p["coach_id"] == cid and p["status"] in ("DRAFT", "PROPOSED"):
                billing.recompute_plan_posture(p)

    else:  # AVAILABLE
        if c["status"] != "INACTIVE":
            E.raise_error(E.ERR_INVALID_STATE,
                          "Cannot transition coach from %s to AVAILABLE" % c["status"])
        c["status"] = "AVAILABLE"
        supervision.recompute_coach(c)
        touch(c)

    return success_object(coach_pub(c), 200)


@bp.get("/coaches/<cid>/plans")
def coach_plans(cid):
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin", "Coach"])
    require_coach_scope(auth, cid)
    get_entity("coach", cid)
    rows = [p for p in db.plans.values() if p["coach_id"] == cid]
    return list_response(rows, plan_pub, paginate=False)


@bp.get("/coaches/<cid>/sessions")
def coach_sessions(cid):
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin", "Coach"])
    require_coach_scope(auth, cid)
    get_entity("coach", cid)
    rows = [s for s in db.sessions.values() if s["coach_id"] == cid]
    return list_response(rows, session_pub, paginate=False)


@bp.get("/coaches/<cid>/notes")
def coach_notes(cid):
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin", "Coach"])
    require_coach_scope(auth, cid)
    get_entity("coach", cid)
    rows = [n for n in db.notes.values() if n["author_coach_id"] == cid]
    return list_response(rows, note_pub, paginate=False)


@bp.get("/coaches/<cid>/workshops")
def coach_workshops(cid):
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin", "Coach"])
    require_coach_scope(auth, cid)
    get_entity("coach", cid)
    rows = [w for w in db.workshops.values() if w["coach_id"] == cid]
    return list_response(rows, workshop_pub, paginate=False)
