"""Certificant reads, the reverse-reachability reads, and public verification.

PRD 3.10.  `GET /registry/verify` is the only capability in the system reachable
with no headers whatsoever, and suppression there is deliberately
indistinguishable from non-existence.
"""

from flask import Blueprint, request

import serialize
from db import DB, ordered
from dispatch import api
from errors import ApiError
from middleware import (
    ROLE_CERTIFICANT,
    ROLE_ELIGIBILITY_REVIEWER,
    ROLE_ETHICS_OFFICER,
    ROLE_EXAM_OPERATIONS,
    ROLE_PROGRAM_ADMIN,
    authenticate,
)
from response import apply_filters, object_response, paginate, read_pagination
from services import derive, lookup
from util import fmt_ts

bp = Blueprint("certificants", __name__)

SUPPRESSED_PUBLICATION_STATUSES = ("WITHHELD", "REMOVED")


@bp.get("/certificants/<certificant_id>")
@api
def read_certificant(certificant_id):
    authenticate([ROLE_PROGRAM_ADMIN, ROLE_ETHICS_OFFICER, ROLE_CERTIFICANT,
                  ROLE_EXAM_OPERATIONS, ROLE_ELIGIBILITY_REVIEWER])
    return object_response(serialize.certificant(lookup.certificant(certificant_id)))


@bp.get("/certificants")
@api
def list_certificants():
    authenticate([ROLE_PROGRAM_ADMIN, ROLE_ETHICS_OFFICER, ROLE_CERTIFICANT,
                  ROLE_EXAM_OPERATIONS, ROLE_ELIGIBILITY_REVIEWER])
    limit, offset = read_pagination()
    rows = ordered(DB.certificants.values())
    for certificant in rows:
        derive.refresh_certificant_projection(certificant)
    rows = apply_filters(rows, {
        "candidate_id": "candidate_id",
        "program_id": "program_id",
        "status": "status",
        "publication_status": "publication_status",
        "certificate_number": "certificate_number",
    })
    return paginate(rows, serialize.certificant, limit, offset)


@bp.get("/registry/verify")
@api
def verify_credential():
    certificate_number = request.args.get("certificate_number")
    if certificate_number is None or not certificate_number.strip():
        raise ApiError("ERR_INVALID_REQUEST")

    match = None
    for certificant in ordered(DB.certificants.values()):
        if certificant["certificate_number"] == certificate_number:
            match = certificant
            break
    if match is None:
        raise ApiError("ERR_CERTIFICANT_NOT_FOUND")

    derive.refresh_certificant_projection(match)
    if match["publication_status"] in SUPPRESSED_PUBLICATION_STATUSES:
        raise ApiError("ERR_CERTIFICANT_NOT_FOUND")

    program = DB.programs[match["program_id"]]
    candidate = DB.candidates[match["candidate_id"]]
    return object_response({
        "certificate_number": match["certificate_number"],
        "credential_code": program["credential_code"],
        "full_name": candidate["full_name"],
        "credential_status": match["status"],
        "publication_status": match["publication_status"],
        "issued_on": fmt_ts(match["issued_on"]),
        "valid_through": fmt_ts(match["valid_through"]),
        "verified_at": fmt_ts(DB.now()),
    })


@bp.get("/certificants/<certificant_id>/recertification-cycles")
@api
def list_certificant_cycles(certificant_id):
    authenticate([ROLE_PROGRAM_ADMIN, ROLE_ETHICS_OFFICER, ROLE_CERTIFICANT])
    certificant = lookup.certificant(certificant_id)
    limit, offset = read_pagination()
    rows = derive.cycles_of_certificant(certificant["id"])
    rows = apply_filters(rows, {"status": "status", "path": "path"})
    return paginate(rows, serialize.cycle, limit, offset)


@bp.get("/certificants/<certificant_id>/disciplinary-cases")
@api
def list_certificant_cases(certificant_id):
    authenticate([ROLE_PROGRAM_ADMIN, ROLE_ETHICS_OFFICER, ROLE_CERTIFICANT])
    certificant = lookup.certificant(certificant_id)
    limit, offset = read_pagination()
    rows = derive.cases_of_certificant(certificant["id"])
    rows = apply_filters(rows, {"status": "status", "outcome": "outcome"})
    return paginate(rows, serialize.case, limit, offset)
