"""Payments (exact amounts, ordering), cancellation tiers and refunds,
settle/void money conservation, and schedule changes (postpone, reschedule,
backup window)."""
from test_helpers import (
    ApiErrorId,
    create_design,
    create_show,
    create_show_event_payload,
    create_site,
    get_show,
    lock_design,
    pay_show_in_full,
    record_simulation,
    set_clock,
    setup_authorized_show,
    setup_ready_show,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

PLANNER = TEST_USERS["planner_headers"]
FLEET = TEST_USERS["fleet_manager_headers"]


class TestPayments:
    def test_payment_exact_amount_and_order_enforced(self, api):
        """PRD: "A payment with `kind` `DEPOSIT` is accepted only while
        `payment_status` is `DEPOSIT_DUE` (else `ERR_INVALID_STATE`) and its
        amount must equal `deposit_cents` exactly — no partial deposits, no
        overpayments — else `ERR_PAYMENT_AMOUNT_MISMATCH`; acceptance adds the
        amount to `paid_total_cents` and moves the show to `DEPOSIT_PAID`." and
        "The deposit must precede the balance"

        Design: Corner/validations/payment_exact_amount_and_order_enforced
        """
        site = create_site()
        set_clock()
        show = create_show(site["id"])

        # BALANCE before DEPOSIT violates the payment ordering.
        resp = api.record_payment(
            show["id"], {"kind": "BALANCE",
                         "amount_cents": show["balance_cents"]}, PLANNER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        # One cent short of the exact deposit.
        resp = api.record_payment(
            show["id"], {"kind": "DEPOSIT",
                         "amount_cents": show["deposit_cents"] - 1}, PLANNER)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH)

        paid = validate_success(api.record_payment(
            show["id"], {"kind": "DEPOSIT",
                         "amount_cents": show["deposit_cents"]}, PLANNER))
        assert paid["payment_status"] == "DEPOSIT_PAID"
        assert paid["paid_total_cents"] == show["deposit_cents"]


class TestParallelDimensions:
    def test_payment_and_lifecycle_dimensions_move_independently(self, api):
        """PRD: "A freshly booked show carries `lifecycle_status` `PLANNING` and
        `payment_status` `DEPOSIT_DUE` — two parallel state dimensions that
        evolve independently."

        Design: Difficulty/non_linear_state_machine/show_event_parallel_lifecycle_and_payment_dimensions
        """
        site = create_site()
        set_clock()
        show = create_show(site["id"])
        assert show["lifecycle_status"] == "PLANNING"
        assert show["payment_status"] == "DEPOSIT_DUE"

        design = create_design(show["id"])
        record_simulation(design["id"])

        paid = validate_success(api.record_payment(
            show["id"], {"kind": "DEPOSIT",
                         "amount_cents": show["deposit_cents"]}, PLANNER))
        assert paid["payment_status"] == "DEPOSIT_PAID"
        assert paid["lifecycle_status"] == "PLANNING", \
            "payment moved, lifecycle did not"

        lock_design(show["id"], design["id"])
        locked = get_show(show["id"])
        assert locked["lifecycle_status"] == "DESIGN_LOCKED"
        assert locked["payment_status"] == "DEPOSIT_PAID", \
            "lifecycle moved, payment did not"

    def test_cancel_and_settle_move_payment_to_refunded(self, api):
        """PRD: "With at least 168 hours — seven days — the tier is
        `T2_DEPOSIT_HALF`: the deposit portion refunds at half and the balance
        portion in full."
        PRD: "it posts the frozen refund by setting `refunded_total_cents` to
        `refund_due_cents`, moves `cancellation_status` to `SETTLED`, and moves
        `payment_status` to `REFUNDED` from whichever of `DEPOSIT_DUE`,
        `DEPOSIT_PAID`, or `PAID_IN_FULL` it held."

        Design: Difficulty/non_linear_state_machine/show_event_parallel_lifecycle_and_payment_dimensions
        """
        site = create_site()
        set_clock()
        show = create_show(site["id"])  # 10 drones: 551250 / 165375 / 385875
        pay_show_in_full(show["id"])

        # Default clock 2026-08-01: lead 235 hours -> T2_DEPOSIT_HALF.
        cancelled = validate_success(api.cancel_show(show["id"], PLANNER))
        assert cancelled["lifecycle_status"] == "CANCELLED"
        assert cancelled["cancellation_tier"] == "T2_DEPOSIT_HALF"
        assert cancelled["refund_due_cents"] == 468563  # 82688 + 385875

        settled = validate_success(api.settle_cancellation(show["id"], PLANNER))
        assert settled["lifecycle_status"] == "CANCELLED"
        assert settled["payment_status"] == "REFUNDED"
        assert settled["cancellation_status"] == "SETTLED"
        assert settled["refunded_total_cents"] == 468563


class TestCancellationRefundRounding:
    def test_pricing_components_for_two_drones(self, api):
        """PRD: "The pre-surcharge subtotal is a base fee of 500,000 cents (five
        thousand dollars) plus the drone fee." and "The `deposit_cents` is 30
        percent of the contract value, rounded half up to integer cents, and the
        `balance_cents` is the contract value minus the deposit."

        Design: Difficulty/combinatorial_formula/refund_per_component_rounding_then_sum
        """
        site = create_site()
        set_clock()
        show = create_show(site["id"], drone_count_planned=2)
        assert show["contract_value_cents"] == 530250
        assert show["deposit_cents"] == 159075
        assert show["balance_cents"] == 371175

    def test_refund_rounds_each_component_then_sums(self, api):
        """PRD: "The rounding order is pinned: each portion is multiplied by its
        tier percentage and rounded half up to integer cents first, and only
        then are the two rounded components summed." and "Below 72 hours the
        tier is `T4_HALF_ALL`, refunding half of each portion."

        Design: Difficulty/combinatorial_formula/refund_per_component_rounding_then_sum
        """
        site = create_site()
        set_clock()
        show = create_show(site["id"], drone_count_planned=2)
        pay_show_in_full(show["id"])
        # Cancel 24h before the window: tier T4 (half of each portion).
        set_clock("2026-08-09T19:00:00Z")
        cancelled = validate_success(api.cancel_show(show["id"], PLANNER))
        assert cancelled["cancellation_tier"] == "T4_HALF_ALL"
        # round_half_up(159075*0.5)=79538 + round_half_up(371175*0.5)=185588;
        # the forbidden sum-then-round order would yield 265125.
        assert cancelled["refund_due_cents"] == 265126


class TestCancellationLeadTimeBoundary:
    def test_lead_exactly_336h_selects_t1_full(self, api):
        """PRD: "With at least 336 hours of lead time — fourteen days — the tier
        is `T1_FULL` and both portions refund at 100 percent." and "For
        `T1_FULL` alone, an administration fee of 25,000 cents (250 dollars) is
        then subtracted from the sum. Finally the result is floored at zero"

        Design: Difficulty/boundary_precision_check/refund_lead_time_336h_exact_boundary
        """
        site = create_site()
        set_clock()
        show = create_show(site["id"], name="Show S1")  # window Aug 10 19:00
        pay_show_in_full(show["id"])

        # 2026-07-27T19:00 is exactly 336 hours before the window start.
        set_clock("2026-07-27T19:00:00Z")
        cancelled = validate_success(api.cancel_show(show["id"], PLANNER))
        assert cancelled["cancellation_tier"] == "T1_FULL"
        assert cancelled["refund_due_cents"] == 526250  # 551250 - 25000 fee

    def test_lead_one_second_under_336h_selects_t2(self, api):
        """PRD: "With at least 168 hours — seven days — the tier is
        `T2_DEPOSIT_HALF`: the deposit portion refunds at half and the balance
        portion in full."

        Design: Difficulty/boundary_precision_check/refund_lead_time_336h_exact_boundary
        """
        site = create_site()
        set_clock()
        show = create_show(site["id"], name="Show S2",
                           window_start="2026-08-11T19:00:00Z",
                           window_end="2026-08-11T19:30:00Z")
        pay_show_in_full(show["id"])

        # 2026-07-28T19:00:01 is 335h59m59s before the window start.
        set_clock("2026-07-28T19:00:01Z")
        cancelled = validate_success(api.cancel_show(show["id"], PLANNER))
        assert cancelled["cancellation_tier"] == "T2_DEPOSIT_HALF"
        assert cancelled["refund_due_cents"] == 468563  # 82688 + 385875


class TestMoneyConservation:
    def _paid_show_cancelled_t2(self, api):
        site = create_site()
        set_clock()
        show = create_show(site["id"])  # 10 drones, contract 551250
        pay_show_in_full(show["id"])
        set_clock("2026-08-02T19:00:00Z")  # lead 192h -> T2
        cancelled = validate_success(api.cancel_show(show["id"], PLANNER))
        assert cancelled["cancellation_tier"] == "T2_DEPOSIT_HALF"
        assert cancelled["refund_due_cents"] == 468563
        return show

    def test_settle_posts_frozen_refund(self, api):
        """PRD: "**Settling** a cancellation requires the show to be `CANCELLED`
        with `cancellation_status` `FILED` (else `ERR_INVALID_STATE`); it posts
        the frozen refund by setting `refunded_total_cents` to
        `refund_due_cents`, moves `cancellation_status` to `SETTLED`, and moves
        `payment_status` to `REFUNDED` from whichever of `DEPOSIT_DUE`,
        `DEPOSIT_PAID`, or `PAID_IN_FULL` it held."
        PRD: "`paid_total_cents` only ever accumulates and is never decremented
        by any operation."

        Design: Difficulty/compensating_invariant/refund_settle_void_money_conservation
        """
        show = self._paid_show_cancelled_t2(api)
        after_cancel = get_show(show["id"])
        assert after_cancel["refunded_total_cents"] == 0, "refund not yet posted"
        assert after_cancel["paid_total_cents"] == 551250
        assert after_cancel["payment_status"] == "PAID_IN_FULL"

        settled = validate_success(api.settle_cancellation(show["id"], PLANNER))
        assert settled["refunded_total_cents"] == 468563
        assert settled["paid_total_cents"] == 551250, "paid_total never moves"
        assert settled["payment_status"] == "REFUNDED"
        assert settled["cancellation_status"] == "SETTLED"

    def test_void_cancellation_reverses_refund(self, api):
        """PRD: "**Voiding** a settled cancellation requires
        `cancellation_status` `SETTLED` on a `CANCELLED` show (else
        `ERR_INVALID_STATE`); it reverses the refund by zeroing
        `refunded_total_cents`, moves `cancellation_status` to `VOIDED`, and
        recomputes `payment_status` from `paid_total_cents`: zero paid means
        `DEPOSIT_DUE`, an amount equal to `deposit_cents` means `DEPOSIT_PAID`,
        and an amount equal to `contract_value_cents` means `PAID_IN_FULL`. The
        show itself remains `CANCELLED` — voiding is a financial reversal, not a
        resurrection."

        Design: Difficulty/compensating_invariant/refund_settle_void_money_conservation
        """
        show = self._paid_show_cancelled_t2(api)
        validate_success(api.settle_cancellation(show["id"], PLANNER))

        voided = validate_success(api.void_cancellation(show["id"], PLANNER))
        assert voided["refunded_total_cents"] == 0
        assert voided["paid_total_cents"] == 551250, "paid_total never moves"
        assert voided["payment_status"] == "PAID_IN_FULL", \
            "551250 paid equals the contract value"
        assert voided["cancellation_status"] == "VOIDED"
        assert voided["lifecycle_status"] == "CANCELLED"


class TestCancellationStateAndCascade:
    def test_cancel_already_cancelled_returns_invalid_state(self, api):
        """PRD: "**Cancelling** a show is valid from every lifecycle except the
        terminal `EXECUTED` and `CANCELLED` states (else `ERR_INVALID_STATE`)"
        and "computes — once, freezing the result — the cancellation tier and
        the `refund_due_cents`."

        Design: Corner/state_machines/cancel_already_cancelled_returns_invalid_state
        """
        site = create_site()
        set_clock()
        show = create_show(site["id"], drone_count_planned=2)
        cancelled = validate_success(api.cancel_show(show["id"], PLANNER))
        assert cancelled["cancellation_tier"] == "T2_DEPOSIT_HALF"
        assert cancelled["refund_due_cents"] == 0, "nothing was paid"

        resp = api.cancel_show(show["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_show(show["id"])["refund_due_cents"] == 0, "frozen, unchanged"

    def test_cancel_voids_assignments_and_releases_drones(self, api):
        """PRD: "It also cascades through the grid: every `ASSIGNED` launch-grid
        slot for the show becomes `VOIDED`, and each drone released by such a
        void returns from `RESERVED` to `AVAILABLE` with its own version
        incremented. The show lands in `CANCELLED` with posture `NOT_READY`."

        Design: Corner/state_machines/cancel_voids_assignments_and_releases_drones
        """
        ctx = setup_ready_show(
            show_overrides={"drone_count_planned": 2},
            design_overrides={"drone_count": 2})
        show_id = ctx["show"]["id"]
        a1, a2 = ctx["assignments"]
        d1, d2 = ctx["drones"]

        cancelled = validate_success(api.cancel_show(show_id, PLANNER))
        assert cancelled["lifecycle_status"] == "CANCELLED"
        assert cancelled["assigned_count"] == 0

        for assignment_id in (a1["id"], a2["id"]):
            row = validate_success(
                api.get_launch_grid_assignment(assignment_id, FLEET))
            assert row["status"] == "VOIDED"
        for drone in (d1, d2):
            assert validate_success(api.get_drone(drone["id"], FLEET))["status"] \
                == "AVAILABLE"


class TestScheduleChanges:
    def test_postpone_reschedule_auto_advances_to_design_locked(self, api):
        """PRD: "Both paths land the show in `PLANNING`, and both then
        recompute: if the pinned design is still `LOCKED`, the show immediately
        advances to `DESIGN_LOCKED` without further operator action, and the
        posture is recomputed with the show's version incremented."
        PRD: "**Postponing** a show is valid from `AUTHORIZED`, `READY`, or
        `GO_CERTIFIED` (else `ERR_INVALID_STATE`) and moves the show to
        `POSTPONED` with posture `NOT_READY`"

        Design: Corner/state_machines/postpone_reschedule_auto_advances_to_design_locked
        """
        ctx = setup_authorized_show()
        show = ctx["show"]

        postponed = validate_success(api.postpone_show(show["id"], PLANNER,
                                                       payload={"reason":
                                                                "client request"}))
        assert postponed["lifecycle_status"] == "POSTPONED"

        moved = validate_success(api.reschedule_show(
            show["id"], {"window_start": "2026-08-12T19:00:00Z",
                         "window_end": "2026-08-12T19:30:00Z"}, PLANNER))
        assert moved["lifecycle_status"] == "DESIGN_LOCKED", \
            "pinned design still LOCKED, so PLANNING auto-advances"
        assert moved["window_start"] == "2026-08-12T19:00:00Z"

    def test_activate_backup_consumes_window_and_requires_backup(self, api):
        """PRD: "**Activating the backup window** requires a backup window to be
        set with `backup_consumed` still false, and the backup start must be
        strictly after the current logical-clock reading; failures on either
        count are `ERR_BACKUP_WINDOW_UNAVAILABLE`. Activation moves the show's
        window to the backup window, sets `backup_consumed` to true, clears the
        backup fields, and re-runs the turnaround check on the moved window
        (else `ERR_SHOW_WINDOW_CONFLICT`)."

        Design: Corner/state_machines/activate_backup_consumes_window_and_requires_backup
        """
        # S1: backup window reserved; the authorization covers both windows.
        ctx = setup_authorized_show(
            show_overrides={"backup_window_start": "2026-08-12T19:00:00Z",
                            "backup_window_end": "2026-08-12T19:30:00Z"},
            auth_overrides={"window_end": "2026-08-13T21:00:00Z"})
        s1 = ctx["show"]
        validate_success(api.postpone_show(s1["id"], PLANNER))

        # S2: no backup window reserved.
        ctx2 = setup_authorized_show(
            show_overrides={"name": "Show S2",
                            "window_start": "2026-08-20T19:00:00Z",
                            "window_end": "2026-08-20T19:30:00Z",
                            "drone_count_planned": 5},
            design_overrides={"drone_count": 5, "max_altitude_ft": 250,
                              "duration_sec": 300},
            auth_overrides={"window_start": "2026-08-20T18:00:00Z",
                            "window_end": "2026-08-20T21:00:00Z"})
        s2 = ctx2["show"]
        validate_success(api.postpone_show(s2["id"], PLANNER))

        moved = validate_success(api.activate_backup(s1["id"], PLANNER))
        assert moved["lifecycle_status"] == "DESIGN_LOCKED", \
            "auto-advanced: the pinned design is still LOCKED"
        assert moved["window_start"] == "2026-08-12T19:00:00Z"
        assert moved["backup_consumed"] is True

        resp = api.activate_backup(s2["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_BACKUP_WINDOW_UNAVAILABLE)

    def test_show_window_in_past_rejected_at_create_and_reschedule(self, api):
        """PRD: "The window start must be strictly after the current
        logical-clock reading; a window that is not in the future is rejected
        with `ERR_SHOW_WINDOW_IN_PAST`" and "**Rescheduling** replaces the
        window with the supplied `window_start` and `window_end`: the new start
        must be strictly after the current logical-clock reading (else
        `ERR_SHOW_WINDOW_IN_PAST`)"

        Design: Corner/validations/show_window_in_past_rejected_at_create_and_reschedule
        """
        site = create_site()
        set_clock()
        # One second before the current logical-clock reading.
        resp = api.create_show_event(
            create_show_event_payload(site["id"], name="Past Show",
                                      window_start="2026-07-31T23:59:59Z",
                                      window_end="2026-08-01T00:30:00Z",
                                      drone_count_planned=5),
            PLANNER)
        validate_error(resp, ApiErrorId.ERR_SHOW_WINDOW_IN_PAST)

        ctx = setup_authorized_show()
        validate_success(api.postpone_show(ctx["show"]["id"], PLANNER))
        resp = api.reschedule_show(
            ctx["show"]["id"], {"window_start": "2026-07-31T20:00:00Z",
                                "window_end": "2026-07-31T20:30:00Z"}, PLANNER)
        validate_error(resp, ApiErrorId.ERR_SHOW_WINDOW_IN_PAST)
        assert get_show(ctx["show"]["id"])["lifecycle_status"] == "POSTPONED"
