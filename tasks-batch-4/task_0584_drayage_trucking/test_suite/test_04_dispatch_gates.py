"""Pickup dispatch: the permit gate, the active-driver gate, the permit-over-expiry
priority, the overweight weight boundary, and dispatch authorization.

Covers Difficulty rules: cross_entity_state_dependency, priority_pair_validation_conflict,
boundary_precision_check. Covers Corner section: validations.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    mk_terminal, mk_booking,
    create_weigh_ticket_payload, create_permit_payload,
    setup_pickup_ready,
    TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLER = TEST_USERS["biller_headers"]


def _overweight_appointed(api, *, container_number, appt_end="2026-05-20T23:59:59Z",
                          leg_start="2026-05-06T08:00:00Z", leg_end="2026-05-06T12:00:00Z"):
    ctx = setup_pickup_ready(
        api, clock="2026-05-06T00:00:00Z", container_number=container_number,
        appt_end=appt_end, leg_start=leg_start, leg_end=leg_end,
    )
    get_success_data(api.create_weigh_ticket(
        create_weigh_ticket_payload(ctx["booking_id"], 90000), DISPATCHER))
    permit = get_success_data(api.create_permit(
        create_permit_payload(ctx["booking_id"], permit_number="P11"), DISPATCHER))
    ctx["permit_id"] = permit["id"]
    return ctx


# --- cross_entity_state_dependency: dispatch requires an APPROVED permit ---

def test_dispatch_blocked_while_permit_only_requested(api):
    """PRD §3.5: "If a booking's `requires_permit` is true and no `APPROVED` permit
    exists for it, dispatching its pickup leg is rejected with `ERR_PERMIT_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/dispatch_requires_approved_permit_booking_permit
    """
    ctx = _overweight_appointed(api, container_number="MSCUG")
    resp = api.dispatch_leg(ctx["leg_id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_PERMIT_REQUIRED, expected_status=422)


def test_dispatch_succeeds_after_permit_approved(api):
    """PRD §3.5: "Approving it advances it to `APPROVED`; approval requires the
    permit to currently be `REQUESTED` and increments the permit's `version`."
    PRD §3.6: "**Dispatching** a leg advances it from `PLANNED` to `DISPATCHED`. For
    a pickup leg this is the pivotal operation and drives the booking from `APPOINTED`
    to `DISPATCHED`."

    Design: Difficulty/cross_entity_state_dependency/dispatch_requires_approved_permit_booking_permit
    """
    ctx = _overweight_appointed(api, container_number="MSCUG")
    permit = get_success_data(api.approve_permit(ctx["permit_id"], DISPATCHER))
    assert permit["status"] == "APPROVED"
    get_success_data(api.dispatch_leg(ctx["leg_id"], DISPATCHER))
    leg = validate_success(api.get_leg(ctx["leg_id"], DISPATCHER))
    assert leg["status"] == "DISPATCHED"
    booking = validate_success(api.get_booking(ctx["booking_id"], DISPATCHER))
    assert booking["status"] == "DISPATCHED"


# --- cross_entity_state_dependency: dispatch requires an ACTIVE driver -----

def test_dispatch_inactive_driver_rejected(api):
    """PRD §3.1: "Only an `ACTIVE` driver may be dispatched; an attempt to dispatch
    a leg whose assigned driver is `INACTIVE` is rejected with `ERR_DRIVER_INACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/dispatch_requires_active_driver_leg_driver
    """
    ctx = setup_pickup_ready(api, clock="2026-05-06T00:00:00Z", container_number="MSCUH",
                             driver_status="INACTIVE")
    resp = api.dispatch_leg(ctx["leg_id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_DRIVER_INACTIVE, expected_status=409)


def test_dispatch_inactive_driver_leaves_leg_planned(api):
    """PRD §3.1: "Only an `ACTIVE` driver may be dispatched; an attempt to dispatch
    a leg whose assigned driver is `INACTIVE` is rejected with `ERR_DRIVER_INACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/dispatch_requires_active_driver_leg_driver
    """
    ctx = setup_pickup_ready(api, clock="2026-05-06T00:00:00Z", container_number="MSCUH",
                             driver_status="INACTIVE")
    api.dispatch_leg(ctx["leg_id"], DISPATCHER)
    leg = validate_success(api.get_leg(ctx["leg_id"], DISPATCHER))
    assert leg["status"] == "PLANNED"


# --- priority: permit gate (p7) beats appointment expiry (p9) --------------

def test_permit_gate_precedes_appointment_expiry(api):
    """PRD §2.6: "For a pickup dispatch, the booking's state (priority 6) is checked,
    then the permit gate (priority 7), then the chassis/appointment/driver referential
    states (priority 8), and only then the appointment-expiry check (priority 9)."
    PRD §3.5: "If a booking's `requires_permit` is true and no `APPROVED` permit
    exists for it, dispatching its pickup leg is rejected with `ERR_PERMIT_REQUIRED`."

    Design: Difficulty/priority_pair_validation_conflict/safety_permit_beats_temporal_expired_on_dispatch
    """
    ctx = _overweight_appointed(api, container_number="MSCU9", appt_end="2026-05-07T12:00:00Z",
                                leg_start="2026-05-07T09:00:00Z", leg_end="2026-05-07T11:00:00Z")
    # Advance the clock past window_end so the appointment is also expired.
    api.set_clock("2026-05-10T00:00:00Z", DISPATCHER)
    resp = api.dispatch_leg(ctx["leg_id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_PERMIT_REQUIRED, expected_status=422)


def test_permit_over_expiry_leaves_leg_planned(api):
    """PRD §2.6: "For a pickup dispatch, the booking's state (priority 6) is checked,
    then the permit gate (priority 7), then the chassis/appointment/driver referential
    states (priority 8), and only then the appointment-expiry check (priority 9)."

    Design: Difficulty/priority_pair_validation_conflict/safety_permit_beats_temporal_expired_on_dispatch
    """
    ctx = _overweight_appointed(api, container_number="MSCU9", appt_end="2026-05-07T12:00:00Z",
                                leg_start="2026-05-07T09:00:00Z", leg_end="2026-05-07T11:00:00Z")
    api.set_clock("2026-05-10T00:00:00Z", DISPATCHER)
    api.dispatch_leg(ctx["leg_id"], DISPATCHER)
    leg = validate_success(api.get_leg(ctx["leg_id"], DISPATCHER))
    assert leg["status"] == "PLANNED"


# --- boundary_precision_check: overweight strict-'>' at 80000 --------------

def test_weight_at_legal_limit_not_overweight(api):
    """PRD §3.5: "the load is overweight when its `gross_weight_lbs` is strictly
    greater than the legal limit of 80000 pounds — so 80000 is legal and 80001 is over."
    PRD §3.5: "Recording a ticket sets the booking's `gross_weight_lbs` to the weighed
    value, and once any overweight ticket exists for the booking, the booking's
    `requires_permit` becomes true."

    Design: Difficulty/boundary_precision_check/overweight_weight_boundary_at_and_over_limit
    """
    terminal = mk_terminal(api, name="Pier L", code="PIERL")
    booking = mk_booking(api, terminal["id"], container_number="MSCUE")
    ticket = validate_success(api.create_weigh_ticket(
        create_weigh_ticket_payload(booking["id"], 80000), DISPATCHER), expected_status=201)
    assert ticket["is_overweight"] is False
    after = validate_success(api.get_booking(booking["id"], DISPATCHER))
    assert after["requires_permit"] is False


def test_weight_over_legal_limit_is_overweight(api):
    """PRD §3.5: "the load is overweight when its `gross_weight_lbs` is strictly
    greater than the legal limit of 80000 pounds — so 80000 is legal and 80001 is over."
    PRD §3.5: "Recording a ticket sets the booking's `gross_weight_lbs` to the weighed
    value, and once any overweight ticket exists for the booking, the booking's
    `requires_permit` becomes true."

    Design: Difficulty/boundary_precision_check/overweight_weight_boundary_at_and_over_limit
    """
    terminal = mk_terminal(api, name="Pier L", code="PIERL")
    booking = mk_booking(api, terminal["id"], container_number="MSCUF")
    ticket = validate_success(api.create_weigh_ticket(
        create_weigh_ticket_payload(booking["id"], 80001), DISPATCHER), expected_status=201)
    assert ticket["is_overweight"] is True
    after = validate_success(api.get_booking(booking["id"], DISPATCHER))
    assert after["requires_permit"] is True


# --- Corner: Biller may not dispatch a leg --------------------------------

def test_biller_cannot_dispatch_leg(api):
    """PRD §2.1: "When a syntactically valid, known role attempts an operation it is
    not permitted to perform, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "The `Dispatcher` role owns all operational data — terminals, chassis,
    drivers, bookings, chassis assignment and release, appointments, legs, weigh
    tickets, permits, and the logical clock."

    Design: Corner/validations/biller_cannot_dispatch_leg_returns_unauthorized
    """
    ctx = setup_pickup_ready(api, clock="2026-05-06T00:00:00Z", container_number="MSCU15")
    resp = api.dispatch_leg(ctx["leg_id"], BILLER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)
    leg = validate_success(api.get_leg(ctx["leg_id"], DISPATCHER))
    assert leg["status"] == "PLANNED"
