"""ParkingAssignment endpoints (PRD §3.4, §3.5, §2.7 OCC)."""
from datetime import timedelta

from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import authenticate, require_role
from response import success, list_response
from helpers import (get_json, require_string, require_int, parse_datetime,
                     _parse_iso, pagination_params, paginate)
from services.derived import weight_class_accepted, visit_delivered_jeta_gallons
from services.calculations import parking_ramp_fee

bp = Blueprint("parking_assignments", __name__)

TOW_BUFFER = timedelta(minutes=30)


def assignment_view(a):
    return {
        "id": a["id"],
        "service_visit_id": a["service_visit_id"],
        "spot_id": a["spot_id"],
        "occupy_start_utc": a["occupy_start_utc"],
        "occupy_end_utc": a["occupy_end_utc"],
        "status": a["status"],
        "fee_cents": a["fee_cents"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def _owner_operator_id(assignment):
    visit = db.service_visits.get(assignment["service_visit_id"])
    return visit["operator_id"] if visit else None


@bp.route("/parking-assignments", methods=["POST"])
def create_assignment():
    _, role = authenticate()
    require_role(role, {"OpsDispatcher", "LineManager"})
    body = get_json()
    service_visit_id = require_string(body, "service_visit_id")
    spot_id = require_string(body, "spot_id")
    start = parse_datetime(body, "occupy_start_utc")
    end = parse_datetime(body, "occupy_end_utc")

    # Existence left to right.
    visit = db.service_visits.get(service_visit_id)
    if visit is None:
        raise err(errors.ERR_NOT_FOUND, "Service visit not found.")
    spot = db.parking_spots.get(spot_id)
    if spot is None:
        raise err(errors.ERR_NOT_FOUND, "Parking spot not found.")

    # Weight-class fit (business rule) before interval validity per §3.10 ordering.
    aircraft = db.aircraft.get(visit["aircraft_id"])
    if aircraft is not None and not weight_class_accepted(aircraft["weight_class"], spot["max_weight_class"]):
        raise err(errors.ERR_WEIGHT_CLASS_REJECTED,
                  "Aircraft weight class exceeds the spot's max weight class.")

    # Interval validity.
    if not (end > start):
        raise err(errors.ERR_INVALID_INTERVAL, "occupy_end_utc must be strictly after occupy_start_utc.")

    a = db.common_create()
    a.update({
        "service_visit_id": service_visit_id,
        "spot_id": spot_id,
        "occupy_start_utc": body["occupy_start_utc"],
        "occupy_end_utc": body["occupy_end_utc"],
        "status": "HELD",
        "fee_cents": 0,
    })
    db.parking_assignments[a["id"]] = a
    return success(assignment_view(a), 201)


@bp.route("/parking-assignments/<id>", methods=["GET"])
def get_assignment(id):
    user_id, role = authenticate()
    require_role(role, {"OpsDispatcher", "BillingClerk", "LineManager", "Operator"})
    a = db.parking_assignments.get(id)
    if a is None:
        raise err(errors.ERR_NOT_FOUND, "Parking assignment not found.")
    if role == "Operator" and user_id != _owner_operator_id(a):
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Operator may read only its own assignments.")
    return success(assignment_view(a), 200)


@bp.route("/parking-assignments", methods=["GET"])
def list_assignments():
    user_id, role = authenticate()
    require_role(role, {"OpsDispatcher", "BillingClerk", "LineManager", "Operator"})
    limit, offset = pagination_params()
    records = list(db.parking_assignments.values())
    if role == "Operator":
        records = [r for r in records if _owner_operator_id(r) == user_id]
    v_f = request.args.get("service_visit_id")
    s_f = request.args.get("spot_id")
    st_f = request.args.get("status")
    if v_f is not None:
        records = [r for r in records if r["service_visit_id"] == v_f]
    if s_f is not None:
        records = [r for r in records if r["spot_id"] == s_f]
    if st_f is not None:
        records = [r for r in records if r["status"] == st_f]
    window, total = paginate(records, limit, offset)
    return list_response([assignment_view(r) for r in window], limit, offset, total)


def _half_open_overlap(s1, e1, s2, e2):
    """Two half-open intervals [s1,e1), [s2,e2) overlap iff s1 < e2 and s2 < e1."""
    return s1 < e2 and s2 < e1


@bp.route("/parking-assignments/<id>/occupy", methods=["POST"])
def occupy(id):
    _, role = authenticate()
    require_role(role, {"OpsDispatcher", "LineManager"})
    a = db.parking_assignments.get(id)
    if a is None:
        raise err(errors.ERR_NOT_FOUND, "Parking assignment not found.")
    body = get_json()
    expected_version = require_int(body, "expected_assignment_version")

    # State eligibility.
    if a["status"] != "HELD":
        raise err(errors.ERR_INVALID_STATE, "occupy requires HELD status.")
    visit = db.service_visits.get(a["service_visit_id"])
    if visit["status"] not in ("ON_GROUND", "SERVICING"):
        raise err(errors.ERR_VISIT_NOT_SERVICEABLE,
                  "Parent visit must be ON_GROUND or SERVICING.")
    spot = db.parking_spots.get(a["spot_id"])
    if spot["spot_status"] != "AVAILABLE":
        raise err(errors.ERR_SPOT_OUT_OF_SERVICE, "Spot is out of service.")

    # Overlap geometry depends on spot type (business rule).
    a_start = _parse_iso(a["occupy_start_utc"])
    a_end = _parse_iso(a["occupy_end_utc"])
    for other in db.parking_assignments.values():
        if other["id"] == a["id"]:
            continue
        if other["spot_id"] != a["spot_id"]:
            continue
        if other["status"] != "OCCUPIED":
            continue
        o_start = _parse_iso(other["occupy_start_utc"])
        o_end = _parse_iso(other["occupy_end_utc"])
        if spot["spot_type"] == "HANGAR":
            # Closed, buffer-inclusive overlap: widen this window by the tow buffer.
            ws = a_start - TOW_BUFFER
            we = a_end + TOW_BUFFER
            if ws <= o_end and o_start <= we:
                raise err(errors.ERR_SPOT_TOW_BUFFER_CONFLICT,
                          "Hangar tow-buffer conflict with an occupied window.")
        else:
            if _half_open_overlap(a_start, a_end, o_start, o_end):
                raise err(errors.ERR_SPOT_WINDOW_CONFLICT,
                          "Spot window conflict with an occupied window.")

    # Optimistic concurrency check (§2.7) — after business conflicts per §3.10.
    if expected_version != a["version"]:
        raise err(errors.ERR_STALE_VERSION, "Stale assignment version.")

    # Compute fee, transition.
    aircraft = db.aircraft.get(visit["aircraft_id"])
    delivered = visit_delivered_jeta_gallons(visit["id"])
    a["fee_cents"] = parking_ramp_fee(
        aircraft["weight_class"], visit["nights"], spot["spot_type"], delivered)
    a["status"] = "OCCUPIED"
    db.touch(a)
    return success(assignment_view(a), 200)


@bp.route("/parking-assignments/<id>/release", methods=["POST"])
def release(id):
    _, role = authenticate()
    require_role(role, {"OpsDispatcher", "LineManager"})
    a = db.parking_assignments.get(id)
    if a is None:
        raise err(errors.ERR_NOT_FOUND, "Parking assignment not found.")
    if a["status"] not in ("HELD", "OCCUPIED"):
        raise err(errors.ERR_INVALID_STATE, "release requires HELD or OCCUPIED status.")
    # fee_cents retained for billing on OCCUPIED release; nothing to keep on HELD.
    a["status"] = "RELEASED"
    db.touch(a)
    return success(assignment_view(a), 200)
