"""Signup endpoints: create/approve/confirm/cancel/check-in/check-out/no-show/captain."""
from datetime import timedelta

from flask import Blueprint, request

import errors
from db import store
from middleware import require_roles
from response import success_object, success_list
from util import (
    get_body, require_field, optional_field, as_string, as_int,
    logical_now, parse_dt, format_iso,
)
from services.core import (
    make_record, touch, paginate, sort_by_created, serialize_signup,
    get_volunteer_or_404, get_shift_or_404, get_signup_or_404,
    confirmed_count, update_shift_posture, run_safety_gauntlet, check_overlap,
    compute_hour_log_fields, NON_TERMINAL_SIGNUP,
)
from services.seat_open import seat_open_handling
from services.cascade import cancel_signup_record, revoke_distributions_for_signup

bp = Blueprint("signups", __name__)
ANY = ("Anonymous", "Volunteer", "Captain", "GroupLeader", "VolunteerCoordinator", "EventDirector")


def _signup_window_check(ev, volunteer, now):
    """Temporal-window gate for signup creation (priority 8)."""
    early = parse_dt(ev["early_access_opens_at"])
    opens = parse_dt(ev["signup_opens_at"])
    closes = parse_dt(ev["signup_closes_at"])
    if now < early or now >= closes:
        raise errors.signup_window_closed()
    if early <= now < opens and not volunteer.get("is_returning"):
        raise errors.early_access_restricted()


def _gauntlet_for_create_or_approve(volunteer, shift, now, check_window, check_duplicate):
    """Shared signup gauntlet, in §2.10 priority order (state -> age -> skill -> training
    -> temporal -> constraints). Capacity is checked by the caller where applicable."""
    ev = store.events.get(shift["event_id"])
    # state gates (priority 4)
    if ev is None or ev["status"] != "PUBLISHED":
        raise errors.event_not_published()
    if volunteer["status"] != "ELIGIBLE":
        raise errors.volunteer_not_eligible()
    if shift["status"] not in {"OPEN", "FULL"}:
        raise errors.shift_not_open()
    role = store.role_catalog_entries.get(shift["role_entry_id"])
    if role is None or role["status"] != "ACTIVE":
        raise errors.role_entry_not_active()
    # business safety 5-7
    run_safety_gauntlet(volunteer, shift, now)
    # temporal 8
    if check_window:
        _signup_window_check(ev, volunteer, now)
    # constraints 9
    if check_duplicate:
        dup = any(
            su["volunteer_id"] == volunteer["id"]
            and su["shift_id"] == shift["id"]
            and su["status"] in NON_TERMINAL_SIGNUP
            for su in store.signups.values()
        )
        if dup:
            raise errors.duplicate_signup()
    check_overlap(volunteer["id"], shift)
    return ev, role


def _set_confirm_by(signup, shift, now):
    start = parse_dt(shift["start_at"])
    a = now + timedelta(hours=48)
    b = start - timedelta(hours=1)
    signup["confirm_by_at"] = format_iso(min(a, b))


@bp.post("/volunteer-ops/signups")
def create_signup():
    user_id, role = require_roles("Volunteer", "VolunteerCoordinator")
    body = get_body()
    volunteer_id = as_string(require_field(body, "volunteer_id"), "volunteer_id")
    volunteer = get_volunteer_or_404(volunteer_id)
    shift_id = as_string(require_field(body, "shift_id"), "shift_id")
    shift = get_shift_or_404(shift_id)
    now = logical_now()

    _gauntlet_for_create_or_approve(volunteer, shift, now, check_window=True, check_duplicate=True)

    # ownership (priority 13): Volunteer may only file for themselves
    if role == "Volunteer" and user_id != volunteer["id"]:
        raise errors.not_resource_owner()

    seats_free = confirmed_count(shift["id"]) < shift["required_headcount"]
    status = "REQUESTED" if seats_free else "WAITLISTED"
    su = make_record({
        "event_id": shift["event_id"],
        "volunteer_id": volunteer["id"],
        "shift_id": shift["id"],
        "status": status,
        "origin": "DIRECT",
        "replaces_signup_id": None,
        "is_captain": False,
        "requested_at": format_iso(now),
        "approved_at": None,
        "confirm_by_at": None,
        "confirmed_at": None,
        "checked_in_at": None,
        "checked_out_at": None,
    })
    store.signups[su["id"]] = su
    return success_object(serialize_signup(su), status=201)


@bp.get("/volunteer-ops/signups")
def list_signups():
    require_roles(*ANY)
    event_id = request.args.get("event_id")
    volunteer_id = request.args.get("volunteer_id")
    shift_id = request.args.get("shift_id")
    status = request.args.get("status")
    replaces = request.args.get("replaces_signup_id")
    items = [
        s for s in store.signups.values()
        if (event_id is None or s["event_id"] == event_id)
        and (volunteer_id is None or s["volunteer_id"] == volunteer_id)
        and (shift_id is None or s["shift_id"] == shift_id)
        and (status is None or s["status"] == status)
        and (replaces is None or s.get("replaces_signup_id") == replaces)
    ]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return success_list([serialize_signup(s) for s in page], limit, offset, total)


@bp.get("/volunteer-ops/signups/<signupId>")
def get_signup(signupId):
    require_roles(*ANY)
    su = get_signup_or_404(signupId)
    return success_object(serialize_signup(su))


@bp.post("/volunteer-ops/signups/<signupId>/approve")
def approve_signup(signupId):
    require_roles("VolunteerCoordinator")
    su = get_signup_or_404(signupId)
    if su["status"] != "REQUESTED":
        raise errors.signup_not_approvable()
    volunteer = store.volunteers.get(su["volunteer_id"])
    if volunteer is None:
        raise errors.volunteer_not_found()
    shift = store.shifts.get(su["shift_id"])
    if shift is None:
        raise errors.shift_not_found()
    now = logical_now()
    _gauntlet_for_create_or_approve(volunteer, shift, now, check_window=False, check_duplicate=False)
    # capacity (priority 10)
    if confirmed_count(shift["id"]) >= shift["required_headcount"]:
        raise errors.shift_capacity_reached()

    su["status"] = "APPROVED"
    su["approved_at"] = format_iso(now)
    _set_confirm_by(su, shift, now)
    touch(su)
    update_shift_posture(shift)
    return success_object(serialize_signup(su))


@bp.post("/volunteer-ops/signups/<signupId>/confirm")
def confirm_signup(signupId):
    user_id, role = require_roles("Volunteer")
    su = get_signup_or_404(signupId)
    if su["status"] != "APPROVED":
        raise errors.signup_not_confirmable()
    now = logical_now()
    if su.get("confirm_by_at") and now > parse_dt(su["confirm_by_at"]):
        raise errors.confirm_deadline_passed()
    if user_id != su["volunteer_id"]:
        raise errors.not_resource_owner()
    su["status"] = "CONFIRMED"
    su["confirmed_at"] = format_iso(now)
    touch(su)
    shift = store.shifts.get(su["shift_id"])
    if shift is not None:
        update_shift_posture(shift)
    return success_object(serialize_signup(su))


@bp.post("/volunteer-ops/signups/<signupId>/cancel")
def cancel_signup(signupId):
    user_id, role = require_roles("Volunteer", "VolunteerCoordinator")
    su = get_signup_or_404(signupId)
    if su["status"] not in {"REQUESTED", "WAITLISTED", "APPROVED", "CONFIRMED"}:
        raise errors.signup_not_cancellable()
    ev = store.events.get(su["event_id"])
    # self-cancel of a CONFIRMED signup is forbidden once the event is RACE_DAY
    if (
        role == "Volunteer"
        and su["status"] == "CONFIRMED"
        and ev is not None and ev["status"] == "RACE_DAY"
    ):
        raise errors.signup_not_cancellable()
    # ownership: Volunteer may only cancel own signups
    if role == "Volunteer" and user_id != su["volunteer_id"]:
        raise errors.not_resource_owner()
    cancel_signup_record(su, fire_seat_open=True)
    return success_object(serialize_signup(su))


@bp.post("/volunteer-ops/signups/<signupId>/check-in")
def check_in_signup(signupId):
    require_roles("VolunteerCoordinator")
    su = get_signup_or_404(signupId)
    if su["status"] != "CONFIRMED":
        raise errors.signup_not_checkinable()
    ev = store.events.get(su["event_id"])
    if ev is None or ev["status"] != "RACE_DAY":
        raise errors.invalid_event_state("Check-in requires event status RACE_DAY.")
    shift = store.shifts.get(su["shift_id"])
    if shift is None:
        raise errors.shift_not_found()
    now = logical_now()
    start = parse_dt(shift["start_at"])
    end = parse_dt(shift["end_at"])
    if not (start - timedelta(minutes=60) <= now <= end):
        raise errors.checkin_window_invalid()
    su["status"] = "CHECKED_IN"
    su["checked_in_at"] = format_iso(now)
    touch(su)
    # auto-create credential distribution
    dist = make_record({
        "event_id": su["event_id"],
        "signup_id": su["id"],
        "inventory_id": None,
        "kind": "CREDENTIAL",
        "status": "ISSUED",
        "issued_at": format_iso(now),
        "returned_at": None,
    })
    store.distribution_records[dist["id"]] = dist
    update_shift_posture(shift)
    return success_object(serialize_signup(su))


@bp.post("/volunteer-ops/signups/<signupId>/check-out")
def check_out_signup(signupId):
    require_roles("VolunteerCoordinator")
    su = get_signup_or_404(signupId)
    if su["status"] != "CHECKED_IN":
        raise errors.signup_not_checked_outable()
    body = get_body()
    break_minutes = optional_field(body, "break_minutes", 0)
    break_minutes = as_int(break_minutes, "break_minutes")
    if break_minutes < 0:
        raise errors.invalid_request("break_minutes must be >= 0.")
    now = logical_now()
    su["status"] = "COMPLETED"
    su["checked_out_at"] = format_iso(now)
    touch(su)
    raw, claimed, credited = compute_hour_log_fields(
        su["checked_in_at"], su["checked_out_at"], break_minutes)
    log = make_record({
        "event_id": su["event_id"],
        "signup_id": su["id"],
        "status": "PENDING_VERIFICATION",
        "break_minutes": break_minutes,
        "raw_minutes": raw,
        "claimed_hours": claimed,
        "credited_hours": credited,
        "verified_by_role": None,
    })
    store.hour_logs[log["id"]] = log
    shift = store.shifts.get(su["shift_id"])
    if shift is not None:
        update_shift_posture(shift)
    return success_object(serialize_signup(su))


@bp.post("/volunteer-ops/signups/<signupId>/mark-no-show")
def mark_no_show(signupId):
    user_id, role = require_roles("Captain", "VolunteerCoordinator")
    su = get_signup_or_404(signupId)
    if su["status"] != "CONFIRMED":
        raise errors.signup_not_no_showable()
    ev = store.events.get(su["event_id"])
    if ev is None or ev["status"] not in {"RACE_DAY", "COMPLETED"}:
        raise errors.invalid_event_state("Mark-no-show requires event RACE_DAY or COMPLETED.")
    shift = store.shifts.get(su["shift_id"])
    if shift is None:
        raise errors.shift_not_found()
    now = logical_now()
    start = parse_dt(shift["start_at"])
    if now < start + timedelta(minutes=30):
        raise errors.no_show_grace_not_passed()
    # ownership: Captain must hold a captain signup on this shift
    if role == "Captain":
        is_captain_of_shift = any(
            s["shift_id"] == shift["id"]
            and s["volunteer_id"] == user_id
            and s.get("is_captain")
            and s["status"] in NON_TERMINAL_SIGNUP | {"COMPLETED"}
            for s in store.signups.values()
        )
        if not is_captain_of_shift:
            raise errors.not_resource_owner()

    su["status"] = "NO_SHOW"
    if su.get("is_captain"):
        su["is_captain"] = False
    touch(su)

    volunteer = store.volunteers.get(su["volunteer_id"])
    if volunteer is not None:
        volunteer["no_show_strikes"] += 1
        if volunteer["no_show_strikes"] >= 2 and volunteer["status"] == "ELIGIBLE":
            volunteer["status"] = "SUSPENDED"
            touch(volunteer)
            # cascade: cancel every other APPROVED|CONFIRMED signup of this volunteer;
            # each freed seat fires seat-open handling with the cancelled signup as
            # the freed record (PRD §3.7 link five: "every freed seat fires seat-open
            # handling"; the backfill's replaces_signup_id points at the freed signup).
            freed = []
            for other in list(store.signups.values()):
                if (
                    other["volunteer_id"] == volunteer["id"]
                    and other["id"] != su["id"]
                    and other["status"] in {"APPROVED", "CONFIRMED"}
                ):
                    cancel_signup_record(other, fire_seat_open=False)
                    freed.append(other)
            for other in freed:
                other_shift = store.shifts.get(other["shift_id"])
                if other_shift is not None:
                    seat_open_handling(other_shift, freed_signup=other)
        else:
            touch(volunteer)

    # this shift's freed seat
    seat_open_handling(shift, freed_signup=su)
    return success_object(serialize_signup(su))


@bp.post("/volunteer-ops/signups/<signupId>/assign-captain")
def assign_captain(signupId):
    require_roles("VolunteerCoordinator")
    su = get_signup_or_404(signupId)
    if su["status"] != "CONFIRMED":
        raise errors.signup_not_confirmable()
    volunteer = store.volunteers.get(su["volunteer_id"])
    if volunteer is None:
        raise errors.volunteer_not_found()
    now = logical_now()
    # training gate: CAPTAIN_COURSE current
    from services.core import training_current
    if not training_current(volunteer["id"], "CAPTAIN_COURSE", now):
        raise errors.training_not_current()
    # one captain per shift
    for other in store.signups.values():
        if (
            other["shift_id"] == su["shift_id"]
            and other["id"] != su["id"]
            and other.get("is_captain")
            and other["status"] in NON_TERMINAL_SIGNUP | {"COMPLETED"}
        ):
            raise errors.captain_slot_taken()
    su["is_captain"] = True
    touch(su)
    return success_object(serialize_signup(su))


@bp.post("/volunteer-ops/signups/<signupId>/remove-captain")
def remove_captain(signupId):
    require_roles("VolunteerCoordinator")
    su = get_signup_or_404(signupId)
    su["is_captain"] = False
    touch(su)
    return success_object(serialize_signup(su))
