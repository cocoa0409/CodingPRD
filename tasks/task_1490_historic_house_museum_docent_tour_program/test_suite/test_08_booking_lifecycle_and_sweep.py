"""Booking holds and refunds, the ops sweep, member lapse/renewal, and the
seat / revenue conservation invariants."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_slot_seat_conservation,
    cancel_booking,
    confirm_booking,
    create_general_booking,
    create_member,
    get_booking,
    get_slot,
    run_epoch,
    set_clock,
    setup_open_slot,
    validate_error,
    validate_success,
)

FRONT_DESK = TEST_USERS["front_desk_staff_headers"]


class TestRevenueProjectionVariants:
    """Identical booking data, two revenue readings: committed vs projected."""

    def _slot_with_confirmed_and_reserved(self):
        ctx = setup_open_slot()
        confirmed = create_general_booking(ctx["slot_id"], 2,
                                           visitor_name="Ann")
        confirm_booking(confirmed["id"], 2000)
        create_general_booking(ctx["slot_id"], 3, visitor_name="Bob")
        return ctx

    def test_revenue_committed_counts_confirmed_only(self):
        """PRD section 3.6: "`revenue_committed_cents` is the sum of
        `total_price_cents` over the slot's `CONFIRMED` bookings — money
        actually confirmed, nothing more."

        Design: Difficulty/dual_variant_calc/slot_revenue_projection_variants
        """
        ctx = self._slot_with_confirmed_and_reserved()
        slot = get_slot(ctx["slot_id"])
        assert slot["revenue_committed_cents"] == 2000, (
            f"committed must exclude the RESERVED 3000, "
            f"got {slot['revenue_committed_cents']}"
        )

    def test_revenue_projected_adds_discounted_reserved(self):
        """PRD section 3.6: "`revenue_projected_cents` adds a forward-looking
        uplift to the same committed base: the sum of `total_price_cents`
        over the slot's `RESERVED` bookings, multiplied by 0.8 and rounded
        half-up to a whole cent."

        Design: Difficulty/dual_variant_calc/slot_revenue_projection_variants
        """
        ctx = self._slot_with_confirmed_and_reserved()
        slot = get_slot(ctx["slot_id"])
        # 2000 + round_half_up(3000 * 0.8) = 2000 + 2400 = 4400
        assert slot["revenue_projected_cents"] == 4400, (
            f"projected must be 4400, got {slot['revenue_projected_cents']}"
        )
        assert slot["revenue_committed_cents"] \
            != slot["revenue_projected_cents"], (
                "committed and projected must differ while RESERVED bookings "
                "exist"
            )


class TestSeatBucketConservation:

    def test_reservation_moves_seats_between_buckets(self):
        """PRD section 3.6: "Creation immediately adds its `party_size` to
        the slot's `seats_reserved`, flips the slot from `OPEN` to `FULL` if
        `seats_available` reaches zero, and recomputes the slot's revenue."
        PRD section 3.4: "both `seats_reserved` and `seats_confirmed` start
        at zero, `seats_available` equals the snapshotted `capacity`".

        Design: Difficulty/compensating_invariant/seat_bucket_conservation
        """
        ctx = setup_open_slot()
        baseline = get_slot(ctx["slot_id"])
        assert baseline["capacity"] == 18
        assert (baseline["seats_reserved"], baseline["seats_confirmed"],
                baseline["seats_available"]) == (0, 0, 18)
        assert_slot_seat_conservation(baseline)

        create_general_booking(ctx["slot_id"], 4)
        after = get_slot(ctx["slot_id"])
        assert (after["seats_reserved"], after["seats_confirmed"],
                after["seats_available"]) == (4, 0, 14), (
            f"reserve of 4 must move buckets to (4, 0, 14), got "
            f"({after['seats_reserved']}, {after['seats_confirmed']}, "
            f"{after['seats_available']})"
        )
        assert_slot_seat_conservation(after)

    def test_cancel_returns_buckets_to_baseline(self):
        """PRD section 3.6: "Cancellation releases seats from whichever
        bucket the booking occupied — reserved or confirmed — and sets
        `refund_cents`, which is zero until the moment of cancellation."

        Design: Difficulty/compensating_invariant/seat_bucket_conservation
        """
        ctx = setup_open_slot()
        booking = create_general_booking(ctx["slot_id"], 4)
        cancel_booking(booking["id"])
        after = get_slot(ctx["slot_id"])
        assert (after["seats_reserved"], after["seats_confirmed"],
                after["seats_available"]) == (0, 0, 18), (
            "the create/cancel pair must leave the slot exactly at "
            f"baseline (0, 0, 18), got ({after['seats_reserved']}, "
            f"{after['seats_confirmed']}, {after['seats_available']})"
        )
        assert_slot_seat_conservation(after)


class TestRevenueConservation:

    def test_confirm_recognizes_revenue_and_cancel_refunds_in_full(self):
        """PRD section 3.6: "`revenue_committed_cents` is the sum of
        `total_price_cents` over the slot's `CONFIRMED` bookings — money
        actually confirmed, nothing more."
        PRD section 3.6: "Cancelling a paid `CONFIRMED` booking follows the
        time tiers measured in whole hours between the logical clock and the
        slot's `start_at`: at least 48 hours before the start, the full
        `total_price_cents` is refunded".

        Design: Difficulty/compensating_invariant/revenue_conservation_confirm_then_refund
        """
        ctx = setup_open_slot(start_at="2026-09-10T10:00:00Z")
        booking = create_general_booking(ctx["slot_id"], 2)
        confirm_booking(booking["id"], 2000)
        slot = get_slot(ctx["slot_id"])
        assert slot["revenue_committed_cents"] == 2000
        cancelled = cancel_booking(booking["id"])
        # Far more than 48 hours before the 2026-09-10 start: full refund.
        assert cancelled["refund_cents"] == 2000
        assert cancelled["refund_cents"] == cancelled["total_price_cents"]

    def test_cancel_returns_committed_revenue_to_baseline(self):
        """PRD section 3.6: "Cancellation releases seats from whichever
        bucket the booking occupied — reserved or confirmed — and sets
        `refund_cents`, which is zero until the moment of cancellation."
        PRD section 3.6: "`CANCELLED` and `EXPIRED` bookings are excluded
        from both figures, always."

        Design: Difficulty/compensating_invariant/revenue_conservation_confirm_then_refund
        """
        ctx = setup_open_slot(start_at="2026-09-10T10:00:00Z")
        booking = create_general_booking(ctx["slot_id"], 2)
        confirm_booking(booking["id"], 2000)
        cancel_booking(booking["id"])
        slot = get_slot(ctx["slot_id"])
        assert slot["revenue_committed_cents"] == 0, (
            f"committed revenue must return to baseline after the refund, "
            f"got {slot['revenue_committed_cents']}"
        )


class TestRefundTierBoundary:

    def test_refund_tier_boundary_48h_inclusive(self):
        """PRD section 3.6: "Cancelling a paid `CONFIRMED` booking follows
        the time tiers measured in whole hours between the logical clock and
        the slot's `start_at`: at least 48 hours before the start, the full
        `total_price_cents` is refunded; at least 24 hours but fewer than 48,
        half the total is refunded, rounded half-up to a whole cent; fewer
        than 24 hours, nothing is refunded."

        Design: Corner/calculations/refund_tier_boundary_48h_inclusive
        """
        ctx = setup_open_slot(start_at="2026-09-10T10:00:00Z")
        b1 = create_general_booking(ctx["slot_id"], 2, visitor_name="Ann")
        confirm_booking(b1["id"], 2000)
        b2 = create_general_booking(ctx["slot_id"], 2, visitor_name="Bob")
        confirm_booking(b2["id"], 2000)

        # Exactly 48 hours before the 2026-09-10T10:00:00Z start: full tier.
        set_clock("2026-09-08T10:00:00Z")
        cancelled1 = cancel_booking(b1["id"])
        assert cancelled1["refund_cents"] == 2000, (
            f"the >= 48h tier is inclusive, expected 2000, "
            f"got {cancelled1['refund_cents']}"
        )

        # 47 hours 59 minutes before start: half tier.
        set_clock("2026-09-08T10:01:00Z")
        cancelled2 = cancel_booking(b2["id"])
        assert cancelled2["refund_cents"] == 1000, (
            f"round_half_up(2000 * 0.5) = 1000 expected, "
            f"got {cancelled2['refund_cents']}"
        )


class TestBookingTerminalState:

    def test_booking_cancel_from_cancelled_rejected(self):
        """PRD section 2.9, tier 5: "the target resource must be in a state
        that offers the requested transition; generic violations yield
        `ERR_INVALID_STATE`".
        PRD section 3.6: "Cancellation releases seats from whichever bucket
        the booking occupied — reserved or confirmed — and sets
        `refund_cents`, which is zero until the moment of cancellation."

        Design: Corner/state_machines/booking_cancel_from_cancelled_rejected
        """
        ctx = setup_open_slot()
        booking = create_general_booking(ctx["slot_id"], 1)
        cancel_booking(booking["id"])
        resp = api_client.cancel_booking(booking["id"], FRONT_DESK)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestOpsEpoch:

    def test_booking_hold_expiry_via_ops_epoch(self):
        """PRD section 3.6: "`hold_expires_at` is set to the earlier of two
        instants — 48 hours after the booking's creation, and the slot's
        `start_at` — and the periodic sweep expires any `RESERVED` booking
        whose `hold_expires_at` the logical clock has reached, moving it to
        `EXPIRED`, releasing its reserved seats, flipping a `FULL` slot back
        to `OPEN` when seats are freed, and recomputing revenue."
        PRD section 3.5: "Membership ages under the periodic sweep, a
        `MuseumAdmin`-only ops capability that also expires stale booking
        holds (§3.6) and reports the sweep's results as
        `expired_booking_count` and `lapsed_member_count`."

        Design: Corner/state_machines/booking_hold_expiry_via_ops_epoch
        """
        ctx = setup_open_slot()
        booking = create_general_booking(ctx["slot_id"], 2)
        assert booking["status"] == "RESERVED"
        # Created at the startup clock 2026-08-01T00:00:00Z, so the hold ends
        # 48h later (2026-08-03T00:00:00Z), earlier than the 2026-09-01 start.
        set_clock("2026-08-03T00:00:01Z")
        sweep = run_epoch()
        assert sweep["expired_booking_count"] == 1, (
            f"the sweep must expire exactly this hold, "
            f"got {sweep['expired_booking_count']}"
        )
        after = get_booking(booking["id"])
        assert after["status"] == "EXPIRED"
        slot = get_slot(ctx["slot_id"])
        assert slot["seats_available"] == 18, (
            f"expiry must release the reserved seats, "
            f"got {slot['seats_available']}"
        )

    def test_member_lapse_via_ops_epoch(self):
        """PRD section 3.5: "On each run, an `ACTIVE` member whose
        `renews_on` has passed — the renewal date is earlier than the current
        date — slips to `LAPSED`, and a `LAPSED` member more than thirty days
        past `renews_on` hardens into `EXPIRED`, which is terminal."
        PRD section 3.5: "Renewal restores standing: from either `ACTIVE` or
        `LAPSED`, a renewal carrying a `renews_on` strictly after the current
        date moves the member back to `ACTIVE` and replaces the stored date."

        Design: Corner/state_machines/member_lapse_via_ops_epoch
        """
        member = create_member(renews_on="2026-08-10")
        set_clock("2026-08-11T00:00:00Z")
        sweep = run_epoch()
        assert sweep["lapsed_member_count"] == 1
        resp = api_client.get_member(member["id"], FRONT_DESK)
        data = validate_success(resp)
        assert data["status"] == "LAPSED", (
            f"member past renews_on must lapse, got {data['status']}"
        )
        resp = api_client.renew_member(
            member["id"], {"renews_on": "2027-01-01"}, FRONT_DESK)
        renewed = validate_success(resp)
        assert renewed["status"] == "ACTIVE"
        assert renewed["renews_on"] == "2027-01-01", (
            f"renewal must replace the stored date, "
            f"got {renewed['renews_on']}"
        )
