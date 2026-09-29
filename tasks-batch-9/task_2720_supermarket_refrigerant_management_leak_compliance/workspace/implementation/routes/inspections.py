"""Regulatory inspections and penalty exposure (PRD 3.9)."""
from flask import Blueprint, request

import constants
import db
import response
import util
import validate
from errors import ApiError, invalid
from middleware import (COMPLIANCE_MANAGER, REGULATOR, STORE_MANAGER,
                        current_user_id, endpoint, read_endpoint,
                        require_store_scope)
from services import posture

bp = Blueprint("inspections", __name__)


def _parse_citations(payload):
    raw = validate.opt_list(payload, "citations", default=[])
    citations = []
    for item in raw:
        if not isinstance(item, dict):
            raise invalid("each citation must be an object")
        citation_code = validate.req_str(item, "citation_code")
        severity = validate.req_enum(item, "severity", constants.CITATION_SEVERITIES)
        violation_days = validate.req_int(item, "violation_days", minimum=0)
        citations.append({
            "citation_code": citation_code,
            "severity": severity,
            "violation_days": violation_days,
        })
    return citations


@bp.post("/inspections")
@endpoint([REGULATOR])
def create_inspection():
    payload = validate.body()
    store_id = validate.req_id(payload, "store_id")
    inspector_name = validate.req_str(payload, "inspector_name")
    citations = _parse_citations(payload)
    store = db.require("stores", store_id)

    clock = db.now()
    inspection = db.new_entity()
    inspection.update({
        "store_id": store_id,
        "inspector_name": inspector_name,
        "citations": citations,
        "status": "OPEN",
        "opened_at": clock,
        "response_deadline": util.add_days(clock, constants.INSPECTION_RESPONSE_DAYS),
        "opened_by_user_id": current_user_id(),
        "chronic_multiplier_applied": constants.CHRONIC_MULTIPLIER[
            store["compliance_status"]],
        "penalty_exposure_usd": util.q2(0),
        "capped": False,
        "responded_at": None,
        "response_summary": None,
        "corrective_action_code": None,
        "escalated_at": None,
        "closed_at": None,
        "closed_by_user_id": None,
        "closure_note": None,
    })
    posture.recompute_inspection(inspection, store)
    db.insert("inspections", inspection)
    posture.recompute_store(store)
    return response.created(inspection)


@bp.get("/inspections")
@read_endpoint
def list_inspections():
    filters = {
        "store_id": request.args.get("store_id"),
        "status": request.args.get("status"),
    }
    return response.listing(db.values("inspections"), filters)


@bp.get("/inspections/<inspection_id>")
@read_endpoint
def get_inspection(inspection_id):
    return response.ok(db.require("inspections", inspection_id))


@bp.post("/inspections/<inspection_id>/response")
@endpoint([STORE_MANAGER, COMPLIANCE_MANAGER])
def respond_to_inspection(inspection_id):
    payload = validate.body()
    response_summary = validate.req_str(payload, "response_summary")
    corrective_action_code = validate.req_enum(payload, "corrective_action_code",
                                               constants.CORRECTIVE_ACTION_CODES)
    inspection = db.require("inspections", inspection_id)
    require_store_scope(inspection["store_id"])
    if inspection["status"] not in ("OPEN", "ESCALATED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    store = db.require("stores", inspection["store_id"])
    snap = db.snapshot(inspection)
    inspection["status"] = "RESPONDED"
    inspection["responded_at"] = db.now()
    inspection["response_summary"] = response_summary
    inspection["corrective_action_code"] = corrective_action_code
    posture.recompute_inspection(inspection, store)
    db.commit(inspection, snap)
    posture.recompute_store(store)
    return response.ok(inspection)


@bp.post("/inspections/<inspection_id>/closure")
@endpoint([REGULATOR])
def close_inspection(inspection_id):
    payload = validate.body()
    closure_note = validate.req_str(payload, "closure_note")
    inspection = db.require("inspections", inspection_id)
    if inspection["status"] != "RESPONDED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if current_user_id() == inspection["opened_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES_INSPECTION")
    store = db.require("stores", inspection["store_id"])
    snap = db.snapshot(inspection)
    inspection["status"] = "CLOSED"
    inspection["closed_at"] = db.now()
    inspection["closed_by_user_id"] = current_user_id()
    inspection["closure_note"] = closure_note
    db.commit(inspection, snap)
    posture.recompute_store(store)
    return response.ok(inspection)
