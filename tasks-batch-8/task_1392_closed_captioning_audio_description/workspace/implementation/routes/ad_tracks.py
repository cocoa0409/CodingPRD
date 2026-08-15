"""AudioDescriptionTrack endpoints (PRD §3.5)."""
from flask import Blueprint, request

import serialize
from auth import ALL_ROLES, body, guarded
from db import DB, now, stamp_new, touch
from errors import (
    ApiError,
    ERR_GAP_COVERAGE_OUT_OF_BAND,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STUDIO_TURNOVER_VIOLATION,
    invalid_transition,
    not_found,
    validation,
)
from respond import list_response, ok_object
from services import workflow
from services.ad import (
    COVERAGE_MAX_PCT,
    COVERAGE_MIN_PCT,
    compute_gap_coverage,
    studio_conflict,
    validate_gaps,
    validate_segments,
)
from util import req_str

bp = Blueprint("ad_tracks", __name__)


def get_ad_track(ad_track_id):
    t = DB.ad_tracks.get(ad_track_id)
    if t is None:
        raise not_found("Audio description track not found")
    return t


@bp.post("/caption-ad/work-orders/<workOrderId>/audio-description-tracks")
@guarded({"ADProducer"})
def create_ad_track(workOrderId, _user_id, _role):
    order = DB.work_orders.get(workOrderId)
    if order is None:
        raise not_found("Work order not found")
    data = body()
    language = req_str(data, "language")
    narrator_name = req_str(data, "narrator_name")
    if "gaps" not in data:
        raise validation("Field 'gaps' is required")
    if "segments" not in data:
        raise validation("Field 'segments' is required")
    gaps = validate_gaps(data["gaps"])
    segments = validate_segments(data["segments"], gaps)
    if order["order_status"] != "IN_PRODUCTION":
        raise invalid_transition("AD tracks can only be created while the order is IN_PRODUCTION")
    rec = {
        "work_order_id": order["id"],
        "language": language,
        "narrator_name": narrator_name,
        "author_user_id": _user_id,
        "ad_status": "SCRIPTING",
        "gaps": gaps,
        "segments": segments,
        "gap_coverage_pct": None,
        "studio_id": None,
        "record_start_at": None,
        "record_end_at": None,
    }
    stamp_new(rec)
    DB.ad_tracks[rec["id"]] = rec
    return ok_object(serialize.ad_track(rec), status=201)


@bp.get("/caption-ad/audio-description-tracks")
@guarded(set(ALL_ROLES))
def list_ad_tracks(_user_id, _role):
    records = list(DB.ad_tracks.values())
    for param, field in (("work_order_id", "work_order_id"), ("ad_status", "ad_status")):
        v = request.args.get(param)
        if v is not None:
            records = [r for r in records if r[field] == v]
    return list_response(records, serialize.ad_track)


@bp.get("/caption-ad/audio-description-tracks/<adTrackId>")
@guarded(set(ALL_ROLES))
def get_one_ad_track(adTrackId, _user_id, _role):
    return ok_object(serialize.ad_track(get_ad_track(adTrackId)))


@bp.patch("/caption-ad/audio-description-tracks/<adTrackId>")
@guarded({"ADProducer"})
def edit_ad_track(adTrackId, _user_id, _role):
    t = get_ad_track(adTrackId)
    data = body()
    if "gaps" in data and data["gaps"] is not None:
        new_gaps = validate_gaps(data["gaps"])
    else:
        new_gaps = None
    if "segments" in data and data["segments"] is not None:
        effective_gaps = new_gaps if new_gaps is not None else t["gaps"]
        new_segments = validate_segments(data["segments"], effective_gaps)
    else:
        new_segments = None
    if "narrator_name" in data and data["narrator_name"] is not None:
        new_narrator = req_str(data, "narrator_name")
    else:
        new_narrator = None
    # Editable only while SCRIPTING.
    if t["ad_status"] != "SCRIPTING":
        raise invalid_transition("AD tracks are editable only while SCRIPTING")
    if new_gaps is not None:
        t["gaps"] = new_gaps
    if new_segments is not None:
        t["segments"] = new_segments
    if new_narrator is not None:
        t["narrator_name"] = new_narrator
    touch(t)
    return ok_object(serialize.ad_track(t))


@bp.post("/caption-ad/audio-description-tracks/<adTrackId>/submit-script")
@guarded({"ADProducer"})
def submit_script(adTrackId, _user_id, _role):
    t = get_ad_track(adTrackId)
    # Shape (priority 5): segments non-empty at submit-script.
    if not t["segments"]:
        raise validation("Field 'segments' must be non-empty at submit-script")
    if t["ad_status"] != "SCRIPTING":
        raise invalid_transition("Only a SCRIPTING track can submit its script")
    coverage = compute_gap_coverage(t["gaps"], t["segments"])
    if not (COVERAGE_MIN_PCT <= coverage <= COVERAGE_MAX_PCT):
        raise ApiError(
            ERR_GAP_COVERAGE_OUT_OF_BAND,
            422,
            "Gap coverage must land between 35.0 and 85.0 inclusive",
        )
    t["gap_coverage_pct"] = coverage
    t["ad_status"] = "SCRIPT_REVIEW"
    touch(t)
    return ok_object(serialize.ad_track(t))


@bp.post("/caption-ad/audio-description-tracks/<adTrackId>/approve-script")
@guarded({"QCSpecialist"})
def approve_script(adTrackId, _user_id, _role):
    t = get_ad_track(adTrackId)
    if t["ad_status"] != "SCRIPT_REVIEW":
        raise invalid_transition("Only a SCRIPT_REVIEW track can be approved")
    if _user_id == t["author_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403, "Approver must differ from the track author")
    t["ad_status"] = "RECORDING"
    touch(t)
    return ok_object(serialize.ad_track(t))


@bp.post("/caption-ad/audio-description-tracks/<adTrackId>/reject-script")
@guarded({"QCSpecialist"})
def reject_script(adTrackId, _user_id, _role):
    t = get_ad_track(adTrackId)
    note = body().get("rejection_note")
    if not isinstance(note, str) or note == "":
        raise validation("Field 'rejection_note' is required and must be non-empty")
    if t["ad_status"] != "SCRIPT_REVIEW":
        raise invalid_transition("Only a SCRIPT_REVIEW track can be rejected")
    t["ad_status"] = "SCRIPTING"
    touch(t)
    return ok_object(serialize.ad_track(t))


@bp.post("/caption-ad/audio-description-tracks/<adTrackId>/book-studio")
@guarded({"ADProducer"})
def book_studio(adTrackId, _user_id, _role):
    from util import req_dt
    t = get_ad_track(adTrackId)
    data = body()
    studio_id = req_str(data, "studio_id")
    record_start_at = req_dt(data, "record_start_at")
    record_end_at = req_dt(data, "record_end_at")
    if record_end_at <= record_start_at:
        raise validation("Field 'record_end_at' must be after 'record_start_at'")
    if t["ad_status"] != "RECORDING":
        raise invalid_transition("Studio time can only be booked while RECORDING")
    if studio_conflict(studio_id, t["id"], record_start_at, record_end_at):
        raise ApiError(
            ERR_STUDIO_TURNOVER_VIOLATION,
            409,
            "Studio bookings on the same studio_id must be separated by at least 30 minutes",
        )
    t["studio_id"] = studio_id
    t["record_start_at"] = record_start_at
    t["record_end_at"] = record_end_at
    touch(t)
    return ok_object(serialize.ad_track(t))


@bp.post("/caption-ad/audio-description-tracks/<adTrackId>/submit-mix")
@guarded({"ADProducer"})
def submit_mix(adTrackId, _user_id, _role):
    t = get_ad_track(adTrackId)
    if t["ad_status"] != "RECORDING":
        raise invalid_transition("Only a RECORDING track can submit its mix")
    if t["studio_id"] is None or t["record_start_at"] is None or t["record_end_at"] is None:
        raise invalid_transition("A studio booking must be present before submitting the mix")
    if now() < t["record_end_at"]:
        raise invalid_transition("The mix cannot be submitted before the booking ends")
    t["ad_status"] = "MIX_QC"
    touch(t)
    return ok_object(serialize.ad_track(t))


@bp.post("/caption-ad/audio-description-tracks/<adTrackId>/approve-mix")
@guarded({"QCSpecialist"})
def approve_mix(adTrackId, _user_id, _role):
    t = get_ad_track(adTrackId)
    if t["ad_status"] != "MIX_QC":
        raise invalid_transition("Only a MIX_QC track can be approved")
    if _user_id == t["author_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403, "Approver must differ from the track author")
    t["ad_status"] = "CONFORMED"
    touch(t)
    order = DB.work_orders[t["work_order_id"]]
    workflow.recompute_bubble(order)
    return ok_object(serialize.ad_track(t))


@bp.post("/caption-ad/audio-description-tracks/<adTrackId>/reject-mix")
@guarded({"QCSpecialist"})
def reject_mix(adTrackId, _user_id, _role):
    t = get_ad_track(adTrackId)
    note = body().get("rejection_note")
    if not isinstance(note, str) or note == "":
        raise validation("Field 'rejection_note' is required and must be non-empty")
    if t["ad_status"] != "MIX_QC":
        raise invalid_transition("Only a MIX_QC track can be rejected")
    t["ad_status"] = "RECORDING"
    # Mix rejection clears the studio booking; the producer must re-book.
    t["studio_id"] = None
    t["record_start_at"] = None
    t["record_end_at"] = None
    touch(t)
    return ok_object(serialize.ad_track(t))
