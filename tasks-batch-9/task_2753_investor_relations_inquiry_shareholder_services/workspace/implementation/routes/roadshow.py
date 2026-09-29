"""Roadshow events and the allocation waterfall (PRD §3.8)."""
from flask import Blueprint

import calc
import validation as V
from envelope import created, ok, ok_list, paginate
from errors import ApiError
from serializers import event_out
from store import (EVENT_STATUSES, EVENT_TYPES, MIN_ALLOCATION_SCORE,
                   SLOT_MINUTES_ALLOWED, new_row, sorted_rows, store, touch)

bp = Blueprint("roadshow", __name__)


@bp.post("/roadshow-events")
def create_event():
    V.authorize("IRAdmin")
    b = V.body()
    company_id = V.f_str(b, "company_id", required=True)
    event_type = V.f_enum(b, "event_type", EVENT_TYPES, required=True)
    venue_city = V.f_str(b, "venue_city", required=True, max_len=80)
    window_start = V.f_dt(b, "window_start", required=True)
    window_end = V.f_dt(b, "window_end", required=True)
    slot_minutes = V.f_int(b, "slot_minutes", required=True)
    capacity_slots = V.f_int(b, "capacity_slots", required=True, minimum=1)
    if window_start >= window_end:
        V.bad("window_start must be strictly before window_end")
    if slot_minutes not in SLOT_MINUTES_ALLOWED:
        V.bad("slot_minutes must be one of 20, 30, 45, 60")

    company = V.get_company(company_id)

    event = new_row({
        "company_id": company["id"],
        "event_type": event_type,
        "venue_city": venue_city,
        "window_start": window_start,
        "window_end": window_end,
        "slot_minutes": slot_minutes,
        "capacity_slots": capacity_slots,
        "allocated_count": 0,
        "waitlisted_count": 0,
        "released_count": 0,
        "declined_count": 0,
        "request_ledger_total": 0,
        "status": "PLANNING",
    })
    store.events[event["id"]] = event
    return created(event_out(event))


@bp.get("/roadshow-events")
def list_events():
    V.authorize("IRAdmin", "IRAnalyst", "DisclosureOfficer", "Investor")
    limit, offset = V.q_pagination()
    company_id = V.q_str("company_id")
    event_type = V.q_enum("event_type", EVENT_TYPES)
    status = V.q_enum("status", EVENT_STATUSES)
    rows = sorted_rows(store.events)
    if company_id is not None:
        rows = [r for r in rows if r["company_id"] == company_id]
    if event_type is not None:
        rows = [r for r in rows if r["event_type"] == event_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list([event_out(r) for r in page], limit, offset, total)


@bp.get("/roadshow-events/<event_id>")
def read_event(event_id):
    V.authorize("IRAdmin", "IRAnalyst", "DisclosureOfficer", "Investor")
    return ok(event_out(V.get_event(event_id)))


@bp.post("/roadshow-events/<event_id>/open-requests")
def open_requests(event_id):
    V.authorize("IRAdmin")
    event = V.get_event(event_id)
    if event["status"] != "PLANNING":
        raise ApiError("ERR_EVENT_INVALID_STATE", "only a PLANNING event may be opened")
    event["status"] = "OPEN_FOR_REQUESTS"
    touch(event)
    return ok(event_out(event))


@bp.post("/roadshow-events/<event_id>/allocate")
def allocate(event_id):
    V.authorize("IRAdmin")
    event = V.get_event(event_id)

    if event["status"] != "OPEN_FOR_REQUESTS":
        raise ApiError("ERR_EVENT_INVALID_STATE",
                       "only an OPEN_FOR_REQUESTS event may be allocated")

    company = store.companies.get(event["company_id"])
    if company is not None and company["disclosure_posture"] == "BLACKOUT":
        raise ApiError("ERR_DISCLOSURE_BLACKOUT", "the issuer's disclosure posture is BLACKOUT")

    candidates = [m for m in sorted_rows(store.meeting_requests)
                  if m["event_id"] == event["id"] and m["status"] == "REQUESTED"]
    if not candidates:
        raise ApiError("ERR_NO_PENDING_REQUESTS", "this event has no request in REQUESTED")

    for m in candidates:
        contact = store.contacts.get(m["contact_id"])
        m["final_priority_score"] = calc.final_score(contact, m) if contact is not None else None

    eligible = [m for m in candidates
                if m["final_priority_score"] is not None
                and m["final_priority_score"] >= MIN_ALLOCATION_SCORE]
    eligible_ids = set(m["id"] for m in eligible)
    deferred = [m for m in candidates if m["id"] not in eligible_ids]
    eligible.sort(key=calc.allocation_rank_key)

    remaining = event["capacity_slots"] - event["allocated_count"]
    if remaining < 0:
        remaining = 0
    now = store.now()
    for index, m in enumerate(eligible):
        if index < remaining:
            m["status"] = "ALLOCATED"
            m["allocated_at"] = now
            m["promoted_from_waitlist"] = False
        else:
            m["status"] = "WAITLISTED"
        touch(m)
    for m in deferred:
        m["status"] = "WAITLISTED"
        touch(m)

    calc.refresh_event_counters(event)
    event["status"] = "LOCKED"
    touch(event)

    return ok({
        "event_id": event["id"],
        "event_status": event["status"],
        "evaluated_count": len(candidates),
        "allocated_count": event["allocated_count"],
        "waitlisted_count": event["waitlisted_count"],
        "threshold_deferred_count": len(deferred),
    })


@bp.post("/roadshow-events/<event_id>/complete")
def complete_event(event_id):
    V.authorize("IRAdmin")
    event = V.get_event(event_id)
    if event["status"] != "LOCKED":
        raise ApiError("ERR_EVENT_INVALID_STATE", "only a LOCKED event may be completed")

    event["status"] = "COMPLETED"
    touch(event)
    for m in sorted_rows(store.meeting_requests):
        if m["event_id"] == event["id"] and m["status"] == "WAITLISTED":
            m["status"] = "DECLINED"
            touch(m)
    calc.refresh_event_counters(event)
    return ok(event_out(event))
