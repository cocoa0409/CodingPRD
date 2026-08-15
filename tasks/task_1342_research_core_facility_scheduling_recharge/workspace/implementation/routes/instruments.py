"""Instruments (PRD §3.2)."""

from flask import Blueprint, request

from auth import authenticate, require_roles
from errors import fail
from helpers import (
    Body, validate_body, non_empty_str, is_int, is_num,
    system_cancel, system_reject, event_contains_now, ser_instrument,
)
from store import store, now
from util import new_entity, ok_object, parse_pagination, paginate, sort_default, touch

bp = Blueprint("instruments", __name__)


def get_instrument_or_404(iid):
    inst = store.instruments.get(iid)
    if inst is None:
        fail("ERR_NOT_FOUND", "Instrument not found")
    return inst


@bp.route("/instruments", methods=["POST"])
def create_instrument():
    authenticate()
    require_roles("FacilityAdmin")
    body = Body(request.get_json(silent=True))
    validate_body(
        body,
        allowed={"name", "model", "location", "requires_training", "booking_buffer_minutes",
                 "min_booking_minutes", "max_booking_minutes", "cancellation_free_notice_hours",
                 "late_cancel_penalty_pct", "no_show_penalty_pct"},
        required={"name", "model", "location", "min_booking_minutes", "max_booking_minutes",
                  "cancellation_free_notice_hours", "late_cancel_penalty_pct", "no_show_penalty_pct"},
        checkers={
            "name": non_empty_str,
            "model": non_empty_str,
            "location": non_empty_str,
            "requires_training": lambda v: isinstance(v, bool),
            "booking_buffer_minutes": lambda v: is_int(v) and v >= 0,
            "min_booking_minutes": lambda v: is_int(v) and v > 0,
            "max_booking_minutes": lambda v: is_int(v) and v > 0,
            "cancellation_free_notice_hours": lambda v: is_int(v) and v >= 0,
            "late_cancel_penalty_pct": lambda v: is_num(v) and 0 <= v <= 1,
            "no_show_penalty_pct": lambda v: is_num(v) and 0 <= v <= 1,
        },
    )
    if body.get("max_booking_minutes") < body.get("min_booking_minutes"):
        fail("ERR_INVALID_REQUEST", "max_booking_minutes must be >= min_booking_minutes")
    inst = new_entity({
        "name": body.get("name"),
        "model": body.get("model"),
        "location": body.get("location"),
        "requires_training": body.get("requires_training", True),
        "booking_buffer_minutes": body.get("booking_buffer_minutes", 0),
        "min_booking_minutes": body.get("min_booking_minutes"),
        "max_booking_minutes": body.get("max_booking_minutes"),
        "cancellation_free_notice_hours": body.get("cancellation_free_notice_hours"),
        "late_cancel_penalty_pct": body.get("late_cancel_penalty_pct"),
        "no_show_penalty_pct": body.get("no_show_penalty_pct"),
        "status": "AVAILABLE",
    })
    store.instruments[inst["id"]] = inst
    return ok_object(ser_instrument(inst), status=201)


@bp.route("/instruments", methods=["GET"])
def list_instruments():
    authenticate()
    require_roles("FacilityAdmin", "CoreStaff", "FinanceOfficer", "Researcher", "ExternalClient")
    limit, offset = parse_pagination(request.args)
    items = list(store.instruments.values())
    status = request.args.get("status")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    return paginate(sort_default(items), limit, offset, ser_instrument)


@bp.route("/instruments/<iid>", methods=["GET"])
def get_instrument(iid):
    authenticate()
    require_roles("FacilityAdmin", "CoreStaff", "FinanceOfficer", "Researcher", "ExternalClient")
    return ok_object(ser_instrument(get_instrument_or_404(iid)))


@bp.route("/instruments/<iid>/retire", methods=["POST"])
def retire_instrument(iid):
    authenticate()
    require_roles("FacilityAdmin")
    inst = get_instrument_or_404(iid)
    if inst["status"] == "RETIRED":
        fail("ERR_INVALID_STATE", "Instrument is already RETIRED")
    inst["status"] = "RETIRED"
    touch(inst)
    # Cascade 1: REQUESTED bookings -> REJECTED; future APPROVED -> CANCELLED (waived)
    for b in list(store.bookings.values()):
        if b["instrument_id"] != iid:
            continue
        if b["status"] == "REQUESTED":
            system_reject(b)
        elif b["status"] == "APPROVED" and b["_start_at"] > now():
            system_cancel(b, "INSTRUMENT_RETIRED")
    # Cascade 2: CONFIRMED downtime events -> RESOLVED
    for ev in list(store.downtime_events.values()):
        if ev["instrument_id"] == iid and ev["status"] == "CONFIRMED":
            ev["status"] = "RESOLVED"
            touch(ev)
    # Cascade 3: non-terminated maintenance contracts -> TERMINATED
    for c in list(store.contracts.values()):
        if c["instrument_id"] == iid and not c.get("_terminated"):
            c["_terminated"] = True
            touch(c)
    # Cascade 4: this instrument's line in DRAFT/UNDER_REVIEW rate sets -> flagged
    for rs in list(store.rate_sets.values()):
        if rs["status"] not in ("DRAFT", "UNDER_REVIEW"):
            continue
        changed = False
        flags = rs.setdefault("_line_flags", [False] * len(rs["lines"]))
        for idx, line in enumerate(rs["lines"]):
            if line["instrument_id"] == iid and not flags[idx]:
                flags[idx] = True
                changed = True
        if changed:
            touch(rs)
    return ok_object(ser_instrument(inst))


@bp.route("/instruments/<iid>/return-to-service", methods=["POST"])
def return_to_service(iid):
    authenticate()
    require_roles("FacilityAdmin")
    inst = get_instrument_or_404(iid)
    if inst["status"] not in ("DOWN", "MAINTENANCE"):
        fail("ERR_INVALID_STATE", "Only a DOWN or MAINTENANCE instrument can return to service")
    # Allowed only when no other CONFIRMED downtime window contains now
    for ev in store.downtime_events.values():
        if ev["instrument_id"] == iid and ev["status"] == "CONFIRMED" and event_contains_now(ev):
            fail("ERR_INVALID_STATE", "A CONFIRMED downtime event still covers the current time")
    inst["status"] = "AVAILABLE"
    touch(inst)
    return ok_object(ser_instrument(inst))
