"""Vote tallies, quorum arithmetic, notice lead times and training currency.

These tests exercise the counted arithmetic of PRD 3.4 (the two tally bases, the
abstain/recuse asymmetry, the frozen quorum verdict and its strict-majority
test), the notice-lead stack of PRD 3.7, and the quarter-gap currency window of
PRD 3.2.
"""

from test_helpers.api_client import paginate_params
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_fields,
    assert_ratio,
    assert_status,
    find_by,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    Paths,
    end_term_payload,
    minutes_payload,
    vote_payload,
)
from test_helpers.fixtures import (
    adjourn,
    advance_quarter,
    appoint_member,
    approve_minutes,
    assign_training,
    cast_vote,
    close_motion,
    complete_training,
    convene,
    create_fund,
    create_seat,
    draft_proposal,
    hold_meeting_and_carry_motion,
    make_member_active,
    move_motion,
    open_meeting,
    read_meeting,
    read_member,
    read_motion,
    schedule_meeting,
    select_target_date_suite,
    setup_full_menu,
    setup_qdia_candidates,
    submit_proposal,
)
from test_helpers.test_users import auditor_headers, sponsor_headers
from test_helpers.types import (
    AssetClass,
    EndTermReason,
    FiduciaryTrainingStatus,
    MappingStrategy,
    MeetingStatus,
    MemberStatus,
    MotionStatus,
    MotionSubjectType,
    ProposalStatus,
    SeatClass,
    SeatStatus,
    ShareClass,
    SlotDesignation,
    TallyBasis,
    TrainingModule,
    TrainingStatus,
    Vote,
)


# --------------------------------------------------------------------------
# PRD 3.4: the two tally denominators
# --------------------------------------------------------------------------


def test_an_abstention_is_a_cast_vote_and_dilutes_support(api, full_menu):
    """Two FOR votes and one abstention leave a three-vote denominator under
    VOTES_CAST, so support lands on 66.6667 percent.

    Design: Corner/calculations/an_abstention_dilutes_the_votes_cast_denominator_while_a_recusal_shrinks_the_body
    """
    ctx = full_menu
    meeting = open_meeting(ctx, "2026-08-18", key="tally")

    motion = move_motion(
        ctx,
        meeting["id"],
        MotionSubjectType.WATCH_LIST_ACTION,
        ctx.fund("small")["id"],
        TallyBasis.VOTES_CAST,
        key="abstain",
    )
    # PRD 3.4 freezes the eligible voter count from the meeting roster.
    assert_fields(
        motion,
        eligible_voter_count=3,
        for_count=0,
        against_count=0,
        abstain_count=0,
        recuse_count=0,
        support_pct=None,
        closed_at=None,
    )
    assert_ratio(motion["carried_threshold_pct"], "0.6000", "carried_threshold_pct")

    cast_vote(ctx, motion["id"], ctx.members["chair"]["id"], Vote.FOR)
    cast_vote(ctx, motion["id"], ctx.members["finance"]["id"], Vote.FOR)
    cast_vote(ctx, motion["id"], ctx.members["hr"]["id"], Vote.ABSTAIN)

    closed = close_motion(ctx, motion["id"])
    assert_fields(
        closed,
        for_count=2,
        against_count=0,
        abstain_count=1,
        recuse_count=0,
        eligible_voter_count=3,
    )
    # 2 * 100 / (2 + 0 + 1) = 66.66666..., half up at four places.
    assert_ratio(closed["support_pct"], "66.6667", "support_pct")
    assert closed["closed_at"] is not None


def test_a_recusal_replaces_the_earlier_vote_and_leaves_the_denominator(api, full_menu):
    """A member who first votes AGAINST and then recuses leaves one vote entry,
    and the recusal is excluded from the VOTES_CAST denominator entirely.

    Design: Corner/calculations/an_abstention_dilutes_the_votes_cast_denominator_while_a_recusal_shrinks_the_body
    """
    ctx = full_menu
    meeting = open_meeting(ctx, "2026-08-18", key="tally")

    motion = move_motion(
        ctx,
        meeting["id"],
        MotionSubjectType.WATCH_LIST_ACTION,
        ctx.fund("intl")["id"],
        TallyBasis.VOTES_CAST,
        key="recuse",
    )
    cast_vote(ctx, motion["id"], ctx.members["chair"]["id"], Vote.FOR)
    cast_vote(ctx, motion["id"], ctx.members["finance"]["id"], Vote.FOR)
    cast_vote(ctx, motion["id"], ctx.members["hr"]["id"], Vote.AGAINST)
    replaced = cast_vote(
        ctx,
        motion["id"],
        ctx.members["hr"]["id"],
        Vote.RECUSE,
        recusal_basis="Affiliated with the plan recordkeeper.",
    )
    # A later vote replaces the member's earlier entry rather than adding one.
    assert len(replaced["votes"]) == 3, replaced["votes"]
    assert_fields(replaced, for_count=2, against_count=0, abstain_count=0, recuse_count=1)

    closed = close_motion(ctx, motion["id"])
    assert_fields(
        closed,
        for_count=2,
        against_count=0,
        abstain_count=0,
        recuse_count=1,
        eligible_voter_count=3,
    )
    # 2 * 100 / (2 + 0 + 0) with the recusal removed from the body.
    assert_ratio(closed["support_pct"], "100.0000", "support_pct")
    assert_status(closed, MotionStatus.CARRIED)
    assert_ratio(closed["carried_threshold_pct"], "0.6000", "carried_threshold_pct")


def test_one_for_vote_is_total_support_under_one_basis_and_a_third_under_the_other(
    api, full_menu
):
    """The identical single FOR vote out of three attending members is 100.0000
    percent under VOTES_CAST and 33.3333 percent under ELIGIBLE_VOTERS.

    Design: Corner/calculations/the_same_single_for_vote_is_100_percent_under_one_basis_and_33_percent_under_the_other
    """
    ctx = full_menu
    meeting = open_meeting(ctx, "2026-08-19", key="bases")

    cast_basis = move_motion(
        ctx,
        meeting["id"],
        MotionSubjectType.WATCH_LIST_ACTION,
        ctx.fund("small")["id"],
        TallyBasis.VOTES_CAST,
        key="cast",
    )
    cast_vote(ctx, cast_basis["id"], ctx.members["chair"]["id"], Vote.FOR)
    closed_cast = close_motion(ctx, cast_basis["id"])
    assert_fields(
        closed_cast,
        tally_basis=TallyBasis.VOTES_CAST,
        eligible_voter_count=3,
        for_count=1,
        against_count=0,
        abstain_count=0,
        recuse_count=0,
    )
    # Denominator 1 + 0 + 0 = 1.
    assert_ratio(closed_cast["support_pct"], "100.0000", "support_pct")
    assert_status(closed_cast, MotionStatus.CARRIED)

    eligible_basis = move_motion(
        ctx,
        meeting["id"],
        MotionSubjectType.WATCH_LIST_ACTION,
        ctx.fund("intl")["id"],
        TallyBasis.ELIGIBLE_VOTERS,
        key="eligible",
    )
    cast_vote(ctx, eligible_basis["id"], ctx.members["chair"]["id"], Vote.FOR)
    closed_eligible = close_motion(ctx, eligible_basis["id"])
    assert_fields(
        closed_eligible,
        tally_basis=TallyBasis.ELIGIBLE_VOTERS,
        eligible_voter_count=3,
        for_count=1,
        against_count=0,
        abstain_count=0,
        recuse_count=0,
    )
    # Denominator 3 - 0 = 3, so 1 * 100 / 3 = 33.33333..., half up.
    assert_ratio(closed_eligible["support_pct"], "33.3333", "support_pct")
    assert closed_eligible["closed_at"] is not None


def test_an_empty_tally_base_refuses_the_close_under_either_basis(api, full_menu):
    """A wholly recused body and a motion with no votes at all both close on a
    zero denominator, which is refused and leaves both motions OPEN.

    Design: Corner/calculations/the_same_single_for_vote_is_100_percent_under_one_basis_and_33_percent_under_the_other
    """
    ctx = full_menu
    meeting = open_meeting(ctx, "2026-08-19", key="bases")

    all_recused = move_motion(
        ctx,
        meeting["id"],
        MotionSubjectType.WATCH_LIST_ACTION,
        ctx.fund("small")["id"],
        TallyBasis.ELIGIBLE_VOTERS,
        key="recused",
    )
    for member_id in ctx.member_ids:
        cast_vote(
            ctx,
            all_recused["id"],
            member_id,
            Vote.RECUSE,
            recusal_basis="Conflicted on this fund family.",
        )
    validate_error(
        ctx.client.post(Paths.motion_close(all_recused["id"]), {}, ctx.chair),
        ApiErrorId.NO_ELIGIBLE_VOTERS,
        422,
    )
    still_open = read_motion(ctx.client, all_recused["id"])
    assert_status(still_open, MotionStatus.OPEN)
    assert_fields(still_open, recuse_count=3, support_pct=None, closed_at=None)

    silent = move_motion(
        ctx,
        meeting["id"],
        MotionSubjectType.WATCH_LIST_ACTION,
        ctx.fund("intl")["id"],
        TallyBasis.VOTES_CAST,
        key="silent",
    )
    validate_error(
        ctx.client.post(Paths.motion_close(silent["id"]), {}, ctx.chair),
        ApiErrorId.NO_ELIGIBLE_VOTERS,
        422,
    )
    unvoted = read_motion(ctx.client, silent["id"])
    assert_status(unvoted, MotionStatus.OPEN)
    assert_fields(
        unvoted,
        for_count=0,
        against_count=0,
        abstain_count=0,
        recuse_count=0,
        support_pct=None,
        closed_at=None,
    )


# --------------------------------------------------------------------------
# PRD 3.4: the frozen quorum verdict
# --------------------------------------------------------------------------


def _five_filled_voting_seats(api):
    """A seated menu whose committee has five filled voting seats: the three
    default seats plus a participant representative and an independent."""
    ctx = setup_full_menu(api)
    extras = (
        (
            "participant",
            "S-PAR",
            SeatClass.PARTICIPANT_REP,
            4,
            "Renata Alvarez",
            "renata.alvarez@example.com",
        ),
        (
            "independent",
            "S-IND",
            SeatClass.INDEPENDENT,
            5,
            "Desmond Whitfield",
            "desmond.whitfield@example.com",
        ),
    )
    for key, seat_code, seat_class, seat_index, name, email in extras:
        seat = create_seat(
            api,
            ctx.plan_id,
            seat_code=seat_code,
            seat_class=seat_class,
            seat_index=seat_index,
            voting=True,
        )
        ctx.seats[key] = seat
        member = appoint_member(api, seat["id"], member_name=name, person_email=email)
        ctx.members[key] = member
        make_member_active(api, member["id"], 90.00)
    ctx.refresh_plan()
    return ctx


def test_the_quorum_verdict_is_frozen_at_convene_and_a_resignation_cannot_disturb_it(api):
    """Three of five eligible voting seats clear both the floor of three and the
    strict-majority test, and the frozen figures survive a mid-session
    resignation all the way to approved minutes.

    Design: Corner/calculations/quorum_is_frozen_at_convene_and_needs_both_the_floor_and_a_strict_majority
    """
    ctx = _five_filled_voting_seats(api)

    meeting = schedule_meeting(ctx, "2026-08-20", key="frozen")
    assert_fields(
        meeting,
        eligible_voting_seat_count=0,
        voting_attendee_count=0,
        quorum_met=False,
        charter_version_pinned=None,
    )

    convened = convene(ctx, meeting["id"], attendees=ctx.member_ids)
    # 3 >= 3 clears the floor and 2 * 3 = 6 > 5 clears the strict majority.
    assert_fields(
        convened,
        eligible_voting_seat_count=5,
        voting_attendee_count=3,
        quorum_met=True,
        carried_motion_count=0,
    )
    assert_status(convened, MeetingStatus.IN_SESSION)
    assert convened["charter_version_pinned"] == ctx.plan_version

    hr_id = ctx.members["hr"]["id"]
    resigned = validate_success(
        ctx.client.post(
            Paths.end_term(hr_id),
            end_term_payload(EndTermReason.RESIGNATION),
            sponsor_headers(),
        )
    )
    assert_status(resigned, MemberStatus.RESIGNED)
    vacated = validate_success(
        ctx.client.get(Paths.seat(ctx.seats["hr"]["id"]), sponsor_headers())
    )
    assert_status(vacated, SeatStatus.VACANT)

    # The verdict was decided at convene and is never recomputed.
    mid_session = read_meeting(ctx.client, meeting["id"])
    assert_fields(
        mid_session,
        eligible_voting_seat_count=5,
        voting_attendee_count=3,
        quorum_met=True,
    )

    adjourn(ctx, meeting["id"])
    approved = approve_minutes(ctx, meeting["id"], "MIN-2026-Q0-FRZ")
    assert_status(approved, MeetingStatus.MINUTES_APPROVED)
    assert_fields(
        approved,
        eligible_voting_seat_count=5,
        voting_attendee_count=3,
        quorum_met=True,
    )


def test_two_attendees_below_the_floor_of_three_block_the_close_and_the_minutes(api):
    """With four eligible voting seats and two attendees the majority test
    passes but the floor of three does not, so the motion cannot be closed and
    the minutes cannot be approved.

    Design: Corner/calculations/quorum_is_frozen_at_convene_and_needs_both_the_floor_and_a_strict_majority
    """
    ctx = _five_filled_voting_seats(api)
    validate_success(
        ctx.client.post(
            Paths.end_term(ctx.members["hr"]["id"]),
            end_term_payload(EndTermReason.RESIGNATION),
            sponsor_headers(),
        )
    )

    meeting = schedule_meeting(ctx, "2026-08-21", key="inquorate")
    convened = convene(
        ctx,
        meeting["id"],
        attendees=[ctx.members["chair"]["id"], ctx.members["finance"]["id"]],
    )
    # 2 * 2 = 4 is not strictly greater than 4 either, and 2 < 3.
    assert_fields(
        convened,
        eligible_voting_seat_count=4,
        voting_attendee_count=2,
        quorum_met=False,
    )
    assert_status(convened, MeetingStatus.IN_SESSION)

    motion = move_motion(
        ctx,
        meeting["id"],
        MotionSubjectType.WATCH_LIST_ACTION,
        ctx.fund("small")["id"],
        TallyBasis.VOTES_CAST,
        key="inquorate",
    )
    cast_vote(ctx, motion["id"], ctx.members["chair"]["id"], Vote.FOR)
    cast_vote(ctx, motion["id"], ctx.members["finance"]["id"], Vote.FOR)

    validate_error(
        ctx.client.post(Paths.motion_close(motion["id"]), {}, ctx.chair),
        ApiErrorId.QUORUM_NOT_MET,
        409,
    )
    unclosed = read_motion(ctx.client, motion["id"])
    assert_status(unclosed, MotionStatus.OPEN)
    assert_fields(unclosed, for_count=2, support_pct=None, closed_at=None)

    adjourn(ctx, meeting["id"])
    withdrawn = read_motion(ctx.client, motion["id"])
    assert_status(withdrawn, MotionStatus.WITHDRAWN)
    assert withdrawn["closed_at"] is not None

    validate_error(
        ctx.client.post(
            Paths.minutes_approve(meeting["id"]),
            minutes_payload("MIN-2026-Q0-INQ"),
            ctx.chair,
        ),
        ApiErrorId.QUORUM_NOT_MET,
        409,
    )
    stranded = read_meeting(ctx.client, meeting["id"])
    assert_status(stranded, MeetingStatus.ADJOURNED)
    assert_fields(stranded, minutes_approved_at=None, carried_motion_count=0)


# --------------------------------------------------------------------------
# PRD 3.7: the notice lead stack
# --------------------------------------------------------------------------


def _menu_with_seated_qdia(api):
    """A seated five-slot menu plus a sixth qualified-default slot occupied by
    the winning target-date suite."""
    ctx = setup_qdia_candidates(api)
    motion = hold_meeting_and_carry_motion(
        ctx,
        MotionSubjectType.TARGET_DATE_SELECTION,
        ctx.fund("td_thru")["id"],
        meeting_date="2026-08-17",
        minutes_doc_ref="MIN-2026-Q0-TDS",
        key="tds",
    )
    select_target_date_suite(ctx, "td_thru", motion["id"])
    ctx.refresh_plan()
    return ctx


def test_the_notice_lead_is_30_days_plus_a_15_day_map_to_qdia_surcharge(api):
    """On a CORE slot a direct mapping stays at the plan's 30-day base, a
    mapping into the qualified default adds 15 days and a re-enrolment adds 30.

    Design: Corner/calculations/the_notice_lead_stack_produces_30_45_60_and_90_days_from_the_same_base
    """
    ctx = _menu_with_seated_qdia(api)
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
    create_fund(
        ctx,
        "bond_b",
        ticker="BNDGX",
        fund_name="Bulwark Core Bond Institutional",
        asset_class_code=AssetClass.CORE_BOND,
        share_class_code=ShareClass.INSTITUTIONAL,
        gross_expense_ratio_bps=22,
        net_expense_ratio_bps=22,
        revenue_share_bps=0,
        peer_median_expense_bps=30,
        track_record_quarters=48,
        manager_tenure_quarters=28,
        style_drift_r2=0.9600,
        plan_assets_cents=0,
    )

    arms = (
        ("small", "small", "small_b", MappingStrategy.DIRECT_MAP, 30),
        ("lc", "lc_a", "lc_b", MappingStrategy.MAP_TO_QDIA, 45),
        ("bond", "bond", "bond_b", MappingStrategy.REENROLLMENT, 60),
    )
    for slot_key, outgoing, incoming, strategy, expected_days in arms:
        drafted = draft_proposal(
            ctx,
            slot_key,
            outgoing,
            incoming,
            key=slot_key,
            mapping_strategy=strategy,
        )
        assert_status(drafted, ProposalStatus.DRAFT)
        # PRD 3.7 computes the lead time at submission.
        submitted = submit_proposal(ctx, drafted["id"], key=slot_key)
        assert_status(submitted, ProposalStatus.UNDER_REVIEW)
        assert_fields(
            submitted,
            mapping_strategy=strategy,
            notice_lead_days_required=expected_days,
            pinned_ips_id=ctx.ips_id,
        )


def test_a_reenrolment_into_the_qdia_slot_stacks_to_90_days(api):
    """The qualified-default surcharge applies on an ERISA-covered plan, the
    re-enrolment surcharge stacks on top of it, and the 15-day mapping
    surcharge never applies to the qualified-default slot itself.

    Design: Corner/calculations/the_notice_lead_stack_produces_30_45_60_and_90_days_from_the_same_base
    """
    ctx = _menu_with_seated_qdia(api)
    assert ctx.plan["erisa_covered"] is True
    assert ctx.slot("qdia")["designation"] == SlotDesignation.QDIA

    arms = (
        # 30 base + 30 qualified default + 30 re-enrolment.
        (MappingStrategy.REENROLLMENT, 90),
        # 30 base + 30 qualified default.
        (MappingStrategy.DIRECT_MAP, 60),
        # The 15-day surcharge needs a slot that is not the qualified default.
        (MappingStrategy.MAP_TO_QDIA, 60),
    )
    for strategy, expected_days in arms:
        drafted = draft_proposal(
            ctx,
            "qdia",
            "td_thru",
            "td_tie",
            key=f"qdia_{strategy}",
            mapping_strategy=strategy,
        )
        submitted = submit_proposal(ctx, drafted["id"], key=f"qdia_{strategy}")
        assert_status(submitted, ProposalStatus.UNDER_REVIEW)
        assert_fields(
            submitted,
            mapping_strategy=strategy,
            notice_lead_days_required=expected_days,
        )


# --------------------------------------------------------------------------
# PRD 3.2: the training currency window
# --------------------------------------------------------------------------


def _training_records(ctx, member_id):
    rows, _meta = validate_paginated(
        ctx.client.get(
            Paths.TRAINING_RECORDS,
            auditor_headers(),
            paginate_params(limit=50, member_id=member_id),
        )
    )
    return rows


def test_a_seven_quarter_gap_still_counts_as_current_training(api, full_menu):
    """A quarter gap of seven against a validity of eight quarters is strictly
    less than the window, so the whole committee still convenes and votes.

    Design: Corner/calculations/training_stays_current_for_seven_quarters_and_lapses_on_the_eighth
    """
    ctx = full_menu
    for _ in range(7):
        advance_quarter(ctx)
    assert ctx.plan["fiscal_quarter_index"] == 7

    records = _training_records(ctx, ctx.chair_id)
    assert len(records) == 2, records
    for record in records:
        # 7 - 0 = 7 is strictly less than the record's validity_quarters.
        assert_status(record, TrainingStatus.COMPLETED)
        assert_fields(record, completed_quarter_index=0, validity_quarters=8)
    for key in ("chair", "finance", "hr"):
        member = read_member(ctx.client, ctx.members[key]["id"])
        assert_fields(
            member,
            status=MemberStatus.ACTIVE,
            fiduciary_training_status=FiduciaryTrainingStatus.CURRENT,
        )

    meeting = open_meeting(ctx, "2026-08-25", quarter_index=7, key="q7")
    assert_fields(
        meeting,
        eligible_voting_seat_count=3,
        voting_attendee_count=3,
        quorum_met=True,
    )
    motion = move_motion(
        ctx,
        meeting["id"],
        MotionSubjectType.WATCH_LIST_ACTION,
        ctx.fund("small")["id"],
        TallyBasis.VOTES_CAST,
        key="current",
    )
    for member_id in ctx.member_ids:
        cast_vote(ctx, motion["id"], member_id, Vote.FOR)
    closed = close_motion(ctx, motion["id"])
    assert_fields(closed, for_count=3, eligible_voter_count=3)
    assert_ratio(closed["support_pct"], "100.0000", "support_pct")
    assert_status(closed, MotionStatus.CARRIED)


def test_the_eighth_quarter_lapses_the_training_and_strands_the_meeting(api, full_menu):
    """A quarter gap that reaches the eight-quarter validity expires every
    record, which blocks the vote and the minutes while leaving the frozen
    quorum figures untouched, and a fresh completion restarts the window.

    Design: Corner/calculations/training_stays_current_for_seven_quarters_and_lapses_on_the_eighth
    """
    ctx = full_menu
    for _ in range(7):
        advance_quarter(ctx)
    meeting = open_meeting(ctx, "2026-08-25", quarter_index=7, key="q7")
    motion = move_motion(
        ctx,
        meeting["id"],
        MotionSubjectType.WATCH_LIST_ACTION,
        ctx.fund("small")["id"],
        TallyBasis.VOTES_CAST,
        key="lapsed",
    )

    advance_quarter(ctx)
    assert ctx.plan["fiscal_quarter_index"] == 8
    for record in _training_records(ctx, ctx.chair_id):
        # 8 - 0 = 8 has reached the validity window.
        assert_status(record, TrainingStatus.EXPIRED)
    lapsed_chair = read_member(ctx.client, ctx.chair_id)
    assert_fields(
        lapsed_chair,
        status=MemberStatus.ACTIVE,
        fiduciary_training_status=FiduciaryTrainingStatus.EXPIRED,
    )

    validate_error(
        ctx.client.post(
            Paths.votes(motion["id"]),
            vote_payload(ctx.chair_id, Vote.FOR),
            ctx.chair,
        ),
        ApiErrorId.TRAINING_NOT_CURRENT,
        409,
    )
    unvoted = read_motion(ctx.client, motion["id"])
    assert_status(unvoted, MotionStatus.OPEN)
    assert_fields(unvoted, for_count=0, support_pct=None)

    frozen = read_meeting(ctx.client, meeting["id"])
    assert_fields(
        frozen,
        eligible_voting_seat_count=3,
        voting_attendee_count=3,
        quorum_met=True,
    )

    adjourn(ctx, meeting["id"])
    withdrawn = read_motion(ctx.client, motion["id"])
    assert_status(withdrawn, MotionStatus.WITHDRAWN)

    validate_error(
        ctx.client.post(
            Paths.minutes_approve(meeting["id"]),
            minutes_payload("MIN-2026-Q7-LAP"),
            ctx.chair,
        ),
        ApiErrorId.TRAINING_NOT_CURRENT,
        409,
    )
    stranded = read_meeting(ctx.client, meeting["id"])
    assert_status(stranded, MeetingStatus.ADJOURNED)

    for module in (TrainingModule.FIDUCIARY_DUTIES, TrainingModule.IPS_MECHANICS):
        record = assign_training(ctx.client, ctx.chair_id, module_code=module)
        complete_training(ctx.client, record["id"], ctx.chair_id, 96.00)
    restored = read_member(ctx.client, ctx.chair_id)
    assert_fields(
        restored, fiduciary_training_status=FiduciaryTrainingStatus.CURRENT
    )
    fresh = find_by(
        _training_records(ctx, ctx.chair_id),
        module_code=TrainingModule.FIDUCIARY_DUTIES,
        status=TrainingStatus.COMPLETED,
    )
    assert_fields(fresh, completed_quarter_index=8, validity_quarters=8)

    later = open_meeting(
        ctx, "2026-08-26", quarter_index=8, key="q8", attendees=[ctx.chair_id]
    )
    # Only the chair is both ACTIVE and current, so the floor of three fails.
    assert_fields(
        later,
        eligible_voting_seat_count=1,
        voting_attendee_count=1,
        quorum_met=False,
    )
