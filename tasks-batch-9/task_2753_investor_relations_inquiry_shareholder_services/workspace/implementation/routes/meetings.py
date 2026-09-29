"""Meeting requests, the double-booking rule and slot release (PRD §3.8)."""
from datetime import timedelta

from flask import Blueprint

import calc
import validation as V
from envelope import created, ok, ok_list, paginate
from errors import ApiError
from serializers import meeting_request_out
from store import (CONTACT_BUFFER_MINUTES, MEETING_STATUSES, MIN_ALLOCATION_SCORE,
                   new_row, sorted_rows, store, touch)

bp = Blueprint("meetings", __name__)

BLOCKING_STATUSES = ("REQUESTED", "ALLOCATED", "WAITLISTED")


@bp.post("/meeting-requests")
def create_meeting_request():
    actor = V.authorize("Investor", "IRAdmin")
    b = V.body()
    event_id = V.f_str(b, "event_id", required=True)
    contact_id = V.f_str(b, "contact_id", required=True)
    slot_start = V.f_dt(b, "requested_slot_start", required=True)
    slot_end = V.f_dt(b, "requested_slot_end", required=True)

    # §2.10 step 5: contact_id precedes event_id in the canonical declaration order
    contact = V.get_contact(contact_id)
    event = V.get_event(event_id)

    V.own_contact(actor, contact_id)

    if event["status"] != "OPEN_FOR_REQUESTS":
        raise ApiError("ERR_EVENT_NOT_OPEN_FOR_REQUESTS",
                       "the event is not open for meeting requests")
    if contact["company_id"] != event["company_id"]:
        raise ApiError("ERR_CONTACT_COMPANY_MISMATCH",
                       "the requesting contact belongs to a different issuer")

    if slot_start < event["window_start"] or slot_end > event["window_end"]:
        raise ApiError("ERR_SLOT_OUT_OF_WINDOW",
                       "the requested slot must sit entirely inside the event window")
    minutes = (slot_end - slot_start).total_seconds() / 60.0
    if minutes != float(event["slot_minutes"]):
        raise ApiError("ERR_SLOT_DURATION_INVALID",
                       "the slot must be exactly %d minutes long" % event["slot_minutes"])

    buffer = timedelta(minutes=CONTACT_BUFFER_MINUTES)
    for other in sorted_rows(store.meeting_requests):
        if other["contact_id"] != contact["id"] or other["status"] not in BLOCKING_STATUSES:
            continue
        if (slot_start < other["requested_slot_end"] + buffer
                and other["requested_slot_start"] - buffer < slot_end):
            raise ApiError("ERR_CONTACT_DOUBLE_BOOKED",
                           "this contact already holds a meeting request within 30 minutes")

    meeting = new_row({
        "event_id": event["id"],
        "contact_id": contact["id"],
        "requested_slot_start": slot_start,
        "requested_slot_end": slot_end,
        "provisional_priority_score": calc.provisional_score(contact),
        "final_priority_score": None,
        "status": "REQUESTED",
        "allocated_at": None,
        "release_reason": None,
        "promoted_from_waitlist": False,
    })
    store.meeting_requests[meeting["id"]] = meeting
    calc.refresh_event_counters(event)
    touch(event)
    return created(meeting_request_out(meeting))


@bp.get("/meeting-requests")
def list_meeting_requests():
    V.authorize("IRAdmin", "IRAnalyst", "DisclosureOfficer", "Investor")
    limit, offset = V.q_pagination()
    event_id = V.q_str("event_id")
    contact_id = V.q_str("contact_id")
    status = V.q_enum("status", MEETING_STATUSES)
    rows = sorted_rows(store.meeting_requests)
    if event_id is not None:
        rows = [r for r in rows if r["event_id"] == event_id]
    if contact_id is not None:
        rows = [r for r in rows if r["contact_id"] == contact_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list([meeting_request_out(r) for r in page], limit, offset, total)


@bp.get("/meeting-requests/<meeting_id>")
def read_meeting_request(meeting_id):
    V.authorize("IRAdmin", "IRAnalyst", "DisclosureOfficer", "Investor")
    return ok(meeting_request_out(V.get_meeting_request(meeting_id)))


@bp.post("/meeting-requests/<meeting_id>/release")
def release_meeting_request(meeting_id):
    V.authorize("IRAdmin")
    b = V.body()
    reason = V.f_str(b, "reason", required=True)

    meeting = V.get_meeting_request(meeting_id)
    if meeting["status"] != "ALLOCATED":
        raise ApiError("ERR_MEETING_REQUEST_NOT_ALLOCATED",
                       "only an ALLOCATED request may be released")
    event = store.events.get(meeting["event_id"])
    if event is None or event["status"] != "LOCKED":
        raise ApiError("ERR_EVENT_INVALID_STATE", "the parent event must be LOCKED")

    # link 1 -- the request itself
    meeting["status"] = "RELEASED"
    meeting["release_reason"] = reason
    touch(meeting)

    # link 2 -- the event ledger; a slot is now free
    calc.refresh_event_counters(event)
    touch(event)

    # link 3 -- promote the highest-ranked eligible waitlisted request
    if event["allocated_count"] < event["capacity_slots"]:
        pool = [m for m in sorted_rows(store.meeting_requests)
                if m["event_id"] == event["id"] and m["status"] == "WAITLISTED"
                and m["final_priority_score"] is not None
                and m["final_priority_score"] >= MIN_ALLOCATION_SCORE]
        if pool:
            pool.sort(key=calc.allocation_rank_key)
            promoted = pool[0]
            promoted["status"] = "ALLOCATED"
            promoted["promoted_from_waitlist"] = True
            promoted["allocated_at"] = store.now()
            touch(promoted)
            calc.refresh_event_counters(event)
    return ok(meeting_request_out(meeting))
