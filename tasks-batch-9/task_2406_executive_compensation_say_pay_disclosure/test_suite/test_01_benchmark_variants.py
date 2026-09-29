"""Two-variant derivations: the peer-group benchmark and an award's two valuations.

Screening stores both benchmark variants — the raw median of the peers' disclosed
CEO compensation and the size-adjusted rescaling of the same list — and lets the
group's `benchmark_basis` elect which one drives the target. An award carries the
same duality: the backward-looking realized figure and the forward-looking
realizable figure are computed from one row by two deliberately different rules.
"""

import pytest

from test_helpers import (
    CONSULTANT,
    add_peer_member,
    api_client,
    assert_money,
    certify_metric,
    create_company,
    create_peer_group,
    market_data_payload,
    read_award,
    read_pay_for_performance,
    read_pay_program,
    read_peer_group,
    refresh_market_data,
    screen_peer_group,
    setup_award,
    setup_issuer,
    setup_pay_program,
    submit_metric_result,
    validate_success,
)

FOUR_PEERS = ("BRVO", "CHRL", "DLTA", "ECHO")


# ---------------------------------------------------------------------------
# Local composition helpers (built only from the barrel's atoms)
# ---------------------------------------------------------------------------
def _issuer_with_four_peers() -> dict:
    """ACME as the issuer plus the four canonical candidate peers."""
    env = setup_issuer()
    for ticker in FOUR_PEERS:
        env["peers"][ticker] = create_company(ticker)
    return env


def _draft_group_over_four_peers(env: dict, benchmark_basis: str) -> dict:
    """Open a DRAFT group on the given basis and accept all four peers into it."""
    group = create_peer_group(env["issuer"]["id"], benchmark_basis)
    for ticker in FOUR_PEERS:
        add_peer_member(group["id"], env["peers"][ticker]["id"], "SIZE_MATCH")
    return group


def _four_peer_program_with_two_granted_awards() -> dict:
    """Four-peer approved group, a certified annual-incentive vehicle, two grants.

    The CEO holds an ANNUAL_INCENTIVE opportunity and a 100,000-unit
    LONG_TERM_PSU grant, both still GRANTED when the assertions run.
    """
    env = setup_pay_program(
        metric_curves=("ADJ_EPS_LINEAR", "COST_RATIO_STEP"),
        peer_tickers=FOUR_PEERS,
    )
    env = setup_award(env, "annual_incentive", "ANNUAL_INCENTIVE")
    env = setup_award(env, "psu", "LONG_TERM_PSU")
    for metric, achieved in zip(env["metrics"], (5.50, 0.63)):
        submit_metric_result(metric["id"], achieved)
    for metric in env["metrics"]:
        certify_metric(metric["id"])
    return env


# ---------------------------------------------------------------------------
# Benchmark variants
# ---------------------------------------------------------------------------
def test_raw_and_size_adjusted_variants_both_stored_and_basis_elects_the_target():
    """Screening the same four peers twice stores both variants and elects one.

    The raw list of disclosed compensation is 9,000,000.00 / 12,000,000.00 /
    18,000,000.00 / 24,000,000.00 and nearest-ranks to 12,000,000.00. Rescaling
    the same peers by their clamped issuer-over-peer revenue factors (1.2500,
    0.8333, 0.5000, 1.6667) reorders the list to 12,000,000.00 /
    14,999,400.00 / 15,000,000.00 / 15,000,300.00 and selects 14,999,400.00, so
    the two bases differ by 2,999,400.00 on identical inputs.

    "The `SIZE_ADJUSTED` variant first scales each peer's disclosed compensation
    for the size difference: divide the issuer's revenue by that peer's revenue,
    clamp the quotient to no less than 0.5 and no more than 2.0, round the
    clamped factor half-up to four decimal places, multiply the peer's
    `ceo_tdc_usd` by that rounded factor, and round the product half-up to two
    decimal places."

    Design: Difficulty/dual_variant_calc/raw_median_vs_size_adjusted_benchmark_diverge_on_one_peer_set
    """
    env = _issuer_with_four_peers()
    raw_group = _draft_group_over_four_peers(env, "RAW_MEDIAN")
    adjusted_group = _draft_group_over_four_peers(env, "SIZE_ADJUSTED")

    raw = screen_peer_group(raw_group["id"])
    adjusted = screen_peer_group(adjusted_group["id"])

    assert raw["status"] == "SCREENED"
    assert adjusted["status"] == "SCREENED"
    assert raw["accepted_member_count"] == 4
    assert adjusted["accepted_member_count"] == 4

    # Both variants are always stored, whichever basis the group elected.
    for group in (raw, adjusted):
        assert_money(
            group["benchmark_target_tdc_raw_usd"], 12000000.00, "benchmark_target_tdc_raw_usd"
        )
        assert_money(
            group["benchmark_target_tdc_adjusted_usd"],
            14999400.00,
            "benchmark_target_tdc_adjusted_usd",
        )

    assert_money(raw["benchmark_target_tdc_usd"], 12000000.00, "RAW_MEDIAN benchmark")
    assert_money(adjusted["benchmark_target_tdc_usd"], 14999400.00, "SIZE_ADJUSTED benchmark")
    assert_money(
        adjusted["benchmark_target_tdc_usd"] - raw["benchmark_target_tdc_usd"],
        2999400.00,
        "benchmark divergence between the two bases",
    )


def test_median_uses_mean_of_middles_while_the_benchmark_nearest_ranks_lower():
    """The peer-set median and the benchmark percentile are different methods.

    The four peers' revenues are 6, 8, 12 and 20 billion, so the mean of the two
    middle values gives median_revenue_usd 10,000,000,000.00 rather than the
    8,000,000,000.00 a lower-of-middles selection would return. Over the same
    membership the disclosed compensation list nearest-ranks to 12,000,000.00,
    not to the 15,000,000.00 mean of its own two middle values.

    "For an even count this selects the **lower** of the two middle values, which
    is why the benchmark figure does not in general equal the mean-of-middles
    median used for `median_revenue_usd` — the two computations are deliberately
    different and both are asserted."

    Design: Difficulty/dual_variant_calc/raw_median_vs_size_adjusted_benchmark_diverge_on_one_peer_set
    """
    env = _issuer_with_four_peers()
    group = _draft_group_over_four_peers(env, "RAW_MEDIAN")

    screened = screen_peer_group(group["id"])

    assert_money(screened["median_revenue_usd"], 10000000000.00, "median_revenue_usd")
    assert screened["median_revenue_usd"] != pytest.approx(8000000000.00, abs=0.01)
    assert_money(screened["median_market_cap_usd"], 23000000000.00, "median_market_cap_usd")
    assert_money(screened["size_fit_score"], 100.00, "size_fit_score")

    # The benchmark percentile takes the lower of the two middle values.
    assert_money(
        screened["benchmark_target_tdc_raw_usd"], 12000000.00, "benchmark_target_tdc_raw_usd"
    )
    assert screened["benchmark_target_tdc_raw_usd"] != pytest.approx(15000000.00, abs=0.01)

    readback = read_peer_group(group["id"])
    assert_money(readback["median_revenue_usd"], 10000000000.00, "median_revenue_usd")
    assert_money(
        readback["benchmark_target_tdc_raw_usd"], 12000000.00, "benchmark_target_tdc_raw_usd"
    )


# ---------------------------------------------------------------------------
# Realized versus realizable pay
# ---------------------------------------------------------------------------
def test_realized_and_realizable_totals_diverge_while_both_awards_stay_granted():
    """Nothing delivered means 0.00 realized while the same rows mark to market.

    The annual-incentive opportunity carries the certified 130.00 factor on a
    1,800,000.00 target, and the PSU grant has no metric of its own vehicle, so
    it marks 100,000 units at the refreshed 60.00 share price on the assumed
    100.00 percent of target. Realized therefore totals 0.00 against a
    realizable total of 8,340,000.00.

    "An award still `GRANTED` has a `realized_value_usd` of 0.00, and so does a
    `FORFEITED` one."

    Design: Difficulty/dual_variant_calc/realized_versus_realizable_pay_diverge_on_identical_awards
    """
    env = _four_peer_program_with_two_granted_awards()
    refresh_market_data(env["issuer"]["id"], share_price_usd=60.00)

    annual = read_award(env["awards"]["annual_incentive"]["id"])
    psu = read_award(env["awards"]["psu"]["id"])

    assert annual["status"] == "GRANTED"
    assert psu["status"] == "GRANTED"
    assert_money(annual["certified_factor_pct"], 130.00, "certified_factor_pct")
    assert_money(annual["realized_value_usd"], 0.00, "annual realized_value_usd")
    assert_money(annual["realizable_value_usd"], 2340000.00, "annual realizable_value_usd")
    assert psu["certified_factor_pct"] is None, (
        "a PSU award with no metric of its own vehicle has no certified factor"
    )
    assert_money(psu["realized_value_usd"], 0.00, "psu realized_value_usd")
    assert_money(psu["realizable_value_usd"], 6000000.00, "psu realizable_value_usd")

    program = read_pay_program(env["program"]["id"])
    assert_money(program["realized_pay_total_usd"], 0.00, "realized_pay_total_usd")
    assert_money(program["realizable_pay_total_usd"], 8340000.00, "realizable_pay_total_usd")

    picture = read_pay_for_performance(env["program"]["id"])
    assert_money(picture["realized_pay_total_usd"], 0.00, "realized_pay_total_usd")
    assert_money(picture["realizable_pay_total_usd"], 8340000.00, "realizable_pay_total_usd")
    assert_money(picture["pay_percentile_rank"], 0.00, "pay_percentile_rank")
    assert_money(picture["tsr_percentile_rank"], 30.00, "tsr_percentile_rank")
    assert_money(picture["degree_of_alignment"], 30.00, "degree_of_alignment")
    assert picture["alignment_status"] == "ALIGNED"
    assert picture["accepted_peer_count"] == 4


def test_share_price_refresh_moves_realizable_pay_and_leaves_realized_untouched():
    """A price move re-marks outstanding grants without delivering a dollar.

    At the 50.00 grant price the PSU award is realizable at 5,000,000.00 and the
    program's realizable total is 7,340,000.00; refreshing the share price to
    60.00 lifts those to 6,000,000.00 and 8,340,000.00 while every realized
    figure stays at 0.00.

    "Fourth, independently of the peer-group chain, a changed share price
    re-marks every award of the issuer's programs that is still `GRANTED`,
    rewriting each award's `realizable_value_usd` and then each affected
    program's `realizable_pay_total_usd`."

    Design: Difficulty/dual_variant_calc/realized_versus_realizable_pay_diverge_on_identical_awards
    """
    env = _four_peer_program_with_two_granted_awards()

    psu_before = read_award(env["awards"]["psu"]["id"])
    program_before = read_pay_program(env["program"]["id"])
    assert_money(psu_before["realizable_value_usd"], 5000000.00, "psu realizable before refresh")
    assert_money(psu_before["realized_value_usd"], 0.00, "psu realized before refresh")
    assert_money(
        program_before["realizable_pay_total_usd"], 7340000.00, "realizable total before refresh"
    )
    assert_money(program_before["realized_pay_total_usd"], 0.00, "realized total before refresh")

    response = api_client.refresh_market_data(
        env["issuer"]["id"], market_data_payload(share_price_usd=60.00), CONSULTANT
    )
    validate_success(response, 200)

    psu_after = read_award(env["awards"]["psu"]["id"])
    program_after = read_pay_program(env["program"]["id"])
    assert_money(psu_after["realizable_value_usd"], 6000000.00, "psu realizable after refresh")
    assert_money(psu_after["realized_value_usd"], 0.00, "psu realized after refresh")
    assert_money(
        program_after["realizable_pay_total_usd"], 8340000.00, "realizable total after refresh"
    )
    assert_money(program_after["realized_pay_total_usd"], 0.00, "realized total after refresh")

    # The annual-incentive leg has no share price in its formula at all.
    annual_after = read_award(env["awards"]["annual_incentive"]["id"])
    assert_money(annual_after["realizable_value_usd"], 2340000.00, "annual realizable after refresh")
    assert_money(annual_after["realized_value_usd"], 0.00, "annual realized after refresh")
