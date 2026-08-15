"""Facilities and closure intervals (with the deep closure cascade)."""

import uuid

from flask import Blueprint

import errors as E
from domain import facility_out, get_or_404, cancel_assignment, overlaps, FACILITY_KINDS
from store import DB
from util import (body_json, req_str, req_enum, req_dt, req_present, is_int,
                  envelope_object, require_role, stamp_new, touch)

bp = Blueprint("facilities", __name__)


def _validate_windows(windows):
    if not isinstance(windows, list):
        raise E.err_validation("operating_windows must be an array")
    out = []
    for w in windows:
        if not isinstance(w, dict):
            raise E.err_validation("each operating window must be an object")
        dow = w.get("day_of_week")
        open_m = w.get("open_minute")
        close_m = w.get("close_minute")
        if not is_int(dow) or not (0 <= dow <= 6):
            raise E.err_validation("day_of_week must be an integer in 0..6")
        if not is_int(open_m) or not is_int(close_m) or not (0 <= open_m < close_m <= 1440):
            raise E.err_validation("operating windows must satisfy 0 <= open_minute < close_minute <= 1440")
        out.append({"day_of_week": dow, "open_minute": open_m, "close_minute": close_m})
    return out


@bp.route("/v1/facilities", methods=["POST"])
def create_facility():
    require_role("RecAdmin")
    body = body_json()
    name = req_str(body, "name")
    kind = req_enum(body, "kind", FACILITY_KINDS)
    if "operating_windows" not in body or body["operating_windows"] is None:
        raise E.err_validation("Missing required field: operating_windows")
    windows = _validate_windows(body["operating_windows"])
    facility = stamp_new({
        "name": name,
        "kind": kind,
        "operating_windows": windows,
        "closures": [],
    })
    DB.facilities[facility["id"]] = facility
    return envelope_object(facility_out(facility), 201)


@bp.route("/v1/facilities/<facility_id>", methods=["GET"])
def get_facility(facility_id):
    require_role("RecAdmin", "LeagueCoordinator", "FacilityManager", "Member", "Staff")
    facility = get_or_404(DB.facilities, facility_id)
    return envelope_object(facility_out(facility))


@bp.route("/v1/facilities/<facility_id>/closures", methods=["POST"])
def create_closure(facility_id):
    require_role("FacilityManager")
    facility = get_or_404(DB.facilities, facility_id)
    body = body_json()
    start_at = req_dt(body, "start_at")
    end_at = req_dt(body, "end_at")
    reason = req_str(body, "reason")
    if end_at <= start_at:
        raise E.err_validation("end_at must be after start_at")
    expected = req_present(body, "expected_facility_version")
    if not is_int(expected):
        raise E.err_validation("expected_facility_version must be an integer")
    if expected != facility["version"]:
        raise E.err_stale_version()
    # Deep cascade: bump overlapping SCHEDULED games; cancel overlapping
    # SCHEDULED classes (registrations cancelled, no promotion, no pay).
    for gm in sorted(DB.games.values(), key=lambda g: g["_seq"]):
        if gm["facility_id"] != facility_id or gm["status"] != "SCHEDULED":
            continue
        if gm["start_at"] is None:
            continue
        if overlaps(gm["start_at"], gm["end_at"], start_at, end_at):
            gm["status"] = "RESCHEDULE_REQUIRED"
            touch(gm)
            for a in list(DB.assignments.values()):
                if a["game_id"] == gm["id"]:
                    cancel_assignment(a)
    for fc in sorted(DB.fitness_classes.values(), key=lambda c: c["_seq"]):
        if fc["facility_id"] != facility_id or fc["status"] != "SCHEDULED":
            continue
        if overlaps(fc["start_at"], fc["end_at"], start_at, end_at):
            fc["status"] = "CANCELLED"
            for reg in DB.registrations.values():
                if reg["fitness_class_id"] == fc["id"] and reg["status"] in ("REGISTERED", "WAITLISTED"):
                    reg["status"] = "CANCELLED"
                    touch(reg)
            fc["registered_count"] = 0
            fc["waitlist_count"] = 0
            touch(fc)
    facility["closures"].append({
        "closure_id": uuid.uuid4().hex,
        "start_at": start_at,
        "end_at": end_at,
        "reason": reason,
    })
    touch(facility)
    return envelope_object(facility_out(facility), 201)
