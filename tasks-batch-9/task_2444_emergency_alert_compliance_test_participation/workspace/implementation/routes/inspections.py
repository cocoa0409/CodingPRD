"""InspectionRequest endpoints (PRD 3.9)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import clock
import serializers
from auth import ANY_ROLE, check_station_ownership, guard
from envelope import object_response
from errors import ApiError
from routes.helpers import collection_response, filter_equals
from services import calculations as calc
from store import base_row, db, mark_created, touch
from validators import (
    DOCUMENT_KINDS,
    get_inspection,
    get_station,
    json_body,
    req_array,
    req_string,
)

bp = Blueprint("inspections", __name__)


@bp.post("/inspection-requests")
@guard("FieldInspector")
def create_inspection():
    body = json_body(request)
    station_id = req_string(body, "station_id")
    requested_document_kinds = req_array(
        body, "requested_document_kinds", non_empty=True, distinct=True,
        member_enum=DOCUMENT_KINDS,
    )

    get_station(station_id)

    now = clock.now()
    inspection = base_row()
    inspection.update({
        "station_id": station_id,
        "requested_document_kinds": list(requested_document_kinds),
        "provided_document_kinds": [],
        "requested_at": now,
        "response_due_at": now + timedelta(days=calc.INSPECTION_RESPONSE_DAYS),
        "responded_at": None,
        "completeness_score": None,
        "status": "OPEN",
    })
    db.inspections[inspection["id"]] = inspection
    mark_created(inspection)
    return object_response(serializers.inspection(inspection), 201)


@bp.get("/inspection-requests/<inspection_id>")
@guard(*ANY_ROLE)
def read_inspection(inspection_id):
    inspection = get_inspection(inspection_id)
    return object_response(serializers.inspection(inspection))


@bp.get("/inspection-requests")
@guard(*ANY_ROLE)
def list_inspections():
    rows = list(db.inspections.values())
    rows = filter_equals(rows, request, (
        ("station_id", "station_id"),
        ("status", "status"),
    ))
    return collection_response(rows, request, serializers.inspection)


@bp.post("/inspection-requests/<inspection_id>/draft-response")
@guard("StationEngineer")
def draft_response(inspection_id):
    body = json_body(request)
    provided_document_kinds = req_array(
        body, "provided_document_kinds", non_empty=False, member_enum=DOCUMENT_KINDS,
    )

    inspection = get_inspection(inspection_id)
    station = db.stations.get(inspection["station_id"])
    if station is not None:
        check_station_ownership(station)

    if inspection["status"] not in ("OPEN", "RESPONSE_DRAFTED"):
        raise ApiError("ERR_INSPECTION_NOT_DRAFTABLE")

    # each draft overwrites the list wholesale
    inspection["provided_document_kinds"] = list(provided_document_kinds)
    inspection["status"] = "RESPONSE_DRAFTED"
    touch(inspection)
    return object_response(serializers.inspection(inspection))


@bp.post("/inspection-requests/<inspection_id>/submit-response")
@guard("CertifyingOfficer")
def submit_response(inspection_id):
    inspection = get_inspection(inspection_id)
    station = db.stations.get(inspection["station_id"])
    if station is not None:
        check_station_ownership(station)

    # rung 7 — state
    if inspection["status"] != "RESPONSE_DRAFTED":
        raise ApiError("ERR_INSPECTION_NOT_DRAFTED")
    if not inspection["provided_document_kinds"]:
        raise ApiError("ERR_INSPECTION_NOT_DRAFTED")

    # rung 10 — the submission window closes response_due_at + 7 days
    now = clock.now()
    closes_at = inspection["response_due_at"] + timedelta(days=calc.INSPECTION_RESPONSE_DAYS)
    if now > closes_at:
        raise ApiError("ERR_INSPECTION_RESPONSE_WINDOW_CLOSED")

    inspection["responded_at"] = now
    inspection["completeness_score"] = calc.inspection_completeness_score(inspection, now)
    inspection["status"] = "RESPONDED"
    touch(inspection)
    return object_response(serializers.inspection(inspection))


@bp.post("/inspection-requests/<inspection_id>/close")
@guard("FieldInspector")
def close_inspection(inspection_id):
    inspection = get_inspection(inspection_id)

    if inspection["status"] != "RESPONDED":
        raise ApiError("ERR_INSPECTION_NOT_RESPONDED")

    score = inspection["completeness_score"]
    score = Decimal("0.00") if score is None else Decimal(score)
    if score >= calc.INSPECTION_SATISFIED_MIN:
        inspection["status"] = "CLOSED_SATISFIED"
    else:
        inspection["status"] = "CLOSED_DEFICIENT"
    touch(inspection)
    return object_response(serializers.inspection(inspection))
