"""Station endpoints (PRD 3.2, 3.8, 2.12)."""

from decimal import Decimal

from flask import Blueprint, request

import clock
import serializers
from auth import ANY_ROLE, check_station_ownership, guard
from envelope import object_response
from errors import ApiError
from routes.helpers import collection_response, filter_equals
from services import scoring
from store import base_row, db, mark_created, touch
from validators import (
    CALL_SIGN_RE,
    SERVICE_TYPES,
    get_state_plan,
    get_station,
    json_body,
    req_array,
    req_string,
)

bp = Blueprint("stations", __name__)


@bp.post("/stations")
@guard("ComplianceAdmin")
def create_station():
    body = json_body(request)
    state_plan_id = req_string(body, "state_plan_id")
    call_sign = req_string(body, "call_sign", pattern=CALL_SIGN_RE)
    service_type = req_string(body, "service_type")
    if service_type not in SERVICE_TYPES:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'service_type' must be one of %s."
                       % ", ".join(SERVICE_TYPES))
    engineer_user_ids = req_array(body, "engineer_user_ids", non_empty=True, distinct=True)
    certification_officer_user_id = req_string(body, "certification_officer_user_id")

    # rung 4 — body FK
    get_state_plan(state_plan_id)

    # rung 11 — uniqueness
    for existing in db.stations.values():
        if existing["call_sign"] == call_sign:
            raise ApiError("ERR_DUPLICATE_CALL_SIGN")

    station = base_row()
    station.update({
        "state_plan_id": state_plan_id,
        "call_sign": call_sign,
        "service_type": service_type,
        "engineer_user_ids": list(engineer_user_ids),
        "certification_officer_user_id": certification_officer_user_id,
        "compliance_posture": "PROVISIONING",
        "compliance_score": None,
        "compliance_variant_applied": None,
        "accessible_source_count": 0,
        "silent_assignment_count": 0,
        "penalty_points_total": Decimal("0.00"),
        "plan_revalidation_required": False,
        "public_file_document_count": 0,
        "last_log_review_at": None,
    })
    db.stations[station["id"]] = station
    mark_created(station)
    return object_response(serializers.station(station), 201)


@bp.get("/stations/<station_id>")
@guard(*ANY_ROLE)
def read_station(station_id):
    station = get_station(station_id)
    return object_response(serializers.station(station))


@bp.get("/stations")
@guard(*ANY_ROLE)
def list_stations():
    rows = list(db.stations.values())
    rows = filter_equals(rows, request, (
        ("state_plan_id", "state_plan_id"),
        ("compliance_posture", "compliance_posture"),
        ("call_sign", "call_sign"),
    ))
    return collection_response(rows, request, serializers.station)


@bp.get("/stations/<station_id>/compliance-summary")
@guard(*ANY_ROLE)
def compliance_summary(station_id):
    station = get_station(station_id)
    plan = db.state_plans.get(station["state_plan_id"])
    required_source_count = plan["required_source_count"] if plan else 0
    data = {
        "station_id": station["id"],
        "compliance_posture": station["compliance_posture"],
        "compliance_score": serializers.n(station["compliance_score"]),
        "compliance_variant_applied": station["compliance_variant_applied"],
        "required_source_count": required_source_count,
        "accessible_source_count": station["accessible_source_count"],
        "missing_source_count": max(0, required_source_count - station["accessible_source_count"]),
        "silent_assignment_count": station["silent_assignment_count"],
        "outage_breach_count": scoring.outage_breach_count(station),
        "unfiled_test_count": scoring.unfiled_test_count(station),
        "penalty_points_total": serializers.n(station["penalty_points_total"]),
        "plan_revalidation_required": station["plan_revalidation_required"],
        "public_file_document_count": station["public_file_document_count"],
        "last_log_review_at": clock.iso(station["last_log_review_at"]),
    }
    return object_response(data)


@bp.post("/stations/<station_id>/run-log-review")
@guard("ComplianceAdmin")
def run_log_review(station_id):
    station = get_station(station_id)
    scoring.recompute_station(station, log_review=True)
    return object_response(serializers.station(station))


@bp.post("/stations/<station_id>/public-file-documents")
@guard("StationEngineer")
def record_public_file_document(station_id):
    body = json_body(request)
    req_string(body, "document_kind")
    req_string(body, "reference_label")

    station = get_station(station_id)
    check_station_ownership(station)

    station["public_file_document_count"] += 1
    touch(station)
    return object_response(serializers.station(station), 201)
