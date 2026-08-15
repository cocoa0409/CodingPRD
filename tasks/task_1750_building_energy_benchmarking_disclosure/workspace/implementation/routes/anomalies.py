"""Anomaly flag endpoints: manual raise, list, get, resolve, waive."""
from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import get_context, require_roles
from response import created, ok, paginate
from services import core
from validation import parse_body, require_path_entity, require_min_length

bp = Blueprint("anomalies", __name__)


@bp.post("/v1/benchmark-reports/<report_id>/anomaly-flags")
def create_anomaly_flag(report_id):
    get_context()
    require_roles(["ComplianceOfficer"])
    report = require_path_entity(store.reports, report_id)
    body = parse_body({"detail": ("string", True, None)}, allow_empty=False)
    if report["status"] not in ("SUBMITTED", "VERIFIED", "CERTIFIED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Manual review requires a SUBMITTED, VERIFIED, or CERTIFIED report")
    flag = core.create_anomaly(report["id"], "MANUAL_REVIEW", body["detail"])
    report["status"] = "FLAGGED"
    db.touch(report)
    core.supersede_publications_for(report)
    return created(flag)


@bp.get("/v1/anomaly-flags")
def list_anomaly_flags():
    get_context()
    rows = list(store.anomaly_flags.values())
    rows = paginate.filter(rows, "report_id")
    rows = paginate.filter(rows, "status")
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/v1/anomaly-flags/<flag_id>")
def get_anomaly_flag(flag_id):
    get_context()
    flag = require_path_entity(store.anomaly_flags, flag_id)
    return ok(flag)


@bp.post("/v1/anomaly-flags/<flag_id>/resolve")
def resolve_anomaly_flag(flag_id):
    uid, _ = get_context()
    require_roles(["BuildingOwner"])
    flag = require_path_entity(store.anomaly_flags, flag_id)
    report = store.reports.get(flag["report_id"])
    building = store.buildings.get(report["building_id"]) if report else None
    if building is None or building["owner_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                       "BuildingOwner does not own the report's building")
    body = parse_body({"resolution_note": ("string", True, None)}, allow_empty=False)
    require_min_length(body, "resolution_note", 20)
    if flag["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only an OPEN anomaly flag can be resolved")
    flag["status"] = "RESOLVED"
    flag["resolution_note"] = body["resolution_note"]
    db.touch(flag)
    return ok(flag)


@bp.post("/v1/anomaly-flags/<flag_id>/waive")
def waive_anomaly_flag(flag_id):
    get_context()
    require_roles(["ComplianceOfficer"])
    flag = require_path_entity(store.anomaly_flags, flag_id)
    body = parse_body({"waive_reason": ("string", True, None)}, allow_empty=False)
    if flag["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only an OPEN anomaly flag can be waived")
    flag["status"] = "WAIVED"
    flag["waive_reason"] = body["waive_reason"]
    db.touch(flag)
    return ok(flag)
