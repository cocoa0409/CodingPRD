"""Billing cycles: half-open period overlap, preview-vs-close variant
divergence, surcharge actuals, discount tier evaluated on gross, close /
settle / dispute segregation of duties, and charge-preview state gating."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_merchant,
    create_order,
    create_published_plan,
    create_return_item_line,
    fulfill_order_to_refund_posted,
    make_platform_admin_headers,
    setup_commercial_spine,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ADMIN_1 = make_platform_admin_headers("admin-1")
ADMIN_2 = make_platform_admin_headers("admin-2")


class TestCycleWindows:

    def test_billing_period_half_open_adjacency(self, api):
        """PRD §3.2: "The new window must not overlap any non-terminal cycle
        of the same merchant under half-open interval arithmetic — two windows
        overlap when each starts before the other ends — and a violation is
        rejected with `ERR_BILLING_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/billing_period_half_open_adjacency
        """
        plan = create_published_plan()
        merchant = create_merchant(plan["id"], legal_name="M-Per")

        first = api.create_billing_cycle(
            merchant["id"],
            {"period_start": "2026-04-01T00:00:00Z",
             "period_end": "2026-06-01T00:00:00Z"},
            ADMIN,
        )
        validate_success(first, expected_status=201)

        # Adjacent: starts exactly at the first cycle's period_end — allowed
        # under half-open arithmetic.
        adjacent = api.create_billing_cycle(
            merchant["id"],
            {"period_start": "2026-06-01T00:00:00Z",
             "period_end": "2026-08-01T00:00:00Z"},
            ADMIN,
        )
        validate_success(adjacent, expected_status=201)

        # A one-month-and-a-half window overlaps both existing cycles.
        overlapping = api.create_billing_cycle(
            merchant["id"],
            {"period_start": "2026-05-15T00:00:00Z",
             "period_end": "2026-07-01T00:00:00Z"},
            ADMIN,
        )
        validate_error(overlapping, ApiErrorId.ERR_BILLING_PERIOD_OVERLAP)


class TestChargeVariants:

    def test_billing_preview_vs_close_inflight_divergence(self, api):
        """PRD §3.2: "A **provisional preview**, available to a
        `PlatformAdmin` or the merchant's own `MerchantAdmin` while the cycle
        is `OPEN`, is forward-looking: it counts both fulfilled and in-flight
        orders toward overage. A **final close** counts fulfilled orders only,
        so identical data with any in-flight orders yields a different total
        between the two variants."

        Design: Difficulty/dual_variant_calc/billing_preview_vs_close_inflight_divergence
        """
        spine = setup_commercial_spine(
            plan_overrides={
                "monthly_fee_cents": 100000, "included_returns": 2,
                "overage_fee_cents": 50000, "free_returns": False,
            },
            shopper_email="sb@x.com", with_zone=True,
        )
        cycle = spine["cycle"]

        for sku in ("B1", "B2", "B3"):
            fulfill_order_to_refund_posted(
                spine, items=[create_return_item_line(sku=sku,
                                                      unit_price_cents=1000)]
            )
        # Fourth order stays INITIATED (in-flight).
        create_order(spine, method="HOME_PICKUP", boxless=True,
                     items=[create_return_item_line(sku="B4",
                                                    unit_price_cents=1000)])

        preview = validate_success(api.get_charge_preview(cycle["id"], ADMIN))
        # PRD §3.2 lists `variant` among the exposed preview fields but never
        # pins its string value, so only presence is asserted.
        assert "variant" in preview
        # counted = 3 fulfilled + 1 in-flight = 4 -> overage 2 -> fee 100000
        # -> gross 200000 -> 5% discount 10000 -> total 190000.
        assert preview["overage_count"] == 2
        assert preview["total_cents"] == 190000

        closed = validate_success(api.close_billing_cycle(cycle["id"], ADMIN))
        # counted = 3 fulfilled -> overage 1 -> fee 50000 -> gross 150000 ->
        # no discount -> total 150000.
        assert closed["overage_count"] == 1
        assert closed["gross_cents"] == 150000
        assert closed["total_cents"] == 150000
        assert closed["status"] == "CLOSING"

    def test_billing_discount_tier_evaluated_on_gross_pinned(self, api):
        """PRD §3.2: "The volume discount is tiered on the gross: a gross of
        at least 500,000 cents earns ten percent, a gross of at least 200,000
        cents but less than 500,000 earns five percent, and anything below
        earns nothing; `discount_cents` is the gross multiplied by the
        applicable percentage, rounded half-up to integer cents. The invoice
        total `total_cents` is the gross minus the discount."

        Design: Difficulty/combinatorial_formula/billing_discount_tier_evaluated_on_gross_pinned
        """
        # included_returns must be >= 2 so the §3.3 overage hard cap
        # (2x inclusion) admits three orders; gross stays pinned at 200000.
        spine = setup_commercial_spine(
            plan_overrides={
                "monthly_fee_cents": 175000, "included_returns": 2,
                "overage_fee_cents": 25000, "free_returns": False,
            },
            shopper_email="sd@x.com", with_zone=True,
        )
        for sku in ("D1", "D2", "D3"):
            fulfill_order_to_refund_posted(
                spine, items=[create_return_item_line(sku=sku,
                                                      unit_price_cents=500)]
            )
        closed = validate_success(
            api.close_billing_cycle(spine["cycle"]["id"], ADMIN)
        )
        # gross = 175000 + 1*25000 = 200000 -> tier 5% -> discount 10000.
        assert closed["gross_cents"] == 200000
        assert closed["discount_cents"] == 10000
        assert closed["total_cents"] == 190000

    def test_billing_surcharges_use_actuals_in_both_variants(self, api):
        """PRD §3.2: "The surcharge component `surcharge_cents` always uses
        actual fulfilled orders in both variants: for each fulfilled order,
        the plan's `oversize_surcharge_cents` is added when the order
        `has_oversize_item`, and the plan's `pickup_fee_cents` is added when
        the order's `method` is `HOME_PICKUP`."

        Design: Corner/calculations/billing_surcharges_use_actuals_in_both_variants
        """
        spine = setup_commercial_spine(
            plan_overrides={
                "monthly_fee_cents": 1000, "included_returns": 10,
                "overage_fee_cents": 10, "oversize_surcharge_cents": 1500,
                "pickup_fee_cents": 700, "free_returns": False,
            },
            shopper_email="ssu@x.com", with_zone=True,
        )
        cycle = spine["cycle"]
        # One fulfilled HOME_PICKUP order carrying an oversize item (200 cm).
        fulfill_order_to_refund_posted(
            spine,
            items=[create_return_item_line(sku="SU", unit_price_cents=9000,
                                           longest_side_cm=200,
                                           weight_grams=9000)],
        )

        preview = validate_success(api.get_charge_preview(cycle["id"], ADMIN))
        # surcharge = 1500 (oversize) + 700 (pickup) = 2200.
        assert preview["surcharge_cents"] == 2200
        assert preview["gross_cents"] == 3200
        assert preview["total_cents"] == 3200

        closed = validate_success(api.close_billing_cycle(cycle["id"], ADMIN))
        assert closed["surcharge_cents"] == 2200
        assert closed["total_cents"] == 3200


class TestPreviewStateGate:

    def test_charge_preview_on_closing_cycle_rejected(self, api):
        """PRD §3.2: "A **provisional preview**, available to a
        `PlatformAdmin` or the merchant's own `MerchantAdmin` while the cycle
        is `OPEN`".
        PRD §2.8: "the target resource is in a valid from-state for the
        requested transition and terminal resources reject everything, else
        `ERR_INVALID_STATE` or `ERR_ALREADY_TERMINAL`."

        Design: Corner/endpoints/charge_preview_on_closing_cycle_rejected
        """
        spine = setup_commercial_spine(shopper_email="scp@x.com")
        cycle = spine["cycle"]
        validate_success(api.close_billing_cycle(cycle["id"], ADMIN))
        resp = api.get_charge_preview(cycle["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestSettlementSoD:

    def test_segregation_of_duties_billing_settler(self, api):
        """PRD §3.2: "Settling moves the cycle from `CLOSING` to the terminal
        `SETTLED` and must be performed by a *different* `PlatformAdmin` than
        the one who closed it — a settler whose identity equals
        `closed_by_user_id` is refused with `ERR_SOD_SETTLER_EQUALS_CLOSER`.
        Settlement records `settled_by_user_id` and adds the cycle's
        `total_cents` to the merchant's `ledger_balance_cents`."

        Design: Corner/roles/segregation_of_duties_billing_settler
        """
        spine = setup_commercial_spine(
            plan_overrides={"monthly_fee_cents": 1000},
            shopper_email="ssb@x.com",
        )
        cycle = spine["cycle"]
        validate_success(api.close_billing_cycle(cycle["id"], ADMIN_1))

        blocked = api.settle_billing_cycle(cycle["id"], ADMIN_1)
        validate_error(blocked, ApiErrorId.ERR_SOD_SETTLER_EQUALS_CLOSER)

        settled = validate_success(api.settle_billing_cycle(cycle["id"], ADMIN_2))
        assert settled["status"] == "SETTLED"

        merchant = validate_success(
            api.get_merchant_account(spine["merchant"]["id"], ADMIN)
        )
        assert merchant["ledger_balance_cents"] == 1000
