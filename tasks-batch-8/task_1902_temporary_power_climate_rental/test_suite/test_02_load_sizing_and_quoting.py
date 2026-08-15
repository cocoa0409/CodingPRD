"""Load sizing variants and tiered quote accrual (PRD §3.3, §3.4)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_equipment_line,
    add_kit_line,
    assert_rental_contract,
    create_accessory_kit,
    create_contract,
    create_customer,
    create_equipment_unit,
    create_site,
    get_contract,
    quote_contract,
    run_size_load,
    setup_draft_contract,
    setup_quoted_contract,
    validate_error,
    validate_success,
)

TEST_SALES = TEST_USERS["sales_engineer_headers"]

# The dual-variant profile from the design recipe: 100 CONTINUOUS + 80
# INTERMITTENT + 40 STANDBY.
DUAL_PROFILE = [
    {"load_type": "CONTINUOUS", "nameplate_kw": 100},
    {"load_type": "INTERMITTENT", "nameplate_kw": 80},
    {"load_type": "STANDBY", "nameplate_kw": 40},
]


class TestLoadSizingDualVariant:
    def test_nameplate_sum_sizes_to_275(self, api):
        """PRD §3.3: "Under the nameplate-sum variant, every entry's `nameplate_kw`
        is summed, the sum is multiplied by the safety factor 1.25, and the result is
        rounded up to the next whole kilowatt."

        Design: Difficulty/dual_variant_calc/load_sizing_nameplate_vs_diversified
        """
        customer = create_customer()
        site = create_site(customer["id"])
        contract = create_contract(
            customer["id"], site["id"], load_profile=DUAL_PROFILE
        )

        sized = validate_success(
            api.size_load(contract["id"], {"sizing_method": "NAMEPLATE_SUM"}, TEST_SALES),
            200,
        )
        # ceil(1.25 * (100 + 80 + 40)) = ceil(275.0) = 275
        assert sized["sized_kw"] == 275
        assert sized["sizing_method"] == "NAMEPLATE_SUM"

    def test_diversified_demand_sizes_to_213_and_records_variant(self, api):
        """PRD §3.3: "Under the diversified-demand variant, each entry's
        `nameplate_kw` is first weighted by its demand factor — 1.0 for `CONTINUOUS`,
        0.7 for `INTERMITTENT`, and 0.35 for `STANDBY` loads — the weighted entries
        are summed, the sum is multiplied by the same 1.25 safety factor, and the
        result is rounded up to the next whole kilowatt."
        PRD §3.3: "Either way, the outcome is written to the contract as `sized_kw`,
        the variant used is recorded in `sizing_method`, and the contract's `version`
        increments."

        Design: Difficulty/dual_variant_calc/load_sizing_nameplate_vs_diversified
        """
        customer = create_customer()
        site = create_site(customer["id"])
        contract = create_contract(
            customer["id"], site["id"], load_profile=DUAL_PROFILE
        )

        nameplate = validate_success(
            api.size_load(contract["id"], {"sizing_method": "NAMEPLATE_SUM"}, TEST_SALES),
            200,
        )
        diversified = validate_success(
            api.size_load(
                contract["id"], {"sizing_method": "DIVERSIFIED_DEMAND"}, TEST_SALES
            ),
            200,
        )
        # ceil(1.25 * (100*1.0 + 80*0.7 + 40*0.35)) = ceil(212.5) = 213
        assert diversified["sized_kw"] == 213
        assert nameplate["sized_kw"] == 275
        assert nameplate["sized_kw"] != diversified["sized_kw"], (
            "identical load profile must yield variant-divergent sizes"
        )

        fetched = get_contract(contract["id"])
        assert fetched["sized_kw"] == 213
        assert fetched["sizing_method"] == "DIVERSIFIED_DEMAND", (
            "the last applied variant is recorded on the contract"
        )


class TestTieredQuoteAccrual:
    def test_quote_decomposes_seven_day_window_into_week_tier(self, api):
        """PRD §3.4: "That duration decomposes into whole twenty-eight-day months, and
        the remainder decomposes into whole seven-day weeks and leftover days."
        PRD §3.4: "The time charge is the whole months times the monthly rate plus the
        remainder charge; the line charge is the time charge multiplied by the line
        `quantity`; and the line's `demob_fee_cents` is added once for each equipment
        line."

        Design: Difficulty/combinatorial_formula/rental_charge_tiered_decomposition
        """
        bundle = setup_quoted_contract(with_kit=True)
        # Equipment line: 7 days -> 1 week = 60000, + 35000 demob = 95000.
        # Kit line x1: 1 week = 15000. Contract total 110000.
        assert bundle["contract"]["quoted_total_cents"] == 110000

    def test_quote_week_tier_not_naive_daily_sum(self, api):
        """PRD §3.4: "The remainder charge is the lesser of the whole weeks times the
        weekly rate plus the leftover-day block, and the monthly rate."

        Design: Difficulty/combinatorial_formula/rental_charge_tiered_decomposition
        """
        bundle = setup_quoted_contract(with_kit=True)
        quoted = bundle["contract"]["quoted_total_cents"]
        naive_daily = 7 * 12000 + 35000 + 7 * 3000  # 140000 — must NOT be used
        assert quoted != naive_daily, "the week tier must be selected at day 7"
        assert quoted == 110000


class TestRateBreakBoundary:
    def test_day7_window_selects_week_tier_exactly(self, api):
        """PRD §3.4: "The chargeable duration in days is the number of seconds between
        window start and end divided by 86,400, rounded up to the next whole day".
        PRD §3.4: "That duration decomposes into whole twenty-eight-day months, and
        the remainder decomposes into whole seven-day weeks and leftover days."

        Design: Difficulty/boundary_precision_check/rate_break_day7_equals_week_rate
        """
        bundle = setup_quoted_contract()
        # Exactly 7 days: weeks = 1, days = 0 -> 60000 + 35000 demob.
        assert bundle["contract"]["quoted_total_cents"] == 95000, (
            "an exactly-7-day window is one weekly block, not 7 daily charges "
            "(7 x 12000 + 35000 = 119000 would be wrong)"
        )

    def test_day8_window_extends_beyond_week_tier(self, api):
        """PRD §3.4: "The leftover-day block costs the lesser of the leftover days
        times the daily rate and the weekly rate, and contributes zero when there are
        no leftover days."

        Design: Difficulty/boundary_precision_check/rate_break_day7_equals_week_rate
        """
        bundle = setup_quoted_contract(
            contract_overrides={"expected_offhire_date": "2026-09-09T00:00:00Z"}
        )
        # 8 days: 1 week (60000) + 1 leftover day (min(12000, 60000)) = 72000,
        # + 35000 demob = 107000.
        assert bundle["contract"]["quoted_total_cents"] == 107000

    def test_day6_day_block_caps_at_week_rate(self, api):
        """PRD §3.4: "The leftover-day block costs the lesser of the leftover days
        times the daily rate and the weekly rate, and contributes zero when there are
        no leftover days."

        Design: Corner/calculations/day6_caps_at_week_rate
        """
        bundle = setup_quoted_contract(
            contract_overrides={"expected_offhire_date": "2026-09-07T00:00:00Z"}
        )
        # 6 days: min(6 x 12000, 60000) = 60000 capped, + 35000 demob = 95000;
        # uncapped 72000 + 35000 = 107000 would be wrong.
        assert bundle["contract"]["quoted_total_cents"] == 95000


class TestSizeLoadConsistency:
    def test_immediate_read_after_size_load(self, api):
        """PRD §3.3: "Either way, the outcome is written to the contract as
        `sized_kw`, the variant used is recorded in `sizing_method`, and the
        contract's `version` increments."

        Design: Corner/consistency_model/immediate_read_after_write
        """
        customer = create_customer()
        site = create_site(customer["id"])
        contract = create_contract(customer["id"], site["id"])

        run_size_load(contract["id"], "NAMEPLATE_SUM")
        fetched = get_contract(contract["id"])
        # ceil(1.25 * 160) = 200
        assert fetched["sized_kw"] == 200
        assert fetched["sizing_method"] == "NAMEPLATE_SUM"
        assert fetched["version"] == 2


class TestQuotePrerequisites:
    def test_quote_with_undersized_fleet_rejected(self, api):
        """PRD §3.4: "the contract must have a `sized_kw`, must hold at least one
        line, and must field enough equipment — the sum of `capacity_kw` across its
        equipment lines must be at least the `sized_kw`. Failing any leg is rejected
        with `ERR_UNDERSIZED_FLEET` (HTTP 422)".

        Design: Corner/validations/undersized_fleet_at_quote
        """
        bundle = setup_draft_contract(
            unit_overrides={"capacity_kw": 150, "day_rate_cents": 9000,
                            "week_rate_cents": 45000, "month_rate_cents": 150000,
                            "demob_fee_cents": 25000, "nox_g_per_kwh": 3.0},
        )
        # sized_kw = 200 but the only equipment line fields 150 kW.
        assert bundle["contract"]["sized_kw"] == 200

        res = api.quote_contract(bundle["contract"]["id"], TEST_SALES)
        validate_error(res, ApiErrorId.ERR_UNDERSIZED_FLEET, expected_status=422)
        assert get_contract(bundle["contract"]["id"])["status"] == "DRAFT"

    def test_quote_from_quoted_returns_invalid_state(self, api):
        """PRD §3.9: "any action attempted against a resource standing in a state that
        does not source the requested transition is rejected with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/quote_from_quoted_returns_invalid_state
        """
        bundle = setup_quoted_contract()
        contract = bundle["contract"]
        assert contract["status"] == "QUOTED"

        res = api.quote_contract(contract["id"], TEST_SALES)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        fetched = get_contract(contract["id"])
        assert fetched["version"] == contract["version"], (
            "a rejected transition must not advance the contract version"
        )
        assert fetched["quoted_at"] == contract["quoted_at"]
        assert fetched["quoted_total_cents"] == contract["quoted_total_cents"]
