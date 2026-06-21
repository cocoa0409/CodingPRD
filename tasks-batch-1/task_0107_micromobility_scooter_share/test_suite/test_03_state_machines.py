"""State-machine behavior: the cyclic ACTIVE<->PAUSED trip loop, the Fine
DISPUTED branch to WAIVED, invalid transitions, terminal-state lockdown, and
precondition-gated transitions (cancel grace window, reinstate with fines, end
in a no-ride zone).
"""
from test_helpers import (
    validate_success,
    validate_error,
    make_rider_headers,
    ApiErrorId,
    TEST_USERS,
    fixtures as fx,
)

_ADMIN = TEST_USERS["admin_headers"]


def test_trip_active_paused_cycle_repeats(api):
    """PRD §3.4: "A trip may cycle between `ACTIVE` and `PAUSED` any number of
    times."

    Pause, resume, then pause again all succeed; after the second pause the trip
    is PAUSED — a linear pipeline could not revisit PAUSED after returning to
    ACTIVE.

    Design: Difficulty/non_linear_state_machine/trip_active_paused_cycle_repeats
    """
    plan, zone, vehicle = fx.setup_world()
    rider = fx.create_funded_rider(plan["id"])
    headers = make_rider_headers(rider["id"])
    trip = fx.start_trip(rider, vehicle, "2026-06-04T00:00:00Z")
    fx.set_clock("2026-06-04T00:02:00Z")
    validate_success(api.pause_trip(trip["id"], headers))
    fx.set_clock("2026-06-04T00:03:00Z")
    validate_success(api.resume_trip(trip["id"], headers))
    fx.set_clock("2026-06-04T00:04:00Z")
    after_2nd = validate_success(api.pause_trip(trip["id"], headers))
    assert after_2nd["status"] == "PAUSED", (
        f"expected PAUSED after second pause, got {after_2nd['status']}")


def test_trip_resumes_back_to_active_in_cycle(api):
    """PRD §3.4: "Resuming a `PAUSED` trip transitions it `PAUSED → ACTIVE`,
    closing the open pause segment and opening a new ride segment whose `started_at`
    is the current clock and whose `zone_id` is the vehicle's current zone."

    After a pause, resume returns the trip to ACTIVE — the loop can re-enter
    ACTIVE, demonstrating the cycle.

    Design: Difficulty/non_linear_state_machine/trip_active_paused_cycle_repeats
    """
    plan, zone, vehicle = fx.setup_world()
    rider = fx.create_funded_rider(plan["id"])
    headers = make_rider_headers(rider["id"])
    trip = fx.start_trip(rider, vehicle, "2026-06-04T00:00:00Z")
    fx.set_clock("2026-06-04T00:02:00Z")
    validate_success(api.pause_trip(trip["id"], headers))
    fx.set_clock("2026-06-04T00:03:00Z")
    resumed = validate_success(api.resume_trip(trip["id"], headers))
    assert resumed["status"] == "ACTIVE", (
        f"expected ACTIVE after resume, got {resumed['status']}")


def test_fine_disputed_branches_to_waived(api):
    """PRD §3.6: "Waiving the fine instead transitions it `DISPUTED → WAIVED`,
    which is terminal, and reverses the original charge: a `WalletTransaction` of
    type `FINE_REFUND` is created carrying the positive `amount_cents`,
    `Rider.wallet_balance_cents` is increased by the fine amount, and
    `Rider.outstanding_fine_cents` is reduced by the fine amount."

    A fine disputed, rejected back to PENDING, disputed again, then waived ends in
    WAIVED with outstanding cleared to 0.

    Design: Difficulty/non_linear_state_machine/fine_disputed_branches_to_waived_or_pending
    """
    plan, ok_zone, np_zone, vehicle, rider, trip, fine = fx.setup_trip_ended_in_no_park(
        "2026-06-05T00:00:00Z", "2026-06-05T00:01:30Z", amount_cents=5000)
    headers = make_rider_headers(rider["id"])
    validate_success(api.dispute_fine(fine["id"], headers))
    validate_success(api.reject_dispute_fine(fine["id"], _ADMIN))
    validate_success(api.dispute_fine(fine["id"], headers))
    waived = validate_success(api.waive_fine(fine["id"], _ADMIN))
    assert waived["settlement_status"] == "WAIVED", (
        f"expected WAIVED, got {waived['settlement_status']}")
    rider_after = validate_success(api.get_rider(rider["id"], headers))
    assert rider_after["outstanding_fine_cents"] == 0, (
        f"expected outstanding 0 after waive, got {rider_after['outstanding_fine_cents']}")


def test_fine_reject_dispute_returns_to_pending(api):
    """PRD §3.6: "Rejecting the dispute returns the fine `DISPUTED → PENDING`,
    restoring it to the collectible pool with no monetary effect — and a fine may
    cycle between `PENDING` and `DISPUTED` repeatedly as it is disputed and
    rejected."

    The PENDING<->DISPUTED cycle: dispute then reject-dispute returns the fine to
    PENDING (so it can be disputed again).

    Design: Difficulty/non_linear_state_machine/fine_disputed_branches_to_waived_or_pending
    """
    plan, ok_zone, np_zone, vehicle, rider, trip, fine = fx.setup_trip_ended_in_no_park(
        "2026-06-05T00:00:00Z", "2026-06-05T00:01:30Z", amount_cents=5000)
    headers = make_rider_headers(rider["id"])
    validate_success(api.dispute_fine(fine["id"], headers))
    rejected = validate_success(api.reject_dispute_fine(fine["id"], _ADMIN))
    assert rejected["settlement_status"] == "PENDING", (
        f"expected PENDING after reject-dispute, got {rejected['settlement_status']}")


def test_pause_completed_trip_invalid_state(api):
    """PRD §3.4: "A rider may pause an `ACTIVE` trip, transitioning it
    `ACTIVE → PAUSED`."
    PRD §2.8: "Only after these gates does the system evaluate state-machine
    legality (`ERR_INVALID_STATE`), then the domain-specific business rules
    described in §3, and finally field-level shape validation (`ERR_INVALID_REQUEST`)
    for missing required fields, invalid enum members, or out-of-range numeric
    values on any create or action body."

    Pausing a COMPLETED trip is undefined and returns ERR_INVALID_STATE (409).

    Design: Corner/state_machines/pause_already_completed_trip_returns_invalid_state
    """
    plan, zone, vehicle, rider, trip = fx.setup_completed_trip(
        "2026-07-01T00:00:00Z", "2026-07-01T00:05:00Z")
    headers = make_rider_headers(rider["id"])
    resp = api.pause_trip(trip["id"], headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_resume_active_trip_invalid_state(api):
    """PRD §3.4: "Resuming a `PAUSED` trip transitions it `PAUSED → ACTIVE`,
    closing the open pause segment and opening a new ride segment whose `started_at`
    is the current clock and whose `zone_id` is the vehicle's current zone."
    PRD §2.8: "Only after these gates does the system evaluate state-machine
    legality (`ERR_INVALID_STATE`), then the domain-specific business rules
    described in §3, and finally field-level shape validation (`ERR_INVALID_REQUEST`)
    for missing required fields, invalid enum members, or out-of-range numeric
    values on any create or action body."

    Resuming an ACTIVE (not PAUSED) trip is undefined and returns
    ERR_INVALID_STATE (409).

    Design: Corner/state_machines/resume_active_trip_returns_invalid_state
    """
    plan, zone, vehicle, rider, trip = fx.setup_active_trip("2026-07-02T00:00:00Z")
    headers = make_rider_headers(rider["id"])
    resp = api.resume_trip(trip["id"], headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_return_retired_vehicle_to_service_invalid_state(api):
    """PRD §3.1: "A `MAINTENANCE` vehicle may instead be retired, transitioning
    `MAINTENANCE → RETIRED`, which is terminal."
    PRD §2.8: "Only after these gates does the system evaluate state-machine
    legality (`ERR_INVALID_STATE`), then the domain-specific business rules
    described in §3, and finally field-level shape validation (`ERR_INVALID_REQUEST`)
    for missing required fields, invalid enum members, or out-of-range numeric
    values on any create or action body."

    A RETIRED vehicle is terminal; return-to-service from RETIRED is undefined and
    returns ERR_INVALID_STATE (409).

    Design: Corner/state_machines/retired_vehicle_terminal_no_further_transitions
    """
    zone = fx.create_zone(zone_type="RIDE_OK", priority=5)
    vehicle = fx.create_vehicle(zone["id"])
    validate_success(api.vehicle_maintenance(vehicle["id"], _ADMIN))
    validate_success(api.vehicle_retire(vehicle["id"], _ADMIN))
    resp = api.vehicle_return_to_service(vehicle["id"], _ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_cancel_after_grace_window_invalid_state(api):
    """PRD §3.5: "cancellation is permitted only while the trip is `ACTIVE` and
    only within 120 seconds of `started_at` (the elapsed time from `started_at` to
    now must be at most 120 seconds)."
    PRD §2.8: "Only after these gates does the system evaluate state-machine
    legality (`ERR_INVALID_STATE`), then the domain-specific business rules
    described in §3, and finally field-level shape validation (`ERR_INVALID_REQUEST`)
    for missing required fields, invalid enum members, or out-of-range numeric
    values on any create or action body."

    Cancelling 180s after start (> 120s grace) fails the cancel precondition and
    returns ERR_INVALID_STATE (409); the trip stays ACTIVE.

    Design: Corner/state_machines/cancel_after_grace_window_returns_invalid_state
    """
    plan, zone, vehicle, rider, trip = fx.setup_active_trip("2026-07-03T00:00:00Z")
    headers = make_rider_headers(rider["id"])
    fx.set_clock("2026-07-03T00:03:00Z")
    resp = api.cancel_trip(trip["id"], headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_trip(trip["id"], headers))
    assert after["status"] == "ACTIVE", f"expected trip to stay ACTIVE, got {after['status']}"


def test_cancel_within_grace_succeeds_no_charge(api):
    """PRD §3.5: "Cancelling closes all open segments, sets `final_fare_cents` and
    `billable_minutes` to 0, and returns the vehicle `IN_USE → AVAILABLE` without
    changing its zone. No wallet charge is created for a cancelled trip."

    Cancelling 60s after start (<= 120s grace) sets final_fare_cents to 0, leaves
    the wallet at 5000, and returns the vehicle to AVAILABLE.

    Design: Corner/state_machines/cancel_within_grace_succeeds_no_charge
    """
    plan, zone, vehicle, rider, trip = fx.setup_active_trip("2026-07-04T00:00:00Z")
    headers = make_rider_headers(rider["id"])
    fx.set_clock("2026-07-04T00:01:00Z")
    cancelled = validate_success(api.cancel_trip(trip["id"], headers))
    assert cancelled["status"] == "CANCELLED", f"expected CANCELLED, got {cancelled['status']}"
    assert cancelled["final_fare_cents"] == 0, (
        f"expected final_fare_cents 0, got {cancelled['final_fare_cents']}")
    rider_after = validate_success(api.get_rider(rider["id"], headers))
    assert rider_after["wallet_balance_cents"] == 5000, (
        f"expected wallet untouched at 5000, got {rider_after['wallet_balance_cents']}")
    veh_after = validate_success(api.get_vehicle(vehicle["id"], _ADMIN))
    assert veh_after["status"] == "AVAILABLE", f"expected AVAILABLE, got {veh_after['status']}"


def test_reinstate_with_outstanding_fines_rejected(api):
    """PRD §3.2: "Reinstating a `SUSPENDED` rider transitions it
    `SUSPENDED → ACTIVE`, but only when the rider's `outstanding_fine_cents` is
    exactly 0; attempting to reinstate a rider who still owes a balance is rejected
    with `ERR_OUTSTANDING_FINES`."

    A rider with a PENDING NO_PARK fine (outstanding 2500) who is then SUSPENDED
    cannot be reinstated; the call returns ERR_OUTSTANDING_FINES (422) and the
    rider stays SUSPENDED.

    Design: Corner/state_machines/reinstate_with_outstanding_fines_rejected
    """
    plan, ok_zone, np_zone, vehicle, rider, trip, fine = fx.setup_trip_ended_in_no_park(
        "2026-07-05T00:00:00Z", "2026-07-05T00:01:30Z", amount_cents=5000)
    validate_success(api.suspend_rider(rider["id"], _ADMIN))
    resp = api.reinstate_rider(rider["id"], _ADMIN)
    validate_error(resp, ApiErrorId.ERR_OUTSTANDING_FINES.value)
    after = validate_success(api.get_rider(rider["id"], make_rider_headers(rider["id"])))
    assert after["status"] == "SUSPENDED", f"expected SUSPENDED, got {after['status']}"


def test_end_active_trip_in_no_ride_zone_rejected(api):
    """PRD §3.5: "ending in a no-ride zone is rejected with
    `ERR_END_IN_NO_RIDE_ZONE`, and the rider must walk the vehicle out of such a
    zone before ending."

    Ending an ACTIVE trip in a NO_RIDE end zone returns ERR_END_IN_NO_RIDE_ZONE
    (422); the trip stays ACTIVE.

    Design: Corner/state_machines/end_active_trip_in_no_ride_zone_returns_422
    """
    plan, zone, vehicle, rider, trip = fx.setup_active_trip("2026-07-24T00:00:00Z")
    no_ride = fx.create_zone(zone_type="NO_RIDE", priority=2)
    headers = make_rider_headers(rider["id"])
    fx.set_clock("2026-07-24T00:02:00Z")
    resp = api.end_trip(trip["id"], {"end_zone_id": no_ride["id"]}, headers)
    validate_error(resp, ApiErrorId.ERR_END_IN_NO_RIDE_ZONE.value)
    after = validate_success(api.get_trip(trip["id"], headers))
    assert after["status"] == "ACTIVE", f"expected trip to stay ACTIVE, got {after['status']}"
