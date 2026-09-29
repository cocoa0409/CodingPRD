"""Upgrade quoting, the settlement assembly order, application and reversal."""

from test_helpers import (
    BRONZE,
    GOLD,
    ApiErrorId,
    CreditMode,
    PaymentMode,
    ProgramStatus,
    TierSpec,
    UpgradeOrderStatus,
    apply_upgrade,
    assert_instant_equals,
    assert_installment_statuses,
    assert_ledger,
    assert_upgrade_settlement,
    build_active_pass,
    build_plan,
    build_program,
    compliance_officer_headers,
    create_park_day,
    get_pass,
    plan_installments,
    quote_upgrade,
    reverse_upgrade,
    reverse_upgrade_payload,
    settle_installment,
    validate_error,
)

PLATINUM = TierSpec(
    name="PLATINUM",
    tier_rank=5,
    base_price_cents=55000,
    in_park_discount_pct=0.20,
    peak_reservation_quota=9,
    parking_benefit="INCLUDED",
)


def _bronze_pass_with_two_settled_installments(api):
    """A BRONZE pass on a four-installment plan with 8250 cents paid to date."""
    program = build_program(api, tiers=(BRONZE, GOLD), status=ProgramStatus.SALES_OPEN.value)
    pass_ctx = build_active_pass(
        api, program, tier_name="BRONZE", payment_mode=PaymentMode.PAYMENT_PLAN.value
    )
    plan_ctx = build_plan(api, pass_ctx.id, 3000, 4, "2026-09-01")
    settle_installment(api, plan_ctx.installment(1)["id"], 2625)
    settle_installment(api, plan_ctx.installment(2)["id"], 2625)
    return program, pass_ctx, plan_ctx


class TestUpgradeCreditModesDiverge:
    """The two credit modes read different facts and produce different totals."""

    def test_paid_to_date_credits_every_cent_handed_over(self, api, default_clock):
        """Under PAID_TO_DATE the raw credit is the pass's paid-to-date figure.

        PRD: "Under `PAID_TO_DATE`, the raw credit is simply the pass's
        `paid_to_date_cents` — every cent the guest has actually handed over on the
        source tier, comprising the down payment, all settled installments and any
        prior upgrade payments."

        Design: Difficulty/dual_variant_calc/upgrade_credit_paid_to_date_vs_prorated_diverge
        """
        program, pass_ctx, _ = _bronze_pass_with_two_settled_installments(api)
        for calendar_date in ("2026-07-15", "2026-08-10", "2026-08-20", "2026-09-05"):
            create_park_day(api, program.id, calendar_date)

        order = quote_upgrade(
            api,
            pass_ctx.id,
            program.tier_id("BRONZE"),
            program.tier_id("GOLD"),
            credit_mode=CreditMode.PAID_TO_DATE.value,
        )

        assert_upgrade_settlement(
            order, gross=18000, raw_credit=8250, credit=8250, net=9750, admin_fee=1000, total_due=10750
        )

    def test_prorated_value_credits_the_unconsumed_share_of_the_list_price(self, api, default_clock):
        """Three of four operating days ahead makes the ratio 0.7500 and the credit 9000.

        PRD: "A Bronze pass listed at 12000 cents upgrading to Gold, with 8250 cents
        paid to date and three of the programme's four park days still ahead, credits
        8250 under `PAID_TO_DATE`; under `PRORATED_VALUE` the ratio is `0.7500` and the
        raw credit is 12000 multiplied by that, which is 9000."

        Design: Difficulty/dual_variant_calc/upgrade_credit_paid_to_date_vs_prorated_diverge
        """
        program, pass_ctx, _ = _bronze_pass_with_two_settled_installments(api)
        for calendar_date in ("2026-07-15", "2026-08-10", "2026-08-20", "2026-09-05"):
            create_park_day(api, program.id, calendar_date)

        order = quote_upgrade(
            api,
            pass_ctx.id,
            program.tier_id("BRONZE"),
            program.tier_id("GOLD"),
            credit_mode=CreditMode.PRORATED_VALUE.value,
        )

        assert_upgrade_settlement(
            order, gross=18000, raw_credit=9000, credit=9000, net=9000, admin_fee=1000, total_due=10000
        )

    def test_both_quotes_coexist_and_leave_the_pass_untouched(self, api, default_clock):
        """Quoting is a read of the pass: two quotes differ by 750 and change nothing.

        PRD: "The modes therefore move in opposite directions over a season — the
        paid-to-date credit rises as installments settle and never looks at the
        calendar, while the prorated credit falls as the season is consumed and never
        looks at how much has been paid — and on identical data either can be the
        larger."

        Design: Difficulty/dual_variant_calc/upgrade_credit_paid_to_date_vs_prorated_diverge
        """
        program, pass_ctx, _ = _bronze_pass_with_two_settled_installments(api)
        for calendar_date in ("2026-07-15", "2026-08-10", "2026-08-20", "2026-09-05"):
            create_park_day(api, program.id, calendar_date)

        paid_order = quote_upgrade(
            api,
            pass_ctx.id,
            program.tier_id("BRONZE"),
            program.tier_id("GOLD"),
            credit_mode=CreditMode.PAID_TO_DATE.value,
        )
        prorated_order = quote_upgrade(
            api,
            pass_ctx.id,
            program.tier_id("BRONZE"),
            program.tier_id("GOLD"),
            credit_mode=CreditMode.PRORATED_VALUE.value,
        )

        assert paid_order["total_due_cents"] - prorated_order["total_due_cents"] == 750, (
            "the two credit modes should diverge by 750 cents on this data, got "
            f"{paid_order['total_due_cents']} and {prorated_order['total_due_cents']}"
        )
        for order in (paid_order, prorated_order):
            assert order["status"] == UpgradeOrderStatus.QUOTED.value, (
                f"a new order should open QUOTED, got {order['status']!r}"
            )
        pass_row = get_pass(api, pass_ctx.id)
        assert pass_row["tier_id"] == program.tier_id("BRONZE"), (
            "a quote must not move the pass onto the target tier"
        )
        assert_ledger(pass_row, paid=8250, credited=0)


class TestUpgradeSettlementAssemblyOrder:
    """The fee band is keyed on the post-credit figure, not on the gross delta."""

    def test_a_785_cent_net_delta_attracts_no_admin_fee(self, api, default_clock):
        """The PRD's Gold-to-Platinum example: gross 25000, credit 24215, fee nothing.

        PRD: "a Gold pass listed at 30000 cents moving to Platinum at 55000 cents,
        under `PAID_TO_DATE` with 24215 cents paid, has a gross delta of 25000, a raw
        credit of 24215, a capped credit of 24215, a net delta of 785, and therefore a
        fee of nothing at all, for a total due of 785 cents."

        Design: Difficulty/combinatorial_formula/upgrade_settlement_order_credit_cap_then_fee_tier
        """
        program = build_program(
            api, tiers=(GOLD, PLATINUM), status=ProgramStatus.SALES_OPEN.value
        )
        pass_ctx = build_active_pass(
            api, program, tier_name="GOLD", payment_mode=PaymentMode.PAYMENT_PLAN.value
        )
        plan_ctx = build_plan(api, pass_ctx.id, 6000, 7, "2026-09-01")
        for sequence_no in (1, 2, 3, 4, 5):
            settle_installment(api, plan_ctx.installment(sequence_no)["id"], 3643)

        order = quote_upgrade(
            api,
            pass_ctx.id,
            program.tier_id("GOLD"),
            program.tier_id("PLATINUM"),
            credit_mode=CreditMode.PAID_TO_DATE.value,
        )

        assert_upgrade_settlement(
            order, gross=25000, raw_credit=24215, credit=24215, net=785, admin_fee=0, total_due=785
        )

    def test_the_quote_is_stamped_from_the_logical_clock_and_lasts_fourteen_days(
        self, api, default_clock
    ):
        """The order opens QUOTED with expiry fourteen days after the quote instant.

        PRD: "A new order opens with `status` `QUOTED`, records the computed
        `gross_delta_cents`, `raw_credit_cents`, `credit_cents`, `net_delta_cents`,
        `admin_fee_cents` and `total_due_cents`, stamps `quoted_at` with the logical
        clock's current instant, sets `quote_expires_at` to fourteen days after
        `quoted_at`, and leaves `payment_amount_cents` and `reverse_reason` null."

        Design: Difficulty/combinatorial_formula/upgrade_settlement_order_credit_cap_then_fee_tier
        """
        program = build_program(
            api, tiers=(GOLD, PLATINUM), status=ProgramStatus.SALES_OPEN.value
        )
        pass_ctx = build_active_pass(
            api, program, tier_name="GOLD", payment_mode=PaymentMode.PAYMENT_PLAN.value
        )
        plan_ctx = build_plan(api, pass_ctx.id, 6000, 7, "2026-09-01")
        for sequence_no in (1, 2, 3, 4, 5):
            settle_installment(api, plan_ctx.installment(sequence_no)["id"], 3643)

        order = quote_upgrade(
            api,
            pass_ctx.id,
            program.tier_id("GOLD"),
            program.tier_id("PLATINUM"),
            credit_mode=CreditMode.PAID_TO_DATE.value,
        )

        assert order["status"] == UpgradeOrderStatus.QUOTED.value, (
            f"a new order should open QUOTED, got {order['status']!r}"
        )
        assert_instant_equals(order["quoted_at"], "2026-08-01T00:00:00Z", "quoted_at")
        assert_instant_equals(order["quote_expires_at"], "2026-08-15T00:00:00Z", "quote_expires_at")
        assert order["payment_amount_cents"] is None, (
            f"payment_amount_cents should still be null on a quote, got {order['payment_amount_cents']!r}"
        )
        assert order["reverse_reason"] is None, (
            f"reverse_reason should still be null on a quote, got {order['reverse_reason']!r}"
        )


class TestProratedCreditWithNoOperatingCalendar:
    """With no park days at all the prorated ratio is pinned to zero."""

    def _bronze_pass_in_a_programme_with_no_park_days(self, api):
        program = build_program(api, tiers=(BRONZE, GOLD), status=ProgramStatus.SALES_OPEN.value)
        pass_ctx = build_active_pass(
            api, program, tier_name="BRONZE", payment_mode=PaymentMode.PAY_IN_FULL.value
        )
        return program, pass_ctx

    def test_the_credit_mode_alone_moves_the_total_due_by_the_whole_payment(
        self, api, default_clock
    ):
        """One pass, two modes: 12000 credited or nothing credited.

        PRD: "Under `PRORATED_VALUE`, the raw credit is the unconsumed share of the source
        tier's list price, measured in remaining operating days: count all park days
        belonging to the pass's programme and call that the total-days figure; count those
        of them whose `calendar_date` falls on or after the logical clock's current date and
        call that the future-days figure; the remaining ratio is the future-days figure
        divided by the total-days figure, rounded half up to four decimal places, except
        that when the programme has no park days at all the ratio is taken as `0.0000`
        rather than dividing; and the raw credit is the source tier's `base_price_cents`
        multiplied by that ratio, truncated down to a whole number of cents."

        Design: Corner/calculations/upgrade_credit_prorated_variant_selected_with_no_park_days
        """
        program, pass_ctx = self._bronze_pass_in_a_programme_with_no_park_days(api)
        assert_ledger(get_pass(api, pass_ctx.id), paid=12000, outstanding=0)

        paid_order = quote_upgrade(
            api,
            pass_ctx.id,
            program.tier_id("BRONZE"),
            program.tier_id("GOLD"),
            credit_mode=CreditMode.PAID_TO_DATE.value,
        )
        prorated_order = quote_upgrade(
            api,
            pass_ctx.id,
            program.tier_id("BRONZE"),
            program.tier_id("GOLD"),
            credit_mode=CreditMode.PRORATED_VALUE.value,
        )

        assert_upgrade_settlement(
            paid_order,
            gross=18000,
            raw_credit=12000,
            credit=12000,
            net=6000,
            admin_fee=1000,
            total_due=7000,
        )
        assert_upgrade_settlement(
            prorated_order,
            gross=18000,
            raw_credit=0,
            credit=0,
            net=18000,
            admin_fee=1000,
            total_due=19000,
        )

    def test_both_quotes_open_stamped_and_leave_the_pass_on_its_source_tier(
        self, api, default_clock
    ):
        """Two live quotes on one pass move nothing until one is applied.

        PRD: "A new order opens with `status` `QUOTED`, records the computed
        `gross_delta_cents`, `raw_credit_cents`, `credit_cents`, `net_delta_cents`,
        `admin_fee_cents` and `total_due_cents`, stamps `quoted_at` with the logical
        clock's current instant, sets `quote_expires_at` to fourteen days after
        `quoted_at`, and leaves `payment_amount_cents` and `reverse_reason` null."

        Design: Corner/calculations/upgrade_credit_prorated_variant_selected_with_no_park_days
        """
        program, pass_ctx = self._bronze_pass_in_a_programme_with_no_park_days(api)

        orders = [
            quote_upgrade(
                api,
                pass_ctx.id,
                program.tier_id("BRONZE"),
                program.tier_id("GOLD"),
                credit_mode=mode,
            )
            for mode in (CreditMode.PAID_TO_DATE.value, CreditMode.PRORATED_VALUE.value)
        ]

        for order in orders:
            assert order["status"] == UpgradeOrderStatus.QUOTED.value, (
                f"each new order should open QUOTED, got {order['status']!r}"
            )
            assert_instant_equals(order["quoted_at"], "2026-08-01T00:00:00Z", "quoted_at")
            assert_instant_equals(
                order["quote_expires_at"], "2026-08-15T00:00:00Z", "quote_expires_at"
            )
        assert get_pass(api, pass_ctx.id)["tier_id"] == program.tier_id("BRONZE"), (
            "quoting moves nothing: the pass should still sit on BRONZE"
        )


FEE_BAND_TIERS = (
    BRONZE,
    TierSpec(
        name="SILVER",
        tier_rank=2,
        base_price_cents=17000,
        in_park_discount_pct=0.10,
        peak_reservation_quota=3,
        parking_benefit="DISCOUNT",
    ),
    TierSpec(
        name="SILVER_PLUS",
        tier_rank=3,
        base_price_cents=17001,
        in_park_discount_pct=0.10,
        peak_reservation_quota=3,
        parking_benefit="DISCOUNT",
    ),
    TierSpec(
        name="GOLD",
        tier_rank=4,
        base_price_cents=32000,
        in_park_discount_pct=0.15,
        reservation_required_on_peak=False,
        peak_reservation_quota=5,
        parking_benefit="INCLUDED",
    ),
    TierSpec(
        name="GOLD_PLUS",
        tier_rank=5,
        base_price_cents=32001,
        in_park_discount_pct=0.15,
        reservation_required_on_peak=False,
        peak_reservation_quota=5,
        parking_benefit="INCLUDED",
    ),
)


class TestAdminFeeBandEdges:
    """Both band ceilings are inclusive upper bounds on the net delta."""

    def _unpaid_bronze_pass_with_no_park_days(self, api):
        program = build_program(
            api, tiers=FEE_BAND_TIERS, status=ProgramStatus.SALES_OPEN.value
        )
        pass_ctx = build_active_pass(
            api, program, tier_name="BRONZE", payment_mode=PaymentMode.PAYMENT_PLAN.value
        )
        return program, pass_ctx

    def _prorated_quote(self, api, program, pass_ctx, target_name):
        return quote_upgrade(
            api,
            pass_ctx.id,
            program.tier_id("BRONZE"),
            program.tier_id(target_name),
            credit_mode=CreditMode.PRORATED_VALUE.value,
        )

    def test_a_net_delta_of_exactly_5000_is_free_and_5001_costs_1000(self, api, default_clock):
        """The first band ceiling includes 5000, so one cent more crosses it.

        PRD: "When `net_delta_cents` is 5000 cents or less, the fee is 0."

        Design: Corner/calculations/upgrade_admin_fee_bands_tested_at_both_inclusive_boundaries
        """
        program, pass_ctx = self._unpaid_bronze_pass_with_no_park_days(api)
        assert_ledger(get_pass(api, pass_ctx.id), paid=0, outstanding=12000)

        at_edge = self._prorated_quote(api, program, pass_ctx, "SILVER")
        one_over = self._prorated_quote(api, program, pass_ctx, "SILVER_PLUS")

        assert_upgrade_settlement(
            at_edge, gross=5000, raw_credit=0, credit=0, net=5000, admin_fee=0, total_due=5000
        )
        assert_upgrade_settlement(
            one_over, gross=5001, raw_credit=0, credit=0, net=5001, admin_fee=1000, total_due=6001
        )

    def test_a_net_delta_of_exactly_20000_costs_1000_and_20001_costs_2500(
        self, api, default_clock
    ):
        """The second band ceiling includes 20000, so one cent more crosses it.

        PRD: "Otherwise, when `net_delta_cents` is 20000 cents or less, the fee is 1000
        cents."

        Design: Corner/calculations/upgrade_admin_fee_bands_tested_at_both_inclusive_boundaries
        """
        program, pass_ctx = self._unpaid_bronze_pass_with_no_park_days(api)

        at_edge = self._prorated_quote(api, program, pass_ctx, "GOLD")
        one_over = self._prorated_quote(api, program, pass_ctx, "GOLD_PLUS")

        assert_upgrade_settlement(
            at_edge, gross=20000, raw_credit=0, credit=0, net=20000, admin_fee=1000, total_due=21000
        )
        assert_upgrade_settlement(
            one_over,
            gross=20001,
            raw_credit=0,
            credit=0,
            net=20001,
            admin_fee=2500,
            total_due=22501,
        )
        for order in (at_edge, one_over):
            assert order["status"] == UpgradeOrderStatus.QUOTED.value, (
                f"each quote should open QUOTED, got {order['status']!r}"
            )


class TestUpgradeReversalConservesTheLedger:
    """Applying and then reversing an upgrade leaves no residue on the pass."""

    def test_reversal_returns_every_ledger_figure_to_its_pre_upgrade_value(self, api, default_clock):
        """The compensation is exact on all five ledger fields.

        PRD: "`billed_total_cents` falls by `gross_delta_cents` plus
        `admin_fee_cents`; `credited_amount_cents` falls by `credit_cents`;
        `paid_to_date_cents` falls by `payment_amount_cents`;
        `outstanding_balance_cents` is recomputed so that the §2.10 ledger identity
        still holds with no residue"

        Design: Difficulty/compensating_invariant/upgrade_apply_then_reverse_conserves_pass_ledger_identity
        """
        program, pass_ctx, _ = _bronze_pass_with_two_settled_installments(api)
        before = get_pass(api, pass_ctx.id)
        assert_ledger(before, billed=13500, paid=8250, credited=0, outstanding=5250, contract=12000)

        order = quote_upgrade(
            api,
            pass_ctx.id,
            program.tier_id("BRONZE"),
            program.tier_id("GOLD"),
            credit_mode=CreditMode.PAID_TO_DATE.value,
        )
        apply_upgrade(api, order["id"], 10750)
        applied = get_pass(api, pass_ctx.id)
        assert_ledger(applied, billed=32500, paid=19000, credited=8250, outstanding=5250, contract=30000)

        reverse_upgrade(
            api, order["id"], reason="Holder disputed the tier change", officer_user_id="officer-9"
        )

        after = get_pass(api, pass_ctx.id)
        assert_ledger(after, billed=13500, paid=8250, credited=0, outstanding=5250, contract=12000)

    def test_reversal_restores_the_tier_leaves_the_schedule_alone_and_cannot_repeat(
        self, api, default_clock
    ):
        """The order is terminal in REVERSED, so a second reversal is refused.

        PRD: "On success the order moves `APPLIED → REVERSED`, its terminal state, and
        every ledger effect is compensated exactly: the pass's `tier_id` returns to
        `source_tier_id` and `contract_value_cents` returns to the source tier's
        `base_price_cents`"

        Design: Difficulty/compensating_invariant/upgrade_apply_then_reverse_conserves_pass_ledger_identity
        """
        program, pass_ctx, plan_ctx = _bronze_pass_with_two_settled_installments(api)
        order = quote_upgrade(
            api,
            pass_ctx.id,
            program.tier_id("BRONZE"),
            program.tier_id("GOLD"),
            credit_mode=CreditMode.PAID_TO_DATE.value,
        )
        apply_upgrade(api, order["id"], 10750)

        reversed_order = reverse_upgrade(
            api, order["id"], reason="Holder disputed the tier change", officer_user_id="officer-9"
        )

        assert reversed_order["status"] == UpgradeOrderStatus.REVERSED.value, (
            f"the order should be REVERSED, got {reversed_order['status']!r}"
        )
        assert reversed_order["reverse_reason"] == "Holder disputed the tier change", (
            f"reverse_reason should record the officer's reason, got {reversed_order['reverse_reason']!r}"
        )
        pass_row = get_pass(api, pass_ctx.id)
        assert pass_row["tier_id"] == program.tier_id("BRONZE"), (
            "the pass should sit back on its source tier after the reversal"
        )
        assert_installment_statuses(
            plan_installments(api, plan_ctx.id), ["SETTLED", "SETTLED", "SCHEDULED", "SCHEDULED"]
        )

        second = api.reverse_upgrade_order(
            order["id"],
            reverse_upgrade_payload("Second attempt"),
            headers=compliance_officer_headers(),
        )
        validate_error(second, ApiErrorId.ERR_UPGRADE_ORDER_NOT_ACTIONABLE.value, 409)
