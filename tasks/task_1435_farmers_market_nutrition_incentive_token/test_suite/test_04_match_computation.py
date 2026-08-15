"""Match computation: nested min, ratio constants, caps, and pool accounting (PRD §3.4)."""
from test_helpers import (
    validate_success, get_success_data,
    TEST_USERS,
    create_open_day,
    setup_booth_scenario,
    create_issuance_payload,
    assert_program_pool_invariants,
)

ADMIN = TEST_USERS["program_admin_headers"]
BOOTH = TEST_USERS["booth_operator_headers"]
MANAGER = TEST_USERS["market_manager_headers"]


def _issue(api, shopper_id, day_id, charge):
    """One issuance with a fresh OCC read of the shopper version."""
    shopper = get_success_data(api.get_shopper(shopper_id, BOOTH))
    return api.create_issuance(
        create_issuance_payload(shopper_id=shopper_id, market_day_id=day_id,
                                benefit_charged_cents=charge,
                                expected_shopper_version=shopper["version"]),
        BOOTH)


class TestNestedMinClamps:
    def test_day_allowance_binds_second_issuance(self, api):
        """PRD §3.4: "Second, the remaining daily allowance is the daily cap
        minus the match value already issued to that shopper on the calendar
        date of the market day — an issuance always counts toward the calendar
        date of its market day, never the wall-clock moment of the request, and
        only issuances still in `ACTIVE` status count toward either accumulator."
        PRD §3.4: "The operative match, recorded on the issuance as
        `match_cents`, is the smallest of these four quantities — the raw match
        and the three remaining allowances — rounded down to a whole-dollar
        multiple of 100 cents, because match tokens exist only in one-dollar
        denominations; any sub-dollar remainder is forfeited."

        Design: Difficulty/combinatorial_formula/match_nested_min_clamps_to_day_remaining
        """
        sc = setup_booth_scenario(with_vendor=False)
        shop_id, day_id = sc["shopper"]["id"], sc["market_day"]["id"]

        first = validate_success(_issue(api, shop_id, day_id, 1200), expected_status=201)
        assert first["match_cents"] == 1200, "raw 1200 within all allowances"

        second = validate_success(_issue(api, shop_id, day_id, 1500), expected_status=201)
        assert second["match_cents"] == 800, "min(1500, 2000-1200, 18800, 98800) — day allowance binds"

    def test_match_accumulators_after_day_clamp(self, api):
        """PRD §3.4: "Recording it raises the shopper's
        `season_match_used_cents` by the minted match, draws the program's
        `match_pool_remaining_cents` down by the same amount, and raises the
        market day's `issued_value_cents` by base plus match; the shopper, the
        program, and the market day each increment their `version`."

        Design: Difficulty/combinatorial_formula/match_nested_min_clamps_to_day_remaining
        """
        sc = setup_booth_scenario(with_vendor=False)
        shop_id, day_id = sc["shopper"]["id"], sc["market_day"]["id"]
        validate_success(_issue(api, shop_id, day_id, 1200), expected_status=201)
        validate_success(_issue(api, shop_id, day_id, 1500), expected_status=201)

        shopper = get_success_data(api.get_shopper(shop_id, BOOTH))
        assert shopper["season_match_used_cents"] == 2000, "1200 + 800 accumulate across issuances"
        program = get_success_data(api.get_program(sc["program"]["id"], ADMIN))
        assert program["match_pool_remaining_cents"] == 98000, "100000 - 2000 minted match"
        assert_program_pool_invariants(program)


class TestPoolExhaustion:
    def test_pool_binds_first_issuance(self, api):
        """PRD §3.4: "Fourth, the remaining pool is the program's
        `match_pool_remaining_cents`."
        PRD §3.4: "The operative match, recorded on the issuance as
        `match_cents`, is the smallest of these four quantities — the raw match
        and the three remaining allowances — rounded down to a whole-dollar
        multiple of 100 cents, because match tokens exist only in one-dollar
        denominations; any sub-dollar remainder is forfeited."

        Design: Difficulty/combinatorial_formula/pool_remaining_feeds_next_match_evaluation_order
        """
        sc = setup_booth_scenario(pool_cents=900, with_vendor=False)
        first = validate_success(
            _issue(api, sc["shopper"]["id"], sc["market_day"]["id"], 1000),
            expected_status=201)
        assert first["match_cents"] == 900, "pool 900 binds below raw 1000"
        program = get_success_data(api.get_program(sc["program"]["id"], ADMIN))
        assert program["match_pool_remaining_cents"] == 0

    def test_exhausted_pool_zero_match_base_still_mints(self, api):
        """PRD §3.4: "Clamping is silent: when any allowance is exhausted the
        match is simply zero, the issuance still succeeds, and base tokens
        always mint — cap exhaustion is never an error."

        Design: Difficulty/combinatorial_formula/pool_remaining_feeds_next_match_evaluation_order
        """
        sc = setup_booth_scenario(pool_cents=900, with_vendor=False)
        shop_id, day_id = sc["shopper"]["id"], sc["market_day"]["id"]
        validate_success(_issue(api, shop_id, day_id, 1000), expected_status=201)

        second = validate_success(_issue(api, shop_id, day_id, 500), expected_status=201)
        assert second["match_cents"] == 0, "pool exhausted -> zero match"
        assert second["base_value_cents"] == 500, "base tokens always mint"
        program = get_success_data(api.get_program(sc["program"]["id"], ADMIN))
        assert program["match_pool_remaining_cents"] == 0, "pool never goes negative"


class TestDailyCapBoundary:
    def test_daily_cap_exact_boundary_granted_in_full(self, api):
        """PRD §3.4: "`SNAP` matches dollar for dollar (a ratio of 1.0) up to a
        daily cap of $20.00 and a season cap of $200.00; `WIC` matches at fifty
        cents on the dollar (a ratio of 0.5) up to $10.00 per day and $100.00
        per season; `SENIOR` matches dollar for dollar up to $15.00 per day and
        $150.00 per season."
        PRD §3.4: "The operative match, recorded on the issuance as
        `match_cents`, is the smallest of these four quantities — the raw match
        and the three remaining allowances — rounded down to a whole-dollar
        multiple of 100 cents, because match tokens exist only in one-dollar
        denominations; any sub-dollar remainder is forfeited."

        Design: Difficulty/boundary_precision_check/daily_match_cap_exact_boundary_then_exhaustion
        """
        sc = setup_booth_scenario(with_vendor=False)
        first = validate_success(
            _issue(api, sc["shopper"]["id"], sc["market_day"]["id"], 2000),
            expected_status=201)
        assert first["match_cents"] == 2000, "match exactly at the $20.00 daily cap is granted"

    def test_daily_cap_exhausted_next_issuance_zero_match(self, api):
        """PRD §3.4: "Clamping is silent: when any allowance is exhausted the
        match is simply zero, the issuance still succeeds, and base tokens
        always mint — cap exhaustion is never an error."
        PRD §3.4: "Recording it raises the shopper's
        `season_match_used_cents` by the minted match, draws the program's
        `match_pool_remaining_cents` down by the same amount, and raises the
        market day's `issued_value_cents` by base plus match; the shopper, the
        program, and the market day each increment their `version`."

        Design: Difficulty/boundary_precision_check/daily_match_cap_exact_boundary_then_exhaustion
        """
        sc = setup_booth_scenario(with_vendor=False)
        shop_id, day_id = sc["shopper"]["id"], sc["market_day"]["id"]
        validate_success(_issue(api, shop_id, day_id, 2000), expected_status=201)

        second = validate_success(_issue(api, shop_id, day_id, 100), expected_status=201)
        assert second["match_cents"] == 0, "day allowance exhausted -> clamped to zero"
        assert second["base_value_cents"] == 100, "base issuance continues"
        shopper = get_success_data(api.get_shopper(shop_id, BOOTH))
        assert shopper["season_match_used_cents"] == 2000


class TestBenefitTypeConstants:
    def test_wic_half_ratio_floored_to_whole_dollar(self, api):
        """PRD §3.4: "`SNAP` matches dollar for dollar (a ratio of 1.0) up to a
        daily cap of $20.00 and a season cap of $200.00; `WIC` matches at fifty
        cents on the dollar (a ratio of 0.5) up to $10.00 per day and $100.00
        per season; `SENIOR` matches dollar for dollar up to $15.00 per day and
        $150.00 per season."
        PRD §3.4: "First, the raw match is the charged amount multiplied by the
        shopper's benefit-type ratio, rounded down to a whole cent."
        PRD §3.4: "The operative match, recorded on the issuance as
        `match_cents`, is the smallest of these four quantities — the raw match
        and the three remaining allowances — rounded down to a whole-dollar
        multiple of 100 cents, because match tokens exist only in one-dollar
        denominations; any sub-dollar remainder is forfeited."

        Design: Corner/calculations/c_calc_wic_half_ratio_floored_to_whole_dollar
        """
        sc = setup_booth_scenario(benefit_type="WIC", benefit_ref="WIC-1", with_vendor=False)
        issuance = validate_success(
            _issue(api, sc["shopper"]["id"], sc["market_day"]["id"], 300),
            expected_status=201)
        assert issuance["match_cents"] == 100, "floor(min(floor(300*0.5)=150, ...) / 100) * 100"
        program = get_success_data(api.get_program(sc["program"]["id"], ADMIN))
        assert program["match_pool_remaining_cents"] == 99900, "only the minted 100 is debited"

    def test_senior_day_cap_binds_below_raw_match(self, api):
        """PRD §3.4: "`SNAP` matches dollar for dollar (a ratio of 1.0) up to a
        daily cap of $20.00 and a season cap of $200.00; `WIC` matches at fifty
        cents on the dollar (a ratio of 0.5) up to $10.00 per day and $100.00
        per season; `SENIOR` matches dollar for dollar up to $15.00 per day and
        $150.00 per season."
        PRD §3.4: "The operative match, recorded on the issuance as
        `match_cents`, is the smallest of these four quantities — the raw match
        and the three remaining allowances — rounded down to a whole-dollar
        multiple of 100 cents, because match tokens exist only in one-dollar
        denominations; any sub-dollar remainder is forfeited."

        Design: Corner/calculations/c_calc_senior_day_cap_binds_below_raw_match
        """
        sc = setup_booth_scenario(benefit_type="SENIOR", benefit_ref="SEN-1", with_vendor=False)
        issuance = validate_success(
            _issue(api, sc["shopper"]["id"], sc["market_day"]["id"], 2000),
            expected_status=201)
        assert issuance["match_cents"] == 1500, "SENIOR day cap $15.00 binds below raw 2000"

    def test_pool_partial_clamp_then_floor(self, api):
        """PRD §3.4: "Fourth, the remaining pool is the program's
        `match_pool_remaining_cents`."
        PRD §3.4: "The operative match, recorded on the issuance as
        `match_cents`, is the smallest of these four quantities — the raw match
        and the three remaining allowances — rounded down to a whole-dollar
        multiple of 100 cents, because match tokens exist only in one-dollar
        denominations; any sub-dollar remainder is forfeited."

        Design: Corner/calculations/c_calc_pool_partial_clamp_then_floor
        """
        sc = setup_booth_scenario(pool_cents=950, with_vendor=False)
        issuance = validate_success(
            _issue(api, sc["shopper"]["id"], sc["market_day"]["id"], 1000),
            expected_status=201)
        assert issuance["match_cents"] == 900, "min(1000, 2000, 20000, 950) = 950, floored to 900"
        program = get_success_data(api.get_program(sc["program"]["id"], ADMIN))
        assert program["match_pool_remaining_cents"] == 50, "pool debited only the minted 900"


class TestAccumulatorScoping:
    def test_day_allowance_resets_across_days_season_accumulates(self, api):
        """PRD §3.4: "Second, the remaining daily allowance is the daily cap
        minus the match value already issued to that shopper on the calendar
        date of the market day — an issuance always counts toward the calendar
        date of its market day, never the wall-clock moment of the request, and
        only issuances still in `ACTIVE` status count toward either accumulator."
        PRD §3.4: "Third, the remaining season allowance is the season cap
        minus the shopper's `season_match_used_cents`."

        Design: Corner/calculations/c_calc_season_usage_accumulates_across_days_day_cap_resets
        """
        sc = setup_booth_scenario(with_vendor=False)
        shop_id = sc["shopper"]["id"]
        first = validate_success(
            _issue(api, shop_id, sc["market_day"]["id"], 2000), expected_status=201)
        assert first["match_cents"] == 2000

        validate_success(api.set_clock("2026-08-02T00:00:00Z", ADMIN))
        day2 = create_open_day(sc["market"]["id"], date="2026-08-02",
                               opens_at="2026-08-02T08:00:00Z",
                               closes_at="2026-08-02T14:00:00Z")
        second = validate_success(_issue(api, shop_id, day2["id"], 2000), expected_status=201)
        assert second["match_cents"] == 2000, "day allowance keys on the market day's date"

        shopper = get_success_data(api.get_shopper(shop_id, BOOTH))
        assert shopper["season_match_used_cents"] == 4000, "season accumulator spans both days"


class TestImmediateConsistency:
    def test_pool_debit_visible_on_next_read(self, api):
        """PRD §3.4: "Recording it raises the shopper's
        `season_match_used_cents` by the minted match, draws the program's
        `match_pool_remaining_cents` down by the same amount, and raises the
        market day's `issued_value_cents` by base plus match; the shopper, the
        program, and the market day each increment their `version`."
        PRD §3.8: "The forward-looking view, `liability_forward_cents`, sums
        the face value of every token of the program that may still
        legitimately be presented — those in `ISSUED`, `REDEEMED`, or `FLAGGED`
        — treating flagged value as contingent exposure for pool planning."

        Design: Corner/consistency_model/c_consistency_immediate_pool_debit_visible_on_next_read
        """
        sc = setup_booth_scenario(with_vendor=False)
        issuance = validate_success(
            _issue(api, sc["shopper"]["id"], sc["market_day"]["id"], 1200),
            expected_status=201)
        assert issuance["match_cents"] == 1200

        program = get_success_data(api.get_program(sc["program"]["id"], ADMIN))
        assert program["match_pool_remaining_cents"] == 98800, "100000 - 1200 minted match"
        assert program["liability_forward_cents"] == 2400, "1200 base + 1200 match all ISSUED"
        day = get_success_data(api.get_market_day(sc["market_day"]["id"], MANAGER))
        assert day["issued_value_cents"] == 2400, "base plus match"
