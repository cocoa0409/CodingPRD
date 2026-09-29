"""Menu posture ratios, glidepath fit, provider cost passes and menu capacity.

These tests exercise the derived arithmetic that governs the menu: the at-risk
ratio and its posture thresholds (PRD 2.10), the glidepath fit formula and the
deterministic qualified-default selector (PRD 3.8), the three provider-cost
passes of PRD 3.9, and the capacity triple of PRD 2.10 as a reservation is
taken, refused and released.
"""

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_capacity_triple,
    assert_cents,
    assert_fields,
    assert_ratio,
    assert_score,
    assert_status,
    validate_error,
    validate_success,
)
from test_helpers.factories import (
    Paths,
    proposal_payload,
    seat_fund_payload,
    target_date_selection_payload,
)
from test_helpers.fixtures import (
    approve_proposal,
    benchmark_engagement,
    create_engagement,
    create_fund,
    create_slot,
    create_target_date_fund,
    draft_proposal,
    finalize_review,
    hold_meeting_and_carry_motion,
    read_engagement,
    read_fund,
    read_motion,
    read_plan,
    read_proposal,
    read_slot,
    seat_fund,
    select_target_date_suite,
    setup_breach_quarter,
    setup_full_menu,
    setup_governed_plan,
    setup_qdia_candidates,
    submit_proposal,
)
from test_helpers.test_users import consultant_headers, recordkeeper_headers, sponsor_headers
from test_helpers.types import (
    AssetClass,
    Construction,
    CreditAccrualStatus,
    EngagementStatus,
    FeeCreditTier,
    FundMenuStatus,
    GlidepathType,
    MenuPosture,
    MotionStatus,
    MotionSubjectType,
    ProposalStatus,
    ProviderRole,
    ShareClass,
    SlotDesignation,
    SlotStatus,
    WatchStatus,
)


# --------------------------------------------------------------------------
# PRD 2.10: the at-risk ratio and its posture thresholds
# --------------------------------------------------------------------------


def test_retiring_a_healthy_slot_lifts_the_ratio_to_one_half_and_freezes_the_menu(api):
    """Retiring one healthy slot shrinks the live-menu denominator from five to
    four, which lifts the at-risk ratio from 0.4000 to exactly 0.5000 and
    freezes the menu against any further replacement.

    Design: Corner/calculations/menu_posture_freezes_at_exactly_one_half_and_the_freeze_blocks_new_proposals
    """
    ctx = setup_breach_quarter(api)
    create_fund(
        ctx,
        "small_b",
        ticker="SMVGX",
        fund_name="Summit Small Cap Value Institutional",
        asset_class_code=AssetClass.US_SMALL_CAP,
        share_class_code=ShareClass.INSTITUTIONAL,
        gross_expense_ratio_bps=52,
        net_expense_ratio_bps=52,
        revenue_share_bps=0,
        peer_median_expense_bps=55,
        track_record_quarters=36,
        manager_tenure_quarters=20,
        style_drift_r2=0.9200,
        plan_assets_cents=0,
    )
    pending = draft_proposal(ctx, "small", "small", "small_b", key="small")

    finalize_review(ctx)
    ctx.refresh_plan()
    # Two of five live slots are at risk after the breaching quarter.
    assert_ratio(ctx.plan["at_risk_slot_ratio"], "0.4000", "at_risk_slot_ratio")
    assert_status(ctx.plan, MenuPosture.RESTRICTED, "menu_posture")
    blocked = read_proposal(ctx.client, pending["id"])
    assert_status(blocked, ProposalStatus.BLOCKED)
    assert_fields(blocked, pre_block_status=ProposalStatus.DRAFT)

    retired = validate_success(
        ctx.client.post(Paths.slot_retire(ctx.slot("tips")["id"]), {}, sponsor_headers())
    )
    assert_status(retired, SlotStatus.RETIRED)
    # The retired slot keeps its occupant for audit while releasing capacity.
    assert retired["current_fund_id"] == ctx.fund("tips")["id"]
    vacated_fund = read_fund(ctx.client, ctx.fund("tips")["id"])
    assert_fields(
        vacated_fund,
        menu_status=FundMenuStatus.PENDING_REMOVAL,
        watch_status=WatchStatus.CLEAR,
    )

    frozen_plan = ctx.refresh_plan()
    # 2 at-risk slots over a denominator of 4 is exactly the freeze threshold.
    assert_ratio(frozen_plan["at_risk_slot_ratio"], "0.5000", "at_risk_slot_ratio")
    assert_status(frozen_plan, MenuPosture.FROZEN, "menu_posture")
    assert_capacity_triple(frozen_plan, occupied=4, reserved=0, available=2)

    version_before = frozen_plan["version"]
    refused = ctx.client.post(
        Paths.REPLACEMENTS,
        proposal_payload(
            ctx.plan_id,
            ctx.slot("lc")["id"],
            ctx.fund("lc_a")["id"],
            ctx.fund("lc_b")["id"],
            version_before,
        ),
        consultant_headers(),
    )
    validate_error(refused, ApiErrorId.MENU_FROZEN, 409)
    assert read_plan(ctx.client, ctx.plan_id)["version"] == version_before

    still_blocked = read_proposal(ctx.client, pending["id"])
    assert_status(still_blocked, ProposalStatus.BLOCKED)
    assert_fields(still_blocked, pre_block_status=ProposalStatus.DRAFT)


# --------------------------------------------------------------------------
# PRD 3.8: glidepath fit
# --------------------------------------------------------------------------


def test_glidepath_fit_prices_the_same_three_inputs_against_four_reference_pairs(api):
    """The same 50 percent equity at 65, landing age 80 and 45 basis points
    score 100.00, 92.50, 47.50 and 40.00 across the four combinations of
    glidepath type and construction.

    Design: Corner/calculations/glidepath_fit_prices_the_same_three_inputs_four_different_ways
    """
    ctx = setup_full_menu(api)

    # THROUGH_RETIREMENT reference 50.0 / 80, CUSTOM allowance 45 bps.
    perfect = read_fund(ctx.client, ctx.fund("td_thru")["id"])
    assert_score(perfect["glidepath_fit_score"], "100.00", "glidepath_fit_score")

    # Same shape read as OFF_THE_SHELF: allowance 30, so half of the 15 bps
    # excess is a 7.50 point cost penalty.
    off_the_shelf = create_target_date_fund(
        ctx,
        "td_off_shelf_pair",
        ticker="TDOTS",
        fund_name="Trellis Through Retirement Off The Shelf",
        glidepath_type=GlidepathType.THROUGH_RETIREMENT,
        construction=Construction.OFF_THE_SHELF,
        equity_at_65_pct=50.00,
        landing_point_age=80,
    )
    assert_score(off_the_shelf["glidepath_fit_score"], "92.50", "glidepath_fit_score")

    # TO_RETIREMENT reference 35.0 / 65: an equity gap of 15 costs 22.50 and a
    # landing gap of 15 costs 30.00.
    to_retirement = create_target_date_fund(
        ctx,
        "td_to_custom",
        ticker="TDTOR",
        fund_name="Trellis To Retirement Custom",
        glidepath_type=GlidepathType.TO_RETIREMENT,
        construction=Construction.CUSTOM,
        equity_at_65_pct=50.00,
        landing_point_age=80,
    )
    assert_score(to_retirement["glidepath_fit_score"], "47.50", "glidepath_fit_score")

    # Both penalties at once: 100.00 - 22.50 - 30.00 - 7.50.
    to_off_the_shelf = create_target_date_fund(
        ctx,
        "td_to_off_shelf",
        ticker="TDOTR",
        fund_name="Trellis To Retirement Off The Shelf",
        glidepath_type=GlidepathType.TO_RETIREMENT,
        construction=Construction.OFF_THE_SHELF,
        equity_at_65_pct=50.00,
        landing_point_age=80,
    )
    assert_score(to_off_the_shelf["glidepath_fit_score"], "40.00", "glidepath_fit_score")


def test_a_negative_glidepath_fit_floors_at_zero_and_a_cheaper_expense_repairs_it(api):
    """A suite that misses every reference and costs 200 basis points scores a
    raw negative that floors at 0.00, and dropping a suite's net expense to its
    allowance lifts its fit back to a perfect 100.00.

    Design: Corner/calculations/glidepath_fit_prices_the_same_three_inputs_four_different_ways
    """
    ctx = setup_full_menu(api)

    # 100.00 - 1.5*35 - 2.0*30 - (200-30)/2 = -97.50 before the floor.
    floored = create_target_date_fund(
        ctx,
        "td_floor",
        ticker="TDFLR",
        fund_name="Farshore Mispriced To Retirement Suite",
        share_class_code=ShareClass.INVESTOR,
        glidepath_type=GlidepathType.TO_RETIREMENT,
        construction=Construction.OFF_THE_SHELF,
        equity_at_65_pct=0.00,
        landing_point_age=95,
        gross_expense_ratio_bps=200,
        net_expense_ratio_bps=200,
    )
    assert_score(floored["glidepath_fit_score"], "0.00", "glidepath_fit_score")

    off_the_shelf = create_target_date_fund(
        ctx,
        "td_off_shelf_pair",
        ticker="TDOTS",
        fund_name="Trellis Through Retirement Off The Shelf",
        glidepath_type=GlidepathType.THROUGH_RETIREMENT,
        construction=Construction.OFF_THE_SHELF,
        equity_at_65_pct=50.00,
        landing_point_age=80,
    )
    assert_score(off_the_shelf["glidepath_fit_score"], "92.50", "glidepath_fit_score")

    repaired = validate_success(
        ctx.client.patch(
            Paths.fund(off_the_shelf["id"]),
            {"net_expense_ratio_bps": 30},
            recordkeeper_headers(),
        )
    )
    # Net expense exactly equal to the allowance is a cost penalty of 0.00.
    assert_score(repaired["glidepath_fit_score"], "100.00", "glidepath_fit_score")
    assert_fields(
        repaired,
        net_expense_ratio_bps=30,
        menu_status=FundMenuStatus.CANDIDATE,
        watch_status=WatchStatus.CLEAR,
    )
    assert_cents(
        ctx.refresh_plan()["total_plan_assets_cents"],
        1200000000,
        "total_plan_assets_cents",
    )


# --------------------------------------------------------------------------
# PRD 3.8: the qualified default selector
# --------------------------------------------------------------------------


def test_the_default_selector_refuses_a_suite_that_loses_the_ticker_tiebreak(api):
    """Two suites tie on fit, expense and track record, so the alphabetically
    later ticker is not the winner and naming it changes nothing.

    Design: Corner/calculations/the_qdia_selector_filters_on_track_record_then_breaks_a_three_way_tie_on_ticker
    """
    ctx = setup_qdia_candidates(api)
    tie = ctx.fund("td_tie")
    thru = ctx.fund("td_thru")
    # The two leaders are indistinguishable on every ordering key but ticker.
    assert_score(tie["glidepath_fit_score"], "100.00", "glidepath_fit_score")
    assert_score(thru["glidepath_fit_score"], "100.00", "glidepath_fit_score")
    assert_fields(tie, net_expense_ratio_bps=45, track_record_quarters=40)
    assert_fields(thru, net_expense_ratio_bps=45, track_record_quarters=40)
    # The cheapest suite is disqualified by the twelve-quarter floor.
    assert_fields(ctx.fund("td_cheap"), net_expense_ratio_bps=20, track_record_quarters=11)

    motion = hold_meeting_and_carry_motion(
        ctx,
        MotionSubjectType.TARGET_DATE_SELECTION,
        tie["id"],
        meeting_date="2026-08-17",
        minutes_doc_ref="MIN-2026-Q0-TDS",
        key="tie",
    )
    refused = ctx.client.post(
        Paths.target_date_selection(tie["id"]),
        target_date_selection_payload(motion["id"], GlidepathType.THROUGH_RETIREMENT),
        ctx.chair,
    )
    validate_error(refused, ApiErrorId.INVALID_REQUEST, 400)

    qdia_slot = read_slot(ctx.client, ctx.slot("qdia")["id"])
    assert_status(qdia_slot, SlotStatus.EMPTY)
    assert qdia_slot["current_fund_id"] is None
    assert_fields(
        read_fund(ctx.client, tie["id"]),
        menu_status=FundMenuStatus.CANDIDATE,
        credit_accrual_status=CreditAccrualStatus.NOT_ACCRUING,
        qdia_flag=False,
    )
    assert_capacity_triple(ctx.refresh_plan(), occupied=5, reserved=0, available=1)
    assert_status(read_motion(ctx.client, motion["id"]), MotionStatus.CARRIED)


def test_the_winning_suite_takes_the_last_menu_position_and_the_losers_stay_candidates(api):
    """Selecting the ticker-first suite of the tied pair seats it in the
    qualified default slot, filling the sixth and last menu position while the
    three losing suites remain candidates.

    Design: Corner/calculations/the_qdia_selector_filters_on_track_record_then_breaks_a_three_way_tie_on_ticker
    """
    ctx = setup_qdia_candidates(api)
    winner = ctx.fund("td_thru")
    motion = hold_meeting_and_carry_motion(
        ctx,
        MotionSubjectType.TARGET_DATE_SELECTION,
        winner["id"],
        meeting_date="2026-08-17",
        minutes_doc_ref="MIN-2026-Q0-TDS",
        key="tds",
    )
    select_target_date_suite(ctx, "td_thru", motion["id"])

    seated = read_fund(ctx.client, winner["id"])
    assert_fields(
        seated,
        menu_status=FundMenuStatus.ACTIVE,
        credit_accrual_status=CreditAccrualStatus.ACCRUING,
        qdia_flag=True,
    )
    qdia_slot = read_slot(ctx.client, ctx.slot("qdia")["id"])
    assert_status(qdia_slot, SlotStatus.ACTIVE)
    assert qdia_slot["current_fund_id"] == winner["id"]

    for key in ("td_tie", "td_cheap", "td_off_shelf"):
        loser = read_fund(ctx.client, ctx.fund(key)["id"])
        assert_fields(
            loser,
            menu_status=FundMenuStatus.CANDIDATE,
            credit_accrual_status=CreditAccrualStatus.NOT_ACCRUING,
            qdia_flag=False,
        )

    plan = ctx.refresh_plan()
    assert_capacity_triple(plan, occupied=6, reserved=0, available=0)
    assert_ratio(plan["at_risk_slot_ratio"], "0.0000", "at_risk_slot_ratio")
    assert_status(plan, MenuPosture.OPEN, "menu_posture")


# --------------------------------------------------------------------------
# PRD 3.9: the three provider-cost passes
# --------------------------------------------------------------------------


def test_the_credit_tier_reads_only_the_gross_cost_across_the_whole_ladder(api):
    """Four engagements on the same 1,200-account, 12,000,000.00-dollar plan
    land on 25.00, 25.01, 45.00 and 70.00 basis points of gross cost, and the
    tier boundaries are inclusive at both 25.00 and 45.00.

    Design: Corner/calculations/provider_cost_passes_run_a_then_b_then_c_and_the_tier_never_reads_the_total
    """
    ctx = setup_full_menu(api)
    plan = ctx.refresh_plan()
    assert_cents(plan["total_plan_assets_cents"], 1200000000, "total_plan_assets_cents")
    assert plan["participant_account_count"] == 1200
    # With no credit balance the offset is never applied, so the total equals
    # the gross for every tier.
    assert_cents(plan["revenue_credit_balance_cents"], 0, "revenue_credit_balance_cents")

    ladder = (
        ("recordkeeper", ProviderRole.RECORDKEEPER, "Northwind Recordkeeping LLC", 1500, 10, 60,
         "25.00", FeeCreditTier.TIER_A, False, EngagementStatus.ACTIVE),
        ("advisor", ProviderRole.ADVISOR, "Cardinal Retirement Advisors", 1501, 10, 60,
         "25.01", FeeCreditTier.TIER_B, False, EngagementStatus.ACTIVE),
        ("auditor", ProviderRole.AUDITOR, "Halstead Plan Audit Group", 3000, 15, 74,
         "45.00", FeeCreditTier.TIER_B, False, EngagementStatus.ACTIVE),
        ("custodian", ProviderRole.CUSTODIAN, "Meridian Trust Custody", 6000, 10, 60,
         "70.00", FeeCreditTier.TIER_C, True, EngagementStatus.UNDER_RFP),
    )
    for key, role, name, per_head, asset_bps, percentile, expected, tier, rfp, status in ladder:
        fresh = create_engagement(
            ctx,
            key=key,
            provider_role=role,
            provider_name=name,
            per_head_fee_cents=per_head,
            asset_based_bps=asset_bps,
            benchmark_percentile=percentile,
        )
        assert_fields(
            fresh,
            status=EngagementStatus.PENDING,
            gross_cost_bps=None,
            total_cost_bps=None,
            fee_credit_tier=None,
            last_benchmarked_quarter_index=None,
            rfp_required=False,
        )
        benchmarked = benchmark_engagement(ctx, fresh["id"], key=key)
        assert_score(benchmarked["gross_cost_bps"], expected, "gross_cost_bps")
        assert_score(benchmarked["total_cost_bps"], expected, "total_cost_bps")
        assert_fields(
            benchmarked,
            fee_credit_tier=tier,
            rfp_required=rfp,
            status=status,
            last_benchmarked_quarter_index=0,
        )


def test_a_repeat_benchmark_in_the_same_quarter_and_an_assetless_plan_are_both_refused(api):
    """A second benchmark inside the same fiscal quarter is refused as already
    current, and a plan holding no assets cannot divide the per-head fee at all.

    Design: Corner/calculations/provider_cost_passes_run_a_then_b_then_c_and_the_tier_never_reads_the_total
    """
    ctx = setup_full_menu(api)
    engagement = create_engagement(ctx)
    # 4200 cents per head over 1200 accounts is 42.00 bps, plus 8 asset-based.
    benchmarked = benchmark_engagement(ctx, engagement["id"])
    assert_score(benchmarked["gross_cost_bps"], "50.00", "gross_cost_bps")
    assert_score(benchmarked["total_cost_bps"], "50.00", "total_cost_bps")
    assert_fields(
        benchmarked,
        fee_credit_tier=FeeCreditTier.TIER_C,
        status=EngagementStatus.ACTIVE,
        rfp_required=False,
        last_benchmarked_quarter_index=0,
    )

    repeat = ctx.client.post(
        Paths.engagement_benchmark(engagement["id"]), {}, consultant_headers()
    )
    validate_error(repeat, ApiErrorId.BENCHMARK_ALREADY_CURRENT, 409)
    unchanged = read_engagement(ctx.client, engagement["id"])
    assert_score(unchanged["gross_cost_bps"], "50.00", "gross_cost_bps")
    assert_fields(
        unchanged, status=EngagementStatus.ACTIVE, last_benchmarked_quarter_index=0
    )

    bare = setup_governed_plan(
        api,
        plan_name="Farshore Logistics 401(k) Plan",
        plan_sponsor_name="Farshore Logistics Inc.",
    )
    assert_cents(bare.plan["total_plan_assets_cents"], 0, "total_plan_assets_cents")
    assetless = create_engagement(bare, key="assetless")
    refused = ctx.client.post(
        Paths.engagement_benchmark(assetless["id"]), {}, consultant_headers()
    )
    validate_error(refused, ApiErrorId.NO_PLAN_ASSETS, 422)
    assert_fields(
        read_engagement(bare.client, assetless["id"]),
        status=EngagementStatus.PENDING,
        gross_cost_bps=None,
        total_cost_bps=None,
        fee_credit_tier=None,
        last_benchmarked_quarter_index=None,
    )


# --------------------------------------------------------------------------
# PRD 2.10 and 3.7: the capacity triple through reserve, refusal and release
# --------------------------------------------------------------------------


def test_a_reservation_blocks_the_last_seat_until_it_is_rescinded_exactly(api):
    """An approved replacement reserves the one free position, which starves a
    seating attempt, and rescinding the approval restores the triple exactly so
    the sixth position can be filled.

    Design: Corner/calculations/the_capacity_triple_sums_to_six_through_reserve_block_and_exact_restoration
    """
    ctx = setup_full_menu(api)
    emerging = create_fund(
        ctx,
        "em",
        ticker="EMGIX",
        fund_name="Eastgate Emerging Markets Institutional",
        asset_class_code=AssetClass.EMERGING_MKTS,
        share_class_code=ShareClass.INSTITUTIONAL,
        gross_expense_ratio_bps=42,
        net_expense_ratio_bps=42,
        revenue_share_bps=0,
        peer_median_expense_bps=45,
        track_record_quarters=40,
        manager_tenure_quarters=22,
        style_drift_r2=0.9100,
        plan_assets_cents=0,
    )
    spare = create_slot(
        ctx,
        "em",
        AssetClass.EMERGING_MKTS,
        6,
        designation=SlotDesignation.SPECIALTY,
    )
    assert_status(spare, SlotStatus.EMPTY)
    # An empty slot consumes no position: five occupied, one still available.
    assert_capacity_triple(ctx.refresh_plan(), occupied=5, reserved=0, available=1)

    proposal = draft_proposal(ctx, "lc", "lc_a", "lc_b", key="lc")
    submit_proposal(ctx, proposal["id"], key="lc")
    motion = hold_meeting_and_carry_motion(
        ctx,
        MotionSubjectType.FUND_REPLACEMENT,
        proposal["id"],
        meeting_date="2026-08-17",
        minutes_doc_ref="MIN-2026-Q0-REP",
        key="replacement",
    )
    approved = approve_proposal(ctx, proposal["id"], motion["id"], key="lc")
    assert_status(approved, ProposalStatus.APPROVED)
    assert approved["approving_motion_id"] == motion["id"]
    assert_status(read_slot(ctx.client, ctx.slot("lc")["id"]), SlotStatus.PENDING_REPLACEMENT)
    # The approval moves the free position into the reserved column.
    assert_capacity_triple(ctx.refresh_plan(), occupied=5, reserved=1, available=0)

    starved = ctx.client.post(
        Paths.seat_fund(spare["id"]),
        seat_fund_payload(emerging["id"]),
        consultant_headers(),
    )
    validate_error(starved, ApiErrorId.MENU_CAPACITY_EXHAUSTED, 409)
    assert_status(read_slot(ctx.client, spare["id"]), SlotStatus.EMPTY)
    assert_fields(read_fund(ctx.client, emerging["id"]), menu_status=FundMenuStatus.CANDIDATE)
    assert_capacity_triple(ctx.refresh_plan(), occupied=5, reserved=1, available=0)

    rescinded = validate_success(
        ctx.client.post(
            Paths.proposal_rescind(proposal["id"]),
            {"reason": "The committee frees the reserved position for the new sleeve."},
            ctx.chair,
        )
    )
    assert_status(rescinded, ProposalStatus.UNDER_REVIEW)
    assert rescinded["approving_motion_id"] is None
    # The outgoing slot was CLEAR, so it returns to ACTIVE rather than AT_RISK.
    assert_status(read_slot(ctx.client, ctx.slot("lc")["id"]), SlotStatus.ACTIVE)
    assert_capacity_triple(ctx.refresh_plan(), occupied=5, reserved=0, available=1)

    seated = seat_fund(ctx, "em", "em")
    assert_status(seated, SlotStatus.ACTIVE)
    assert seated["current_fund_id"] == emerging["id"]
    assert_fields(
        read_fund(ctx.client, emerging["id"]),
        menu_status=FundMenuStatus.ACTIVE,
        credit_accrual_status=CreditAccrualStatus.ACCRUING,
        qdia_flag=False,
    )
    final_plan = ctx.refresh_plan()
    assert_capacity_triple(final_plan, occupied=6, reserved=0, available=0)
    assert_cents(final_plan["total_plan_assets_cents"], 1200000000, "total_plan_assets_cents")
    assert_status(read_motion(ctx.client, motion["id"]), MotionStatus.CARRIED)
