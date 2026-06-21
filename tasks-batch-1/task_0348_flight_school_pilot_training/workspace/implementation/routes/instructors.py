"""Instructor (CFI) routes."""

from flask import Blueprint

import errors
from db import db, new_common, public, sorted_by_created
from errors import err
from middleware import (as_int, as_str, get_body, get_user_context,
                        parse_pagination, require_fields, require_role)
from response import list_success, success
from services.common import find_or_404

bp = Blueprint("instructors", __name__)

ENDORSEMENT_CODES = {"SOLO", "XC", "COMPLEX", "TAILWHEEL"}


@bp.post("/flight-school/instructors")
def create_instructor():
    _, role = get_user_context()
    require_role(role, {"SchoolAdmin"})
    body = get_body()
    require_fields(body, ["full_name", "email", "cfi_rate_cents_per_hour",
                          "authorized_endorsement_codes"])
    full_name = as_str(body, "full_name")
    email = as_str(body, "email")
    rate = as_int(body, "cfi_rate_cents_per_hour")
    if rate <= 0:
        raise err(errors.ERR_INVALID_REQUEST, "cfi_rate_cents_per_hour must be > 0.")
    codes = body["authorized_endorsement_codes"]
    if not isinstance(codes, list) or any(c not in ENDORSEMENT_CODES for c in codes):
        raise err(errors.ERR_INVALID_REQUEST,
                  "authorized_endorsement_codes must be a list of valid codes.")

    record = new_common()
    record.update({
        "full_name": full_name,
        "email": email,
        "cfi_rate_cents_per_hour": rate,
        "authorized_endorsement_codes": list(codes),
        "status": "ACTIVE",
    })
    db.instructors[record["id"]] = record
    return success(public(record), status=201)


@bp.get("/flight-school/instructors")
def list_instructors():
    _, role = get_user_context()
    require_role(role, {"SchoolAdmin", "Dispatcher", "Student"})
    limit, offset = parse_pagination()
    items = sorted_by_created(list(db.instructors.values()))
    total = len(items)
    page = items[offset:offset + limit]
    return list_success([public(i) for i in page], limit, offset, total)


@bp.get("/flight-school/instructors/<instructor_id>")
def get_instructor(instructor_id):
    _, role = get_user_context()
    require_role(role, {"SchoolAdmin", "Dispatcher", "Student", "Instructor"})
    record = find_or_404(db.instructors, instructor_id)
    return success(public(record))
