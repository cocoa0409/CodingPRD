"""Hospitalist, Patient, Shift endpoints."""

from flask import Blueprint, request

from db import store
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_UNAUTHORIZED_ROLE,
    ERR_SHIFT_INVALID_STATE, ERR_SHIFT_HANDOFF_MISSING, ERR_SHIFT_INVALID_WINDOW,
    ERR_SHIFT_OVERLAP,
)
from middleware import require_roles
from response import success_object, success_list
from services.core import make_entity, touch, intervals_overlap
from services import serializers
import clock

bp = Blueprint("roster", __name__)

SPECIALTIES = {"INTERNAL_MEDICINE", "FAMILY_MEDICINE", "ICU"}
EMPLOYMENT = {"ACTIVE", "ON_LEAVE", "INACTIVE"}
ACUITY = {"HIGH", "MEDIUM", "LOW"}
ADMIT_SOURCE = {"ED", "DIRECT", "TRANSFER"}
STAY_TYPE = {"INPATIENT", "OBSERVATION"}
SHIFT_TYPE = {"DAY", "NIGHT"}

ALL_ROLES = ["GroupAdmin", "Hospitalist", "ConsultingSpecialist"]


def _paginate(items, serializer):
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, "Invalid pagination parameters", 400)
    if limit < 1 or limit > 100 or offset < 0:
        raise ApiError(ERR_INVALID_REQUEST, "Invalid pagination parameters", 400)
    items = sorted(items, key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serializer(i) for i in page], limit, offset, total)


def _body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be an object", 400)
    return data


# ---------------------------------------------------------------------------
# Hospitalists
# ---------------------------------------------------------------------------

@bp.route("/hospitalists", methods=["POST"])
def create_hospitalist():
    require_roles(["GroupAdmin"])
    body = _body()
    full_name = body.get("full_name")
    specialty = body.get("specialty")
    if not full_name or not isinstance(full_name, str):
        raise ApiError(ERR_INVALID_REQUEST, "full_name is required", 400)
    if specialty not in SPECIALTIES:
        raise ApiError(ERR_INVALID_REQUEST, "specialty must be one of INTERNAL_MEDICINE, FAMILY_MEDICINE, ICU", 400)
    employment_status = body.get("employment_status", "ACTIVE")
    if employment_status not in EMPLOYMENT:
        raise ApiError(ERR_INVALID_REQUEST, "invalid employment_status", 400)
    max_census_cap = body.get("max_census_cap", 16)
    if not isinstance(max_census_cap, int) or isinstance(max_census_cap, bool) or max_census_cap < 1:
        raise ApiError(ERR_INVALID_REQUEST, "max_census_cap must be an integer >= 1", 400)
    night_eligible = body.get("night_eligible", True)
    if not isinstance(night_eligible, bool):
        raise ApiError(ERR_INVALID_REQUEST, "night_eligible must be a boolean", 400)

    h = make_entity({
        "full_name": full_name,
        "specialty": specialty,
        "employment_status": employment_status,
        "max_census_cap": max_census_cap,
        "night_eligible": night_eligible,
        "current_census": 0,
        "pending_offers": 0,
        "distribution_eligible": employment_status == "ACTIVE",
    })
    store["hospitalists"][h["id"]] = h
    return success_object(serializers.hospitalist(h), 201)


@bp.route("/hospitalists", methods=["GET"])
def list_hospitalists():
    require_roles(ALL_ROLES)
    items = list(store["hospitalists"].values())
    emp = request.args.get("employment_status")
    if emp is not None:
        items = [h for h in items if h["employment_status"] == emp]
    return _paginate(items, serializers.hospitalist)


@bp.route("/hospitalists/<hid>", methods=["GET"])
def get_hospitalist(hid):
    require_roles(ALL_ROLES)
    h = store["hospitalists"].get(hid)
    if h is None:
        raise ApiError(ERR_NOT_FOUND, "Hospitalist not found", 404)
    return success_object(serializers.hospitalist(h))


# ---------------------------------------------------------------------------
# Patients
# ---------------------------------------------------------------------------

@bp.route("/patients", methods=["POST"])
def create_patient():
    require_roles(["GroupAdmin"])
    body = _body()
    mrn = body.get("mrn")
    acuity = body.get("acuity")
    admit_source = body.get("admit_source")
    stay_type = body.get("stay_type")
    if not mrn or not isinstance(mrn, str):
        raise ApiError(ERR_INVALID_REQUEST, "mrn is required", 400)
    if acuity not in ACUITY:
        raise ApiError(ERR_INVALID_REQUEST, "invalid acuity", 400)
    if admit_source not in ADMIT_SOURCE:
        raise ApiError(ERR_INVALID_REQUEST, "invalid admit_source", 400)
    if stay_type not in STAY_TYPE:
        raise ApiError(ERR_INVALID_REQUEST, "invalid stay_type", 400)
    admitted_at = None
    if "admitted_at" in body and body["admitted_at"] is not None:
        admitted_at = clock.parse_iso(body["admitted_at"])
        if admitted_at is None:
            raise ApiError(ERR_INVALID_REQUEST, "admitted_at must be ISO8601 datetime", 400)
    if admitted_at is None:
        admitted_at = clock.now()

    # uniqueness of mrn
    for p in store["patients"].values():
        if p["mrn"] == mrn:
            raise ApiError(ERR_INVALID_REQUEST, "mrn must be unique across all patients", 400)

    obs_status = "OBS_ACTIVE" if stay_type == "OBSERVATION" else "NONE"
    obs_started = admitted_at if stay_type == "OBSERVATION" else None
    p = make_entity({
        "mrn": mrn,
        "acuity": acuity,
        "admit_source": admit_source,
        "stay_type": stay_type,
        "admitted_at": admitted_at,
        "admission_status": "ADMITTED",
        "observation_status": obs_status,
        "observation_started_at": obs_started,
        "los_midnights": 0,
        "los_blocks": 0,
        "los_alert_flag": False,
    })
    store["patients"][p["id"]] = p
    return success_object(serializers.patient(p), 201)


@bp.route("/patients", methods=["GET"])
def list_patients():
    require_roles(ALL_ROLES)
    items = list(store["patients"].values())
    adm = request.args.get("admission_status")
    if adm is not None:
        items = [p for p in items if p["admission_status"] == adm]
    st = request.args.get("stay_type")
    if st is not None:
        items = [p for p in items if p["stay_type"] == st]
    los_alert = request.args.get("los_alert")
    if los_alert is not None:
        val = los_alert.lower() == "true"
        items = [p for p in items if p["los_alert_flag"] == val]
    return _paginate(items, serializers.patient)


@bp.route("/patients/<pid>", methods=["GET"])
def get_patient(pid):
    require_roles(ALL_ROLES)
    p = store["patients"].get(pid)
    if p is None:
        raise ApiError(ERR_NOT_FOUND, "Patient not found", 404)
    return success_object(serializers.patient(p))


# ---------------------------------------------------------------------------
# Shifts
# ---------------------------------------------------------------------------

@bp.route("/shifts", methods=["POST"])
def create_shift():
    require_roles(["GroupAdmin"])
    body = _body()
    hospitalist_id = body.get("hospitalist_id")
    shift_type = body.get("shift_type")
    start_at_s = body.get("start_at")
    end_at_s = body.get("end_at")
    if not hospitalist_id or not isinstance(hospitalist_id, str):
        raise ApiError(ERR_INVALID_REQUEST, "hospitalist_id is required", 400)
    if shift_type not in SHIFT_TYPE:
        raise ApiError(ERR_INVALID_REQUEST, "invalid shift_type", 400)
    start_at = clock.parse_iso(start_at_s)
    end_at = clock.parse_iso(end_at_s)
    if start_at is None or end_at is None:
        raise ApiError(ERR_INVALID_REQUEST, "start_at and end_at must be ISO8601 datetimes", 400)

    h = store["hospitalists"].get(hospitalist_id)
    if h is None:
        raise ApiError(ERR_NOT_FOUND, "Hospitalist not found", 404)

    if end_at <= start_at:
        raise ApiError(ERR_SHIFT_INVALID_WINDOW, "shift end_at must be strictly after start_at", 422)

    for s in store["shifts"].values():
        if s["hospitalist_id"] == hospitalist_id and s["state"] != "CLOSED":
            if intervals_overlap(start_at, end_at, s["start_at"], s["end_at"]):
                raise ApiError(ERR_SHIFT_OVERLAP, "new shift overlaps an existing shift of this hospitalist", 409)

    s = make_entity({
        "hospitalist_id": hospitalist_id,
        "shift_type": shift_type,
        "start_at": start_at,
        "end_at": end_at,
        "state": "SCHEDULED",
    })
    store["shifts"][s["id"]] = s
    return success_object(serializers.shift(s), 201)


@bp.route("/shifts", methods=["GET"])
def list_shifts():
    require_roles(ALL_ROLES)
    items = list(store["shifts"].values())
    hid = request.args.get("hospitalist_id")
    if hid is not None:
        items = [s for s in items if s["hospitalist_id"] == hid]
    st = request.args.get("state")
    if st is not None:
        items = [s for s in items if s["state"] == st]
    return _paginate(items, serializers.shift)


@bp.route("/shifts/<sid>", methods=["GET"])
def get_shift(sid):
    require_roles(ALL_ROLES)
    s = store["shifts"].get(sid)
    if s is None:
        raise ApiError(ERR_NOT_FOUND, "Shift not found", 404)
    return success_object(serializers.shift(s))


@bp.route("/shifts/<sid>/activate", methods=["POST"])
def activate_shift(sid):
    role, uid = require_roles(["GroupAdmin", "Hospitalist"])
    s = store["shifts"].get(sid)
    if s is None:
        raise ApiError(ERR_NOT_FOUND, "Shift not found", 404)
    if role == "Hospitalist" and s["hospitalist_id"] != uid:
        raise ApiError(ERR_UNAUTHORIZED_ROLE, "Hospitalist may only activate own shifts", 403)
    if s["state"] != "SCHEDULED":
        raise ApiError(ERR_SHIFT_INVALID_STATE, "activate requires state SCHEDULED", 409)
    s["state"] = "ACTIVE"
    touch(s)
    return success_object(serializers.shift(s))


@bp.route("/shifts/<sid>/close", methods=["POST"])
def close_shift(sid):
    role, uid = require_roles(["GroupAdmin", "Hospitalist"])
    s = store["shifts"].get(sid)
    if s is None:
        raise ApiError(ERR_NOT_FOUND, "Shift not found", 404)
    if role == "Hospitalist" and s["hospitalist_id"] != uid:
        raise ApiError(ERR_UNAUTHORIZED_ROLE, "Hospitalist may only close own shifts", 403)
    if s["state"] != "ACTIVE":
        raise ApiError(ERR_SHIFT_INVALID_STATE, "close requires state ACTIVE", 409)
    has_accepted = any(
        h["shift_id"] == sid and h["status"] == "ACCEPTED"
        for h in store["handoffs"].values()
    )
    if not has_accepted:
        raise ApiError(ERR_SHIFT_HANDOFF_MISSING, "shift close requires an ACCEPTED handoff", 409)
    s["state"] = "CLOSED"
    touch(s)
    return success_object(serializers.shift(s))
