"""InvestigatorAssignment endpoints (PRD 3.3)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE_TRANSITION, ERR_FORBIDDEN_ROLE,
    ERR_INVESTIGATOR_ALREADY_ACTIVE, ERR_SEGREGATION_OF_DUTIES,
)
from middleware import authorized, STAFF_READ_ROLES
from response import success_list, success_object
from services.core import (
    new_record, touch, public, bump_case, append_event, get_case,
    check_case_not_terminal, get_pagination, sort_items, apply_filters,
    check_not_case_party, check_segregation,
)
from validate import get_body, req_str, require_path, require_profile_fk

bp = Blueprint("assignments", __name__)


@bp.post("/cases/<cid>/investigator-assignments")
def propose_assignment(cid):
    caller = authorized(["TitleIXCoordinator"])
    case = get_case(cid)
    check_case_not_terminal(case)
    body = get_body()
    # Tier 3: body FK existence.
    require_profile_fk(body, "investigator_id")
    investigator_id = body.get("investigator_id")
    if isinstance(investigator_id, str):
        # Tier 5: party bar (more specific) then segregation.
        check_not_case_party(case, investigator_id)
        check_segregation(case, investigator_id, for_function="investigator")
        # Tier 7: one ACTIVE assignment per case.
        if any(a["case_id"] == cid and a["status"] == "ACTIVE"
               for a in db["investigator_assignments"].values()):
            raise_error(ERR_INVESTIGATOR_ALREADY_ACTIVE,
                        "another investigator assignment on this case is ACTIVE")
    # Tier 11: schema.
    investigator_id = req_str(body, "investigator_id")
    rec = new_record("investigator_assignments", {
        "case_id": cid,
        "investigator_id": investigator_id,
        "status": "PROPOSED",
        "recusal_reason": None,
    })
    append_event(cid, "INVESTIGATOR_PROPOSED", caller,
                 {"assignment_id": rec["id"], "investigator_id": investigator_id})
    return success_object(public(rec), 201)


@bp.get("/cases/<cid>/investigator-assignments")
def list_assignments(cid):
    authorized(STAFF_READ_ROLES)
    get_case(cid)
    items = [a for a in db["investigator_assignments"].values() if a["case_id"] == cid]
    items = apply_filters(items, {"status": request.args.get("status")})
    items = sort_items(items)
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


@bp.get("/investigator-assignments/<aid>")
def get_assignment(aid):
    authorized(STAFF_READ_ROLES)
    rec = require_path("investigator_assignments", aid)
    return success_object(public(rec))


@bp.get("/investigator-assignments")
def list_assignments_filtered():
    authorized(["TitleIXCoordinator", "CaseAdministrator"])
    items = list(db["investigator_assignments"].values())
    items = apply_filters(items, {
        "investigator_id": request.args.get("investigator_id"),
        "status": request.args.get("status"),
    })
    items = sort_items(items)
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


@bp.post("/investigator-assignments/<aid>/accept")
def accept_assignment(aid):
    caller = authorized(["Investigator"])
    asg = require_path("investigator_assignments", aid)
    case = get_case(asg["case_id"])
    if asg["status"] != "PROPOSED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"assignment is {asg['status']}, not PROPOSED")
    if caller.user_id != asg["investigator_id"]:
        raise_error(ERR_FORBIDDEN_ROLE,
                    "only the proposed investigator may accept the assignment")
    # Tier 5: full segregation re-check at acceptance (party inclusion here is
    # the generic segregation error per the validation applies_to lists).
    if caller.user_id in (case["complainant_id"], case["respondent_id"]):
        raise_error(ERR_SEGREGATION_OF_DUTIES,
                    "the acceptor is a case party")
    check_segregation(case, caller.user_id, for_function="investigator",
                      exclude_assignment_id=aid)
    # The strict accept rule also bars holding another LIVE (PROPOSED/ACTIVE)
    # assignment of one's own on the case; a COMPLETED prior assignment of the
    # same person does not bar re-service (the remand cycle re-engages them).
    if any(a["case_id"] == case["id"] and a["id"] != aid
           and a["investigator_id"] == caller.user_id
           and a["status"] in ("PROPOSED", "ACTIVE")
           for a in db["investigator_assignments"].values()):
        raise_error(ERR_SEGREGATION_OF_DUTIES,
                    "the acceptor already holds another live investigator assignment on this case")
    # Tier 7: no other ACTIVE assignment on the case.
    if any(a["case_id"] == case["id"] and a["status"] == "ACTIVE" and a["id"] != aid
           for a in db["investigator_assignments"].values()):
        raise_error(ERR_INVESTIGATOR_ALREADY_ACTIVE,
                    "another investigator assignment on this case is ACTIVE")
    asg["status"] = "ACTIVE"
    touch(asg)
    bump_case(case)
    append_event(case["id"], "INVESTIGATOR_ACCEPTED", caller,
                 {"assignment_id": aid, "status": "ACTIVE"})
    return success_object(public(asg))


@bp.post("/investigator-assignments/<aid>/decline")
def decline_assignment(aid):
    caller = authorized(["Investigator"])
    asg = require_path("investigator_assignments", aid)
    case = get_case(asg["case_id"])
    if asg["status"] != "PROPOSED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"assignment is {asg['status']}, not PROPOSED")
    if caller.user_id != asg["investigator_id"]:
        raise_error(ERR_FORBIDDEN_ROLE,
                    "only the proposed investigator may decline the assignment")
    asg["status"] = "DECLINED"
    touch(asg)
    bump_case(case)
    append_event(case["id"], "INVESTIGATOR_DECLINED", caller,
                 {"assignment_id": aid, "status": "DECLINED"})
    return success_object(public(asg))


@bp.post("/investigator-assignments/<aid>/recuse")
def recuse_assignment(aid):
    caller = authorized(["Investigator", "TitleIXCoordinator"])
    asg = require_path("investigator_assignments", aid)
    case = get_case(asg["case_id"])
    if asg["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"assignment is {asg['status']}, not ACTIVE")
    if caller.user_id != asg["investigator_id"] and caller.user_id != case["coordinator_id"]:
        raise_error(ERR_FORBIDDEN_ROLE,
                    "only the assigned investigator or the case coordinator may recuse")
    body = get_body()
    recusal_reason = req_str(body, "recusal_reason")
    asg["recusal_reason"] = recusal_reason
    asg["status"] = "RECUSED"
    touch(asg)
    bump_case(case)
    append_event(case["id"], "INVESTIGATOR_RECUSED", caller,
                 {"assignment_id": aid, "status": "RECUSED"})
    return success_object(public(asg))
