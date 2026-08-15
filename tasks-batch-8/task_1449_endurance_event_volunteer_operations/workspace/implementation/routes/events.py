"""Event endpoints, logical clock, and epoch sweep."""
from flask import Blueprint, request

import errors
from db import store
from middleware import require_roles
from response import success_object, success_list
from util import (
    get_body, require_field, as_string, as_int, normalize_iso, parse_dt,
    format_iso, logical_now, set_logical_clock,
)
from services.core import (
    make_record, touch, serialize_event, paginate, sort_by_created,
    get_event_or_404,
)
from services.cascade import event_cancel_cascade, cancel_signup_record
from services.seat_open import seat_open_handling

bp = Blueprint("events", __name__)

ANY = ("Anonymous", "Volunteer", "Captain", "GroupLeader", "VolunteerCoordinator", "EventDirector")


def _validate_event_times(body, base=None):
    """Validate the five instants + ordering invariants. Returns normalized values."""
    src = dict(base) if base else {}
    for f in ("event_start_at", "event_end_at", "early_access_opens_at",
              "signup_opens_at", "signup_closes_at"):
        if f in body and body[f] is not None:
            src[f] = normalize_iso(as_string(body[f], f))
    missing = [f for f in ("event_start_at", "event_end_at", "early_access_opens_at",
                           "signup_opens_at", "signup_closes_at") if f not in src]
    if missing:
        raise errors.invalid_request(f"Missing required field: {missing[0]}")
    start = parse_dt(src["event_start_at"])
    end = parse_dt(src["event_end_at"])
    early = parse_dt(src["early_access_opens_at"])
    opens = parse_dt(src["signup_opens_at"])
    closes = parse_dt(src["signup_closes_at"])
    if not (end > start):
        raise errors.invalid_request("event_end_at must be strictly after event_start_at.")
    if not (early <= opens < closes):
        raise errors.invalid_request(
            "signup_opens_at must be >= early_access_opens_at and < signup_closes_at.")
    if not (closes <= start):
        raise errors.invalid_request("signup_closes_at must be <= event_start_at.")
    return src


@bp.post("/volunteer-ops/_clock/set_current_utc")
def set_clock():
    require_roles("EventDirector")
    body = get_body()
    to_iso = require_field(body, "to_iso8601")
    now_iso = set_logical_clock(as_string(to_iso, "to_iso8601"))
    return success_object({"now_iso8601": now_iso})


@bp.post("/volunteer-ops/events")
def create_event():
    require_roles("EventDirector")
    body = get_body()
    name = as_string(require_field(body, "name"), "name")
    vals = _validate_event_times(body)
    ev = make_record({
        "name": name,
        "event_start_at": vals["event_start_at"],
        "event_end_at": vals["event_end_at"],
        "early_access_opens_at": vals["early_access_opens_at"],
        "signup_opens_at": vals["signup_opens_at"],
        "signup_closes_at": vals["signup_closes_at"],
        "status": "DRAFT",
    })
    store.events[ev["id"]] = ev
    return success_object(serialize_event(ev), status=201)


@bp.get("/volunteer-ops/events")
def list_events():
    require_roles(*ANY)
    items = sort_by_created(list(store.events.values()))
    page, limit, offset, total = paginate(items, request.args)
    return success_list([serialize_event(e) for e in page], limit, offset, total)


@bp.get("/volunteer-ops/events/<eventId>")
def get_event(eventId):
    require_roles(*ANY)
    ev = get_event_or_404(eventId)
    return success_object(serialize_event(ev))


@bp.patch("/volunteer-ops/events/<eventId>")
def update_event(eventId):
    require_roles("EventDirector")
    ev = get_event_or_404(eventId)
    # state gate: only while DRAFT
    if ev["status"] != "DRAFT":
        raise errors.invalid_event_state("Event configuration may only be updated while DRAFT.")
    body = get_body()
    expected = require_field(body, "expected_event_version")
    expected = as_int(expected, "expected_event_version")
    if expected != ev["version"]:
        raise errors.stale_version()
    if "name" in body and body["name"] is not None:
        ev["name"] = as_string(body["name"], "name")
    vals = _validate_event_times(body, base={
        "event_start_at": ev["event_start_at"],
        "event_end_at": ev["event_end_at"],
        "early_access_opens_at": ev["early_access_opens_at"],
        "signup_opens_at": ev["signup_opens_at"],
        "signup_closes_at": ev["signup_closes_at"],
    })
    for f in ("event_start_at", "event_end_at", "early_access_opens_at",
              "signup_opens_at", "signup_closes_at"):
        ev[f] = vals[f]
    touch(ev)
    return success_object(serialize_event(ev))


@bp.post("/volunteer-ops/events/<eventId>/publish")
def publish_event(eventId):
    require_roles("EventDirector")
    ev = get_event_or_404(eventId)
    if ev["status"] != "DRAFT":
        raise errors.invalid_event_state("Publish requires event status DRAFT.")
    has_role = any(
        r["event_id"] == ev["id"] and r["status"] == "ACTIVE"
        for r in store.role_catalog_entries.values()
    )
    has_segment = any(s["event_id"] == ev["id"] for s in store.course_segments.values())
    has_shift = any(s["event_id"] == ev["id"] for s in store.shifts.values())
    if not (has_role and has_segment and has_shift):
        raise errors.event_readiness_incomplete()
    ev["status"] = "PUBLISHED"
    touch(ev)
    return success_object(serialize_event(ev))


def _lock_event(ev):
    ev["status"] = "LOCKED"
    touch(ev)
    for shift in store.shifts.values():
        if shift["event_id"] == ev["id"] and shift["status"] in {"OPEN", "FULL"}:
            shift["status"] = "LOCKED"
            touch(shift)


@bp.post("/volunteer-ops/events/<eventId>/lock-signups")
def lock_signups(eventId):
    require_roles("EventDirector")
    ev = get_event_or_404(eventId)
    if ev["status"] != "PUBLISHED":
        raise errors.invalid_event_state("Lock-signups requires event status PUBLISHED.")
    _lock_event(ev)
    return success_object(serialize_event(ev))


@bp.post("/volunteer-ops/events/<eventId>/start-race-day")
def start_race_day(eventId):
    require_roles("EventDirector")
    ev = get_event_or_404(eventId)
    if ev["status"] != "LOCKED":
        raise errors.invalid_event_state("Start-race-day requires event status LOCKED.")
    now = logical_now()
    if now < parse_dt(ev["event_start_at"]):
        raise errors.event_not_yet_started()
    ev["status"] = "RACE_DAY"
    touch(ev)
    for shift in store.shifts.values():
        if shift["event_id"] == ev["id"] and shift["status"] == "LOCKED":
            shift["status"] = "IN_PROGRESS"
            touch(shift)
    return success_object(serialize_event(ev))


@bp.post("/volunteer-ops/events/<eventId>/complete")
def complete_event(eventId):
    require_roles("EventDirector")
    ev = get_event_or_404(eventId)
    if ev["status"] != "RACE_DAY":
        raise errors.invalid_event_state("Complete requires event status RACE_DAY.")
    now = logical_now()
    if now < parse_dt(ev["event_end_at"]):
        raise errors.event_not_yet_ended()
    still_on = any(
        su["event_id"] == ev["id"] and su["status"] == "CHECKED_IN"
        for su in store.signups.values()
    )
    if still_on:
        raise errors.signups_still_on_course()
    ev["status"] = "COMPLETED"
    touch(ev)
    return success_object(serialize_event(ev))


@bp.post("/volunteer-ops/events/<eventId>/open-debrief")
def open_debrief(eventId):
    require_roles("EventDirector")
    ev = get_event_or_404(eventId)
    if ev["status"] != "COMPLETED":
        raise errors.invalid_event_state("Open-debrief requires event status COMPLETED.")
    ev["status"] = "DEBRIEF_OPEN"
    touch(ev)
    return success_object(serialize_event(ev))


@bp.post("/volunteer-ops/events/<eventId>/close")
def close_event(eventId):
    require_roles("EventDirector")
    ev = get_event_or_404(eventId)
    if ev["status"] != "DEBRIEF_OPEN":
        raise errors.invalid_event_state("Close requires event status DEBRIEF_OPEN.")
    unresolved_logs = any(
        l["event_id"] == ev["id"] and l["status"] in {"PENDING_VERIFICATION", "DISPUTED"}
        for l in store.hour_logs.values()
    )
    submitted_debriefs = any(
        d["event_id"] == ev["id"] and d["status"] == "SUBMITTED"
        for d in store.debrief_reports.values()
    )
    open_adjustments = any(
        a["event_id"] == ev["id"] and a["status"] in {"PROPOSED", "APPROVED"}
        for a in store.role_adjustments.values()
    )
    unreconciled_shifts = any(
        s["event_id"] == ev["id"] and s["status"] not in {"RECONCILED", "CANCELLED"}
        for s in store.shifts.values()
    )
    if unresolved_logs or submitted_debriefs or open_adjustments or unreconciled_shifts:
        raise errors.event_close_blocked()
    ev["status"] = "CLOSED"
    touch(ev)
    return success_object(serialize_event(ev))


@bp.post("/volunteer-ops/events/<eventId>/cancel")
def cancel_event(eventId):
    require_roles("EventDirector")
    ev = get_event_or_404(eventId)
    if ev["status"] not in {"DRAFT", "PUBLISHED", "LOCKED", "RACE_DAY", "COMPLETED"}:
        raise errors.invalid_event_state("Event cannot be cancelled from its current status.")
    event_cancel_cascade(ev)
    ev["status"] = "CANCELLED"
    touch(ev)
    return success_object(serialize_event(ev))


@bp.post("/volunteer-ops/events/<eventId>/run-epoch-sweep")
def run_epoch_sweep(eventId):
    require_roles("EventDirector")
    ev = get_event_or_404(eventId)
    now = logical_now()

    # 1. Expire PASSED training records of this event past valid_until; cascade cancels
    expired_ids = []
    freed_signups = []
    for tr in list(store.training_records.values()):
        if tr["event_id"] != ev["id"] or tr["status"] != "PASSED":
            continue
        if tr.get("valid_until") and parse_dt(tr["valid_until"]) < now:
            tr["status"] = "EXPIRED"
            touch(tr)
            expired_ids.append(tr["id"])
            # cascade: cancel APPROVED|CONFIRMED signups of this volunteer whose shift's
            # role requires exactly this module
            for su in list(store.signups.values()):
                if (
                    su["volunteer_id"] == tr["volunteer_id"]
                    and su["status"] in {"APPROVED", "CONFIRMED"}
                ):
                    shift = store.shifts.get(su["shift_id"])
                    if shift is None:
                        continue
                    role = store.role_catalog_entries.get(shift["role_entry_id"])
                    if role and role["required_training_module"] == tr["module_code"]:
                        cancel_signup_record(su, fire_seat_open=False)
                        freed_signups.append(su)
    for su in freed_signups:
        shift = store.shifts.get(su["shift_id"])
        if shift is not None:
            seat_open_handling(shift, freed_signup=su)

    # 2. Auto-lock if PUBLISHED and now >= signup_closes_at
    auto_locked = False
    if ev["status"] == "PUBLISHED" and now >= parse_dt(ev["signup_closes_at"]):
        _lock_event(ev)
        auto_locked = True

    # 3. Cancel APPROVED signups whose confirm_by_at has passed; each freed seat
    # fires seat-open handling with the timed-out signup as the freed record.
    timed_out_ids = []
    timed_out_signups = []
    for su in list(store.signups.values()):
        if (
            su["event_id"] == ev["id"]
            and su["status"] == "APPROVED"
            and su.get("confirm_by_at")
            and parse_dt(su["confirm_by_at"]) < now
        ):
            cancel_signup_record(su, fire_seat_open=False)
            timed_out_ids.append(su["id"])
            timed_out_signups.append(su)
    for su in timed_out_signups:
        shift = store.shifts.get(su["shift_id"])
        if shift is not None:
            seat_open_handling(shift, freed_signup=su)

    return success_object({
        "expired_training_record_ids": expired_ids,
        "auto_locked": auto_locked,
        "timed_out_signup_ids": timed_out_ids,
    })
