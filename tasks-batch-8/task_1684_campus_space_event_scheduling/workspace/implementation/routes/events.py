"""Event reservations (PRD 3.4): the full ad-hoc booking lifecycle."""

from datetime import timedelta

import db
import serializers
from clock import clock, render_server
from constants import (
    CONFIRM_WINDOW_HOURS,
    CHECKIN_EARLY_MINUTES,
    CHECKIN_LATE_MINUTES,
    DECISION_DEADLINE_HOURS,
    FEATURES,
    MAX_EVENT_HOURS,
    MIN_EVENT_MINUTES,
    MIN_LIABILITY_COVERAGE_CENTS,
    PRECEDENCE_TIER,
    RATE_FIELD,
)
from errors import ApiError
from middleware import endpoint
from routes.common import list_response, one
from services import invoices as invoice_service
from services.cascade import cancel_nonterminal_orders, revoke_requested_grants
from services.derive import derive_standing
from services.intervals import (
    event_intersects_term,
    event_occupancy_conflicts,
    has_outstanding_grants,
    occupancy_interval,
)
from services.pricing import cancellation_fee_cents
from validate import (
    get_event_masked,
    get_room,
    opt_enum_array,
    opt_int,
    req_dt,
    req_int,
    req_str,
)

ALL_READ_ROLES = ["Scheduler", "FacilitiesManager", "ServiceCoordinator", "FinanceAdmin", "OrgRequester"]


def _term_priority_lock(event):
    """PRD 3.3: while a term is in SCHEDULING, approving or rebooking an ad-hoc
    event whose [start_at, end_at) intersects the term's instructional dates is
    rejected until the term reaches GENERAL."""
    for term in db.terms.values():
        if term.get("status") != "SCHEDULING":
            continue
        if event_intersects_term(event, term):
            raise ApiError(
                "ERR_TERM_PRIORITY_LOCKED",
                "The event intersects a term in its academic priority scheduling window.",
            )


def _room_gates(event, room, exclude_event_id=None):
    """The approval/rebooking room gates, in PRD order: ACTIVE, capacity,
    features superset, then occupancy/outage/placed-block conflicts."""
    if room["status"] != "ACTIVE":
        raise ApiError("ERR_ROOM_NOT_AVAILABLE", "The room is not active.")
    if event["expected_attendance"] > room["capacity"]:
        raise ApiError("ERR_CAPACITY_EXCEEDED", "expected_attendance exceeds the room capacity.")
    if not set(event.get("required_features", [])) <= set(room.get("features", [])):
        raise ApiError("ERR_FEATURE_MISMATCH", "The room does not offer all required features.")
    occ_start, occ_end = occupancy_interval(event, room)
    if event_occupancy_conflicts(
        room, occ_start, occ_end, exclude_event_id=exclude_event_id, include_blocks=True
    ):
        raise ApiError("ERR_ROOM_NOT_AVAILABLE", "The room has a conflicting commitment.")


def _pin_rates(event, room, org):
    event["pinned_hourly_rate_cents"] = room[RATE_FIELD[org["org_type"]]]
    event["pinned_peak_multiplier_bps"] = room.get("peak_multiplier_bps", 12500)


@endpoint("POST", "/campus/event-reservations", roles=["OrgRequester"], code=201)
def create_event(ctx):
    body = ctx.body
    # The OrgRequester's X-User-ID is the acting Organization's id.
    org = db.organizations.get(ctx.user_id)
    if org is None:
        raise ApiError("ERR_NOT_FOUND", "The acting organization does not exist.")

    room_id = req_str(body, "room_id")
    room = get_room(room_id)  # body FK existence (rung 3)

    # Rung 4 - request shape, in PRD listing order.
    title = req_str(body, "title")
    expected_attendance = req_int(body, "expected_attendance")
    if expected_attendance < 1:
        raise ApiError("ERR_INVALID_REQUEST", "expected_attendance must be at least 1.")
    start_raw, start_dt = req_dt(body, "start_at")
    end_raw, end_dt = req_dt(body, "end_at")
    if end_dt <= start_dt:
        raise ApiError("ERR_INVALID_TIME_RANGE", "end_at must be later than start_at.")
    duration = end_dt - start_dt
    if duration < timedelta(minutes=MIN_EVENT_MINUTES) or duration > timedelta(hours=MAX_EVENT_HOURS):
        raise ApiError(
            "ERR_DURATION_OUT_OF_RANGE",
            "The event duration must be within [30 minutes, 8 hours].",
        )
    required_features = opt_enum_array(body, "required_features", FEATURES)
    setup_minutes = opt_int(body, "setup_minutes", 0)
    teardown_minutes = opt_int(body, "teardown_minutes", 0)
    if setup_minutes < 0 or teardown_minutes < 0:
        raise ApiError("ERR_INVALID_REQUEST", "setup_minutes and teardown_minutes must be non-negative.")
    expected_room_version = req_int(body, "expected_room_version")

    # Rung 5 - OCC on the room version.
    if expected_room_version != room["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_room_version does not match the room's current version.",
        )

    # Rung 7 - a suspended organization cannot create event requests.
    if derive_standing(org) == "SUSPENDED":
        raise ApiError("ERR_ORG_SUSPENDED", "A suspended organization cannot create event requests.")

    # Rung 9 - resource constraints: capacity, features, then conflicts.
    if expected_attendance > room["capacity"]:
        raise ApiError("ERR_CAPACITY_EXCEEDED", "expected_attendance exceeds the room capacity.")
    if not set(required_features) <= set(room.get("features", [])):
        raise ApiError("ERR_FEATURE_MISMATCH", "The room does not offer all required features.")
    occ_start = start_dt - timedelta(minutes=setup_minutes)
    occ_end = end_dt + timedelta(minutes=teardown_minutes + room.get("turnaround_buffer_minutes", 0))
    if event_occupancy_conflicts(room, occ_start, occ_end):
        raise ApiError("ERR_ROOM_NOT_AVAILABLE", "The room has a conflicting commitment.")

    now = clock.now
    decision_deadline = now + timedelta(hours=DECISION_DEADLINE_HOURS)
    row = db.new_row(
        db.event_reservations,
        requester_org_id=org["id"],
        room_id=room["id"],
        title=title,
        expected_attendance=expected_attendance,
        required_features=required_features,
        start_at=start_raw,
        end_at=end_raw,
        setup_minutes=setup_minutes,
        teardown_minutes=teardown_minutes,
        precedence_tier=PRECEDENCE_TIER[org["org_type"]],
        status="REQUESTED",
        decision_deadline=render_server(decision_deadline),
        confirm_deadline=None,
        checked_in_at=None,
        pinned_hourly_rate_cents=None,
        pinned_peak_multiplier_bps=None,
        cancellation_fee_cents=None,
        cancel_reason=None,
        approved_by_user_id=None,
        decline_reason=None,
        _start=start_dt,
        _end=end_dt,
        _decision_deadline=decision_deadline,
        _confirm_deadline=None,
    )
    # Creating an event records demand against the room: room version +1.
    db.touch(room)
    return one(serializers.event(row), status=201)


@endpoint("GET", "/campus/event-reservations/{id}", roles=ALL_READ_ROLES, code=200)
def get_event_detail(ctx):
    return one(serializers.event(get_event_masked(ctx, ctx.id)))


@endpoint("GET", "/campus/event-reservations", roles=ALL_READ_ROLES, code=200)
def list_events(ctx):
    rows = db.all_of(db.event_reservations)
    if ctx.is_org_requester:
        # List endpoints silently scope an OrgRequester's results to their own
        # organization.
        rows = [r for r in rows if r.get("requester_org_id") == ctx.user_id]
    return list_response(
        rows,
        ctx.args,
        serializers.event,
        mapping={
            "room_id": lambda r: r.get("room_id"),
            "requester_org_id": lambda r: r.get("requester_org_id"),
            "status": lambda r: r.get("status"),
        },
    )


@endpoint("POST", "/campus/event-reservations/{id}/approve", roles=["Scheduler"], code=200)
def approve_event(ctx):
    event = get_event_masked(ctx, ctx.id)
    # Rung 6 - state validity, including the decision deadline.
    if event["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "Only a REQUESTED event can be approved.")
    now = clock.now
    if now > event["_decision_deadline"]:
        raise ApiError("ERR_INVALID_STATE", "The decision deadline has passed.")
    # Rung 7 - the suspended-organization bar.
    org = db.organizations.get(event["requester_org_id"])
    if org is not None and derive_standing(org) == "SUSPENDED":
        raise ApiError("ERR_ORG_SUSPENDED", "A suspended organization's events cannot be approved.")
    # Rung 8 - the term priority lock.
    _term_priority_lock(event)
    # Rung 9 - the room gates.
    room = get_room(event["room_id"])
    _room_gates(event, room, exclude_event_id=event["id"])

    # Approval pins the economics onto the event; later room edits never
    # reprice it.
    _pin_rates(event, room, org)
    event["status"] = "APPROVED"
    confirm_deadline = now + timedelta(hours=CONFIRM_WINDOW_HOURS)
    event["confirm_deadline"] = render_server(confirm_deadline)
    event["_confirm_deadline"] = confirm_deadline
    event["approved_by_user_id"] = ctx.user_id
    invoice_service.create_provisional_invoice(event, org)
    db.touch(event)
    return one(serializers.event(event))


@endpoint("POST", "/campus/event-reservations/{id}/decline", roles=["Scheduler"], code=200)
def decline_event(ctx):
    event = get_event_masked(ctx, ctx.id)
    if event["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "Only a REQUESTED event can be declined.")
    reason = req_str(ctx.body, "reason")
    event["status"] = "DECLINED"
    event["decline_reason"] = reason
    db.touch(event)
    # The system revokes grants still in REQUESTED when the event is declined.
    revoke_requested_grants(event)
    return one(serializers.event(event))


@endpoint("POST", "/campus/event-reservations/{id}/confirm", roles=["OrgRequester"], code=200)
def confirm_event(ctx):
    event = get_event_masked(ctx, ctx.id)  # ownership mismatch masked as 404
    if event["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "Only an APPROVED event can be confirmed.")
    org = db.organizations.get(event["requester_org_id"])
    # Rung 7 - the EXTERNAL insurance gate.
    if org is not None and org["org_type"] == "EXTERNAL":
        expiry = org.get("_insurance_expiry")
        coverage = org.get("insurance_coverage_cents")
        if expiry is None or expiry < event["_end"]:
            raise ApiError(
                "ERR_INSURANCE_INVALID",
                "The insurance certificate must remain valid through the event end.",
            )
        if coverage is None or coverage < MIN_LIABILITY_COVERAGE_CENTS:
            raise ApiError(
                "ERR_INSURANCE_INVALID",
                "The liability coverage must be at least %d cents." % MIN_LIABILITY_COVERAGE_CENTS,
            )
    # Rung 8 - the confirmation window.
    if clock.now > event["_confirm_deadline"]:
        raise ApiError("ERR_CONFIRM_WINDOW_EXPIRED", "The confirmation deadline has passed.")
    # Rung 10 - the PROBATION prepayment gate (money rules, always last).
    if org is not None and derive_standing(org) == "PROBATION":
        invoice = invoice_service.current_invoice(event)
        if invoice is None or (
            invoice.get("paid_cents", 0) + invoice.get("waived_cents", 0) < invoice.get("total_cents", 0)
        ):
            raise ApiError(
                "ERR_PREPAYMENT_REQUIRED",
                "A probationary organization must fully cover the provisional invoice before confirming.",
            )
    event["status"] = "CONFIRMED"
    db.touch(event)
    return one(serializers.event(event))


@endpoint("POST", "/campus/event-reservations/{id}/cancel", roles=["OrgRequester", "Scheduler"], code=200)
def cancel_event(ctx):
    event = get_event_masked(ctx, ctx.id)  # OrgRequester ownership masked as 404
    if event["status"] not in ("REQUESTED", "APPROVED", "CONFIRMED", "BUMPED"):
        raise ApiError("ERR_INVALID_STATE", "The event cannot be cancelled from its current state.")
    # A CONFIRMED event holding outstanding access grants refuses cancellation.
    if event["status"] == "CONFIRMED" and has_outstanding_grants(event):
        raise ApiError(
            "ERR_ACCESS_GRANTS_OUTSTANDING",
            "Return or mark lost the outstanding access grants first.",
        )

    if event["status"] == "BUMPED":
        reason = "BUMPED"
    elif ctx.role == "Scheduler":
        reason = "ADMIN"
    else:
        reason = "CLIENT"

    now = clock.now
    fee = 0
    invoice = invoice_service.current_invoice(event)
    # The tiered fee applies only to CLIENT cancels of events with a live
    # invoice; the base is the invoice's pinned room + service snapshot.
    if reason == "CLIENT" and event["status"] in ("APPROVED", "CONFIRMED") and invoice is not None:
        notice = event["_start"] - now
        base = invoice.get("room_charge_cents", 0) + invoice.get("service_charge_cents", 0)
        fee = cancellation_fee_cents(base, notice)
    event["cancellation_fee_cents"] = fee
    event["cancel_reason"] = reason

    fulfilled = [
        o
        for o in invoice_service.orders_of_event(event)
        if o.get("status") == "FULFILLED"
    ]
    if event["status"] in ("APPROVED", "CONFIRMED") and invoice is not None:
        if fee == 0 and not fulfilled:
            # Free cancellation with nothing fulfilled: the invoice is voided.
            if invoice["status"] == "PROVISIONAL":
                db.set_fields(invoice, status="VOIDED")
        else:
            # Cancellation with charges: fee + fulfilled service + deposits;
            # the room line is excluded and no surcharge is applied.
            invoice_service.finalize_invoice(event, "CANCELLED")

    cancel_nonterminal_orders(event, fee_waived=(reason != "CLIENT"))
    revoke_requested_grants(event)
    event["status"] = "CANCELLED"
    db.touch(event)
    return one(serializers.event(event))


@endpoint("POST", "/campus/event-reservations/{id}/rebook", roles=["Scheduler", "OrgRequester"], code=200)
def rebook_event(ctx):
    event = get_event_masked(ctx, ctx.id)  # OrgRequester ownership masked as 404
    body = ctx.body
    room_id = req_str(body, "room_id")
    room = get_room(room_id)  # body FK existence (rung 3)
    if event["status"] != "BUMPED":
        raise ApiError("ERR_INVALID_STATE", "Only a BUMPED event can be rebooked.")
    org = db.organizations.get(event["requester_org_id"])
    # Rung 8 - the term priority lock, then rung 9 - the room gates, both the
    # same as approval.
    _term_priority_lock(event)
    _room_gates(event, room, exclude_event_id=event["id"])

    now = clock.now
    event["room_id"] = room["id"]
    # Rates are re-pinned from the NEW room at rebooking time.
    _pin_rates(event, room, org)
    event["status"] = "APPROVED"
    confirm_deadline = now + timedelta(hours=CONFIRM_WINDOW_HOURS)
    event["confirm_deadline"] = render_server(confirm_deadline)
    event["_confirm_deadline"] = confirm_deadline
    event["approved_by_user_id"] = ctx.user_id
    # A fresh PROVISIONAL invoice at the new rates; the voided history is
    # retained.
    invoice_service.create_provisional_invoice(event, org)
    db.touch(event)
    return one(serializers.event(event))


@endpoint("POST", "/campus/event-reservations/{id}/check-in", roles=["OrgRequester", "FacilitiesManager"], code=200)
def check_in_event(ctx):
    event = get_event_masked(ctx, ctx.id)  # OrgRequester ownership masked as 404
    if event["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", "Only a CONFIRMED event can be checked in.")
    now = clock.now
    window_start = event["_start"] - timedelta(minutes=CHECKIN_EARLY_MINUTES)
    window_end = event["_start"] + timedelta(minutes=CHECKIN_LATE_MINUTES)
    if now < window_start or now > window_end:
        raise ApiError(
            "ERR_CHECKIN_WINDOW_CLOSED",
            "Check-in is allowed only within [start_at - 30m, start_at + 15m].",
        )
    event["checked_in_at"] = render_server(now)
    event["status"] = "IN_PROGRESS"
    db.touch(event)
    return one(serializers.event(event))
