"""Cascading unwinds, rate exhaust/revive cycle, and conserved-quantity invariants."""
from test_helpers import (
    validate_success,
    make_approved_trip, make_credit_from_cancelled_nonref,
    book, cancel_booking, cancel_trip, trip_version,
    make_policy, make_traveler, make_trip, submit_trip,
    first_credit_for_origin, credits_for_traveler, assert_credit_value_conserved,
    get_credit,
    TEST_USERS,
)

MGR = TEST_USERS["travel_manager_headers"]


def _booked_nonref_with_rate(cap_usage_count=1):
    """Approved trip + one NONREFUNDABLE AIR booking consuming a rate at the given cap."""
    ctx = make_approved_trip(with_rate=True, market_estimate=420000,
                             rate_overrides={"cap_usage_count": cap_usage_count},
                             trip_overrides={"return_date": "2026-08-20T09:00:00Z"})
    trip, trav, ven, rate = ctx["trip"], ctx["traveler"], ctx["vendor"], ctx["rate"]
    booking = book(trip["id"], trav["id"], trip["version"], vendor_id=ven["id"],
                   negotiated_rate_id=rate["id"], segment_type="AIR",
                   fare_basis="NONREFUNDABLE", fare_cents=250000)
    ctx["booking"] = booking
    return ctx


# ─── Rate exhaust/reactivate cycle ────────────────────
def test_rate_exhausts_when_consumption_reaches_cap(api):
    """PRD §3.1: "A rate is `ACTIVE` while its `consumed_count` is below its
    `cap_usage_count` and becomes `EXHAUSTED` the moment `consumed_count` reaches or
    exceeds `cap_usage_count`."

    Design: Difficulty/non_linear_state_machine/negotiated_rate_exhaust_then_reactivate_cycle
    """
    ctx = _booked_nonref_with_rate(cap_usage_count=1)
    rate = validate_success(api.get_negotiated_rate(ctx["rate"]["id"], MGR))
    assert rate["consumed_count"] == 1, f"consumed_count should be 1, got {rate['consumed_count']}"
    assert rate["status"] == "EXHAUSTED", f"rate at cap should be EXHAUSTED, got {rate['status']}"


def test_rate_reactivates_when_cancel_drops_below_cap(api):
    """PRD §3.1: "when a cancellation or refund lowers `consumed_count` back below
    `cap_usage_count` and the current clock is still at or before `valid_to`, an
    exhausted rate returns to `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/negotiated_rate_exhaust_then_reactivate_cycle
    """
    ctx = _booked_nonref_with_rate(cap_usage_count=1)
    cancel_booking(ctx["booking"]["id"], ctx["traveler"]["id"])
    rate = validate_success(api.get_negotiated_rate(ctx["rate"]["id"], MGR))
    assert rate["consumed_count"] == 0, f"consumed_count should return to 0, got {rate['consumed_count']}"
    assert rate["status"] == "ACTIVE", f"rate should revive to ACTIVE, got {rate['status']}"


# ─── Trip cancel: three-hop cascade ───────────────────
def test_trip_cancel_cascades_to_booking_and_mints_credit(api):
    """PRD §3.4: "Every non-terminal booking of the trip is cancelled or refunded according
    to its own `fare_basis` exactly as above."
    PRD §3.4: "A `NONREFUNDABLE` booking moves to `CANCELLED` and mints an
    `UnusedTicketCredit` whose `face_value_cents` and initial `residual_value_cents` both
    equal the cancelled booking's `fare_cents`."

    Design: Difficulty/transitive_cascade/trip_cancel_three_hop_cascade
    """
    ctx = _booked_nonref_with_rate(cap_usage_count=1)
    trip, trav, booking = ctx["trip"], ctx["traveler"], ctx["booking"]
    cancel_trip(trip["id"], trav["id"])
    trip_after = validate_success(api.get_trip_request(trip["id"], MGR))
    booking_after = validate_success(api.get_booking(booking["id"], MGR))
    assert trip_after["status"] == "CANCELLED", f"trip should be CANCELLED, got {trip_after['status']}"
    assert booking_after["status"] == "CANCELLED", f"booking should be CANCELLED, got {booking_after['status']}"
    credit = first_credit_for_origin(booking["id"], trav["id"])
    assert credit["face_value_cents"] == 250000, (
        f"minted credit face value should equal the cancelled fare 250000, got {credit['face_value_cents']}"
    )


def test_trip_cancel_releases_and_revives_exhausted_rate(api):
    """PRD §3.4: "any negotiated rate whose `consumed_count` thereby drops below its
    `cap_usage_count` transitions from `EXHAUSTED` back to `ACTIVE`."

    Design: Difficulty/transitive_cascade/trip_cancel_three_hop_cascade
    """
    ctx = _booked_nonref_with_rate(cap_usage_count=1)
    cancel_trip(ctx["trip"]["id"], ctx["traveler"]["id"])
    rate = validate_success(api.get_negotiated_rate(ctx["rate"]["id"], MGR))
    assert rate["status"] == "ACTIVE", f"rate should revive to ACTIVE, got {rate['status']}"
    assert rate["consumed_count"] == 0, f"consumed_count should drop to 0, got {rate['consumed_count']}"


# ─── Traveler suspend: two-hop cascade ────────────────
def _pending_trip_for_suspend():
    policy = make_policy()
    trav = make_traveler(policy["id"])
    trip = make_trip(trav["id"], market_estimate_cents=200000)
    trip = submit_trip(trip["id"], trav["id"])  # -> PENDING_MANAGER
    return trav, trip


def test_suspend_marks_traveler_suspended(api):
    """PRD §3.1: "A `TravelManager` may suspend an active traveler, moving `status` to
    `SUSPENDED`."

    Design: Difficulty/transitive_cascade/traveler_suspend_two_hop_cascade
    """
    trav, trip = _pending_trip_for_suspend()
    suspended = validate_success(api.suspend_traveler(trav["id"], MGR))
    assert suspended["status"] == "SUSPENDED", f"traveler should be SUSPENDED, got {suspended['status']}"


def test_suspend_cascade_cancels_pending_trip(api):
    """PRD §3.1: "suspension cascades, cancelling every trip request of that traveler
    currently in `DRAFT`, `PENDING_MANAGER`, or `PENDING_EXEC` by transitioning each to
    `CANCELLED`."

    Design: Difficulty/transitive_cascade/traveler_suspend_two_hop_cascade
    """
    trav, trip = _pending_trip_for_suspend()
    validate_success(api.suspend_traveler(trav["id"], MGR))
    trip_after = validate_success(api.get_trip_request(trip["id"], MGR))
    assert trip_after["status"] == "CANCELLED", (
        f"the traveler's PENDING_MANAGER trip should cascade to CANCELLED, got {trip_after['status']}"
    )


# ─── Conserved credit value on partial redemption ─────
def _partial_redemption():
    ctx = make_credit_from_cancelled_nonref(fare_cents=250000)
    trav, ven, trip, credit = ctx["traveler"], ctx["vendor"], ctx["trip"], ctx["credit"]
    v = trip_version(trip["id"], trav["id"])
    redeeming = book(trip["id"], trav["id"], v, vendor_id=ven["id"], segment_type="AIR",
                     fare_basis="REFUNDABLE", fare_cents=180000, redeem_credit_id=credit["id"],
                     depart_datetime="2026-08-10T09:00:00Z", return_datetime="2026-08-10T20:00:00Z")
    credit_after = get_credit(credit["id"])
    return redeeming, credit_after


def test_partial_redemption_applies_min_and_leaves_residual(api):
    """PRD §3.3: "The amount applied, recorded as `credit_applied_cents`, is the smaller of
    the credit's residual value before this redemption and the booking's `fare_cents`."
    PRD §3.3: "if residual remains, the credit becomes `PARTIALLY_USED`."

    Design: Difficulty/compensating_invariant/unused_credit_value_conserved_on_redemption
    """
    redeeming, credit_after = _partial_redemption()
    assert redeeming["credit_applied_cents"] == 180000, (
        f"applied should be min(250000, 180000) = 180000, got {redeeming['credit_applied_cents']}"
    )
    assert credit_after["residual_value_cents"] == 70000, (
        f"residual should be 250000-180000 = 70000, got {credit_after['residual_value_cents']}"
    )
    assert credit_after["status"] == "PARTIALLY_USED", (
        f"partially drawn credit should be PARTIALLY_USED, got {credit_after['status']}"
    )


def test_credit_value_conserved_across_partial_redemption(api):
    """PRD §3.5: "A credit's `residual_value_cents` is always its `face_value_cents` minus
    the total applied across every booking that has drawn on it; value is neither created
    nor destroyed, so face value always equals residual plus applied-to-date."

    Design: Difficulty/compensating_invariant/unused_credit_value_conserved_on_redemption
    """
    _redeeming, credit_after = _partial_redemption()
    assert credit_after["face_value_cents"] == 250000
    assert_credit_value_conserved(credit_after, applied_total=180000)


# ─── Conserved usage count on cancel ──────────────────
def _two_rate_bookings():
    ctx = make_approved_trip(with_rate=True, market_estimate=420000,
                             rate_overrides={"cap_usage_count": 2},
                             trip_overrides={"return_date": "2026-08-20T09:00:00Z"})
    trip, trav, ven, rate = ctx["trip"], ctx["traveler"], ctx["vendor"], ctx["rate"]
    b1 = book(trip["id"], trav["id"], trip["version"], vendor_id=ven["id"],
              negotiated_rate_id=rate["id"], segment_type="AIR", fare_basis="NONREFUNDABLE",
              fare_cents=250000, depart_datetime="2026-08-01T09:00:00Z",
              return_datetime="2026-08-01T20:00:00Z")
    v2 = trip_version(trip["id"], trav["id"])
    b2 = book(trip["id"], trav["id"], v2, vendor_id=ven["id"], negotiated_rate_id=rate["id"],
              segment_type="AIR", fare_basis="NONREFUNDABLE", fare_cents=250000,
              depart_datetime="2026-08-10T09:00:00Z", return_datetime="2026-08-10T20:00:00Z")
    ctx["b1"], ctx["b2"] = b1, b2
    return ctx


def test_rate_reaches_cap_when_both_segments_consume(api):
    """PRD §3.1: "The number of bookings currently consuming a rate — its `consumed_count`
    — is at all times the count of bookings that reference the rate through
    `negotiated_rate_id` and are in either `TICKETED` or `EXCHANGED` status."

    Design: Difficulty/compensating_invariant/rate_usage_count_conserved_on_cancel
    """
    ctx = _two_rate_bookings()
    rate = validate_success(api.get_negotiated_rate(ctx["rate"]["id"], MGR))
    assert rate["consumed_count"] == 2, f"two consuming bookings -> consumed 2, got {rate['consumed_count']}"
    assert rate["status"] == "EXHAUSTED", f"at cap 2 the rate is EXHAUSTED, got {rate['status']}"


def test_rate_count_restored_after_one_cancel(api):
    """PRD §3.1: "conversely, when a cancellation or refund lowers `consumed_count` back
    below `cap_usage_count` and the current clock is still at or before `valid_to`, an
    exhausted rate returns to `ACTIVE`."

    Design: Difficulty/compensating_invariant/rate_usage_count_conserved_on_cancel
    """
    ctx = _two_rate_bookings()
    cancel_booking(ctx["b1"]["id"], ctx["traveler"]["id"])
    rate = validate_success(api.get_negotiated_rate(ctx["rate"]["id"], MGR))
    assert rate["consumed_count"] == 1, f"one remaining consuming booking -> consumed 1, got {rate['consumed_count']}"
    assert rate["status"] == "ACTIVE", f"below cap the rate is ACTIVE, got {rate['status']}"
    assert rate["cap_usage_count"] == 2, "cap is immutable at 2 (remaining + consumed conserved)"
