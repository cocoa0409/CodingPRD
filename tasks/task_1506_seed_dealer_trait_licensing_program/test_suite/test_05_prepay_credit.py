"""Money movement: prepay evaluation order, prepay ledger conservation, credit
limits, and prepay window rules (PRD §3.6, §2.9)."""
from test_helpers import (
    TEST_USERS,
    add_line,
    close_sales_at,
    confirm_order,
    create_draft_order,
    get_success_data,
    set_clock,
    settle_program_at,
    setup_market,
    validate_error,
    validate_success,
    ApiErrorId,
)

ADMIN = TEST_USERS["admin_headers"]
SALESREP = TEST_USERS["salesrep_headers"]

THREE_TIERS = [
    {"cutoff_at": "2026-09-30T23:59:59Z", "discount_bps": 1200},
    {"cutoff_at": "2026-11-15T23:59:59Z", "discount_bps": 1000},
    {"cutoff_at": "2027-01-15T23:59:59Z", "discount_bps": 600},
]
PREPAY_TIERS = [
    {"pay_by": "2026-12-20T23:59:59Z", "discount_bps": 800},
    {"pay_by": "2027-02-15T23:59:59Z", "discount_bps": 500},
]


def _prepay_market(api, **program_extras):
    overrides = {
        "early_order_tiers": THREE_TIERS,
        "prepay_tiers": PREPAY_TIERS,
        "volume_rebate_tiers": [{"min_units": 500, "rebate_bps": 500}],
        "daily_delivery_capacity_units": 1000,
    }
    overrides.update(program_extras)
    return setup_market(program_overrides=overrides,
                        lot_overrides={"received_units": 10000})


class TestPrepayEvaluationOrder:
    def test_prepay_discount_computed_on_pre_prepay_net(self, api):
        """PRD §3.6: "First, the net before prepay is the order's
        `gross_amount_cents` minus its `rebate_amount_cents`."
        PRD §3.6: "Third, the `prepay_discount_cents` is that rate applied to
        the pre-prepay net, rounded half-up to whole cents."

        Design: Difficulty/combinatorial_formula/prepay_discount_on_pre_prepay_balance_not_on_amount_tendered
        """
        ctx = _prepay_market(api)
        set_clock("2026-11-20T00:00:00Z")  # tier-3 window: 600bps
        order = create_draft_order(ctx["grower"], ctx["program"])
        add_line(order, ctx["variety"]["id"], 300)
        order = confirm_order(order["id"])
        # per unit: round_half_up(18000 x 0.94) = 16920 -> gross 5076000, rebate 0
        assert order["gross_amount_cents"] == 5076000

        set_clock("2026-12-01T00:00:00Z")  # inside the 800bps prepay window
        paid = validate_success(api.prepay_order(order["id"], 4669920, SALESREP))
        # 800bps on the PRE-prepay net 5076000, never on the amount tendered
        assert paid["prepay_discount_cents"] == 406080
        assert paid["net_amount_cents"] == 5076000 - 406080
        assert paid["payment_status"] == "PREPAID"

    def test_prepay_grows_grower_prepay_balance(self, api):
        """PRD §3.6: "the grower's `prepay_balance_cents` grows by that amount —
        any excess over the net due staying unapplied cash in the balance — and
        the payment dimension moves `UNPAID → PREPAID`."

        Design: Difficulty/combinatorial_formula/prepay_discount_on_pre_prepay_balance_not_on_amount_tendered
        """
        ctx = _prepay_market(api)
        set_clock("2026-11-20T00:00:00Z")
        order = create_draft_order(ctx["grower"], ctx["program"])
        add_line(order, ctx["variety"]["id"], 300)
        order = confirm_order(order["id"])

        set_clock("2026-12-01T00:00:00Z")
        paid = validate_success(api.prepay_order(order["id"], 4669920, SALESREP))
        assert paid["prepaid_amount_cents"] == 4669920

        grower = validate_success(api.get_grower(ctx["grower"]["id"], ADMIN))
        assert grower["prepay_balance_cents"] == 4669920


class TestPrepayLedgerConservation:
    def test_prepay_then_refund_restores_order_and_balance(self, api):
        """PRD §3.6: "The refund subtracts the order's `prepaid_amount_cents`
        from the grower's `prepay_balance_cents`, zeroes the order's
        `prepaid_amount_cents` and `prepay_discount_cents`, restores
        `net_amount_cents` to gross minus rebate, and returns the payment
        dimension `PREPAID → UNPAID`."

        Design: Difficulty/compensating_invariant/prepay_ledger_conserved_through_prepay_refund_reprepay_settle
        """
        ctx = _prepay_market(api)
        set_clock("2026-09-15T00:00:00Z")  # tier-1 window: 1200bps
        order = create_draft_order(ctx["grower"], ctx["program"])
        add_line(order, ctx["variety"]["id"], 40)
        order = confirm_order(order["id"])
        # per unit: round_half_up(18000 x 0.88) = 15840 -> gross 633600, rebate 0
        assert order["net_amount_cents"] == 633600

        set_clock("2026-12-01T00:00:00Z")
        net_due = 633600 - 50688  # 800bps on the pre-prepay net
        paid = validate_success(api.prepay_order(order["id"], net_due, SALESREP))
        assert paid["payment_status"] == "PREPAID"
        grower = validate_success(api.get_grower(ctx["grower"]["id"], ADMIN))
        assert grower["prepay_balance_cents"] == 582912

        get_success_data(api.refund_prepay(ctx["grower"]["id"], order["id"], ADMIN))
        grower = validate_success(api.get_grower(ctx["grower"]["id"], ADMIN))
        assert grower["prepay_balance_cents"] == 0
        order = validate_success(api.get_order(order["id"], SALESREP))
        assert order["payment_status"] == "UNPAID"
        assert order["prepaid_amount_cents"] == 0
        assert order["prepay_discount_cents"] == 0
        assert order["net_amount_cents"] == 633600

    def test_reprepay_then_settle_leaves_zero_balance(self, api):
        """PRD §2.9: "A grower's `prepay_balance_cents` always equals the sum of
        all prepay amounts collected, minus the sum of all refunded prepay
        amounts, minus the sum of all prepay applications performed when prepaid
        orders settle."
        PRD §3.9: "each closed order that was `PREPAID` applies its prepayment,
        subtracting `net_amount_cents` from the grower's `prepay_balance_cents`
        and moving its payment dimension to `SETTLED`".

        Design: Difficulty/compensating_invariant/prepay_ledger_conserved_through_prepay_refund_reprepay_settle
        """
        ctx = _prepay_market(api)
        set_clock("2026-09-15T00:00:00Z")
        order = create_draft_order(ctx["grower"], ctx["program"])
        add_line(order, ctx["variety"]["id"], 40)
        order = confirm_order(order["id"])

        set_clock("2026-12-01T00:00:00Z")
        net_due = 582912
        get_success_data(api.prepay_order(order["id"], net_due, SALESREP))
        get_success_data(api.refund_prepay(ctx["grower"]["id"], order["id"], ADMIN))
        repaid = validate_success(api.prepay_order(order["id"], net_due, SALESREP))
        assert repaid["payment_status"] == "PREPAID"
        grower = validate_success(api.get_grower(ctx["grower"]["id"], ADMIN))
        assert grower["prepay_balance_cents"] == 582912

        close_sales_at(ctx["program"]["id"])
        settle_program_at(ctx["program"]["id"])
        grower = validate_success(api.get_grower(ctx["grower"]["id"], ADMIN))
        # 582912 + 582912 (prepay, re-prepay) - 582912 (refund) - 582912 (settle)
        assert grower["prepay_balance_cents"] == 0
        order = validate_success(api.get_order(order["id"], SALESREP))
        assert order["status"] == "CLOSED"
        assert order["payment_status"] == "SETTLED"


class TestPrepayGuards:
    def test_prepay_one_cent_short_rejected(self, api):
        """PRD §3.6: "Fifth, the supplied `amount_cents` must be at least the
        net due, otherwise `ERR_PREPAY_AMOUNT_INSUFFICIENT`."

        Design: Corner/validations/prepay_one_cent_short_rejected
        """
        ctx = _prepay_market(api)
        set_clock("2026-11-20T00:00:00Z")
        order = create_draft_order(ctx["grower"], ctx["program"])
        add_line(order, ctx["variety"]["id"], 300)
        order = confirm_order(order["id"])

        set_clock("2026-12-01T00:00:00Z")
        resp = api.prepay_order(order["id"], 4669919, SALESREP)
        validate_error(resp, ApiErrorId.ERR_PREPAY_AMOUNT_INSUFFICIENT)

        paid = validate_success(api.prepay_order(order["id"], 4669920, SALESREP))
        assert paid["payment_status"] == "PREPAID"

    def test_prepay_after_last_window_rejected(self, api):
        """PRD §3.6: "the system selects the prepay tier with the largest
        `discount_bps` among tiers whose `pay_by` is at or after the logical
        clock; if no such tier remains, the request fails with
        `ERR_PREPAY_WINDOW_CLOSED`."

        Design: Corner/validations/prepay_after_last_window_rejected
        """
        ctx = setup_market(
            program_overrides={
                "prepay_tiers": [{"pay_by": "2027-02-15T23:59:59Z", "discount_bps": 500}]
            }
        )
        set_clock("2027-01-10T00:00:00Z")
        order = create_draft_order(ctx["grower"], ctx["program"])
        add_line(order, ctx["variety"]["id"], 10)
        order = confirm_order(order["id"])

        set_clock("2027-02-16T00:00:00Z")
        resp = api.prepay_order(order["id"], 169200, SALESREP)
        validate_error(resp, ApiErrorId.ERR_PREPAY_WINDOW_CLOSED)
        order_after = validate_success(api.get_order(order["id"], SALESREP))
        assert order_after["payment_status"] == "UNPAID"

    def test_prepay_second_window_tier_selected(self, api):
        """PRD §3.6: "the system selects the prepay tier with the largest
        `discount_bps` among tiers whose `pay_by` is at or after the logical
        clock".

        Design: Corner/calculations/prepay_second_window_tier_selected
        """
        ctx = setup_market(
            program_overrides={
                "prepay_tiers": [
                    {"pay_by": "2026-12-20T23:59:59Z", "discount_bps": 800},
                    {"pay_by": "2027-02-15T23:59:59Z", "discount_bps": 500},
                ]
            },
            lot_overrides={"received_units": 10000},
        )
        set_clock("2026-12-01T00:00:00Z")
        order = create_draft_order(ctx["grower"], ctx["program"])
        add_line(order, ctx["variety"]["id"], 100)
        order = confirm_order(order["id"])
        # 600bps tier (cutoff 2027-01-15 >= clock): per unit 16920, net 1692000
        assert order["net_amount_cents"] == 1692000

        set_clock("2026-12-21T00:00:00Z")  # first window expired; 500bps remains
        paid = validate_success(api.prepay_order(order["id"], 1607400, SALESREP))
        assert paid["prepay_discount_cents"] == 84600
        assert paid["net_amount_cents"] == 1607400
        assert paid["payment_status"] == "PREPAID"


class TestCreditLimit:
    def test_confirm_exceeding_credit_limit_rejected(self, api):
        """PRD §3.5: "the grower's `outstanding_balance_cents` plus the order's
        net amount — gross less the volume rebate — must not exceed
        `credit_limit_cents` (`ERR_CREDIT_LIMIT_EXCEEDED`)."

        Design: Corner/validations/confirm_exceeding_credit_limit_rejected
        """
        ctx = setup_market(grower_overrides={"credit_limit_cents": 1000000})
        set_clock("2027-01-10T00:00:00Z")
        order = create_draft_order(ctx["grower"], ctx["program"])
        add_line(order, ctx["variety"]["id"], 100)
        # projected net 100 x 16920 = 1692000 > 1000000 limit
        resp = api.confirm_order(order["id"], SALESREP)
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)

        order_after = validate_success(api.get_order(order["id"], SALESREP))
        assert order_after["status"] == "DRAFT"
        lot = validate_success(api.get_inventory_lot(ctx["lot"]["id"], ADMIN))
        assert lot["reserved_units"] == 0, "rejected confirm must not reserve inventory"
