"""RecordingGrant routes."""
from flask import Blueprint, request

import db
from errors import (
    err_not_found, err_referenced_not_found, err_invalid_request, err_invalid_state,
    err_recording_prohibited, err_streaming_classification_block,
)
from middleware import require_roles, check_applicant_owner
from response import ok_object, ok_list, parse_pagination
from services import calculations
from services.serializers import recording_grant_out

bp = Blueprint("recording_grants", __name__)

GRANT_KINDS = {"CAST_RECORDING_AUDIO", "STREAMING_VIDEO", "ARCHIVAL_VIDEO"}
DISTRIBUTION_SCOPES = {"CAST_CREW_ONLY", "PAYWALL", "PUBLIC_FREE"}


@bp.post("/licensing/recording-grants")
def create_recording_grant():
    user_id, role = require_roles("Applicant")
    body = request.get_json(silent=True) or {}
    agreement_id = body.get("agreement_id")
    if not isinstance(agreement_id, str) or not agreement_id:
        raise err_invalid_request("agreement_id is required")
    g = db.agreements.get(agreement_id)
    if not g:
        raise err_referenced_not_found("agreement_id not found")
    check_applicant_owner(user_id, role, g["organization_id"])
    grant_kind = body.get("grant_kind")
    if grant_kind not in GRANT_KINDS:
        raise err_invalid_request("grant_kind invalid")
    scope = body.get("distribution_scope")
    if scope not in DISTRIBUTION_SCOPES:
        raise err_invalid_request("distribution_scope invalid")
    now = db.clock_now()
    gr = {
        "id": db.new_id(),
        "agreement_id": agreement_id,
        "grant_kind": grant_kind,
        "distribution_scope": scope,
        "recording_royalty_cents": 0,
        "status": "REQUESTED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.recording_grants[gr["id"]] = gr
    return ok_object(recording_grant_out(gr), 201)


@bp.get("/licensing/recording-grants/<grant_id>")
def get_recording_grant(grant_id):
    user_id, role = require_roles("RightsAdmin", "LicensingOfficer", "Applicant", "FinanceOfficer")
    gr = db.recording_grants.get(grant_id)
    if not gr:
        raise err_not_found("RecordingGrant not found")
    if role == "Applicant":
        g = db.agreements[gr["agreement_id"]]
        check_applicant_owner(user_id, role, g["organization_id"])
    return ok_object(recording_grant_out(gr))


@bp.get("/licensing/recording-grants")
def list_recording_grants():
    user_id, role = require_roles("RightsAdmin", "LicensingOfficer", "Applicant", "FinanceOfficer")
    limit, offset = parse_pagination(request.args)
    agreement_id = request.args.get("agreement_id")
    status = request.args.get("status")
    items = list(db.recording_grants.values())
    if role == "Applicant":
        items = [g for g in items if db.agreements[g["agreement_id"]]["organization_id"] == user_id]
    if agreement_id is not None:
        items = [g for g in items if g["agreement_id"] == agreement_id]
    if status is not None:
        items = [g for g in items if g["status"] == status]
    items.sort(key=lambda g: (g["created_at"], g["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([recording_grant_out(g) for g in page], limit, offset, total)


@bp.post("/licensing/recording-grants/<grant_id>/approve")
def approve_recording_grant(grant_id):
    require_roles("RightsAdmin")
    gr = db.recording_grants.get(grant_id)
    if not gr:
        raise err_not_found("RecordingGrant not found")
    if gr["status"] != "REQUESTED":
        raise err_invalid_state("RecordingGrant must be REQUESTED")
    g = db.agreements[gr["agreement_id"]]
    if g["license_status"] != "ACTIVE":
        raise err_invalid_state("Agreement must be ACTIVE")
    title = db.titles[g["title_id"]]
    if gr["grant_kind"] == "STREAMING_VIDEO" and g["classification"] != "AMATEUR":
        raise err_streaming_classification_block()
    if gr["distribution_scope"] == "PUBLIC_FREE" and gr["grant_kind"] == "STREAMING_VIDEO" and title["restricted_material"]:
        raise err_recording_prohibited()
    royalty = calculations.recording_royalty(title, gr["grant_kind"], gr["distribution_scope"])
    gr["recording_royalty_cents"] = royalty
    gr["status"] = "APPROVED"
    gr["updated_at"] = db.clock_now()
    gr["version"] += 1
    g["royalty_balance_cents"] += royalty
    g["updated_at"] = db.clock_now()
    g["version"] += 1
    return ok_object(recording_grant_out(gr))


@bp.post("/licensing/recording-grants/<grant_id>/deny")
def deny_recording_grant(grant_id):
    require_roles("RightsAdmin")
    gr = db.recording_grants.get(grant_id)
    if not gr:
        raise err_not_found("RecordingGrant not found")
    if gr["status"] != "REQUESTED":
        raise err_invalid_state("RecordingGrant must be REQUESTED")
    gr["status"] = "DENIED"
    gr["updated_at"] = db.clock_now()
    gr["version"] += 1
    return ok_object(recording_grant_out(gr))


@bp.post("/licensing/recording-grants/<grant_id>/mark_exercised")
def mark_exercised(grant_id):
    user_id, role = require_roles("Applicant")
    gr = db.recording_grants.get(grant_id)
    if not gr:
        raise err_not_found("RecordingGrant not found")
    g = db.agreements[gr["agreement_id"]]
    check_applicant_owner(user_id, role, g["organization_id"])
    if gr["status"] != "APPROVED":
        raise err_invalid_state("RecordingGrant must be APPROVED to mark exercised")
    if g["license_status"] != "ACTIVE":
        raise err_invalid_state("Agreement must be ACTIVE")
    now = db.clock_now()
    if not (g["window_start"] <= now <= g["window_end"]):
        raise err_invalid_state("Current clock outside agreement window")
    gr["status"] = "EXERCISED"
    gr["updated_at"] = now
    gr["version"] += 1
    return ok_object(recording_grant_out(gr))
