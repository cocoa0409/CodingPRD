"""Goal endpoints: add to plan, list, transitions."""
from flask import Blueprint

import db
import errors as E
import middleware as mw
from middleware import (get_auth, require_roles, require_family_scope,
                        require_coach_scope, get_body, require_fields, get_entity,
                        touch, new_common, goal_pub, list_response, parse_date)
from response import success_object

bp = Blueprint("goals", __name__)

_EDITABLE_PLAN_STATES = ("DRAFT", "PROPOSED", "ACTIVE")


@bp.post("/plans/<pid>/goals")
def create_goal(pid):
    auth = get_auth()
    require_roles(auth, ["Coach"])
    plan = get_entity("plan", pid)
    require_coach_scope(auth, plan["coach_id"])
    if plan["status"] not in _EDITABLE_PLAN_STATES:
        E.raise_error(E.ERR_INVALID_STATE,
                      "Goals may only be added while the plan is DRAFT, PROPOSED, or ACTIVE")
    body = get_body()
    require_fields(body, ["title", "target_date"])
    parse_date(body["target_date"], "target_date")
    g = new_common()
    g.update({
        "plan_id": pid,
        "title": body["title"],
        "target_date": body["target_date"],
        "status": "SET",
        "carried_to_plan_id": None,
        "resolved_at": None,
        "resolved_at_dt": None,
    })
    db.goals[g["id"]] = g
    return success_object(goal_pub(g), 201)


@bp.get("/plans/<pid>/goals")
def list_goals(pid):
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin", "Coach", "FamilyMember"])
    plan = get_entity("plan", pid)
    client = db.clients[plan["client_id"]]
    require_family_scope(auth, client["family_id"])
    rows = [g for g in db.goals.values() if g["plan_id"] == pid]
    return list_response(rows, goal_pub, paginate=False)


@bp.post("/goals/<gid>/transition")
def goal_transition(gid):
    auth = get_auth()
    require_roles(auth, ["Coach"])
    g = get_entity("goal", gid)
    plan = db.plans[g["plan_id"]]
    require_coach_scope(auth, plan["coach_id"])
    body = get_body()
    require_fields(body, ["to_state"])
    to = body["to_state"]
    mw.enum_check(to, ["IN_PROGRESS", "ACHIEVED", "DROPPED"], "to_state")

    if to == "IN_PROGRESS":
        if g["status"] != "SET":
            E.raise_error(E.ERR_INVALID_STATE,
                          "Cannot transition goal from %s to IN_PROGRESS" % g["status"])
        if plan["status"] not in _EDITABLE_PLAN_STATES:
            E.raise_error(E.ERR_INVALID_STATE,
                          "Owning plan state %s does not permit this goal transition"
                          % plan["status"])
        g["status"] = "IN_PROGRESS"

    elif to == "ACHIEVED":
        if g["status"] not in ("SET", "IN_PROGRESS"):
            E.raise_error(E.ERR_INVALID_STATE,
                          "Cannot transition goal from %s to ACHIEVED" % g["status"])
        if plan["status"] != "ACTIVE":
            E.raise_error(E.ERR_PLAN_NOT_ACTIVE,
                          "Owning plan must be ACTIVE to achieve a goal")
        g["status"] = "ACHIEVED"
        g["resolved_at"] = db.now_iso()
        g["resolved_at_dt"] = db.clock

    else:  # DROPPED
        if g["status"] not in ("SET", "IN_PROGRESS"):
            E.raise_error(E.ERR_INVALID_STATE,
                          "Cannot transition goal from %s to DROPPED" % g["status"])
        if plan["status"] not in _EDITABLE_PLAN_STATES:
            E.raise_error(E.ERR_INVALID_STATE,
                          "Owning plan state %s does not permit this goal transition"
                          % plan["status"])
        g["status"] = "DROPPED"
        g["resolved_at"] = db.now_iso()
        g["resolved_at_dt"] = db.clock

    touch(g)
    return success_object(goal_pub(g), 200)
