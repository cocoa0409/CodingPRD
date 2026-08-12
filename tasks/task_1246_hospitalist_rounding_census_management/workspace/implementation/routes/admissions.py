"""Admission + Assignment endpoints."""

from flask import Blueprint, request

from db import store
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_UNAUTHORIZED_ROLE,
    ERR_ADMISSION_INVALID_STATE, ERR_ADMISSION_NOT_OFFERED_TO_HOSPITALIST,
    ERR_DUPLICATE_ACTIVE_ASSIGNMENT, ERR_HOSPITALIST_NOT_ACTIVE,
    ERR_NO_ACTIVE_SHIFT, ERR_CENSUS_CAP_REACHED,
    ERR_ASSIGNMENT_INVALID_STATE, ERR_STALE_VERSION, ERR_TRANSFER_TARGET_MISMATCH,
)
from middleware import require_roles
from response import success_object, success_list
from services.core import (
    make_entity, touch, run_selector, active_covering_shift,
    refresh_hospitalist_census, continuity_flag,
)
from services import serializers
import clock

bp = Blueprint("admissions", __name__)

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
# Admissions
# ---------------------------------------------------------------------------

@bp.route("/admissions", methods=["POST"])
def create_admission():
    require_roles(["GroupAdmin"])
    body = _body()
    patient_id = body.get("patient_id")
    if not patient_id or not isinstance(patient_id, str):
        raise ApiError(ERR_INVALID_REQUEST, "patient_id is required", 400)
    patient = store["patients"].get(patient_id)
    if patient is None:
        raise ApiError(ERR_NOT_FOUND, "Patient not found", 404)

    now = clock.now()

    # readmission side effect
    if patient["admission_status"] == "DISCHARGED":
        patient["admission_status"] = "ADMITTED"
        patient["observation_status"] = "NONE"
        patient["admitted_at"] = now
        patient["los_midnights"] = 0
        patient["los_blocks"] = 0
        patient["los_alert_flag"] = False
        touch(patient)

    admission = make_entity({
        "patient_id": patient_id,
        "status": "QUEUED",
        "offered_to_hospitalist_id": None,
        "declined_hospitalist_ids": [],
        "distribution_score": None,
        "assignment_id": None,
        "offered_at": None,
        "decided_at": None,
    })
    store["admissions"][admission["id"]] = admission

    # run selector immediately
    run_selector(admission)
    return success_object(serializers.admission(admission), 201)


@bp.route("/admissions", methods=["GET"])
def list_admissions():
    require_roles(ALL_ROLES)
    items = list(store["admissions"].values())
    pid = request.args.get("patient_id")
    if pid is not None:
        items = [a for a in items if a["patient_id"] == pid]
    ohid = request.args.get("offered_to_hospitalist_id")
    if ohid is not None:
        items = [a for a in items if a["offered_to_hospitalist_id"] == ohid]
    aid = request.args.get("assignment_id")
    if aid is not None:
        items = [a for a in items if a["assignment_id"] == aid]
    st = request.args.get("status")
    if st is not None:
        items = [a for a in items if a["status"] == st]
    return _paginate(items, serializers.admission)


@bp.route("/admissions/<aid>", methods=["GET"])
def get_admission(aid):
    require_roles(ALL_ROLES)
    a = store["admissions"].get(aid)
    if a is None:
        raise ApiError(ERR_NOT_FOUND, "Admission not found", 404)
    return success_object(serializers.admission(a))


@bp.route("/admissions/<aid>/accept", methods=["POST"])
def accept_admission(aid):
    role, uid = require_roles(["Hospitalist"])
    a = store["admissions"].get(aid)
    if a is None:
        raise ApiError(ERR_NOT_FOUND, "Admission not found", 404)

    # state
    if a["status"] != "OFFERED":
        raise ApiError(ERR_ADMISSION_INVALID_STATE, "accept requires status OFFERED", 409)

    h = store["hospitalists"].get(a["offered_to_hospitalist_id"])

    # temporal: offered hospitalist must hold an ACTIVE shift covering now
    now = clock.now()
    if h is None or active_covering_shift(h["id"], now) is None:
        raise ApiError(ERR_NO_ACTIVE_SHIFT, "offered hospitalist has no ACTIVE shift covering now", 422)

    # cross-entity: caller must be the offered hospitalist
    if uid != a["offered_to_hospitalist_id"]:
        raise ApiError(ERR_ADMISSION_NOT_OFFERED_TO_HOSPITALIST, "caller is not the offered hospitalist", 409)

    # cross-entity: patient must not already hold an ACTIVE assignment
    for asg in store["assignments"].values():
        if asg["patient_id"] == a["patient_id"] and asg["status"] == "ACTIVE":
            raise ApiError(ERR_DUPLICATE_ACTIVE_ASSIGNMENT, "patient already has an ACTIVE assignment", 409)

    # cross-entity: employment ACTIVE
    if h["employment_status"] != "ACTIVE":
        raise ApiError(ERR_HOSPITALIST_NOT_ACTIVE, "hospitalist employment_status is not ACTIVE", 422)

    # capacity
    if h["current_census"] >= h["max_census_cap"]:
        raise ApiError(ERR_CENSUS_CAP_REACHED, "hospitalist census is at max_census_cap", 422)

    # create assignment
    cont = continuity_flag(a["patient_id"], h["id"], now)
    asg = make_entity({
        "patient_id": a["patient_id"],
        "hospitalist_id": h["id"],
        "status": "ACTIVE",
        "continuity_flag": cont,
        "assigned_at": now,
        "closed_at": None,
        "close_reason": None,
        "transfer_target_hospitalist_id": None,
    })
    store["assignments"][asg["id"]] = asg

    a["status"] = "ACCEPTED"
    a["assignment_id"] = asg["id"]
    a["decided_at"] = now
    touch(a)

    refresh_hospitalist_census(h)
    touch(h)

    return success_object(serializers.admission(a))


@bp.route("/admissions/<aid>/decline", methods=["POST"])
def decline_admission(aid):
    role, uid = require_roles(["Hospitalist"])
    a = store["admissions"].get(aid)
    if a is None:
        raise ApiError(ERR_NOT_FOUND, "Admission not found", 404)
    if a["status"] != "OFFERED":
        raise ApiError(ERR_ADMISSION_INVALID_STATE, "decline requires status OFFERED", 409)
    if uid != a["offered_to_hospitalist_id"]:
        raise ApiError(ERR_ADMISSION_NOT_OFFERED_TO_HOSPITALIST, "caller is not the offered hospitalist", 409)

    decliner = store["hospitalists"].get(uid)
    a["declined_hospitalist_ids"].append(uid)
    a["offered_to_hospitalist_id"] = None
    a["distribution_score"] = None
    a["status"] = "QUEUED"
    touch(a)

    if decliner is not None:
        refresh_hospitalist_census(decliner)
        touch(decliner)

    # immediately re-run selector excluding decliners
    run_selector(a)
    return success_object(serializers.admission(a))


# ---------------------------------------------------------------------------
# Assignments
# ---------------------------------------------------------------------------

@bp.route("/assignments", methods=["GET"])
def list_assignments():
    require_roles(ALL_ROLES)
    items = list(store["assignments"].values())
    pid = request.args.get("patient_id")
    if pid is not None:
        items = [a for a in items if a["patient_id"] == pid]
    hid = request.args.get("hospitalist_id")
    if hid is not None:
        items = [a for a in items if a["hospitalist_id"] == hid]
    tth = request.args.get("transfer_target_hospitalist_id")
    if tth is not None:
        items = [a for a in items if a.get("transfer_target_hospitalist_id") == tth]
    st = request.args.get("status")
    if st is not None:
        items = [a for a in items if a["status"] == st]
    return _paginate(items, serializers.assignment)


@bp.route("/assignments/<aid>", methods=["GET"])
def get_assignment(aid):
    require_roles(ALL_ROLES)
    a = store["assignments"].get(aid)
    if a is None:
        raise ApiError(ERR_NOT_FOUND, "Assignment not found", 404)
    return success_object(serializers.assignment(a))


@bp.route("/assignments/<aid>/transfer", methods=["POST"])
def transfer_assignment(aid):
    role, uid = require_roles(["Hospitalist", "GroupAdmin"])
    body = _body()

    # request shape
    target_id = body.get("target_hospitalist_id")
    if not target_id or not isinstance(target_id, str):
        raise ApiError(ERR_INVALID_REQUEST, "target_hospitalist_id is required", 400)
    if "expected_assignment_version" not in body:
        raise ApiError(ERR_INVALID_REQUEST, "expected_assignment_version is required", 400)
    expected = body.get("expected_assignment_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(ERR_INVALID_REQUEST, "expected_assignment_version must be an integer", 400)

    a = store["assignments"].get(aid)
    if a is None:
        raise ApiError(ERR_NOT_FOUND, "Assignment not found", 404)

    # ownership for Hospitalist: must be the current holder
    if role == "Hospitalist" and a["hospitalist_id"] != uid:
        raise ApiError(ERR_UNAUTHORIZED_ROLE, "Hospitalist may only transfer own assignments", 403)

    # target equals current holder -> request shape error
    if target_id == a["hospitalist_id"]:
        raise ApiError(ERR_INVALID_REQUEST, "transfer target equals current hospitalist", 400)

    # existence of target
    target = store["hospitalists"].get(target_id)
    if target is None:
        raise ApiError(ERR_NOT_FOUND, "Target hospitalist not found", 404)

    # state
    if a["status"] != "ACTIVE":
        raise ApiError(ERR_ASSIGNMENT_INVALID_STATE, "transfer requires status ACTIVE", 409)

    # OCC
    if expected != a["version"]:
        raise ApiError(ERR_STALE_VERSION, "expected_assignment_version does not match current version", 412)

    a["status"] = "PENDING_TRANSFER"
    a["transfer_target_hospitalist_id"] = target_id
    touch(a)
    return success_object(serializers.assignment(a))


@bp.route("/assignments/<aid>/accept-transfer", methods=["POST"])
def accept_transfer(aid):
    role, uid = require_roles(["Hospitalist"])
    a = store["assignments"].get(aid)
    if a is None:
        raise ApiError(ERR_NOT_FOUND, "Assignment not found", 404)
    if a["status"] != "PENDING_TRANSFER":
        raise ApiError(ERR_ASSIGNMENT_INVALID_STATE, "accept-transfer requires status PENDING_TRANSFER", 409)

    target = store["hospitalists"].get(a["transfer_target_hospitalist_id"])

    # temporal: target must hold a covering ACTIVE shift
    now = clock.now()
    if target is None or active_covering_shift(target["id"], now) is None:
        raise ApiError(ERR_NO_ACTIVE_SHIFT, "target has no ACTIVE shift covering now", 422)

    # cross-entity: caller must be the target
    if uid != a["transfer_target_hospitalist_id"]:
        raise ApiError(ERR_TRANSFER_TARGET_MISMATCH, "caller is not the transfer target", 409)

    # cross-entity: target employment ACTIVE
    if target["employment_status"] != "ACTIVE":
        raise ApiError(ERR_HOSPITALIST_NOT_ACTIVE, "target employment_status is not ACTIVE", 422)

    # capacity
    if target["current_census"] >= target["max_census_cap"]:
        raise ApiError(ERR_CENSUS_CAP_REACHED, "target census is at max_census_cap", 422)

    source = store["hospitalists"].get(a["hospitalist_id"])

    # close source assignment
    a["status"] = "CLOSED"
    a["close_reason"] = "TRANSFER"
    a["closed_at"] = now
    target_id = a["transfer_target_hospitalist_id"]
    a["transfer_target_hospitalist_id"] = None
    touch(a)

    # create successor assignment
    cont = continuity_flag(a["patient_id"], target_id, now)
    new_asg = make_entity({
        "patient_id": a["patient_id"],
        "hospitalist_id": target_id,
        "status": "ACTIVE",
        "continuity_flag": cont,
        "assigned_at": now,
        "closed_at": None,
        "close_reason": None,
        "transfer_target_hospitalist_id": None,
    })
    store["assignments"][new_asg["id"]] = new_asg

    if source is not None:
        refresh_hospitalist_census(source)
        touch(source)
    refresh_hospitalist_census(target)
    touch(target)

    return success_object(serializers.assignment(a))


@bp.route("/assignments/<aid>/cancel-transfer", methods=["POST"])
def cancel_transfer(aid):
    role, uid = require_roles(["Hospitalist", "GroupAdmin"])
    a = store["assignments"].get(aid)
    if a is None:
        raise ApiError(ERR_NOT_FOUND, "Assignment not found", 404)
    if role == "Hospitalist" and a["hospitalist_id"] != uid:
        raise ApiError(ERR_UNAUTHORIZED_ROLE, "Hospitalist may only cancel own assignments", 403)
    if a["status"] != "PENDING_TRANSFER":
        raise ApiError(ERR_ASSIGNMENT_INVALID_STATE, "cancel-transfer requires status PENDING_TRANSFER", 409)
    a["status"] = "ACTIVE"
    a["transfer_target_hospitalist_id"] = None
    touch(a)
    return success_object(serializers.assignment(a))
