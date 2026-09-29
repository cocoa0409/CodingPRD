"""Exact behaviour on the documented numeric edges.

Every threshold in this domain is declared inclusive or exclusive in prose, and
the PRD spells the edges out: an expense cap floored to whole basis points where
a fund sitting exactly on the cap passes, a training gap that expires the moment
it reaches the record's validity, and provider cost tiers that flip at 25.00 /
25.01 and a competition trigger that flips at 60.00 / 60.01.  Each test below
pits the value one unit inside an edge against the value exactly on it and the
value one unit past it.
"""

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_capacity_triple,
    assert_cents,
    assert_fields,
    assert_ratio,
    assert_score,
    assert_status,
    get_success_data,
    validate_error,
)
from test_helpers.factories import (
    Paths,
    engagement_payload,
    seat_fund_payload,
    vote_payload,
    without,
)
from test_helpers.fixtures import (
    Ctx,
    activate_member,
    adopt_charter,
    advance_quarter,
    appoint_member,
    assign_training,
    benchmark_engagement,
    cast_vote,
    complete_training,
    convene,
    create_engagement,
    create_fund,
    create_seat,
    create_slot,
    draft_ips,
    move_motion,
    read_engagement,
    read_fund,
    read_member,
    read_motion,
    read_plan,
    read_slot,
    register_plan,
    schedule_meeting,
    seat_fund,
    setup_adopted_ips,
    sign_acceptance,
)
from test_helpers.test_users import consultant_headers, member_headers, sponsor_headers
from test_helpers.types import (
    AssetClass,
    CreditAccrualStatus,
    EngagementStatus,
    FeeCreditTier,
    FiduciaryTrainingStatus,
    FundMenuStatus,
    IpsStatus,
    MemberStatus,
    MenuPosture,
    MotionStatus,
    MotionSubjectType,
    ProviderRole,
    SeatClass,
    SlotStatus,
    TrainingModule,
    TrainingStatus,
    Vote,
)

# --------------------------------------------------------------------------
# The eligibility edges of PRD 3.3
#
# The default statement carries min_track_record_quarters 12, an
# expense_peer_multiple of 1.25 and a style_drift_r2_floor of 0.8000, so a peer
# median of 40 gives a cap of exactly 50 basis points.
# --------------------------------------------------------------------------

_SLOT_LAYOUT = (
    ("lc", AssetClass.US_LARGE_CAP, 1),
    ("sm", AssetClass.US_SMALL_CAP, 2),
    ("intl", AssetClass.INTL_DEVELOPED, 3),
    ("bond", AssetClass.CORE_BOND, 4),
    ("tips", AssetClass.TIPS, 5),
)


def _candidate_universe(client):
    """A six-slot plan with five empty slots and one candidate per edge."""
    ctx = setup_adopted_ips(client)
    for key, asset_class, index in _SLOT_LAYOUT:
        create_slot(ctx, key, asset_class, index)

    create_fund(
        ctx,
        "cap_exact",
        ticker="MGCAP",
        fund_name="Marigold Large Cap Index",
        asset_class_code=AssetClass.US_LARGE_CAP,
        gross_expense_ratio_bps=55,
        net_expense_ratio_bps=50,
        revenue_share_bps=5,
        peer_median_expense_bps=40,
        track_record_quarters=24,
        manager_tenure_quarters=24,
        manager_change_flag=False,
        style_drift_r2=0.8000,
        plan_assets_cents=3000000,
    )
    create_fund(
        ctx,
        "cap_over",
        ticker="MGOVR",
        fund_name="Marigold Large Cap Premium",
        asset_class_code=AssetClass.US_LARGE_CAP,
        gross_expense_ratio_bps=60,
        net_expense_ratio_bps=51,
        revenue_share_bps=5,
        peer_median_expense_bps=40,
        track_record_quarters=24,
        manager_tenure_quarters=24,
        manager_change_flag=False,
        style_drift_r2=0.9000,
        plan_assets_cents=3000000,
    )
    create_fund(
        ctx,
        "drifted",
        ticker="MGDRF",
        fund_name="Marigold Small Cap Opportunity",
        asset_class_code=AssetClass.US_SMALL_CAP,
        gross_expense_ratio_bps=45,
        net_expense_ratio_bps=40,
        revenue_share_bps=5,
        peer_median_expense_bps=40,
        track_record_quarters=24,
        manager_tenure_quarters=24,
        manager_change_flag=False,
        style_drift_r2=0.7999,
        plan_assets_cents=1000000,
    )
    create_fund(
        ctx,
        "short_record",
        ticker="MGNEW",
        fund_name="Marigold International Launch",
        asset_class_code=AssetClass.INTL_DEVELOPED,
        gross_expense_ratio_bps=70,
        net_expense_ratio_bps=60,
        revenue_share_bps=5,
        peer_median_expense_bps=40,
        track_record_quarters=11,
        manager_tenure_quarters=24,
        manager_change_flag=False,
        style_drift_r2=0.9000,
        plan_assets_cents=1000000,
    )
    create_fund(
        ctx,
        "new_manager_3",
        ticker="MGCH3",
        fund_name="Marigold Inflation Protected Short Tenure",
        asset_class_code=AssetClass.TIPS,
        gross_expense_ratio_bps=34,
        net_expense_ratio_bps=30,
        revenue_share_bps=4,
        peer_median_expense_bps=40,
        track_record_quarters=24,
        manager_tenure_quarters=3,
        manager_change_flag=True,
        style_drift_r2=0.9000,
        plan_assets_cents=1000000,
    )
    create_fund(
        ctx,
        "new_manager_4",
        ticker="MGCH4",
        fund_name="Marigold Inflation Protected Core",
        asset_class_code=AssetClass.TIPS,
        gross_expense_ratio_bps=55,
        net_expense_ratio_bps=50,
        revenue_share_bps=5,
        peer_median_expense_bps=40,
        track_record_quarters=12,
        manager_tenure_quarters=4,
        manager_change_flag=True,
        style_drift_r2=0.8000,
        plan_assets_cents=1000000,
    )
    return ctx


def _try_seat(ctx, slot_key, fund_key):
    return ctx.client.post(
        Paths.seat_fund(ctx.slot(slot_key)["id"]),
        seat_fund_payload(ctx.fund(fund_key)["id"]),
        consultant_headers(),
    )


def _assert_slot_untouched(ctx, slot_key, fund_key):
    assert_fields(
        read_slot(ctx.client, ctx.slot(slot_key)["id"]),
        status=SlotStatus.EMPTY,
        current_fund_id=None,
    )
    assert_fields(
        read_fund(ctx.client, ctx.fund(fund_key)["id"]),
        menu_status=FundMenuStatus.CANDIDATE,
        credit_accrual_status=CreditAccrualStatus.NOT_ACCRUING,
    )


def test_fund_exactly_on_the_expense_cap_and_style_floor_is_seated(api):
    """A net expense of exactly the floored cap of 50 basis points and a drift
    fit exactly on the 0.8000 floor both pass, so the slot fills.

    Design: Difficulty/boundary_precision_check/ips_eligibility_four_inclusive_edges_and_first_failure_order
    """
    ctx = _candidate_universe(api)

    slot = seat_fund(ctx, "lc", "cap_exact")

    assert_fields(
        slot,
        status=SlotStatus.ACTIVE,
        current_fund_id=ctx.fund("cap_exact")["id"],
    )
    assert_fields(
        read_fund(ctx.client, ctx.fund("cap_exact")["id"]),
        menu_status=FundMenuStatus.ACTIVE,
        credit_accrual_status=CreditAccrualStatus.ACCRUING,
        qdia_flag=False,
    )


def test_one_basis_point_over_the_expense_cap_is_refused(api):
    """A net expense of 51 against a cap of 50 fails the expense criterion and
    leaves both rows exactly as they were.

    Design: Difficulty/boundary_precision_check/ips_eligibility_four_inclusive_edges_and_first_failure_order
    """
    ctx = _candidate_universe(api)

    resp = _try_seat(ctx, "lc", "cap_over")
    validate_error(resp, ApiErrorId.FUND_FAILS_IPS_CRITERIA)

    _assert_slot_untouched(ctx, "lc", "cap_over")


def test_style_fit_one_ten_thousandth_below_the_floor_is_refused(api):
    """A drift fit of 0.7999 against a 0.8000 floor fails, proving the floor
    comparison is inclusive only at the floor itself.

    Design: Difficulty/boundary_precision_check/ips_eligibility_four_inclusive_edges_and_first_failure_order
    """
    ctx = _candidate_universe(api)

    resp = _try_seat(ctx, "sm", "drifted")
    validate_error(resp, ApiErrorId.FUND_FAILS_IPS_CRITERIA)

    _assert_slot_untouched(ctx, "sm", "drifted")


def test_track_record_one_quarter_short_is_refused(api):
    """Eleven quarters against a twelve-quarter minimum fails even though the
    fund also breaks the expense cap.

    Design: Difficulty/boundary_precision_check/ips_eligibility_four_inclusive_edges_and_first_failure_order
    """
    ctx = _candidate_universe(api)

    resp = _try_seat(ctx, "intl", "short_record")
    validate_error(resp, ApiErrorId.FUND_FAILS_IPS_CRITERIA)

    _assert_slot_untouched(ctx, "intl", "short_record")


def test_manager_tenure_of_four_quarters_clears_a_manager_change(api):
    """After a manager change three quarters of tenure fails and four passes, on
    the very same still-empty slot.

    Design: Difficulty/boundary_precision_check/ips_eligibility_four_inclusive_edges_and_first_failure_order
    """
    ctx = _candidate_universe(api)

    too_new = _try_seat(ctx, "tips", "new_manager_3")
    validate_error(too_new, ApiErrorId.FUND_FAILS_IPS_CRITERIA)
    _assert_slot_untouched(ctx, "tips", "new_manager_3")

    seated = get_success_data(_try_seat(ctx, "tips", "new_manager_4"))
    assert_fields(
        seated,
        status=SlotStatus.ACTIVE,
        current_fund_id=ctx.fund("new_manager_4")["id"],
    )


def test_refused_seatings_move_no_capacity_or_asset_counter(api):
    """Only the two funds sitting on the inclusive edges are seated, so the
    capacity triple and the plan asset total count exactly those two.

    Design: Difficulty/boundary_precision_check/ips_eligibility_four_inclusive_edges_and_first_failure_order
    """
    ctx = _candidate_universe(api)
    seat_fund(ctx, "lc", "cap_exact")
    seat_fund(ctx, "tips", "new_manager_4")

    for slot_key, fund_key in (
        ("sm", "drifted"),
        ("intl", "short_record"),
    ):
        validate_error(
            _try_seat(ctx, slot_key, fund_key),
            ApiErrorId.FUND_FAILS_IPS_CRITERIA,
        )

    plan = read_plan(ctx.client, ctx.plan_id)
    assert_capacity_triple(plan, occupied=2, reserved=0, available=4)
    assert_cents(plan["total_plan_assets_cents"], 4000000, "total_plan_assets_cents")
    assert_ratio(plan["at_risk_slot_ratio"], "0.0000")
    assert_status(plan, MenuPosture.OPEN, field="menu_posture")


# --------------------------------------------------------------------------
# The training validity edge of PRD 3.2
#
# A record is current while the quarter gap is strictly less than its
# validity_quarters, so a gap that reaches the validity is stale.
# --------------------------------------------------------------------------

_SEAT_PLAN = (
    ("chair", "S-CHAIR", SeatClass.CHAIR, 1, "Rowan Adeyemi", "rowan.adeyemi@example.com", 3),
    ("finance", "S-FINANCE", SeatClass.FINANCE, 2, "Ines Kovac", "ines.kovac@example.com", 2),
)

_REQUIRED_MODULES = (TrainingModule.FIDUCIARY_DUTIES, TrainingModule.IPS_MECHANICS)


def _two_seat_committee(client):
    """A two-voting-seat governed plan whose chair holds three-quarter training
    and whose second member holds two-quarter training, both closed out in
    quarter 0, plus one drafted statement to move motions about."""
    ctx = Ctx(client)
    ctx.plan = register_plan(
        client,
        plan_name="Foxglove Retirement Savings Plan",
        plan_sponsor_name="Foxglove Industries Inc.",
        participant_account_count=90,
        menu_slot_capacity=4,
        quorum_min_voting_members=2,
        max_voting_seats=2,
        voting_threshold_pct=0.6667,
    )
    ctx.training_records = {}
    for key, code, seat_class, index, name, email, validity in _SEAT_PLAN:
        seat = create_seat(
            client,
            ctx.plan_id,
            seat_code=code,
            seat_class=seat_class,
            voting=True,
            seat_index=index,
        )
        ctx.seats[key] = seat
        member = appoint_member(
            client, seat["id"], member_name=name, person_email=email
        )
        ctx.members[key] = member
        ctx.training_records[key] = [
            complete_training(
                client,
                assign_training(
                    client,
                    member["id"],
                    module_code=module,
                    validity_quarters=validity,
                )["id"],
                member["id"],
            )
            for module in _REQUIRED_MODULES
        ]
        sign_acceptance(client, member["id"])
        ctx.members[key] = activate_member(client, member["id"])
    ctx.plan = adopt_charter(
        client,
        ctx.plan_id,
        quorum_min_voting_members=2,
        max_voting_seats=2,
        voting_threshold_pct=0.6667,
    )
    ctx.ips = draft_ips(client, ctx.plan_id)
    return ctx


def _record_rows(ctx, key):
    return [
        get_success_data(
            ctx.client.get(Paths.training_record(row["id"]), sponsor_headers())
        )
        for row in ctx.training_records[key]
    ]


def test_training_one_quarter_inside_its_validity_is_still_current(api):
    """A gap of one quarter against validities of two and three quarters leaves
    both members current, so the whole committee still counts toward quorum.

    Design: Difficulty/boundary_precision_check/training_expiry_gap_equals_validity_quarters_is_expired
    """
    ctx = _two_seat_committee(api)
    plan = advance_quarter(ctx)
    assert_fields(plan, fiscal_quarter_index=1)

    for key in ("chair", "finance"):
        assert_fields(
            read_member(ctx.client, ctx.members[key]["id"]),
            status=MemberStatus.ACTIVE,
            fiduciary_training_status=FiduciaryTrainingStatus.CURRENT,
        )
        for row in _record_rows(ctx, key):
            assert_fields(
                row,
                status=TrainingStatus.COMPLETED,
                completed_quarter_index=0,
            )

    meeting = schedule_meeting(ctx, "2026-08-20", quarter_index=1)
    convened = convene(
        ctx,
        meeting["id"],
        [ctx.members["chair"]["id"], ctx.members["finance"]["id"]],
    )
    assert_fields(
        convened,
        voting_attendee_count=2,
        eligible_voting_seat_count=2,
        quorum_met=True,
    )


def test_training_gap_equal_to_the_validity_expires_the_records(api):
    """A gap of exactly two quarters expires a two-quarter record while a
    three-quarter record at the same gap stays current; the lapsed member stays
    active.

    Design: Difficulty/boundary_precision_check/training_expiry_gap_equals_validity_quarters_is_expired
    """
    ctx = _two_seat_committee(api)
    advance_quarter(ctx)
    plan = advance_quarter(ctx)
    assert_fields(plan, fiscal_quarter_index=2)

    for row in _record_rows(ctx, "finance"):
        assert_fields(row, status=TrainingStatus.EXPIRED, completed_quarter_index=0)
    assert_fields(
        read_member(ctx.client, ctx.members["finance"]["id"]),
        status=MemberStatus.ACTIVE,
        fiduciary_training_status=FiduciaryTrainingStatus.EXPIRED,
    )

    for row in _record_rows(ctx, "chair"):
        assert_fields(row, status=TrainingStatus.COMPLETED)
    assert_fields(
        read_member(ctx.client, ctx.members["chair"]["id"]),
        status=MemberStatus.ACTIVE,
        fiduciary_training_status=FiduciaryTrainingStatus.CURRENT,
    )


def test_expired_member_drops_out_of_both_quorum_figures_and_cannot_vote(api):
    """At the expiry edge the lapsed member counts toward neither quorum figure,
    is refused a vote, and leaves the motion unclosable for want of quorum.

    Design: Difficulty/boundary_precision_check/training_expiry_gap_equals_validity_quarters_is_expired
    """
    ctx = _two_seat_committee(api)
    advance_quarter(ctx)
    advance_quarter(ctx)

    chair_id = ctx.members["chair"]["id"]
    lapsed_id = ctx.members["finance"]["id"]
    meeting = schedule_meeting(ctx, "2026-09-10", quarter_index=2)
    convened = convene(ctx, meeting["id"], [chair_id, lapsed_id])
    assert_fields(
        convened,
        voting_attendee_count=1,
        eligible_voting_seat_count=1,
        quorum_met=False,
    )

    motion = move_motion(
        ctx, meeting["id"], MotionSubjectType.IPS_ADOPTION, ctx.ips_id
    )
    lapsed_vote = ctx.client.post(
        Paths.votes(motion["id"]),
        vote_payload(lapsed_id, Vote.FOR),
        member_headers(lapsed_id),
    )
    validate_error(lapsed_vote, ApiErrorId.TRAINING_NOT_CURRENT)
    assert_fields(read_motion(ctx.client, motion["id"]), for_count=0)

    assert_fields(cast_vote(ctx, motion["id"], chair_id, Vote.FOR), for_count=1)

    closed = ctx.client.post(Paths.motion_close(motion["id"]), {}, ctx.chair)
    validate_error(closed, ApiErrorId.QUORUM_NOT_MET)
    assert_status(read_motion(ctx.client, motion["id"]), MotionStatus.OPEN)
    assert_status(
        get_success_data(ctx.client.get(Paths.ips(ctx.ips_id), sponsor_headers())),
        IpsStatus.DRAFT,
    )


# --------------------------------------------------------------------------
# The provider cost edges of PRD 3.9
#
# 180 participants against 1,800,000.00 of plan assets makes one cent of
# per-head fee worth exactly 0.01 basis points, which is what lets a gross cost
# be placed exactly on 25.00 or 60.00 and then nudged one hundredth past it.
# --------------------------------------------------------------------------


def _benchmarkable_plan(client):
    """A governed plan with one seated holding worth 1,800,000.00 and an empty
    revenue credit pool, so every tier offset is forced to 0.00."""
    ctx = setup_adopted_ips(client, participant_account_count=180)
    create_slot(ctx, "lc", AssetClass.US_LARGE_CAP, 1)
    create_fund(
        ctx,
        "lc",
        ticker="FGLCX",
        fund_name="Foxglove Large Cap Core",
        asset_class_code=AssetClass.US_LARGE_CAP,
        gross_expense_ratio_bps=40,
        net_expense_ratio_bps=35,
        revenue_share_bps=5,
        peer_median_expense_bps=40,
        track_record_quarters=24,
        manager_tenure_quarters=24,
        manager_change_flag=False,
        style_drift_r2=0.9000,
        plan_assets_cents=180000000,
    )
    seat_fund(ctx, "lc", "lc")
    plan = read_plan(ctx.client, ctx.plan_id)
    assert_cents(plan["total_plan_assets_cents"], 180000000, "total_plan_assets_cents")
    assert_cents(plan["revenue_credit_balance_cents"], 0, "revenue_credit_balance_cents")
    return ctx


def _benchmark(ctx, key="engagement", **overrides):
    engagement = create_engagement(ctx, key, **overrides)
    assert_fields(
        engagement,
        status=EngagementStatus.PENDING,
        rfp_required=False,
        last_benchmarked_quarter_index=None,
    )
    return benchmark_engagement(ctx, engagement["id"], key)


def test_total_cost_of_exactly_sixty_basis_points_asks_for_no_competition(api):
    """A total cost sitting exactly on 60.00 does not trigger a competition, and
    the pending engagement simply becomes active.

    Design: Difficulty/boundary_precision_check/provider_cost_tier_and_rfp_edges_at_2500_2501_6000_6001_and_pct_75
    """
    ctx = _benchmarkable_plan(api)

    benchmarked = _benchmark(
        ctx,
        provider_role=ProviderRole.RECORDKEEPER,
        term_start_date="2026-01-01",
        term_end_date="2026-12-31",
        per_head_fee_cents=0,
        asset_based_bps=60,
        benchmark_percentile=74,
        last_rfp_quarter_index=0,
    )

    assert_score(benchmarked["gross_cost_bps"], "60.00", "gross_cost_bps")
    assert_score(benchmarked["total_cost_bps"], "60.00", "total_cost_bps")
    assert_fields(
        benchmarked,
        fee_credit_tier=FeeCreditTier.TIER_C,
        rfp_required=False,
        status=EngagementStatus.ACTIVE,
        last_benchmarked_quarter_index=0,
    )


def test_one_hundredth_past_sixty_basis_points_forces_a_competition(api):
    """One cent of per-head fee lifts the total to 60.01, which is strictly
    greater than the trigger, so the engagement goes under competition.

    Design: Difficulty/boundary_precision_check/provider_cost_tier_and_rfp_edges_at_2500_2501_6000_6001_and_pct_75
    """
    ctx = _benchmarkable_plan(api)

    benchmarked = _benchmark(
        ctx,
        provider_role=ProviderRole.RECORDKEEPER,
        term_start_date="2026-01-01",
        term_end_date="2026-12-31",
        per_head_fee_cents=1,
        asset_based_bps=60,
        benchmark_percentile=74,
        last_rfp_quarter_index=0,
    )

    assert_score(benchmarked["gross_cost_bps"], "60.01", "gross_cost_bps")
    assert_score(benchmarked["total_cost_bps"], "60.01", "total_cost_bps")
    assert_fields(
        benchmarked,
        fee_credit_tier=FeeCreditTier.TIER_C,
        rfp_required=True,
        status=EngagementStatus.UNDER_RFP,
        last_benchmarked_quarter_index=0,
    )


def test_benchmark_percentile_of_exactly_seventy_five_forces_a_competition(api):
    """The percentile comparison is inclusive, so a cheap TIER_A engagement at
    exactly 75 still goes to competition.

    Design: Difficulty/boundary_precision_check/provider_cost_tier_and_rfp_edges_at_2500_2501_6000_6001_and_pct_75
    """
    ctx = _benchmarkable_plan(api)

    benchmarked = _benchmark(
        ctx,
        provider_role=ProviderRole.ADVISOR,
        provider_name="Foxglove Advisory Partners LLC",
        per_head_fee_cents=0,
        asset_based_bps=20,
        benchmark_percentile=75,
        last_rfp_quarter_index=0,
    )

    assert_score(benchmarked["gross_cost_bps"], "20.00", "gross_cost_bps")
    assert_score(benchmarked["total_cost_bps"], "20.00", "total_cost_bps")
    assert_fields(
        benchmarked,
        fee_credit_tier=FeeCreditTier.TIER_A,
        rfp_required=True,
        status=EngagementStatus.UNDER_RFP,
    )


def test_benchmark_percentile_one_below_the_trigger_keeps_the_incumbent(api):
    """The identical engagement at 74 stays active with no competition, which is
    what makes 75 the edge rather than the neighbourhood.

    Design: Difficulty/boundary_precision_check/provider_cost_tier_and_rfp_edges_at_2500_2501_6000_6001_and_pct_75
    """
    ctx = _benchmarkable_plan(api)

    benchmarked = _benchmark(
        ctx,
        provider_role=ProviderRole.ADVISOR,
        provider_name="Foxglove Advisory Partners LLC",
        per_head_fee_cents=0,
        asset_based_bps=20,
        benchmark_percentile=74,
        last_rfp_quarter_index=0,
    )

    assert_score(benchmarked["gross_cost_bps"], "20.00", "gross_cost_bps")
    assert_score(benchmarked["total_cost_bps"], "20.00", "total_cost_bps")
    assert_fields(
        benchmarked,
        fee_credit_tier=FeeCreditTier.TIER_A,
        rfp_required=False,
        status=EngagementStatus.ACTIVE,
    )


def test_never_competed_role_forces_a_competition_on_its_own(api):
    """A null last competition quarter triggers on its own arm, with the
    percentile and the total cost both well inside their edges.

    Design: Difficulty/boundary_precision_check/provider_cost_tier_and_rfp_edges_at_2500_2501_6000_6001_and_pct_75
    """
    ctx = _benchmarkable_plan(api)
    created = get_success_data(
        ctx.client.post(
            Paths.ENGAGEMENTS,
            without(
                engagement_payload(
                    ctx.plan_id,
                    provider_role=ProviderRole.ADVISOR,
                    provider_name="Foxglove Advisory Partners LLC",
                    per_head_fee_cents=0,
                    asset_based_bps=20,
                    benchmark_percentile=74,
                ),
                "last_rfp_quarter_index",
            ),
            sponsor_headers(),
        ),
        201,
    )
    assert_fields(created, last_rfp_quarter_index=None, rfp_required=False)

    benchmarked = benchmark_engagement(ctx, created["id"], "advisor")

    assert_score(benchmarked["total_cost_bps"], "20.00", "total_cost_bps")
    assert_fields(
        benchmarked,
        fee_credit_tier=FeeCreditTier.TIER_A,
        rfp_required=True,
        status=EngagementStatus.UNDER_RFP,
    )


def test_gross_cost_of_exactly_twenty_five_is_the_cheapest_tier(api):
    """25.00 basis points gross is TIER_A, the tier being read from the gross
    cost alone.

    Design: Difficulty/boundary_precision_check/provider_cost_tier_and_rfp_edges_at_2500_2501_6000_6001_and_pct_75
    """
    ctx = _benchmarkable_plan(api)

    benchmarked = _benchmark(
        ctx,
        provider_role=ProviderRole.AUDITOR,
        provider_name="Foxglove Plan Audit LLP",
        per_head_fee_cents=0,
        asset_based_bps=25,
        benchmark_percentile=74,
        last_rfp_quarter_index=0,
    )

    assert_score(benchmarked["gross_cost_bps"], "25.00", "gross_cost_bps")
    assert_score(benchmarked["total_cost_bps"], "25.00", "total_cost_bps")
    assert_fields(
        benchmarked,
        fee_credit_tier=FeeCreditTier.TIER_A,
        rfp_required=False,
        status=EngagementStatus.ACTIVE,
    )


def test_gross_cost_of_twenty_five_point_zero_one_falls_to_the_middle_tier(api):
    """One hundredth of a basis point more moves the engagement to TIER_B, and
    with an empty credit pool the offset stays 0.00 so the total is unchanged
    from the gross.

    Design: Difficulty/boundary_precision_check/provider_cost_tier_and_rfp_edges_at_2500_2501_6000_6001_and_pct_75
    """
    ctx = _benchmarkable_plan(api)

    benchmarked = _benchmark(
        ctx,
        provider_role=ProviderRole.AUDITOR,
        provider_name="Foxglove Plan Audit LLP",
        per_head_fee_cents=1,
        asset_based_bps=25,
        benchmark_percentile=74,
        last_rfp_quarter_index=0,
    )

    assert_score(benchmarked["gross_cost_bps"], "25.01", "gross_cost_bps")
    assert_score(benchmarked["total_cost_bps"], "25.01", "total_cost_bps")
    assert_fields(
        benchmarked,
        fee_credit_tier=FeeCreditTier.TIER_B,
        rfp_required=False,
        status=EngagementStatus.ACTIVE,
    )


def test_second_benchmark_in_the_same_quarter_is_refused(api):
    """The self-loop needs the fiscal quarter to be strictly past the stamped
    one, so an immediate re-run changes nothing.

    Design: Difficulty/boundary_precision_check/provider_cost_tier_and_rfp_edges_at_2500_2501_6000_6001_and_pct_75
    """
    ctx = _benchmarkable_plan(api)
    benchmarked = _benchmark(
        ctx,
        provider_role=ProviderRole.RECORDKEEPER,
        per_head_fee_cents=0,
        asset_based_bps=20,
        benchmark_percentile=74,
        last_rfp_quarter_index=0,
    )
    assert_fields(
        benchmarked,
        status=EngagementStatus.ACTIVE,
        last_benchmarked_quarter_index=0,
    )

    again = ctx.client.post(
        Paths.engagement_benchmark(benchmarked["id"]), {}, consultant_headers()
    )
    validate_error(again, ApiErrorId.BENCHMARK_ALREADY_CURRENT)

    assert_fields(
        read_engagement(ctx.client, benchmarked["id"]),
        status=EngagementStatus.ACTIVE,
        last_benchmarked_quarter_index=0,
    )
