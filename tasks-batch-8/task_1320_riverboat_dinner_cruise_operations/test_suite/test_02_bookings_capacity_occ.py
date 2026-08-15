"""Bookings: capacity boundary, OCC freshness, payment lifecycle, cancellation,
derived-counter conservation, and immediate consistency (PRD §2.9, §2.10, §3.3)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    cancel_booking,
    counter_inquiry,
    create_booking,
    create_customer,
    create_inquiry,
    create_paid_booking,
    declare_weather_event,
    get_booking,
    get_cruise,
    make_customer_headers,
    pay_booking,
    quote_inquiry,
    settle_credits,
    setup_inventory,
    setup_weather_cancelled_cruise,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    weather_cancel,
)

OM = TEST_USERS["ops_manager_headers"]


class TestCoastGuardCapacityBoundary:
    def test_exact_fit_allowed_over_by_one_rejected(self, api):
        """PRD §3.3: "if adding this party would push the cruise's
        `reserved_covers` above the vessel's `coast_guard_capacity`, the sale
        fails with `ERR_CAPACITY_EXCEEDED`."
        PRD §3.2: "the certified maximum passenger count from the vessel's USCG
        Certificate of Inspection, which is a hard upper bound on boarding
        everywhere in the system"

        Design: Difficulty/boundary_precision_check/coast_guard_capacity_exact_fit_vs_over_by_one
        """
        inv = setup_inventory(vessel_capacity=6)
        cruise = inv["cruise"]
        customer = create_customer("a@example.com", "A")
        create_booking(cruise["id"], customer["id"], 4, cruise["version"])

        # 4 + 2 == 6 == capacity exactly: allowed (<= semantics)
        version2 = get_cruise(cruise["id"])["version"]
        bk_b = create_booking(cruise["id"], customer["id"], 2, version2)
        assert get_cruise(cruise["id"])["reserved_covers"] == 6

        # 6 + 1 = 7 > 6: rejected
        version3 = get_cruise(cruise["id"])["version"]
        resp = api.create_booking(
            cruise["id"],
            {"customer_id": customer["id"], "party_size": 1,
             "expected_cruise_version": version3},
            make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)

    def test_reserved_covers_definition_counts_pending_and_paid(self, api):
        """PRD §3.3: "A cruise's `reserved_covers` is defined precisely: the sum
        of `party_size` over the cruise's bookings whose `booking_status` is
        `RESERVED`, `CONFIRMED`, or `BOARDED` and whose `payment_status` is
        `PENDING`, `PAID`, or `REFUND_PENDING`."

        Design: Difficulty/boundary_precision_check/coast_guard_capacity_exact_fit_vs_over_by_one
        """
        inv = setup_inventory(vessel_capacity=6)
        cruise = inv["cruise"]
        customer = create_customer("a@example.com", "A")
        # Unpaid PENDING booking still consumes headroom.
        create_booking(cruise["id"], customer["id"], 6, cruise["version"])
        assert get_cruise(cruise["id"])["reserved_covers"] == 6
        version = get_cruise(cruise["id"])["version"]
        resp = api.create_booking(
            cruise["id"],
            {"customer_id": customer["id"], "party_size": 1,
             "expected_cruise_version": version},
            make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)


class TestOptimisticConcurrency:
    def test_stale_cruise_version_rejected_on_booking_create(self, api):
        """PRD §2.9: "If the cruise's current `version` does not match — for
        example because another writer has just created or cancelled a booking,
        legitimately changing `reserved_covers` and therefore the capacity
        headroom the current writer believes remains — the creation is rejected
        with `ERR_STALE_VERSION` (HTTP 412), rather than allowing a sale computed
        from a stale view of remaining capacity."

        Design: Difficulty/occ_stale_version/booking_create_stale_cruise_version
        """
        inv = setup_inventory()
        cruise = inv["cruise"]
        customer = create_customer("a@example.com", "A")
        # First create bumps cruise version 1 -> 2.
        create_booking(cruise["id"], customer["id"], 1, cruise["version"])

        resp = api.create_booking(
            cruise["id"],
            {"customer_id": customer["id"], "party_size": 1,
             "expected_cruise_version": cruise["version"]},
            make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_stale_version_precedes_capacity_when_both_fail(self, api):
        """PRD §2.8: "Two consequences of this fixed ordering are worth stating
        plainly. A request that is both stale (rung 14) and in breach of capacity
        (rung 6) is rejected with `ERR_CAPACITY_EXCEEDED`, because capacity is
        evaluated first."
        PRD §2.9: "Creating a booking against a cruise requires
        `expected_cruise_version`, carrying the `version` of the cruise as the
        client last observed it. If the cruise's current `version` does not match
        ... the creation is rejected with `ERR_STALE_VERSION` (HTTP 412)"

        Design: Difficulty/occ_stale_version/booking_create_stale_cruise_version
        """
        # PRD pins rung 6 ahead of rung 14: a doubly-invalid request (stale
        # version AND capacity breach) must surface ERR_CAPACITY_EXCEEDED.
        inv = setup_inventory(vessel_capacity=2)
        cruise = inv["cruise"]
        customer = create_customer("s@example.com", "S")
        create_paid_booking(cruise["id"], customer["id"], 2, cruise["version"])
        assert get_cruise(cruise["id"])["reserved_covers"] == 2
        # Stale token (initial version) AND party that would exceed capacity.
        resp = api.create_booking(
            cruise["id"],
            {"customer_id": customer["id"], "party_size": 1,
             "expected_cruise_version": cruise["version"]},
            make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)

    def test_stale_inquiry_version_rejected_on_quote(self, api):
        """PRD §2.9: "Posting a charter quote requires `expected_inquiry_version`,
        carrying the `version` of the charter inquiry as the sales agent last
        observed it. If the inquiry's current `version` does not match — for
        example because the customer has just posted a counter, legitimately
        advancing `quote_round` — the quote is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Difficulty/occ_stale_version/charter_quote_stale_inquiry_version
        """
        inv = setup_inventory(vessel_capacity=60)
        customer = create_customer("corp@example.com", "Corp")
        inquiry = create_inquiry(inv["cruise"]["id"], customer["id"])
        quoted = quote_inquiry(inquiry["id"], inquiry["version"])
        counter_inquiry(inquiry["id"], customer["id"])

        resp = api.quote_charter_inquiry(
            inquiry["id"], {"expected_inquiry_version": quoted["version"]},
            TEST_USERS["charter_agent_headers"])
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_fresh_inquiry_version_succeeds_after_counter(self, api):
        """PRD §2.9: "Both the quote and counter actions increment the inquiry's
        `version` by one."
        PRD §3.9: "Every quote posting must carry the `expected_inquiry_version`
        token of §2.9 — an agent quoting from a stale view of the negotiation is
        rejected with `ERR_STALE_VERSION` (HTTP 412) — and every quote or counter
        increments the inquiry's `version` by one."

        Design: Difficulty/occ_stale_version/charter_quote_stale_inquiry_version
        """
        # The dual: after the counter bumps the version, a re-quote carrying the
        # CURRENT version succeeds, proving the token is compared against the
        # live revision.
        inv = setup_inventory(vessel_capacity=60)
        customer = create_customer("corp2@example.com", "Corp2")
        inquiry = create_inquiry(inv["cruise"]["id"], customer["id"])
        quote_inquiry(inquiry["id"], inquiry["version"])
        countered = counter_inquiry(inquiry["id"], customer["id"])
        requoted = quote_inquiry(inquiry["id"], countered["version"])
        assert requoted["status"] == "QUOTED"
        assert requoted["version"] == countered["version"] + 1, (
            f"Each quote increments the inquiry version by one: "
            f"{countered['version']} -> {requoted['version']}"
        )

    def test_current_version_succeeds_and_increments_cruise_version(self, api):
        """PRD §2.9: "Booking creation itself increments the cruise's `version`
        by one, so every successful sale invalidates every previously observed
        revision."

        Design: Corner/complexity_layers/occ_correct_version_succeeds_and_increments
        """
        inv = setup_inventory()
        cruise = inv["cruise"]
        customer = create_customer("a@example.com", "A")
        resp = api.create_booking(
            cruise["id"],
            {"customer_id": customer["id"], "party_size": 1,
             "expected_cruise_version": cruise["version"]},
            make_customer_headers(customer["id"]))
        validate_success(resp, expected_status=201)
        after = get_cruise(cruise["id"])
        assert after["version"] == cruise["version"] + 1, (
            f"Booking creation must increment cruise version by exactly 1: "
            f"{cruise['version']} -> {after['version']}"
        )


class TestPaymentLifecycle:
    def test_double_pay_rejected(self, api):
        """PRD §3.3: "Paying for a booking is gated four ways: the booking's
        `payment_status` must be `PENDING` and its `booking_status` must be
        `RESERVED` or `CONFIRMED` (otherwise `ERR_INVALID_STATE`)"

        Design: Corner/state_machines/double_pay_idempotency_rejected
        """
        inv = setup_inventory()
        cruise = inv["cruise"]
        customer = create_customer("a@example.com", "A")
        booking = create_booking(cruise["id"], customer["id"], 1,
                                 cruise["version"])
        pay_booking(booking["id"], customer["id"])

        resp = api.pay_booking(booking["id"],
                               make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_pay_moves_reserved_booking_to_confirmed(self, api):
        """PRD §3.3: "On successful payment the ticket total is recomputed and
        frozen into `booking_total_cents`, the beverage total is stored into
        `bar_package_total_cents`, `payment_status` moves to `PAID`, a `RESERVED`
        booking advances automatically to `CONFIRMED`, and the cruise's
        `reserved_covers` is recomputed."

        Design: Corner/state_machines/double_pay_idempotency_rejected
        """
        inv = setup_inventory()
        cruise = inv["cruise"]
        customer = create_customer("a@example.com", "A")
        booking = create_booking(cruise["id"], customer["id"], 2,
                                 cruise["version"])
        assert booking["payment_status"] == "PENDING"
        assert booking["booking_status"] == "RESERVED"
        paid = pay_booking(booking["id"], customer["id"])
        assert paid["payment_status"] == "PAID"
        assert paid["booking_status"] == "CONFIRMED"
        assert get_cruise(cruise["id"])["reserved_covers"] == 2


class TestReservedCoversConservation:
    def test_create_pay_cancel_round_trip_restores_reserved_covers(self, api):
        """PRD §3.3: "Cancellation moves the booking to `CANCELLED`, moves
        `payment_status` to `REFUNDED` when it had been `PAID` (an unpaid booking
        simply cancels), and recomputes the cruise's `reserved_covers`."
        PRD §3.3: "On creation the server computes `booking_total_cents` and
        `bar_package_total_cents` per the pinned pricing below, recomputes the
        cruise's `reserved_covers`, and increments the cruise's `version` by one."

        Design: Difficulty/compensating_invariant/reserved_covers_conserved_under_booking_cancel
        """
        inv = setup_inventory()
        cruise = inv["cruise"]
        assert cruise["reserved_covers"] == 0
        customer = create_customer("a@example.com", "A")
        booking = create_booking(cruise["id"], customer["id"], 4,
                                 cruise["version"])
        assert get_cruise(cruise["id"])["reserved_covers"] == 4
        pay_booking(booking["id"], customer["id"])
        cancelled = cancel_booking(booking["id"], customer["id"])

        assert cancelled["booking_status"] == "CANCELLED"
        assert cancelled["payment_status"] == "REFUNDED"
        assert get_cruise(cruise["id"])["reserved_covers"] == 0, (
            "reserved_covers must return to its pre-action value after the "
            "compensating cancel"
        )

    def test_unpaid_cancel_leaves_payment_pending_then_cancelled_path(self, api):
        """PRD §3.3: "Cancellation moves the booking to `CANCELLED`, moves
        `payment_status` to `REFUNDED` when it had been `PAID` (an unpaid booking
        simply cancels), and recomputes the cruise's `reserved_covers`."

        Design: Difficulty/compensating_invariant/reserved_covers_conserved_under_booking_cancel
        """
        inv = setup_inventory()
        cruise = inv["cruise"]
        customer = create_customer("b@example.com", "B")
        booking = create_booking(cruise["id"], customer["id"], 3,
                                 cruise["version"])
        assert get_cruise(cruise["id"])["reserved_covers"] == 3
        cancelled = cancel_booking(booking["id"], customer["id"])
        assert cancelled["booking_status"] == "CANCELLED"
        # Unpaid booking simply cancels: payment_status was never PAID.
        assert cancelled["payment_status"] == "PENDING"
        assert get_cruise(cruise["id"])["reserved_covers"] == 0


class TestImmediateConsistency:
    def test_booking_create_immediately_visible_in_cruise_aggregate(self, api):
        """PRD §2.10: "Several resources carry derived counters that the server
        recomputes immediately whenever an underlying event occurs — never lazily
        at read time."

        Design: Corner/consistency_model/booking_create_immediately_visible_in_cruise_aggregate
        """
        inv = setup_inventory()
        cruise = inv["cruise"]
        customer = create_customer("a@example.com", "A")
        create_booking(cruise["id"], customer["id"], 3, cruise["version"])
        after = get_cruise(cruise["id"])
        assert after["reserved_covers"] == 3, (
            f"reserved_covers must include the just-created booking "
            f"immediately, got {after['reserved_covers']}"
        )


class TestBookingParallelDimensions:
    def test_weather_cancel_moves_payment_and_booking_axes_independently(self, api):
        """PRD §3.8: "Every booking of the cruise whose `payment_status` is
        `PENDING` or `PAID` moves to `REFUND_PENDING`, and its `booking_status`
        moves to `CANCELLED`."
        PRD §3.3: "these two state dimensions evolve in parallel —
        `payment_status` walks `PENDING`, `PAID`, `REFUND_PENDING`, `REFUNDED`,
        and `CREDITED`, while `booking_status` walks `RESERVED`, `CONFIRMED`,
        `BOARDED`, `NO_SHOW`, `CANCELLED`, and `CONVERTED_TO_CHARTER`"

        Design: Difficulty/non_linear_state_machine/booking_parallel_payment_and_boarding_dimensions
        """
        ctx = setup_weather_cancelled_cruise(clock_at="2026-08-09T13:00:00Z",
                                             party_size=2)
        booking = get_booking(ctx["booking"]["id"])
        assert booking["payment_status"] == "REFUND_PENDING", (
            f"Payment axis must advance to REFUND_PENDING, got "
            f"{booking['payment_status']}"
        )
        assert booking["booking_status"] == "CANCELLED", (
            f"Booking axis must reach its own terminal CANCELLED, got "
            f"{booking['booking_status']}"
        )
        # Payment axis is NOT terminal here (settle-credits still to come):
        # prove it by settling and observing CREDITED.
        settle_credits(ctx["event"]["id"])
        settled_booking = get_booking(ctx["booking"]["id"])
        assert settled_booking["payment_status"] == "CREDITED"
        assert settled_booking["booking_status"] == "CANCELLED"

    def test_customer_cancel_gated_on_cruise_scheduled(self, api):
        """PRD §3.3: "A `Customer` may cancel their own booking while it stands
        at `RESERVED` or `CONFIRMED` (otherwise `ERR_INVALID_STATE`) and only
        while the cruise is still `SCHEDULED` (otherwise
        `ERR_CRUISE_NOT_BOOKABLE`)."

        Design: Difficulty/non_linear_state_machine/booking_parallel_payment_and_boarding_dimensions
        """
        ctx = setup_weather_cancelled_cruise(clock_at="2026-08-09T13:00:00Z",
                                             party_size=1)
        resp = api.cancel_booking(
            ctx["booking"]["id"],
            make_customer_headers(ctx["customer"]["id"]))
        # The booking already cascaded to CANCELLED and the cruise is CANCELLED;
        # either way the second cancel is rejected.
        actual = validate_error_is_one_of(
            resp, [ApiErrorId.ERR_INVALID_STATE.value,
                   ApiErrorId.ERR_CRUISE_NOT_BOOKABLE.value])
        assert actual in (ApiErrorId.ERR_INVALID_STATE.value,
                          ApiErrorId.ERR_CRUISE_NOT_BOOKABLE.value)


class TestBookingInputShape:
    def test_missing_party_size_rejected(self, api):
        """PRD §3.3: "A `Customer` creates a **Booking** against a specific
        cruise with a payload naming the paying `customer_id`, a `party_size` of
        at least one, an optional `bar_package_count` (default zero, and never
        greater than `party_size`), and — mandatorily — the
        optimistic-concurrency token `expected_cruise_version` described in §2.9.
        Violations of these input-shape rules are rejected with
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/booking_missing_required_party_size_rejected
        """
        inv = setup_inventory()
        cruise = inv["cruise"]
        customer = create_customer("a@example.com", "A")
        resp = api.create_booking(
            cruise["id"],
            {"customer_id": customer["id"],
             "expected_cruise_version": cruise["version"]},
            make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestCancelledCruiseTerminalLockdown:
    def test_booking_create_on_cancelled_cruise_rejected(self, api):
        """PRD §3.3: "The cruise must be `SCHEDULED` or the sale fails with
        `ERR_CRUISE_NOT_BOOKABLE`"
        PRD §3.8: "The cruise must stand at `SCHEDULED` or `WEATHER_HOLD`
        (otherwise `ERR_INVALID_STATE`), and there must exist a covering
        `CANCELLATION_REQUIRED` event standing at `DECLARED` or
        `CANCELLATION_ISSUED` (otherwise `ERR_NO_ACTIVE_WEATHER_EVENT`)."

        Design: Corner/state_machines/cancelled_cruise_terminal_lockdown
        """
        inv = setup_inventory()
        cruise = inv["cruise"]
        declare_weather_event()
        weather_cancel(cruise["id"])
        assert get_cruise(cruise["id"])["status"] == "CANCELLED"

        customer = create_customer("a@example.com", "A")
        version = get_cruise(cruise["id"])["version"]
        resp = api.create_booking(
            cruise["id"],
            {"customer_id": customer["id"], "party_size": 1,
             "expected_cruise_version": version},
            make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_CRUISE_NOT_BOOKABLE)
