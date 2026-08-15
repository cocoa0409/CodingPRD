"""Assessment cycles: posture state machine, OCC PATCH, and the close cascade
(PRD §3.4). Invitations also live here (nested under the cycle)."""
from datetime import timedelta

import db
import serializers
import util
from errors import (api_err, err_invalid_request, err_not_found, err_ownership,
                    err_ref_not_found)
from flask import Blueprint
from middleware import authenticate, require_roles
from response import success_object
from services import core
from util import (bump, filter_params, new_id, next_seq, opt_int, paginate,
                  parse_dt, req_string, sort_records)

bp = Blueprint("cycles", __name__)

READ_ROLES = ["HiringManager", "TalentAssessmentAdmin", "ComplianceOfficer",
              "DecisionOfficer", "Interviewer"]


def _get_cycle_or_404(cid):
    c = db.stores["cycles"].get(cid)
    if c is None:
        raise err_not_found("AssessmentCycle not found")
    return c


def _own_cycle(ctx, cyc):
    req = db.stores["requisitions"].get(cyc["requisition_id"])
    if req is None or req["hiring_manager_id"] != ctx.user_id:
        raise err_ownership("Only the owning HiringManager may operate on this cycle")
    return req


def _posture_gate(cyc, admitted):
    """Child-operation posture gate: FROZEN -> ERR_CYCLE_FROZEN; otherwise
    posture must be in `admitted` else ERR_CYCLE_NOT_ACTIVE."""
    if cyc["posture"] == "FROZEN":
        raise api_err("ERR_CYCLE_FROZEN", "Cycle is FROZEN")
    if cyc["posture"] not in admitted:
        raise api_err("ERR_CYCLE_NOT_ACTIVE", "Cycle posture does not admit this operation")


def _refresh(cyc):
    core.recompute_cycle_counters(cyc)
    return cyc


@bp.get("/talent/cycles")
def list_cycles():
    ctx = authenticate()
    require_roles(ctx, READ_ROLES)
    filters = filter_params(["requisition_id", "instrument_id", "guide_id", "posture"])
    recs = []
    for cyc in sort_records(list(db.stores["cycles"].values())):
        if "requisition_id" in filters and cyc["requisition_id"] != filters["requisition_id"]:
            continue
        if "instrument_id" in filters and cyc["instrument_id"] != filters["instrument_id"]:
            continue
        if "guide_id" in filters and cyc["guide_id"] != filters["guide_id"]:
            continue
        if "posture" in filters and cyc["posture"] != filters["posture"]:
            continue
        _refresh(cyc)
        recs.append(serializers.cycle(cyc))
    return paginate(recs)


@bp.get("/talent/cycles/<cid>")
def get_cycle(cid):
    ctx = authenticate()
    require_roles(ctx, READ_ROLES)
    cyc = _get_cycle_or_404(cid)
    _refresh(cyc)
    return success_object(serializers.cycle(cyc))


@bp.patch("/talent/cycles/<cid>")
def patch_cycle(cid):
    ctx = authenticate()
    require_roles(ctx, ["HiringManager"])
    cyc = _get_cycle_or_404(cid)
    body = util.get_body()
    # Body FK resolution (tier 4) precedes ownership (tier 5)
    new_instrument_id = body.get("instrument_id", cyc["instrument_id"])
    new_guide_id = body.get("guide_id", cyc["guide_id"])
    new_instrument = db.stores["instruments"].get(new_instrument_id)
    if new_instrument is None:
        raise err_ref_not_found("instrument_id does not resolve")
    new_guide = db.stores["guides"].get(new_guide_id)
    if new_guide is None:
        raise err_ref_not_found("guide_id does not resolve")
    _own_cycle(ctx, cyc)
    if cyc["posture"] != "SETUP":
        raise api_err("ERR_INVALID_STATE", "Cycle update is admitted only while SETUP")
    # OCC (tier 8) — non-optional per PRD §2.6
    expected = body.get("expected_cycle_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err_invalid_request("expected_cycle_version is required")
    if expected != cyc["version"]:
        raise api_err("ERR_STALE_CYCLE_VERSION",
                      "expected_cycle_version does not match the cycle's current version")
    # Re-pin readiness gates (tier 9): instrument VALIDATED, guide APPROVED
    if new_instrument_id != cyc["instrument_id"]:
        if new_instrument["validation_status"] != "VALIDATED":
            raise api_err("ERR_INSTRUMENT_NOT_VALIDATED",
                          "Replacement instrument must be VALIDATED")
    if new_guide_id != cyc["guide_id"]:
        if new_guide["status"] != "APPROVED":
            raise api_err("ERR_GUIDE_NOT_APPROVED", "Replacement guide must be APPROVED")
    # Field updates
    w_start = cyc["administration_window_start"]
    w_end = cyc["administration_window_end"]
    if "administration_window_start" in body and body["administration_window_start"] is not None:
        w_start = parse_dt(body["administration_window_start"], "administration_window_start")
    if "administration_window_end" in body and body["administration_window_end"] is not None:
        w_end = parse_dt(body["administration_window_end"], "administration_window_end")
    if w_start >= w_end:
        raise api_err("ERR_WINDOW_ORDER_INVALID",
                      "administration_window_start must be before administration_window_end")
    if "max_sessions_per_day" in body and body["max_sessions_per_day"] is not None:
        m = body["max_sessions_per_day"]
        if isinstance(m, bool) or not isinstance(m, int) or m < 1 or m > 100:
            raise err_invalid_request("max_sessions_per_day must be an integer 1..100")
        cyc["max_sessions_per_day"] = m
    old_guide_id = cyc["guide_id"]
    cyc["administration_window_start"] = w_start
    cyc["administration_window_end"] = w_end
    cyc["instrument_id"] = new_instrument_id
    cyc["guide_id"] = new_guide_id
    bump(cyc)
    if new_guide_id != old_guide_id:
        old_guide = db.stores["guides"].get(old_guide_id)
        if old_guide is not None:
            core.recompute_guide_pins(old_guide)
            bump(old_guide)
        core.recompute_guide_pins(new_guide)
        bump(new_guide)
    _refresh(cyc)
    return success_object(serializers.cycle(cyc))


@bp.post("/talent/cycles/<cid>/activate")
def activate_cycle(cid):
    ctx = authenticate()
    require_roles(ctx, ["HiringManager"])
    cyc = _get_cycle_or_404(cid)
    req = _own_cycle(ctx, cyc)
    if cyc["posture"] != "SETUP":
        raise api_err("ERR_INVALID_STATE", "Cycle must be SETUP to activate")
    if req["status"] != "OPEN":
        raise api_err("ERR_REQUISITION_NOT_OPEN", "Requisition must be OPEN")
    instrument = db.stores["instruments"].get(cyc["instrument_id"])
    guide = db.stores["guides"].get(cyc["guide_id"])
    if instrument is None or instrument["validation_status"] != "VALIDATED":
        raise api_err("ERR_INSTRUMENT_NOT_VALIDATED", "Instrument must be VALIDATED")
    vendor = db.stores["vendors"].get(instrument["vendor_id"])
    if vendor is None or vendor["status"] != "ACTIVE" or instrument["vendor_suspended"]:
        raise api_err("ERR_VENDOR_NOT_ACTIVE",
                      "Vendor must be ACTIVE and instrument not vendor-suspended")
    if guide is None or guide["status"] != "APPROVED":
        raise api_err("ERR_GUIDE_NOT_APPROVED", "Guide must be APPROVED")
    if cyc["administration_window_end"] < db.get_now():
        raise api_err("ERR_OUTSIDE_ADMINISTRATION_WINDOW",
                      "administration_window_end is in the past")
    cyc["posture"] = "ACTIVE"
    bump(cyc)
    _refresh(cyc)
    return success_object(serializers.cycle(cyc))


@bp.post("/talent/cycles/<cid>/freeze")
def freeze_cycle(cid):
    ctx = authenticate()
    require_roles(ctx, ["ComplianceOfficer"])
    cyc = _get_cycle_or_404(cid)
    if cyc["posture"] not in ("SETUP", "ACTIVE", "SCORING"):
        raise api_err("ERR_INVALID_STATE",
                      "Freeze admitted only from SETUP, ACTIVE, or SCORING")
    body = util.get_body()
    reason = body.get("freeze_reason", "MANUAL")
    if reason not in ("MANUAL", "ADVERSE_IMPACT"):
        raise err_invalid_request("freeze_reason must be MANUAL or ADVERSE_IMPACT")
    cyc["frozen_from_posture"] = cyc["posture"]
    cyc["posture"] = "FROZEN"
    cyc["frozen_reason"] = reason
    bump(cyc)
    _refresh(cyc)
    return success_object(serializers.cycle(cyc))


@bp.post("/talent/cycles/<cid>/unfreeze")
def unfreeze_cycle(cid):
    ctx = authenticate()
    require_roles(ctx, ["ComplianceOfficer"])
    cyc = _get_cycle_or_404(cid)
    if cyc["posture"] != "FROZEN":
        raise api_err("ERR_INVALID_STATE", "Cycle must be FROZEN to unfreeze")
    body = util.get_body()
    # Reason-specific safety gates (tier 9) precede the note shape check (16)
    if cyc.get("frozen_reason") == "ADVERSE_IMPACT":
        has_final = any(
            s["cycle_id"] == cid and s["snapshot_type"] == "FINAL"
            for s in db.stores["snapshots"].values()
        )
        if not has_final:
            raise api_err("ERR_ADVERSE_IMPACT_UNRESOLVED",
                          "Unfreezing an ADVERSE_IMPACT hold requires a FINAL snapshot")
    if cyc.get("frozen_reason") == "VENDOR_HOLD":
        instrument = db.stores["instruments"].get(cyc["instrument_id"])
        vendor = (db.stores["vendors"].get(instrument["vendor_id"])
                  if instrument else None)
        if (instrument is None or vendor is None or vendor["status"] != "ACTIVE"
                or instrument["vendor_suspended"]):
            raise api_err("ERR_VENDOR_NOT_ACTIVE",
                          "VENDOR_HOLD unfreeze requires vendor ACTIVE and flag cleared")
    note = body.get("resolution_note")
    if not isinstance(note, str) or len(note) < 20:
        raise err_invalid_request("resolution_note of at least 20 characters is required")
    cyc["posture"] = cyc["frozen_from_posture"]
    cyc["frozen_from_posture"] = None
    cyc["frozen_reason"] = None
    bump(cyc)
    _refresh(cyc)
    return success_object(serializers.cycle(cyc))


@bp.post("/talent/cycles/<cid>/begin-scoring")
def begin_scoring(cid):
    ctx = authenticate()
    require_roles(ctx, ["HiringManager"])
    cyc = _get_cycle_or_404(cid)
    _own_cycle(ctx, cyc)
    if cyc["posture"] != "ACTIVE":
        raise api_err("ERR_INVALID_STATE", "Cycle must be ACTIVE to begin scoring")
    for s in db.stores["sessions"].values():
        if s["cycle_id"] == cid and s["status"] == "SCHEDULED":
            raise api_err("ERR_SESSIONS_STILL_SCHEDULED",
                          "SCHEDULED sessions remain in this cycle")
    cyc["posture"] = "SCORING"
    bump(cyc)
    _refresh(cyc)
    return success_object(serializers.cycle(cyc))


@bp.post("/talent/cycles/<cid>/close")
def close_cycle(cid):
    ctx = authenticate()
    require_roles(ctx, ["HiringManager"])
    cyc = _get_cycle_or_404(cid)
    _own_cycle(ctx, cyc)
    if cyc["posture"] == "CLOSED":
        raise api_err("ERR_INVALID_STATE", "Cycle is already CLOSED")
    now = db.get_now()
    # LINK 1 + 2: cancel non-terminal assessments, sessions, accommodations
    for a in list(db.stores["assessments"].values()):
        if a["cycle_id"] == cid and a["admin_status"] in core.CANCELLABLE_ADMIN:
            core.cancel_assessment(a, "CYCLE_CLOSED")
    cyc["posture"] = "CLOSED"
    cyc["closed_at"] = now
    cyc["frozen_from_posture"] = None
    cyc["frozen_reason"] = None
    bump(cyc)
    # LINK 3: retention anchor for assessments without a FINALIZED decision
    for a in db.stores["assessments"].values():
        if a["cycle_id"] != cid:
            continue
        if core.finalized_decision(cid, a["candidate_id"]) is None:
            core.recompute_retention_anchor(a)
            bump(a)
    _refresh(cyc)
    guide = db.stores["guides"].get(cyc["guide_id"])
    if guide is not None:
        core.recompute_guide_pins(guide)
        bump(guide)
    return success_object(serializers.cycle(cyc))


@bp.post("/talent/cycles/<cid>/invitations")
def invite_candidate(cid):
    ctx = authenticate()
    require_roles(ctx, ["HiringManager"])
    cyc = _get_cycle_or_404(cid)
    body = util.get_body()
    candidate_id = body.get("candidate_id")
    if not isinstance(candidate_id, str):
        raise err_invalid_request("candidate_id is required")
    candidate = db.stores["candidates"].get(candidate_id)
    if candidate is None:
        raise err_ref_not_found("candidate_id does not resolve")
    _own_cycle(ctx, cyc)
    # Posture: invitations admitted in SETUP or ACTIVE; FROZEN distinct code
    _posture_gate(cyc, ("SETUP", "ACTIVE"))
    if candidate["status"] != "ACTIVE":
        raise api_err("ERR_CANDIDATE_WITHDRAWN", "Candidate is WITHDRAWN")
    for a in db.stores["assessments"].values():
        if a["cycle_id"] == cid and a["candidate_id"] == candidate_id:
            raise api_err("ERR_DUPLICATE_INVITATION",
                          "Candidate already invited into this cycle")
    now = db.get_now()
    rec = {
        "id": new_id(),
        "cycle_id": cid,
        "candidate_id": candidate_id,
        "admin_status": "INVITED",
        "feedback_status": "NOT_SENT",
        "scheduled_for": None,
        "started_at": None,
        "completed_at": None,
        "raw_score": None,
        "composite_score": None,
        "accommodation_extension_days": 0,
        "retention_expires_at": None,
        "purged_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_created": now,
        "_seq": next_seq(),
    }
    db.stores["assessments"][rec["id"]] = rec
    cyc["active_candidate_count"] += 1
    bump(cyc)
    return success_object(serializers.assessment(rec), 201)
