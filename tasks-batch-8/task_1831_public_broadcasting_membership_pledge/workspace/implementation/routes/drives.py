"""Pledge drives, on-air breaks, matching challenges, underwriting credits."""

from datetime import timedelta

from flask import Blueprint, request

import db
import response
import validators as v
from errors import (
    ApiError,
    ERR_BREAK_OVERLAP,
    ERR_DRIVE_OVERLAP,
    ERR_INVALID_STATE,
    ERR_STALE_DRIVE_VERSION,
    ERR_UNRESOLVED_PLEDGES,
)
from middleware import require_roles
from services import core

bp = Blueprint("drives", __name__)

ALL_ROLES = ("StationAdmin", "MembershipCoordinator", "PhoneVolunteer")


# --- Drives ---

@bp.route("/station/pledge-drives", methods=["POST"])
def create_drive():
    body = v.get_json_body()
    require_roles("StationAdmin")
    name = v.req_str(body, "name")
    starts_at = v.req_dt(body, "starts_at")
    ends_at = v.req_dt(body, "ends_at")
    goal_cents = v.req_int(body, "goal_cents", min_val=0)
    if ends_at <= starts_at:
        v.invalid("ends_at must be strictly after starts_at")

    ent = db.new_entity()
    ent.update({
        "name": name,
        "starts_at": db.iso(starts_at),
        "ends_at": db.iso(ends_at),
        "status": "DRAFT",
        "goal_cents": goal_cents,
        "pledged_cents": 0,
        "collected_cents": 0,
    })
    db.drives[ent["id"]] = ent
    return response.success_object(ent, status=201)


@bp.route("/station/pledge-drives/<did>", methods=["GET"])
def get_drive(did):
    require_roles(*ALL_ROLES)
    ent = db.drives.get(did)
    if ent is None:
        v.not_found(f"PledgeDrive '{did}' not found")
    return response.success_object(ent)


# --- Breaks ---

@bp.route("/station/pledge-drives/<did>/breaks", methods=["POST"])
def create_break(did):
    body = v.get_json_body()
    require_roles("StationAdmin")
    drive = db.drives.get(did)
    if drive is None:
        v.not_found(f"PledgeDrive '{did}' not found")

    starts_at = v.req_dt(body, "starts_at")
    ends_at = v.req_dt(body, "ends_at")
    program_title = v.req_str(body, "program_title")
    pitch_level_code = v.req_str(body, "pitch_level_code")
    if ends_at <= starts_at:
        v.invalid("ends_at must be strictly after starts_at")
    expected = body.get("expected_drive_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        v.invalid("Field 'expected_drive_version' is required and must be an integer")

    # State: drive must be DRAFT or SCHEDULED (priority 4 — before OCC/business checks)
    if drive["status"] not in ("DRAFT", "SCHEDULED"):
        raise ApiError(ERR_INVALID_STATE[0],
                       f"Break lineup frozen once drive is {drive['status']}",
                       ERR_INVALID_STATE[1])

    # pitch level existence
    if core.get_level_by_code(pitch_level_code) is None:
        v.invalid(f"MembershipLevel '{pitch_level_code}' not found")

    # OCC check
    if expected != drive["version"]:
        raise ApiError(ERR_STALE_DRIVE_VERSION[0],
                       "expected_drive_version does not match PledgeDrive.version",
                       ERR_STALE_DRIVE_VERSION[1])

    # Window containment + 5-minute buffer overlap check (half-open intervals)
    drive_start = db.parse_dt(drive["starts_at"])
    drive_end = db.parse_dt(drive["ends_at"])
    if starts_at < drive_start or ends_at > drive_end:
        raise ApiError(ERR_BREAK_OVERLAP[0],
                       "Break must lie within the drive window",
                       ERR_BREAK_OVERLAP[1])

    buffer = timedelta(minutes=5)
    for other in db.breaks.values():
        if other["drive_id"] != did:
            continue
        o_start = db.parse_dt(other["starts_at"])
        o_end = db.parse_dt(other["ends_at"])
        # Half-open [start, end) with 5-minute buffer between any two breaks:
        # allowed iff new_start >= o_end + buffer OR new_end + buffer <= o_start
        if starts_at >= o_end + buffer or ends_at + buffer <= o_start:
            continue
        raise ApiError(ERR_BREAK_OVERLAP[0],
                       "Break overlaps another break in the same drive within the 5-minute buffer",
                       ERR_BREAK_OVERLAP[1])

    ent = db.new_entity()
    ent.update({
        "drive_id": did,
        "starts_at": db.iso(starts_at),
        "ends_at": db.iso(ends_at),
        "program_title": program_title,
        "pitch_level_code": pitch_level_code,
        "status": "SCHEDULED",
    })
    db.breaks[ent["id"]] = ent
    db.touch(drive)  # OCC: drive version increments on break creation
    return response.success_object(ent, status=201)


@bp.route("/station/pledge-drives/<did>/breaks", methods=["GET"])
def list_breaks(did):
    require_roles(*ALL_ROLES)
    if did not in db.drives:
        v.not_found(f"PledgeDrive '{did}' not found")
    limit, offset = v.parse_pagination(request.args)
    items = [b for b in db.breaks.values() if b["drive_id"] == did]
    items = v.sort_created(items)
    page, total = v.paginate(items, limit, offset)
    return response.success_list(page, limit, offset, total)


# --- Drive lifecycle ---

def _get_drive_or_404(did):
    drive = db.drives.get(did)
    if drive is None:
        v.not_found(f"PledgeDrive '{did}' not found")
    return drive


@bp.route("/station/pledge-drives/<did>/schedule", methods=["POST"])
def schedule_drive(did):
    v.get_json_body(required=False)
    require_roles("StationAdmin")
    drive = _get_drive_or_404(did)
    if drive["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE[0],
                       f"Drive must be DRAFT to schedule (current: {drive['status']})",
                       ERR_INVALID_STATE[1])
    # At least one SCHEDULED break must exist
    has_break = any(b["drive_id"] == did and b["status"] == "SCHEDULED" for b in db.breaks.values())
    if not has_break:
        raise ApiError(ERR_INVALID_STATE[0],
                       "At least one OnAirBreak in SCHEDULED status must exist for the drive",
                       ERR_INVALID_STATE[1])
    # Overlap check: no other drive in SCHEDULED/ON_AIR overlapping [starts_at, ends_at) half-open
    s = db.parse_dt(drive["starts_at"])
    e = db.parse_dt(drive["ends_at"])
    for other in db.drives.values():
        if other["id"] == did:
            continue
        if other["status"] not in ("SCHEDULED", "ON_AIR"):
            continue
        os_ = db.parse_dt(other["starts_at"])
        oe = db.parse_dt(other["ends_at"])
        # Half-open overlap: s < oe and os < e
        if s < oe and os_ < e:
            raise ApiError(ERR_DRIVE_OVERLAP[0],
                           "Drive overlaps another SCHEDULED or ON_AIR drive",
                           ERR_DRIVE_OVERLAP[1])
    drive["status"] = "SCHEDULED"
    db.touch(drive)
    return response.success_object(drive)


@bp.route("/station/pledge-drives/<did>/unschedule", methods=["POST"])
def unschedule_drive(did):
    v.get_json_body(required=False)
    require_roles("StationAdmin")
    drive = _get_drive_or_404(did)
    if drive["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE[0],
                       f"Drive must be SCHEDULED to unschedule (current: {drive['status']})",
                       ERR_INVALID_STATE[1])
    drive["status"] = "DRAFT"
    db.touch(drive)
    return response.success_object(drive)


@bp.route("/station/pledge-drives/<did>/go-live", methods=["POST"])
def go_live_drive(did):
    v.get_json_body(required=False)
    require_roles("StationAdmin")
    drive = _get_drive_or_404(did)
    if drive["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE[0],
                       f"Drive must be SCHEDULED to go live (current: {drive['status']})",
                       ERR_INVALID_STATE[1])
    if db.now() < db.parse_dt(drive["starts_at"]):
        raise ApiError(ERR_INVALID_STATE[0],
                       "Logical clock has not reached the drive starts_at",
                       ERR_INVALID_STATE[1])
    drive["status"] = "ON_AIR"
    db.touch(drive)
    return response.success_object(drive)


@bp.route("/station/pledge-drives/<did>/close", methods=["POST"])
def close_drive(did):
    v.get_json_body(required=False)
    require_roles("StationAdmin")
    drive = _get_drive_or_404(did)
    if drive["status"] != "ON_AIR":
        raise ApiError(ERR_INVALID_STATE[0],
                       f"Drive must be ON_AIR to close (current: {drive['status']})",
                       ERR_INVALID_STATE[1])
    drive["status"] = "CLOSED"
    db.touch(drive)
    # Cascade: all breaks still SCHEDULED -> AIRED
    for b in db.breaks.values():
        if b["drive_id"] == did and b["status"] == "SCHEDULED":
            b["status"] = "AIRED"
            db.touch(b)
    # Cascade: all challenges still OPEN -> EXPIRED
    for c in db.challenges.values():
        if c["drive_id"] == did and c["status"] == "OPEN":
            c["status"] = "EXPIRED"
            db.touch(c)
    return response.success_object(drive)


@bp.route("/station/pledge-drives/<did>/reconcile", methods=["POST"])
def reconcile_drive(did):
    v.get_json_body(required=False)
    require_roles("MembershipCoordinator")
    drive = _get_drive_or_404(did)
    if drive["status"] != "CLOSED":
        raise ApiError(ERR_INVALID_STATE[0],
                       f"Drive must be CLOSED to reconcile (current: {drive['status']})",
                       ERR_INVALID_STATE[1])
    for p in db.pledges.values():
        if p["drive_id"] == did and p["payment_status"] in ("PLEDGED", "PARTIAL"):
            raise ApiError(ERR_UNRESOLVED_PLEDGES[0],
                           "Drive has pledges in PLEDGED or PARTIAL status",
                           ERR_UNRESOLVED_PLEDGES[1])
    drive["status"] = "RECONCILED"
    db.touch(drive)
    return response.success_object(drive)


# --- Matching challenges ---

@bp.route("/station/pledge-drives/<did>/matching-challenges", methods=["POST"])
def create_challenge(did):
    body = v.get_json_body()
    require_roles("StationAdmin")
    drive = _get_drive_or_404(did)
    sponsor_name = v.req_str(body, "sponsor_name")
    goal_cents = v.req_int(body, "goal_cents", min_val=1)
    match_cents = v.req_int(body, "match_cents", min_val=1)

    ent = db.new_entity()
    ent.update({
        "drive_id": did,
        "sponsor_name": sponsor_name,
        "goal_cents": goal_cents,
        "match_cents": match_cents,
        "progress_cents": 0,
        "status": "OPEN",
    })
    db.challenges[ent["id"]] = ent
    return response.success_object(ent, status=201)


@bp.route("/station/pledge-drives/<did>/matching-challenges", methods=["GET"])
def list_challenges(did):
    require_roles(*ALL_ROLES)
    if did not in db.drives:
        v.not_found(f"PledgeDrive '{did}' not found")
    limit, offset = v.parse_pagination(request.args)
    items = [c for c in db.challenges.values() if c["drive_id"] == did]
    items = v.sort_created(items)
    page, total = v.paginate(items, limit, offset)
    return response.success_list(page, limit, offset, total)


@bp.route("/station/matching-challenges/<cid>", methods=["GET"])
def get_challenge(cid):
    require_roles(*ALL_ROLES)
    ent = db.challenges.get(cid)
    if ent is None:
        v.not_found(f"MatchingChallenge '{cid}' not found")
    return response.success_object(ent)


# --- Underwriting credits ---

@bp.route("/station/pledge-drives/<did>/underwriting-credits", methods=["POST"])
def create_credit(did):
    body = v.get_json_body()
    require_roles("StationAdmin")
    drive = _get_drive_or_404(did)
    underwriter_name = v.req_str(body, "underwriter_name")
    amount_cents = v.req_int(body, "amount_cents", min_val=1)
    aired = v.opt_bool(body, "aired", default=False)

    ent = db.new_entity()
    ent.update({
        "drive_id": did,
        "underwriter_name": underwriter_name,
        "amount_cents": amount_cents,
        "aired": aired,
    })
    db.credits[ent["id"]] = ent
    return response.success_object(ent, status=201)


@bp.route("/station/pledge-drives/<did>/underwriting-credits", methods=["GET"])
def list_credits(did):
    require_roles("StationAdmin", "MembershipCoordinator")
    if did not in db.drives:
        v.not_found(f"PledgeDrive '{did}' not found")
    limit, offset = v.parse_pagination(request.args)
    items = [c for c in db.credits.values() if c["drive_id"] == did]
    items = v.sort_created(items)
    page, total = v.paginate(items, limit, offset)
    return response.success_list(page, limit, offset, total)
