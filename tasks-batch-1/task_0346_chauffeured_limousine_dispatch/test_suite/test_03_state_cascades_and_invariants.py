"""Cross-entity cascades, the chauffeur duty cycle, the flight revert loop,
compensating invariants, and state-gating across entities.

These exercise the operational story: assigning a reservation flips the chauffeur,
dispatching moves it ON_TRIP, completing reverts it; cancelling unwinds the same
hops; a delayed flight slides the assignment window and reverts when it recovers.
"""
from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    create_account,
    create_vehicle_class,
    create_chauffeur,
    create_vehicle,
    create_affiliate,
    create_reservation,
    create_quoted_reservation,
    create_confirmed_reservation,
    quote_reservation,
    confirm_reservation,
    assign_in_house,
    dispatch_trip,
    post_wait_event,
    complete_trip,
    suspend_account,
    suspend_chauffeur,
    attach_flight_tracking,
    push_flight_update,
    setup_assigned_reservation,
    setup_en_route_reservation,
    setup_completed_reservation,
    setup_assigned_airport_reservation,
    invoice_reservation,
    settle_reservation,
    api_client,
    TEST_USERS,
    trip_event_payload,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/nonlinear_chauffeur_status_cycle_on_duty_on_trip_on_duty
# ---------------------------------------------------------------------------
def test_chauffeur_returns_to_on_duty_after_trip_cycle():
    """PRD §3.4: "Completion runs the final settlement and stamps final_total_cents,
    then unwinds the operational cascade: the chauffeur moves ON_TRIP → ON_DUTY,
    the chauffeur's active_assignment_id is cleared, and the assignment moves
    ACTIVE → RELEASED, freeing both the chauffeur and the vehicle for their next trip."

    Design: Difficulty/non_linear_state_machine/nonlinear_chauffeur_status_cycle_on_duty_on_trip_on_duty
    """
    ctx = setup_completed_reservation(
        "2026-07-05T12:05:00Z", "2026-07-05T12:10:00Z",
        account_overrides={"negotiated_discount_pct": 0, "default_gratuity_pct": 20},
        res_overrides={"pickup_at": "2026-07-05T12:00:00Z",
                       "planned_drop_at": "2026-07-05T13:00:00Z", "estimated_miles": 10},
    )
    drv = validate_success(api_client.get_chauffeur(ctx["chauffeur_id"], DISPATCHER), 200)
    assert drv["status"] == "ON_DUTY", f"chauffeur should cycle back to ON_DUTY, got {drv['status']}"
    assert drv["active_assignment_id"] is None


def test_chauffeur_on_trip_with_active_assignment_during_dispatch():
    """PRD §3.3: "The cascade's second hop fires here: the chauffeur moves
    ON_DUTY → ON_TRIP and the chauffeur's active_assignment_id is set to the
    driving assignment's id."

    Design: Difficulty/non_linear_state_machine/nonlinear_chauffeur_status_cycle_on_duty_on_trip_on_duty
    """
    ctx = setup_en_route_reservation(
        account_overrides={"negotiated_discount_pct": 0, "default_gratuity_pct": 20},
        res_overrides={"pickup_at": "2026-07-05T12:00:00Z",
                       "planned_drop_at": "2026-07-05T13:00:00Z", "estimated_miles": 10},
    )
    drv = validate_success(api_client.get_chauffeur(ctx["chauffeur_id"], DISPATCHER), 200)
    assert drv["status"] == "ON_TRIP", f"chauffeur should be ON_TRIP while dispatched, got {drv['status']}"
    assert drv["active_assignment_id"] == ctx["assignment"]["id"]


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/nonlinear_flight_tracking_on_time_delayed_revert_loop
# ---------------------------------------------------------------------------
def _airport_flight_only():
    """AIRPORT reservation (DRAFT) with flight tracking, scheduled arrival 15:00.
    Not assigned, so updates only flip flight status (no window shift). Returns ft id."""
    account = create_account()
    vclass = create_vehicle_class(code="SUV", base_fare_cents=7000, per_mile_cents=300,
                                  hourly_rate_cents=15000, wait_per_minute_cents=250)
    res = create_reservation(account["id"], vclass["id"], trip_type="AIRPORT",
                             pickup_at="2026-07-06T15:30:00Z",
                             planned_drop_at="2026-07-06T16:30:00Z", estimated_miles=18)
    flight = attach_flight_tracking(res["id"], flight_number="UA1234",
                                    scheduled_arrival_at="2026-07-06T15:00:00Z", meet_and_greet=True)
    return flight["id"]


def test_flight_reverts_to_on_time_after_delay_clears():
    """PRD §3.6: "When the delay is strictly greater than fifteen minutes, the
    flight becomes DELAYED (from either ON_TIME or DELAYED); when the delay is
    within fifteen minutes, the flight returns to ON_TIME."

    Design: Difficulty/non_linear_state_machine/nonlinear_flight_tracking_on_time_delayed_revert_loop
    """
    ftid = _airport_flight_only()
    push_flight_update(ftid, estimated_arrival_at="2026-07-06T15:40:00Z")  # delay 40 -> DELAYED
    reverted = push_flight_update(ftid, estimated_arrival_at="2026-07-06T15:10:00Z")  # delay 10 -> ON_TIME
    assert reverted["status"] == "ON_TIME", f"should revert to ON_TIME, got {reverted['status']}"
    assert reverted["estimated_arrival_at"] == "2026-07-06T15:10:00Z"


def test_flight_delay_update_flips_to_delayed():
    """PRD §3.6: "A delay of exactly fifteen minutes leaves the flight ON_TIME —
    only a delay strictly past the threshold trips it into DELAYED."

    Design: Difficulty/non_linear_state_machine/nonlinear_flight_tracking_on_time_delayed_revert_loop
    """
    ftid = _airport_flight_only()
    delayed = push_flight_update(ftid, estimated_arrival_at="2026-07-06T15:40:00Z")  # delay 40
    assert delayed["status"] == "DELAYED", f"delay 40 > 15 => DELAYED, got {delayed['status']}"


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/cascade_assignment_create_depth3_reservation_chauffeur_assignment
# ---------------------------------------------------------------------------
def test_assignment_create_cascades_reservation_assignment_chauffeur():
    """PRD §3.3: "As the first hop of a cross-entity cascade, the reservation
    moves to ASSIGNED and its version increments by one. As the second visible
    effect, the chauffeur moves from OFF_DUTY to ON_DUTY (a chauffeur already
    ON_DUTY stays ON_DUTY)."

    Design: Difficulty/transitive_cascade/cascade_assignment_create_depth3_reservation_chauffeur_assignment
    """
    ctx = setup_assigned_reservation(
        account_overrides={"negotiated_discount_pct": 0, "default_gratuity_pct": 20},
        res_overrides={"pickup_at": "2026-07-07T12:00:00Z",
                       "planned_drop_at": "2026-07-07T13:00:00Z", "estimated_miles": 10},
    )
    res = validate_success(api_client.get_reservation(ctx["reservation_id"], DISPATCHER), 200)
    drv = validate_success(api_client.get_chauffeur(ctx["chauffeur_id"], DISPATCHER), 200)
    assert res["trip_status"] == "ASSIGNED"
    assert ctx["assignment"]["status"] == "ACTIVE"
    assert drv["status"] == "ON_DUTY"


def test_assignment_create_makes_assignment_active():
    """PRD §3.3: "When all preconditions hold, the system creates an assignment
    whose status is ACTIVE and whose window_start_at and window_end_at are copied
    from the reservation's pickup_at and planned_drop_at."

    Design: Difficulty/transitive_cascade/cascade_assignment_create_depth3_reservation_chauffeur_assignment
    """
    ctx = setup_assigned_reservation(
        account_overrides={"negotiated_discount_pct": 0, "default_gratuity_pct": 20},
        res_overrides={"pickup_at": "2026-07-07T12:00:00Z",
                       "planned_drop_at": "2026-07-07T13:00:00Z", "estimated_miles": 10},
    )
    asg = validate_success(api_client.get_assignment(ctx["assignment"]["id"], DISPATCHER), 200)
    assert asg["status"] == "ACTIVE"
    assert asg["window_start_at"] == "2026-07-07T12:00:00Z"
    assert asg["window_end_at"] == "2026-07-07T13:00:00Z"


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/cascade_cancel_en_route_depth2_reservation_assignment_then_chauffeur
# ---------------------------------------------------------------------------
def _en_route_for_cancel():
    """Reservation EN_ROUTE, chauffeur ON_TRIP, ACTIVE assignment, grace 0 so the
    cancel is permitted from EN_ROUTE without billing concerns."""
    return setup_en_route_reservation(
        account_overrides={"negotiated_discount_pct": 0, "default_gratuity_pct": 20,
                           "cancellation_grace_minutes": 0},
        res_overrides={"pickup_at": "2026-07-08T12:00:00Z",
                       "planned_drop_at": "2026-07-08T13:00:00Z", "estimated_miles": 10},
    )


def test_cancel_en_route_releases_assignment_and_reverts_chauffeur():
    """PRD §3.7: "cancelling an EN_ROUTE reservation releases the assignment and
    reverts the chauffeur ON_TRIP → OFF_DUTY while clearing its active_assignment_id."

    Design: Difficulty/transitive_cascade/cascade_cancel_en_route_depth2_reservation_assignment_then_chauffeur
    """
    ctx = _en_route_for_cancel()
    validate_success(
        api_client.create_trip_event(ctx["reservation_id"], trip_event_payload("CANCEL"), DISPATCHER), 200
    )
    drv = validate_success(api_client.get_chauffeur(ctx["chauffeur_id"], DISPATCHER), 200)
    asg = validate_success(api_client.get_assignment(ctx["assignment"]["id"], DISPATCHER), 200)
    assert drv["status"] == "OFF_DUTY", f"chauffeur should revert OFF_DUTY, got {drv['status']}"
    assert drv["active_assignment_id"] is None
    assert asg["status"] == "RELEASED"


def test_cancel_en_route_moves_reservation_to_cancelled():
    """PRD §3.7: "Cancellation drives the reservation to CANCELLED, runs the tier
    calculation to stamp cancellation_fee_cents, and writes an immutable
    CancellationRecord referencing the reservation by reservation_id and capturing
    the chosen tier, the lead_minutes, and the fee_cents mirrored from the reservation."

    Design: Difficulty/transitive_cascade/cascade_cancel_en_route_depth2_reservation_assignment_then_chauffeur
    """
    ctx = _en_route_for_cancel()
    cancelled = validate_success(
        api_client.create_trip_event(ctx["reservation_id"], trip_event_payload("CANCEL"), DISPATCHER), 200
    )
    assert cancelled["trip_status"] == "CANCELLED"


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/compensating_chauffeur_duty_conserved_across_assign_then_cancel
# ---------------------------------------------------------------------------
def test_assign_then_cancel_conserves_chauffeur_off_duty():
    """PRD §3.7: "cancelling an ASSIGNED reservation releases the assignment
    ACTIVE → RELEASED and reverts the chauffeur ON_DUTY → OFF_DUTY"

    Design: Difficulty/compensating_invariant/compensating_chauffeur_duty_conserved_across_assign_then_cancel
    """
    ctx = setup_assigned_reservation(
        account_overrides={"cancellation_grace_minutes": 0},
        res_overrides={"pickup_at": "2026-07-17T12:00:00Z",
                       "planned_drop_at": "2026-07-17T13:00:00Z", "estimated_miles": 10},
    )
    validate_success(
        api_client.create_trip_event(ctx["reservation_id"], trip_event_payload("CANCEL"), DISPATCHER), 200
    )
    drv = validate_success(api_client.get_chauffeur(ctx["chauffeur_id"], DISPATCHER), 200)
    asg = validate_success(api_client.get_assignment(ctx["assignment"]["id"], DISPATCHER), 200)
    assert drv["status"] == "OFF_DUTY", f"net-zero duty drift: expected OFF_DUTY, got {drv['status']}"
    assert drv["active_assignment_id"] is None
    assert asg["status"] == "RELEASED"


def test_assign_then_cancel_chauffeur_can_be_reassigned():
    """PRD §3.3: "The nominated chauffeur must be available, meaning its status is
    OFF_DUTY or ON_DUTY and not ON_TRIP or SUSPENDED"

    Design: Difficulty/compensating_invariant/compensating_chauffeur_duty_conserved_across_assign_then_cancel
    """
    # After assign+cancel the chauffeur is OFF_DUTY (available) and has no ACTIVE
    # assignment, so a fresh confirmed reservation can be assigned to the same
    # chauffeur+vehicle — proving the resources were truly released.
    ctx = setup_assigned_reservation(
        account_overrides={"cancellation_grace_minutes": 0},
        res_overrides={"pickup_at": "2026-07-17T12:00:00Z",
                       "planned_drop_at": "2026-07-17T13:00:00Z", "estimated_miles": 10},
    )
    validate_success(
        api_client.create_trip_event(ctx["reservation_id"], trip_event_payload("CANCEL"), DISPATCHER), 200
    )
    confirmed2 = create_confirmed_reservation(
        ctx["account_id"], ctx["vclass"]["id"], trip_type="POINT_TO_POINT",
        pickup_at="2026-07-17T18:00:00Z", planned_drop_at="2026-07-17T19:00:00Z", estimated_miles=8,
    )
    asg2 = assign_in_house(confirmed2["id"], ctx["chauffeur_id"], ctx["vehicle_id"], confirmed2["version"])
    assert asg2["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/compensating_account_balance_conserved_invoice_then_settle
# ---------------------------------------------------------------------------
def _completed_invoiced_10610():
    """Completed reservation final_total 10610, then invoiced. Returns (account_id, rid)."""
    ctx = setup_completed_reservation(
        "2026-07-18T12:05:00Z", "2026-07-18T12:27:00Z",
        account_overrides={"negotiated_discount_pct": 10, "default_gratuity_pct": 20},
        class_overrides={"code": "SEDAN", "base_fare_cents": 5000, "per_mile_cents": 250,
                         "hourly_rate_cents": 12000, "wait_per_minute_cents": 200,
                         "included_wait_minutes": 15},
        res_overrides={"pickup_at": "2026-07-18T12:00:00Z",
                       "planned_drop_at": "2026-07-18T13:00:00Z",
                       "estimated_miles": 12.4, "tolls_cents": 350},
    )
    invoice_reservation(ctx["reservation_id"])
    return ctx["account_id"], ctx["reservation_id"], ctx["reservation_final"]


def test_invoice_then_settle_returns_balance_to_zero():
    """PRD §2.9: "A corporate account's outstanding_balance_cents is the sum of
    final_total_cents over that account's reservations whose settlement_status is
    INVOICED, less amounts that have moved on to SETTLED or WRITTEN_OFF"

    Design: Difficulty/compensating_invariant/compensating_account_balance_conserved_invoice_then_settle
    """
    set_clock("2026-07-18T09:00:00Z")
    account_id, rid, final = _completed_invoiced_10610()
    assert final["final_total_cents"] == 10610
    settled = settle_reservation(rid)
    assert settled["settlement_status"] == "SETTLED"
    account = validate_success(api_client.get_corporate_account(account_id, DISPATCHER), 200)
    assert account["outstanding_balance_cents"] == 0, (
        f"settle drops balance by 10610 back to 0, got {account['outstanding_balance_cents']}"
    )


def test_invoice_raises_balance_by_final_total():
    """PRD §3.8: "Invoicing recomputes the owning account's outstanding_balance_cents."

    Design: Difficulty/compensating_invariant/compensating_account_balance_conserved_invoice_then_settle
    """
    set_clock("2026-07-18T09:00:00Z")
    account_id, _rid, _final = _completed_invoiced_10610()
    account = validate_success(api_client.get_corporate_account(account_id, DISPATCHER), 200)
    assert account["outstanding_balance_cents"] == 10610, (
        f"invoiced reservation raises balance to 10610, got {account['outstanding_balance_cents']}"
    )


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/cross_entity_confirm_requires_account_active
# ---------------------------------------------------------------------------
def test_confirm_blocked_when_account_suspended():
    """PRD §3.3: "It requires the reservation to be QUOTED and the owning corporate
    account's status to be ACTIVE; if the account has been suspended, confirmation
    is rejected with ERR_ACCOUNT_SUSPENDED"

    Design: Difficulty/cross_entity_state_dependency/cross_entity_confirm_requires_account_active
    """
    account = create_account()
    vclass = create_vehicle_class(code="SEDAN", base_fare_cents=5000, per_mile_cents=250,
                                  hourly_rate_cents=12000, wait_per_minute_cents=200)
    quoted = create_quoted_reservation(account["id"], vclass["id"], trip_type="POINT_TO_POINT",
                                       pickup_at="2026-07-13T12:00:00Z",
                                       planned_drop_at="2026-07-13T13:00:00Z", estimated_miles=10)
    suspend_account(account["id"])
    resp = api_client.create_trip_event(quoted["id"], trip_event_payload("CONFIRM"), DISPATCHER)
    validate_error(resp, "ERR_ACCOUNT_SUSPENDED")


def test_confirm_succeeds_when_account_active():
    """PRD §3.3: "Confirmation moves a reservation QUOTED → CONFIRMED and may be
    performed by a Dispatcher or a CorporateBooker."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_confirm_requires_account_active
    """
    account = create_account()
    vclass = create_vehicle_class(code="SEDAN", base_fare_cents=5000, per_mile_cents=250,
                                  hourly_rate_cents=12000, wait_per_minute_cents=200)
    quoted = create_quoted_reservation(account["id"], vclass["id"], trip_type="POINT_TO_POINT",
                                       pickup_at="2026-07-13T12:00:00Z",
                                       planned_drop_at="2026-07-13T13:00:00Z", estimated_miles=10)
    confirmed = confirm_reservation(quoted["id"])
    assert confirmed["trip_status"] == "CONFIRMED"


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/cross_entity_assignment_requires_chauffeur_not_suspended
# ---------------------------------------------------------------------------
def test_assign_blocked_when_chauffeur_suspended():
    """PRD §3.3: "The nominated chauffeur must be available, meaning its status is
    OFF_DUTY or ON_DUTY and not ON_TRIP or SUSPENDED; an unavailable chauffeur is
    rejected with ERR_RESOURCE_UNAVAILABLE."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_assignment_requires_chauffeur_not_suspended
    """
    account = create_account()
    vclass = create_vehicle_class(code="SEDAN", base_fare_cents=5000, per_mile_cents=250,
                                  hourly_rate_cents=12000, wait_per_minute_cents=200)
    drv = create_chauffeur(full_name="Dana", home_market_code="SFO")
    suspend_chauffeur(drv["id"])
    veh = create_vehicle(vclass["id"], plate="BLK-X1")
    confirmed = create_confirmed_reservation(account["id"], vclass["id"], trip_type="POINT_TO_POINT",
                                             pickup_at="2026-07-14T12:00:00Z",
                                             planned_drop_at="2026-07-14T13:00:00Z", estimated_miles=10)
    from test_helpers import create_assignment_payload
    resp = api_client.create_assignment(
        create_assignment_payload(confirmed["id"], drv["id"], veh["id"], confirmed["version"]),
        DISPATCHER,
    )
    validate_error(resp, "ERR_RESOURCE_UNAVAILABLE")
    res = validate_success(api_client.get_reservation(confirmed["id"], DISPATCHER), 200)
    assert res["trip_status"] == "CONFIRMED", "reservation stays CONFIRMED on a rejected assignment"


def test_assign_succeeds_when_chauffeur_off_duty():
    """PRD §3.3: "A successful assignment is the gateway from CONFIRMED to ASSIGNED"

    Design: Difficulty/cross_entity_state_dependency/cross_entity_assignment_requires_chauffeur_not_suspended
    """
    account = create_account()
    vclass = create_vehicle_class(code="SEDAN", base_fare_cents=5000, per_mile_cents=250,
                                  hourly_rate_cents=12000, wait_per_minute_cents=200)
    drv = create_chauffeur(full_name="Dana", home_market_code="SFO")
    veh = create_vehicle(vclass["id"], plate="BLK-X2")
    confirmed = create_confirmed_reservation(account["id"], vclass["id"], trip_type="POINT_TO_POINT",
                                             pickup_at="2026-07-14T12:00:00Z",
                                             planned_drop_at="2026-07-14T13:00:00Z", estimated_miles=10)
    asg = assign_in_house(confirmed["id"], drv["id"], veh["id"], confirmed["version"])
    assert asg["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Corner/calculations/calc_flight_delay_window_shift_on_assigned_reservation
# ---------------------------------------------------------------------------
def test_flight_delay_shifts_assignment_window_on_assigned_reservation():
    """PRD §3.6: "When a non-landing update crosses into DELAYED and the linked
    reservation is ASSIGNED with exactly one ACTIVE assignment, the system slides
    that assignment's window_start_at and window_end_at forward by the incremental
    difference between the current delay and the shift already applied"

    Design: Corner/calculations/calc_flight_delay_window_shift_on_assigned_reservation
    """
    ctx = setup_assigned_airport_reservation(
        scheduled_arrival_at="2026-08-09T15:00:00Z",
        pickup_at="2026-08-09T15:30:00Z",
        planned_drop_at="2026-08-09T16:30:00Z",
    )
    flight = push_flight_update(ctx["flight_tracking_id"], estimated_arrival_at="2026-08-09T15:40:00Z")
    assert flight["status"] == "DELAYED"
    asg = validate_success(api_client.get_assignment(ctx["assignment_id"], DISPATCHER), 200)
    assert asg["window_start_at"] == "2026-08-09T16:10:00Z", (
        f"window start shifts +40 min, got {asg['window_start_at']}"
    )
    assert asg["window_end_at"] == "2026-08-09T17:10:00Z", (
        f"window end shifts +40 min, got {asg['window_end_at']}"
    )
