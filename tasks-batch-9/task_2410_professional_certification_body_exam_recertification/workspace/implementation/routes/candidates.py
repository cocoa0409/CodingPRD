"""Candidate endpoints (PRD 3.6)."""

from flask import Blueprint

import serialize
from db import DB, mark_created, new_record, ordered
from dispatch import api
from errors import ApiError
from middleware import (
    ROLE_CANDIDATE,
    ROLE_ELIGIBILITY_REVIEWER,
    ROLE_ETHICS_OFFICER,
    ROLE_EXAM_OPERATIONS,
    ROLE_PROGRAM_ADMIN,
    authenticate,
    ensure_body,
    peek_body,
    req_str,
)
from response import apply_filters, created_response, object_response, paginate, read_pagination
from services import lookup

bp = Blueprint("candidates", __name__)


@bp.post("/candidates")
@api
def create_candidate():
    authenticate([ROLE_EXAM_OPERATIONS, ROLE_ELIGIBILITY_REVIEWER])
    body = ensure_body(peek_body())
    email = req_str(body, "email")
    full_name = req_str(body, "full_name")

    for existing in DB.candidates.values():
        if existing["email"] == email:
            raise ApiError("ERR_CANDIDATE_EMAIL_TAKEN")

    candidate = new_record(
        email=email,
        full_name=full_name,
        status="ACTIVE",
        barred_until=None,
        bar_reason=None,
    )
    mark_created(candidate)
    DB.candidates[candidate["id"]] = candidate
    return created_response(serialize.candidate(candidate))


@bp.get("/candidates/<candidate_id>")
@api
def read_candidate(candidate_id):
    authenticate([ROLE_EXAM_OPERATIONS, ROLE_ELIGIBILITY_REVIEWER, ROLE_PROGRAM_ADMIN,
                  ROLE_CANDIDATE, ROLE_ETHICS_OFFICER])
    return object_response(serialize.candidate(lookup.candidate(candidate_id)))


@bp.get("/candidates")
@api
def list_candidates():
    authenticate([ROLE_EXAM_OPERATIONS, ROLE_ELIGIBILITY_REVIEWER, ROLE_PROGRAM_ADMIN])
    limit, offset = read_pagination()
    rows = ordered(DB.candidates.values())
    rows = apply_filters(rows, {
        "email": "email",
        "status": "status",
        "bar_reason": "bar_reason",
    })
    return paginate(rows, serialize.candidate, limit, offset)
