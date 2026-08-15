"""Requisitions (PRD §3.4) and nested cycle creation."""
import db
import serializers
import util
from errors import (api_err, err_invalid_request, err_not_found,
                    err_ownership, err_ref_not_found)
from flask import Blueprint
from middleware import authenticate, require_roles
from response import success_object
from services import core
from util import bump, new_id, next_seq, parse_dt, req_int, req_string

bp = Blueprint("requisitions", __name__)


def _get_req_or_404(rid):
    r = db.stores["requisitions"].get(rid)
    if r is None:
        raise err_not_found("Requisition not found")
    return r


@bp.post("/talent/requisitions")
def create_requisition():
    ctx = authenticate()
    require_roles(ctx, ["HiringManager"])
    body = util.get_body()
    title = req_string(body, "title")
    department = req_string(body, "department")
    openings_count = req_int(body, "openings_count", lo=1)
    retention_days = body.get("retention_days", 730)
    if isinstance(retention_days, bool) or not isinstance(retention_days, int):
        raise err_invalid_request("retention_days must be an integer")
    if retention_days < 180 or retention_days > 3650:
        raise err_invalid_request("retention_days must be between 180 and 3650")
    now = db.get_now()
    rec = {
        "id": new_id(),
        "hiring_manager_id": ctx.user_id,
        "title": title,
        "department": department,
        "openings_count": openings_count,
        "filled_count": 0,
        "status": "OPEN",
        "retention_days": retention_days,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_created": now,
        "_seq": next_seq(),
    }
    db.stores["requisitions"][rec["id"]] = rec
    return success_object(serializers.requisition(rec), 201)


@bp.get("/talent/requisitions/<rid>")
def get_requisition(rid):
    ctx = authenticate()
    require_roles(ctx, ["HiringManager", "TalentAssessmentAdmin",
                        "ComplianceOfficer", "DecisionOfficer"])
    r = _get_req_or_404(rid)
    if ctx.role == "HiringManager" and r["hiring_manager_id"] != ctx.user_id:
        raise err_ownership("HiringManager may only read own requisitions")
    core.recompute_requisition_filled(r)
    return success_object(serializers.requisition(r))


@bp.post("/talent/requisitions/<rid>/close")
def close_requisition(rid):
    ctx = authenticate()
    require_roles(ctx, ["HiringManager"])
    r = _get_req_or_404(rid)
    if r["hiring_manager_id"] != ctx.user_id:
        raise err_ownership("Only the owning HiringManager may close the requisition")
    if r["status"] not in ("OPEN", "FILLED"):
        raise api_err("ERR_INVALID_STATE", "Requisition must be OPEN or FILLED to close")
    for cyc in db.stores["cycles"].values():
        if cyc["requisition_id"] == rid and cyc["posture"] != "CLOSED":
            raise api_err("ERR_CYCLE_NOT_CLOSED",
                          "All cycles must be CLOSED before the requisition closes")
    r["status"] = "CLOSED"
    bump(r)
    return success_object(serializers.requisition(r))


@bp.post("/talent/requisitions/<rid>/cycles")
def create_cycle(rid):
    ctx = authenticate()
    require_roles(ctx, ["HiringManager"])
    r = _get_req_or_404(rid)
    body = util.get_body()
    # Body FK resolution left-to-right in declared input order: instrument_id, guide_id
    instrument_id = body.get("instrument_id")
    if not isinstance(instrument_id, str):
        raise err_invalid_request("instrument_id is required")
    instrument = db.stores["instruments"].get(instrument_id)
    if instrument is None:
        raise err_ref_not_found("instrument_id does not resolve")
    guide_id = body.get("guide_id")
    if not isinstance(guide_id, str):
        raise err_invalid_request("guide_id is required")
    guide = db.stores["guides"].get(guide_id)
    if guide is None:
        raise err_ref_not_found("guide_id does not resolve")
    # Ownership (tier 5)
    if r["hiring_manager_id"] != ctx.user_id:
        raise err_ownership("Only the owning HiringManager may create cycles")
    # Dedicated state gate: requisition OPEN (tier 7)
    if r["status"] != "OPEN":
        raise api_err("ERR_REQUISITION_NOT_OPEN", "Requisition must be OPEN")
    # Business safety gates (tier 9) in PRD §3.4 order:
    # instrument VALIDATED -> vendor ACTIVE -> guide APPROVED
    if instrument["validation_status"] != "VALIDATED":
        raise api_err("ERR_INSTRUMENT_NOT_VALIDATED", "Instrument must be VALIDATED")
    vendor = db.stores["vendors"].get(instrument["vendor_id"])
    if vendor is None or vendor["status"] != "ACTIVE" or instrument["vendor_suspended"]:
        raise api_err("ERR_VENDOR_NOT_ACTIVE",
                      "Vendor must be ACTIVE and instrument not vendor-suspended")
    if guide["status"] != "APPROVED":
        raise api_err("ERR_GUIDE_NOT_APPROVED", "Guide must be APPROVED")
    label = req_string(body, "label")
    w_start = parse_dt(body.get("administration_window_start"), "administration_window_start")
    w_end = parse_dt(body.get("administration_window_end"), "administration_window_end")
    max_sessions = body.get("max_sessions_per_day", 8)
    if isinstance(max_sessions, bool) or not isinstance(max_sessions, int):
        raise err_invalid_request("max_sessions_per_day must be an integer")
    if max_sessions < 1 or max_sessions > 100:
        raise err_invalid_request("max_sessions_per_day must be between 1 and 100")
    if w_start >= w_end:
        raise api_err("ERR_WINDOW_ORDER_INVALID",
                      "administration_window_start must be before administration_window_end")
    now = db.get_now()
    rec = {
        "id": new_id(),
        "requisition_id": rid,
        "instrument_id": instrument_id,
        "guide_id": guide_id,
        "label": label,
        "posture": "SETUP",
        "frozen_from_posture": None,
        "frozen_reason": None,
        "administration_window_start": w_start,
        "administration_window_end": w_end,
        "max_sessions_per_day": max_sessions,
        "active_candidate_count": 0,
        "decisions_finalized_count": 0,
        "closed_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_created": now,
        "_seq": next_seq(),
    }
    db.stores["cycles"][rec["id"]] = rec
    core.recompute_guide_pins(guide)
    bump(guide)
    return success_object(serializers.cycle(rec), 201)
