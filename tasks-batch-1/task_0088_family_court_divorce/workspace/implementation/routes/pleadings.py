"""Pleading endpoints + the petition/answer cycle (PRD §3.2)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_DUPLICATE_PETITION,
    ERR_PETITION_NOT_SERVED,
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

bp = Blueprint("pleadings", __name__)

READ_ROLES = ["Clerk", "Judge", "Mediator", "Petitioner", "Respondent"]


def _petition_for_case(case_id):
    for p in db.pleadings.values():
        if p["case_id"] == case_id and p["pleading_type"] == "PETITION":
            return p
    return None


@bp.post("/api/pleadings")
def create_pleading():
    require_auth(["Clerk", "Petitioner", "Respondent"])()
    body = get_json_body()

    case_id = body.get("case_id")
    case = get_case(case_id)  # 404 first
    filed_by_party_id = body.get("filed_by_party_id")
    party = get_party(filed_by_party_id)  # 404, left-to-right after case
    if party["case_id"] != case_id:
        raise APIError(ERR_INVALID_REQUEST, 422, "filed_by_party_id not on this case")

    assert_case_not_terminal(case)

    pleading_type = body.get("pleading_type")
    if pleading_type not in ("PETITION", "ANSWER"):
        raise APIError(ERR_INVALID_REQUEST, 422, "pleading_type must be PETITION or ANSWER")

    # Ownership: entity-backed roles may only file as their own party.
    _check_party_ownership(party)

    # At most one PETITION per case (ERR_DUPLICATE_PETITION).
    if pleading_type == "PETITION" and _petition_for_case(case_id) is not None:
        raise APIError(ERR_DUPLICATE_PETITION, 409, "A PETITION already exists on the case")

    pleading = {
        "case_id": case_id,
        "pleading_type": pleading_type,
        "filed_by_party_id": filed_by_party_id,
        "status": "DRAFT",
        "served_at": None,
    }
    db.stamp_common(pleading)
    db.pleadings[pleading["id"]] = pleading
    return ok_object(serialize(pleading), 201)


def _check_party_ownership(party):
    role = current_role()
    if role in ("Petitioner", "Respondent"):
        expected_role = "PETITIONER" if role == "Petitioner" else "RESPONDENT"
        if party["role"] != expected_role or party["user_id"] != current_user_id():
            raise APIError(ERR_FORBIDDEN_ROLE, 403, "Acting role does not own this party")


@bp.get("/api/pleadings/<rid>")
def get_pleading_route(rid):
    require_auth(READ_ROLES)()
    pleading = require(db.pleadings, rid, "Pleading")
    return ok_object(serialize(pleading), 200)


@bp.get("/api/pleadings")
def list_pleadings():
    require_auth(READ_ROLES)()
    limit, offset = paginate_params(request.args)
    items = sorted_by_creation(list(db.pleadings.values()))
    case_id = request.args.get("case_id")
    filed_by = request.args.get("filed_by_party_id")
    if case_id is not None:
        items = [p for p in items if p["case_id"] == case_id]
    if filed_by is not None:
        items = [p for p in items if p["filed_by_party_id"] == filed_by]
    page, total = slice_page(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


@bp.post("/api/pleadings/<rid>/serve")
def serve_pleading(rid):
    require_auth(["Clerk"])()
    pleading = require(db.pleadings, rid, "Pleading")
    case = get_case(pleading["case_id"])
    assert_case_not_terminal(case)

    # State gate (ERR_INVALID_STATE) — only DRAFT pleadings may be served.
    if pleading["status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, 409, "Only a DRAFT pleading can be served")

    if pleading["pleading_type"] == "ANSWER":
        # Referential: the case PETITION must already be SERVED (or ANSWERED).
        petition = _petition_for_case(case["id"])
        if petition is None or petition["status"] not in ("SERVED", "ANSWERED"):
            raise APIError(ERR_PETITION_NOT_SERVED, 409, "PETITION must be served first")

    ts = db.now_iso()
    pleading["served_at"] = ts
    pleading["status"] = "SERVED"
    db.bump(pleading)

    if pleading["pleading_type"] == "PETITION":
        # Drives Case FILED -> AWAITING_RESPONSE.
        if case["status"] == "FILED":
            case["status"] = "AWAITING_RESPONSE"
            db.bump(case)
    else:  # ANSWER
        # Drives Case AWAITING_RESPONSE -> CONTESTED; PETITION -> ANSWERED.
        if case["status"] == "AWAITING_RESPONSE":
            case["status"] = "CONTESTED"
            db.bump(case)
            petition = _petition_for_case(case["id"])
            if petition is not None and petition["status"] == "SERVED":
                petition["status"] = "ANSWERED"
                db.bump(petition)

    return ok_object(serialize(pleading), 200)
