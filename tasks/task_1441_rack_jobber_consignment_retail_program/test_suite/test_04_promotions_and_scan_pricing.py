"""Promotion windows and the minimum-gap rule; scan price resolution against
directives and promotions, including the pinned per-line funding rounding."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_promotion_payload,
    get_success_data,
    new_product,
    new_program,
    new_promotion,
    new_statement,
    post_matched_sale,
    schedule_promotion,
    set_clock,
    setup_shop,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["jobber_admin_headers"]


class TestPromoGapBuffer:
    def test_one_day_separation_rejected(self, api):
        """PRD section 3.3: "With the default one-day gap and an existing
        promotion ending on 2026-08-10, a candidate starting 2026-08-11 is
        rejected — one day of separation does not exceed the required one full
        day — while a start of 2026-08-12 is accepted."

        Design: Difficulty/resource_temporal_overlap/promotion_gap_buffer_semantics
        """
        set_clock()
        program = new_program(name="GapCo")
        product = new_product(program["id"], sku="COF-001", name="Cold Brew")
        x1 = new_promotion(program["id"], product["id"], name="Early August",
                           depth_pct=0.10, start_date="2026-08-01",
                           end_date="2026-08-10")
        assert x1["status"] == "DRAFT"
        res = api.create_promotion(
            create_promotion_payload(program["id"], product["id"],
                                     name="Too Soon", depth_pct=0.15,
                                     start_date="2026-08-11",
                                     end_date="2026-08-15"),
            ADMIN)
        validate_error(res, ApiErrorId.ERR_PROMO_GAP_VIOLATION)

    def test_full_gap_day_accepted(self, api):
        """PRD section 3.3: "With the default one-day gap and an existing
        promotion ending on 2026-08-10, a candidate starting 2026-08-11 is
        rejected — one day of separation does not exceed the required one full
        day — while a start of 2026-08-12 is accepted."
        PRD section 3.3: "Creation also enforces gap discipline, and this check
        is deliberately stricter than the space-allocation overlap rule of
        §3.4."

        Design: Difficulty/resource_temporal_overlap/promotion_gap_buffer_semantics
        """
        set_clock()
        program = new_program(name="GapCo")
        product = new_product(program["id"], sku="COF-001", name="Cold Brew")
        new_promotion(program["id"], product["id"], name="Early August",
                      depth_pct=0.10, start_date="2026-08-01",
                      end_date="2026-08-10")
        x3 = validate_success(api.create_promotion(
            create_promotion_payload(program["id"], product["id"],
                                     name="Gap OK", depth_pct=0.15,
                                     start_date="2026-08-12",
                                     end_date="2026-08-15"),
            ADMIN), 201)
        assert x3["status"] == "DRAFT", (
            "the gap check runs at create, independent of scheduling")


class TestPromoLifecycle:
    def test_cancel_after_end_rejected(self, api):
        """PRD section 3.3: "Ending by a `JobberAdmin` moves `ACTIVE` or
        `SUSPENDED` to `ENDED`, and cancellation moves any of `DRAFT`,
        `SCHEDULED`, `ACTIVE`, or `SUSPENDED` to `CANCELLED`. Both `ENDED` and
        `CANCELLED` are terminal."
        PRD section 2.8: "From-state validity: the target resource must be in a
        state from which the requested transition exists, failing with
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/promo_cancel_after_end_rejected
        """
        set_clock()
        program = new_program(name="PromoTerm")
        product = new_product(program["id"], sku="PT-1", name="Promo Item")
        promo = new_promotion(program["id"], product["id"], name="Flash",
                              start_date="2026-08-01", end_date="2026-08-05")
        scheduled = schedule_promotion(promo["id"])
        assert scheduled["status"] == "ACTIVE", (
            "the window covers the clock date, so scheduling lands ACTIVE")
        ended = validate_success(api.end_promotion(promo["id"], ADMIN), 200)
        assert ended["status"] == "ENDED"
        res = api.cancel_promotion(promo["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api.get_promotion(promo["id"], ADMIN))
        assert after["status"] == "ENDED"

    def test_promo_auto_lifecycle_on_clock_sweep(self, api):
        """PRD section 2.6: "A scheduled promotion whose window now covers the
        clock date becomes `ACTIVE`, and an active or suspended promotion whose
        `end_date` has passed becomes `ENDED`."

        Design: Corner/state_machines/promo_auto_lifecycle_on_clock_sweep
        """
        set_clock()
        program = new_program(name="AutoPromo")
        product = new_product(program["id"], sku="AP-1", name="Auto Item")
        promo = new_promotion(program["id"], product["id"], name="Auto",
                              start_date="2026-08-03", end_date="2026-08-05")
        scheduled = schedule_promotion(promo["id"])
        assert scheduled["status"] == "SCHEDULED", "window not yet open"
        set_clock("2026-08-03T00:00:00Z")
        mid = get_success_data(api.get_promotion(promo["id"], ADMIN))
        assert mid["status"] == "ACTIVE", "sweep entered the window"
        set_clock("2026-08-06T00:00:00Z")
        after = get_success_data(api.get_promotion(promo["id"], ADMIN))
        assert after["status"] == "ENDED", "sweep passed end_date"


class TestScanPricing:
    def test_promo_min_price_applied(self, api):
        """PRD section 3.6: "When a promotion applies, the promo price is the
        base price multiplied by one minus `depth_pct`, rounded half-up to a
        whole cent, and the scan's `unit_price_cents` is the lesser of the base
        price and that promo price; `is_promo_priced` is true exactly when the
        resolved unit price lands below the base."

        Design: Corner/calculations/scan_pricing_promo_min_applied
        """
        ctx = setup_shop(product_overrides={"min_retail_cents": 100})
        promo = new_promotion(ctx["program"]["id"], ctx["product"]["id"],
                              name="Quarter", depth_pct=0.25,
                              start_date="2026-08-01", end_date="2026-08-05")
        schedule_promotion(promo["id"])
        scan = post_matched_sale(
            ctx["agreement"]["id"], ctx["product"]["id"], ctx["store"]["id"],
            quantity=2, scanned_at="2026-08-02T09:00:00Z",
            client_event_id="mp-1")
        assert scan["unit_price_cents"] == 150, (
            "min(200, round_half_up(200 * 0.75))")
        assert scan["line_value_cents"] == 300
        assert scan["is_promo_priced"] is True

    def test_directive_price_when_no_promo(self, api):
        """PRD section 3.6: "With no promotion, the unit price is simply the
        base price and `is_promo_priced` is false."

        Design: Corner/calculations/scan_pricing_directive_when_no_promo
        """
        ctx = setup_shop()
        scan = post_matched_sale(
            ctx["agreement"]["id"], ctx["product"]["id"], ctx["store"]["id"],
            quantity=3, scanned_at="2026-08-01T09:00:00Z",
            client_event_id="np-1")
        assert scan["unit_price_cents"] == 200
        assert scan["is_promo_priced"] is False
        assert scan["line_value_cents"] == 600


class TestPromoFundingRounding:
    def _funding_scenario(self, api):
        ctx = setup_shop(product_overrides={"jobber_cost_cents": 60,
                                            "min_retail_cents": 100},
                         price_cents=101)
        promo = new_promotion(ctx["program"]["id"], ctx["product"]["id"],
                              name="Quarter Off", depth_pct=0.25,
                              jobber_funding_pct=0.5,
                              start_date="2026-08-01", end_date="2026-08-05")
        schedule_promotion(promo["id"])
        return ctx

    def test_per_line_rounding_half_up(self, api):
        """PRD section 3.6: "For each promo-priced line, the per-unit discount
        is the directive price minus the resolved unit price; the line's
        `jobber_funding_cents` is that per-unit discount multiplied by the line
        `quantity` and by the promotion's `jobber_funding_pct`, rounded half-up
        to a whole cent."

        Design: Difficulty/combinatorial_formula/promo_funding_per_line_then_sum_rounding
        """
        ctx = self._funding_scenario(api)
        for event_id in ("s-a", "s-b"):
            scan = post_matched_sale(
                ctx["agreement"]["id"], ctx["product"]["id"],
                ctx["store"]["id"], quantity=1,
                scanned_at="2026-08-02T09:00:00Z", client_event_id=event_id)
            assert scan["unit_price_cents"] == 76, (
                "round_half_up(101 * 0.75) = 76")
            assert scan["jobber_funding_cents"] == 13, (
                "round_half_up(25 * 1 * 0.5) rounds 12.5 up to 13")

    def test_statement_sums_rounded_lines(self, api):
        """PRD section 3.6: "Settlement totals sum these already-rounded line
        figures. Summing raw discounts first and rounding once at the end is
        forbidden, because the orders genuinely diverge: at a directive price
        of 101 cents with depth 0.25 and half jobber funding, two quantity-1
        lines fund 13 plus 13 — 26 cents — under the pinned order, where
        sum-then-round would yield 25."

        Design: Difficulty/combinatorial_formula/promo_funding_per_line_then_sum_rounding
        """
        ctx = self._funding_scenario(api)
        for event_id in ("s-a", "s-b"):
            post_matched_sale(
                ctx["agreement"]["id"], ctx["product"]["id"],
                ctx["store"]["id"], quantity=1,
                scanned_at="2026-08-02T09:00:00Z", client_event_id=event_id)
        statement = new_statement(ctx["agreement"]["id"], period_index=0)
        assert statement["promo_jobber_funding_cents"] == 26, (
            "13 + 13 = 26; the forbidden sum-then-round order yields 25")
        assert statement["gross_scanned_sales_cents"] == 152
