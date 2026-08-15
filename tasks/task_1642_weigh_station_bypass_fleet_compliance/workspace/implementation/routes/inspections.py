"""Inspection report feed (PRD 3.8). Append-only; feeds only the ROI report."""
from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import body_json, ctx, list_response, need_enum, need_int, need_str, opt_bool, require_role
from response import ok
from util import fmt_ts, parse_datetime

bp = Blueprint("inspections", __name__)

LEVELS = ("LEVEL_1", "LEVEL_2", "LEVEL_3")


@bp.post("/api/inspection-reports")
def create_report():
    _uid, role = ctx()
    require_role(role, ("SafetyDataFeed",))
    body = body_json()
    cid = body.get("carrier_id")
    vid = body.get("vehicle_id")
    # Rung 4: existence, type order — carrier before vehicle
    carrier = store.carriers.get(cid) if isinstance(cid, str) else None
    if isinstance(cid, str) and carrier is None:
        raise ApiError("ERR_CARRIER_NOT_FOUND", 404, "carrier id does not exist")
    veh = store.vehicles.get(vid) if isinstance(vid, str) else None
    if isinstance(vid, str) and veh is None:
        raise ApiError("ERR_VEHICLE_NOT_FOUND", 404, "vehicle id does not exist")
    # Rung 9: inspected_at must not be in the future
    ins = parse_datetime(body.get("inspected_at"))
    if ins is not None and ins > db.now():
        raise ApiError(
            "ERR_FUTURE_INSPECTION", 400, "inspected_at is after the logical now"
        )
    # Rung 12: fields
    cid = need_str(body, "carrier_id")
    vid = need_str(body, "vehicle_id")
    level = need_enum(body, "inspection_level", LEVELS)
    violations = need_int(body, "violations_found")
    if violations < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "violations_found must be >= 0")
    if ins is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "inspected_at must be an ISO-8601 timestamp"
        )
    oos = opt_bool(body, "out_of_service_order", False)
    rec = {
        "id": db.new_id(),
        "_seq": store.next_seq(),
        "carrier_id": cid,
        "vehicle_id": vid,
        "inspection_level": level,
        "inspected_at": fmt_ts(ins),
        "_inspected_dt": ins,
        "violations_found": violations,
        "out_of_service_order": oos,
    }
    db.stamp_feed(rec)
    store.reports[rec["id"]] = rec
    return ok(db.public(rec), 201)


@bp.get("/api/inspection-reports")
def list_reports():
    return list_response(
        store.reports.values(),
        [("carrier_id", "carrier_id"), ("vehicle_id", "vehicle_id")],
    )


@bp.get("/api/inspection-reports/<reportId>")
def get_report(reportId):
    ctx()
    rec = store.reports.get(reportId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, "inspection report id does not exist")
    return ok(db.public(rec), 200)
