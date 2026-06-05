"""Party and Child endpoints (PRD §3.2)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_INVALID_REQUEST, ERR_DUPLICATE_PARTY_ROLE
from middleware import require_auth, get_json_body, paginate_params, slice_page
from response import ok_object, ok_array
from services.common import (
    serialize,
    serialize_list,
    sorted_by_creation,
    get_case,
    assert_case_not_terminal,
    party_with_role,
    require,
)

bp = Blueprint("parties", __name__)

READ_ROLES = ["Clerk", "Judge", "Mediator", "Petitioner", "Respondent"]


@bp.post("/api/parties")
def create_party():
    require_auth(["Clerk"])()
    body = get_json_body()
    case_id = body.get("case_id")
    case = get_case(case_id)  # existence (404) before terminal check
    assert_case_not_terminal(case)

    role = body.get("role")
    if role not in ("PETITIONER", "RESPONDENT"):
        raise APIError(ERR_INVALID_REQUEST, 422, "role must be PETITIONER or RESPONDENT")
    user_id = body.get("user_id")
    if not isinstance(user_id, str) or user_id == "":
        raise APIError(ERR_INVALID_REQUEST, 422, "user_id is required")
    full_name = body.get("full_name")
    if not isinstance(full_name, str) or full_name == "":
        raise APIError(ERR_INVALID_REQUEST, 422, "full_name is required")
    income = body.get("gross_monthly_income_cents")
    if not isinstance(income, int) or isinstance(income, bool) or income < 0:
        raise APIError(ERR_INVALID_REQUEST, 422, "gross_monthly_income_cents must be an integer >= 0")

    # At most one party per role per case (ERR_DUPLICATE_PARTY_ROLE).
    if party_with_role(case_id, role) is not None:
        raise APIError(ERR_DUPLICATE_PARTY_ROLE, 409, f"A {role} already exists on the case")

    party = {
        "case_id": case_id,
        "role": role,
        "user_id": user_id,
        "full_name": full_name,
        "gross_monthly_income_cents": income,
    }
    db.stamp_common(party)
    db.parties[party["id"]] = party
    return ok_object(serialize(party), 201)


@bp.get("/api/parties/<rid>")
def get_party_route(rid):
    require_auth(READ_ROLES)()
    party = require(db.parties, rid, "Party")
    return ok_object(serialize(party), 200)


@bp.get("/api/parties")
def list_parties():
    require_auth(READ_ROLES)()
    limit, offset = paginate_params(request.args)
    items = sorted_by_creation(list(db.parties.values()))
    case_id = request.args.get("case_id")
    if case_id is not None:
        items = [p for p in items if p["case_id"] == case_id]
    page, total = slice_page(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


# ----- Child -----
@bp.post("/api/children")
def create_child():
    require_auth(["Clerk"])()
    body = get_json_body()
    case_id = body.get("case_id")
    case = get_case(case_id)
    assert_case_not_terminal(case)

    full_name = body.get("full_name")
    if not isinstance(full_name, str) or full_name == "":
        raise APIError(ERR_INVALID_REQUEST, 422, "full_name is required")
    birth_year = body.get("birth_year")
    if not isinstance(birth_year, int) or isinstance(birth_year, bool) or birth_year < 1900:
        raise APIError(ERR_INVALID_REQUEST, 422, "birth_year must be an integer >= 1900")

    child = {
        "case_id": case_id,
        "full_name": full_name,
        "birth_year": birth_year,
    }
    db.stamp_common(child)
    db.children[child["id"]] = child
    return ok_object(serialize(child), 201)


@bp.get("/api/children/<rid>")
def get_child_route(rid):
    require_auth(READ_ROLES)()
    child = require(db.children, rid, "Child")
    return ok_object(serialize(child), 200)


@bp.get("/api/children")
def list_children():
    require_auth(READ_ROLES)()
    limit, offset = paginate_params(request.args)
    items = sorted_by_creation(list(db.children.values()))
    case_id = request.args.get("case_id")
    if case_id is not None:
        items = [c for c in items if c["case_id"] == case_id]
    page, total = slice_page(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)
