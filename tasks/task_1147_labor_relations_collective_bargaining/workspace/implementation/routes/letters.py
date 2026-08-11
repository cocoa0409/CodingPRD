"""SideLetter endpoints."""

from flask import Blueprint, request

from db import db
from errors import (
    ERR_INVALID_EFFECTIVE_RANGE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_SIDE_LETTER_OVERLAP,
    ERR_SOD_VIOLATION,
    ERR_UNAUTHORIZED_ROLE,
    raise_err,
)
from helpers import (
    ALL_ROLES, authenticate, get_body, lookup, new_entity, page, parse_pagination,
    req_datetime, req_enum, req_string, serialize, sort_items, touch,
)
from response import success_list, success_object

bp = Blueprint("letters", __name__)

LETTER_STATUSES = ("DRAFT", "PENDING_LEGAL", "EXECUTED", "EXPIRED", "SUPERSEDED")


@bp.post("/labor-relations/side-letters")
def create_letter():
    user_id, role = authenticate(["LRManager"])
    body = get_body()
    agreement_id = req_string(body, "agreement_id")
    clause_id = req_string(body, "clause_id")
    letter_type = req_enum(body, "letter_type", ("SIDE_LETTER", "MOA", "MOU"))
    title = req_string(body, "title")
    effective_start = req_datetime(body, "effective_start")
    effective_end = req_datetime(body, "effective_end")

    agreement = lookup(db.agreements, agreement_id, "CollectiveAgreement")
    clause = lookup(db.clauses, clause_id, "Clause")
    if clause["agreement_id"] != agreement_id:
        raise_err(ERR_INVALID_REQUEST, "clause_id does not belong to the given agreement")
    if agreement["status"] in ("ARCHIVED", "REPLACED"):
        raise_err(ERR_INVALID_STATE, "Cannot create a side letter on a %s agreement" % agreement["status"])
    if effective_end < effective_start:
        raise_err(ERR_INVALID_EFFECTIVE_RANGE, "effective_end must be on or after effective_start")

    letter = new_entity()
    letter.update({
        "agreement_id": agreement_id,
        "clause_id": clause_id,
        "letter_type": letter_type,
        "title": title,
        "effective_start": effective_start,
        "effective_end": effective_end,
        "status": "DRAFT",
        "drafted_by_user_id": user_id,
        "executed_by_user_id": None,
    })
    db.letters[letter["id"]] = letter
    return success_object(serialize(letter), status=201)


@bp.get("/labor-relations/side-letters")
def list_letters():
    authenticate(ALL_ROLES)
    limit, offset = parse_pagination()
    agreement_id = request.args.get("agreement_id")
    clause_id = request.args.get("clause_id")
    status = request.args.get("status")
    items = list(db.letters.values())
    if agreement_id is not None:
        items = [l for l in items if l["agreement_id"] == agreement_id]
    if clause_id is not None:
        items = [l for l in items if l["clause_id"] == clause_id]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    items = sort_items(items)
    slice_, total = page(items, limit, offset)
    return success_list([serialize(l) for l in slice_], limit, offset, total)


@bp.get("/labor-relations/side-letters/<letter_id>")
def get_letter(letter_id):
    authenticate(ALL_ROLES)
    letter = lookup(db.letters, letter_id, "SideLetter")
    return success_object(serialize(letter))


@bp.post("/labor-relations/side-letters/<letter_id>/state")
def transition_letter(letter_id):
    user_id, role = authenticate(["LRManager", "LegalCounsel"])
    letter = lookup(db.letters, letter_id, "SideLetter")
    body = get_body()
    to_status = req_string(body, "to_status")
    if to_status not in LETTER_STATUSES:
        raise_err(ERR_INVALID_REQUEST, "Unknown side-letter status: %s" % to_status)
    if to_status in ("EXPIRED", "SUPERSEDED"):
        raise_err(ERR_INVALID_STATE, "Cannot transition a side letter to %s via this endpoint" % to_status)

    # Per-transition role gating (priority 3 style)
    if to_status == "PENDING_LEGAL" and role != "LRManager":
        raise_err(ERR_UNAUTHORIZED_ROLE, "Only LRManager may submit a letter for legal review")
    if to_status in ("EXECUTED", "DRAFT") and role != "LegalCounsel":
        raise_err(ERR_UNAUTHORIZED_ROLE, "Only LegalCounsel may execute or return a letter")

    if to_status == "PENDING_LEGAL":
        if letter["status"] != "DRAFT":
            raise_err(ERR_INVALID_STATE, "Only a DRAFT letter can be submitted for legal review")
        letter["status"] = "PENDING_LEGAL"

    elif to_status == "DRAFT":
        if letter["status"] != "PENDING_LEGAL":
            raise_err(ERR_INVALID_STATE, "Only a PENDING_LEGAL letter can be returned to DRAFT")
        letter["status"] = "DRAFT"

    else:  # EXECUTED
        if letter["status"] != "PENDING_LEGAL":
            raise_err(ERR_INVALID_STATE, "Only a PENDING_LEGAL letter can be executed")
        agreement = lookup(db.agreements, letter["agreement_id"], "CollectiveAgreement")
        if agreement["status"] not in ("ACTIVE", "EXTENDED"):
            raise_err(ERR_INVALID_STATE, "The letter's agreement must be ACTIVE or EXTENDED to execute")
        if user_id == letter["drafted_by_user_id"]:
            raise_err(ERR_SOD_VIOLATION, "Executor must differ from drafted_by_user_id")
        # Closed-interval overlap among EXECUTED letters on the same clause;
        # touching boundaries conflict
        for other in db.letters.values():
            if (other["id"] != letter["id"] and other["clause_id"] == letter["clause_id"]
                    and other["status"] == "EXECUTED"
                    and letter["effective_start"] <= other["effective_end"]
                    and other["effective_start"] <= letter["effective_end"]):
                raise_err(ERR_SIDE_LETTER_OVERLAP, "Overlaps an EXECUTED side letter on the same clause")
        letter["executed_by_user_id"] = user_id
        letter["status"] = "EXECUTED"

    touch(letter)
    return success_object(serialize(letter))
