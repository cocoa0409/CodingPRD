"""Field dispatch: technicians, availability slots, visits and fees (PRD 3.8)."""

from flask import Blueprint, request

import sla
import serializers as S
from counters import household_of_ticket, recompute_slot_counts
from envelope import created, ok, ok_list, paginate, read_pagination
from errors import ApiError
from firmware_svc import release_service_hold_rollouts
from ladder import (bad_request, begin, filter_enum, gates, in_force_subscription,
                    invalid_state, opt_str, plan_of, req_instant, req_region,
                    req_str, resolve, scope_household, scope_technician, touch,
                    ENUMS)
from money import (LATE_CANCEL_CUTOFF_HOURS, LATE_CANCEL_FEE_CENTS,
                   NO_SHOW_FEE_CENTS, TRAVEL_BUFFER_MINUTES)
from store import clock, db, new_row, sort_rows
from timeutil import add_hours, add_minutes, try_parse_instant

bp = Blueprint("dispatch", __name__)
PREFIX = "/smart-home-support"

SLOT_READ_ROLES = ("PlatformAdmin", "SupportAgent", "Technician", "Owner")


# --------------------------------------------------------------------------
# Technicians and slots
# --------------------------------------------------------------------------
@bp.post(PREFIX + "/technicians")
def register_technician():
    ctx = begin(("PlatformAdmin",))
    body = ctx.body
    full_name = req_str(body, "full_name", 1)
    region_code = req_region(body)
    skills = body.get("skills")
    if not isinstance(skills, list) or not skills:
        bad_request("skills must be a non-empty array.")
    for item in skills:
        if not isinstance(item, str):
            bad_request("Every element of skills must be a string.")
        if item not in ENUMS["skills"]:
            raise ApiError("ERR_INVALID_ENUM", "A skills element is outside its enumeration.")

    row = new_row()
    row.update({
        "full_name": full_name,
        "region_code": region_code,
        "skills": list(skills),
        "total_slot_count": 0,
        "open_slot_count": 0,
        "booked_slot_count": 0,
        "blocked_slot_count": 0,
    })
    db.technicians[row["id"]] = row
    return created(S.technician(row))


@bp.get(PREFIX + "/technicians/<tid>")
def read_technician(tid):
    ctx = begin(("PlatformAdmin", "SupportAgent", "Technician"))
    found = resolve(technician=tid)
    scope_technician(ctx, tid)
    return ok(S.technician(found["technician"]))


@bp.post(PREFIX + "/technicians/<tid>/visit-slots")
def publish_slot(tid):
    ctx = begin(("Technician", "PlatformAdmin"))
    found = resolve(technician=tid)
    technician = found["technician"]
    scope_technician(ctx, tid)
    start_raw, start_dt = req_instant(ctx.body, "start_at")
    end_raw, end_dt = req_instant(ctx.body, "end_at")
    if not end_dt > start_dt:
        bad_request("end_at must be strictly after start_at.")

    row = new_row()
    row.update({
        "technician_id": technician["id"],
        # The slot's region_code is COPIED from the owning technician; any
        # value supplied in the request is ignored (PRD 3.8).
        "region_code": technician["region_code"],
        # Caller-supplied instants, echoed verbatim (G2).
        "start_at": start_raw,
        "end_at": end_raw,
        "status": "OPEN",
    })
    db.visit_slots[row["id"]] = row
    recompute_slot_counts(technician)
    return created(S.visit_slot(row))


@bp.get(PREFIX + "/visit-slots")
def list_slots():
    begin(SLOT_READ_ROLES)
    limit, offset = read_pagination(request.args)
    status = filter_enum(request.args, "status", "slot_status")
    tid = request.args.get("technician_id")
    rows = []
    for row in db.visit_slots.values():
        if tid is not None and row.get("technician_id") != tid:
            continue
        if status is not None and row.get("status") != status:
            continue
        rows.append(row)
    page, total = paginate(sort_rows(rows), limit, offset)
    return ok_list([S.visit_slot(r) for r in page], limit, offset, total)


@bp.get(PREFIX + "/visit-slots/<sid>")
def read_slot(sid):
    ctx = begin(SLOT_READ_ROLES)
    found = resolve(slot=sid)
    slot = found["slot"]
    scope_technician(ctx, slot.get("technician_id"))
    return ok(S.visit_slot(slot))


# --------------------------------------------------------------------------
# The travel-buffer rule
# --------------------------------------------------------------------------
def _buffer_conflict(candidate, exclude_slot_ids=()):
    """A candidate slot conflicts with an already-BOOKED slot of the SAME
    technician when the booked slot's start moved 45 minutes earlier is
    strictly before the candidate's end AND the candidate's start is strictly
    before the booked slot's end moved 45 minutes later.  Both comparisons are
    strict, so exact buffer adjacency is legal."""
    c_start = try_parse_instant(candidate["start_at"])
    c_end = try_parse_instant(candidate["end_at"])
    for booked in db.visit_slots.values():
        if booked["id"] == candidate["id"] or booked["id"] in exclude_slot_ids:
            continue
        if booked.get("technician_id") != candidate.get("technician_id"):
            continue
        if booked.get("status") != "BOOKED":
            continue
        b_start = try_parse_instant(booked["start_at"])
        b_end = try_parse_instant(booked["end_at"])
        if (add_minutes(b_start, -TRAVEL_BUFFER_MINUTES) < c_end
                and c_start < add_minutes(b_end, TRAVEL_BUFFER_MINUTES)):
            return True
    return False


def _check_slot_rungs(ticket_household, slot):
    # Rung 41 -- region.
    if slot.get("region_code") != ticket_household.get("region_code"):
        raise ApiError("ERR_SLOT_REGION_MISMATCH")
    # Rung 42 -- availability.
    if slot.get("status") != "OPEN":
        raise ApiError("ERR_SLOT_UNAVAILABLE")
    # Rung 43 -- the travel buffer.
    if _buffer_conflict(slot):
        raise ApiError("ERR_SLOT_BUFFER_CONFLICT")


# --------------------------------------------------------------------------
# Visits
# --------------------------------------------------------------------------
@bp.post(PREFIX + "/visits")
def book_visit():
    ctx = begin(("SupportAgent",))
    body = ctx.body
    found = resolve(ticket=body.get("ticket_id"), slot=body.get("slot_id"))
    ticket = found.get("ticket")
    slot = found.get("slot")
    if ticket is None:
        bad_request("Field 'ticket_id' must be a non-empty string.")
    if slot is None:
        bad_request("Field 'slot_id' must be a non-empty string.")
    household = household_of_ticket(ticket)
    gates(household=household, ticket=ticket)

    # Rung 27 is EXEMPT here: a ticket that is simply not dispatch-ready is
    # reported by rung 40 instead, which is what keeps that rung reachable for
    # tickets still in NEW, TRIAGED or REMOTE_DIAG.
    if ticket.get("dispatch_status") not in ("REQUIRED", "RESCHEDULING", "NO_SHOW"):
        raise ApiError("ERR_DISPATCH_NOT_REQUIRED")
    _check_slot_rungs(household, slot)

    technician = db.technicians.get(slot.get("technician_id"))
    row = new_row()
    row.update({
        "ticket_id": ticket["id"],
        "slot_id": slot["id"],
        "status": "SCHEDULED",
        # Copied verbatim from the occupied slot (G2).
        "scheduled_start_at": slot["start_at"],
        "scheduled_end_at": slot["end_at"],
        "cancelled_at": None,
        "fee_kind": "NONE",
        "fee_cents": 0,
        "fee_waived": False,
        "completion_notes": None,
    })
    db.visits[row["id"]] = row
    slot["status"] = "BOOKED"
    touch(slot)
    recompute_slot_counts(technician)
    ticket["workflow_status"] = "ONSITE"
    ticket["dispatch_status"] = "SCHEDULED"
    touch(ticket)
    return created(S.visit(row))


@bp.get(PREFIX + "/visits")
def list_visits():
    begin(SLOT_READ_ROLES)
    limit, offset = read_pagination(request.args)
    tid = request.args.get("ticket_id")
    sid = request.args.get("slot_id")
    rows = []
    for row in db.visits.values():
        if tid is not None and row.get("ticket_id") != tid:
            continue
        if sid is not None and row.get("slot_id") != sid:
            continue
        rows.append(row)
    page, total = paginate(sort_rows(rows), limit, offset)
    return ok_list([S.visit(r) for r in page], limit, offset, total)


def _visit_scope(ctx, visit):
    slot = db.visit_slots.get(visit.get("slot_id"))
    ticket = db.tickets.get(visit.get("ticket_id"))
    scope_technician(ctx, slot.get("technician_id") if slot else None)
    scope_household(ctx, ticket.get("household_id") if ticket else None)
    return slot, ticket


@bp.get(PREFIX + "/visits/<vid>")
def read_visit(vid):
    ctx = begin(SLOT_READ_ROLES)
    found = resolve(visit=vid)
    visit = found["visit"]
    _visit_scope(ctx, visit)
    return ok(S.visit(visit))


@bp.post(PREFIX + "/visits/<vid>/reschedule")
def reschedule_visit(vid):
    ctx = begin(("SupportAgent",))
    body = ctx.body
    found = resolve(slot=body.get("new_slot_id"), visit=vid)
    new_slot = found.get("slot")
    visit = found["visit"]
    if new_slot is None:
        bad_request("Field 'new_slot_id' must be a non-empty string.")
    old_slot, ticket = _visit_scope(ctx, visit)
    household = household_of_ticket(ticket)
    gates(household=household, ticket=ticket)

    if visit.get("status") != "SCHEDULED":
        invalid_state("Only a SCHEDULED visit may be rescheduled.")
    _check_slot_rungs(household, new_slot)

    # Adjudication of friction 1: READING A -- the vacated slot is released to
    # OPEN unconditionally.  The endpoint's own effect ("The vacated slot is
    # released to OPEN") is stated without qualification, no error code is
    # nominated anywhere for a late reschedule, and Reading B would either
    # invent an unstated BLOCKED effect or make late rescheduling impossible.
    # Reading A keeps every declared effect of the endpoint reachable and is
    # the only reading that preserves slot-capacity conservation on this path.
    if old_slot is not None:
        old_slot["status"] = "OPEN"
        touch(old_slot)
    new_slot["status"] = "BOOKED"
    touch(new_slot)
    visit["slot_id"] = new_slot["id"]
    visit["scheduled_start_at"] = new_slot["start_at"]
    visit["scheduled_end_at"] = new_slot["end_at"]
    touch(visit)
    recompute_slot_counts(db.technicians.get(old_slot.get("technician_id")) if old_slot else None)
    recompute_slot_counts(db.technicians.get(new_slot.get("technician_id")))
    return ok(S.visit(visit))


@bp.post(PREFIX + "/visits/<vid>/cancel")
def cancel_visit(vid):
    ctx = begin(("SupportAgent", "Owner"))
    found = resolve(visit=vid)
    visit = found["visit"]
    slot, ticket = _visit_scope(ctx, visit)
    household = household_of_ticket(ticket)
    gates(household=household, ticket=ticket)

    if visit.get("status") != "SCHEDULED":
        invalid_state("Only a SCHEDULED visit may be cancelled.")

    start = try_parse_instant(visit["scheduled_start_at"])
    cutoff = add_hours(start, -LATE_CANCEL_CUTOFF_HOURS)
    now = clock.now()
    subscription = in_force_subscription(ticket["household_id"]) if ticket else None
    plan = plan_of(subscription) if subscription is not None else None

    if now <= cutoff:
        # Early cancellation: no fee, and the slot returns to OPEN.
        visit["fee_kind"] = "NONE"
        visit["fee_cents"] = 0
        visit["fee_waived"] = False
        if slot is not None:
            slot["status"] = "OPEN"
            touch(slot)
    else:
        # Late cancellation.  The PRO waiver applies here and only here.
        visit["fee_kind"] = "LATE_CANCEL"
        if plan is not None and plan.get("tier") == "PRO":
            visit["fee_waived"] = True
            visit["fee_cents"] = 0
        else:
            visit["fee_waived"] = False
            visit["fee_cents"] = LATE_CANCEL_FEE_CENTS
        if slot is not None:
            slot["status"] = "BLOCKED"
            touch(slot)
    if subscription is not None:
        subscription["next_invoice_adjustment_cents"] = (
            subscription.get("next_invoice_adjustment_cents") or 0) + visit["fee_cents"]

    visit["cancelled_at"] = clock.now_iso()
    visit["status"] = "CANCELLED"
    touch(visit)
    if slot is not None:
        recompute_slot_counts(db.technicians.get(slot.get("technician_id")))
    if ticket is not None:
        ticket["workflow_status"] = "DISPATCH_PENDING"
        ticket["dispatch_status"] = "RESCHEDULING"
        touch(ticket)
    return ok(S.visit(visit))


@bp.post(PREFIX + "/visits/<vid>/complete")
def complete_visit(vid):
    ctx = begin(("Technician",))
    found = resolve(visit=vid)
    visit = found["visit"]
    slot, ticket = _visit_scope(ctx, visit)
    household = household_of_ticket(ticket)
    completion_notes = opt_str(ctx.body, "completion_notes")
    gates(household=household, ticket=ticket)

    if visit.get("status") != "SCHEDULED":
        invalid_state("Only a SCHEDULED visit may be completed.")
    # Rung 44 -- the clock must be at or after scheduled_start_at.
    if clock.now() < try_parse_instant(visit["scheduled_start_at"]):
        raise ApiError("ERR_VISIT_NOT_STARTED")

    visit["status"] = "COMPLETED"
    if completion_notes is not None:
        visit["completion_notes"] = completion_notes
    # The occupied slot STAYS BOOKED -- a completed visit does not free capacity.
    touch(visit)

    if ticket is not None:
        ticket["workflow_status"] = "RESOLVED"
        ticket["dispatch_status"] = "COMPLETED"
        ticket["resolved_at"] = clock.now_iso()
        if ticket.get("survey_solicited_at") is None:
            ticket["survey_solicited_at"] = ticket["resolved_at"]
        sla.settle_met(ticket)
        touch(ticket)
        device = db.devices.get(ticket.get("device_id")) if ticket.get("device_id") else None
        if device is not None and device.get("lifecycle_status") == "SERVICE_HOLD":
            device["lifecycle_status"] = "ACTIVE"
            release_service_hold_rollouts(device)
            touch(device)
    return ok(S.visit(visit))


@bp.post(PREFIX + "/visits/<vid>/no-show")
def no_show_visit(vid):
    ctx = begin(("Technician",))
    found = resolve(visit=vid)
    visit = found["visit"]
    slot, ticket = _visit_scope(ctx, visit)
    household = household_of_ticket(ticket)
    gates(household=household, ticket=ticket)

    if visit.get("status") != "SCHEDULED":
        invalid_state("Only a SCHEDULED visit may be reported as a no-show.")
    # Rung 44 -- there is no cutoff test at all, only the start-time rung.
    if clock.now() < try_parse_instant(visit["scheduled_start_at"]):
        raise ApiError("ERR_VISIT_NOT_STARTED")

    # The PRO waiver does NOT apply to no-shows.
    visit["fee_kind"] = "NO_SHOW"
    visit["fee_cents"] = NO_SHOW_FEE_CENTS
    visit["fee_waived"] = False
    visit["status"] = "NO_SHOW"
    touch(visit)
    subscription = in_force_subscription(ticket["household_id"]) if ticket else None
    if subscription is not None:
        subscription["next_invoice_adjustment_cents"] = (
            subscription.get("next_invoice_adjustment_cents") or 0) + NO_SHOW_FEE_CENTS
    if slot is not None:
        slot["status"] = "BLOCKED"
        touch(slot)
        recompute_slot_counts(db.technicians.get(slot.get("technician_id")))
    if ticket is not None:
        ticket["workflow_status"] = "DISPATCH_PENDING"
        ticket["dispatch_status"] = "NO_SHOW"
        touch(ticket)
    return ok(S.visit(visit))
