"""ConversionJob endpoints (PRD §3.9): create, run, retry, cancel."""
from flask import Blueprint, request

import serialize
from auth import ALL_ROLES, body, guarded
from db import DB, stamp_new, touch
from errors import (
    ApiError,
    ERR_CONVERSION_SAME_FORMAT,
    ERR_EMBED_NOT_SUPPORTED,
    ERR_RETRY_LIMIT_REACHED,
    ERR_SOURCE_TRACK_NOT_FINAL,
    invalid_transition,
    not_found,
)
from respond import list_response, ok_object
from util import is_int, opt_bool, req_enum, req_int

bp = Blueprint("conversion_jobs", __name__)

TARGET_FORMATS = {"SCC", "WEBVTT", "TTML", "SRT"}
FINAL_SOURCE_STATES = {"CONFORMED", "DELIVERED", "SUPERSEDED", "ARCHIVED"}
MAX_OUTPUT_DELTA_MS = 250


def get_job(job_id):
    j = DB.conversion_jobs.get(job_id)
    if j is None:
        raise not_found("Conversion job not found")
    return j


@bp.post("/caption-ad/conversion-jobs")
@guarded({"OperationsManager", "CaptionEditor"})
def create_conversion_job(_user_id, _role):
    data = body()
    source_track_id = data.get("source_track_id")
    if not isinstance(source_track_id, str) or source_track_id not in DB.caption_tracks:
        raise not_found("Referenced source_track_id does not exist")
    target_format = req_enum(data, "target_format", TARGET_FORMATS)
    embed = opt_bool(data, "embed", default=False)
    source = DB.caption_tracks[source_track_id]
    # Capacity/cardinality checks (priority 10) precede linked-entity state (11).
    if target_format == source["caption_format"]:
        raise ApiError(ERR_CONVERSION_SAME_FORMAT, 422, "target_format must differ from the source caption_format")
    if embed and target_format != "SCC":
        raise ApiError(ERR_EMBED_NOT_SUPPORTED, 422, "embed is only supported when target_format is SCC")
    if source["track_status"] not in FINAL_SOURCE_STATES:
        raise ApiError(ERR_SOURCE_TRACK_NOT_FINAL, 409, "Source track is not in a final state")
    rec = {
        "source_track_id": source_track_id,
        "target_format": target_format,
        "embed": embed,
        "job_status": "QUEUED",
        "attempt_count": 0,
        "output_duration_ms": None,
        "last_delta_ms": None,
    }
    stamp_new(rec)
    DB.conversion_jobs[rec["id"]] = rec
    return ok_object(serialize.conversion_job(rec), status=201)


@bp.get("/caption-ad/conversion-jobs")
@guarded(set(ALL_ROLES))
def list_conversion_jobs(_user_id, _role):
    records = list(DB.conversion_jobs.values())
    for param, field in (("source_track_id", "source_track_id"), ("job_status", "job_status")):
        v = request.args.get(param)
        if v is not None:
            records = [r for r in records if r[field] == v]
    return list_response(records, serialize.conversion_job)


@bp.get("/caption-ad/conversion-jobs/<conversionJobId>")
@guarded(set(ALL_ROLES))
def get_one_conversion_job(conversionJobId, _user_id, _role):
    return ok_object(serialize.conversion_job(get_job(conversionJobId)))


@bp.post("/caption-ad/conversion-jobs/<conversionJobId>/run")
@guarded({"OperationsManager"})
def run_conversion_job(conversionJobId, _user_id, _role):
    j = get_job(conversionJobId)
    output_duration_ms = body().get("output_duration_ms")
    if not is_int(output_duration_ms):
        from errors import validation
        raise validation("Field 'output_duration_ms' is required and must be an integer")
    if j["job_status"] != "QUEUED":
        raise invalid_transition("Only a QUEUED job can run")
    # One run is a single atomic pass QUEUED -> CONVERTING -> VALIDATING ->
    # COMPLETED | FAILED_VALIDATION; the intermediate states never rest.
    source = DB.caption_tracks[j["source_track_id"]]
    order = DB.work_orders[source["work_order_id"]]
    media = DB.media_assets[order["media_asset_id"]]
    delta = output_duration_ms - media["duration_seconds"] * 1000
    j["output_duration_ms"] = output_duration_ms
    j["last_delta_ms"] = delta
    if abs(delta) <= MAX_OUTPUT_DELTA_MS:
        j["job_status"] = "COMPLETED"
    else:
        j["job_status"] = "FAILED_VALIDATION"
        j["attempt_count"] += 1
    touch(j)
    return ok_object(serialize.conversion_job(j))


@bp.post("/caption-ad/conversion-jobs/<conversionJobId>/retry")
@guarded({"OperationsManager"})
def retry_conversion_job(conversionJobId, _user_id, _role):
    j = get_job(conversionJobId)
    if j["job_status"] != "FAILED_VALIDATION":
        raise invalid_transition("Only a FAILED_VALIDATION job can be retried")
    if j["attempt_count"] >= 3:
        raise ApiError(ERR_RETRY_LIMIT_REACHED, 409, "Conversion retry limit reached")
    j["job_status"] = "QUEUED"
    touch(j)
    return ok_object(serialize.conversion_job(j))


@bp.post("/caption-ad/conversion-jobs/<conversionJobId>/cancel")
@guarded({"OperationsManager"})
def cancel_conversion_job(conversionJobId, _user_id, _role):
    j = get_job(conversionJobId)
    if j["job_status"] != "QUEUED":
        raise invalid_transition("Only a QUEUED job can be cancelled")
    j["job_status"] = "CANCELLED"
    touch(j)
    return ok_object(serialize.conversion_job(j))
