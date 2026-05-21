"""VolunteerShift endpoints."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, g

from ..auth import require_roles
from ..calculations import shift_hours
from ..errors import raise_error
from ..response import success_response
from ..services.aggregates import recompute_guardian_volunteer
from ..services.lookup import get_guardian, get_season, get_shift
from ..services.serializers import serialize_shift
from ..store import get_store, new_id, stamp_create, stamp_update
from ..time_utils import format_iso, now_dt, parse_iso
from ..validation import (
    as_enum,
    as_iso_datetime,
    check_version_if_supplied,
    get_json_body,
    require_fields,
)

shift_bp = Blueprint("shifts", __name__)


ROLES = {"SCOREKEEPER", "CONCESSIONS", "FIELD_PREP", "UMPIRE_ASSIST", "SETUP_TEARDOWN"}


@shift_bp.route("/league/volunteer-shifts", methods=["POST"])
@require_roles(["Guardian", "LeagueAdmin"])
def create_shift():
    body = get_json_body()
    require_fields(body, ["season_id", "guardian_id", "role", "scheduled_start", "scheduled_end"])
    store = get_store()
    season = get_season(store, body["season_id"])
    guardian = get_guardian(store, body["guardian_id"])
    if g.role == "Guardian" and g.user_id != guardian["id"]:
        raise_error("ERR_NOT_OWNER")

    role = as_enum(body["role"], "role", ROLES)
    start = as_iso_datetime(body["scheduled_start"], "scheduled_start")
    end = as_iso_datetime(body["scheduled_end"], "scheduled_end")
    if end <= start:
        raise_error("ERR_VALIDATION", "scheduled_end must be strictly after scheduled_start.")

    game_id = None
    if "game_id" in body and body["game_id"] is not None:
        if body["game_id"] not in store.games:
            raise_error("ERR_REFERENCE_NOT_FOUND", "Game not found.")
        game_id = body["game_id"]

    shift = {
        "id": new_id(),
        "season_id": season["id"],
        "guardian_id": guardian["id"],
        "game_id": game_id,
        "role": role,
        "scheduled_start": format_iso(start),
        "scheduled_end": format_iso(end),
        "hours_credited": Decimal("0.00"),
        "status": "SCHEDULED",
    }
    stamp_create(shift)
    store.shifts[shift["id"]] = shift
    store.record_audit("VolunteerShift", shift["id"], g.role, g.user_id, "SHIFT_SCHEDULED", {})
    return success_response(serialize_shift(shift), status_code=201)


@shift_bp.route("/league/volunteer-shifts/<shift_id>", methods=["GET"])
@require_roles(["Guardian", "LeagueAdmin"])
def read_shift(shift_id: str):
    store = get_store()
    shift = get_shift(store, shift_id)
    if g.role == "Guardian" and shift["guardian_id"] != g.user_id:
        raise_error("ERR_NOT_OWNER")
    return success_response(serialize_shift(shift), status_code=200)


@shift_bp.route("/league/volunteer-shifts/<shift_id>/check-in", methods=["POST"])
@require_roles(["Guardian"])
def check_in(shift_id: str):
    store = get_store()
    shift = get_shift(store, shift_id)
    if shift["guardian_id"] != g.user_id:
        raise_error("ERR_NOT_OWNER")
    if shift["status"] != "SCHEDULED":
        raise_error("ERR_INVALID_STATE", "Only SCHEDULED shifts may check in.")

    start = parse_iso(shift["scheduled_start"])
    end = parse_iso(shift["scheduled_end"])
    now = now_dt()
    grace = timedelta(minutes=30)
    if now < (start - grace) or now > (end + grace):
        raise_error("ERR_CHECK_IN_OUTSIDE_WINDOW")

    shift["status"] = "CHECKED_IN"
    stamp_update(shift)
    store.record_audit("VolunteerShift", shift["id"], g.role, g.user_id, "SHIFT_CHECKED_IN", {})
    return success_response(serialize_shift(shift), status_code=200)


@shift_bp.route("/league/volunteer-shifts/<shift_id>/approve", methods=["POST"])
@require_roles(["LeagueAdmin"])
def approve_shift(shift_id: str):
    store = get_store()
    shift = get_shift(store, shift_id)
    if shift["status"] != "CHECKED_IN":
        raise_error("ERR_INVALID_STATE", "Only CHECKED_IN shifts may be approved.")

    end = parse_iso(shift["scheduled_end"])
    if now_dt() < end:
        raise_error("ERR_INVALID_STATE", "Cannot approve before scheduled_end.")

    start = parse_iso(shift["scheduled_start"])
    hours = shift_hours(start, end)
    shift["hours_credited"] = hours
    shift["status"] = "APPROVED"
    stamp_update(shift)

    # Recompute guardian's aggregate.
    guardian = store.guardians.get(shift["guardian_id"])
    if guardian:
        recompute_guardian_volunteer(store, guardian, shift["season_id"])

    store.record_audit("VolunteerShift", shift["id"], g.role, g.user_id, "SHIFT_APPROVED", {"hours": str(hours)})
    return success_response(serialize_shift(shift), status_code=200)


@shift_bp.route("/league/volunteer-shifts/<shift_id>/mark-no-show", methods=["POST"])
@require_roles(["LeagueAdmin"])
def mark_no_show(shift_id: str):
    store = get_store()
    shift = get_shift(store, shift_id)
    if shift["status"] != "SCHEDULED":
        raise_error("ERR_INVALID_STATE", "Only SCHEDULED shifts may be marked NO_SHOW.")

    end = parse_iso(shift["scheduled_end"])
    grace = timedelta(minutes=30)
    if now_dt() <= (end + grace):
        raise_error("ERR_INVALID_STATE", "Grace window has not yet closed.")

    shift["status"] = "NO_SHOW"
    stamp_update(shift)
    store.record_audit("VolunteerShift", shift["id"], g.role, g.user_id, "SHIFT_NO_SHOW", {})
    return success_response(serialize_shift(shift), status_code=200)


@shift_bp.route("/league/volunteer-shifts/<shift_id>", methods=["DELETE"])
@require_roles(["Guardian"])
def cancel_shift(shift_id: str):
    store = get_store()
    shift = get_shift(store, shift_id)
    if shift["guardian_id"] != g.user_id:
        raise_error("ERR_NOT_OWNER")
    if shift["status"] != "SCHEDULED":
        raise_error("ERR_INVALID_STATE", "Only SCHEDULED shifts may be cancelled.")

    shift["status"] = "CANCELLED"
    stamp_update(shift)
    store.record_audit("VolunteerShift", shift["id"], g.role, g.user_id, "SHIFT_CANCELLED", {})
    return success_response(serialize_shift(shift), status_code=200)
