"""
Valuation methods, transfer risk variants and the pricing arithmetic around them.

Three areas of the contract are pinned here. First the fair-value model: the
deterministic single-projection method against the shock-weighted method that
evaluates the same projection under three rate scenarios, and the way a newer run
retires the one before it. Second the counterparty transfer risk score, whose
two variants read different entity sets — the balance-sheet row alone before the
trade, the completed transfers and their error cases after it. Third the two
different roundings the desk applies to one offered price: a single rounding over
the whole tape for the bid's own value, and a rounding per stratum before
summation for the contractual purchase price, plus the holdback sized off that
figure.
"""

from test_helpers import (
    C, F, U,
    ApiClient, JsonDict,
    assert_holdback_split, assert_scenario_map, assert_settlement_wire,
    assert_status, assert_stratum_breakdown,
    build_completed_transfer, build_desk, build_locked_portfolio,
    build_published_package, data_of, refresh_portfolio,
)

# The heterogeneous three-loan pool, valued at the opening 4000 bps curve under
# the desk-base assumption vector.
POOL_V_NAME = "Pool-V"
POOL_VB_NAME = "Pool-Vb"

# Pool-Vb is Pool-V with its middle loan performing: same balance, same note
# rate, same escrow, but CURRENT with no loss-mitigation workout attached.
LOANS_VB = [
    dict(C.LOANS_V[0], loan_number="Vb-0001"),
    dict(C.LOANS_V[1], loan_number="Vb-0002",
         delinquency_bucket="CURRENT", loss_mit_status="NONE"),
    dict(C.LOANS_V[2], loan_number="Vb-0003"),
]

POOL_VB_STATIC_VALUE_CENTS = 246489
POOL_VB_STATIC_VALUE_BPS = 54.78
POOL_V_WEIGHTED_AVG_NOTE_RATE = 6.5833

# Pool T at 118 bps: one rounding over the whole tape versus four strata each
# rounded before the sum.
TAPE_BID_VALUE_CENTS = 472002
STRATUM_PRICE_CENTS = 118001
PURCHASE_PRICE_CENTS = 472004
HOLDBACK_CENTS = 28320
SETTLEMENT_WIRE_CENTS = 443684
RESERVE_PRICE_CENTS = 162997
POOL_T_STRATUM_LABELS = ["CA", "FL", "NY", "TX"]

# Bravo's balance-sheet score and the two service-quality readings on it.
BRAVO_BASE_SCORE = 92
BRAVO_POST_TRANSFER_SCORE = 62
BRAVO_APPROVAL_PENALTY = 8
BRAVO_COMPLAINT_PENALTY = 30


def _pool_v(api: ApiClient) -> JsonDict:
    """A locked tape holding the heterogeneous three-loan pool."""
    return build_locked_portfolio(api, loans=C.LOANS_V, name=POOL_V_NAME)


def _value_second_pool(api: ApiClient, env: JsonDict, loans: list,
                       name: str) -> JsonDict:
    """Open, load, lock and value a second pool for the same selling servicer."""
    portfolio = F.create_portfolio(api, env["seller_id"], name=name)
    F.add_loans(api, portfolio["id"], env["seller_id"], loans)
    locked = F.lock_tape(api, portfolio["id"], env["seller_id"])
    run = F.run_valuation(api, portfolio["id"], env["assumption_set_id"],
                          locked["version"])
    return {"portfolio": F.read_portfolio(api, portfolio["id"]), "run": run}


def _work_one_error_case(api: ApiClient, env: JsonDict) -> JsonDict:
    """
    Log one borrower notice of error on the first transferred loan, then
    acknowledge it one day later and resolve it five days after it was opened —
    both inside their statutory windows.
    """
    F.set_clock(api, "2026-09-05T00:00:00Z")
    case = F.open_error_case(api, env["transfer_id"],
                             env["included_loan_ids"][0])
    F.set_clock(api, "2026-09-06T00:00:00Z")
    F.acknowledge_case(api, case["id"], env["buyer_id"])
    F.set_clock(api, "2026-09-10T00:00:00Z")
    return F.resolve_case(api, case["id"], env["buyer_id"],
                          remediation_cents=5000)


# ---------------------------------------------------------------------------
# The two fair-value methods on one pool
# ---------------------------------------------------------------------------
def test_static_valuation_prices_the_pool_once_at_the_assumption_speed(
        api: ApiClient) -> None:
    """
    The deterministic method runs one projection and publishes no scenario map.

    PRD: "Under `DETERMINISTIC_STATIC` that projection is evaluated exactly once, at the assumption set's own prepayment speed and the curve-adjusted discount rate, and `scenario_values` is null."

    Design: Difficulty/dual_variant_calc/msr_fair_value_static_versus_oas_shock_weighted
    """
    env = _pool_v(api)

    run = F.run_valuation(api, env["portfolio_id"], env["assumption_set_id"],
                          env["portfolio_version"],
                          method="DETERMINISTIC_STATIC")

    assert run["method"] == "DETERMINISTIC_STATIC"
    assert run["value_cents"] == C.POOL_V_STATIC_VALUE_CENTS
    assert run["value_bps_of_upb"] == C.POOL_V_STATIC_VALUE_BPS
    assert run["scenario_values"] is None
    assert float(run["effective_discount_rate_pct"]) == 10.0
    assert run["included_loan_count"] == 3
    assert_status(run, "COMPLETED")


def test_shock_weighted_valuation_lands_below_the_static_value(
        api: ApiClient) -> None:
    """
    Weighting the three shocked legs prices the same pool below the static run.

    PRD: "The run's `value_cents` is then the sum across the three scenarios of each weight multiplied by that scenario's value, rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/msr_fair_value_static_versus_oas_shock_weighted
    """
    env = _pool_v(api)
    static_run = F.run_valuation(api, env["portfolio_id"],
                                 env["assumption_set_id"],
                                 env["portfolio_version"],
                                 method="DETERMINISTIC_STATIC")
    refresh_portfolio(api, env)

    oas_run = F.run_valuation(api, env["portfolio_id"],
                              env["assumption_set_id"],
                              env["portfolio_version"],
                              method="OAS_SHOCK_WEIGHTED")

    assert oas_run["method"] == "OAS_SHOCK_WEIGHTED"
    assert oas_run["value_cents"] == C.POOL_V_OAS_VALUE_CENTS
    assert oas_run["value_bps_of_upb"] == C.POOL_V_OAS_VALUE_BPS
    assert oas_run["included_loan_count"] == 3
    assert static_run["value_cents"] - oas_run["value_cents"] == 702


def test_shock_weighted_run_stores_all_three_scenario_values(
        api: ApiClient) -> None:
    """
    The scenario map carries the three labelled legs, its BASE leg matching the
    static run exactly.

    PRD: "Each scenario's value is itself computed by rounding per loan and then summing, and is stored in `scenario_values` under the scenario's own label, so the map has exactly the three keys `DOWN_50`, `BASE` and `UP_50`."

    Design: Difficulty/dual_variant_calc/msr_fair_value_static_versus_oas_shock_weighted
    """
    env = _pool_v(api)
    static_run = F.run_valuation(api, env["portfolio_id"],
                                 env["assumption_set_id"],
                                 env["portfolio_version"],
                                 method="DETERMINISTIC_STATIC")
    refresh_portfolio(api, env)

    oas_run = F.run_valuation(api, env["portfolio_id"],
                              env["assumption_set_id"],
                              env["portfolio_version"],
                              method="OAS_SHOCK_WEIGHTED")

    stored = F.read_valuation_run(api, oas_run["id"])
    assert_scenario_map(stored, C.POOL_V_OAS_SCENARIO_VALUES)
    assert stored["scenario_values"]["BASE"] == static_run["value_cents"]
    assert float(stored["effective_discount_rate_pct"]) == 10.0


def test_second_valuation_run_supersedes_the_unreferenced_first_run(
        api: ApiClient) -> None:
    """
    With no package anchored on it, the earlier static run retires when the
    shock-weighted run lands.

    PRD: "Creating a newer run for the same portfolio retires older ones: a run whose status is `COMPLETED` or `STALE` moves to `SUPERSEDED` (a terminal status) with its `version` incremented by 1 — *unless* a bid package whose status is `PUBLISHED`, `BIDDING_SUSPENDED` or `AWARDED` still points at it, in which case the older run keeps whatever status it had, so a published reserve price never loses its anchor."

    Design: Difficulty/dual_variant_calc/msr_fair_value_static_versus_oas_shock_weighted
    """
    env = _pool_v(api)
    static_run = F.run_valuation(api, env["portfolio_id"],
                                 env["assumption_set_id"],
                                 env["portfolio_version"],
                                 method="DETERMINISTIC_STATIC")
    refresh_portfolio(api, env)

    oas_run = F.run_valuation(api, env["portfolio_id"],
                              env["assumption_set_id"],
                              env["portfolio_version"],
                              method="OAS_SHOCK_WEIGHTED")

    retired = F.read_valuation_run(api, static_run["id"])
    assert_status(retired, "SUPERSEDED")
    assert retired["version"] == 2
    assert_status(F.read_valuation_run(api, oas_run["id"]), "COMPLETED")


# ---------------------------------------------------------------------------
# The two transfer-risk variants on one counterparty
# ---------------------------------------------------------------------------
def test_pre_award_risk_score_reads_only_the_counterparty_row(
        api: ApiClient) -> None:
    """
    Before any trade the acquiring servicer scores purely off its balance sheet,
    rating and agency approvals.

    PRD: "Under the `PRE_AWARD` variant — which is what the read answers when `variant` is omitted, and what the bid gate always uses — the score *is* the base score, and both `complaint_penalty` and `sla_penalty` report 0, because no post-transfer performance history exists at bid time."

    Design: Difficulty/dual_variant_calc/counterparty_risk_score_pre_award_versus_post_transfer
    """
    env = build_desk(api)

    score = data_of(api.get_risk_score(env["buyer_id"], U.MANAGER))

    assert score["variant"] == "PRE_AWARD"
    assert score["score"] == BRAVO_BASE_SCORE
    assert score["tier"] == "LOW"
    assert score["rating_penalty"] == 0
    assert score["capital_penalty"] == 0
    assert score["approval_penalty"] == BRAVO_APPROVAL_PENALTY
    assert score["complaint_penalty"] == 0
    assert score["sla_penalty"] == 0


def test_post_transfer_risk_score_charges_the_complaint_concentration(
        api: ApiClient) -> None:
    """
    One complaint over four transferred loans drops the same institution two
    risk tiers, purely through the post-transfer penalties.

    PRD: "The first looks at complaint concentration: take the highest complaint concentration ratio (computed exactly as in §3.8, step one) across every servicing transfer of this counterparty whose status is `COMPLETED`, using 0.00 when the counterparty has none, multiply it by 3, round half up to a whole number, and cap the result at 30."

    Design: Difficulty/dual_variant_calc/counterparty_risk_score_pre_award_versus_post_transfer
    """
    env = build_completed_transfer(api)
    assert env["transfer"]["transferred_loan_count"] == 4
    _work_one_error_case(api, env)

    score = data_of(api.get_risk_score(env["buyer_id"], U.MANAGER,
                                       {"variant": "POST_TRANSFER"}))

    assert score["variant"] == "POST_TRANSFER"
    assert score["score"] == BRAVO_POST_TRANSFER_SCORE
    assert score["tier"] == "MEDIUM"
    assert score["complaint_penalty"] == BRAVO_COMPLAINT_PENALTY
    assert score["sla_penalty"] == 0


def test_default_risk_variant_ignores_the_completed_transfer_history(
        api: ApiClient) -> None:
    """
    The same counterparty, read with no variant, still scores off its unchanged
    balance-sheet row alone.

    PRD: "Because the two variants read different entity sets — one only the counterparty row, the other also its completed transfers and their error cases — the same institution scores differently the day after it closes a troubled transfer."

    Design: Difficulty/dual_variant_calc/counterparty_risk_score_pre_award_versus_post_transfer
    """
    env = build_completed_transfer(api)
    _work_one_error_case(api, env)

    default_read = data_of(api.get_risk_score(env["buyer_id"], U.MANAGER))

    assert default_read["variant"] == "PRE_AWARD"
    assert default_read["score"] == BRAVO_BASE_SCORE
    assert default_read["tier"] == "LOW"
    assert default_read["complaint_penalty"] == 0
    assert default_read["sla_penalty"] == 0
    buyer = data_of(api.get_counterparty(env["buyer_id"], U.MANAGER))
    assert buyer["servicer_rating"] == "TIER_1"
    assert buyer["net_worth_cents"] == 1200000000


# ---------------------------------------------------------------------------
# Delinquency multiplier and loss-mitigation surcharge inside one loan
# ---------------------------------------------------------------------------
def test_valuation_charges_delinquency_multiplier_over_the_base_service_cost(
        api: ApiClient) -> None:
    """
    A pool holding one sixty-day delinquent loan in forbearance values at the
    figure its multiplied-and-surcharged servicing cost produces.

    PRD: "the cost of servicing for the year is the assumption set's `cost_to_service_annual_cents` multiplied by the delinquency cost multiplier for the loan's `delinquency_bucket`, plus a flat additive surcharge for the loan's `loss_mit_status`."

    Design: Difficulty/combinatorial_formula/msr_fair_value_combines_delinquency_multiplier_and_loss_mit_surcharge
    """
    env = _pool_v(api)

    run = F.run_valuation(api, env["portfolio_id"], env["assumption_set_id"],
                          env["portfolio_version"],
                          method="DETERMINISTIC_STATIC")

    assert run["value_cents"] == C.POOL_V_STATIC_VALUE_CENTS
    assert run["value_bps_of_upb"] == C.POOL_V_STATIC_VALUE_BPS
    assert run["included_loan_count"] == 3
    portfolio = refresh_portfolio(api, env)
    assert portfolio["total_upb_cents"] == C.POOL_V_TOTAL_UPB_CENTS
    assert (portfolio["weighted_avg_note_rate_pct"]
            == POOL_V_WEIGHTED_AVG_NOTE_RATE)


def test_curing_one_loan_bucket_and_workout_lifts_the_pool_value(
        api: ApiClient) -> None:
    """
    Two pools identical but for one loan's delinquency bucket and workout status
    diverge by the whole of that loan's cost swing.

    PRD: "The delinquency multiplier is 1.0 for `CURRENT`, 1.5 for `DQ_30_59`, 2.5 for `DQ_60_89`, 4.0 for `DQ_90_PLUS` and 6.0 for `FORECLOSURE`."

    Design: Difficulty/combinatorial_formula/msr_fair_value_combines_delinquency_multiplier_and_loss_mit_surcharge
    """
    env = _pool_v(api)
    delinquent_run = F.run_valuation(api, env["portfolio_id"],
                                     env["assumption_set_id"],
                                     env["portfolio_version"],
                                     method="DETERMINISTIC_STATIC")

    performing = _value_second_pool(api, env, LOANS_VB, POOL_VB_NAME)

    assert delinquent_run["value_cents"] == C.POOL_V_STATIC_VALUE_CENTS
    assert performing["run"]["value_cents"] == POOL_VB_STATIC_VALUE_CENTS
    assert performing["run"]["value_bps_of_upb"] == POOL_VB_STATIC_VALUE_BPS
    assert (performing["run"]["value_cents"] - delinquent_run["value_cents"]
            == 37303)
    assert performing["run"]["included_loan_count"] == 3
    assert (performing["portfolio"]["total_upb_cents"]
            == C.POOL_V_TOTAL_UPB_CENTS)
    assert (performing["portfolio"]["weighted_avg_note_rate_pct"]
            == POOL_V_WEIGHTED_AVG_NOTE_RATE)


# ---------------------------------------------------------------------------
# One price, two roundings: the bid's value and the contractual purchase price
# ---------------------------------------------------------------------------
def test_bid_value_applies_the_price_once_over_the_whole_tape(
        api: ApiClient) -> None:
    """
    A 118 bps offer on the four-state tape is rounded exactly once, over the
    combined unpaid balance.

    PRD: "The bid's own economics are computed as `bid_value_cents`: the package's `tape_upb_cents` multiplied by `price_bps`, divided by 10,000, rounded half up to whole cents — **one** rounding over the whole tape."

    Design: Difficulty/combinatorial_formula/purchase_price_rounds_per_stratum_before_summation
    """
    env = build_published_package(api)
    assert env["package"]["stratum_count"] == 4
    assert env["package"]["tape_upb_cents"] == C.POOL_T_TOTAL_UPB_CENTS

    bid = F.submit_bid(api, env["package_id"], env["buyer_id"],
                       env["package_version"], price_bps=118, holdback_pct=6)

    assert bid["bid_value_cents"] == TAPE_BID_VALUE_CENTS
    assert bid["bid_value_cents"] >= env["package"]["reserve_price_cents"]


def test_reserve_price_scales_the_anchored_mark_by_the_floor(
        api: ApiClient) -> None:
    """
    Publication stamps a reserve of 95 percent of the anchored mark, so the
    offered price is measured against a figure no bid can move.

    PRD: "The reserve is the bound run's `value_cents`, multiplied by the package's `reserve_price_floor_pct` and divided by 100, multiplied by the package's `tape_upb_cents` and divided by the portfolio's `total_upb_cents` as frozen at tape lock, with a single half-up rounding to whole cents applied only at the very end and no intermediate rounding."

    Design: Difficulty/combinatorial_formula/purchase_price_rounds_per_stratum_before_summation
    """
    env = build_published_package(api)

    package = F.read_package(api, env["package_id"])

    assert package["reserve_price_cents"] == RESERVE_PRICE_CENTS
    assert TAPE_BID_VALUE_CENTS > package["reserve_price_cents"]


def test_purchase_price_rounds_each_stratum_before_the_summation(
        api: ApiClient) -> None:
    """
    Awarding the same 118 bps offer prices each of the four state strata on its
    own and sums the rounded results, two cents above the bid's own value.

    PRD: "For each distinct `stratum_label` on the awarded tape, visited in ascending lexicographic order of the label, the stratum's unpaid balance is the sum of `upb_snapshot_cents` over that stratum's included lines, and the stratum's price is that balance multiplied by the winning bid's `price_bps`, divided by 10,000, and rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/purchase_price_rounds_per_stratum_before_summation
    """
    env = build_published_package(api)
    bid = F.submit_bid(api, env["package_id"], env["buyer_id"],
                       env["package_version"], price_bps=118, holdback_pct=6)

    agreement = F.award(api, env["package_id"], bid["id"])

    assert agreement["purchase_price_cents"] == PURCHASE_PRICE_CENTS
    assert (agreement["purchase_price_cents"] - bid["bid_value_cents"]) == 2
    assert_stratum_breakdown(agreement, POOL_T_STRATUM_LABELS)
    breakdown = agreement["stratum_price_breakdown"]
    assert len(breakdown) == 4
    for label in POOL_T_STRATUM_LABELS:
        assert breakdown[label]["price_cents"] == STRATUM_PRICE_CENTS
        assert breakdown[label]["upb_cents"] == 10000050


def test_holdback_is_sized_off_the_per_stratum_purchase_price(
        api: ApiClient) -> None:
    """
    Six percent of the per-stratum purchase price, not of the bid's own value,
    is what the buyer withholds.

    PRD: "The holdback is then sized: `holdback_cents` is `purchase_price_cents` multiplied by `holdback_pct`, divided by 100, rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/purchase_price_rounds_per_stratum_before_summation
    """
    env = build_published_package(api)
    bid = F.submit_bid(api, env["package_id"], env["buyer_id"],
                       env["package_version"], price_bps=118, holdback_pct=6)

    agreement = F.award(api, env["package_id"], bid["id"])

    assert agreement["purchase_price_cents"] == PURCHASE_PRICE_CENTS
    assert agreement["holdback_cents"] == HOLDBACK_CENTS


def test_award_opens_the_holdback_split_wholly_retained(
        api: ApiClient) -> None:
    """
    At award the whole holdback sits retained and the wire is the purchase price
    net of it.

    PRD: "`holdback_retained_cents` is initialised to that figure, `holdback_released_cents` and `holdback_applied_cents` to 0, and `settlement_wire_cents` to `purchase_price_cents` less `holdback_cents`."

    Design: Difficulty/combinatorial_formula/purchase_price_rounds_per_stratum_before_summation
    """
    env = build_published_package(api)
    bid = F.submit_bid(api, env["package_id"], env["buyer_id"],
                       env["package_version"], price_bps=118, holdback_pct=6)

    agreement = F.award(api, env["package_id"], bid["id"])

    assert_holdback_split(agreement, retained=HOLDBACK_CENTS, released=0,
                          applied=0)
    assert_settlement_wire(agreement)
    assert agreement["settlement_wire_cents"] == SETTLEMENT_WIRE_CENTS
    stored = F.read_agreement(api, agreement["id"])
    assert stored["settlement_wire_cents"] == SETTLEMENT_WIRE_CENTS
