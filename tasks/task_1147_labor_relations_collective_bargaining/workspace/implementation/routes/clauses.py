"""Clause endpoints and the interpretation workflow."""

from flask import Blueprint, request

from db import db
from errors import (
    ERR_DUPLICATE_ARTICLE_REF,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_RESOLUTION_REFERENCE_INVALID,
    ERR_UNAUTHORIZED_ROLE,
    ERR_UNION_MISMATCH,
    raise_err,
)
from helpers import (
    ALL_ROLES, authenticate, get_body, lookup, new_entity, opt_bool, page,
    parse_pagination, req_string, serialize, sort_items, touch,
)
from response import success_list, success_object

bp = Blueprint("clauses", __name__)

ACTIONS = ("OPEN_REVIEW", "CLOSE_REVIEW", "RECORD", "DISPUTE", "RESOLVE")

# Per-action role gating (PRD 3.2): disallowed action-per-role pairs -> ERR_UNAUTHORIZED_ROLE
ACTION_ROLES = {
    "OPEN_REVIEW": {"LRManager"},
    "CLOSE_REVIEW": {"LRManager"},
    "RECORD": {"LegalCounsel"},
    "DISPUTE": {"LRManager", "UnionRepresentative"},
    "RESOLVE": {"LegalCounsel"},
}


@bp.post("/labor-relations/clauses")
def create_clause():
    authenticate(["LRManager"])
    body = get_body()
    agreement_id = req_string(body, "agreement_id")
    article_ref = req_string(body, "article_ref")
    title = req_string(body, "title")
    body_text = req_string(body, "body_text")
    is_economic = opt_bool(body, "is_economic", False)

    agreement = lookup(db.agreements, agreement_id, "CollectiveAgreement")
    if agreement["status"] in ("ARCHIVED", "REPLACED"):
        raise_err(ERR_INVALID_STATE, "Cannot create a clause on a %s agreement" % agreement["status"])
    for existing in db.clauses.values():
        if existing["agreement_id"] == agreement_id and existing["article_ref"] == article_ref:
            raise_err(ERR_DUPLICATE_ARTICLE_REF, "article_ref %s already exists in this agreement" % article_ref)

    clause = new_entity()
    clause.update({
        "agreement_id": agreement_id,
        "article_ref": article_ref,
        "title": title,
        "body_text": body_text,
        "is_economic": is_economic,
        "interpretation_status": "UNINTERPRETED",
        "interpretation_text": None,
        "resolved_by_ref": None,
    })
    db.clauses[clause["id"]] = clause
    return success_object(serialize(clause), status=201)


@bp.get("/labor-relations/clauses")
def list_clauses():
    authenticate(ALL_ROLES)
    limit, offset = parse_pagination()
    agreement_id = request.args.get("agreement_id")
    interpretation_status = request.args.get("interpretation_status")
    items = list(db.clauses.values())
    if agreement_id is not None:
        items = [c for c in items if c["agreement_id"] == agreement_id]
    if interpretation_status is not None:
        items = [c for c in items if c["interpretation_status"] == interpretation_status]
    items = sort_items(items)
    slice_, total = page(items, limit, offset)
    return success_list([serialize(c) for c in slice_], limit, offset, total)


@bp.get("/labor-relations/clauses/<clause_id>")
def get_clause(clause_id):
    authenticate(ALL_ROLES)
    clause = lookup(db.clauses, clause_id, "Clause")
    return success_object(serialize(clause))


@bp.post("/labor-relations/clauses/<clause_id>/interpretation")
def clause_interpretation(clause_id):
    user_id, role = authenticate(["LRManager", "LegalCounsel", "UnionRepresentative"])
    clause = lookup(db.clauses, clause_id, "Clause")
    body = get_body()
    action = req_string(body, "action")
    if action not in ACTIONS:
        raise_err(ERR_INVALID_REQUEST, "Unknown interpretation action: %s" % action)

    # Per-action role gating (priority 3, reported as ERR_UNAUTHORIZED_ROLE)
    if role not in ACTION_ROLES[action]:
        raise_err(ERR_UNAUTHORIZED_ROLE, "Role %s may not perform %s" % (role, action))

    agreement = lookup(db.agreements, clause["agreement_id"], "CollectiveAgreement")

    # UnionRepresentative ownership: X-User-ID must equal the agreement's union_id
    if role == "UnionRepresentative" and user_id != agreement["union_id"]:
        raise_err(ERR_UNION_MISMATCH, "X-User-ID does not match the agreement's union_id")

    status = clause["interpretation_status"]

    if action == "OPEN_REVIEW":
        if status != "UNINTERPRETED":
            raise_err(ERR_INVALID_STATE, "Only an UNINTERPRETED clause can enter review")
        clause["interpretation_status"] = "UNDER_REVIEW"

    elif action == "CLOSE_REVIEW":
        if status != "UNDER_REVIEW":
            raise_err(ERR_INVALID_STATE, "Only an UNDER_REVIEW clause can close review")
        clause["interpretation_status"] = "UNINTERPRETED"

    elif action == "RECORD":
        interpretation_text = body.get("interpretation_text")
        if not isinstance(interpretation_text, str) or not interpretation_text.strip():
            raise_err(ERR_INVALID_REQUEST, "interpretation_text is required for RECORD")
        if status != "UNDER_REVIEW":
            raise_err(ERR_INVALID_STATE, "Only an UNDER_REVIEW clause can be recorded")
        clause["interpretation_text"] = interpretation_text
        clause["interpretation_status"] = "INTERPRETED"

    elif action == "DISPUTE":
        if status not in ("INTERPRETED", "RESOLVED"):
            raise_err(ERR_INVALID_STATE, "Only an INTERPRETED or RESOLVED clause can be disputed")
        if status == "RESOLVED":
            clause["resolved_by_ref"] = None  # re-dispute clears the resolution reference
        clause["interpretation_status"] = "DISPUTED"

    elif action == "RESOLVE":
        side_letter_id = body.get("side_letter_id")
        past_practice_id = body.get("past_practice_id")
        if (side_letter_id is None) == (past_practice_id is None):
            raise_err(ERR_INVALID_REQUEST, "Exactly one of side_letter_id / past_practice_id is required")
        if side_letter_id is not None and not isinstance(side_letter_id, str):
            raise_err(ERR_INVALID_REQUEST, "side_letter_id must be a string")
        if past_practice_id is not None and not isinstance(past_practice_id, str):
            raise_err(ERR_INVALID_REQUEST, "past_practice_id must be a string")
        # Reference resolution (priority 5) precedes the state check (priority 6)
        letter = practice = None
        if side_letter_id is not None:
            letter = lookup(db.letters, side_letter_id, "SideLetter")
        else:
            practice = lookup(db.practices, past_practice_id, "PastPractice")
        if status != "DISPUTED":
            raise_err(ERR_INVALID_STATE, "Only a DISPUTED clause can be resolved")
        if letter is not None:
            if letter["status"] != "EXECUTED":
                raise_err(ERR_RESOLUTION_REFERENCE_INVALID, "Cited side letter is not EXECUTED")
            clause["resolved_by_ref"] = side_letter_id
        else:
            if practice["status"] != "VERIFIED":
                raise_err(ERR_RESOLUTION_REFERENCE_INVALID, "Cited past practice is not VERIFIED")
            clause["resolved_by_ref"] = past_practice_id
        clause["interpretation_status"] = "RESOLVED"

    touch(clause)
    return success_object(serialize(clause))
