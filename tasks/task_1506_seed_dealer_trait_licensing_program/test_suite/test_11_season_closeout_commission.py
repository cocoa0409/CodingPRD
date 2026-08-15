"""Season closeout: the close_sales and settle sweeps, settlement gates, grower
deactivation gates, and the commission statement's provisional/final variants."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_line,
    assert_commission_statement,
    close_sales_at,
    confirm_order,
    create_draft_order,
    create_grower,
    create_open_program,
    create_published_recommendation,
    create_signed_agreement,
    create_trait_package,
    get_program_commission_statement,
    schedule_delivery,
    set_clock,
    settle_program_at,
    setup_confirmed_order,
    setup_market,
    setup_commission_dual_variant_scenario,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
SALESREP = TEST_USERS["salesrep_headers"]


class TestCommissionDualVariant:
    def test_provisional_variant_counts_replacement_units(self, api):
        """PRD §3.9: "`volume_units` counts the included orders' `total_units`
        minus the units of `CREDITED` returns on them; the provisional variant —
        used while the program is `OPEN` or `SALES_CLOSED` — lets
        replacement-order units count toward the tally, while the final variant,
        computed at settlement, excludes replacement-order units entirely."

        Design: Difficulty/dual_variant_calc/commission_provisional_counts_replacement_units_final_excludes
        """
        ctx = setup_commission_dual_variant_scenario()
        provisional = validate_success(
            api.recompute_commission_statement(ctx["statement"]["id"], ADMIN)
        )
        assert_commission_statement(provisional)
        # 900 paid units + 360 replacement units = 1260 >= 1000 -> tier earned
        assert provisional["volume_units"] == 1260
        assert provisional["net_sales_cents"] == 16200000
        assert provisional["base_commission_cents"] == 810000
        assert provisional["volume_bonus_bps"] == 100
        assert provisional["total_commission_cents"] == 972000

    def test_final_variant_excludes_replacement_units(self, api):
        """PRD §3.9: "the final variant, computed at settlement, excludes
        replacement-order units entirely."
        PRD §3.9: "the bonus falls away even though net sales never moved."

        Design: Difficulty/dual_variant_calc/commission_provisional_counts_replacement_units_final_excludes
        """
        ctx = setup_commission_dual_variant_scenario()
        provisional = validate_success(
            api.recompute_commission_statement(ctx["statement"]["id"], ADMIN)
        )
        close_sales_at(ctx["program"]["id"])
        settle_program_at(ctx["program"]["id"])

        final = validate_success(
            api.get_commission_statement(ctx["statement"]["id"], ADMIN)
        )
        assert final["status"] == "FINALIZED"
        assert final["volume_units"] == 900, (
            "replacement-order units are excluded from the final tally"
        )
        assert final["net_sales_cents"] == 16200000
        assert final["volume_bonus_bps"] == 0
        assert final["total_commission_cents"] == 810000
        assert provisional["total_commission_cents"] != final["total_commission_cents"], (
            "the variant switch alone moved the commission"
        )


class TestCommissionVolumeBoundary:
    def _two_order_scenario(self, api, second_units):
        """Program (base 500bps; commission volume tier 1000 -> 100bps) with a
        600-unit and a `second_units`-unit order, both confirmed past the
        early-order cutoffs."""
        ctx = setup_market(
            program_overrides={
                "early_order_tiers": [
                    {"cutoff_at": "2027-01-15T23:59:59Z", "discount_bps": 600}
                ],
                "commission_volume_tiers": [{"min_net_units": 1000, "bonus_bps": 100}],
            },
            lot_overrides={"received_units": 50000},
        )
        set_clock("2027-02-01T00:00:00Z")
        for units in (600, second_units):
            order = create_draft_order(ctx["grower"], ctx["program"])
            add_line(order, ctx["variety"]["id"], units)
            confirm_order(order["id"])
        ctx["statement"] = get_program_commission_statement(ctx["program"]["id"])
        return ctx

    def test_volume_bonus_at_exactly_min_net_units(self, api):
        """PRD §3.9: "`volume_bonus_bps` is the largest `bonus_bps` among
        commission volume tiers whose `min_net_units` the statement's
        `volume_units` meets or exceeds (zero when none qualify)".

        Design: Difficulty/boundary_precision_check/commission_volume_tier_exactly_at_min_units
        """
        ctx = self._two_order_scenario(api, 400)
        stmt = validate_success(
            api.recompute_commission_statement(ctx["statement"]["id"], ADMIN)
        )
        assert stmt["volume_units"] == 1000
        assert stmt["volume_bonus_bps"] == 100, "meets-or-exceeds is inclusive"
        # net sales 18000000; base 500bps -> 900000; bonus 100bps -> 180000
        assert stmt["base_commission_cents"] == 900000
        assert stmt["volume_bonus_cents"] == 180000
        assert stmt["total_commission_cents"] == 1080000

    def test_volume_bonus_one_unit_below_min_net_units(self, api):
        """PRD §3.9: "`volume_bonus_bps` is the largest `bonus_bps` among
        commission volume tiers whose `min_net_units` the statement's
        `volume_units` meets or exceeds (zero when none qualify)".

        Design: Difficulty/boundary_precision_check/commission_volume_tier_exactly_at_min_units
        """
        ctx = self._two_order_scenario(api, 399)
        stmt = validate_success(
            api.recompute_commission_statement(ctx["statement"]["id"], ADMIN)
        )
        assert stmt["volume_units"] == 999
        assert stmt["volume_bonus_bps"] == 0
        # net sales 17982000; base 500bps -> 899100
        assert stmt["total_commission_cents"] == 899100


class TestCloseSalesSweep:
    def test_close_sales_cancels_drafts_and_expires_recommendations(self, api):
        """PRD §3.9: "The transition `OPEN → SALES_CLOSED` stamps
        `sales_closed_at` and runs a four-part sweep: every order of the program
        still in `DRAFT` moves to `CANCELLED` (no reservations ever existed on
        drafts)" and "every recommendation of the program in `DRAFT` or
        `PUBLISHED` moves to `EXPIRED`".

        Design: Corner/state_machines/close_sales_cancels_drafts_and_expires_recommendations
        """
        ctx = setup_market(with_lot=False, with_field=True)
        rec = create_published_recommendation(ctx["program"], ctx["field"],
                                              ctx["variety"])
        assert rec["status"] == "PUBLISHED"
        order = create_draft_order(ctx["grower"], ctx["program"])

        program = close_sales_at(ctx["program"]["id"])
        assert program["status"] == "SALES_CLOSED"

        order_after = validate_success(api.get_order(order["id"], SALESREP))
        assert order_after["status"] == "CANCELLED"
        rec_after = validate_success(api.get_recommendation(rec["id"], ADMIN))
        assert rec_after["status"] == "EXPIRED"

    def test_agreement_past_window_expired_by_close_sales_sweep(self, api):
        """PRD §3.9: "every trait agreement whose `effective_to` has fallen
        behind the clock, whether `ACTIVE` or `SUSPENDED`, moves to `EXPIRED`."

        Design: Corner/state_machines/agreement_past_window_expired_by_close_sales_sweep
        """
        program = create_open_program()
        grower = create_grower()
        package = create_trait_package()
        agreement = create_signed_agreement(
            grower, package["id"], effective_to="2027-01-31T23:59:59Z"
        )
        assert agreement["status"] == "ACTIVE"

        close_sales_at(program["id"], clock="2027-03-20T00:00:00Z")
        agreement_after = validate_success(
            api.get_trait_agreement(agreement["id"], ADMIN)
        )
        assert agreement_after["status"] == "EXPIRED"


class TestSettleGate:
    def test_settle_blocked_while_scheduled_ticket_exists(self, api):
        """PRD §3.9: "Four preconditions guard it, all surfacing
        `ERR_PROGRAM_NOT_SETTLABLE`: the logical clock must be strictly later
        than `return_window_end`; no order of the program may sit in
        `COMPLIANCE_HOLD`; no replant claim on the program's orders may sit in
        `FILED`, `UNDER_REVIEW`, or `INFO_REQUESTED`; and no delivery ticket on
        the program's orders may remain `SCHEDULED`."

        Design: Corner/state_machines/settle_blocked_while_scheduled_ticket_exists
        """
        ctx = setup_confirmed_order(units=10)
        schedule_delivery(ctx["order"], ctx["line"], 10,
                          scheduled_date="2027-05-01T00:00:00Z")
        close_sales_at(ctx["program"]["id"])

        set_clock("2027-07-15T00:00:00Z")
        resp = api.settle_program(ctx["program"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_SETTLABLE)
        program = validate_success(api.get_program(ctx["program"]["id"], ADMIN))
        assert program["status"] == "SALES_CLOSED"


class TestGrowerDeactivationGates:
    def test_grower_deactivate_blocked_by_open_orders_then_by_unsettled_balance(self, api):
        """PRD §3.2: "Deactivation is the terminal exit `ACTIVE → INACTIVE` and
        carries two gates evaluated under the adjudication order: no order of
        the grower may be in `DRAFT`, `CONFIRMED`, or `COMPLIANCE_HOLD`
        (otherwise `ERR_GROWER_HAS_OPEN_ORDERS`), and both balances must be
        exactly zero — `outstanding_balance_cents` and `prepay_balance_cents`
        alike — otherwise `ERR_GROWER_NOT_SETTLED`."

        Design: Corner/validations/grower_deactivate_blocked_by_open_orders_then_by_unsettled_balance
        """
        ctx = setup_confirmed_order(units=10)
        resp = api.deactivate_grower(ctx["grower"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_GROWER_HAS_OPEN_ORDERS)

        close_sales_at(ctx["program"]["id"])
        settle_program_at(ctx["program"]["id"])
        # The sweep invoiced the order: the grower's outstanding balance now
        # holds the order's net and is non-zero.
        resp = api.deactivate_grower(ctx["grower"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_GROWER_NOT_SETTLED)
