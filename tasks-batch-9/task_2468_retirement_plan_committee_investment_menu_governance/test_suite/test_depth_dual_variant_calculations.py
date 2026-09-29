"""The same inputs priced two ways.

Three calculations in this domain carry a variant switch: the composite score is
blended from the trailing pairs or from the since-watch window (PRD 3.5), a fee
levelization run splits its pool per participant account or by fund assets
(PRD 3.8), and a motion tallies support over the ballots cast or over the
non-recused eligible body (PRD 3.4).  Each test below pins one side of one of
those switches to the number the PRD derives, so that a run of the other branch
on the identical row would be visible.
"""

from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_cents,
    assert_fields,
    assert_ratio,
    assert_score,
    assert_status,
    get_success_data,
)
from test_helpers.constants import accrual_cents
from test_helpers.factories import Paths
from test_helpers.fixtures import (
    Ctx,
    adopt_ips,
    advance_quarter,
    cast_vote,
    close_motion,
    create_fund,
    approve_run_with_motion,
    create_levelization_run,
    create_slot,
    draft_ips,
    hold_meeting_and_carry_motion,
    move_motion,
    open_meeting,
    open_review,
    read_fund,
    read_motion,
    read_run,
    seat_fund,
    setup_adopted_ips,
    submit_scorecard,
)
from test_helpers.test_users import consultant_headers
from test_helpers.types import (
    AssetClass,
    LevelizationMethod,
    LevelizationStatus,
    MotionStatus,
    MotionSubjectType,
    ScorecardStatus,
    ScoringVariant,
    TallyBasis,
    Vote,
    WatchRecommendation,
    WatchStatus,
)

#: The measured quarter used by both composite-score tests.  Read as a trailing
#: blend the excess is 0.6 * (820 - 900) + 0.4 * (700 - 650) = -28 basis points;
#: read as a since-watch window it is 100 - 900 = -800.
MEASUREMENT = {
    "trailing_return_3y_bps": 820,
    "trailing_return_5y_bps": 700,
    "benchmark_return_3y_bps": 900,
    "benchmark_return_5y_bps": 650,
    "peer_rank_pct": 90,
    "style_drift_r2": 0.8500,
    "net_expense_ratio_bps": 70,
    "peer_median_expense_bps": 40,
    "manager_tenure_quarters": 6,
    "manager_change_flag": True,
}

#: The since-watch pair the trailing blend must ignore.
ROLLING_INPUTS = {
    "rolling_since_watch_return_bps": 100,
    "rolling_since_watch_benchmark_bps": 900,
}


def read_scorecard(client: ApiClient, scorecard_id: str) -> dict:
    """Read one scorecard back as the consultant who submitted it."""
    return get_success_data(client.get(Paths.scorecard(scorecard_id), consultant_headers()))


def test_trailing_period_review_ignores_the_since_watch_inputs_on_the_row(api: ApiClient) -> None:
    """A TRAILING_PERIOD review blends the 3-year and 5-year pairs at 60/40 even
    when the submitted row also carries a since-watch window.

    Design: Difficulty/dual_variant_calc/composite_score_trailing_blend_ignores_rolling_inputs
    """
    ctx = setup_adopted_ips(api, ips_overrides={"scoring_variant": ScoringVariant.TRAILING_PERIOD})
    create_fund(
        ctx,
        "acmlx",
        ticker="ACMLX",
        fund_name="Acme Large Cap Value",
        asset_class_code=AssetClass.US_LARGE_CAP,
        share_class_code="R6",
        gross_expense_ratio_bps=80,
        net_expense_ratio_bps=70,
        revenue_share_bps=0,
        peer_median_expense_bps=40,
        track_record_quarters=16,
        manager_tenure_quarters=6,
        manager_change_flag=True,
        style_drift_r2=0.8500,
        plan_assets_cents=0,
    )
    review = open_review(ctx, 0)
    assert_fields(review, scoring_variant=ScoringVariant.TRAILING_PERIOD)

    trailing_only = submit_scorecard(ctx, "acmlx", dict(MEASUREMENT), key="first")

    # PRD 3.5: excess -28 bps, so performance is 50.00 - 2.80; the peer, expense,
    # style and manager components are 10.00, 40.00, 100.00 and 12.00; the
    # weighted sum 0.40*47.20 + 0.20*10.00 + 0.20*40.00 + 0.10*100.00 +
    # 0.10*12.00 rounds once to 40.08.
    assert_score(trailing_only["performance_component"], "47.20", "performance_component")
    assert_score(trailing_only["peer_component"], "10.00", "peer_component")
    assert_score(trailing_only["expense_component"], "40.00", "expense_component")
    assert_score(trailing_only["style_component"], "100.00", "style_component")
    assert_score(trailing_only["manager_component"], "12.00", "manager_component")
    assert_score(trailing_only["composite_score"], "40.08", "composite_score")
    # 40.08 is above the 40.00 watch trigger, but the manager change puts the
    # fund in breach anywhere at or below 50.00 (PRD 3.6), and a CLEAR fund whose
    # score is above the 25.00 remediation trigger is recommended WATCH.
    assert_fields(trailing_only, watch_recommendation=WatchRecommendation.WATCH)

    # The same row resubmitted with the since-watch pair populated supersedes the
    # first and scores identically: the variant comes from the review, never from
    # the payload.
    with_rolling = submit_scorecard(
        ctx, "acmlx", dict(MEASUREMENT, **ROLLING_INPUTS), key="second"
    )
    assert_fields(
        with_rolling,
        rolling_since_watch_return_bps=100,
        rolling_since_watch_benchmark_bps=900,
        supersedes_scorecard_id=trailing_only["id"],
        watch_recommendation=WatchRecommendation.WATCH,
    )
    assert_score(with_rolling["performance_component"], "47.20", "performance_component")
    assert_score(with_rolling["composite_score"], "40.08", "composite_score")
    assert_status(with_rolling, ScorecardStatus.SUBMITTED)
    assert_status(read_scorecard(api, trailing_only["id"]), ScorecardStatus.SUPERSEDED)

    review = get_success_data(api.get(Paths.review(review["id"]), consultant_headers()))
    assert_fields(review, submitted_scorecard_count=1)
    assert_fields(read_fund(api, ctx.fund("acmlx")["id"]), watch_status=WatchStatus.CLEAR)


def test_rolling_since_watch_review_prices_the_identical_row_off_the_watch_window(
    api: ApiClient, breach_quarter_finalized: Ctx
) -> None:
    """A ROLLING_SINCE_WATCH review takes the excess straight from the
    since-watch pair and discards both trailing pairs.

    Design: Difficulty/dual_variant_calc/composite_score_trailing_blend_ignores_rolling_inputs
    """
    ctx = breach_quarter_finalized
    watched = read_fund(api, ctx.fund("small")["id"])
    # Quarter 0 put this fund on watch, so the since-watch window exists
    # (PRD 3.6 and the availability gate in PRD 2.12 priority 79).
    assert_fields(
        watched, watch_status=WatchStatus.WATCH, watch_started_quarter_index=0,
        consecutive_breach_quarters=1,
    )

    advance_quarter(ctx)
    rolling_ips = draft_ips(
        api,
        ctx.plan_id,
        version_label="IPS-2026-B",
        scoring_variant=ScoringVariant.ROLLING_SINCE_WATCH,
    )
    motion = hold_meeting_and_carry_motion(
        ctx,
        MotionSubjectType.IPS_ADOPTION,
        rolling_ips["id"],
        meeting_date="2026-08-20",
        minutes_doc_ref="MIN-2026-Q1-010",
        quarter_index=1,
        key="rolling_ips",
    )
    ctx.ips = adopt_ips(ctx, rolling_ips["id"], motion["id"])

    review = open_review(ctx, 1)
    assert_fields(review, scoring_variant=ScoringVariant.ROLLING_SINCE_WATCH)

    scored = submit_scorecard(ctx, "small", dict(MEASUREMENT, **ROLLING_INPUTS), key="rolling")

    # PRD 3.5: the excess is 100 - 900 = -800 bps, so 50.00 - 80.00 clamps to
    # 0.00 instead of the 47.20 the trailing pairs on this same row would give.
    assert_score(scored["performance_component"], "0.00", "performance_component")
    assert_score(scored["peer_component"], "10.00", "peer_component")
    assert_score(scored["expense_component"], "40.00", "expense_component")
    assert_score(scored["style_component"], "100.00", "style_component")
    assert_score(scored["manager_component"], "12.00", "manager_component")
    # 0.00 + 2.00 + 8.00 + 10.00 + 1.20 = 21.20, not the 40.08 of the blend.
    assert_score(scored["composite_score"], "21.20", "composite_score")
    # 21.20 is at or below the 25.00 remediation trigger and this is the second
    # consecutive breach quarter against a grace of 2, so the first ladder arm
    # of PRD 3.6 recommends termination.
    assert_fields(scored, watch_recommendation=WatchRecommendation.TERMINATE)


def levelized_plan(api: ApiClient, participant_account_count: int) -> Ctx:
    """A two-slot menu whose only revenue-sharing fund accrues 2,400 cents.

    The large-cap fund holds 1,200,000 cents at 20 basis points of revenue
    sharing, so its PRD 3.8 accrual is floor(1200000 * 20 / 10000) = 2400; the
    bond fund holds 1,800,000 cents but shares no revenue, so it accrues
    nothing.  The plan therefore reports 3,000,000 cents of assets, which is the
    denominator the pro-rata split uses.
    """
    ctx = setup_adopted_ips(api, participant_account_count=participant_account_count)
    create_fund(ctx, "lc_a", plan_assets_cents=1200000, revenue_share_bps=20)
    create_fund(ctx, "bond", plan_assets_cents=1800000, revenue_share_bps=0)
    create_slot(ctx, "lc", AssetClass.US_LARGE_CAP, 1)
    create_slot(ctx, "bond", AssetClass.CORE_BOND, 2)
    seat_fund(ctx, "lc", "lc_a")
    seat_fund(ctx, "bond", "bond")
    ctx.refresh_plan()
    assert_cents(ctx.plan["total_plan_assets_cents"], 3000000, "total_plan_assets_cents")
    return ctx


def eligible_pool_cents(run: dict) -> int:
    """The pool PRD 3.8 pass 1 leaves: the smaller of the run's snapshot and the
    sum of the per-fund floored accruals, which is 2400 + 0 here."""
    accruals = accrual_cents(1200000, 20) + accrual_cents(1800000, 0)
    return min(run["credit_pool_cents"], accruals)


def test_per_capita_levelization_parks_the_indivisible_tail_in_the_remainder(
    api: ApiClient,
) -> None:
    """A PER_CAPITA run divides the pool by the participant account count, floors
    it, and retains the tail it cannot hand out.

    Design: Difficulty/dual_variant_calc/levelization_per_capita_remainder_vs_pro_rata_waterfall
    """
    ctx = levelized_plan(api, participant_account_count=7)
    run = create_levelization_run(
        ctx, quarter_index=0, method=LevelizationMethod.PER_CAPITA, key="per_capita"
    )
    # PRD 3.8 leaves a created run's allocation fields at their declared initial
    # values and makes approval the act that "freezes allocation_lines,
    # per_account_cents, allocated_total_cents and remainder_cents".
    approve_run_with_motion(ctx, run["id"], key="per_capita")
    run = read_run(api, run["id"])

    pool = eligible_pool_cents(run)
    # PRD 3.8 pass 2 over the 2,400-cent pool and 7 accounts: per_account_cents
    # is floor(2400 / 7) = 342, allocated_total_cents is 342 * 7 = 2394 and the
    # 6 cents that will not divide stay behind as remainder_cents.
    per_account = pool // 7
    assert_fields(run, method=LevelizationMethod.PER_CAPITA)
    assert_status(run, LevelizationStatus.APPROVED)
    assert_cents(run["per_account_cents"], per_account, "per_account_cents")
    assert_cents(run["allocated_total_cents"], per_account * 7, "allocated_total_cents")
    assert_cents(run["remainder_cents"], pool - per_account * 7, "remainder_cents")
    assert run["allocated_total_cents"] + run["remainder_cents"] == pool, (
        "PRD 3.8 pass 3: allocated_total_cents plus remainder_cents must equal "
        f"the eligible pool {pool}"
    )

    # Each line is the allocated total times that fund's share of the accruals,
    # so the whole allocated total lands on the only fund that shares revenue.
    lines = run["allocation_lines"]
    assert sum(line["allocated_cents"] for line in lines) == run["allocated_total_cents"], lines
    sharing = [line for line in lines if line["fund_id"] == ctx.fund("lc_a")["id"]]
    assert len(sharing) == 1, lines
    assert_cents(sharing[0]["allocated_cents"], per_account * 7, "allocated_cents")


def test_pro_rata_levelization_hands_out_every_cent_through_the_waterfall(
    api: ApiClient,
) -> None:
    """A PRO_RATA run splits the same pool by fund assets, keeps no remainder and
    reports no per-account figure.

    Design: Difficulty/dual_variant_calc/levelization_per_capita_remainder_vs_pro_rata_waterfall
    """
    ctx = levelized_plan(api, participant_account_count=7)
    run = create_levelization_run(
        ctx, quarter_index=0, method=LevelizationMethod.PRO_RATA, key="pro_rata"
    )
    # PRD 3.8: the three passes land at approval, which freezes what they wrote.
    approve_run_with_motion(ctx, run["id"], key="pro_rata")
    run = read_run(api, run["id"])

    pool = eligible_pool_cents(run)
    # PRD 3.8 pass 2: the per-account figure is not meaningful under this method,
    # the waterfall distributes the whole 2,400-cent pool one cent at a time and
    # remainder_cents is always exactly 0 — 2400 against the 2394 the per-capita
    # split of the same pool produces.
    assert_fields(run, method=LevelizationMethod.PRO_RATA, per_account_cents=None)
    assert_status(run, LevelizationStatus.APPROVED)
    assert_cents(run["allocated_total_cents"], pool, "allocated_total_cents")
    assert_cents(run["remainder_cents"], 0, "remainder_cents")
    assert run["allocated_total_cents"] + run["remainder_cents"] == pool, run

    lines = run["allocation_lines"]
    assert lines, "a pro-rata run writes one allocation line per pool fund"
    assert sum(line["allocated_cents"] for line in lines) == pool, lines
    assert all(line["allocated_cents"] >= 0 for line in lines), lines


def tallied_motion(
    ctx: Ctx,
    subject_type: str,
    subject_id: str,
    tally_basis: str,
    votes: dict,
    meeting_date: str,
) -> dict:
    """Convene all three members, move a motion on the given basis, record the
    listed ballots and close it, returning the closed motion."""
    meeting = open_meeting(ctx, meeting_date, 0, key="tally")
    motion = move_motion(ctx, meeting["id"], subject_type, subject_id, tally_basis, key="tally")
    for member_id, vote in votes.items():
        extra = {"recusal_basis": "Employed by the plan recordkeeper"} if vote == Vote.RECUSE else {}
        cast_vote(ctx, motion["id"], member_id, vote, **extra)
    close_motion(ctx, motion["id"])
    return read_motion(ctx.client, motion["id"])


def test_votes_cast_basis_divides_by_the_ballots_actually_cast(api: ApiClient) -> None:
    """Under VOTES_CAST the denominator is the sum of the FOR, AGAINST and
    ABSTAIN counts, so two FOR ballots from a three-member roster carry.

    Design: Difficulty/dual_variant_calc/motion_tally_votes_cast_vs_eligible_voters_denominator
    """
    ctx = setup_adopted_ips(api)
    fund = create_fund(ctx, "lc_a")
    chair_id, finance_id, _hr_id = ctx.member_ids

    motion = tallied_motion(
        ctx,
        MotionSubjectType.WATCH_LIST_ACTION,
        fund["id"],
        TallyBasis.VOTES_CAST,
        {chair_id: Vote.FOR, finance_id: Vote.FOR},
        "2026-08-05",
    )

    # PRD 3.4: the third attendee never voted, so the denominator is 2 and
    # support is 2 * 100 / 2 = 100.0000 — not the 66.6667 that dividing by the
    # three eligible attendees would give.
    assert_fields(
        motion,
        tally_basis=TallyBasis.VOTES_CAST,
        eligible_voter_count=3,
        for_count=2,
        against_count=0,
        abstain_count=0,
        recuse_count=0,
    )
    assert_ratio(motion["support_pct"], "100.0000", "support_pct")
    assert_status(motion, MotionStatus.CARRIED)


def test_eligible_voters_basis_divides_by_the_whole_non_recused_body(api: ApiClient) -> None:
    """Under ELIGIBLE_VOTERS the denominator is the voting attendance less the
    recusals, so the identical two FOR ballots score only 66.6667.

    Design: Difficulty/dual_variant_calc/motion_tally_votes_cast_vs_eligible_voters_denominator
    """
    ctx = setup_adopted_ips(api)
    fund = create_fund(ctx, "lc_a")
    chair_id, finance_id, _hr_id = ctx.member_ids

    motion = tallied_motion(
        ctx,
        MotionSubjectType.WATCH_LIST_ACTION,
        fund["id"],
        TallyBasis.ELIGIBLE_VOTERS,
        {chair_id: Vote.FOR, finance_id: Vote.FOR},
        "2026-08-05",
    )

    # The four counters are identical to the VOTES_CAST tally of the same
    # ballots; only the denominator moves, from 2 ballots to 3 - 0 seats.
    assert_fields(
        motion,
        tally_basis=TallyBasis.ELIGIBLE_VOTERS,
        eligible_voter_count=3,
        for_count=2,
        against_count=0,
        abstain_count=0,
        recuse_count=0,
    )
    assert_ratio(motion["support_pct"], "66.6667", "support_pct")


def test_eligible_voters_basis_shrinks_by_the_recusals(api: ApiClient, full_menu: Ctx) -> None:
    """A recusal leaves the body rather than diluting it: under ELIGIBLE_VOTERS
    the denominator drops with the recusal, so two FOR out of three attendees
    still reads 100.0000.

    Design: Difficulty/dual_variant_calc/motion_tally_votes_cast_vs_eligible_voters_denominator
    """
    ctx = full_menu
    run = create_levelization_run(ctx, quarter_index=0, method=LevelizationMethod.PER_CAPITA)
    chair_id, finance_id, hr_id = ctx.member_ids

    # PRD 3.4 requires the member affiliated with the recordkeeper to recuse on a
    # fee levelization motion.
    motion = tallied_motion(
        ctx,
        MotionSubjectType.FEE_LEVELIZATION,
        run["id"],
        TallyBasis.ELIGIBLE_VOTERS,
        {chair_id: Vote.FOR, finance_id: Vote.FOR, hr_id: Vote.RECUSE},
        "2026-08-06",
    )

    # The denominator is eligible_voter_count 3 minus recuse_count 1, so support
    # is 200 / 2 = 100.0000; had the recusal stayed in the base it would read
    # 66.6667.
    assert_fields(
        motion,
        tally_basis=TallyBasis.ELIGIBLE_VOTERS,
        eligible_voter_count=3,
        for_count=2,
        against_count=0,
        abstain_count=0,
        recuse_count=1,
    )
    assert_ratio(motion["support_pct"], "100.0000", "support_pct")
    assert_status(motion, MotionStatus.CARRIED)


def test_an_abstention_dilutes_support_under_votes_cast(api: ApiClient) -> None:
    """An abstention is a cast ballot, so under VOTES_CAST it enters the
    denominator and pulls the same two FOR votes down to 66.6667.

    Design: Difficulty/dual_variant_calc/motion_tally_votes_cast_vs_eligible_voters_denominator
    """
    ctx = setup_adopted_ips(api)
    fund = create_fund(ctx, "lc_a")
    chair_id, finance_id, hr_id = ctx.member_ids

    motion = tallied_motion(
        ctx,
        MotionSubjectType.WATCH_LIST_ACTION,
        fund["id"],
        TallyBasis.VOTES_CAST,
        {chair_id: Vote.FOR, finance_id: Vote.FOR, hr_id: Vote.ABSTAIN},
        "2026-08-05",
    )

    assert_fields(
        motion,
        tally_basis=TallyBasis.VOTES_CAST,
        eligible_voter_count=3,
        for_count=2,
        against_count=0,
        abstain_count=1,
        recuse_count=0,
    )
    assert_ratio(motion["support_pct"], "66.6667", "support_pct")
