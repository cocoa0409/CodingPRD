"""Order cancellation: tiered restocking fees, terminal lockdown, slot
release conservation, and the waitlist promotion cascade (PRD §3.5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    amend_order,
    assert_dealer_order,
    book_order,
    book_order_ballast,
    book_order_no_options,
    book_order_tower,
    book_order_tower_ballast,
    cancel_order,
    confirm_order,
    create_amend_order_payload,
    create_dealer,
    create_dealer_order_payload,
    create_hull,
    create_model,
    create_option,
    create_run,
    create_show,
    create_slot,
    get_dealer,
    get_order,
    get_slot,
    make_dealer_principal_headers,
    set_clock,
    setup_bookable_world,
    setup_committed_hull,
    validate_error,
    validate_success,
)

ANY = TEST_USERS["any_headers"]


class TestRestockingFee:
    def test_waitlisted_cancel_free_full_refund(self, api):
        """PRD §3.5: "From `WAITLISTED` there is no production commitment:
        `cancel_fee_cents` is 0 and `refund_cents` is the full
        `deposit_paid_cents`."

        Design: Corner/calculations/restocking_fee_waitlisted_cancel_free
        """
        model = create_model(api)
        dealer = create_dealer(api)
        order = book_order_no_options(api, dealer, model)
        assert order["status"] == "WAITLISTED"
        cancelled = cancel_order(api, order, dealer)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancel_fee_cents"] == 0
        assert cancelled["refund_cents"] == 257500, "full deposit returned"

    def test_committed_cancel_twelve_percent(self, api):
        """PRD §3.5: "From `COMMITTED` the fee is twelve percent of the invoice
        total, rounded half up, with the same slot release, the same waitlist
        cascade, and the same dealer recount as the allocated path."
        PRD §3.5: "In all non-waitlisted cases `refund_cents` is the deposit
        minus the fee, floored at zero"

        Invoice 3093605 -> fee rhu(3093605 * 0.12) = 371233; the deposit of
        309361 is fully absorbed, so the refund floors at 0.

        Design: Corner/calculations/restocking_fee_committed_12pct
        """
        world = setup_bookable_world(api)
        dealer = world["dealer"]
        order = book_order_tower_ballast(
            api, dealer, world["model"], world["tower"], world["ballast"],
            slot_id=world["slot"]["id"],
        )
        order = confirm_order(api, order, dealer)
        cancelled = cancel_order(api, order, dealer)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancel_fee_cents"] == 371233, (
            f"rhu(3093605 * 0.12) = 371233, got {cancelled['cancel_fee_cents']}"
        )
        assert cancelled["refund_cents"] == 0, "fee exceeds deposit -> refund floors at 0"

    def test_boat_show_cancel_fee_maxed_with_deposit(self, api):
        """PRD §3.5: "For an order whose `source` is `BOAT_SHOW`, either tier's
        fee is replaced by the larger of the computed percentage fee and the
        full `deposit_paid_cents` — a show order cancelled after the surge
        forfeits at least its percentage fee and at most its whole deposit."
        PRD §3.5: "In all non-waitlisted cases `refund_cents` is the deposit
        minus the fee, floored at zero"

        ALLOCATED show order: 5% of 3093605 is 154680, but the 500000 deposit
        is larger, so the whole deposit is forfeited.

        Design: Corner/calculations/restocking_fee_boat_show_max_with_deposit
        """
        world = setup_bookable_world(api)
        show = create_show(
            api, start_date="2026-08-01", end_date="2026-08-15",
            surge_deposit_rate=0.05,
        )
        # Default clock 2026-08-01 is inside the show window.
        order = book_order(
            api, world["dealer"], world["model"],
            option_ids=[world["tower"]["id"], world["ballast"]["id"]],
            source="BOAT_SHOW", show_event_id=show["id"],
            slot_id=world["slot"]["id"], deposit_paid_cents=500000,
        )
        assert order["status"] == "ALLOCATED"
        cancelled = cancel_order(api, order, world["dealer"])
        assert cancelled["cancel_fee_cents"] == 500000, (
            f"max(154680 pct fee, 500000 deposit) = 500000, got "
            f"{cancelled['cancel_fee_cents']}"
        )
        assert cancelled["refund_cents"] == 0


class TestCancelStateGates:
    def test_cancelled_terminal_lockdown(self, api):
        """PRD §3.5: "Cancellation from `IN_PRODUCTION`, `DELIVERED`,
        `RETAILED`, or an already `CANCELLED` state is rejected with
        `ERR_INVALID_ORDER_STATE`."
        PRD §3.5: "Amendment is a self-loop available only from `WAITLISTED`
        and `ALLOCATED`; attempting it from `COMMITTED`, `IN_PRODUCTION`,
        `DELIVERED`, `RETAILED`, or `CANCELLED` is rejected with
        `ERR_INVALID_ORDER_STATE`."
        PRD §3.5: "It requires the order to be `ALLOCATED` — any other state
        yields `ERR_INVALID_ORDER_STATE`"

        A CANCELLED order rejects confirm, amend, and re-cancel alike.

        Design: Corner/state_machines/dealer_order_terminal_lockdown_cancelled
        """
        model = create_model(api)
        dealer = create_dealer(api)
        order = book_order_no_options(api, dealer, model)
        cancelled = cancel_order(api, order, dealer)
        assert cancelled["status"] == "CANCELLED"
        headers = make_dealer_principal_headers(dealer["id"])
        current = get_order(api, order["id"])
        resp_confirm = api.confirm_dealer_order(order["id"], headers)
        validate_error(resp_confirm, ApiErrorId.ERR_INVALID_ORDER_STATE)
        resp_amend = api.amend_dealer_order(
            order["id"],
            create_amend_order_payload(current["version"], deposit_paid_cents=257500),
            headers,
        )
        validate_error(resp_amend, ApiErrorId.ERR_INVALID_ORDER_STATE)
        resp_cancel = api.cancel_dealer_order(order["id"], headers)
        validate_error(resp_cancel, ApiErrorId.ERR_INVALID_ORDER_STATE)

    def test_cancel_rejected_on_in_production(self, api):
        """PRD §3.5: "Cancellation from `IN_PRODUCTION`, `DELIVERED`,
        `RETAILED`, or an already `CANCELLED` state is rejected with
        `ERR_INVALID_ORDER_STATE`."

        Design: Corner/state_machines/dealer_order_cancel_rejected_on_in_production
        """
        world = setup_committed_hull(api, with_options=False)
        order = get_order(api, world["order"]["id"])
        assert order["status"] == "IN_PRODUCTION"
        resp = api.cancel_dealer_order(
            order["id"], make_dealer_principal_headers(world["dealer"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_ORDER_STATE)


class TestCancelCascadePromotion:
    def test_cancel_releases_slot_and_promotes_waitlist(self, api):
        """PRD §3.5: "From `ALLOCATED` the restocking fee is five percent of the
        invoice total, rounded half up; the slot is released (`reserved_hours`
        drops by the order's hours and the slot's `version` increments), the
        dealer's `allocation_used` is recounted down by one with the dealer's
        `version` incremented, and the freed capacity fires the waitlist
        promotion described below."
        PRD §3.5: "The promoted order transitions `WAITLISTED` → `ALLOCATED`
        onto the freed slot: the slot's `reserved_hours` grows by its hours
        with a version increment, its dealer's `allocation_used` is recounted
        up by one with a dealer version increment, and the promoted order's
        `version` increments."

        Slot cap 50: dealer A's WAKE-TOWER order (46h) holds the slot; dealer
        B's BALLAST order (44h) cannot fit in the 4 free hours and waits.
        Cancelling A frees 46h and promotes B onto the same slot.

        Design: Difficulty/transitive_cascade/cancel_cascade_releases_slot_and_promotes_waitlist
        """
        model = create_model(api)
        tower = create_option(api, model["id"], option_code="WAKE-TOWER",
                              name="Wake Tower", price_cents=350000, production_hours=6)
        ballast = create_option(api, model["id"], option_code="BALLAST",
                                name="Ballast", price_cents=180000, production_hours=4)
        da = create_dealer(api, dealer_code="D-A")
        db = create_dealer(api, dealer_code="D-B")
        run = create_run(api)
        slot = create_slot(api, run["id"], slot_code="S1", capacity_hours=50)
        oa = book_order_tower(api, da, model, tower, slot_id=slot["id"])
        assert oa["status"] == "ALLOCATED"
        assert get_slot(api, slot["id"])["reserved_hours"] == 46
        # 44h needed vs 4h free: auto-placement finds nothing -> WAITLISTED.
        ob = book_order_ballast(api, db, model, ballast)
        assert ob["status"] == "WAITLISTED"
        assert ob["slot_id"] is None

        cancelled = cancel_order(api, oa, da)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancel_fee_cents"] == 145874  # rhu(2917475 * 0.05)
        ob_after = get_order(api, ob["id"])
        assert ob_after["status"] == "ALLOCATED", "selector must promote B"
        assert ob_after["slot_id"] == slot["id"]
        slot_after = get_slot(api, slot["id"])
        assert slot_after["reserved_hours"] == 44, (
            f"46 released then 44 promoted: {slot_after['reserved_hours']}"
        )
        assert get_dealer(api, da["id"])["allocation_used"] == 0
        assert get_dealer(api, db["id"])["allocation_used"] == 1

    def test_cancel_with_empty_candidate_set_leaves_slot_open(self, api):
        """PRD §3.5: "Exactly one order is promoted per release event, even if
        hours remain for more; if the candidate set is empty the slot simply
        stays `OPEN` with its freed hours and no error is raised."

        Design: Difficulty/transitive_cascade/cancel_cascade_releases_slot_and_promotes_waitlist
        """
        world = setup_bookable_world(api, with_options=False)
        order = book_order_no_options(
            api, world["dealer"], world["model"], slot_id=world["slot"]["id"]
        )
        assert get_slot(api, world["slot"]["id"])["reserved_hours"] == 40
        cancelled = cancel_order(api, order, world["dealer"])
        assert cancelled["status"] == "CANCELLED"
        slot_after = get_slot(api, world["slot"]["id"])
        assert slot_after["status"] == "OPEN", "no candidates -> slot stays OPEN"
        assert slot_after["reserved_hours"] == 0
        assert get_dealer(api, world["dealer"]["id"])["allocation_used"] == 0


class TestSlotHoursConservation:
    def test_reserved_hours_conservation_across_amend_and_cancel(self, api):
        """PRD §3.3: "While orders occupy it, `reserved_hours` always equals the
        summed `production_hours` of that slot's orders in `ALLOCATED`,
        `COMMITTED`, or `IN_PRODUCTION` — a conservation invariant every
        booking, amendment, cancellation, and promotion re-establishes rather
        than approximates."

        0 -> book WAKE-TOWER (46) -> amend adding BALLAST (50) -> cancel (0):
        the net change returns to the initial state.

        Design: Difficulty/compensating_invariant/slot_reserved_hours_conservation_across_amend_and_cancel
        """
        world = setup_bookable_world(api)
        dealer, slot = world["dealer"], world["slot"]
        order = book_order_tower(
            api, dealer, world["model"], world["tower"], slot_id=slot["id"]
        )
        assert get_slot(api, slot["id"])["reserved_hours"] == 46
        amended = amend_order(
            api, order, dealer,
            option_package_ids=[world["tower"]["id"], world["ballast"]["id"]],
            deposit_paid_cents=309361,
        )
        assert amended["production_hours"] == 50
        assert get_slot(api, slot["id"])["reserved_hours"] == 50, (
            "amendment adjusts reserved_hours by the +4 delta"
        )
        cancelled = cancel_order(api, amended, dealer)
        assert cancelled["status"] == "CANCELLED"
        assert get_slot(api, slot["id"])["reserved_hours"] == 0, (
            "cancel must restore the initial reserved_hours (conservation)"
        )

    def test_reserved_hours_conservation_with_multiple_occupants(self, api):
        """PRD §3.3: "While orders occupy it, `reserved_hours` always equals the
        summed `production_hours` of that slot's orders in `ALLOCATED`,
        `COMMITTED`, or `IN_PRODUCTION` — a conservation invariant every
        booking, amendment, cancellation, and promotion re-establishes rather
        than approximates."

        Two dealers' orders share one slot (46h + 44h = 90h); cancelling one
        leaves the other's hours exactly.

        Design: Difficulty/compensating_invariant/slot_reserved_hours_conservation_across_amend_and_cancel
        """
        world = setup_bookable_world(api)
        model, slot = world["model"], world["slot"]
        db = create_dealer(api, dealer_code="D-B")
        oa = book_order_tower(
            api, world["dealer"], model, world["tower"], slot_id=slot["id"]
        )
        ob = book_order_ballast(api, db, model, world["ballast"], slot_id=slot["id"])
        assert get_slot(api, slot["id"])["reserved_hours"] == 90
        cancel_order(api, oa, world["dealer"])
        slot_after = get_slot(api, slot["id"])
        assert slot_after["reserved_hours"] == 44, (
            f"only the cancelled order's hours are released: {slot_after['reserved_hours']}"
        )
        assert get_order(api, ob["id"])["status"] == "ALLOCATED"


class TestWaitlistPromotionRanking:
    def test_show_boost_outranks_earlier_retail(self, api):
        """PRD §3.5: "Candidates rank first by show priority: an order sourced
        `BOAT_SHOW` whose event's closed window contains the current clock date
        carries a boost of 1 and outranks all unboosted orders, which carry 0.
        Within the same boost level, the earliest `created_at` wins; timestamps
        are unique at millisecond precision, so no further tie-break exists and
        the `id` is never consulted."

        A RETAIL waiter created a day earlier loses the promotion to a
        BOAT_SHOW waiter whose event window contains the clock date.

        Design: Corner/calculations/waitlist_promotion_show_boost_active_window
        """
        model = create_model(api)
        tower = create_option(api, model["id"], option_code="WAKE-TOWER",
                              name="Wake Tower", price_cents=350000, production_hours=6)
        ballast = create_option(api, model["id"], option_code="BALLAST",
                                name="Ballast", price_cents=180000, production_hours=4)
        da = create_dealer(api, dealer_code="D-A")
        db = create_dealer(api, dealer_code="D-B")
        show = create_show(api, start_date="2026-08-01", end_date="2026-08-15",
                           surge_deposit_rate=0.05)
        run = create_run(api)
        slot = create_slot(api, run["id"], slot_code="S1", capacity_hours=50)
        # 2026-08-02: the holder books the 46h WAKE-TOWER order.
        set_clock(api, "2026-08-02T00:00:00Z")
        o_hold = book_order_tower(api, da, model, tower, slot_id=slot["id"])
        assert o_hold["status"] == "ALLOCATED"
        # RETAIL waiter (44h) created first — no slot fits (4h free).
        o_retail = book_order_ballast(api, da, model, ballast)
        assert o_retail["status"] == "WAITLISTED"
        # BOAT_SHOW waiter created a day later, inside the event window.
        set_clock(api, "2026-08-03T00:00:00Z")
        o_show = book_order_ballast(
            api, db, model, ballast, source="BOAT_SHOW", show_event_id=show["id"]
        )
        assert o_show["status"] == "WAITLISTED"
        cancel_order(api, o_hold, da)
        assert get_order(api, o_show["id"])["status"] == "ALLOCATED", (
            "boosted BOAT_SHOW waiter must win the promotion"
        )
        assert get_order(api, o_show["id"])["slot_id"] == slot["id"]
        assert get_order(api, o_retail["id"])["status"] == "WAITLISTED", (
            "unboosted earlier RETAIL waiter must lose"
        )
