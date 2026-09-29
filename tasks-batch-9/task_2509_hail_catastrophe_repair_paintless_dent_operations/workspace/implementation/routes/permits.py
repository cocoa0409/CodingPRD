"""Permit endpoints (PRD §3.2). Permits carry only id and created_at."""

from flask import Blueprint

import serializers
from clock import clock, parse_date
from db import base_row, db
from errors import api_error, bad_request
from middleware import authenticate
from response import list_response, object_response
from routes.common import get_facility, get_permit
from services import aggregates
from services import posture as posture_service
from services.constants import PERMIT_TYPES
from validation import (
    json_body,
    opt_date_string,
    pagination,
    paginate,
    query_filter,
    req_enum,
    req_string,
)

bp = Blueprint("permits", __name__)

PERMIT_READ_ROLES = (
    "CatastropheDirector",
    "CrewCoordinator",
    "ShopEstimator",
    "IntakeAdvisor",
    "PermitOfficer",
)


@bp.post("/hail-ops/permits")
def create_permit():
    authenticate(("CatastropheDirector",))
    body = json_body()
    facility_id = req_string(body, "facility_id")
    permit_type = req_enum(body, "permit_type", PERMIT_TYPES)
    issuing_jurisdiction = req_string(body, "issuing_jurisdiction")

    facility = get_facility(facility_id)
    posture_service.recompute(facility)

    row = base_row(versioned=False)
    row.update({
        "facility_id": facility_id,
        "permit_type": permit_type,
        "issuing_jurisdiction": issuing_jurisdiction,
        "status": "PENDING",
        "valid_from": None,
        "valid_to": None,
        "decided_at": None,
    })
    db.permits[row["id"]] = row
    posture_service.recompute(facility)
    return object_response(serializers.permit(row), 201)


@bp.post("/hail-ops/permits/<identifier>/decision")
def decide_permit(identifier):
    authenticate(("PermitOfficer",))
    body = json_body()
    decision = req_enum(body, "decision", ("APPROVE", "DENY"))
    valid_from = opt_date_string(body, "valid_from")
    valid_to = opt_date_string(body, "valid_to")
    if decision == "APPROVE":
        if valid_from is None or valid_to is None:
            raise bad_request("An APPROVE decision requires valid_from and valid_to.")
        if parse_date(valid_from) > parse_date(valid_to):
            raise bad_request("valid_from must be no later than valid_to.")

    permit = get_permit(identifier)
    facility = db.facilities.get(permit["facility_id"])
    if facility is not None:
        posture_service.recompute(facility)

    if permit["status"] != "PENDING":
        raise api_error(
            "ERR_PERMIT_ALREADY_DECIDED",
            "A decision may only be recorded on a PENDING permit.",
        )

    if decision == "APPROVE":
        permit["status"] = "APPROVED"
        permit["valid_from"] = valid_from
        permit["valid_to"] = valid_to
    else:
        permit["status"] = "DENIED"
    permit["decided_at"] = clock.instant()

    # An approval can heal a SUSPENDED site inside this very request.
    if facility is not None:
        posture_service.recompute(facility)
    return object_response(serializers.permit(permit))


@bp.get("/hail-ops/facilities/<identifier>/permits")
def list_facility_permits(identifier):
    authenticate(PERMIT_READ_ROLES)
    limit, offset = pagination()
    facility = get_facility(identifier)
    posture_service.recompute(facility)

    rows = aggregates.permits_of_facility(facility["id"])
    permit_type = query_filter("permit_type")
    status = query_filter("status")
    if permit_type is not None:
        rows = [r for r in rows if r["permit_type"] == permit_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]

    page = paginate(rows, limit, offset)
    return list_response([serializers.permit(r) for r in page], limit, offset, len(rows))
