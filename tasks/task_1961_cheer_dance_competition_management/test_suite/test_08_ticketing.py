"""Spectator ticketing: price-tier snapshot, group-discount rounding order,
the seat conservation invariant, capacity rejection, hold expiry, the
checkpoint sweep, and order state errors."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_session_seat_invariant,
    assert_ticket_order,
    create_ticket_order,
    create_ticket_order_payload,
    get_success_data,
    make_spectator_headers,
    set_clock,
    setup_session,
    validate_error,
    validate_success,
)

DIRECTOR = TEST_USERS["event_director_headers"]


class TestPricingVariants:
    def test_ticket_order_rounding_variants_diverge_in_cents(self, api):
        """PRD §3.8: "The order's `tier` is decided by an inclusive cutoff:
        orders created on or before the day that is 14 days before the
        event's `start_date` (the cutoff taken at 00:00:00Z) are `ADVANCE`;
        anything later is `GATE`. The snapshotted `unit_price_cents` is 1295
        for `ADVANCE` and 1895 for `GATE`."
        PRD §3.8: "Note the rounding order is pinned to the order level — the
        discount is computed once on the whole subtotal, not per unit; under
        the (documented but never served) per-unit interpretation, 25 advance
        tickets would total 29150 cents instead of the correct 29137, so
        implementations must apply the discount to the subtotal."

        Design: Difficulty/dual_variant_calc/ticket_order_rounding_variants_diverge_in_cents
        """
        # Default logical clock 2026-08-01 <= cutoff 2026-08-22T00:00:00Z.
        event, session = setup_session(capacity=1000)
        resp = api.create_ticket_order(
            create_ticket_order_payload(session["id"], 25),
            make_spectator_headers("spec-1"))
        order = validate_success(resp, 201)
        assert_ticket_order(order)
        assert order["tier"] == "ADVANCE"
        assert order["unit_price_cents"] == 1295
        assert order["discount_cents"] == 3238
        assert order["total_cents"] == 29137

    def test_ticket_group_discount_rounding_order_and_qty_boundary(self, api):
        """PRD §3.8: "A group discount applies when the quantity is at least
        20 (inclusive): 10 percent of the subtotal, rounded half-up once to
        whole cents, becomes `discount_cents`; otherwise `discount_cents` is
        zero. The order's `total_cents` is the subtotal minus the rounded
        discount."

        Design: Difficulty/combinatorial_formula/ticket_group_discount_rounding_order_and_qty_boundary
        """
        event, session = setup_session(capacity=500)

        # Quantity 20 (inclusive boundary): 20*1295 = 25900, discount
        # round_half_up(2590.0) = 2590, total 23310.
        order20 = validate_success(api.create_ticket_order(
            create_ticket_order_payload(session["id"], 20),
            make_spectator_headers("spec-1")), 201)
        assert order20["discount_cents"] == 2590
        assert order20["total_cents"] == 23310

        # Quantity 19: no discount; 19*1295 = 24605.
        order19 = validate_success(api.create_ticket_order(
            create_ticket_order_payload(session["id"], 19),
            make_spectator_headers("spec-2")), 201)
        assert order19["discount_cents"] == 0
        assert order19["total_cents"] == 24605


class TestSeatConservation:
    def test_session_seat_inventory_conserved_through_hold_pay_cancel_refund(self, api):
        """PRD §3.1: "The compensating invariant `seats_available +
        seats_held + seats_sold == capacity` holds at every moment; every
        ticket-order transition in §3.8 is defined by how it moves quantity
        between these counters."
        PRD §3.8: "Payment moves the order to `PAID`, subtracts the quantity
        from `seats_held`, and adds it to `seats_sold`. Cancellation from
        `HELD` moves the order to `CANCELLED` and releases the quantity from
        `seats_held`; cancellation from `PAID` moves it to `REFUNDED` and
        subtracts the quantity from `seats_sold`"

        Design: Difficulty/compensating_invariant/session_seat_inventory_conserved_through_hold_pay_cancel_refund
        """
        event, session = setup_session(capacity=100)

        def seats():
            s = get_success_data(api.get_session(session["id"], DIRECTOR))
            assert_session_seat_invariant(s)
            return s["seats_held"], s["seats_sold"], s["seats_available"]

        order1 = create_ticket_order(session["id"], "spec-1", quantity=25)
        order2 = create_ticket_order(session["id"], "spec-2", quantity=10)
        assert seats() == (35, 0, 65)

        get_success_data(api.pay_ticket_order(order2["id"],
                                              make_spectator_headers("spec-2")))
        assert seats() == (25, 10, 65)

        get_success_data(api.cancel_ticket_order(order1["id"],
                                                 make_spectator_headers("spec-1")))
        assert seats() == (0, 10, 90)

        get_success_data(api.cancel_ticket_order(order2["id"],
                                                 make_spectator_headers("spec-2")))
        assert seats() == (0, 0, 100)

    def test_sold_out_session_rejects_new_order(self, api):
        """PRD §3.8: "Capacity is enforced at creation against the session's
        compensating invariant: the requested `quantity` must fit within
        `seats_available` — held plus sold plus requested must not exceed
        `capacity` — else `ERR_SESSION_SOLD_OUT`."

        Design: Corner/errors/sold_out_session_rejects_new_order
        """
        event, session = setup_session(capacity=10)
        create_ticket_order(session["id"], "spec-1", quantity=6)
        order2 = create_ticket_order(session["id"], "spec-2", quantity=4)
        get_success_data(api.pay_ticket_order(order2["id"],
                                              make_spectator_headers("spec-2")))

        # held 6 + sold 4 fill capacity 10: even a single ticket overflows.
        resp = api.create_ticket_order(
            create_ticket_order_payload(session["id"], 1),
            make_spectator_headers("spec-3"))
        validate_error(resp, ApiErrorId.ERR_SESSION_SOLD_OUT)


class TestHoldExpiryAndCheckpoint:
    def test_pay_after_hold_expiry_rejected_then_checkpoint_sweeps(self, api):
        """PRD §3.8: "From `HELD`, the owning spectator pays: the logical now
        must be no later than `hold_expires_at`, inclusive
        (`ERR_ORDER_HOLD_EXPIRED`)"
        PRD §3.8: "A new order arrives with its `status` set to `HELD`,
        `purchaser_user_id` captured from the acting `X-User-ID`, adds its
        quantity to the session's `seats_held`, and sets `hold_expires_at` to
        15 minutes after creation."
        PRD §3.9: "it expires every `HELD` ticket order of the event whose
        `hold_expires_at` is earlier than the logical now, moving each to
        `EXPIRED` and releasing its seats from `seats_held`."

        Design: Corner/errors/pay_after_hold_expiry_rejected_then_checkpoint_sweeps
        """
        event, session = setup_session(capacity=50)
        order = create_ticket_order(session["id"], "spec-1", quantity=2)

        # 15:01 after creation — one second past the inclusive boundary.
        set_clock("2026-08-01T00:15:01Z")
        resp = api.pay_ticket_order(order["id"], make_spectator_headers("spec-1"))
        validate_error(resp, ApiErrorId.ERR_ORDER_HOLD_EXPIRED)

        result = get_success_data(api.checkpoint(event["id"], DIRECTOR))
        assert result["expired_order_count"] == 1
        after = get_success_data(api.get_ticket_order(order["id"], DIRECTOR))
        assert after["status"] == "EXPIRED"
        session_after = get_success_data(api.get_session(session["id"], DIRECTOR))
        assert session_after["seats_held"] == 0
        assert session_after["seats_available"] == 50


class TestOrderStateErrors:
    def test_order_pay_and_cancel_state_errors(self, api):
        """PRD §3.8: "cancellation from any other state, and payment from any
        state but `HELD`, are rejected with `ERR_ORDER_INVALID_STATE`."

        Design: Corner/errors/order_pay_and_cancel_state_errors
        """
        event, session = setup_session(capacity=50)
        order1 = create_ticket_order(session["id"], "spec-1", quantity=2)
        get_success_data(api.pay_ticket_order(order1["id"],
                                              make_spectator_headers("spec-1")))
        order2 = create_ticket_order(session["id"], "spec-2", quantity=1)
        get_success_data(api.cancel_ticket_order(order2["id"],
                                                 make_spectator_headers("spec-2")))

        # Pay on a PAID order: wrong source state.
        resp = api.pay_ticket_order(order1["id"], make_spectator_headers("spec-1"))
        validate_error(resp, ApiErrorId.ERR_ORDER_INVALID_STATE)

        # Cancel on a CANCELLED order: terminal lockdown.
        resp = api.cancel_ticket_order(order2["id"],
                                       make_spectator_headers("spec-2"))
        validate_error(resp, ApiErrorId.ERR_ORDER_INVALID_STATE)


class TestValidationPriority:
    def test_event_state_beats_session_sold_out(self, api):
        """PRD §2.6: "When a request violates several rules, the rejection is
        determined by a fixed priority order — the lowest-numbered applicable
        check wins"
        PRD §2.6: "6. **Event state** — the operation is permitted in the
        event's current status (`ERR_EVENT_INVALID_STATE`,
        `ERR_EVENT_NOT_LIVE`)." ahead of "14. **Fiscal capacity** — session
        seat availability (`ERR_SESSION_SOLD_OUT`)."
        PRD §3.8: "Ticket sales are open while the event's status is
        `REGISTRATION_OPEN`, `REGISTRATION_CLOSED`, `SCHEDULED`, or `LIVE`;
        outside those states the create is rejected with
        `ERR_EVENT_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/event_state_beats_session_sold_out
        """
        # Event left in DRAFT; session capacity 10 < quantity 40 would also
        # fail the fiscal check, but the event-state check must win.
        event, session = setup_session(capacity=10, open_reg=False)
        resp = api.create_ticket_order(
            create_ticket_order_payload(session["id"], 40),
            make_spectator_headers("spec-1"))
        validate_error(resp, ApiErrorId.ERR_EVENT_INVALID_STATE)

    def test_roster_locked_beats_age_ineligibility(self, api):
        """PRD §2.6: "7. **Team and roster state** — the team's registration
        and music dimensions permit the operation (`ERR_INVALID_STATE`,
        `ERR_MUSIC_NOT_VERIFIED`, `ERR_TEAM_NOT_CHECKED_IN`,
        `ERR_ROSTER_LOCKED`)." ahead of "11. **Safety and segregation** —
        athlete age eligibility, crossover caps, judge certification, routine
        legality, reviewer/applier conflicts"
        PRD §3.2: "once the roster is locked or beyond, removal attempts are
        rejected with `ERR_ROSTER_LOCKED`."

        Design: Difficulty/priority_pair_validation_conflict/roster_locked_beats_age_ineligibility
        """
        from test_helpers import (
            add_roster_entry,
            create_athlete,
            create_roster_entry_payload,
            create_team,
            lock_roster,
            make_team_coach_headers,
            setup_event_with_division,
        )
        event, division, panel, head, safety = setup_event_with_division(
            division_overrides={"min_age": 14, "max_age": 18})
        team = create_team(event["id"], division["id"], "coach-1")
        adult = create_athlete("Ann", "2010-05-01", "coach-1")
        add_roster_entry(team["id"], adult["id"], "coach-1", bib_number=1)
        lock_roster(team["id"], "coach-1")

        # Age 10 at the reference date AND the team is ROSTER_LOCKED: the
        # state error (priority 7) beats the age rule (priority 11).
        kid = create_athlete("Kid", "2016-05-01", "coach-1")
        resp = api.create_roster_entry(
            create_roster_entry_payload(team["id"], kid["id"], bib_number=2),
            make_team_coach_headers("coach-1"))
        validate_error(resp, ApiErrorId.ERR_ROSTER_LOCKED)


class TestPricingSecondAngles:
    def test_ticket_tier_flips_to_gate_after_cutoff(self, api):
        """PRD §3.8: "The order's `tier` is decided by an inclusive cutoff:
        orders created on or before the day that is 14 days before the
        event's `start_date` (the cutoff taken at 00:00:00Z) are `ADVANCE`;
        anything later is `GATE`. The snapshotted `unit_price_cents` is 1295
        for `ADVANCE` and 1895 for `GATE`."
        PRD §3.8: "The order's price is snapshotted at creation and never
        recomputed afterwards."

        Design: Difficulty/dual_variant_calc/ticket_order_rounding_variants_diverge_in_cents
        """
        event, session = setup_session(capacity=100)

        # Move the logical clock one second past the 2026-08-22T00:00:00Z
        # ADVANCE cutoff: the same quantity now prices at the GATE rate.
        set_clock("2026-08-22T00:00:01Z")
        order = validate_success(api.create_ticket_order(
            create_ticket_order_payload(session["id"], 2),
            make_spectator_headers("spec-1")), 201)
        assert order["tier"] == "GATE"
        assert order["unit_price_cents"] == 1895
        assert order["discount_cents"] == 0
        assert order["total_cents"] == 3790

    def test_group_discount_rounds_half_up_on_odd_half_cent(self, api):
        """PRD §3.8: "A group discount applies when the quantity is at least
        20 (inclusive): 10 percent of the subtotal, rounded half-up once to
        whole cents, becomes `discount_cents`"
        PRD §3.8: "Note the rounding order is pinned to the order level — the
        discount is computed once on the whole subtotal, not per unit"

        Design: Difficulty/combinatorial_formula/ticket_group_discount_rounding_order_and_qty_boundary
        """
        event, session = setup_session(capacity=500)

        # 21 ADVANCE tickets: subtotal 27195, discount round_half_up(2719.5)
        # = 2720 (half-up), total 24475. A per-unit reading would give
        # round_half_up(1295*0.9)=1166 per ticket -> 24486.
        order = validate_success(api.create_ticket_order(
            create_ticket_order_payload(session["id"], 21),
            make_spectator_headers("spec-1")), 201)
        assert order["discount_cents"] == 2720
        assert order["total_cents"] == 24475


class TestConservationSecondAngle:
    def test_seat_invariant_holds_immediately_after_each_hold(self, api):
        """PRD §3.1: "The compensating invariant `seats_available +
        seats_held + seats_sold == capacity` holds at every moment"
        PRD §3.8: "A new order arrives with its `status` set to `HELD`,
        `purchaser_user_id` captured from the acting `X-User-ID`, adds its
        quantity to the session's `seats_held`, and sets `hold_expires_at` to
        15 minutes after creation."

        Design: Difficulty/compensating_invariant/session_seat_inventory_conserved_through_hold_pay_cancel_refund
        """
        event, session = setup_session(capacity=50)
        create_ticket_order(session["id"], "spec-1", quantity=7)
        after = get_success_data(api.get_session(session["id"], DIRECTOR))
        assert_session_seat_invariant(after)
        assert after["seats_held"] == 7
        assert after["seats_sold"] == 0
        assert after["seats_available"] == 43


class TestPrioritySecondAngles:
    def test_event_state_beats_session_sold_out_on_full_session(self, api):
        """PRD §2.6: "When a request violates several rules, the rejection is
        determined by a fixed priority order — the lowest-numbered applicable
        check wins"
        PRD §2.6: "6. **Event state** — the operation is permitted in the
        event's current status (`ERR_EVENT_INVALID_STATE`,
        `ERR_EVENT_NOT_LIVE`)." ahead of "14. **Fiscal capacity** — session
        seat availability (`ERR_SESSION_SOLD_OUT`)."

        Design: Difficulty/priority_pair_validation_conflict/event_state_beats_session_sold_out
        """
        # Same pair, second angle: a small order that would fit on capacity
        # is still rejected by event state alone on a DRAFT event.
        event, session = setup_session(capacity=100, open_reg=False)
        resp = api.create_ticket_order(
            create_ticket_order_payload(session["id"], 1),
            make_spectator_headers("spec-1"))
        validate_error(resp, ApiErrorId.ERR_EVENT_INVALID_STATE)

    def test_roster_locked_beats_age_ineligibility_after_lock(self, api):
        """PRD §2.6: "7. **Team and roster state**" ahead of "11. **Safety
        and segregation** — athlete age eligibility, crossover caps, judge
        certification, routine legality, reviewer/applier conflicts"
        PRD §3.2: "once the roster is locked or beyond, removal attempts are
        rejected with `ERR_ROSTER_LOCKED`."

        Design: Difficulty/priority_pair_validation_conflict/roster_locked_beats_age_ineligibility
        """
        from test_helpers import (
            add_roster_entry,
            create_athlete,
            create_roster_entry_payload,
            create_team,
            lock_roster,
            make_team_coach_headers,
            setup_event_with_division,
        )
        event, division, panel, head, safety = setup_event_with_division(
            division_overrides={"min_age": 14, "max_age": 18})
        team = create_team(event["id"], division["id"], "coach-1")
        adult = create_athlete("Ann", "2010-05-01", "coach-1")
        add_roster_entry(team["id"], adult["id"], "coach-1", bib_number=1)

        # While REGISTERED the age rule is live: the under-age add fails with
        # the safety error (proving the setup really violates the age rule).
        kid = create_athlete("Kid", "2016-05-01", "coach-1")
        resp = api.create_roster_entry(
            create_roster_entry_payload(team["id"], kid["id"], bib_number=2),
            make_team_coach_headers("coach-1"))
        validate_error(resp, ApiErrorId.ERR_ATHLETE_AGE_INELIGIBLE)

        # After lock, the same under-age add surfaces the state error instead.
        lock_roster(team["id"], "coach-1")
        resp = api.create_roster_entry(
            create_roster_entry_payload(team["id"], kid["id"], bib_number=2),
            make_team_coach_headers("coach-1"))
        validate_error(resp, ApiErrorId.ERR_ROSTER_LOCKED)
