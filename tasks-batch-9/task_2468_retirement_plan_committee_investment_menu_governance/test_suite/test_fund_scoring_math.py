"""Composite scoring arithmetic and the watch-list ladder.

These tests exercise the numeric contract of PRD 3.5 (the five component arms,
the pinned rounding order and the single half-up at the end), the eligibility
comparisons of PRD 3.3, and the inclusive thresholds and asymmetric cure band of
the PRD 3.6 ladder.
"""

from test_helpers.api_client import paginate_params
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_capacity_triple,
    assert_fields,
    assert_ratio,
    assert_score,
    assert_status,
    find_by,
    validate_error,
    validate_paginated,
)
from test_helpers.factories import Paths, seat_fund_payload
from test_helpers.fixtures import (
    advance_quarter,
    create_fund,
    create_slot,
    draft_proposal,
    finalize_review,
    open_review,
    present_and_document,
    read_fund,
    read_plan,
    read_proposal,
    read_review,
    read_slot,
    recompute_posture,
    setup_breach_quarter,
    setup_full_menu,
    submit_scorecard,
)
from test_helpers.test_users import auditor_headers, consultant_headers
from test_helpers.types import (
    AssetClass,
    CreditAccrualStatus,
    FundMenuStatus,
    MenuPosture,
    ProposalStatus,
    ReviewStatus,
    ScorecardStatus,
    ShareClass,
    SlotDesignation,
    SlotStatus,
    WatchRecommendation,
    WatchStatus,
)


def test_components_round_before_weighting_and_the_sum_rounds_once(api):
    """A 74.6 basis-point excess and an R-squared one ten-thousandth below the
    floor produce a raw weighted sum of 75.795 that must land on 75.80.

    Design: Corner/calculations/components_are_rounded_before_weighting_and_the_weighted_sum_rounds_half_up_once
    """
    ctx = setup_full_menu(api)
    open_review(ctx, 0)

    scorecard = submit_scorecard(
        ctx,
        "small",
        {
            "trailing_return_3y_bps": 891,
            "trailing_return_5y_bps": 850,
            "benchmark_return_3y_bps": 800,
            "benchmark_return_5y_bps": 800,
            "peer_rank_pct": 26,
            "style_drift_r2": 0.7999,
            "net_expense_ratio_bps": 45,
            "peer_median_expense_bps": 40,
            "manager_tenure_quarters": 20,
            "manager_change_flag": False,
        },
    )

    # 0.6*(891-800) + 0.4*(850-800) = 74.6 bps, half-up to 75.
    assert_score(scorecard["performance_component"], "57.50", "performance_component")
    assert_score(scorecard["peer_component"], "74.00", "peer_component")
    assert_score(scorecard["expense_component"], "90.00", "expense_component")
    # 100.00 - 500 * (0.8000 - 0.7999) is the smallest observable style step.
    assert_score(scorecard["style_component"], "99.95", "style_component")
    assert_score(scorecard["manager_component"], "100.00", "manager_component")
    # 23.000 + 14.800 + 18.000 + 9.995 + 10.000 = 75.795, rounded half up once.
    assert_score(scorecard["composite_score"], "75.80", "composite_score")
    # An R-squared below the floor is a breach on its own (PRD 3.6).
    assert_status(scorecard, WatchRecommendation.WATCH, "watch_recommendation")

    fund = read_fund(api, ctx.fund("small")["id"])
    assert_status(fund, WatchStatus.CLEAR, "watch_status")
    assert fund["latest_composite_score"] is None, fund["latest_composite_score"]

    review = read_review(api, ctx.review["id"])
    assert_status(review, ReviewStatus.SCORING)
    assert_fields(review, submitted_scorecard_count=1)


def test_watch_and_remediation_triggers_are_inclusive_to_the_cent(api):
    """40.00 breaches while 40.04 does not, and 25.00 is remediation-grade while
    25.04 only reaches watch.

    Design: Corner/calculations/watch_ladder_breach_and_remediation_thresholds_are_inclusive_to_the_cent
    """
    ctx = setup_full_menu(api)
    open_review(ctx, 0)

    flat = {
        "peer_rank_pct": 100,
        "style_drift_r2": 0.9200,
        "net_expense_ratio_bps": 90,
        "peer_median_expense_bps": 40,
        "manager_tenure_quarters": 20,
        "benchmark_return_3y_bps": 800,
        "benchmark_return_5y_bps": 800,
    }

    # Excess 0 -> performance 50.00 -> 20.00 + 10.00 + 10.00 = 40.00.
    at_trigger = submit_scorecard(
        ctx,
        "lc_a",
        dict(flat, trailing_return_3y_bps=800, trailing_return_5y_bps=800, manager_change_flag=False),
    )
    # Excess round_half_up(0.4*2) = 1 -> performance 50.10 -> 40.04.
    above_trigger = submit_scorecard(
        ctx,
        "bond",
        dict(flat, trailing_return_3y_bps=800, trailing_return_5y_bps=802, manager_change_flag=False),
    )
    # Excess -225 -> performance 27.50, manager 40.00 -> 11.00 + 10.00 + 4.00 = 25.00.
    at_remediation = submit_scorecard(
        ctx,
        "small",
        dict(flat, trailing_return_3y_bps=425, trailing_return_5y_bps=800, manager_change_flag=True),
    )
    # Excess -224 -> performance 27.60 -> 11.04 + 10.00 + 4.00 = 25.04.
    above_remediation = submit_scorecard(
        ctx,
        "intl",
        dict(flat, trailing_return_3y_bps=430, trailing_return_5y_bps=795, manager_change_flag=True),
    )

    assert_score(at_trigger["composite_score"], "40.00", "composite_score")
    assert_status(at_trigger, WatchRecommendation.WATCH, "watch_recommendation")
    assert_score(above_trigger["composite_score"], "40.04", "composite_score")
    assert_status(above_trigger, WatchRecommendation.NONE, "watch_recommendation")
    assert_score(at_remediation["composite_score"], "25.00", "composite_score")
    assert_status(at_remediation, WatchRecommendation.REMEDIATION, "watch_recommendation")
    assert_score(above_remediation["composite_score"], "25.04", "composite_score")
    assert_status(above_remediation, WatchRecommendation.WATCH, "watch_recommendation")

    # Recommendations stay advisory until the review is finalized (PRD 3.5).
    for key in ("lc_a", "bond", "small", "intl"):
        fund = read_fund(api, ctx.fund(key)["id"])
        assert_status(fund, WatchStatus.CLEAR, "watch_status")
        assert_fields(fund, consecutive_breach_quarters=0)
        assert fund["watch_started_quarter_index"] is None, key

    review = read_review(api, ctx.review["id"])
    assert_status(review, ReviewStatus.SCORING)
    assert_fields(review, submitted_scorecard_count=4)

    plan = read_plan(api, ctx.plan_id)
    assert_status(plan, MenuPosture.OPEN, "menu_posture")
    assert_ratio(plan["at_risk_slot_ratio"], "0.0000", "at_risk_slot_ratio")


def test_manager_change_lowers_the_component_and_widens_the_breach_band(api):
    """The same returns, peer rank, expense and style score 45.00 with a manager
    change and 51.00 without, and only the first is a breach.

    Design: Corner/calculations/manager_change_widens_the_breach_band_by_exactly_the_cure_margin
    """
    ctx = setup_full_menu(api)
    open_review(ctx, 0)

    shared = {
        "trailing_return_3y_bps": 1075,
        "trailing_return_5y_bps": 1075,
        "benchmark_return_3y_bps": 800,
        "benchmark_return_5y_bps": 800,
        "peer_rank_pct": 100,
        "style_drift_r2": 0.9200,
        "net_expense_ratio_bps": 90,
        "peer_median_expense_bps": 40,
        "manager_tenure_quarters": 20,
    }

    changed = submit_scorecard(ctx, "lc_a", dict(shared, manager_change_flag=True))
    unchanged = submit_scorecard(ctx, "bond", dict(shared, manager_change_flag=False))

    # Excess 275 -> performance 77.50 for both rows.
    assert_score(changed["performance_component"], "77.50", "performance_component")
    assert_score(unchanged["performance_component"], "77.50", "performance_component")
    # min(40.00, 2*20) against min(100.00, 40.00 + 3*20).
    assert_score(changed["manager_component"], "40.00", "manager_component")
    assert_score(unchanged["manager_component"], "100.00", "manager_component")
    assert_score(changed["composite_score"], "45.00", "composite_score")
    assert_score(unchanged["composite_score"], "51.00", "composite_score")
    # 45.00 is above the 40.00 trigger but inside trigger plus cure margin.
    assert_status(changed, WatchRecommendation.WATCH, "watch_recommendation")
    assert_status(unchanged, WatchRecommendation.NONE, "watch_recommendation")

    for other in ("peer_component", "expense_component", "style_component"):
        assert changed[other] == unchanged[other], other

    for key in ("lc_a", "bond"):
        assert_status(read_fund(api, ctx.fund(key)["id"]), WatchStatus.CLEAR, "watch_status")


#: A real-assets candidate sitting on every inclusive policy boundary at once:
#: 12 quarters of record, 50 basis points against a cap of floor(40 * 1.25),
#: an R-squared exactly at the 0.8000 floor and no manager change.  PRD 2.9
#: makes `asset_class_code` unique per plan among non-RETIRED slots, so the sixth
#: sleeve has to be an asset class the seeded five do not already occupy.
BOUNDARY_FUND = {
    "ticker": "CAPOK",
    "fund_name": "Boundary Real Assets Institutional",
    "asset_class_code": AssetClass.REAL_ASSETS,
    "share_class_code": ShareClass.INSTITUTIONAL,
    "gross_expense_ratio_bps": 50,
    "net_expense_ratio_bps": 50,
    "revenue_share_bps": 0,
    "peer_median_expense_bps": 40,
    "track_record_quarters": 12,
    "manager_tenure_quarters": 8,
    "manager_change_flag": False,
    "style_drift_r2": 0.8000,
    "plan_assets_cents": 0,
}


def test_a_fund_on_every_inclusive_ips_boundary_may_be_seated(api):
    """50 basis points against a cap of exactly 50, 12 quarters against a
    minimum of 12 and an R-squared exactly at the floor all pass.

    Design: Corner/calculations/ips_selection_criteria_pass_at_every_inclusive_boundary_and_fail_one_bp_past_the_cap
    """
    ctx = setup_full_menu(api)
    extra_slot = create_slot(
        ctx,
        "specialty_real",
        AssetClass.REAL_ASSETS,
        6,
        designation=SlotDesignation.SPECIALTY,
    )
    create_fund(ctx, "cap_ok", **BOUNDARY_FUND)

    seated = api.post(
        Paths.seat_fund(extra_slot["id"]),
        seat_fund_payload(ctx.fund("cap_ok")["id"]),
        consultant_headers(),
    )
    assert seated.status_code == 200, seated.text

    slot = read_slot(api, extra_slot["id"])
    assert_status(slot, SlotStatus.ACTIVE)
    assert_fields(slot, current_fund_id=ctx.fund("cap_ok")["id"], ips_id=ctx.ips_id)

    fund = read_fund(api, ctx.fund("cap_ok")["id"])
    assert_status(fund, FundMenuStatus.ACTIVE, "menu_status")
    assert_status(fund, CreditAccrualStatus.ACCRUING, "credit_accrual_status")

    plan = read_plan(api, ctx.plan_id)
    assert_capacity_triple(plan, occupied=6, reserved=0, available=0)
    assert_fields(plan, menu_slot_capacity=6)


def test_one_bp_past_the_cap_or_one_quarter_short_cannot_be_seated(api):
    """51 basis points against a 50 basis-point cap and 11 quarters against a
    12-quarter minimum are both refused, consuming no capacity.

    Design: Corner/calculations/ips_selection_criteria_pass_at_every_inclusive_boundary_and_fail_one_bp_past_the_cap
    """
    ctx = setup_full_menu(api)
    extra_slot = create_slot(
        ctx,
        "specialty_real",
        AssetClass.REAL_ASSETS,
        6,
        designation=SlotDesignation.SPECIALTY,
    )
    over_cap = create_fund(
        ctx,
        "cap_no",
        **dict(
            BOUNDARY_FUND,
            ticker="CAPNO",
            fund_name="Overpriced Large Cap Investor",
            share_class_code=ShareClass.INVESTOR,
            gross_expense_ratio_bps=51,
            net_expense_ratio_bps=51,
        ),
    )
    short_record = create_fund(
        ctx,
        "trk_no",
        **dict(
            BOUNDARY_FUND,
            ticker="TRKNO",
            fund_name="Short Record Large Cap R6",
            share_class_code=ShareClass.R6,
            gross_expense_ratio_bps=45,
            net_expense_ratio_bps=45,
            track_record_quarters=11,
        ),
    )

    for fund_id in (over_cap["id"], short_record["id"]):
        rejected = api.post(
            Paths.seat_fund(extra_slot["id"]),
            seat_fund_payload(fund_id),
            consultant_headers(),
        )
        validate_error(rejected, ApiErrorId.FUND_FAILS_IPS_CRITERIA, 422)

    slot = read_slot(api, extra_slot["id"])
    assert_status(slot, SlotStatus.EMPTY)
    assert slot["current_fund_id"] is None, slot["current_fund_id"]

    for fund_id in (over_cap["id"], short_record["id"]):
        fund = read_fund(api, fund_id)
        assert_status(fund, FundMenuStatus.CANDIDATE, "menu_status")

    plan = read_plan(api, ctx.plan_id)
    assert_capacity_triple(plan, occupied=5, reserved=0, available=1)


def test_the_five_component_arms_decompose_a_finalized_quarter(api, finalized_quarter):
    """The quarter's five scorecards exercise a positive blend, a below-median
    expense at the cap, a negative excess, a zero excess and a capped tenure.

    Design: Corner/calculations/composite_score_decomposes_into_five_rounded_components_under_the_trailing_variant
    """
    ctx = finalized_quarter

    listed = api.get(
        Paths.SCORECARDS,
        auditor_headers(),
        paginate_params(limit=10, offset=0, review_id=ctx.review["id"]),
    )
    rows, meta = validate_paginated(listed)
    assert meta["total_count"] == 5, meta
    for row in rows:
        assert_status(row, ScorecardStatus.SUBMITTED)

    large_cap = find_by(rows, fund_id=ctx.fund("lc_a")["id"])
    assert_score(large_cap["performance_component"], "58.00", "performance_component")
    assert_score(large_cap["peer_component"], "75.00", "peer_component")
    assert_score(large_cap["expense_component"], "90.00", "expense_component")
    assert_score(large_cap["style_component"], "100.00", "style_component")
    assert_score(large_cap["manager_component"], "100.00", "manager_component")
    assert_score(large_cap["composite_score"], "76.20", "composite_score")
    assert_status(large_cap, WatchRecommendation.NONE, "watch_recommendation")

    bond = find_by(rows, fund_id=ctx.fund("bond")["id"])
    assert_score(bond["performance_component"], "53.80", "performance_component")
    # 25 basis points is below the 30 basis-point median, and the component is
    # capped at 100.00 rather than credited past it.
    assert_score(bond["expense_component"], "100.00", "expense_component")
    assert_score(bond["composite_score"], "75.52", "composite_score")

    small = find_by(rows, fund_id=ctx.fund("small")["id"])
    assert_score(small["performance_component"], "39.20", "performance_component")
    assert_score(small["manager_component"], "82.00", "manager_component")
    assert_score(small["composite_score"], "59.88", "composite_score")

    intl = find_by(rows, fund_id=ctx.fund("intl")["id"])
    assert_score(intl["performance_component"], "50.00", "performance_component")
    assert_score(intl["composite_score"], "72.00", "composite_score")

    tips = find_by(rows, fund_id=ctx.fund("tips")["id"])
    # min(100.00, 40.00 + 3*36) caps at 100.00 instead of reaching 148.00.
    assert_score(tips["manager_component"], "100.00", "manager_component")
    assert_score(tips["composite_score"], "70.00", "composite_score")


#: Quarter-1 measurements that hold a fund's score flat: peer rank 100 and an
#: expense 50 basis points over the median zero those two arms, so the composite
#: moves only with the excess return.
FLAT_Q1_INPUTS = {
    "benchmark_return_3y_bps": 800,
    "benchmark_return_5y_bps": 800,
    "peer_rank_pct": 100,
    "style_drift_r2": 0.9200,
    "net_expense_ratio_bps": 90,
    "peer_median_expense_bps": 40,
    "manager_tenure_quarters": 20,
    "manager_change_flag": False,
}

#: A healthy quarter-1 measurement worth exactly 72.00.
HEALTHY_Q1_INPUTS = {
    "trailing_return_3y_bps": 800,
    "trailing_return_5y_bps": 800,
    "benchmark_return_3y_bps": 800,
    "benchmark_return_5y_bps": 800,
    "peer_rank_pct": 40,
    "style_drift_r2": 0.9200,
    "net_expense_ratio_bps": 40,
    "peer_median_expense_bps": 40,
    "manager_tenure_quarters": 30,
    "manager_change_flag": False,
}


def test_a_second_breach_escalates_while_a_deep_one_recommends_termination(api):
    """A watched fund breaching again at 40.00 escalates to remediation, and a
    fund already in remediation scoring 25.00 reaches the grace count and
    recommends termination.

    Design: Corner/calculations/a_second_consecutive_breach_escalates_to_remediation_and_a_deep_one_terminates
    """
    ctx = setup_breach_quarter(api)
    quarter_zero_review_id = ctx.review["id"]
    finalize_review(ctx)
    advance_quarter(ctx)

    open_review(ctx, 1)
    # Excess 0 -> performance 50.00 -> 20.00 + 10.00 + 10.00 = 40.00.
    second_breach = submit_scorecard(
        ctx,
        "small",
        dict(FLAT_Q1_INPUTS, trailing_return_3y_bps=800, trailing_return_5y_bps=800),
    )
    # Excess -225 -> performance 27.50, manager 40.00 -> 11.00 + 10.00 + 4.00 = 25.00.
    deep_breach = submit_scorecard(
        ctx,
        "intl",
        dict(
            FLAT_Q1_INPUTS,
            trailing_return_3y_bps=425,
            trailing_return_5y_bps=800,
            manager_change_flag=True,
        ),
    )

    plan = read_plan(api, ctx.plan_id)
    assert_fields(plan, fiscal_quarter_index=1)
    assert_status(read_review(api, quarter_zero_review_id), ReviewStatus.FINALIZED)

    assert_score(second_breach["composite_score"], "40.00", "composite_score")
    assert_status(second_breach, WatchRecommendation.REMEDIATION, "watch_recommendation")
    assert_score(deep_breach["composite_score"], "25.00", "composite_score")
    assert_status(deep_breach, WatchRecommendation.TERMINATE, "watch_recommendation")

    # Nothing is applied to the funds until this review is finalized.
    assert_status(read_fund(api, ctx.fund("small")["id"]), WatchStatus.WATCH, "watch_status")
    assert_status(
        read_fund(api, ctx.fund("intl")["id"]), WatchStatus.REMEDIATION, "watch_status"
    )

    review = read_review(api, ctx.review["id"])
    assert_status(review, ReviewStatus.SCORING)
    assert_fields(review, ips_id=ctx.ips_id, reopen_count=0)


def test_exactly_fifty_does_not_cure_but_fifty_and_four_cents_does(api):
    """A watched fund scoring exactly 50.00 stays watched while a fund in
    remediation scoring 50.04 clears in one hop, relaxing the posture and
    releasing the blocked proposal.

    Design: Corner/calculations/cure_needs_a_score_strictly_above_the_trigger_plus_margin_so_50_00_does_not_cure
    """
    ctx = setup_breach_quarter(api)
    create_fund(
        ctx,
        "small_b",
        ticker="SMLVB",
        fund_name="Second Summit Small Cap Value R6",
        asset_class_code=AssetClass.US_SMALL_CAP,
        share_class_code=ShareClass.R6,
        gross_expense_ratio_bps=40,
        net_expense_ratio_bps=40,
        revenue_share_bps=0,
        peer_median_expense_bps=55,
        track_record_quarters=24,
        manager_tenure_quarters=12,
        manager_change_flag=False,
        style_drift_r2=0.8800,
        plan_assets_cents=0,
    )
    proposal = draft_proposal(ctx, "small", "small", "small_b", key="prop_small")

    finalize_review(ctx)
    # Two of five slots at risk blocks the small-cap proposal (PRD 3.5 hop 4).
    assert_status(read_proposal(api, proposal["id"]), ProposalStatus.BLOCKED)
    advance_quarter(ctx)

    open_review(ctx, 1)
    # Excess 250 -> performance 75.00 -> 30.00 + 10.00 + 10.00 = 50.00.
    no_cure = submit_scorecard(
        ctx,
        "small",
        dict(FLAT_Q1_INPUTS, trailing_return_3y_bps=1050, trailing_return_5y_bps=1050),
    )
    # Excess 251 -> performance 75.10 -> 30.04 + 10.00 + 10.00 = 50.04.
    cured = submit_scorecard(
        ctx,
        "intl",
        dict(FLAT_Q1_INPUTS, trailing_return_3y_bps=1055, trailing_return_5y_bps=1045),
    )
    for key in ("lc_a", "bond", "tips"):
        submit_scorecard(ctx, key, dict(HEALTHY_Q1_INPUTS))

    present_and_document(
        ctx,
        meeting_date="2026-11-09",
        minutes_doc_ref="MIN-2026-Q1-001",
        quarter_index=1,
    )
    finalize_review(ctx)
    recompute_posture(ctx)

    assert_score(no_cure["composite_score"], "50.00", "composite_score")
    assert_status(no_cure, WatchRecommendation.NONE, "watch_recommendation")
    assert_score(cured["composite_score"], "50.04", "composite_score")
    assert_status(cured, WatchRecommendation.NONE, "watch_recommendation")

    still_watched = read_fund(api, ctx.fund("small")["id"])
    assert_status(still_watched, WatchStatus.WATCH, "watch_status")
    assert_fields(
        still_watched,
        watch_started_quarter_index=0,
        consecutive_breach_quarters=1,
        last_scored_quarter_index=1,
    )
    assert_score(still_watched["latest_composite_score"], "50.00", "latest_composite_score")

    # REMEDIATION clears in a single hop, never by way of WATCH.
    clear_again = read_fund(api, ctx.fund("intl")["id"])
    assert_status(clear_again, WatchStatus.CLEAR, "watch_status")
    assert_fields(
        clear_again,
        consecutive_breach_quarters=0,
        last_scored_quarter_index=1,
        watch_status_before_last_review=WatchStatus.REMEDIATION,
    )
    assert clear_again["watch_started_quarter_index"] is None, clear_again
    assert_score(clear_again["latest_composite_score"], "50.04", "latest_composite_score")

    small_slot = read_slot(api, ctx.slot("small")["id"])
    assert_status(small_slot, SlotStatus.AT_RISK)
    assert_fields(small_slot, at_risk_since_quarter_index=0)
    intl_slot = read_slot(api, ctx.slot("intl")["id"])
    assert_status(intl_slot, SlotStatus.ACTIVE)
    assert intl_slot["at_risk_since_quarter_index"] is None, intl_slot

    plan = read_plan(api, ctx.plan_id)
    # One of five slots at risk is below the 0.2500 rung.
    assert_ratio(plan["at_risk_slot_ratio"], "0.2000", "at_risk_slot_ratio")
    assert_status(plan, MenuPosture.OPEN, "menu_posture")

    released = read_proposal(api, proposal["id"])
    assert_status(released, ProposalStatus.DRAFT)
    assert released["pre_block_status"] is None, released["pre_block_status"]

    review = read_review(api, ctx.review["id"])
    assert_status(review, ReviewStatus.FINALIZED)
    # A cure is not an addition to the watch list.
    assert_fields(review, watch_additions_count=0)
