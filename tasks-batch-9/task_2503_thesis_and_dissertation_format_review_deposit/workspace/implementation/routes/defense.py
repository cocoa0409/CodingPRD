"""Booking, announcing, holding and cancelling the defense (PRD section 3.4)."""

import lookup
import serializers
import validate
from db import db, new_row, write
from errors import fail
from flask import Blueprint
from logical_clock import clock
from middleware import endpoint
from response import array_response, object_response
from routes import common
from routes.common import ALL_ROLES, PREFIX
from services import calc, counters
from services.clearance import recompute_for_thesis
from timeutil import whole_minutes

bp = Blueprint("defense", __name__, url_prefix=PREFIX)

EVENT_STATUSES = (
    "DRAFT",
    "ANNOUNCED",
    "HELD_PASS",
    "HELD_PASS_WITH_REVISIONS",
    "HELD_FAIL",
    "CANCELLED",
)

OUTCOMES = ("PASS", "PASS_WITH_REVISIONS", "FAIL")

OUTCOME_EVENT_STATUS = {
    "PASS": "HELD_PASS",
    "PASS_WITH_REVISIONS": "HELD_PASS_WITH_REVISIONS",
    "FAIL": "HELD_FAIL",
}

OUTCOME_THESIS_STATE = {
    "PASS": "DEFENSE_PASSED",
    "PASS_WITH_REVISIONS": "DEFENSE_PASSED_WITH_REVISIONS",
    "FAIL": "DEFENSE_FAILED",
}


def _thesis_of(event):
    return db.theses.get(event["thesis_id"])


def _confirmed_faculty_ids(thesis_id):
    committee = lookup.committee_of_thesis(thesis_id)
    if committee is None:
        return set()
    return {seat["faculty_id"] for seat in lookup.confirmed_seats(committee["id"])}


# --------------------------------------------------------------------- reads


@bp.get("/defense-events/<event_id>")
@endpoint(ALL_ROLES)
def read_event(user_id, role, event_id):
    return object_response(
        serializers.defense_event(lookup.get_defense_event(event_id))
    )


@bp.get("/defense-events")
@endpoint(ALL_ROLES)
def list_events(user_id, role):
    limit, offset = validate.pagination()
    thesis_id = validate.query_str("thesis_id")
    room_id = validate.query_str("room_id")
    status = validate.query_enum("status", EVENT_STATUSES)

    rows = list(db.defense_events.values())
    if thesis_id is not None:
        rows = [r for r in rows if r["thesis_id"] == thesis_id]
    if room_id is not None:
        rows = [r for r in rows if r["room_id"] == room_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]

    rows = sorted(rows, key=lambda r: (r["scheduled_start"], r["created_at"], r["_seq"]))
    page, total = validate.paginate(rows, limit, offset)
    return array_response(
        [serializers.defense_event(row) for row in page], limit, offset, total
    )


# -------------------------------------------------------------------- writes


@bp.post("/defense-events")
@endpoint(["Student", "GradSchoolAnalyst"])
def schedule_defense(user_id, role):
    body = validate.get_body()
    thesis_id = validate.req_str(body, "thesis_id")
    room_id = validate.req_str(body, "room_id")
    scheduled_start = validate.req_datetime(body, "scheduled_start")
    scheduled_end = validate.req_datetime(body, "scheduled_end")

    thesis = lookup.get_thesis(thesis_id)
    room = lookup.get_room(room_id)

    common.require_owner(role, user_id, thesis)
    common.require_term_open(thesis)

    if thesis["workflow_state"] != "COMMITTEE_APPROVED":
        fail(
            "ERR_THESIS_STATE_INVALID",
            "A defense may only be booked while the document is COMMITTEE_APPROVED",
        )

    committee = lookup.committee_of_thesis(thesis["id"])
    common.require_committee_state(
        committee,
        ("APPROVED",),
        "A defense may only be booked once the committee is APPROVED",
    )

    # Stage 14: ERR_ROOM_UNAVAILABLE, then ERR_ROOM_BOOKING_CONFLICT, then
    # ERR_FACULTY_SCHEDULE_CONFLICT.
    minutes = whole_minutes(scheduled_start, scheduled_end)
    if room["status"] == "MAINTENANCE":
        fail("ERR_ROOM_UNAVAILABLE", "Room '%s' is under MAINTENANCE" % room["code"])
    if minutes < calc.MIN_DEFENSE_MINUTES or minutes > calc.MAX_DEFENSE_MINUTES:
        fail(
            "ERR_ROOM_UNAVAILABLE",
            "The occupation must last between %d and %d minutes"
            % (calc.MIN_DEFENSE_MINUTES, calc.MAX_DEFENSE_MINUTES),
        )

    for existing in lookup.events_of_room(room["id"]):
        if existing["status"] not in calc.COUNTED_EVENT_STATUSES:
            continue
        if calc.room_overlap(
            scheduled_start,
            scheduled_end,
            existing["scheduled_start"],
            existing["scheduled_end"],
            room["turnover_buffer_minutes"],
        ):
            fail(
                "ERR_ROOM_BOOKING_CONFLICT",
                "Room '%s' is occupied within its turnover buffer" % room["code"],
            )

    seated = _confirmed_faculty_ids(thesis["id"])
    if seated:
        for existing in db.defense_events.values():
            if existing["status"] not in ("DRAFT", "ANNOUNCED"):
                continue
            if not calc.faculty_overlap(
                scheduled_start,
                scheduled_end,
                existing["scheduled_start"],
                existing["scheduled_end"],
            ):
                continue
            if seated & _confirmed_faculty_ids(existing["thesis_id"]):
                fail(
                    "ERR_FACULTY_SCHEDULE_CONFLICT",
                    "A confirmed committee member is already committed to another "
                    "defense in that interval",
                )

    # Stage 15: ERR_DEFENSE_START_IN_PAST, then ERR_DEFENSE_AFTER_TERM_DEADLINE.
    if scheduled_start <= clock.now():
        fail(
            "ERR_DEFENSE_START_IN_PAST",
            "scheduled_start must be strictly after the current logical instant",
        )
    term = common.term_of(thesis)
    if term is not None and scheduled_start > term["defense_deadline"]:
        fail(
            "ERR_DEFENSE_AFTER_TERM_DEADLINE",
            "scheduled_start is later than the term's defense_deadline",
        )

    row = new_row(
        thesis_id=thesis["id"],
        room_id=room["id"],
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
        status="DRAFT",
        announced_at=None,
        announcement_lead_bdays=None,
        outcome_note=None,
        cancellation_reason=None,
    )
    db.defense_events[row["id"]] = row

    write(thesis, workflow_state="DEFENSE_SCHEDULED")
    counters.recompute_room(room["id"])
    recompute_for_thesis(thesis)

    return object_response(serializers.defense_event(row), 201)


@bp.post("/defense-events/<event_id>/announce")
@endpoint(["GradSchoolAnalyst"])
def announce_defense(user_id, role, event_id):
    event = lookup.get_defense_event(event_id)
    thesis = _thesis_of(event)
    if thesis is not None:
        common.require_term_open(thesis)

    if event["status"] != "DRAFT":
        fail(
            "ERR_DEFENSE_STATE_INVALID",
            "Only a DRAFT defense may be announced",
        )

    lead = calc.defense_announcement_lead(clock.now(), event["scheduled_start"])
    term = common.term_of(thesis) if thesis is not None else None
    required = term["announcement_lead_business_days"] if term is not None else 0
    if lead < required:
        fail(
            "ERR_ANNOUNCEMENT_LEAD_TOO_SHORT",
            "The announcement lead of %d business days is shorter than the required %d"
            % (lead, required),
        )

    write(
        event,
        status="ANNOUNCED",
        announced_at=clock.now(),
        announcement_lead_bdays=lead,
    )
    if thesis is not None:
        write(thesis, workflow_state="DEFENSE_ANNOUNCED")
        recompute_for_thesis(thesis)
    return object_response(serializers.defense_event(event))


@bp.post("/defense-events/<event_id>/outcome")
@endpoint(["FacultyMember"])
def record_outcome(user_id, role, event_id):
    event = lookup.get_defense_event(event_id)
    body = validate.get_body()
    outcome = validate.req_enum(body, "outcome", OUTCOMES)
    outcome_note = validate.opt_str(body, "outcome_note")

    thesis = _thesis_of(event)
    committee = (
        lookup.committee_of_thesis(thesis["id"]) if thesis is not None else None
    )

    # Stage 7: only the CONFIRMED CHAIR of the APPROVED committee may record.
    chair_id = None
    if committee is not None and committee["status"] == "APPROVED":
        for seat in lookup.confirmed_seats(committee["id"]):
            if seat["role"] == "CHAIR":
                chair_id = seat["faculty_id"]
                break
    if chair_id is None or chair_id != user_id:
        fail(
            "ERR_NOT_COMMITTEE_CHAIR",
            "Only the confirmed chair of the approved committee may record the outcome",
        )

    if thesis is not None:
        common.require_term_open(thesis)

    if event["status"] != "ANNOUNCED":
        fail(
            "ERR_DEFENSE_STATE_INVALID",
            "Only an ANNOUNCED defense may carry an outcome",
        )
    if clock.now() < event["scheduled_end"]:
        fail(
            "ERR_DEFENSE_STATE_INVALID",
            "The outcome cannot be recorded before the defense has ended",
        )

    write(
        event,
        status=OUTCOME_EVENT_STATUS[outcome],
        outcome_note=outcome_note,
    )
    if thesis is not None:
        write(thesis, workflow_state=OUTCOME_THESIS_STATE[outcome])

    if outcome == "FAIL" and committee is not None:
        write(committee, status="DISSOLVED")
        counters.recompute_all_chair_loads()

    counters.recompute_room(event["room_id"])
    if thesis is not None:
        recompute_for_thesis(thesis)
    return object_response(serializers.defense_event(event))


@bp.post("/defense-events/<event_id>/cancel")
@endpoint(["GradSchoolAnalyst", "Student"])
def cancel_defense(user_id, role, event_id):
    event = lookup.get_defense_event(event_id)
    body = validate.get_body()
    reason = validate.req_str(body, "cancellation_reason", allow_empty=False)

    thesis = _thesis_of(event)
    if thesis is not None:
        common.require_owner(role, user_id, thesis)
        common.require_term_open(thesis)

    if event["status"] not in ("DRAFT", "ANNOUNCED"):
        fail(
            "ERR_DEFENSE_STATE_INVALID",
            "Only a DRAFT or ANNOUNCED defense may be cancelled",
        )

    write(event, status="CANCELLED", cancellation_reason=reason)
    if thesis is not None:
        write(thesis, workflow_state="COMMITTEE_APPROVED")
    counters.recompute_room(event["room_id"])
    if thesis is not None:
        recompute_for_thesis(thesis)
    return object_response(serializers.defense_event(event))
