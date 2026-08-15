"""SupervisionRecord endpoints: schedule, list, transitions."""
from flask import Blueprint

import db
import errors as E
import middleware as mw
from middleware import (get_auth, require_roles, require_coach_scope, get_body,
                        require_fields, get_entity, touch, new_common,
                        supervision_pub, list_response)
from response import success_object
from services import supervision as sup_svc

bp = Blueprint("supervision", __name__)


@bp.post("/coaches/<cid>/supervision-records")
def create_supervision_record(cid):
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin"])
    coach = get_entity("coach", cid)
    body = get_body()
    require_fields(body, ["supervisor_coach_id", "scheduled_at", "hours"])
    supervisor = get_entity("coach", body["supervisor_coach_id"])
    scheduled_at = mw.parse_dt(body["scheduled_at"], "scheduled_at")
    mw.num_check(body["hours"], "hours", gt=0)
    if body["supervisor_coach_id"] == cid:
        E.raise_error(E.ERR_SELF_SUPERVISION,
                      "A coach cannot be their own supervisor")
    if supervisor["credential_level"] != "SUPERVISOR":
        E.raise_error(E.ERR_CREDENTIAL_INSUFFICIENT,
                      "Supervisor must hold credential_level SUPERVISOR")
    r = new_common()
    r.update({
        "coach_id": cid,
        "supervisor_coach_id": body["supervisor_coach_id"],
        "scheduled_at": db.iso(scheduled_at),
        "scheduled_at_dt": scheduled_at,
        "hours": body["hours"],
        "status": "SCHEDULED",
        "verified_at": None,
        "verified_at_dt": None,
    })
    db.supervision_records[r["id"]] = r
    return success_object(supervision_pub(r), 201)


@bp.get("/coaches/<cid>/supervision-records")
def list_supervision_records(cid):
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin", "Coach"])
    require_coach_scope(auth, cid)
    get_entity("coach", cid)
    rows = [r for r in db.supervision_records.values() if r["coach_id"] == cid]
    return list_response(rows, supervision_pub, paginate=False)


@bp.post("/supervision-records/<rid>/transition")
def supervision_transition(rid):
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin", "Coach"])
    r = get_entity("supervision", rid)
    body = get_body()
    require_fields(body, ["to_state"])
    to = body["to_state"]
    mw.enum_check(to, ["HELD", "VERIFIED", "CANCELLED"], "to_state")

    if to == "HELD":
        if auth["role"] != "Coach":
            E.raise_error(E.ERR_FORBIDDEN_ROLE,
                          "Only the named supervisor coach may mark a record HELD")
        require_coach_scope(auth, r["supervisor_coach_id"])
        if r["status"] != "SCHEDULED":
            E.raise_error(E.ERR_INVALID_STATE,
                          "Cannot transition supervision record from %s to HELD"
                          % r["status"])
        r["status"] = "HELD"

    elif to == "VERIFIED":
        if auth["role"] != "PracticeAdmin":
            E.raise_error(E.ERR_FORBIDDEN_ROLE,
                          "Only PracticeAdmin may verify a supervision record")
        if r["status"] != "HELD":
            E.raise_error(E.ERR_INVALID_STATE,
                          "Cannot transition supervision record from %s to VERIFIED"
                          % r["status"])
        r["status"] = "VERIFIED"
        r["verified_at"] = db.now_iso()
        r["verified_at_dt"] = db.clock
        touch(r)
        coach = db.coaches[r["coach_id"]]
        sup_svc.recompute_coach(coach)
        touch(coach)
        return success_object(supervision_pub(r), 200)

    else:  # CANCELLED
        if auth["role"] != "PracticeAdmin":
            E.raise_error(E.ERR_FORBIDDEN_ROLE,
                          "Only PracticeAdmin may cancel a supervision record")
        if r["status"] not in ("SCHEDULED", "HELD"):
            E.raise_error(E.ERR_INVALID_STATE,
                          "Cannot transition supervision record from %s to CANCELLED"
                          % r["status"])
        r["status"] = "CANCELLED"

    touch(r)
    return success_object(supervision_pub(r), 200)
