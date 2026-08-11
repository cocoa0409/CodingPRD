"""PastPractice endpoints with dual-variant strength scoring and abandonment cycle."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import clock
from db import db
from errors import (
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_PRACTICE_NOT_VERIFIABLE,
    ERR_UNAUTHORIZED_ROLE,
    ERR_UNION_MISMATCH,
    raise_err,
)
from helpers import (
    ALL_ROLES, authenticate, get_body, lookup, new_entity, opt_string, page,
    parse_pagination, req_datetime, req_int, req_string, serialize, sort_items, touch,
)
from response import success_list, success_object

bp = Blueprint("practices", __name__)

PRACTICE_STATUSES = ("ASSERTED", "DOCUMENTED", "VERIFIED", "DISPUTED", "NOTICE_GIVEN", "ABANDONED")


@bp.post("/labor-relations/past-practices")
def create_practice():
    user_id, role = authenticate(["LRManager", "UnionRepresentative"])
    body = get_body()
    union_id = req_string(body, "union_id")
    clause_id = opt_string(body, "clause_id")
    title = req_string(body, "title")
    description = req_string(body, "description")
    first_observed_date = req_datetime(body, "first_observed_date")
    last_observed_date = req_datetime(body, "last_observed_date")
    occurrence_count = req_int(body, "occurrence_count")
    if occurrence_count < 1:
        raise_err(ERR_INVALID_REQUEST, "occurrence_count must be >= 1")

    lookup(db.unions, union_id, "Union")
    if clause_id is not None:
        lookup(db.clauses, clause_id, "Clause")

    # UnionRepresentative may only assert for their own union
    if role == "UnionRepresentative" and user_id != union_id:
        raise_err(ERR_UNION_MISMATCH, "X-User-ID does not match the practice's union_id")

    if last_observed_date < first_observed_date:
        raise_err(ERR_INVALID_REQUEST, "last_observed_date must be on or after first_observed_date")

    practice = new_entity()
    practice.update({
        "union_id": union_id,
        "clause_id": clause_id,
        "title": title,
        "description": description,
        "first_observed_date": first_observed_date,
        "last_observed_date": last_observed_date,
        "occurrence_count": occurrence_count,
        "status": "ASSERTED",
        "strength_legalistic": None,
        "strength_operational": None,
        "asserted_by_user_id": user_id,
        "abandon_effective_date": None,
    })
    db.practices[practice["id"]] = practice
    return success_object(serialize(practice), status=201)


@bp.get("/labor-relations/past-practices")
def list_practices():
    authenticate(ALL_ROLES)
    limit, offset = parse_pagination()
    union_id = request.args.get("union_id")
    clause_id = request.args.get("clause_id")
    status = request.args.get("status")
    items = list(db.practices.values())
    if union_id is not None:
        items = [p for p in items if p["union_id"] == union_id]
    if clause_id is not None:
        items = [p for p in items if p["clause_id"] == clause_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = sort_items(items)
    slice_, total = page(items, limit, offset)
    return success_list([serialize(p) for p in slice_], limit, offset, total)


@bp.get("/labor-relations/past-practices/<practice_id>")
def get_practice(practice_id):
    authenticate(ALL_ROLES)
    practice = lookup(db.practices, practice_id, "PastPractice")
    return success_object(serialize(practice))


@bp.post("/labor-relations/past-practices/<practice_id>/state")
def transition_practice(practice_id):
    user_id, role = authenticate(["LRManager", "LegalCounsel", "UnionRepresentative"])
    practice = lookup(db.practices, practice_id, "PastPractice")
    body = get_body()
    to_status = req_string(body, "to_status")
    if to_status not in PRACTICE_STATUSES:
        raise_err(ERR_INVALID_REQUEST, "Unknown past-practice status: %s" % to_status)
    if to_status in ("ASSERTED", "ABANDONED"):
        raise_err(ERR_INVALID_STATE, "Cannot transition a past practice to %s via this endpoint" % to_status)

    # Per-transition role gating
    if to_status in ("DOCUMENTED", "NOTICE_GIVEN") and role != "LRManager":
        raise_err(ERR_UNAUTHORIZED_ROLE, "Only LRManager may transition a practice to %s" % to_status)
    if to_status == "DISPUTED" and role not in ("LRManager", "UnionRepresentative"):
        raise_err(ERR_UNAUTHORIZED_ROLE, "Only LRManager or UnionRepresentative may dispute a practice")

    # UnionRepresentative ownership for DISPUTED
    if role == "UnionRepresentative" and user_id != practice["union_id"]:
        raise_err(ERR_UNION_MISMATCH, "X-User-ID does not match the practice's union_id")

    status = practice["status"]

    if to_status == "DOCUMENTED":
        if status not in ("ASSERTED", "DISPUTED"):
            raise_err(ERR_INVALID_STATE, "Only an ASSERTED or DISPUTED practice can be documented")
        legalistic, operational = calc.compute_strengths(practice, clock.now())
        practice["strength_legalistic"] = legalistic
        practice["strength_operational"] = operational
        practice["status"] = "DOCUMENTED"

    elif to_status == "VERIFIED":
        if status == "NOTICE_GIVEN":
            # Rescind abandonment: LegalCounsel is not eligible; LRManager rescinds
            if role != "LRManager":
                raise_err(ERR_UNAUTHORIZED_ROLE, "Only LRManager may rescind a notice of abandonment")
            if clock.now() >= practice["abandon_effective_date"]:
                raise_err(ERR_INVALID_STATE, "abandon_effective_date has been reached")
            practice["abandon_effective_date"] = None
            practice["status"] = "VERIFIED"
        else:
            if role != "LegalCounsel":
                raise_err(ERR_UNAUTHORIZED_ROLE, "Only LegalCounsel may verify a practice")
            if status != "DOCUMENTED":
                raise_err(ERR_INVALID_STATE, "Only a DOCUMENTED practice can be verified")
            if (practice["occurrence_count"] < 3
                    or practice["strength_legalistic"] is None
                    or practice["strength_legalistic"] < 0.5):
                raise_err(ERR_PRACTICE_NOT_VERIFIABLE,
                          "Verification requires occurrence_count >= 3 and strength_legalistic >= 0.5000")
            practice["status"] = "VERIFIED"

    elif to_status == "DISPUTED":
        if status != "DOCUMENTED":
            raise_err(ERR_INVALID_STATE, "Only a DOCUMENTED practice can be disputed")
        practice["status"] = "DISPUTED"

    elif to_status == "NOTICE_GIVEN":
        if status != "VERIFIED":
            raise_err(ERR_INVALID_STATE, "Only a VERIFIED practice can enter NOTICE_GIVEN")
        practice["abandon_effective_date"] = clock.now() + timedelta(days=30)
        practice["status"] = "NOTICE_GIVEN"

    touch(practice)
    return success_object(serialize(practice))
