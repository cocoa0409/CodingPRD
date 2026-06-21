"""Reservation seat lifecycle, parallel status axes, and conserved invariants
(PRD §2.5, §3.5, §3.6, §3.7).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_driver_headers, make_rider_headers, make_program_admin_headers,
    setup_active_pool, create_trip, create_reservation,
)

PA = make_program_admin_headers()


def test_reservation_status_axes_evolve_independently(api):
    """PRD §3.6: "A reservation is born with `reservation_status` of `RESERVED` and
    `payment_status` of `PENDING` — the two axes evolve independently, one governing
    the seat lifecycle and the other the money lifecycle."
    PRD §3.6: "A no-show ... moves `reservation_status` to `NO_SHOW`; if
    `payment_status` was `CHARGED`, the `estimate_cost_share_cents` is retained as a
    no-show penalty and `payment_status` becomes `SETTLED`".

    After pay_now: RESERVED / CHARGED. After depart no-show cascade: the seat axis
    is NO_SHOW while the money axis is SETTLED — different values at the same instant.

    Design: Difficulty/non_linear_state_machine/reservation_parallel_status_axes_evolve_independently
    """
    ctx = setup_active_pool(api=api, seed_rider_name="Rae", seed_rider_wallet=50000)
    drv_id, pool_id = ctx["driver_id"], ctx["pool_id"]
    rider = ctx["seed"]
    trip = create_trip(pool_id, drv_id, api=api, distance_miles=10.0)
    res = validate_success(api.create_reservation(
        {"trip_id": trip["id"], "rider_member_id": rider["id"],
         "expected_trip_version": trip["version"], "seat_count": 1, "pay_now": True},
        make_rider_headers(rider["id"])), expected_status=201)
    assert res["reservation_status"] == "RESERVED"
    assert res["payment_status"] == "CHARGED"

    get_success_data(api.open_boarding_trip(trip["id"], make_driver_headers(drv_id)))
    get_success_data(api.depart_trip(trip["id"], make_driver_headers(drv_id)))
    after = get_success_data(api.get_reservation(res["id"], make_driver_headers(drv_id)))
    assert after["reservation_status"] == "NO_SHOW"
    assert after["payment_status"] == "SETTLED"


def test_seat_count_conserved_when_reservation_cancelled(api):
    """PRD §3.5: "The derived `seats_reserved` is the sum of `seat_count` over this
    trip's reservations whose `reservation_status` is `RESERVED`, `CHECKED_IN`, or
    `COMPLETED`."
    PRD §3.6: "The reservation moves to `CANCELLED`; ... The trip's `seats_reserved`
    is recomputed as the seat is released."

    Reserving 2 seats then cancelling restores seats_reserved to its pre-reserve
    value of 0 with no drift, and the charged amount is refunded to the wallet.

    Design: Difficulty/compensating_invariant/seat_conservation_reserve_then_cancel_leaves_seats_reserved
    """
    ctx = setup_active_pool(api=api, seed_rider_name="Rae", seed_rider_wallet=50000)
    drv_id, pool_id = ctx["driver_id"], ctx["pool_id"]
    rider = ctx["seed"]
    trip = create_trip(pool_id, drv_id, api=api, distance_miles=10.0)
    res = validate_success(api.create_reservation(
        {"trip_id": trip["id"], "rider_member_id": rider["id"],
         "expected_trip_version": trip["version"], "seat_count": 2, "pay_now": True},
        make_rider_headers(rider["id"])), expected_status=201)
    assert res["seat_count"] == 2

    cancelled = validate_success(api.cancel_reservation(res["id"], make_rider_headers(rider["id"])))
    assert cancelled["reservation_status"] == "CANCELLED"
    trip_after = get_success_data(api.get_trip(trip["id"], make_driver_headers(drv_id)))
    assert trip_after["seats_reserved"] == 0
    member = get_success_data(api.get_member(rider["id"], PA))
    assert member["wallet_balance_cents"] == 50000


def test_subsidy_consumed_conserved_when_reservation_cancelled_before_finalize(api):
    """PRD §3.10: "The program's derived `subsidy_consumed_cents` is exactly the
    signed sum of `amount_cents` across its entries".
    PRD §3.6: "If a subsidy debit had previously been recorded for this reservation,
    a `SubsidyLedgerEntry` credit of the negative `estimate_subsidy_cents` with
    reason `RESERVATION_CANCELLED` is appended".

    A reserve (no DEBIT recorded yet — subsidy debits only land at finalization)
    then cancel leaves subsidy_consumed_cents at 0 with no net ledger movement.

    Design: Difficulty/compensating_invariant/subsidy_budget_conservation_reserve_then_cancel_leaves_consumed
    """
    ctx = setup_active_pool(api=api, hov_eligible=True, seed_rider_name="Rae",
                            seed_rider_wallet=50000)
    prog_id, drv_id, pool_id = ctx["program_id"], ctx["driver_id"], ctx["pool_id"]
    rider = ctx["seed"]
    trip = create_trip(pool_id, drv_id, api=api, distance_miles=10.0, hov_lane_used=True)
    res = validate_success(api.create_reservation(
        {"trip_id": trip["id"], "rider_member_id": rider["id"],
         "expected_trip_version": trip["version"], "seat_count": 1, "pay_now": True},
        make_rider_headers(rider["id"])), expected_status=201)

    cancelled = validate_success(api.cancel_reservation(res["id"], make_rider_headers(rider["id"])))
    assert cancelled["reservation_status"] == "CANCELLED"
    program = get_success_data(api.get_employer_program(prog_id, PA))
    assert program["subsidy_consumed_cents"] == 0
    member = get_success_data(api.get_member(rider["id"], PA))
    assert member["wallet_balance_cents"] == 50000


def test_complete_trip_with_no_checked_in_riders_settles_seats_to_zero(api):
    """PRD §3.5: "Completing moves a trip from `IN_TRANSIT` to `COMPLETED`; this is
    the settlement event detailed in §3.6."
    PRD §3.7: "Then, for each `CHECKED_IN` reservation, the reservation moves to
    `COMPLETED`".

    With zero checked-in reservations the final inclusion set is empty, so the trip
    completes with no per-seat division and seats_reserved settles to 0.

    Design: Difficulty/boundary_precision_check/empty_completed_set_zero_division_guarded_on_complete
    """
    ctx = setup_active_pool(api=api, seed_rider_name="Rae", seed_rider_wallet=50000)
    drv_id, pool_id = ctx["driver_id"], ctx["pool_id"]
    trip = create_trip(pool_id, drv_id, api=api, distance_miles=10.0)
    get_success_data(api.open_boarding_trip(trip["id"], make_driver_headers(drv_id)))
    get_success_data(api.depart_trip(trip["id"], make_driver_headers(drv_id)))
    completed = validate_success(api.complete_trip(
        trip["id"], {"hov_lane_used": False}, make_driver_headers(drv_id)))
    assert completed["status"] == "COMPLETED"
    assert completed["seats_reserved"] == 0


def test_check_in_on_scheduled_trip_rejected_before_boarding(api):
    """PRD §3.6: "A `Driver` (or `PlatformOps`) checks a rider in while the owning
    trip is `BOARDING`, moving the reservation's `reservation_status` from
    `RESERVED` to `CHECKED_IN`."

    Checking in while the owning trip is still SCHEDULED (boarding not opened)
    returns ERR_INVALID_STATE.

    Design: Corner/state_machines/check_in_reservation_on_scheduled_trip_returns_invalid_state
    """
    ctx = setup_active_pool(api=api, seed_rider_name="Rae", seed_rider_wallet=50000)
    drv_id, pool_id = ctx["driver_id"], ctx["pool_id"]
    rider = ctx["seed"]
    trip = create_trip(pool_id, drv_id, api=api, distance_miles=10.0)
    res = create_reservation(trip["id"], rider["id"], trip["version"], api=api, seat_count=1)
    validate_error(api.check_in_reservation(res["id"], make_driver_headers(drv_id)),
                   ApiErrorId.ERR_INVALID_STATE.value)


def test_trip_cancel_cascade_is_visible_in_same_response(api):
    """PRD §2.5: "every cascade described in §3 completes before the triggering
    request responds."
    PRD §3.5: "Cancelling from `SCHEDULED` cascades every `RESERVED` reservation to
    `CANCELLED`".

    POST /trips/{id}/cancel returns the trip already CANCELLED with seats_reserved 0
    and the reservation already CANCELLED in the same response.

    Design: Corner/consistency_model/immediate_cascade_visible_in_same_response
    """
    ctx = setup_active_pool(api=api, seed_rider_name="Rae", seed_rider_wallet=50000)
    drv_id, pool_id = ctx["driver_id"], ctx["pool_id"]
    rider = ctx["seed"]
    trip = create_trip(pool_id, drv_id, api=api, distance_miles=10.0)
    res = create_reservation(trip["id"], rider["id"], trip["version"], api=api, seat_count=1)
    cancelled = validate_success(api.cancel_trip(trip["id"], make_driver_headers(drv_id)))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["seats_reserved"] == 0
    res_after = get_success_data(api.get_reservation(res["id"], make_driver_headers(drv_id)))
    assert res_after["reservation_status"] == "CANCELLED"
