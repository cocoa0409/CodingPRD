"""Booking cyclic state machine, late-cancel boundary, and slot-count
conservation.

Queue A (Difficulty):
non_linear_state_machine/booking_confirmed_suspended_confirmed_cycle,
boundary_precision_check/late_cancel_at_exactly_24h_no_penalty,
compensating_invariant/amenity_slot_conserved_confirm_then_cancel.
"""
from test_helpers import (
    fixtures as fx,
    make_resident_headers,
    validate_success,
    validate_paginated,
)


def _setup_future_gym_booking(api, clock="2026-05-20T00:00:00Z",
                              start="2026-06-10T10:00:00Z", end="2026-06-10T12:00:00Z",
                              deposit_cents=10000):
    base = fx.setup_amenity_booking_base(
        api, clock=clock,
        resident_overrides={"full_name": "Eve", "email": "eve@x.com", "membership_tier": "STANDARD"},
        amenity_overrides={
            "name": "Gym", "amenity_type": "GYM", "capacity": 1,
            "base_rate_cents_per_hour": 4000, "deposit_cents": deposit_cents,
            "buffer_minutes": 0, "open_minute": 0, "close_minute": 1440,
        },
    )
    booking = fx.new_booking(api, base["amenity"]["id"], base["resident"]["id"],
                             start, end, expected_version=base["amenity"]["version"])
    return base["resident"]["id"], booking["id"]


def test_booking_reconfirmed_after_payment_clears_delinquency(api):
    """PRD §3.3: "each of that resident's `SUSPENDED` bookings whose `start_at`
    is still in the future and whose window is still free of capacity and
    overlap conflicts is transitioned from `SUSPENDED` back to `CONFIRMED`,
    re-placing its deposit hold by increasing `hold_balance_cents` by
    `deposit_hold_cents`."

    A future CONFIRMED booking is suspended by a 60000 charge then re-confirmed
    by a full 60000 payment, with its 10000 hold re-placed.

    Design: Difficulty/non_linear_state_machine/booking_confirmed_suspended_confirmed_cycle
    """
    resident_id, booking_id = _setup_future_gym_booking(api)
    fx.charge_resident(api, resident_id, 60000, "June rent")
    fx.pay_resident(api, resident_id, 60000)

    booking = fx.get_booking(api, booking_id)
    assert booking["status"] == "CONFIRMED"
    resident = fx.get_resident(api, resident_id)
    assert resident["hold_balance_cents"] == 10000, "deposit hold re-placed on re-confirm"


def test_resident_returns_to_good_standing_after_payment(api):
    """PRD §2.7: "if the balance is strictly greater than 150000 cents the
    resident becomes `SUSPENDED`; otherwise, if the balance is strictly greater
    than 50000 cents the resident becomes `DELINQUENT`; otherwise the resident
    is `GOOD_STANDING`."

    After a 60000 charge (DELINQUENT) and an equal 60000 payment, the balance
    returns to 0 and posture returns to GOOD_STANDING — closing the cycle.

    Design: Difficulty/non_linear_state_machine/booking_confirmed_suspended_confirmed_cycle
    """
    resident_id, _ = _setup_future_gym_booking(api)
    fx.charge_resident(api, resident_id, 60000, "June rent")
    fx.pay_resident(api, resident_id, 60000)

    resident = fx.get_resident(api, resident_id)
    assert resident["account_status"] == "GOOD_STANDING"


def _setup_exactly_24h_booking(api):
    """clock 2026-06-01 00:00; booking 2026-06-02 00:00-02:00 (exactly 24h out)
    on a deposit-10000 amenity."""
    base = fx.setup_amenity_booking_base(
        api, clock="2026-06-01T00:00:00Z",
        resident_overrides={"full_name": "Ivy", "email": "ivy@x.com", "membership_tier": "STANDARD"},
        amenity_overrides={
            "name": "Gym", "amenity_type": "GYM", "capacity": 1,
            "base_rate_cents_per_hour": 4000, "deposit_cents": 10000,
            "buffer_minutes": 0, "open_minute": 0, "close_minute": 1440,
        },
    )
    booking = fx.new_booking(api, base["amenity"]["id"], base["resident"]["id"],
                             "2026-06-02T00:00:00Z", "2026-06-02T02:00:00Z",
                             expected_version=base["amenity"]["version"])
    return base["resident"]["id"], booking["id"]


def test_cancel_at_exactly_24h_incurs_no_penalty(api):
    """PRD §3.2: "If that lead time is at least the late-cancel window of 24
    hours, the penalty is zero and the full deposit hold is simply released."

    Cancelling exactly 24h before start (lead time == 24h) charges no penalty:
    rent_balance stays 0.

    Design: Difficulty/boundary_precision_check/late_cancel_at_exactly_24h_no_penalty
    """
    resident_id, booking_id = _setup_exactly_24h_booking(api)
    cancelled = validate_success(api.cancel_booking(booking_id, make_resident_headers(resident_id)))
    assert cancelled["status"] == "CANCELLED"

    resident = fx.get_resident(api, resident_id)
    assert resident["rent_balance_cents"] == 0, "no penalty at exactly 24h"


def test_cancel_at_exactly_24h_releases_full_hold(api):
    """PRD §3.2: "If that lead time is at least the late-cancel window of 24
    hours, the penalty is zero and the full deposit hold is simply released."

    The full 10000 deposit hold is released on the no-penalty cancellation.

    Design: Difficulty/boundary_precision_check/late_cancel_at_exactly_24h_no_penalty
    """
    resident_id, booking_id = _setup_exactly_24h_booking(api)
    validate_success(api.cancel_booking(booking_id, make_resident_headers(resident_id)))

    resident = fx.get_resident(api, resident_id)
    assert resident["hold_balance_cents"] == 0, "hold fully released"


def _setup_cancellable_gym(api):
    base = fx.setup_amenity_booking_base(
        api, clock="2026-06-01T00:00:00Z",
        resident_overrides={"full_name": "Quin", "email": "quin@x.com"},
        amenity_overrides={
            "name": "Gym", "amenity_type": "GYM", "capacity": 1,
            "base_rate_cents_per_hour": 4000, "deposit_cents": 0,
            "buffer_minutes": 0, "open_minute": 0, "close_minute": 1440,
        },
    )
    return base


def test_slot_reusable_after_confirm_then_cancel(api):
    """PRD §3.2: "A confirm that places a booking and its compensating cancel
    that releases it leave occupancy unchanged at every instant."

    Booking A on a capacity-1 amenity then cancelling A frees the slot, so
    booking B on the identical window is admitted CONFIRMED.

    Design: Difficulty/compensating_invariant/amenity_slot_conserved_confirm_then_cancel
    """
    base = _setup_cancellable_gym(api)
    amenity_id = base["amenity"]["id"]
    resident_id = base["resident"]["id"]
    booking_a = fx.new_booking(api, amenity_id, resident_id,
                               "2026-06-08T10:00:00Z", "2026-06-08T11:00:00Z",
                               expected_version=base["amenity"]["version"])
    validate_success(api.cancel_booking(booking_a["id"], make_resident_headers(resident_id)))

    booking_b = fx.new_booking(api, amenity_id, resident_id,
                               "2026-06-08T10:00:00Z", "2026-06-08T11:00:00Z")
    assert booking_b["status"] == "CONFIRMED"


def test_only_the_second_booking_occupies_the_slot(api):
    """PRD §3.2: "occupancy at any instant counts bookings in `CONFIRMED` or
    `CHECKED_IN` status whose half-open window covers that instant, and this
    count including the new booking must not exceed `capacity`."

    After cancel-then-rebook, exactly one CONFIRMED booking occupies the window
    (the cancelled one no longer counts), so occupancy conservation holds.

    Design: Difficulty/compensating_invariant/amenity_slot_conserved_confirm_then_cancel
    """
    base = _setup_cancellable_gym(api)
    amenity_id = base["amenity"]["id"]
    resident_id = base["resident"]["id"]
    booking_a = fx.new_booking(api, amenity_id, resident_id,
                               "2026-06-08T10:00:00Z", "2026-06-08T11:00:00Z",
                               expected_version=base["amenity"]["version"])
    validate_success(api.cancel_booking(booking_a["id"], make_resident_headers(resident_id)))
    fx.new_booking(api, amenity_id, resident_id,
                   "2026-06-08T10:00:00Z", "2026-06-08T11:00:00Z")

    data, meta = validate_paginated(
        api.list_bookings(fx.PM, params={"amenity_id": amenity_id, "status": "CONFIRMED"})
    )
    assert meta["total_count"] == 1, "only the re-booked slot is CONFIRMED"
