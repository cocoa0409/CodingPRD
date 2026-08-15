"""MediaAsset endpoints (PRD §3.1): intake, inspection, clear, reject."""
from flask import Blueprint, request

import serialize
from auth import ALL_ROLES, body, guarded
from db import DB, stamp_new, touch
from errors import invalid_transition, not_found, validation
from respond import list_response, ok_object
from util import req_enum, req_int, req_str

bp = Blueprint("media_assets", __name__)

MEDIA_KINDS = {"FILE_BASED", "LIVE_RECORDING"}
FRAME_RATES = {"FPS_23_976", "FPS_24", "FPS_25", "FPS_29_97_DF", "FPS_29_97_NDF", "FPS_30"}


def get_media(media_id):
    m = DB.media_assets.get(media_id)
    if m is None:
        raise not_found("Media asset not found")
    return m


@bp.post("/caption-ad/media-assets")
@guarded({"IntakeCoordinator"})
def create_media_asset(_user_id, _role):
    data = body()
    # Body FKs resolve left to right (client_id) before shape checks.
    client_id = data.get("client_id")
    if not isinstance(client_id, str) or client_id not in DB.clients:
        raise not_found("Referenced client_id does not exist")
    title = req_str(data, "title")
    media_kind = req_enum(data, "media_kind", MEDIA_KINDS)
    duration_seconds = req_int(data, "duration_seconds", minimum=1)
    frame_rate = req_enum(data, "frame_rate", FRAME_RATES)
    rec = {
        "client_id": client_id,
        "title": title,
        "media_kind": media_kind,
        "duration_seconds": duration_seconds,
        "frame_rate": frame_rate,
        "intake_status": "RECEIVED",
        "rejection_reason": None,
    }
    stamp_new(rec)
    DB.media_assets[rec["id"]] = rec
    return ok_object(serialize.media_asset(rec), status=201)


@bp.get("/caption-ad/media-assets")
@guarded(set(ALL_ROLES))
def list_media_assets(_user_id, _role):
    records = list(DB.media_assets.values())
    client_id = request.args.get("client_id")
    if client_id is not None:
        records = [r for r in records if r["client_id"] == client_id]
    status = request.args.get("intake_status")
    if status is not None:
        records = [r for r in records if r["intake_status"] == status]
    return list_response(records, serialize.media_asset)


@bp.get("/caption-ad/media-assets/<mediaAssetId>")
@guarded(set(ALL_ROLES))
def get_one_media_asset(mediaAssetId, _user_id, _role):
    return ok_object(serialize.media_asset(get_media(mediaAssetId)))


@bp.post("/caption-ad/media-assets/<mediaAssetId>/begin-inspection")
@guarded({"IntakeCoordinator"})
def begin_inspection(mediaAssetId, _user_id, _role):
    m = get_media(mediaAssetId)
    if m["intake_status"] != "RECEIVED":
        raise invalid_transition("Only a RECEIVED asset can begin inspection")
    m["intake_status"] = "INSPECTING"
    touch(m)
    return ok_object(serialize.media_asset(m))


@bp.post("/caption-ad/media-assets/<mediaAssetId>/clear")
@guarded({"IntakeCoordinator"})
def clear_media(mediaAssetId, _user_id, _role):
    m = get_media(mediaAssetId)
    if m["intake_status"] != "INSPECTING":
        raise invalid_transition("Only an INSPECTING asset can be cleared")
    m["intake_status"] = "CLEARED"
    touch(m)
    return ok_object(serialize.media_asset(m))


@bp.post("/caption-ad/media-assets/<mediaAssetId>/reject")
@guarded({"IntakeCoordinator"})
def reject_media(mediaAssetId, _user_id, _role):
    m = get_media(mediaAssetId)
    # Request shape (priority 5) precedes state admissibility (priority 7):
    # rejection requires a non-empty rejection_reason.
    reason = body().get("rejection_reason")
    if not isinstance(reason, str) or reason == "":
        raise validation("Field 'rejection_reason' is required and must be non-empty")
    if m["intake_status"] != "INSPECTING":
        raise invalid_transition("Only an INSPECTING asset can be rejected")
    m["intake_status"] = "REJECTED_INTAKE"
    m["rejection_reason"] = reason
    touch(m)
    return ok_object(serialize.media_asset(m))
