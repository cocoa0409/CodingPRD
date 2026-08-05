"""Enrollments: pledging and cycling capacity (PRD §3.3)."""
from flask import Blueprint, request

from errors import err
from common import (require, ALL_ROLES, get_body, ok_object, list_response,
                    require_str, require_number)
from models import (get, get_or_404, insert, touch, recompute_committed_kw)
from store import db

bp_enrollments = Blueprint("enrollments", __name__)


def _device_of(enrollment):
    return get("devices", enrollment["device_id"])


@bp_enrollments.route("/dr/enrollments", methods=["POST"])
def create_enrollment():
    require(["Aggregator"])
    body = get_body()
    # step 4: FK existence (device then program, per PRD §3.3)
    if body.get("device_id") is not None:
        get_or_404("devices", body["device_id"])
    if body.get("program_id") is not None:
        get_or_404("programs", body["program_id"])
    # step 6: required + typed
    device_id = require_str(body, "device_id")
    program_id = require_str(body, "program_id")
    committed_kw = require_number(body, "committed_kw", gt=0)
    rec = insert("enrollments", {
        "device_id": device_id,
        "program_id": program_id,
        "committed_kw": committed_kw,
        "status": "PENDING",
        "season_delivered_kwh": 0,
    })
    return ok_object(rec, status=201)


@bp_enrollments.route("/dr/enrollments/<eid>", methods=["GET"])
def get_enrollment(eid):
    require(ALL_ROLES)
    return ok_object(get_or_404("enrollments", eid))


@bp_enrollments.route("/dr/enrollments", methods=["GET"])
def list_enrollments():
    require(ALL_ROLES)
    device_id = request.args.get("device_id")
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    records = []
    for e in db.data["enrollments"].values():
        if device_id is not None and e["device_id"] != device_id:
            continue
        if program_id is not None and e["program_id"] != program_id:
            continue
        if status is not None and e["status"] != status:
            continue
        records.append(e)
    return list_response(records)


def _sync_ledgers(enrollment):
    device = _device_of(enrollment)
    agg_id = device["aggregator_id"] if device else None
    recompute_committed_kw(enrollment["program_id"], [agg_id] if agg_id else [])


@bp_enrollments.route("/dr/enrollments/<eid>/activate", methods=["POST"])
def activate_enrollment(eid):
    uid, _ = require(["Aggregator"])
    enr = get_or_404("enrollments", eid)
    device = _device_of(enr)
    # step 5: ownership
    if device is None or device["aggregator_id"] != uid:
        raise err("ERR_FORBIDDEN_OWNERSHIP", "Aggregator does not own the enrolled device.")
    # step 8: generic state (enrollment PENDING) — evaluated first per §3.3
    if enr["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Enrollment is not PENDING.")
    program = get("programs", enr["program_id"])
    if program is None or program["status"] != "ACTIVE":
        raise err("ERR_PROGRAM_NOT_ACTIVE", "Program is not ACTIVE.")
    if device["status"] != "ACTIVE":
        raise err("ERR_DEVICE_NOT_ELIGIBLE", "Device is not ACTIVE.")
    for other in db.data["enrollments"].values():
        if (other["id"] != eid and other["device_id"] == enr["device_id"]
                and other["program_id"] == enr["program_id"]
                and other["status"] == "ACTIVE"):
            raise err("ERR_DUPLICATE_ENROLLMENT",
                      "Another ACTIVE enrollment exists for this device/program.")
    enr["status"] = "ACTIVE"
    touch(enr)
    _sync_ledgers(enr)
    return ok_object(enr)


@bp_enrollments.route("/dr/enrollments/<eid>/opt-out", methods=["POST"])
def opt_out_enrollment(eid):
    uid, role = require(["Customer", "Aggregator"])
    enr = get_or_404("enrollments", eid)
    device = _device_of(enr)
    if device is None:
        raise err("ERR_FORBIDDEN_OWNERSHIP", "Enrolled device not found.")
    if role == "Customer":
        if device["customer_id"] != uid:
            raise err("ERR_FORBIDDEN_OWNERSHIP", "Customer does not own the device.")
    else:  # Aggregator
        if device["aggregator_id"] != uid:
            raise err("ERR_FORBIDDEN_OWNERSHIP", "Aggregator does not own the device.")
    if enr["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Enrollment is not ACTIVE.")
    enr["status"] = "OPTED_OUT"
    touch(enr)
    _sync_ledgers(enr)
    return ok_object(enr)


@bp_enrollments.route("/dr/enrollments/<eid>/re-enroll", methods=["POST"])
def re_enroll(eid):
    uid, _ = require(["Aggregator"])
    enr = get_or_404("enrollments", eid)
    device = _device_of(enr)
    if device is None or device["aggregator_id"] != uid:
        raise err("ERR_FORBIDDEN_OWNERSHIP", "Aggregator does not own the enrolled device.")
    if enr["status"] != "OPTED_OUT":
        raise err("ERR_INVALID_STATE", "Enrollment is not OPTED_OUT.")
    program = get("programs", enr["program_id"])
    if program is None or program["status"] != "ACTIVE":
        raise err("ERR_PROGRAM_NOT_ACTIVE", "Program is not ACTIVE.")
    if device["status"] != "ACTIVE":
        raise err("ERR_DEVICE_NOT_ELIGIBLE", "Device is not ACTIVE.")
    enr["status"] = "ACTIVE"
    touch(enr)
    _sync_ledgers(enr)
    return ok_object(enr)


@bp_enrollments.route("/dr/enrollments/<eid>/terminate", methods=["POST"])
def terminate_enrollment(eid):
    uid, _ = require(["Aggregator"])
    enr = get_or_404("enrollments", eid)
    device = _device_of(enr)
    if device is None or device["aggregator_id"] != uid:
        raise err("ERR_FORBIDDEN_OWNERSHIP", "Aggregator does not own the enrolled device.")
    if enr["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Enrollment is not ACTIVE.")
    enr["status"] = "TERMINATED"
    touch(enr)
    _sync_ledgers(enr)
    return ok_object(enr)
