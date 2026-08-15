"""CaptionTrack endpoints (PRD §3.3) and QCReview endpoints (PRD §3.4)."""
from flask import Blueprint, request

import serialize
from auth import ALL_ROLES, body, guarded
from db import DB, stamp_new, touch
from errors import (
    ApiError,
    ERR_REVIEW_MODE_NOT_PERMITTED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_WORK_ORDER_VERSION,
    invalid_transition,
    not_found,
    validation,
)
from respond import list_response, ok_object
from services import workflow
from services.qc import compute_accuracy, outcome_for, validate_review_shape
from util import is_int, req_enum, req_str

bp = Blueprint("caption_tracks", __name__)

CAPTION_FORMATS = {"SCC", "WEBVTT", "TTML", "SRT"}
SPEAKER_ID_STYLES = {"CHEVRON", "DASH", "NAME_TAG"}


def get_track(track_id):
    t = DB.caption_tracks.get(track_id)
    if t is None:
        raise not_found("Caption track not found")
    return t


@bp.post("/caption-ad/work-orders/<workOrderId>/caption-tracks")
@guarded({"CaptionEditor"})
def create_caption_track(workOrderId, _user_id, _role):
    order = DB.work_orders.get(workOrderId)
    if order is None:
        raise not_found("Work order not found")
    data = body()
    language = req_str(data, "language")
    caption_format = req_enum(data, "caption_format", CAPTION_FORMATS)
    speaker_id_style = req_enum(data, "speaker_id_style", SPEAKER_ID_STYLES)
    expected = data.get("expected_work_order_version")
    if not is_int(expected):
        raise validation("Field 'expected_work_order_version' is required and must be an integer")
    supersedes = data.get("supersedes_track_id")
    if supersedes is not None and not isinstance(supersedes, str):
        raise validation("Field 'supersedes_track_id' must be a string or null")
    # OCC (priority 6) precedes state admissibility (priority 7).
    if expected != order["version"]:
        raise ApiError(ERR_STALE_WORK_ORDER_VERSION, 412, "Stale work order version")
    if order["order_status"] != "IN_PRODUCTION":
        raise invalid_transition("Caption tracks can only be created while the order is IN_PRODUCTION")
    # A new version supersedes any in-flight version of the same work order.
    for t in DB.caption_tracks.values():
        if t["work_order_id"] == order["id"] and t["track_status"] in workflow.SUPERSEDABLE_STATES:
            t["track_status"] = "SUPERSEDED"
            touch(t)
    prior_max = max(
        (t["version_no"] for t in DB.caption_tracks.values() if t["work_order_id"] == order["id"]),
        default=0,
    )
    rec = {
        "work_order_id": order["id"],
        "supersedes_track_id": supersedes,
        "version_no": prior_max + 1,
        "language": language,
        "caption_format": caption_format,
        "speaker_id_style": speaker_id_style,
        "track_status": "AUTHORING",
        "author_user_id": _user_id,
        "qc_attempts": 0,
        "last_accuracy_pct": None,
    }
    stamp_new(rec)
    DB.caption_tracks[rec["id"]] = rec
    touch(order)  # creation increments the work order's version by one
    return ok_object(serialize.caption_track(rec), status=201)


@bp.get("/caption-ad/caption-tracks")
@guarded(set(ALL_ROLES))
def list_caption_tracks(_user_id, _role):
    records = list(DB.caption_tracks.values())
    for param, field in (
        ("work_order_id", "work_order_id"),
        ("supersedes_track_id", "supersedes_track_id"),
        ("track_status", "track_status"),
    ):
        v = request.args.get(param)
        if v is not None:
            records = [r for r in records if r[field] == v]
    return list_response(records, serialize.caption_track)


@bp.get("/caption-ad/caption-tracks/<trackId>")
@guarded(set(ALL_ROLES))
def get_one_caption_track(trackId, _user_id, _role):
    return ok_object(serialize.caption_track(get_track(trackId)))


def _transition(trackId, from_states, to_state):
    t = get_track(trackId)
    if t["track_status"] not in from_states:
        raise invalid_transition(f"Track in {t['track_status']} cannot move to {to_state}")
    t["track_status"] = to_state
    touch(t)
    return t


@bp.post("/caption-ad/caption-tracks/<trackId>/submit-review")
@guarded({"CaptionEditor"})
def submit_review(trackId, _user_id, _role):
    return ok_object(serialize.caption_track(_transition(trackId, {"AUTHORING"}, "INTERNAL_REVIEW")))


@bp.post("/caption-ad/caption-tracks/<trackId>/return-to-authoring")
@guarded({"CaptionEditor"})
def return_to_authoring(trackId, _user_id, _role):
    return ok_object(serialize.caption_track(_transition(trackId, {"INTERNAL_REVIEW"}, "AUTHORING")))


@bp.post("/caption-ad/caption-tracks/<trackId>/enqueue-qc")
@guarded({"CaptionEditor"})
def enqueue_qc(trackId, _user_id, _role):
    return ok_object(serialize.caption_track(_transition(trackId, {"INTERNAL_REVIEW"}, "QC_QUEUED")))


@bp.post("/caption-ad/caption-tracks/<trackId>/begin-rework")
@guarded({"CaptionEditor"})
def begin_rework(trackId, _user_id, _role):
    t = get_track(trackId)
    # Once the third FAIL lands the track is QC_FAILED_PERMANENT (terminal) and
    # a rework attempt there is rejected as an invalid transition.
    if t["track_status"] != "QC_FAILED" or t["qc_attempts"] >= 3:
        raise invalid_transition("Only a QC_FAILED track below three attempts can be reworked")
    t["track_status"] = "AUTHORING"
    touch(t)
    return ok_object(serialize.caption_track(t))


@bp.post("/caption-ad/caption-tracks/<trackId>/mark-conformed")
@guarded({"CaptionEditor"})
def mark_conformed(trackId, _user_id, _role):
    t = get_track(trackId)
    if t["track_status"] != "QC_PASSED":
        raise invalid_transition("Only a QC_PASSED track can be marked conformed")
    order = DB.work_orders[t["work_order_id"]]
    if order["order_status"] != "IN_PRODUCTION":
        raise invalid_transition("Work order must be IN_PRODUCTION to conform a track")
    t["track_status"] = "CONFORMED"
    touch(t)
    workflow.recompute_bubble(order)
    return ok_object(serialize.caption_track(t))


@bp.post("/caption-ad/caption-tracks/<trackId>/qc-reviews")
@guarded({"QCSpecialist"})
def create_qc_review(trackId, _user_id, _role):
    t = get_track(trackId)
    data = body()
    # Shape (priority 5), then state (7), then SoD / compliance (8).
    review_mode, total_words, sampled_words, counts = validate_review_shape(data)
    if t["track_status"] != "QC_QUEUED":
        raise invalid_transition("Only a QC_QUEUED track can be reviewed")
    if _user_id == t["author_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403, "Reviewer must differ from the track author")
    order = DB.work_orders[t["work_order_id"]]
    client = DB.clients[order["client_id"]]
    if review_mode == "SAMPLED_REVIEW" and client["compliance_standard"] == "FCC_BROADCAST":
        raise ApiError(ERR_REVIEW_MODE_NOT_PERMITTED, 422, "SAMPLED_REVIEW is never permitted for FCC_BROADCAST clients")
    weighted, accuracy = compute_accuracy(review_mode, total_words, sampled_words, counts)
    threshold, outcome = outcome_for(accuracy, client["compliance_standard"])
    rec = {
        "caption_track_id": t["id"],
        "reviewer_user_id": _user_id,
        "review_mode": review_mode,
        "total_words": total_words,
        "sampled_words": sampled_words,
        "minor_errors": counts["minor_errors"],
        "major_errors": counts["major_errors"],
        "critical_errors": counts["critical_errors"],
        "weighted_errors": weighted,
        "accuracy_pct": accuracy,
        "threshold_pct": threshold,
        "outcome": outcome,
    }
    # QCReview is immutable: only id and created_at (no updated_at / version).
    from db import new_id
    from db import now as _now
    rec["id"] = new_id()
    rec["created_at"] = _now()
    rec["_seq"] = next(DB._seq)
    DB.qc_reviews[rec["id"]] = rec
    # Drive the track: PASS -> QC_PASSED; FAIL -> QC_FAILED (third FAIL ->
    # QC_FAILED_PERMANENT immediately).
    t["last_accuracy_pct"] = accuracy
    if outcome == "PASS":
        t["track_status"] = "QC_PASSED"
    else:
        t["qc_attempts"] += 1
        t["track_status"] = "QC_FAILED"
        if t["qc_attempts"] >= 3:
            t["track_status"] = "QC_FAILED_PERMANENT"
    touch(t)
    return ok_object(serialize.qc_review(rec), status=201)


@bp.get("/caption-ad/qc-reviews")
@guarded(set(ALL_ROLES))
def list_qc_reviews(_user_id, _role):
    records = list(DB.qc_reviews.values())
    for param, field in (("caption_track_id", "caption_track_id"), ("outcome", "outcome")):
        v = request.args.get(param)
        if v is not None:
            records = [r for r in records if r[field] == v]
    return list_response(records, serialize.qc_review)


@bp.get("/caption-ad/qc-reviews/<qcReviewId>")
@guarded(set(ALL_ROLES))
def get_one_qc_review(qcReviewId, _user_id, _role):
    r = DB.qc_reviews.get(qcReviewId)
    if r is None:
        raise not_found("QC review not found")
    return ok_object(serialize.qc_review(r))
