"""Vendors, content ledger, and the depth-3 suspension cascade (PRD §3.1)."""
from flask import Blueprint

import db
import serializers
from errors import api_err, err_invalid_request, err_not_found, err_ownership
from middleware import authenticate, require_roles
from response import success_object
from services import core
from util import (bump, filter_params, new_id, next_seq, paginate, req_enum,
                  req_int, req_string, sort_records)
import util

bp = Blueprint("vendors", __name__)

TIERS = ["TIER_1", "TIER_2", "TIER_3"]


def _get_vendor_or_404(vendor_id):
    v = db.stores["vendors"].get(vendor_id)
    if v is None:
        raise err_not_found("Vendor not found")
    return v


@bp.post("/talent/vendors")
def create_vendor():
    ctx = authenticate()
    require_roles(ctx, ["TalentAssessmentAdmin"])
    body = util.get_body()
    name = req_string(body, "name")
    tier = body.get("security_clearance_tier", "TIER_2")
    if tier not in TIERS:
        raise err_invalid_request("security_clearance_tier must be TIER_1 | TIER_2 | TIER_3")
    now = db.get_now()
    rec = {
        "id": new_id(),
        "name": name,
        "status": "ACTIVE",
        "security_clearance_tier": tier,
        "content_copies_outstanding": 0,
        "terminated_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_created": now,
        "_seq": next_seq(),
    }
    db.stores["vendors"][rec["id"]] = rec
    return success_object(serializers.vendor(rec), 201)


@bp.get("/talent/vendors/<vid>")
def get_vendor(vid):
    ctx = authenticate()
    require_roles(ctx, ["TalentAssessmentAdmin", "ComplianceOfficer", "VendorRepresentative"])
    v = _get_vendor_or_404(vid)
    if ctx.role == "VendorRepresentative" and ctx.user_id != v["id"]:
        raise err_ownership("VendorRepresentative may only read own vendor")
    return success_object(serializers.vendor(v))


@bp.get("/talent/vendors/<vid>/instruments")
def list_vendor_instruments(vid):
    ctx = authenticate()
    require_roles(ctx, ["TalentAssessmentAdmin", "ComplianceOfficer",
                        "VendorRepresentative", "HiringManager"])
    v = _get_vendor_or_404(vid)
    if ctx.role == "VendorRepresentative" and ctx.user_id != v["id"]:
        raise err_ownership("VendorRepresentative may only read own vendor")
    recs = [serializers.instrument(i) for i in sort_records(
        [i for i in db.stores["instruments"].values() if i["vendor_id"] == vid])]
    return paginate(recs)


@bp.get("/talent/vendors/<vid>/content-ledger-events")
def list_ledger(vid):
    ctx = authenticate()
    require_roles(ctx, ["TalentAssessmentAdmin", "ComplianceOfficer", "VendorRepresentative"])
    v = _get_vendor_or_404(vid)
    if ctx.role == "VendorRepresentative" and ctx.user_id != v["id"]:
        raise err_ownership("VendorRepresentative may only read own vendor")
    recs = [serializers.ledger_event(e) for e in sort_records(
        [e for e in db.stores["content_ledger_events"].values() if e["vendor_id"] == vid])]
    return paginate(recs)


@bp.post("/talent/vendors/<vid>/content-ledger-events")
def append_ledger(vid):
    ctx = authenticate()
    require_roles(ctx, ["TalentAssessmentAdmin", "VendorRepresentative"])
    v = _get_vendor_or_404(vid)
    if ctx.role == "VendorRepresentative" and ctx.user_id != v["id"]:
        raise err_ownership("VendorRepresentative may only act on own vendor")
    # Terminal lockdown (tier 7)
    if v["status"] == "TERMINATED":
        raise api_err("ERR_ALREADY_TERMINAL", "Vendor is TERMINATED")
    body = util.get_body()
    direction = req_enum(body, "direction", ["DISTRIBUTE", "DESTROY"])
    copies = req_int(body, "copies", lo=1)
    note = req_string(body, "note", min_len=10)
    # Business safety: DISTRIBUTE restricted to admin while ACTIVE
    if direction == "DISTRIBUTE":
        if ctx.role != "TalentAssessmentAdmin":
            raise api_err("ERR_FORBIDDEN", "Only TalentAssessmentAdmin may DISTRIBUTE")
        if v["status"] != "ACTIVE":
            raise api_err("ERR_VENDOR_NOT_ACTIVE", "Vendor must be ACTIVE to DISTRIBUTE")
    else:  # DESTROY
        if v["status"] not in ("ACTIVE", "SUSPENDED"):
            raise api_err("ERR_VENDOR_NOT_ACTIVE", "Vendor must be ACTIVE or SUSPENDED")
        if copies > v["content_copies_outstanding"]:
            raise api_err("ERR_CONTENT_LEDGER_NEGATIVE",
                          "DESTROY copies exceed content_copies_outstanding")
    now = db.get_now()
    rec = {
        "id": new_id(),
        "vendor_id": vid,
        "direction": direction,
        "copies": copies,
        "note": note,
        "recorded_by_user_id": ctx.user_id,
        "created_at": now,
        "_created": now,
        "_seq": next_seq(),
    }
    db.stores["content_ledger_events"][rec["id"]] = rec
    if direction == "DISTRIBUTE":
        v["content_copies_outstanding"] += copies
    else:
        v["content_copies_outstanding"] -= copies
    bump(v)
    return success_object(serializers.ledger_event(rec), 201)


@bp.post("/talent/vendors/<vid>/suspend")
def suspend_vendor(vid):
    ctx = authenticate()
    require_roles(ctx, ["TalentAssessmentAdmin"])
    v = _get_vendor_or_404(vid)
    if v["status"] == "TERMINATED":
        raise api_err("ERR_ALREADY_TERMINAL", "Vendor is TERMINATED")
    if v["status"] != "ACTIVE":
        raise api_err("ERR_INVALID_STATE", "Vendor must be ACTIVE to suspend")
    v["status"] = "SUSPENDED"
    bump(v)
    # LINK 1: flag instruments
    flagged_ids = set()
    for inst in db.stores["instruments"].values():
        if inst["vendor_id"] == vid and inst["validation_status"] != "RETIRED":
            inst["vendor_suspended"] = True
            bump(inst)
            flagged_ids.add(inst["id"])
    # LINK 2: freeze cycles
    frozen_cycles = []
    for cyc in db.stores["cycles"].values():
        if cyc["instrument_id"] in flagged_ids and cyc["posture"] in ("SETUP", "ACTIVE", "SCORING"):
            cyc["frozen_from_posture"] = cyc["posture"]
            cyc["posture"] = "FROZEN"
            cyc["frozen_reason"] = "VENDOR_HOLD"
            bump(cyc)
            frozen_cycles.append(cyc["id"])
    # LINK 3: cancel SCHEDULED sessions in those cycles
    for s in db.stores["sessions"].values():
        if s["cycle_id"] in frozen_cycles and s["status"] == "SCHEDULED":
            s["status"] = "CANCELLED"
            s["cancellation_reason"] = "VENDOR_HOLD"
            bump(s)
            core.recompute_interviewer_minutes(s["interviewer_id"])
            iv = db.stores["interviewers"].get(s["interviewer_id"])
            if iv is not None:
                bump(iv)
    return success_object(serializers.vendor(v))


@bp.post("/talent/vendors/<vid>/reinstate")
def reinstate_vendor(vid):
    ctx = authenticate()
    require_roles(ctx, ["TalentAssessmentAdmin"])
    v = _get_vendor_or_404(vid)
    if v["status"] == "TERMINATED":
        raise api_err("ERR_ALREADY_TERMINAL", "Vendor is TERMINATED")
    if v["status"] != "SUSPENDED":
        raise api_err("ERR_INVALID_STATE", "Vendor must be SUSPENDED to reinstate")
    v["status"] = "ACTIVE"
    bump(v)
    inst_ids = set()
    for inst in db.stores["instruments"].values():
        if inst["vendor_id"] == vid:
            if inst["vendor_suspended"]:
                inst["vendor_suspended"] = False
                bump(inst)
            inst_ids.add(inst["id"])
    for cyc in db.stores["cycles"].values():
        if (cyc["posture"] == "FROZEN" and cyc.get("frozen_reason") == "VENDOR_HOLD"
                and cyc["instrument_id"] in inst_ids):
            cyc["posture"] = cyc["frozen_from_posture"]
            cyc["frozen_from_posture"] = None
            cyc["frozen_reason"] = None
            bump(cyc)
    # Asymmetric compensation: cancelled sessions are NOT restored.
    return success_object(serializers.vendor(v))


@bp.post("/talent/vendors/<vid>/terminate")
def terminate_vendor(vid):
    ctx = authenticate()
    require_roles(ctx, ["TalentAssessmentAdmin"])
    v = _get_vendor_or_404(vid)
    if v["status"] == "TERMINATED":
        raise api_err("ERR_ALREADY_TERMINAL", "Vendor is TERMINATED")
    if v["status"] not in ("ACTIVE", "SUSPENDED"):
        raise api_err("ERR_INVALID_STATE", "Vendor cannot be terminated from this state")
    if v["content_copies_outstanding"] != 0:
        raise api_err("ERR_CONTENT_COPIES_OUTSTANDING",
                      "content_copies_outstanding must be 0 to terminate")
    v["status"] = "TERMINATED"
    v["terminated_at"] = db.get_now()
    bump(v)
    return success_object(serializers.vendor(v))
