"""Winterization quote composition and servicer volume rebate settlement."""
from test_helpers import validate_success
from test_helpers.factories import create_work_order_payload
from test_helpers.fixtures import (
    add_expense_line,
    run_daily_sweep,
    set_clock,
    setup_completed_order_with_invoice,
    setup_portfolio,
)
from test_helpers.test_users import TEST_USERS, make_servicer_headers

ADMIN = TEST_USERS["vendor_admin_headers"]


def _quote_property(clock, **property_overrides):
    return setup_portfolio(item_code="WINTERIZATION",
                           allowable_overrides={
                               "max_per_occurrence_cents": 999999,
                               "max_occurrences_per_calendar_year": 5,
                               "aggregate_cap_cents_per_property_year": 9999999,
                               "requires_bid_over_cents": 99999999},
                           property_overrides=property_overrides,
                           crew_overrides=None, clock=clock, with_crew=False)


class TestWinterizationQuote:
    def test_winterization_quote_heating_season(self, api):
        """PRD: "The quote begins with a base of 15,000 cents plus 1,200 cents for
        each plumbing fixture recorded in the property's `fixture_count`, adding a
        further 9,000 cents when the property's `has_pool` flag is true. The base is
        scaled by a heating-system multiplier: 1.00 for `NONE`, 1.00 for
        `FORCED_AIR`, 1.5 for `HOT_WATER`, and 1.75 for `STEAM`. A seasonal
        multiplier of 1.2 applies whenever the logical clock's month falls in
        October through March inclusive" and "The estimate is the base times the
        heating multiplier times the seasonal multiplier, rounded half up to whole
        cents, and is stored on the order as `estimated_cost_cents`."

        Design: Difficulty/combinatorial_formula/winterization_quote_nested_inputs
        """
        ctx = _quote_property("2026-01-15T00:00:00Z", fixture_count=8, has_pool=True,
                              heating_system="HOT_WATER", lot_size_sqft=6000)
        resp = api.create_work_order(
            create_work_order_payload(ctx["property_id"], order_type="WINTERIZATION",
                                      due_date="2026-01-20"),
            make_servicer_headers(ctx["servicer_id"]))
        wo = validate_success(resp, expected_status=201)
        assert wo["estimated_cost_cents"] == 60480, (
            f"(15000 + 8*1200 + 9000) * 1.50 * 1.20 = 60480, got {wo['estimated_cost_cents']}")
        assert wo["investor_allowable_version"] == 1

    def test_winterization_quote_off_season(self, api):
        """PRD: "A seasonal multiplier of 1.2 applies whenever the logical clock's
        month falls in October through March inclusive; in all other months it is
        1.0."

        Design: Difficulty/combinatorial_formula/winterization_quote_nested_inputs
        """
        ctx = _quote_property("2026-07-15T00:00:00Z", fixture_count=8, has_pool=True,
                              heating_system="HOT_WATER", lot_size_sqft=6000)
        resp = api.create_work_order(
            create_work_order_payload(ctx["property_id"], order_type="WINTERIZATION",
                                      due_date="2026-07-20"),
            make_servicer_headers(ctx["servicer_id"]))
        wo = validate_success(resp, expected_status=201)
        assert wo["estimated_cost_cents"] == 50400, (
            f"same base * 1.50 * 1.00 seasonal = 50400, got {wo['estimated_cost_cents']}")

    def test_dewinterization_half_base_quote(self, api):
        """PRD: "For `DEWINTERIZATION` orders the seasonal multiplier is always 1.0
        and the base is halved — rounded down to a whole cent — before the
        multipliers are applied."

        Design: Corner/calculations/dewinterization_half_base_quote
        """
        ctx = setup_portfolio(item_code="DEWINTERIZATION",
                              allowable_overrides={
                                  "max_per_occurrence_cents": 999999,
                                  "max_occurrences_per_calendar_year": 5,
                                  "aggregate_cap_cents_per_property_year": 9999999,
                                  "requires_bid_over_cents": 99999999},
                              property_overrides={"fixture_count": 8, "heating_system": "FORCED_AIR",
                                                  "lot_size_sqft": 6000},
                              clock="2026-01-15T00:00:00Z", with_crew=False)
        resp = api.create_work_order(
            create_work_order_payload(ctx["property_id"], order_type="DEWINTERIZATION",
                                      due_date="2026-01-20"),
            make_servicer_headers(ctx["servicer_id"]))
        wo = validate_success(resp, expected_status=201)
        assert wo["estimated_cost_cents"] == 12300, (
            f"(15000 + 8*1200) / 2 = 12300 even in January, got {wo['estimated_cost_cents']}")


class TestVolumeRebate:
    def _setup_million_cent_approval(self, api):
        """One DAMAGE_REPAIR invoice approved at exactly 1,000,000 cents with
        approved_at in August 2026."""
        ctx = setup_completed_order_with_invoice(
            order_type="DAMAGE_REPAIR", unit_price_cents=1000000,
            submitted_cost_cents=1000000,
            allowable_overrides={
                "max_per_occurrence_cents": 1000000,
                "max_occurrences_per_calendar_year": 5,
                "aggregate_cap_cents_per_property_year": 5000000,
                "requires_bid_over_cents": 99999999},
            property_overrides={"fixture_count": 7, "lot_size_sqft": 8000},
            clock="2026-08-05T00:00:00Z")
        validate_success(api.submit_invoice(ctx["invoice_id"], ADMIN))
        validate_success(api.approve_invoice(ctx["invoice_id"],
                                             make_servicer_headers(ctx["servicer_id"])))
        return ctx

    def test_volume_rebate_tier_boundary(self, api):
        """PRD: "A gross of at least 1,000,000 cents earns a rate of 1.5 percent; a
        gross of at least 500,000 cents but below 1,000,000 earns 1.0 percent;
        anything smaller earns nothing, and the boundaries are inclusive — a gross
        of exactly 1,000,000 cents earns the 1.5 percent rate. The sweep records the
        gross as the servicer's `prior_month_gross_cents` and the rebate — gross
        times rate, rounded half up to whole cents — as its
        `volume_rebate_cents`."

        Design: Difficulty/combinatorial_formula/volume_rebate_evaluation_order
        """
        ctx = self._setup_million_cent_approval(api)
        set_clock("2026-09-01T00:00:00Z")
        run_daily_sweep()
        svc = validate_success(api.get_servicer(ctx["servicer_id"], ADMIN))
        assert svc["prior_month_gross_cents"] == 1000000, (
            f"August gross is the approved 1000000, got {svc['prior_month_gross_cents']}")
        assert svc["volume_rebate_cents"] == 15000, (
            f"1000000 * 0.015 = 15000, got {svc['volume_rebate_cents']}")

    def test_volume_rebate_never_feeds_gross(self, api):
        """PRD: "rebate credits are never invoices, so a rebate never feeds a later
        gross."

        Design: Difficulty/combinatorial_formula/volume_rebate_evaluation_order
        """
        ctx = self._setup_million_cent_approval(api)
        set_clock("2026-09-01T00:00:00Z")
        run_daily_sweep()
        set_clock("2026-10-01T00:00:00Z")
        run_daily_sweep()
        svc = validate_success(api.get_servicer(ctx["servicer_id"], ADMIN))
        assert svc["prior_month_gross_cents"] == 0, (
            f"September gross reads 0, not rebate-contaminated, got {svc['prior_month_gross_cents']}")
        assert svc["volume_rebate_cents"] == 0
