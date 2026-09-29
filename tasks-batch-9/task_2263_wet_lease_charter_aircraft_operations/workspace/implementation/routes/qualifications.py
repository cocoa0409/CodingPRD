"""Crew qualifications — lessee-procedures training and the checkride (PRD 3.4)."""

from flask import Blueprint, request

from db import db, new_row, touch, public, clock_now
from errors import ApiError, bad_request
from middleware import (
    require, check_ownership, scope_for_lessee,
    LESSOR_OPS, LESSEE, MAINTENANCE_CONTROLLER,
)
from response import object_response, pagination, paged
from routes.common import find_lease, find_crew, find_qualification, filtered
import validate as V

bp = Blueprint("qualifications", __name__)


@bp.post("/wetlease/crew-qualifications")
def create_qualification():
    require((LESSOR_OPS,))
    body = V.json_body()
    crew_member_id = V.req_str(body, "crew_member_id")
    lease_id = V.req_str(body, "lease_id")

    # PRD 2.8 step 5: the lease identifier resolves before the crew identifier.
    find_lease(lease_id)
    find_crew(crew_member_id)

    row = new_row()
    row.update({
        "crew_member_id": crew_member_id,
        "lease_id": lease_id,
        "differences_training_completed_on": None,
        "checkride_valid_until": None,
        "status": "TRAINING",
    })
    db.crew_qualifications[row["id"]] = row
    return object_response(public(row), 201)


@bp.get("/wetlease/crew-qualifications/<qualification_id>")
def get_qualification(qualification_id):
    actor = require((LESSOR_OPS, MAINTENANCE_CONTROLLER, LESSEE))
    qual = find_qualification(qualification_id)
    check_ownership(actor, "qualification", qual)
    return object_response(public(qual))


@bp.get("/wetlease/crew-qualifications")
def list_qualifications():
    actor = require((LESSOR_OPS, MAINTENANCE_CONTROLLER, LESSEE))
    limit, offset = pagination(request.args)
    rows = filtered(list(db.crew_qualifications.values()), request.args, {
        "crew_member_id": "crew_member_id",
        "lease_id": "lease_id",
        "status": "status",
    })
    rows = scope_for_lessee(actor, "qualification", rows)
    return paged(rows, limit, offset)


@bp.post("/wetlease/crew-qualifications/<qualification_id>/complete-checkride")
def complete_checkride(qualification_id):
    require((LESSOR_OPS,))
    body = V.json_body()
    differences_raw, _differences = V.req_date(body, "differences_training_completed_on")
    checkride_raw, checkride_until = V.req_date(body, "checkride_valid_until")
    qual = find_qualification(qualification_id)

    if qual["status"] not in ("TRAINING", "EXPIRED"):
        raise bad_request("a checkride may only be recorded from TRAINING or EXPIRED")
    crew = db.crew_members.get(qual["crew_member_id"])
    if crew is None or crew["status"] != "ACTIVE":
        raise bad_request("the crew member must be ACTIVE")

    qual["differences_training_completed_on"] = differences_raw
    qual["checkride_valid_until"] = checkride_raw
    qual["status"] = "QUALIFIED" if checkride_until > clock_now().date() else "EXPIRED"
    touch(qual)
    return object_response(public(qual))
