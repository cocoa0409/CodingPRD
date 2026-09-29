"""PermitApplication and PermitBridgeAnalysis endpoints."""

from flask import Blueprint

import calc
import db
import params
import response
import serializers
import services
from calc import D
from db import db as store
from errors import ApiError
from middleware import PERMIT_OFFICER, authenticate, authenticate_read

bp = Blueprint("permits", __name__)

SPEED_CATEGORIES = ("NORMAL", "CRAWL")
PERMIT_STATUSES = (
    "RECEIVED",
    "ANALYZED",
    "APPROVED",
    "APPROVED_WITH_CONDITIONS",
    "DENIED",
    "REVOKED",
)
RECOMMENDED_DECISIONS = ("PENDING", "APPROVE", "APPROVE_WITH_CONDITIONS", "DENY")
ANALYSIS_RESULTS = ("ALLOWED", "ALLOWED_WITH_CONDITIONS", "DENIED")
RESULT_REASONS = (
    "RF_ADEQUATE",
    "RF_MARGINAL",
    "RF_INSUFFICIENT",
    "NO_APPROVED_RATING",
    "BRIDGE_CLOSED",
)
DECISION_TO_STATUS = {
    "APPROVE": "APPROVED",
    "APPROVE_WITH_CONDITIONS": "APPROVED_WITH_CONDITIONS",
    "DENY": "DENIED",
}


@bp.post("/permit-applications")
def create_permit_application():
    authenticate(PERMIT_OFFICER)
    body = params.json_body()
    permit_number = params.get_string(body, "permit_number", required=True)
    carrier_name = params.get_string(body, "carrier_name", required=True)
    raw_axles = params.get_array(body, "axle_loads_tons", required=True, min_items=2)
    axle_loads = []
    for index, entry in enumerate(raw_axles):
        value = params._as_decimal("axle_loads_tons[%d]" % index, entry)
        if value <= 0:
            params.bad("Every entry of 'axle_loads_tons' must be strictly positive.")
        axle_loads.append(value)
    route = params.get_array(body, "route_bridge_ids", required=True, min_items=1)
    for entry in route:
        if not isinstance(entry, str) or entry == "":
            params.bad("Every entry of 'route_bridge_ids' must be a bridge id string.")
    speed_category = params.get_enum(
        body, "speed_category", SPEED_CATEGORIES, default="NORMAL"
    )

    for bridge_id in route:
        services.get_bridge(bridge_id)
    for existing in store.permit_applications.values():
        if existing["permit_number"] == permit_number:
            raise ApiError("ERR_DUPLICATE_PERMIT_NUMBER")

    record = db.new_record(
        {
            "permit_number": permit_number,
            "carrier_name": carrier_name,
            "axle_loads_tons": axle_loads,
            "route_bridge_ids": list(route),
            "axle_count": len(axle_loads),
            "gross_weight_tons": calc.permit_gross_weight_tons(axle_loads),
            "speed_category": speed_category,
            "status": "RECEIVED",
            "recommended_decision": "PENDING",
            "governing_analysis_min_rf": None,
            "decided_at": None,
            "revoked_at": None,
            "decision_note": None,
        }
    )
    store.permit_applications[record["id"]] = record
    return response.object_response(serializers.permit_application(record), 201)


@bp.get("/permit-applications/<permit_id>")
def read_permit_application(permit_id):
    authenticate_read()
    record = services.get_permit_application(permit_id)
    return response.object_response(serializers.permit_application(record))


@bp.get("/permit-applications")
def list_permit_applications():
    authenticate_read()
    limit, offset = params.query_pagination()
    status = params.query_enum("status", PERMIT_STATUSES)
    recommended = params.query_enum("recommended_decision", RECOMMENDED_DECISIONS)
    carrier_name = params.query_string("carrier_name")
    speed_category = params.query_enum("speed_category", SPEED_CATEGORIES)
    items = []
    for record in services.rows("permit_applications"):
        if status is not None and record["status"] != status:
            continue
        if recommended is not None and record["recommended_decision"] != recommended:
            continue
        if carrier_name is not None and record["carrier_name"] != carrier_name:
            continue
        if speed_category is not None and record["speed_category"] != speed_category:
            continue
        items.append(serializers.permit_application(record))
    page, total = response.paginate(items, limit, offset)
    return response.list_response(page, limit, offset, total)


@bp.post("/permit-applications/<permit_id>/analyze")
def analyze_permit_application(permit_id):
    authenticate(PERMIT_OFFICER)
    record = services.get_permit_application(permit_id)
    if record["status"] != "RECEIVED":
        raise ApiError("ERR_PERMIT_STATE_INVALID")

    results = []
    factors = []
    for index, bridge_id in enumerate(record["route_bridge_ids"]):
        bridge = store.bridges.get(bridge_id)
        governing = None
        if bridge is not None:
            governing = services.governing_rating(bridge)
        permit_live_load = None
        permit_impact = None
        rating_factor_permit = None
        if bridge is None or bridge["service_posture"] == "CLOSED":
            analysis_result, result_reason = "DENIED", "BRIDGE_CLOSED"
        elif governing is None:
            analysis_result, result_reason = "DENIED", "NO_APPROVED_RATING"
        else:
            permit_live_load = calc.dec(governing["live_load_ll_kn_m"]) * (
                calc.dec(record["gross_weight_tons"]) / calc.RATING_VEHICLE_TONS
            )
            permit_impact = (
                calc.dec(governing["impact_im_factor"])
                if record["speed_category"] == "NORMAL"
                else calc.CRAWL_IMPACT_FACTOR
            )
            rating_factor_permit = calc.permit_rating_factor(
                governing, record["gross_weight_tons"], record["speed_category"]
            )
            analysis_result, result_reason = calc.permit_analysis_outcome(rating_factor_permit)
            factors.append(rating_factor_permit)
        results.append(analysis_result)
        analysis = db.new_record(
            {
                "permit_application_id": permit_id,
                "bridge_id": bridge_id,
                "governing_load_rating_id": governing["id"] if governing is not None else None,
                "sequence_index": index,
                "permit_live_load_kn_m": permit_live_load,
                "permit_impact_factor": permit_impact,
                "rating_factor_permit": rating_factor_permit,
                "analysis_result": analysis_result,
                "result_reason": result_reason,
            }
        )
        store.permit_bridge_analyses[analysis["id"]] = analysis

    record["status"] = "ANALYZED"
    record["recommended_decision"] = calc.permit_recommended_decision(results)
    record["governing_analysis_min_rf"] = min(factors) if factors else None
    db.touch(record)
    return response.object_response(serializers.permit_application(record))


@bp.post("/permit-applications/<permit_id>/decide")
def decide_permit_application(permit_id):
    authenticate(PERMIT_OFFICER)
    body = params.json_body()
    decision = params.get_enum(
        body, "decision", ("APPROVE", "APPROVE_WITH_CONDITIONS", "DENY"), required=True
    )
    decision_note = params.get_string(body, "decision_note")
    record = services.get_permit_application(permit_id)
    if record["status"] != "ANALYZED":
        raise ApiError("ERR_PERMIT_STATE_INVALID")
    if decision != record["recommended_decision"]:
        raise ApiError("ERR_PERMIT_DECISION_MISMATCH")
    record["status"] = DECISION_TO_STATUS[decision]
    record["decided_at"] = db.now()
    record["decision_note"] = decision_note
    db.touch(record)
    return response.object_response(serializers.permit_application(record))


@bp.get("/permit-bridge-analyses/<analysis_id>")
def read_permit_bridge_analysis(analysis_id):
    authenticate_read()
    record = services.get_permit_bridge_analysis(analysis_id)
    return response.object_response(serializers.permit_bridge_analysis(record))


@bp.get("/permit-bridge-analyses")
def list_permit_bridge_analyses():
    authenticate_read()
    limit, offset = params.query_pagination()
    permit_application_id = params.query_string("permit_application_id")
    bridge_id = params.query_string("bridge_id")
    governing_load_rating_id = params.query_string("governing_load_rating_id")
    analysis_result = params.query_enum("analysis_result", ANALYSIS_RESULTS)
    result_reason = params.query_enum("result_reason", RESULT_REASONS)
    items = []
    for record in services.rows("permit_bridge_analyses"):
        if (
            permit_application_id is not None
            and record["permit_application_id"] != permit_application_id
        ):
            continue
        if bridge_id is not None and record["bridge_id"] != bridge_id:
            continue
        if (
            governing_load_rating_id is not None
            and record["governing_load_rating_id"] != governing_load_rating_id
        ):
            continue
        if analysis_result is not None and record["analysis_result"] != analysis_result:
            continue
        if result_reason is not None and record["result_reason"] != result_reason:
            continue
        items.append(serializers.permit_bridge_analysis(record))
    page, total = response.paginate(items, limit, offset)
    return response.list_response(page, limit, offset, total)
