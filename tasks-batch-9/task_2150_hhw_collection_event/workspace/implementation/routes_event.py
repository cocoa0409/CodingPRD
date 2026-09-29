"""Collection event endpoints: both state axes (PRD §3.3, §3.6)."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import serializers
from calc import ZERO, hours_between
from cascades import (
    append_finding,
    cancel_event_cascade,
    close_event_sweep,
    containment_deficiency_cascade,
    waitlist_promotion_sweep,
)
from common import gate_frozen, gate_restricted, list_response
from envelope import ok
from errors import ApiError
from rollups import (
    containers_of_event,
    events_of_site,
    live_open_lane_count,
    manifests_of_event,
    refresh_world,
)
from store import clock_dt, new_row, set_and_touch, store
from validation import (
    ALL_READ_ROLES,
    authorize,
    body,
    context,
    lookup,
    opt_int,
    opt_str,
    req_dt,
    req_enum,
    req_str,
)

bp = Blueprint("events", __name__)

LIFECYCLE_TRANSITIONS = {
    "CONFIRM_SITE": {"PLANNED": "SITE_CONFIRMED"},
    "OPEN_REGISTRATION": {"SITE_CONFIRMED": "OPEN_FOR_REGISTRATION"},
    "START": {"OPEN_FOR_REGISTRATION": "IN_PROGRESS"},
    "CLOSE": {"IN_PROGRESS": "CLOSED"},
    "RECONCILE": {"CLOSED": "RECONCILED"},
    "CANCEL": {
        "PLANNED": "CANCELLED",
        "SITE_CONFIRMED": "CANCELLED",
        "OPEN_FOR_REGISTRATION": "CANCELLED",
    },
}

CONTAINMENT_TRANSITIONS = {
    ("PENDING_INSPECTION", "PASS"): "COMPLIANT",
    ("PENDING_INSPECTION", "FAIL"): "DEFICIENT",
    ("COMPLIANT", "FAIL"): "DEFICIENT",
    ("DEFICIENT", "PASS"): "REMEDIATED",
    ("REMEDIATED", "PASS"): "COMPLIANT",
    ("REMEDIATED", "FAIL"): "DEFICIENT",
}


@bp.post("/hhw/events")
def create_event():
    user_id, role = context()
    authorize(role, ["EventCoordinator"])
    payload = body()
    program_id = req_str(payload, "program_id")
    site_id = req_str(payload, "site_id")
    window_start = req_dt(payload, "window_start_utc")
    window_end = req_dt(payload, "window_end_utc")
    min_viable = opt_int(payload, "min_viable_registrations", default=20, minimum=0)
    if window_end <= window_start:
        raise ApiError("ERR_INVALID_REQUEST",
                       "window_end_utc must be strictly after window_start_utc.")
    if window_start.date() != window_end.date():
        raise ApiError("ERR_INVALID_REQUEST",
                       "The collection window must fall on one UTC calendar date.")

    program = lookup("program", program_id)
    site = lookup("site", site_id)

    if site["status"] != "APPROVED":                                   # rung 11
        raise ApiError("ERR_SITE_NOT_APPROVED")
    gate_frozen(program)                                               # rung 14

    event_date = window_start.date().isoformat()

    # Rung 24 — closed window against every existing band, widened 48h each side.
    buffer_delta = timedelta(seconds=calc.SITE_BUFFER_SECONDS)
    for existing in events_of_site(site["id"]):
        if existing["lifecycle_status"] == "CANCELLED":
            continue
        band_start = existing["_window_start_dt"] - buffer_delta
        band_end = existing["_window_end_dt"] + buffer_delta
        if window_start <= band_end and window_end >= band_start:
            raise ApiError("ERR_SITE_INTERVAL_CONFLICT")

    # Rung 25 — at most two non-cancelled events per UTC calendar month.
    month = event_date[:7]
    same_month = 0
    for existing in events_of_site(site["id"]):
        if existing["lifecycle_status"] == "CANCELLED":
            continue
        if existing["event_date"][:7] == month:
            same_month += 1
    if same_month >= calc.SITE_MONTHLY_EVENT_CAP:
        raise ApiError("ERR_SITE_MONTHLY_EVENT_CAP")

    row = new_row({
        "program_id": program["id"],
        "site_id": site["id"],
        "window_start_utc": payload["window_start_utc"],
        "window_end_utc": payload["window_end_utc"],
        "_window_start_dt": window_start,
        "_window_end_dt": window_end,
        "min_viable_registrations": min_viable,
        "event_date": event_date,
        "window_duration_hours": hours_between(window_start, window_end),
        "lifecycle_status": "PLANNED",
        "containment_status": "PENDING_INSPECTION",
        "containment_findings": [],
        "open_lane_count": 0,
        "certified_staff_hours": ZERO,
        "staffing_cost_cents": 0,
        "slot_capacity": 0,
        "reserved_slot_count": 0,
        "participant_count": 0,
        "accepted_tonnage_kg": ZERO,
        "rejected_tonnage_kg": ZERO,
        "tonnage_reported_kg": ZERO,
        "projected_cost_per_participant_cents": 0,
        "discrepancy_container_count": 0,
        "cancel_reason": None,
        "_queue_seq": 0,
    })
    store.events[row["id"]] = row
    refresh_world()
    return ok(serializers.collection_event(row), 201)


@bp.get("/hhw/events")
def list_events():
    user_id, role = context()
    authorize(role, ALL_READ_ROLES)
    filters = {
        "program_id": request.args.get("program_id"),
        "site_id": request.args.get("site_id"),
        "lifecycle_status": request.args.get("lifecycle_status"),
        "containment_status": request.args.get("containment_status"),
    }
    return list_response(request.args, list(store.events.values()),
                         serializers.collection_event, filters)


@bp.get("/hhw/events/<event_id>")
def read_event(event_id):
    user_id, role = context()
    authorize(role, ALL_READ_ROLES)
    return ok(serializers.collection_event(lookup("event", event_id)))


@bp.post("/hhw/events/<event_id>/transitions")
def event_transition(event_id):
    user_id, role = context()
    authorize(role, ["EventCoordinator"])
    payload = body()
    action = req_enum(payload, "action", list(LIFECYCLE_TRANSITIONS.keys()))
    cancel_reason = opt_str(payload, "cancel_reason")

    event = lookup("event", event_id)
    program = store.programs.get(event["program_id"])
    site = store.sites.get(event["site_id"])
    from_status = event["lifecycle_status"]

    target = LIFECYCLE_TRANSITIONS[action].get(from_status)              # rung 9
    if target is None:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    if action == "CONFIRM_SITE":
        if site is None or site["status"] != "APPROVED":                 # rung 11
            raise ApiError("ERR_SITE_NOT_APPROVED")
        gate_frozen(program)                                             # rung 14
        set_and_touch(event, lifecycle_status="SITE_CONFIRMED")

    elif action == "OPEN_REGISTRATION":
        # PRD §3.3 states the requirements in this order: the containment axis
        # must read exactly COMPLIANT, the clock must still be before the
        # window start, and the posture must be fully OPEN.
        if event["containment_status"] != "COMPLIANT":                   # rung 12
            raise ApiError("ERR_CONTAINMENT_DEFICIENT")
        if clock_dt() >= event["_window_start_dt"]:                      # rung 9
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "The collection window has already started.")
        gate_frozen(program)                                             # rung 14
        gate_restricted(program)                                         # rung 15
        set_and_touch(event, lifecycle_status="OPEN_FOR_REGISTRATION")

    elif action == "START":
        if clock_dt() < event["_window_start_dt"]:                       # rung 9
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "The collection window has not started yet.")
        if event["containment_status"] not in ("COMPLIANT", "REMEDIATED"):
            raise ApiError("ERR_CONTAINMENT_DEFICIENT")                  # rung 12
        if live_open_lane_count(event) < 1:                              # rung 9
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "No lane is staffed.")
        set_and_touch(event, lifecycle_status="IN_PROGRESS")

    elif action == "CLOSE":
        if clock_dt() < event["_window_end_dt"]:                         # rung 9
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "The collection window has not closed yet.")
        set_and_touch(event, lifecycle_status="CLOSED")
        close_event_sweep(event)

    elif action == "RECONCILE":
        for manifest in manifests_of_event(event["id"]):
            if manifest["status"] not in ("RECEIVED", "VOIDED"):
                raise ApiError("ERR_INVALID_STATE_TRANSITION",
                               "A manifest of this event is still open.")
        for container in containers_of_event(event["id"]):
            if container["status"] == "DISPOSED":
                continue
            if container["status"] == "OPEN" and container["line_count"] == 0:
                continue
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "A container of this event is not settled.")
        if event["discrepancy_container_count"] != 0:
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "The event still carries a flagged container.")
        set_and_touch(event, lifecycle_status="RECONCILED")

    else:  # CANCEL
        set_and_touch(event, lifecycle_status="CANCELLED",
                      cancel_reason=cancel_reason)
        cancel_event_cascade(event, from_status)

    refresh_world()
    return ok(serializers.collection_event(event))


@bp.post("/hhw/events/<event_id>/containment-inspections")
def containment_inspection(event_id):
    user_id, role = context()
    authorize(role, ["ContainmentInspector"])
    payload = body()
    result = req_enum(payload, "result", ["PASS", "FAIL"])
    finding_code = opt_str(payload, "finding_code")
    opt_str(payload, "remediation_note")

    event = lookup("event", event_id)
    site = store.sites.get(event["site_id"])

    # Rung 7 — segregation of duties.
    if site is not None and site["approved_by_user_id"] is not None:
        if site["approved_by_user_id"] == user_id:
            raise ApiError("ERR_INSPECTOR_NOT_INDEPENDENT")

    # Rung 9 — the lifecycle axis must not be terminal, and the containment
    # transition must be declared.
    if event["lifecycle_status"] in ("RECONCILED", "CANCELLED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    target = CONTAINMENT_TRANSITIONS.get((event["containment_status"], result))
    if target is None:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    event["containment_status"] = target
    append_finding(event, "EVENT", result, finding_code, user_id)
    set_and_touch(event)

    if target == "DEFICIENT":
        containment_deficiency_cascade(event)
    else:
        # Entering REMEDIATED or COMPLIANT recomputes slot_capacity and runs the
        # waitlist promotion sweep.
        waitlist_promotion_sweep(event)

    refresh_world()
    return ok(serializers.collection_event(event))
