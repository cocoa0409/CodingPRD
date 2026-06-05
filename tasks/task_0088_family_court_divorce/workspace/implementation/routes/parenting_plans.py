"""ParentingPlan endpoints + revision loop (PRD §3.4)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_OVERNIGHTS_NOT_365,
    ERR_DUPLICATE_PLAN,
    ERR_NOT_DISPUTING_PARTY,
    ERR_FORBIDDEN_ROLE,
)
from middleware import (
    require_auth,
    get_json_body,
    paginate_params,
    slice_page,
    current_role,
    current_user_id,
)
from response import ok_object, ok_array
from services.common import (
    serialize,
    serialize_list,
    sorted_by_creation,
    get_case,
    get_party,
    assert_case_not_terminal,
    require,
)
from services.calculations import parenting_time_percentage, TOTAL_OVERNIGHTS

bp = Blueprint("parenting_plans", __name__)

READ_ROLES = ["Clerk", "Judge", "Mediator", "Petitioner", "Respondent"]


def _plan_for_case(case_id):
    for p in db.parenting_plans.values():
        if p["case_id"] == case_id:
            return p
    return None


def _validate_overnights(body):
    pet = body.get("petitioner_overnights")
    resp = body.get("respondent_overnights")
    for name, v in (("petitioner_overnights", pet), ("respondent_overnights", resp)):
        if not isinstance(v, int) or isinstance(v, bool):
            raise APIError(ERR_INVALID_REQUEST, 422, f"{name} must be an integer")
    if not (0 <= pet <= 365):
        raise APIError(ERR_INVALID_REQUEST, 422, "petitioner_overnights must be 0..365")
    if not (0 <= resp <= 365):
        raise APIError(ERR_INVALID_REQUEST, 422, "respondent_overnights must be 0..365")
    if pet + resp != TOTAL_OVERNIGHTS:
        raise APIError(ERR_OVERNIGHTS_NOT_365, 422, "overnights must sum to 365")
    return pet, resp


def _acting_party_for_case(case_id):
    """Resolve the entity-backed acting Party on this case (Petitioner/Respondent).

    Returns the Party dict, or raises ERR_FORBIDDEN_ROLE if the caller's
    role/user_id does not bind to a party of the expected role on the case.
    """
    role = current_role()
    expected_role = "PETITIONER" if role == "Petitioner" else "RESPONDENT"
    uid = current_user_id()
    for p in db.parties.values():
        if p["case_id"] == case_id and p["role"] == expected_role and p["user_id"] == uid:
            return p
    raise APIError(ERR_FORBIDDEN_ROLE, 403, "No bound party for the acting role on this case")


@bp.post("/api/parenting-plans")
def create_plan():
    require_auth(["Petitioner", "Respondent"])()
    body = get_json_body()

    case_id = body.get("case_id")
    case = get_case(case_id)
    proposed_by = body.get("proposed_by_party_id")
    proposer = get_party(proposed_by)
    if proposer["case_id"] != case_id:
        raise APIError(ERR_INVALID_REQUEST, 422, "proposed_by_party_id not on this case")

    assert_case_not_terminal(case)

    pet, resp = _validate_overnights(body)

    # Ownership: the proposer must be the acting entity-backed party.
    acting = _acting_party_for_case(case_id)
    if acting["id"] != proposer["id"]:
        raise APIError(ERR_FORBIDDEN_ROLE, 403, "Acting role does not own the proposing party")

    # At most one plan per case (ERR_DUPLICATE_PLAN).
    if _plan_for_case(case_id) is not None:
        raise APIError(ERR_DUPLICATE_PLAN, 409, "A parenting plan already exists on the case")

    plan = {
        "case_id": case_id,
        "proposed_by_party_id": proposed_by,
        "petitioner_overnights": pet,
        "respondent_overnights": resp,
        "petitioner_time_pct": parenting_time_percentage(pet),
        "status": "PROPOSED",
    }
    db.stamp_common(plan)
    db.parenting_plans[plan["id"]] = plan
    return ok_object(serialize(plan), 201)


@bp.get("/api/parenting-plans/<rid>")
def get_plan(rid):
    require_auth(READ_ROLES)()
    plan = require(db.parenting_plans, rid, "ParentingPlan")
    return ok_object(serialize(plan), 200)


@bp.get("/api/parenting-plans")
def list_plans():
    require_auth(READ_ROLES)()
    limit, offset = paginate_params(request.args)
    items = sorted_by_creation(list(db.parenting_plans.values()))
    case_id = request.args.get("case_id")
    proposed_by = request.args.get("proposed_by_party_id")
    if case_id is not None:
        items = [p for p in items if p["case_id"] == case_id]
    if proposed_by is not None:
        items = [p for p in items if p["proposed_by_party_id"] == proposed_by]
    page, total = slice_page(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


def _require_non_proposer(plan):
    """ERR_NOT_DISPUTING_PARTY (403): acting party must NOT be the proposer of
    the current version (PRD §3.4)."""
    acting = _acting_party_for_case(plan["case_id"])
    if acting["id"] == plan["proposed_by_party_id"]:
        raise APIError(ERR_NOT_DISPUTING_PARTY, 403, "Proposer may not act on its own version")
    return acting


@bp.post("/api/parenting-plans/<rid>/dispute")
def dispute_plan(rid):
    require_auth(["Petitioner", "Respondent"])()
    plan = require(db.parenting_plans, rid, "ParentingPlan")
    case = get_case(plan["case_id"])
    assert_case_not_terminal(case)
    if plan["status"] not in ("PROPOSED", "REVISED"):
        raise APIError(ERR_INVALID_STATE, 409, "Dispute requires PROPOSED or REVISED")
    _require_non_proposer(plan)
    plan["status"] = "DISPUTED"
    db.bump(plan)
    return ok_object(serialize(plan), 200)


@bp.post("/api/parenting-plans/<rid>/revise")
def revise_plan(rid):
    require_auth(["Petitioner", "Respondent"])()
    plan = require(db.parenting_plans, rid, "ParentingPlan")
    case = get_case(plan["case_id"])
    assert_case_not_terminal(case)
    body = get_json_body()
    if plan["status"] != "DISPUTED":
        raise APIError(ERR_INVALID_STATE, 409, "Revise requires DISPUTED")
    pet, resp = _validate_overnights(body)
    acting = _acting_party_for_case(plan["case_id"])
    plan["petitioner_overnights"] = pet
    plan["respondent_overnights"] = resp
    plan["proposed_by_party_id"] = acting["id"]
    plan["petitioner_time_pct"] = parenting_time_percentage(pet)
    plan["status"] = "REVISED"
    db.bump(plan)
    return ok_object(serialize(plan), 200)


@bp.post("/api/parenting-plans/<rid>/agree")
def agree_plan(rid):
    require_auth(["Petitioner", "Respondent"])()
    plan = require(db.parenting_plans, rid, "ParentingPlan")
    case = get_case(plan["case_id"])
    assert_case_not_terminal(case)
    if plan["status"] not in ("PROPOSED", "REVISED"):
        raise APIError(ERR_INVALID_STATE, 409, "Agree requires PROPOSED or REVISED")
    _require_non_proposer(plan)
    plan["status"] = "AGREED"
    db.bump(plan)
    return ok_object(serialize(plan), 200)
