"""Formulas whose branches interact.

Three derivations in this domain combine several inputs in a pinned order rather
than adding independent terms: glidepath fit picks a reference pair from
`glidepath_type` and a cost allowance from `construction` before applying two
gaps and a floor (PRD 3.8); the revenue-credit pool floors each fund's accrual
before anything is pooled (PRD 3.8); and a provider's tier is selected from the
gross cost only, with the credit offset gated on the plan's credit balance
(PRD 3.9).  Each test pins one cell of one of those matrices.
"""

from test_helpers.api_client import ApiClient
from test_helpers.assertions import assert_cents, assert_fields, assert_score, assert_status
from test_helpers.constants import accrual_cents
from test_helpers.fixtures import (
    Ctx,
    approve_run_with_motion,
    benchmark_engagement,
    create_engagement,
    create_fund,
    create_levelization_run,
    create_slot,
    create_target_date_fund,
    read_engagement,
    read_fund,
    read_run,
    register_plan,
    seat_fund,
    setup_adopted_ips,
)
from test_helpers.types import (
    AssetClass,
    Construction,
    EngagementStatus,
    FeeCreditTier,
    FundMenuStatus,
    GlidepathType,
    LevelizationMethod,
    LevelizationStatus,
    ProviderRole,
)


def suite_plan(api: ApiClient) -> Ctx:
    """A bare registered plan: a candidate suite's glidepath fit is derived from
    the fund's own fields, so no committee, statement or menu is involved."""
    ctx = Ctx(api)
    ctx.plan = register_plan(api, plan_name="Delta 401(k) Plan", participant_account_count=500)
    return ctx


def test_glidepath_fit_prices_the_construction_allowance_on_a_perfect_shape(
    api: ApiClient,
) -> None:
    """A suite sitting exactly on the THROUGH_RETIREMENT reference scores 100.00
    as CUSTOM and 92.50 as OFF_THE_SHELF, because only the allowance moves.

    Design: Difficulty/combinatorial_formula/glidepath_fit_nonlinear_reference_allowance_matrix
    """
    ctx = suite_plan(api)
    shape = {
        "asset_class_code": AssetClass.TARGET_DATE,
        "gross_expense_ratio_bps": 50,
        "net_expense_ratio_bps": 45,
        "revenue_share_bps": 0,
        "peer_median_expense_bps": 40,
        "track_record_quarters": 20,
        "manager_tenure_quarters": 24,
        "style_drift_r2": 0.9200,
        "plan_assets_cents": 0,
        "is_target_date_suite": True,
        "glidepath_type": GlidepathType.THROUGH_RETIREMENT,
        "equity_at_65_pct": 50.00,
        "landing_point_age": 80,
    }
    create_target_date_fund(
        ctx,
        "custom",
        ticker="TDCTH",
        fund_name="Custom Through Suite 2050",
        share_class_code="INSTITUTIONAL",
        construction=Construction.CUSTOM,
        **shape,
    )
    create_target_date_fund(
        ctx,
        "off_shelf",
        ticker="TDOTH",
        fund_name="Shelf Through Suite 2050",
        share_class_code="R6",
        construction=Construction.OFF_THE_SHELF,
        **shape,
    )

    custom = read_fund(api, ctx.fund("custom")["id"])
    off_shelf = read_fund(api, ctx.fund("off_shelf")["id"])

    # PRD 3.8: the THROUGH_RETIREMENT reference is 50.0 percent equity at 65 and
    # a landing age of 80, so both gaps are zero.  A CUSTOM suite is allowed 45
    # basis points, exactly what this suite costs, so the cost penalty is 0.00.
    assert_score(custom["glidepath_fit_score"], "100.00", "glidepath_fit_score")
    assert_fields(custom, is_target_date_suite=True, menu_status=FundMenuStatus.CANDIDATE)
    # The identical shape read against the 30-basis-point OFF_THE_SHELF allowance
    # loses half of the 15-basis-point excess, that is 7.50 points.
    assert_score(off_shelf["glidepath_fit_score"], "92.50", "glidepath_fit_score")


def test_glidepath_fit_switches_reference_pair_with_the_glidepath_type(
    api: ApiClient,
) -> None:
    """The same 50.00 percent equity and landing age of 80 read against the
    TO_RETIREMENT reference scores 47.50 instead of 100.00.

    Design: Difficulty/combinatorial_formula/glidepath_fit_nonlinear_reference_allowance_matrix
    """
    ctx = suite_plan(api)
    create_target_date_fund(
        ctx,
        "custom_to",
        ticker="TDCTO",
        fund_name="Custom To Suite 2050",
        share_class_code="INSTITUTIONAL",
        asset_class_code=AssetClass.TARGET_DATE,
        gross_expense_ratio_bps=50,
        net_expense_ratio_bps=45,
        revenue_share_bps=0,
        peer_median_expense_bps=40,
        track_record_quarters=20,
        manager_tenure_quarters=24,
        style_drift_r2=0.9200,
        plan_assets_cents=0,
        is_target_date_suite=True,
        glidepath_type=GlidepathType.TO_RETIREMENT,
        construction=Construction.CUSTOM,
        equity_at_65_pct=50.00,
        landing_point_age=80,
    )

    # PRD 3.8: against 35.0 percent and age 65 the equity gap is 15.0 and the
    # landing gap is 15, costing 1.5 * 15.0 = 22.50 and 2.0 * 15 = 30.00 points;
    # the CUSTOM allowance still absorbs the 45 basis points of expense.
    fund = read_fund(api, ctx.fund("custom_to")["id"])
    assert_score(fund["glidepath_fit_score"], "47.50", "glidepath_fit_score")


def test_glidepath_fit_floors_a_hopeless_suite_at_zero(api: ApiClient) -> None:
    """A suite far off the reference and far over its allowance floors at 0.00
    rather than reporting a negative fit.

    Design: Difficulty/combinatorial_formula/glidepath_fit_nonlinear_reference_allowance_matrix
    """
    ctx = suite_plan(api)
    create_target_date_fund(
        ctx,
        "clamped",
        ticker="TDCLP",
        fund_name="Shelf To Suite Clamped",
        share_class_code="INVESTOR",
        asset_class_code=AssetClass.TARGET_DATE,
        gross_expense_ratio_bps=300,
        net_expense_ratio_bps=300,
        revenue_share_bps=0,
        peer_median_expense_bps=40,
        track_record_quarters=20,
        manager_tenure_quarters=24,
        style_drift_r2=0.9200,
        plan_assets_cents=0,
        is_target_date_suite=True,
        glidepath_type=GlidepathType.TO_RETIREMENT,
        construction=Construction.OFF_THE_SHELF,
        equity_at_65_pct=0.00,
        landing_point_age=60,
    )

    # PRD 3.8: equity gap 35.0 costs 52.50, landing gap 5 costs 10.00 and the 270
    # basis points over the 30-basis-point allowance cost 135.00, so the raw value
    # is -97.50 and the floor is applied after the rounding.
    fund = read_fund(api, ctx.fund("clamped")["id"])
    assert_score(fund["glidepath_fit_score"], "0.00", "glidepath_fit_score")


#: Two revenue-sharing funds whose raw accruals both land just off a whole cent:
#: 1000001 * 15 / 10000 = 1500.0015 and 999999 * 15 / 10000 = 1499.9985.  Floored
#: fund by fund they contribute 1500 + 1499 = 2999 cents; flooring the summed raw
#: figure 2999.9999... would instead give 3000.
SHARING_FUNDS = (("lc_a", 1000001, AssetClass.US_LARGE_CAP, "lc"),
                 ("bond", 999999, AssetClass.CORE_BOND, "bond"))
SHARE_BPS = 15
FLOORED_POOL_CENTS = 2999


def accrual_floor_plan(api: ApiClient, participant_account_count: int) -> Ctx:
    """A two-slot menu whose funds each accrue a fraction of a cent too much."""
    ctx = setup_adopted_ips(api, participant_account_count=participant_account_count)
    for index, (fund_key, assets, asset_class, slot_key) in enumerate(SHARING_FUNDS, start=1):
        create_fund(ctx, fund_key, plan_assets_cents=assets, revenue_share_bps=SHARE_BPS)
        create_slot(ctx, slot_key, asset_class, index)
        seat_fund(ctx, slot_key, fund_key)
    ctx.refresh_plan()
    assert_cents(ctx.plan["total_plan_assets_cents"], 2000000, "total_plan_assets_cents")
    return ctx


def eligible_pool_cents(run: dict) -> int:
    """The pool PRD 3.8 pass 1 leaves, and the check that it was floored fund by
    fund rather than once over the total."""
    per_fund = sum(accrual_cents(assets, SHARE_BPS) for _key, assets, _ac, _sk in SHARING_FUNDS)
    assert per_fund == FLOORED_POOL_CENTS, per_fund
    assert run["credit_pool_cents"] <= FLOORED_POOL_CENTS, (
        "PRD 3.8 pass 1 floors each fund's accrual before pooling, so the pool "
        f"cannot exceed {FLOORED_POOL_CENTS}; flooring the summed raw accrual "
        f"would give 3000, and the run reports {run['credit_pool_cents']}"
    )
    return min(run["credit_pool_cents"], per_fund)


def accrual_share_cents(allocated_total: int) -> dict:
    """PRD 3.8 pass 3 shares out an allocated total in proportion to each fund's
    own floored accrual."""
    return {
        fund_key: allocated_total * accrual_cents(assets, SHARE_BPS) // FLOORED_POOL_CENTS
        for fund_key, assets, _ac, _sk in SHARING_FUNDS
    }


def pro_rata_split(pool: int) -> dict:
    """PRD 3.8 pass 2 under PRO_RATA: floor each fund's share of the pool by its
    assets, then hand the leftover cents out largest-assets-first."""
    total_assets = sum(assets for _key, assets, _ac, _sk in SHARING_FUNDS)
    order = sorted(SHARING_FUNDS, key=lambda spec: -spec[1])
    split = {key: pool * assets // total_assets for key, assets, _ac, _sk in order}
    leftover = pool - sum(split.values())
    for position in range(leftover):
        split[order[position % len(order)][0]] += 1
    return split


def line_for(ctx: Ctx, run: dict, fund_key: str) -> dict:
    """The single allocation line written for one seated fund."""
    matching = [
        line for line in run["allocation_lines"] if line["fund_id"] == ctx.fund(fund_key)["id"]
    ]
    assert len(matching) == 1, run["allocation_lines"]
    return matching[0]


def test_per_capita_pool_keeps_each_fund_s_own_floored_accrual(api: ApiClient) -> None:
    """Two funds whose raw accruals are 1500.0015 and 1499.9985 cents pool to
    2,999 cents, not to the 3,000 that flooring the sum would give.

    Design: Difficulty/combinatorial_formula/levelization_accrual_floored_per_fund_before_pooling
    """
    # One participant account divides the pool exactly, so nothing is lost to the
    # per-capita floor and pass 3 can be read directly.
    ctx = accrual_floor_plan(api, participant_account_count=1)
    created = create_levelization_run(
        ctx, quarter_index=0, method=LevelizationMethod.PER_CAPITA, key="per_capita"
    )
    # PRD 3.8 leaves a created run's allocation fields at their declared initial
    # values and makes approval the act that "freezes allocation_lines,
    # per_account_cents, allocated_total_cents and remainder_cents".
    approve_run_with_motion(ctx, created["id"], key="per_capita")
    run = read_run(api, created["id"])

    pool = eligible_pool_cents(run)
    assert_status(run, LevelizationStatus.APPROVED)
    assert_fields(run, method=LevelizationMethod.PER_CAPITA, quarter_index=0)
    assert_cents(run["credit_pool_cents"], pool, "credit_pool_cents")
    assert_cents(run["per_account_cents"], pool, "per_account_cents")
    assert_cents(run["allocated_total_cents"], pool, "allocated_total_cents")
    assert_cents(run["remainder_cents"], 0, "remainder_cents")

    # Each fund is credited exactly the accrual it contributed: 1500 and 1499.
    shares = accrual_share_cents(run["allocated_total_cents"])
    for fund_key, _assets, _asset_class, _slot_key in SHARING_FUNDS:
        assert_cents(
            line_for(ctx, run, fund_key)["allocated_cents"], shares[fund_key], "allocated_cents"
        )
    assert sum(shares.values()) == run["allocated_total_cents"], shares


def test_pro_rata_waterfall_cannot_manufacture_the_lost_cent(api: ApiClient) -> None:
    """The pro-rata waterfall distributes the whole pool, yet the pool is still
    2,999 cents, so the two lines read 1500 and 1499.

    Design: Difficulty/combinatorial_formula/levelization_accrual_floored_per_fund_before_pooling
    """
    ctx = accrual_floor_plan(api, participant_account_count=250)
    created = create_levelization_run(
        ctx, quarter_index=0, method=LevelizationMethod.PRO_RATA, key="pro_rata"
    )
    # PRD 3.8: the three passes land at approval, which freezes what they wrote.
    approve_run_with_motion(ctx, created["id"], key="pro_rata")
    run = read_run(api, created["id"])

    pool = eligible_pool_cents(run)
    assert_status(run, LevelizationStatus.APPROVED)
    assert_fields(run, method=LevelizationMethod.PRO_RATA, per_account_cents=None)
    assert_cents(run["allocated_total_cents"], pool, "allocated_total_cents")
    assert_cents(run["remainder_cents"], 0, "remainder_cents")

    # PRD 3.8: the raw pro-rata shares of 2,999 cents over 1,000,001 and 999,999
    # cents of assets are both 1499, and the single leftover cent goes to the
    # larger fund first, so the lines are 1500 and 1499 and their sum is the pool.
    lines = run["allocation_lines"]
    assert sum(line["allocated_cents"] for line in lines) == pool, lines
    assert all(line["allocated_cents"] >= 0 for line in lines), lines
    expected = pro_rata_split(pool)
    assert_cents(line_for(ctx, run, "lc_a")["allocated_cents"], expected["lc_a"], "allocated_cents")
    assert_cents(line_for(ctx, run, "bond")["allocated_cents"], expected["bond"], "allocated_cents")


def benchmarkable_plan(api: ApiClient) -> Ctx:
    """A plan with 400 participant accounts and 1,000,000.00 of assets in one
    seated fund that shares no revenue, so the credit balance stays at zero."""
    ctx = setup_adopted_ips(api, participant_account_count=400)
    create_fund(ctx, "lc_a", plan_assets_cents=100000000, revenue_share_bps=0)
    create_slot(ctx, "lc", AssetClass.US_LARGE_CAP, 1)
    seat_fund(ctx, "lc", "lc_a")
    ctx.refresh_plan()
    assert_cents(ctx.plan["total_plan_assets_cents"], 100000000, "total_plan_assets_cents")
    # PRD 3.9 pass B applies the tier offset only while this figure is strictly
    # greater than zero.
    assert_cents(ctx.plan["revenue_credit_balance_cents"], 0, "revenue_credit_balance_cents")
    return ctx


def test_benchmarking_takes_the_tier_from_the_gross_cost_and_keeps_the_offset_shut(
    api: ApiClient,
) -> None:
    """A 49 basis-point asset fee plus a 16.00 basis-point head cost is TIER_C on
    the gross, and with no credit balance the total stays at 65.00.

    Design: Difficulty/combinatorial_formula/provider_cost_tier_pinned_pass_order_gross_not_total
    """
    ctx = benchmarkable_plan(api)
    engagement = create_engagement(
        ctx,
        key="recordkeeper",
        provider_name="Northgate Recordkeeping LLC",
        provider_role=ProviderRole.RECORDKEEPER,
        per_head_fee_cents=400,
        asset_based_bps=49,
        benchmark_percentile=50,
        last_rfp_quarter_index=0,
    )
    # PRD 3.9: a new engagement carries no cost picture at all.
    assert_status(engagement, EngagementStatus.PENDING)
    assert_fields(
        engagement,
        gross_cost_bps=None,
        fee_credit_tier=None,
        total_cost_bps=None,
        last_benchmarked_quarter_index=None,
        rfp_required=False,
    )

    benchmark_engagement(ctx, engagement["id"])
    priced = read_engagement(api, engagement["id"])

    # Pass A: 400 cents a head over 400 accounts is 160,000 cents, which against
    # 100,000,000 cents of assets is 16.00 basis points, so the gross is 65.00.
    assert_score(priced["gross_cost_bps"], "65.00", "gross_cost_bps")
    # Pass B reads the tier off that gross figure: 65.00 is above 45.00.  Reading
    # it off the post-offset total of 53.00 would have said TIER_C too, but the
    # offset itself is forced to 0.00 here because the credit balance is zero.
    assert_fields(priced, fee_credit_tier=FeeCreditTier.TIER_C)
    # Pass C therefore leaves the total equal to the gross, not 65.00 - 12.00.
    assert_score(priced["total_cost_bps"], "65.00", "total_cost_bps")
    # 65.00 is strictly above the 60.00 total-cost trigger, and a benchmark that
    # requires a competition carries the engagement past ACTIVE to UNDER_RFP.
    assert_fields(priced, rfp_required=True, last_benchmarked_quarter_index=0)
    assert_status(priced, EngagementStatus.UNDER_RFP)


def test_benchmarking_holds_the_inclusive_tier_a_boundary_on_the_gross_cost(
    api: ApiClient,
) -> None:
    """A 21 basis-point asset fee plus a 4.00 basis-point head cost lands exactly
    on 25.00, which is TIER_A with no offset and no competition.

    Design: Difficulty/combinatorial_formula/provider_cost_tier_pinned_pass_order_gross_not_total
    """
    ctx = benchmarkable_plan(api)
    engagement = create_engagement(
        ctx,
        key="advisor",
        provider_name="Harbourline Advisory Partners",
        provider_role=ProviderRole.ADVISOR,
        per_head_fee_cents=100,
        asset_based_bps=21,
        benchmark_percentile=50,
        last_rfp_quarter_index=0,
    )
    assert_status(engagement, EngagementStatus.PENDING)

    benchmark_engagement(ctx, engagement["id"], key="advisor")
    priced = read_engagement(api, engagement["id"])

    # Pass A: 100 cents a head over 400 accounts is 40,000 cents, that is 4.00
    # basis points, so the gross is exactly 21 + 4.00 = 25.00.
    assert_score(priced["gross_cost_bps"], "25.00", "gross_cost_bps")
    # PRD 3.9: 25.00 is TIER_A because the comparison is inclusive; 25.01 would be
    # TIER_B.  A TIER_A offset is 0.00 whatever the credit balance holds.
    assert_fields(priced, fee_credit_tier=FeeCreditTier.TIER_A)
    assert_score(priced["total_cost_bps"], "25.00", "total_cost_bps")
    # None of the four competition arms fires: the percentile is 50.00, the last
    # competition is seeded at this very quarter and 25.00 is under 60.00.
    assert_fields(priced, rfp_required=False, last_benchmarked_quarter_index=0)
    assert_status(priced, EngagementStatus.ACTIVE)
