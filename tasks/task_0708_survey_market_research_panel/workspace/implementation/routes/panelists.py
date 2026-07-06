"""Panelist + Consent endpoints (PRD §3.2, §3.4, §3.6)."""
from flask import Blueprint, request

import db
import errors
import lookup
import response
import validation
from middleware import get_identity, require_roles
from services import calc, core, lifecycle

bp = Blueprint("panelists", __name__)


@bp.post("/panelists")
def create_panelist():
    user_id, role = get_identity()
    require_roles(role, {"PanelOps"})
    body = validation.get_json_body()
    email = validation.require_str(body, "email")
    full_name = validation.require_str(body, "full_name")
    age = validation.require_int(body, "age", minimum=0)
    segment_key = validation.require_str(body, "segment_key")

    rec = db.base_record(common_fields=True)
    rec.update({
        "email": email,
        "full_name": full_name,
        "age": age,
        "segment_key": segment_key,
        "last_activity_at": None,
        "health_score": 100,
        "status": "ACTIVE",
    })
    db.panelists[rec["id"]] = rec
    return response.object_response(core.serialize_panelist(rec), status=201)


@bp.get("/panelists")
def list_panelists():
    user_id, role = get_identity()
    require_roles(role, {"PanelOps", "ResearchManager", "FieldCoordinator"})
    status = request.args.get("status")
    segment_key = request.args.get("segment_key")
    records = []
    for p in db.panelists.values():
        if status is not None and p["status"] != status:
            continue
        if segment_key is not None and p["segment_key"] != segment_key:
            continue
        records.append(p)
    window, limit, offset, total = validation.paginate(records)
    return response.array_response(
        [core.serialize_panelist(p) for p in window], limit, offset, total)


@bp.get("/panelists/<pid>")
def get_panelist(pid):
    user_id, role = get_identity()
    require_roles(role, {"PanelOps", "ResearchManager", "FieldCoordinator", "Panelist"})
    panelist = lookup.panelist(pid)
    return response.object_response(core.serialize_panelist(panelist))


@bp.get("/panelists/<pid>/health")
def panelist_health(pid):
    user_id, role = get_identity()
    require_roles(role, {"PanelOps", "ResearchManager"})
    panelist = lookup.panelist(pid)
    rolling, lifetime = core.health_scores(panelist)
    # Persist the recomputed rolling score + drive status (PRD §3.6).
    core.recompute_panelist_health(panelist)
    data = {
        "health_score": rolling,
        "lifetime_health_score": lifetime,
        "status": panelist["status"],
    }
    return response.object_response(data)


@bp.post("/panelists/<pid>/suspend")
def suspend_panelist(pid):
    user_id, role = get_identity()
    require_roles(role, {"PanelOps"})
    panelist = lookup.panelist(pid)
    if panelist["status"] not in ("ACTIVE", "AT_RISK"):
        errors.fail(errors.ERR_INVALID_STATE, "Panelist is not ACTIVE or AT_RISK")
    panelist["status"] = "SUSPENDED"
    db.touch(panelist)
    lifecycle.cascade_void_for_panelist(panelist["id"])
    return response.object_response(core.serialize_panelist(panelist))


@bp.post("/panelists/<pid>/reinstate")
def reinstate_panelist(pid):
    user_id, role = get_identity()
    require_roles(role, {"PanelOps"})
    panelist = lookup.panelist(pid)
    if panelist["status"] != "SUSPENDED":
        errors.fail(errors.ERR_INVALID_STATE, "Panelist is not SUSPENDED")
    panelist["status"] = "ACTIVE"
    db.touch(panelist)
    return response.object_response(core.serialize_panelist(panelist))


@bp.post("/panelists/<pid>/mark_churned")
def mark_churned(pid):
    user_id, role = get_identity()
    require_roles(role, {"PanelOps"})
    panelist = lookup.panelist(pid)
    if panelist["status"] != "AT_RISK":
        errors.fail(errors.ERR_INVALID_STATE, "Panelist is not AT_RISK")
    # Precondition: health_score < CHURN_FLOOR (PRD §3.6).
    if panelist["health_score"] >= calc.CHURN_FLOOR:
        errors.fail(errors.ERR_INVALID_STATE,
                    "health_score is not below the churn floor")
    panelist["status"] = "CHURNED"
    db.touch(panelist)
    lifecycle.cascade_void_for_panelist(panelist["id"])
    return response.object_response(core.serialize_panelist(panelist))


# ----- Consents -----
@bp.post("/consents")
def create_consent():
    user_id, role = get_identity()
    require_roles(role, {"PanelOps", "Panelist"})
    body = validation.get_json_body()
    panelist_id = validation.require_str(body, "panelist_id")
    study_id = validation.require_str(body, "study_id")
    consent_version = validation.require_int(body, "consent_version", minimum=1)
    decision = validation.require_enum(body, "decision",
                                       {"ACCEPTED", "DECLINED", "WITHDRAWN"})

    panelist = lookup.panelist(panelist_id)
    lookup.study(study_id)
    # Entity-backed Panelist may only record their own consent (PRD §2.1).
    if role == "Panelist" and panelist["id"] != user_id:
        errors.fail(errors.ERR_NOT_RESOURCE_OWNER,
                    "Panelist may only record their own consent")

    rec = db.base_record(common_fields=False)
    import clock
    rec.update({
        "panelist_id": panelist_id,
        "study_id": study_id,
        "consent_version": consent_version,
        "decision": decision,
        "recorded_at": clock.now_iso(),
    })
    db.consents[rec["id"]] = rec
    return response.object_response(core.serialize_consent(rec), status=201)


@bp.get("/consents")
def list_consents():
    user_id, role = get_identity()
    require_roles(role, {"PanelOps", "ResearchManager", "Panelist"})
    panelist_id = request.args.get("panelist_id")
    study_id = request.args.get("study_id")
    records = []
    for c in db.consents.values():
        if panelist_id is not None and c["panelist_id"] != panelist_id:
            continue
        if study_id is not None and c["study_id"] != study_id:
            continue
        records.append(c)
    window, limit, offset, total = validation.paginate(records)
    return response.array_response(
        [core.serialize_consent(c) for c in window], limit, offset, total)


@bp.get("/consents/<cid>")
def get_consent(cid):
    user_id, role = get_identity()
    require_roles(role, {"PanelOps", "ResearchManager", "Panelist"})
    consent = lookup.consent(cid)
    return response.object_response(core.serialize_consent(consent))
