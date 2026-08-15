"""CoachingPlan endpoints: create (OCC), list, read, transitions + cascades."""
from flask import Blueprint

import db
import errors as E
import middleware as mw
from middleware import (get_auth, require_roles, require_family_scope,
                        require_coach_scope, get_body, require_fields, get_entity,
                        touch, new_common, plan_pub, list_response)
from response import success_object
from services import billing, supervision

bp = Blueprint("plans", __name__)


@bp.post("/clients/<cid>/plans")
def create_plan(cid):
    auth = get_auth()
    require_roles(auth, ["Coach"])
    client = get_entity("client", cid)
    body = get_body()
    require_fields(body, ["coach_id", "intake_id", "cadence", "expected_client_version"])
    coach = get_entity("coach", body["coach_id"])
    intake = get_entity("intake", body["intake_id"])
    mw.enum_check(body["cadence"], ["WEEKLY", "BIWEEKLY"], "cadence")

    # OCC (priority 6)
    if body["expected_client_version"] != client["version"]:
        E.raise_error(E.ERR_STALE_CLIENT_VERSION,
                      "Client version has advanced since the caller last observed it")
    # Client gate
    if client["status"] == "DISCHARGED":
        E.raise_error(E.ERR_CLIENT_NOT_ACTIVE, "Client is DISCHARGED")
    # Intake approval
    if intake["status"] != "APPROVED":
        E.raise_error(E.ERR_INTAKE_NOT_APPROVED, "Referenced intake is not APPROVED")
    # Coach INACTIVE gate
    if coach["status"] == "INACTIVE":
        E.raise_error(E.ERR_INVALID_STATE, "Coach is INACTIVE")
    # Linkage: intake must belong to the path client
    if intake["client_id"] != cid:
        E.raise_error(E.ERR_INTAKE_CLIENT_MISMATCH,
                      "intake_id belongs to a different client")

    # Supersede existing DRAFT/PROPOSED plans (goals NOT carried).
    for p in db.plans.values():
        if p["client_id"] == cid and p["status"] in ("DRAFT", "PROPOSED"):
            p["status"] = "SUPERSEDED"
            touch(p)

    revision_number = 1 + sum(1 for p in db.plans.values() if p["client_id"] == cid)
    plan = new_common()
    plan.update({
        "client_id": cid,
        "coach_id": body["coach_id"],
        "intake_id": body["intake_id"],
        "cadence": body["cadence"],
        "revision_number": revision_number,
        "status": "DRAFT",
        "posture": billing.compute_plan_posture({
            "client_id": cid, "coach_id": body["coach_id"],
        }),
        "revision_recommended": False,
        "activated_at": None,
        "activated_at_dt": None,
    })
    db.plans[plan["id"]] = plan
    touch(client)
    return success_object(plan_pub(plan), 201)


@bp.get("/clients/<cid>/plans")
def list_plans(cid):
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin", "Coach", "FamilyMember"])
    client = get_entity("client", cid)
    require_family_scope(auth, client["family_id"])
    rows = [p for p in db.plans.values() if p["client_id"] == cid]
    return list_response(rows, plan_pub, paginate=False)


@bp.get("/plans/<pid>")
def get_plan(pid):
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin", "Coach", "FamilyMember"])
    plan = get_entity("plan", pid)
    client = db.clients[plan["client_id"]]
    require_family_scope(auth, client["family_id"])
    return success_object(plan_pub(plan), 200)


@bp.post("/plans/<pid>/transition")
def plan_transition(pid):
    auth = get_auth()
    require_roles(auth, ["Coach", "FamilyMember", "PracticeAdmin"])
    plan = get_entity("plan", pid)
    client = db.clients[plan["client_id"]]
    fam = db.families[client["family_id"]]
    coach = db.coaches[plan["coach_id"]]
    body = get_body()
    require_fields(body, ["to_state"])
    to = body["to_state"]
    mw.enum_check(to, ["PROPOSED", "DRAFT", "ACTIVE", "COMPLETED", "TERMINATED"],
                  "to_state")

    if to == "PROPOSED":
        if auth["role"] != "Coach":
            E.raise_error(E.ERR_FORBIDDEN_ROLE, "Only Coach may propose a plan")
        require_coach_scope(auth, plan["coach_id"])
        if plan["status"] != "DRAFT":
            E.raise_error(E.ERR_INVALID_STATE,
                          "Cannot transition plan from %s to PROPOSED" % plan["status"])
        if not any(g["plan_id"] == pid and g["status"] in ("SET", "IN_PROGRESS")
                   for g in db.goals.values()):
            E.raise_error(E.ERR_GOALS_NOT_RESOLVED,
                          "Plan must hold at least one SET or IN_PROGRESS goal")
        intake = db.intakes[plan["intake_id"]]
        if intake["status"] != "APPROVED":
            E.raise_error(E.ERR_INTAKE_NOT_APPROVED, "Referenced intake is not APPROVED")
        if coach["status"] == "INACTIVE":
            E.raise_error(E.ERR_INVALID_STATE, "Coach is INACTIVE")
        plan["status"] = "PROPOSED"
        touch(plan)

    elif to == "DRAFT":
        if auth["role"] != "FamilyMember":
            E.raise_error(E.ERR_FORBIDDEN_ROLE,
                          "Only FamilyMember may request plan changes")
        require_family_scope(auth, client["family_id"])
        if plan["status"] != "PROPOSED":
            E.raise_error(E.ERR_INVALID_STATE,
                          "Cannot transition plan from %s to DRAFT" % plan["status"])
        plan["status"] = "DRAFT"
        touch(plan)

    elif to == "ACTIVE":
        if auth["role"] != "FamilyMember":
            E.raise_error(E.ERR_FORBIDDEN_ROLE, "Only FamilyMember may accept a plan")
        require_family_scope(auth, client["family_id"])
        if plan["status"] != "PROPOSED":
            E.raise_error(E.ERR_INVALID_STATE,
                          "Cannot transition plan from %s to ACTIVE" % plan["status"])
        if fam["status"] != "ACTIVE":
            E.raise_error(E.ERR_FAMILY_NOT_ACTIVE, "Family is not ACTIVE")
        if client["status"] not in ("INTAKE", "ACTIVE"):
            E.raise_error(E.ERR_CLIENT_NOT_ACTIVE,
                          "Client must be INTAKE or ACTIVE for plan acceptance")
        if coach["status"] == "INACTIVE":
            E.raise_error(E.ERR_INVALID_STATE, "Coach is INACTIVE")
        # Fiscal gates: caseload cap (p24) before supervision deficit (p25).
        supervision.recompute_coach(coach)
        if coach["active_caseload"] >= coach["caseload_cap"]:
            E.raise_error(E.ERR_CASELOAD_CAP_REACHED,
                          "Coach active caseload has reached the cap")
        if coach["status"] == "SUPERVISION_DEFICIT":
            E.raise_error(E.ERR_COACH_SUPERVISION_DEFICIT,
                          "Coach is in SUPERVISION_DEFICIT")

        # Supersede cascade over the client's other ACTIVE plan.
        for other in db.plans.values():
            if other["client_id"] == client["id"] and other["status"] == "ACTIVE" and other["id"] != pid:
                for g in db.goals.values():
                    if g["plan_id"] == other["id"] and g["status"] in ("SET", "IN_PROGRESS"):
                        g["status"] = "CARRIED_FORWARD"
                        g["carried_to_plan_id"] = pid
                        g["resolved_at"] = db.now_iso()
                        g["resolved_at_dt"] = db.clock
                        touch(g)
                billing.cancel_sessions_early(billing.scheduled_sessions_of_plan(other["id"]))
                other["status"] = "SUPERSEDED"
                touch(other)
                # The superseded plan's coach loses one caseload seat.
                if other["coach_id"] != plan["coach_id"] and other["coach_id"] in db.coaches:
                    supervision.recompute_coach(db.coaches[other["coach_id"]])
                    touch(db.coaches[other["coach_id"]])

        plan["status"] = "ACTIVE"
        plan["activated_at"] = db.now_iso()
        plan["activated_at_dt"] = db.clock
        touch(plan)
        billing.recompute_plan_posture(plan)
        if client["status"] == "INTAKE":
            client["status"] = "ACTIVE"
        client["active_plan_id"] = pid
        touch(client)
        supervision.recompute_coach(coach)
        touch(coach)

    elif to == "COMPLETED":
        if auth["role"] != "Coach":
            E.raise_error(E.ERR_FORBIDDEN_ROLE, "Only Coach may complete a plan")
        require_coach_scope(auth, plan["coach_id"])
        if plan["status"] != "ACTIVE":
            E.raise_error(E.ERR_INVALID_STATE,
                          "Cannot transition plan from %s to COMPLETED" % plan["status"])
        if any(g["plan_id"] == pid and g["status"] in ("SET", "IN_PROGRESS")
               for g in db.goals.values()):
            E.raise_error(E.ERR_GOALS_NOT_RESOLVED,
                          "All goals must be terminal before completion")
        if billing.scheduled_sessions_of_plan(pid):
            E.raise_error(E.ERR_PLAN_HAS_OPEN_SESSIONS,
                          "Plan has sessions still SCHEDULED")
        plan["status"] = "COMPLETED"
        touch(plan)
        if client["active_plan_id"] == pid:
            client["active_plan_id"] = None
            touch(client)
        supervision.recompute_coach(coach)
        touch(coach)

    else:  # TERMINATED
        if auth["role"] == "Coach":
            E.raise_error(E.ERR_FORBIDDEN_ROLE,
                          "Coach may not terminate a plan")
        if auth["role"] == "FamilyMember":
            require_family_scope(auth, client["family_id"])
        if plan["status"] != "ACTIVE":
            E.raise_error(E.ERR_INVALID_STATE,
                          "Cannot transition plan from %s to TERMINATED" % plan["status"])
        billing.cancel_sessions_early(billing.scheduled_sessions_of_plan(pid))
        for g in db.goals.values():
            if g["plan_id"] == pid and g["status"] in ("SET", "IN_PROGRESS"):
                g["status"] = "DROPPED"
                g["resolved_at"] = db.now_iso()
                g["resolved_at_dt"] = db.clock
                touch(g)
        plan["status"] = "TERMINATED"
        touch(plan)
        if client["active_plan_id"] == pid:
            client["active_plan_id"] = None
            touch(client)
        supervision.recompute_coach(coach)
        touch(coach)

    return success_object(plan_pub(plan), 200)
