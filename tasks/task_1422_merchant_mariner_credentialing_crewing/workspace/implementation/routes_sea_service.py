"""Sea-service records: entry, submission, verification, disputes (PRD 3.4)."""

from flask import Blueprint, g, request

from db import store
from errors import err
from helpers import (
    get_body,
    paginate,
    req_dt,
    req_enum,
    req_int,
    req_str,
    require_roles,
    scope_mariner_id,
    scope_mariner_resource,
    sorted_items,
)
from response import success
from serialize import ser_sea_service_record
from services import calendar_days, compute_verified_days

bp = Blueprint("sea_service", __name__)

RANK_TRACKS = ("DECK", "ENGINE", "STEWARD")
SERVICE_REGIONS = ("OCEAN", "NEAR_COASTAL", "INLAND", "GREAT_LAKES")
WATCH_SCHEDULES = ("EIGHT_HOUR", "TWELVE_HOUR")

ALL_ROLES = (
    "FleetAdmin",
    "CrewingManager",
    "CredentialingOfficer",
    "PortCaptain",
    "UnionDispatcher",
    "Mariner",
)


def _get_mariner(mariner_id):
    m = store.mariners.get(mariner_id)
    if m is None:
        raise err("ERR_MARINER_NOT_FOUND", "Mariner %s not found" % mariner_id)
    return m


def _get_record_under_mariner(mariner_id, record_id):
    r = store.sea_service_records.get(record_id)
    if r is None or r["mariner_id"] != mariner_id:
        raise err(
            "ERR_SEA_SERVICE_RECORD_NOT_FOUND",
            "Sea-service record %s not found" % record_id,
        )
    return r


@bp.route("/mariners/<mariner_id>/sea-service-records", methods=["POST"])
@require_roles("Mariner", "CredentialingOfficer")
def create_record(mariner_id):
    scope_mariner_id(mariner_id)
    m = _get_mariner(mariner_id)
    body = get_body()
    # Body FK existence (pipeline step 5).
    vessel_id = body.get("vessel_id")
    if not isinstance(vessel_id, str) or vessel_id == "":
        raise err("ERR_INVALID_REQUEST", "Field 'vessel_id' is required")
    if vessel_id not in store.vessels:
        raise err("ERR_VESSEL_NOT_FOUND", "Vessel %s not found" % vessel_id)
    position_code = req_str(body, "position_code")
    rank_track = req_enum(body, "rank_track", RANK_TRACKS)
    rank_grade = req_int(body, "rank_grade", min_v=1, max_v=9)
    region = req_enum(body, "service_region", SERVICE_REGIONS)
    watch = req_enum(body, "watch_schedule", WATCH_SCHEDULES)
    start = req_dt(body, "start_date")
    end = req_dt(body, "end_date")
    if end < start:
        raise err("ERR_INVALID_REQUEST", "end_date must be on or after start_date")
    if end > store.clock:
        raise err(
            "ERR_INVALID_REQUEST", "end_date must not be later than the current time"
        )
    r = {
        "mariner_id": m["id"],
        "vessel_id": vessel_id,
        "position_code": position_code,
        "rank_track": rank_track,
        "rank_grade": rank_grade,
        "service_region": region,
        "watch_schedule": watch,
        "start_date": start,
        "end_date": end,
        "provisional_days": float(calendar_days(start, end)),
        "verified_days": None,
        "record_status": "DRAFT",
        "entered_by_user_id": g.user_id,
        "verified_by_user_id": None,
        "dispute_reason": None,
    }
    store.stamp(r)
    store.sea_service_records[r["id"]] = r
    return success(ser_sea_service_record(r), code=201)


@bp.route("/mariners/<mariner_id>/sea-service-records", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_mariner_records(mariner_id):
    scope_mariner_id(mariner_id)
    m = _get_mariner(mariner_id)
    items = [
        r for r in store.sea_service_records.values() if r["mariner_id"] == m["id"]
    ]
    status = request.args.get("record_status")
    if status is not None:
        items = [r for r in items if r["record_status"] == status]
    page, meta = paginate(sorted_items(items))
    return success(
        [ser_sea_service_record(r) for r in page],
        response_type="array",
        pagination=meta,
    )


@bp.route("/mariners/<mariner_id>/sea-service-records/<record_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_record(mariner_id, record_id):
    scope_mariner_id(mariner_id)
    _get_mariner(mariner_id)
    r = _get_record_under_mariner(mariner_id, record_id)
    return success(ser_sea_service_record(r))


@bp.route("/vessels/<vessel_id>/sea-service-records", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_vessel_records(vessel_id):
    if vessel_id not in store.vessels:
        raise err("ERR_VESSEL_NOT_FOUND", "Vessel %s not found" % vessel_id)
    items = [
        r for r in store.sea_service_records.values() if r["vessel_id"] == vessel_id
    ]
    page, meta = paginate(sorted_items(items))
    return success(
        [ser_sea_service_record(r) for r in page],
        response_type="array",
        pagination=meta,
    )


@bp.route(
    "/mariners/<mariner_id>/sea-service-records/<record_id>/submit", methods=["POST"]
)
@require_roles("Mariner", "CredentialingOfficer")
def submit_record(mariner_id, record_id):
    scope_mariner_id(mariner_id)
    _get_mariner(mariner_id)
    r = _get_record_under_mariner(mariner_id, record_id)
    if r["record_status"] not in ("DRAFT", "DISPUTED"):
        raise err(
            "ERR_RECORD_NOT_SUBMITTABLE",
            "Only DRAFT or DISPUTED records can be submitted",
        )
    if r["end_date"] < r["start_date"] or r["end_date"] > store.clock:
        raise err(
            "ERR_INVALID_REQUEST",
            "end_date must be on or after start_date and not in the future",
        )
    r["record_status"] = "SUBMITTED"
    store.bump(r)
    return success(ser_sea_service_record(r))


@bp.route(
    "/mariners/<mariner_id>/sea-service-records/<record_id>/verify", methods=["POST"]
)
@require_roles("CredentialingOfficer")
def verify_record(mariner_id, record_id):
    _get_mariner(mariner_id)
    r = _get_record_under_mariner(mariner_id, record_id)
    # Segregation of duties (pipeline step 8) precedes the state check (step 9).
    if g.user_id == r["entered_by_user_id"]:
        raise err(
            "ERR_SOD_VERIFY_SAME_RECORDER",
            "The verifying officer must differ from the recorder",
        )
    if r["record_status"] != "SUBMITTED":
        raise err(
            "ERR_RECORD_NOT_VERIFIABLE", "Only SUBMITTED records can be verified"
        )
    r["record_status"] = "VERIFIED"
    r["verified_days"] = compute_verified_days(r)
    r["verified_by_user_id"] = g.user_id
    store.bump(r)
    return success(ser_sea_service_record(r))


@bp.route(
    "/mariners/<mariner_id>/sea-service-records/<record_id>/dispute", methods=["POST"]
)
@require_roles("CredentialingOfficer")
def dispute_record(mariner_id, record_id):
    _get_mariner(mariner_id)
    r = _get_record_under_mariner(mariner_id, record_id)
    body = get_body()
    reason = req_str(body, "reason")
    if r["record_status"] != "SUBMITTED":
        raise err("ERR_RECORD_NOT_VERIFIABLE", "Only SUBMITTED records can be disputed")
    r["record_status"] = "DISPUTED"
    r["dispute_reason"] = reason
    store.bump(r)
    return success(ser_sea_service_record(r))


@bp.route(
    "/mariners/<mariner_id>/sea-service-records/<record_id>/reject", methods=["POST"]
)
@require_roles("CredentialingOfficer")
def reject_record(mariner_id, record_id):
    _get_mariner(mariner_id)
    r = _get_record_under_mariner(mariner_id, record_id)
    body = get_body()
    req_str(body, "reason")
    if r["record_status"] not in ("SUBMITTED", "DISPUTED"):
        raise err(
            "ERR_RECORD_NOT_VERIFIABLE",
            "Only SUBMITTED or DISPUTED records can be rejected",
        )
    r["record_status"] = "REJECTED"
    store.bump(r)
    return success(ser_sea_service_record(r))
