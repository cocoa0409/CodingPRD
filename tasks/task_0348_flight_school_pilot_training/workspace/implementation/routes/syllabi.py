"""Syllabus routes (immutable configuration entity: id + created_at only)."""

from flask import Blueprint

import errors
from db import db, new_lean, public, sorted_by_created
from errors import err
from middleware import (as_int, as_number, as_str, get_body, get_user_context,
                        parse_pagination, require_fields, require_role)
from response import list_success, success
from services.common import find_or_404

bp = Blueprint("syllabi", __name__)


@bp.post("/flight-school/syllabi")
def create_syllabus():
    _, role = get_user_context()
    require_role(role, {"SchoolAdmin"})
    body = get_body()
    require_fields(body, ["name", "required_dual_hours", "required_solo_hours",
                          "stage_count", "min_deposit_cents"])
    name = as_str(body, "name")
    required_dual_hours = as_number(body, "required_dual_hours")
    required_solo_hours = as_number(body, "required_solo_hours")
    if required_dual_hours < 0 or required_solo_hours < 0:
        raise err(errors.ERR_INVALID_REQUEST, "required hours must be non-negative.")
    stage_count = as_int(body, "stage_count")
    if stage_count < 0:
        raise err(errors.ERR_INVALID_REQUEST, "stage_count must be non-negative.")
    min_deposit_cents = as_int(body, "min_deposit_cents")
    if min_deposit_cents < 0:
        raise err(errors.ERR_INVALID_REQUEST, "min_deposit_cents must be non-negative.")

    record = new_lean()
    record.update({
        "name": name,
        "required_dual_hours": required_dual_hours,
        "required_solo_hours": required_solo_hours,
        "stage_count": stage_count,
        "min_deposit_cents": min_deposit_cents,
    })
    db.syllabi[record["id"]] = record
    return success(public(record), status=201)


@bp.get("/flight-school/syllabi")
def list_syllabi():
    _, role = get_user_context()
    require_role(role, {"SchoolAdmin", "Dispatcher", "Student", "Instructor"})
    limit, offset = parse_pagination()
    items = sorted_by_created(list(db.syllabi.values()))
    total = len(items)
    page = items[offset:offset + limit]
    return list_success([public(s) for s in page], limit, offset, total)


@bp.get("/flight-school/syllabi/<syllabus_id>")
def get_syllabus(syllabus_id):
    _, role = get_user_context()
    require_role(role, {"SchoolAdmin", "Dispatcher", "Student", "Instructor"})
    record = find_or_404(db.syllabi, syllabus_id)
    return success(public(record))
