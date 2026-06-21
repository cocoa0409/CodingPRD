"""LactationConsult resource (PRD §3.5)."""

from flask import Blueprint, request

import db
import services
from errors import (
    APIError,
    ERR_CONSULT_BUFFER_CONFLICT,
    invalid_request,
    invalid_state,
    not_found,
)
from helpers import (
    get_body,
    paginate,
    parse_pagination,
    require_enum,
    require_field,
    sort_created_at_asc,
)
from middleware import require_roles
from response import ok_array, ok_object

bp = Blueprint("lactation_consults", __name__)

CONSULT_STATUSES = {"SCHEDULED", "COMPLETED", "FEEDING_AT_RISK", "CANCELLED"}
CONSULT_BUFFER_MINUTES = 240


def _get_consult(consult_id):
    c = db.lactation_consults.get(consult_id)
    if c is None:
        raise not_found("Lactation consult not found.")
    return c


@bp.post("/lactation-consults")
def create_consult():
    require_roles("AttendingNurse")
    body = get_body()
    newborn_id = require_field(body, "newborn_id", str)
    if db.newborns.get(newborn_id) is None:
        raise not_found("newborn_id does not resolve to a newborn.")
    consult_datetime = require_field(body, "consult_datetime", str)
    try:
        new_dt = db.parse_iso(consult_datetime)
    except ValueError as e:
        raise invalid_request(str(e))

    # Consult buffer (priority 18): closed buffer of 240 minutes against any
    # SCHEDULED/COMPLETED/FEEDING_AT_RISK consult for the same newborn.
    for c in db.lactation_consults.values():
        if c["newborn_id"] != newborn_id:
            continue
        if c["status"] not in ("SCHEDULED", "COMPLETED", "FEEDING_AT_RISK"):
            continue
        existing_dt = db.parse_iso(c["consult_datetime"])
        gap = abs((new_dt - existing_dt).total_seconds()) / 60.0
        if gap <= CONSULT_BUFFER_MINUTES:
            raise APIError(ERR_CONSULT_BUFFER_CONFLICT,
                           "Consult is within the 240-minute buffer of an existing consult.",
                           409)

    row = {
        "id": db.new_id(),
        "newborn_id": newborn_id,
        "consult_datetime": consult_datetime,
        "latch_score": None,
        "status": "SCHEDULED",
        "feeding_adequate": False,
    }
    db.stamp_create(row)
    db.lactation_consults[row["id"]] = row
    return ok_object(db.public(row), 201)


@bp.get("/lactation-consults/<consult_id>")
def get_consult(consult_id):
    require_roles("AttendingNurse", "RegistrySupervisor")
    return ok_object(db.public(_get_consult(consult_id)))


@bp.get("/lactation-consults")
def list_consults():
    require_roles("AttendingNurse", "RegistrySupervisor")
    limit, offset = parse_pagination()
    newborn_id = request.args.get("newborn_id")
    status = request.args.get("status")
    rows = list(db.lactation_consults.values())
    if newborn_id is not None:
        rows = [r for r in rows if r["newborn_id"] == newborn_id]
    if status is not None:
        require_enum(status, "status", CONSULT_STATUSES)
        rows = [r for r in rows if r["status"] == status]
    rows = sort_created_at_asc(rows)
    page, total, has_more = paginate(rows, limit, offset)
    return ok_array([db.public(r) for r in page], limit=limit, offset=offset,
                    total_count=total, has_more=has_more)


@bp.post("/lactation-consults/<consult_id>/complete")
def complete_consult(consult_id):
    require_roles("AttendingNurse")
    c = _get_consult(consult_id)
    body = get_body()
    latch_score = require_field(body, "latch_score", int)
    if not (0 <= latch_score <= 10):
        raise invalid_request("latch_score must be between 0 and 10.")
    if c["status"] != "SCHEDULED":
        raise invalid_state("Only a SCHEDULED consult may be completed.")
    # The newborn must not already be DISCHARGED.
    newborn = db.newborns.get(c["newborn_id"])
    if newborn is not None and newborn["clinical_status"] == "DISCHARGED":
        raise invalid_state("Cannot complete a consult for a discharged newborn.")

    c["latch_score"] = latch_score
    if latch_score >= 7:
        c["status"] = "COMPLETED"
        c["feeding_adequate"] = True
    else:
        c["status"] = "FEEDING_AT_RISK"
        c["feeding_adequate"] = False
    db.stamp_update(c)
    if newborn is not None:
        services.refresh_readiness(newborn)
    return ok_object(db.public(c))


@bp.post("/lactation-consults/<consult_id>/cancel")
def cancel_consult(consult_id):
    require_roles("AttendingNurse")
    c = _get_consult(consult_id)
    if c["status"] != "SCHEDULED":
        raise invalid_state("Only a SCHEDULED consult may be cancelled.")
    c["status"] = "CANCELLED"
    db.stamp_update(c)
    return ok_object(db.public(c))
