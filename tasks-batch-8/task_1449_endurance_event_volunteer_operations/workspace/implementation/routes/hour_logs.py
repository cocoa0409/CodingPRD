"""Hour log endpoints: list/get/verify/dispute/reject/adjust."""
from flask import Blueprint, request

import errors
from db import store
from middleware import require_roles
from response import success_object, success_list
from util import get_body, require_field, as_int, parse_dt
from services.core import (
    touch, paginate, sort_by_created, serialize_hour_log,
    get_hour_log_or_404, compute_hour_log_fields, NON_TERMINAL_SIGNUP,
)

bp = Blueprint("hour_logs", __name__)
ANY = ("Anonymous", "Volunteer", "Captain", "GroupLeader", "VolunteerCoordinator", "EventDirector")


@bp.get("/volunteer-ops/hour-logs")
def list_hour_logs():
    require_roles(*ANY)
    event_id = request.args.get("event_id")
    signup_id = request.args.get("signup_id")
    items = [
        l for l in store.hour_logs.values()
        if (event_id is None or l["event_id"] == event_id)
        and (signup_id is None or l["signup_id"] == signup_id)
    ]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return success_list([serialize_hour_log(l) for l in page], limit, offset, total)


@bp.get("/volunteer-ops/hour-logs/<hourLogId>")
def get_hour_log(hourLogId):
    require_roles(*ANY)
    log = get_hour_log_or_404(hourLogId)
    return success_object(serialize_hour_log(log))


def _is_captain_of_shift(user_id, shift_id):
    return any(
        s["shift_id"] == shift_id
        and s["volunteer_id"] == user_id
        and s.get("is_captain")
        and s["status"] in NON_TERMINAL_SIGNUP | {"COMPLETED"}
        for s in store.signups.values()
    )


@bp.post("/volunteer-ops/hour-logs/<hourLogId>/verify")
def verify_hour_log(hourLogId):
    user_id, role = require_roles("Captain", "VolunteerCoordinator")
    log = get_hour_log_or_404(hourLogId)
    if log["status"] not in {"PENDING_VERIFICATION", "DISPUTED"}:
        raise errors.hour_log_invalid_state()
    if role == "Captain":
        su = store.signups.get(log["signup_id"])
        if su is None or not _is_captain_of_shift(user_id, su["shift_id"]):
            raise errors.not_resource_owner()
    log["status"] = "VERIFIED"
    log["verified_by_role"] = "CAPTAIN" if role == "Captain" else "COORDINATOR"
    touch(log)
    return success_object(serialize_hour_log(log))


@bp.post("/volunteer-ops/hour-logs/<hourLogId>/dispute")
def dispute_hour_log(hourLogId):
    user_id, role = require_roles("Volunteer", "GroupLeader", "VolunteerCoordinator")
    log = get_hour_log_or_404(hourLogId)
    if log["status"] not in {"PENDING_VERIFICATION", "VERIFIED"}:
        raise errors.hour_log_invalid_state()
    if role in {"Volunteer", "GroupLeader"}:
        su = store.signups.get(log["signup_id"])
        if su is None:
            raise errors.not_resource_owner()
        if role == "Volunteer":
            if user_id != su["volunteer_id"]:
                raise errors.not_resource_owner()
        else:  # GroupLeader
            vol = store.volunteers.get(su["volunteer_id"])
            if vol is None or vol.get("group_id") is None or user_id != vol["group_id"]:
                raise errors.not_resource_owner()
    log["status"] = "DISPUTED"
    touch(log)
    return success_object(serialize_hour_log(log))


@bp.post("/volunteer-ops/hour-logs/<hourLogId>/reject")
def reject_hour_log(hourLogId):
    require_roles("VolunteerCoordinator")
    log = get_hour_log_or_404(hourLogId)
    if log["status"] != "PENDING_VERIFICATION":
        raise errors.hour_log_invalid_state()
    log["status"] = "REJECTED"
    touch(log)
    return success_object(serialize_hour_log(log))


@bp.post("/volunteer-ops/hour-logs/<hourLogId>/adjust")
def adjust_hour_log(hourLogId):
    require_roles("VolunteerCoordinator")
    log = get_hour_log_or_404(hourLogId)
    if log["status"] != "PENDING_VERIFICATION":
        raise errors.hour_log_invalid_state()
    body = get_body()
    break_minutes = as_int(require_field(body, "break_minutes"), "break_minutes")
    if break_minutes < 0:
        raise errors.invalid_request("break_minutes must be >= 0.")
    su = store.signups.get(log["signup_id"])
    if su is None:
        raise errors.signup_not_found()
    raw, claimed, credited = compute_hour_log_fields(
        su["checked_in_at"], su["checked_out_at"], break_minutes)
    log["break_minutes"] = break_minutes
    log["raw_minutes"] = raw
    log["claimed_hours"] = claimed
    log["credited_hours"] = credited
    touch(log)
    return success_object(serialize_hour_log(log))
