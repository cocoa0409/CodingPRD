"""IntakeAssessment endpoints: create, list, read, workflow transitions."""
from flask import Blueprint

import db
import errors as E
import middleware as mw
from middleware import (get_auth, require_roles, require_family_scope, get_body,
                        require_fields, get_entity, touch, new_common, intake_pub,
                        plan_pub, list_response)
from response import success_object

bp = Blueprint("intakes", __name__)


@bp.post("/clients/<cid>/intakes")
def create_intake(cid):
    auth = get_auth()
    require_roles(auth, ["FamilyMember", "PracticeAdmin"])
    client = get_entity("client", cid)
    require_family_scope(auth, client["family_id"])
    body = get_body()
    require_fields(body, ["presenting_concerns", "baseline_score"])
    mw.int_check(body["baseline_score"], "baseline_score", minimum=0, maximum=100)
    i = new_common()
    i.update({
        "client_id": cid,
        "presenting_concerns": body["presenting_concerns"],
        "baseline_score": body["baseline_score"],
        "review_notes": None,
        "status": "DRAFT",
    })
    db.intakes[i["id"]] = i
    return success_object(intake_pub(i), 201)


@bp.get("/clients/<cid>/intakes")
def list_intakes(cid):
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin", "Coach", "FamilyMember"])
    client = get_entity("client", cid)
    require_family_scope(auth, client["family_id"])
    rows = [i for i in db.intakes.values() if i["client_id"] == cid]
    return list_response(rows, intake_pub, paginate=False)


@bp.get("/intakes/<iid>")
def get_intake(iid):
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin", "Coach", "FamilyMember"])
    i = get_entity("intake", iid)
    client = db.clients[i["client_id"]]
    require_family_scope(auth, client["family_id"])
    return success_object(intake_pub(i), 200)


@bp.post("/intakes/<iid>/transition")
def intake_transition(iid):
    auth = get_auth()
    require_roles(auth, ["Coach", "FamilyMember"])
    i = get_entity("intake", iid)
    client = db.clients[i["client_id"]]
    body = get_body()
    require_fields(body, ["to_state"])
    to = body["to_state"]
    mw.enum_check(to, ["SUBMITTED", "UNDER_REVIEW", "APPROVED", "NEEDS_REVISION", "DRAFT"],
                  "to_state")

    if to == "SUBMITTED":
        if auth["role"] != "FamilyMember":
            E.raise_error(E.ERR_FORBIDDEN_ROLE,
                          "Only FamilyMember may submit an intake")
        require_family_scope(auth, client["family_id"])
        if i["status"] != "DRAFT":
            E.raise_error(E.ERR_INVALID_STATE,
                          "Cannot transition intake from %s to SUBMITTED" % i["status"])
        if not i["presenting_concerns"] or i["baseline_score"] is None:
            E.raise_error(E.ERR_VALIDATION,
                          "presenting_concerns must be non-empty and baseline_score present")
        i["status"] = "SUBMITTED"

    elif to == "UNDER_REVIEW":
        if auth["role"] != "Coach":
            E.raise_error(E.ERR_FORBIDDEN_ROLE,
                          "Only Coach may move an intake to UNDER_REVIEW")
        if i["status"] != "SUBMITTED":
            E.raise_error(E.ERR_INVALID_STATE,
                          "Cannot transition intake from %s to UNDER_REVIEW" % i["status"])
        i["status"] = "UNDER_REVIEW"

    elif to == "APPROVED":
        if auth["role"] != "Coach":
            E.raise_error(E.ERR_FORBIDDEN_ROLE,
                          "Only Coach may approve an intake")
        if i["status"] != "UNDER_REVIEW":
            E.raise_error(E.ERR_INVALID_STATE,
                          "Cannot transition intake from %s to APPROVED" % i["status"])
        coach = db.coaches.get(auth["user_id"])
        if coach is None or coach["credential_level"] not in ("CERTIFIED", "SUPERVISOR"):
            E.raise_error(E.ERR_CREDENTIAL_INSUFFICIENT,
                          "Intake approval requires CERTIFIED or SUPERVISOR credential")
        i["status"] = "APPROVED"

    elif to == "NEEDS_REVISION":
        if auth["role"] != "Coach":
            E.raise_error(E.ERR_FORBIDDEN_ROLE,
                          "Only Coach may request intake revision")
        if i["status"] != "UNDER_REVIEW":
            E.raise_error(E.ERR_INVALID_STATE,
                          "Cannot transition intake from %s to NEEDS_REVISION" % i["status"])
        if not body.get("review_notes"):
            E.raise_error(E.ERR_VALIDATION, "review_notes are required for NEEDS_REVISION")
        i["review_notes"] = body["review_notes"]
        i["status"] = "NEEDS_REVISION"

    else:  # DRAFT (revision loop)
        if auth["role"] != "FamilyMember":
            E.raise_error(E.ERR_FORBIDDEN_ROLE,
                          "Only FamilyMember may return an intake to DRAFT")
        require_family_scope(auth, client["family_id"])
        if i["status"] != "NEEDS_REVISION":
            E.raise_error(E.ERR_INVALID_STATE,
                          "Cannot transition intake from %s to DRAFT" % i["status"])
        i["status"] = "DRAFT"

    touch(i)
    return success_object(intake_pub(i), 200)


@bp.get("/intakes/<iid>/plans")
def intake_plans(iid):
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin", "Coach"])
    get_entity("intake", iid)
    rows = [p for p in db.plans.values() if p["intake_id"] == iid]
    return list_response(rows, plan_pub, paginate=False)
