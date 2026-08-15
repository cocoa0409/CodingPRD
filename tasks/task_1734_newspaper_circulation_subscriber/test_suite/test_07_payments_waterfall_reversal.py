"""Payments: waterfall allocation, overpayment, reversal cascade, ledger conservation."""
from test_helpers import (
    DIRECTOR,
    REP,
    ApiErrorId,
    create_active_subscription,
    create_subscriber,
    get_subscriber,
    get_subscription,
    list_charges_for_subscription,
    pay_and_clear,
    run_daily_cycle,
    set_clock,
    set_clock_and_cycle,
    setup_two_charge_subscription,
    create_plan,
    create_subscription,
    validate_error,
    validate_success,
)


class TestWaterfallAllocation:
    def test_waterfall_allocation_oldest_due_first(self, api):
        """PRD §3.8: "Allocation walks them oldest-due-first — `due_date`
        ascending, ties broken by `created_at` ascending, never by id —
        taking from each charge the lesser of the remaining funds and that
        charge's outstanding, crediting `paid_amount_cents` (for a payment)
        or `credit_applied_cents` (for a credit memo), and flipping the
        charge to `PAID` when fully covered or `PARTIALLY_PAID` when
        partially."
        PRD §3.8: "The payment records the result in its `allocations` list —
        each entry pairing a `charge_id` with the `amount_cents` applied, in
        allocation order."

        Design: Corner/calculations/waterfall_allocation_oldest_due_first
        """
        ctx = setup_two_charge_subscription(weekly_rate_cents=600)
        charge1, charge2 = ctx["charges"]

        payment = validate_success(
            api.create_payment(
                {"subscriber_id": ctx["subscriber"]["id"], "amount_cents": 700, "method": "CHECK"},
                REP,
            ),
            201,
        )
        cleared = validate_success(api.mark_payment_cleared(payment["id"], REP))

        assert cleared["allocations"] == [
            {"charge_id": charge1["id"], "amount_cents": 600},
            {"charge_id": charge2["id"], "amount_cents": 100},
        ], "waterfall must cover the oldest-due charge first, in allocation order"

        charges = list_charges_for_subscription(ctx["subscription"]["id"])
        by_id = {c["id"]: c for c in charges}
        assert by_id[charge1["id"]]["status"] == "PAID"
        assert by_id[charge2["id"]]["status"] == "PARTIALLY_PAID"
        assert by_id[charge2["id"]]["paid_amount_cents"] == 100

    def test_waterfall_partial_then_full_coverage_flips_statuses(self, api):
        """PRD §3.8: "The eligible set is the subscriber's charges in `OPEN`
        or `PARTIALLY_PAID` status with positive outstanding."
        PRD §3.8: "crediting `paid_amount_cents` (for a payment) or
        `credit_applied_cents` (for a credit memo), and flipping the charge
        to `PAID` when fully covered or `PARTIALLY_PAID` when partially."

        Design: Corner/calculations/waterfall_allocation_oldest_due_first
        """
        ctx = setup_two_charge_subscription(weekly_rate_cents=600)

        pay_and_clear(ctx["subscriber"]["id"], 300)
        charges = list_charges_for_subscription(ctx["subscription"]["id"])
        assert charges[0]["status"] == "PARTIALLY_PAID"
        assert charges[0]["paid_amount_cents"] == 300
        assert charges[1]["status"] == "OPEN"

        pay_and_clear(ctx["subscriber"]["id"], 900)
        charges = list_charges_for_subscription(ctx["subscription"]["id"])
        assert all(c["status"] == "PAID" for c in charges)


class TestOverpayment:
    def test_waterfall_overpayment_to_unapplied(self, api):
        """PRD §3.8: "A payment's leftover remainder lands in the
        subscriber's `unapplied_cash_cents`; a credit memo's leftover stays
        on the memo, which remains `ISSUED`."
        PRD §2.6: "The subscriber's `balance_due_cents` is the sum of
        outstanding amounts over all charges in `OPEN`, `PARTIALLY_PAID`, or
        `PAID` status, minus the subscriber's `unapplied_cash_cents`
        (overpayment remainder not yet allocated to any charge)."

        Design: Corner/calculations/waterfall_overpayment_to_unapplied
        """
        ctx = setup_two_charge_subscription(weekly_rate_cents=600)
        pay_and_clear(ctx["subscriber"]["id"], 1500, method="CASH")

        subscriber = get_subscriber(ctx["subscriber"]["id"])
        assert subscriber["unapplied_cash_cents"] == 300
        assert subscriber["balance_due_cents"] == -300

    def test_waterfall_exact_coverage_leaves_no_unapplied(self, api):
        """PRD §2.6: "The subscriber's `balance_due_cents` is the sum of
        outstanding amounts over all charges in `OPEN`, `PARTIALLY_PAID`, or
        `PAID` status, minus the subscriber's `unapplied_cash_cents`
        (overpayment remainder not yet allocated to any charge)."

        Design: Corner/calculations/waterfall_overpayment_to_unapplied
        """
        ctx = setup_two_charge_subscription(weekly_rate_cents=600)
        pay_and_clear(ctx["subscriber"]["id"], 1200)

        subscriber = get_subscriber(ctx["subscriber"]["id"])
        assert subscriber["unapplied_cash_cents"] == 0
        assert subscriber["balance_due_cents"] == 0


class TestReversalLoop:
    def test_billing_charge_paid_to_open_reversal_loop(self, api):
        """PRD §3.8: "First, each allocation is undone in reverse allocation
        order: the charge's `paid_amount_cents` is restored downward, and
        charge statuses revert — a `PAID` charge whose covered amount returns
        to zero flips all the way back to `OPEN`, while partial restoration
        lands at `PARTIALLY_PAID` or `OPEN` accordingly."
        PRD §3.8: "The payment ends in `REVERSED`."

        Design: Difficulty/non_linear_state_machine/billing_charge_paid_to_open_reversal_loop
        """
        ctx = create_active_subscription(
            start_date="2026-08-03",
            clock="2026-08-03T00:00:00Z",
            plan_overrides={
                "name": "LOOP", "plan_type": "DIGITAL", "issues_per_week": 0,
                "base_weekly_rate_cents": 600,
            },
        )
        payment = pay_and_clear(ctx["subscriber"]["id"], 600, method="ACH")

        charges = list_charges_for_subscription(ctx["subscription"]["id"])
        assert charges[0]["status"] == "PAID"
        assert charges[0]["paid_amount_cents"] == 600

        validate_success(api.reverse_payment(payment["id"], DIRECTOR))

        charge_after = validate_success(api.get_billing_charge(charges[0]["id"], REP))
        assert charge_after["status"] == "OPEN"
        assert charge_after["paid_amount_cents"] == 0

        payment_after = validate_success(api.get_payment(payment["id"], REP))
        assert payment_after["status"] == "REVERSED"

    def test_reversal_restores_partially_paid_charge_to_open(self, api):
        """PRD §3.8: "First, each allocation is undone in reverse allocation
        order: the charge's `paid_amount_cents` is restored downward, and
        charge statuses revert — a `PAID` charge whose covered amount returns
        to zero flips all the way back to `OPEN`, while partial restoration
        lands at `PARTIALLY_PAID` or `OPEN` accordingly."

        Design: Difficulty/non_linear_state_machine/billing_charge_paid_to_open_reversal_loop
        """
        ctx = setup_two_charge_subscription(weekly_rate_cents=600)
        charge1, charge2 = ctx["charges"]
        payment = pay_and_clear(ctx["subscriber"]["id"], 900)

        mid = {c["id"]: c for c in list_charges_for_subscription(ctx["subscription"]["id"])}
        assert mid[charge1["id"]]["status"] == "PAID"
        assert mid[charge2["id"]]["status"] == "PARTIALLY_PAID"

        validate_success(api.reverse_payment(payment["id"], DIRECTOR))

        after = {c["id"]: c for c in list_charges_for_subscription(ctx["subscription"]["id"])}
        assert after[charge1["id"]]["status"] == "OPEN"
        assert after[charge1["id"]]["paid_amount_cents"] == 0
        assert after[charge2["id"]]["status"] == "OPEN"
        assert after[charge2["id"]]["paid_amount_cents"] == 0


class TestReversalDepth3Cascade:
    def test_payment_reversal_depth3_cascade(self, api):
        """PRD §3.8: "It unwinds in three depths. First, each allocation is
        undone in reverse allocation order: the charge's `paid_amount_cents`
        is restored downward, and charge statuses revert — a `PAID` charge
        whose covered amount returns to zero flips all the way back to
        `OPEN`, while partial restoration lands at `PARTIALLY_PAID` or `OPEN`
        accordingly. Second, the charge restorations force the subscriber's
        `balance_due_cents` to recompute upward and claw back the reversed
        remainder from `unapplied_cash_cents`. Third, the worsened balance
        triggers subscription billing re-evaluation, which can flip `ACTIVE`
        to `GRACE` or `GRACE` to `SUSPENDED` under the same lapse
        thresholds."

        Design: Difficulty/transitive_cascade/payment_reversal_depth3_cascade
        """
        ctx = setup_two_charge_subscription(weekly_rate_cents=600)
        charge1, charge2 = ctx["charges"]
        payment = pay_and_clear(ctx["subscriber"]["id"], 900)
        assert get_subscriber(ctx["subscriber"]["id"])["balance_due_cents"] == 300

        # Advance the clock WITHOUT running the batch, so billing is still
        # ACTIVE when the reversal fires its re-evaluation.
        set_clock("2026-08-26T00:00:00Z")
        assert get_subscription(ctx["subscription"]["id"])["billing_status"] == "ACTIVE"

        validate_success(api.reverse_payment(payment["id"], DIRECTOR))

        # Link 1: allocations undone.
        charges = {c["id"]: c for c in list_charges_for_subscription(ctx["subscription"]["id"])}
        assert charges[charge1["id"]]["status"] == "OPEN"
        assert charges[charge1["id"]]["paid_amount_cents"] == 0
        assert charges[charge2["id"]]["status"] == "OPEN"
        assert charges[charge2["id"]]["paid_amount_cents"] == 0

        # Link 2: balance recomputed upward.
        subscriber = get_subscriber(ctx["subscriber"]["id"])
        assert subscriber["balance_due_cents"] == 1200
        assert subscriber["unapplied_cash_cents"] == 0

        # Link 3: oldest charge 9 days past due > GRACE_DAYS 7 -> GRACE,
        # from the reversal's own re-evaluation (no batch run).
        assert get_subscription(ctx["subscription"]["id"])["billing_status"] == "GRACE"

    def test_payment_reversal_cascade_reaches_suspended(self, api):
        """PRD §3.8: "Third, the worsened balance triggers subscription
        billing re-evaluation, which can flip `ACTIVE` to `GRACE` or `GRACE`
        to `SUSPENDED` under the same lapse thresholds."

        Design: Difficulty/transitive_cascade/payment_reversal_depth3_cascade
        """
        ctx = setup_two_charge_subscription(weekly_rate_cents=600)
        payment = pay_and_clear(ctx["subscriber"]["id"], 1200)

        # 22 days past due for the oldest charge (due 2026-08-17) without a
        # batch run: billing still ACTIVE until the reversal re-evaluates.
        set_clock("2026-09-08T00:00:00Z")
        assert get_subscription(ctx["subscription"]["id"])["billing_status"] == "ACTIVE"

        validate_success(api.reverse_payment(payment["id"], DIRECTOR))
        assert get_subscription(ctx["subscription"]["id"])["billing_status"] == "SUSPENDED"


class TestLedgerConservation:
    def test_payment_clear_reverse_ledger_conservation(self, api):
        """PRD §2.6: "The subscriber's `balance_due_cents` is the sum of
        outstanding amounts over all charges in `OPEN`, `PARTIALLY_PAID`, or
        `PAID` status, minus the subscriber's `unapplied_cash_cents`
        (overpayment remainder not yet allocated to any charge)."
        PRD §3.8: "Second, the charge restorations force the subscriber's
        `balance_due_cents` to recompute upward and claw back the reversed
        remainder from `unapplied_cash_cents`."

        Design: Difficulty/compensating_invariant/payment_clear_reverse_ledger_conservation
        """
        ctx = setup_two_charge_subscription(weekly_rate_cents=600)

        before = get_subscriber(ctx["subscriber"]["id"])
        assert before["balance_due_cents"] == 1200
        assert before["unapplied_cash_cents"] == 0

        payment = pay_and_clear(ctx["subscriber"]["id"], 900)
        mid = get_subscriber(ctx["subscriber"]["id"])
        assert mid["balance_due_cents"] == 300

        validate_success(api.reverse_payment(payment["id"], DIRECTOR))
        after = get_subscriber(ctx["subscriber"]["id"])
        assert after["balance_due_cents"] == 1200
        assert after["unapplied_cash_cents"] == 0

        charges = list_charges_for_subscription(ctx["subscription"]["id"])
        for charge in charges:
            assert charge["paid_amount_cents"] == 0
            assert charge["status"] == "OPEN"

    def test_ledger_balance_formula_holds_after_partial_clear(self, api):
        """PRD §2.6: "A charge's outstanding amount is its `amount_cents`
        minus `paid_amount_cents` minus `credit_applied_cents`. The
        subscriber's `balance_due_cents` is the sum of outstanding amounts
        over all charges in `OPEN`, `PARTIALLY_PAID`, or `PAID` status, minus
        the subscriber's `unapplied_cash_cents` (overpayment remainder not
        yet allocated to any charge)."

        Design: Difficulty/compensating_invariant/payment_clear_reverse_ledger_conservation
        """
        ctx = setup_two_charge_subscription(weekly_rate_cents=600)
        pay_and_clear(ctx["subscriber"]["id"], 700)

        subscriber = get_subscriber(ctx["subscriber"]["id"])
        charges = list_charges_for_subscription(ctx["subscription"]["id"])
        outstanding = sum(
            c["amount_cents"] - c["paid_amount_cents"] - c["credit_applied_cents"]
            for c in charges
            if c["status"] in ("OPEN", "PARTIALLY_PAID", "PAID")
        )
        assert subscriber["balance_due_cents"] == outstanding - subscriber["unapplied_cash_cents"]
        assert subscriber["balance_due_cents"] == 500


class TestPaymentPreconditions:
    def test_payment_reverse_requires_cleared_rejected(self, api):
        """PRD §3.8: "Reversal is the deepest compensation in the system,
        reserved for `CirculationDirector`, and only available on a `CLEARED`
        payment (otherwise `ERR_PAYMENT_NOT_CLEARED`)."

        Design: Corner/state_machines/payment_reverse_requires_cleared_rejected
        """
        subscriber = create_subscriber(display_name="PR", email="pr@x.com")
        payment = validate_success(
            api.create_payment(
                {"subscriber_id": subscriber["id"], "amount_cents": 500, "method": "CARD"},
                REP,
            ),
            201,
        )
        assert payment["status"] == "INITIATED"

        resp = api.reverse_payment(payment["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_NOT_CLEARED, 409)

        after = validate_success(api.get_payment(payment["id"], REP))
        assert after["status"] == "INITIATED"

    def test_double_mark_cleared_rejected(self, api):
        """PRD §3.8: "Clearing or failing a payment that is not `INITIATED`
        is rejected with `ERR_PAYMENT_NOT_INITIATED`; failing simply stamps
        `FAILED` with no ledger effects."

        Design: Corner/errors/double_mark_cleared_rejected
        """
        subscriber = create_subscriber(display_name="DM", email="dm@x.com")
        payment = validate_success(
            api.create_payment(
                {"subscriber_id": subscriber["id"], "amount_cents": 500, "method": "CARD"},
                REP,
            ),
            201,
        )
        cleared = validate_success(api.mark_payment_cleared(payment["id"], REP))
        assert cleared["status"] == "CLEARED"

        resp = api.mark_payment_cleared(payment["id"], REP)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_NOT_INITIATED, 409)
