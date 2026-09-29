"""Validation ordering: when one request breaks two rules, PRD 2.12 decides
which error comes back.

Every scenario below is built so that both candidate gates are violated at the
same instant, and the test then pins the single error id the priority ladder in
PRD 2.12 makes mandatory ("an implementation that returns a correct-but-later
error for a request that also violates an earlier rule is wrong").
"""

from test_helpers.api_client import headers_for
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    NON_EXISTENT_UUID,
    assert_capacity_triple,
    assert_fields,
    assert_ratio,
    assert_status,
    get_success_data,
    validate_error,
)
from test_helpers.factories import (
    Paths,
    charter_payload,
    end_term_payload,
    engagement_payload,
    fund_payload,
    member_payload,
    proposal_payload,
    scorecard_payload,
    seat_fund_payload,
    slot_payload,
    vote_payload,
)
from test_helpers.fixtures import (
    CLEAN_SCORECARDS,
    adjourn,
    adopt_ips,
    advance_quarter,
    approve_minutes,
    approve_proposal,
    carry_motion_unanimously,
    create_engagement,
    create_fund,
    create_seat,
    create_slot,
    draft_ips,
    draft_proposal,
    finalize_review,
    hold_meeting_and_carry_motion,
    move_motion,
    open_meeting,
    present_review,
    read_fund,
    read_meeting,
    read_motion,
    read_plan,
    read_review,
    read_slot,
    register_plan,
    seat_fund,
    submit_proposal,
    submit_scorecard,
)
from test_helpers.test_users import (
    TestUsers,
    chair_headers,
    consultant_headers,
    member_headers,
    recordkeeper_headers,
    sponsor_headers,
)
from test_helpers.types import (
    AssetClass,
    CharterStatus,
    CreditAccrualStatus,
    EndTermReason,
    EngagementStatus,
    FundMenuStatus,
    MeetingStatus,
    MemberStatus,
    MenuPosture,
    MotionStatus,
    MotionSubjectType,
    ProposalStatus,
    ProviderRole,
    ReviewStatus,
    Role,
    SeatClass,
    SeatStatus,
    SlotStatus,
)

JSON_ONLY_HEADERS = {"Content-Type": "application/json"}


def _reopen_and_refinalize(ctx, meeting_date, minutes_doc_ref, key, motion_subject=None):
    """Reopen the finalized quarter, rescore one fund, present the review into a
    fresh meeting and finalize it again, optionally carrying one motion at that
    meeting (PRD 3.5 five hops, PRD 3.6 reopen)."""
    review_id = ctx.review["id"]
    ctx.review = get_success_data(
        ctx.client.post(
            Paths.review_reopen(review_id),
            {"reason": "Recordkeeper restated the quarter's expense feed."},
            sponsor_headers(),
        )
    )
    submit_scorecard(ctx, "small", dict(CLEAN_SCORECARDS["small"]), key=f"small_{key}")
    meeting = open_meeting(ctx, meeting_date, key=key)
    present_review(ctx, meeting["id"])
    motion = None
    if motion_subject is not None:
        motion = carry_motion_unanimously(
            ctx, meeting["id"], motion_subject[0], motion_subject[1], key=key
        )
    adjourn(ctx, meeting["id"])
    approve_minutes(ctx, meeting["id"], minutes_doc_ref)
    finalize_review(ctx)
    return meeting, motion


def test_engagement_windows_collide_but_a_reversed_window_answers_first(api, governed_plan):
    """A reversed engagement term is a shape failure even when it also collides
    with the incumbent's window, while an abutting window and a different
    provider role are both accepted.

    Design: Corner/validations/interval_algebra_bites_on_engagements_and_is_vacuous_on_seats
    """
    ctx = governed_plan
    incumbent = create_engagement(ctx)
    assert_status(incumbent, EngagementStatus.PENDING)
    assert_fields(
        incumbent, term_start_date="2026-01-01", term_end_date="2027-12-31",
        provider_role=ProviderRole.RECORDKEEPER,
    )

    # Same plan, same role, a window that shares the incumbent's last day.
    colliding = api.post(
        Paths.ENGAGEMENTS,
        engagement_payload(
            ctx.plan_id,
            provider_name="Southwind Recordkeeping LLC",
            term_start_date="2027-12-31",
            term_end_date="2029-12-31",
        ),
        sponsor_headers(),
    )
    validate_error(colliding, ApiErrorId.ENGAGEMENT_TERM_OVERLAP)

    # Reversed dates that also sit inside the incumbent's window: PRD 2.12
    # answers the shape check at priority 38 before the overlap at priority 67.
    reversed_window = api.post(
        Paths.ENGAGEMENTS,
        engagement_payload(
            ctx.plan_id,
            provider_name="Southwind Recordkeeping LLC",
            term_start_date="2027-06-30",
            term_end_date="2026-06-01",
        ),
        sponsor_headers(),
    )
    validate_error(reversed_window, ApiErrorId.INVALID_REQUEST)

    # Closed intervals that merely abut do not overlap.
    successor = get_success_data(
        api.post(
            Paths.ENGAGEMENTS,
            engagement_payload(
                ctx.plan_id,
                provider_name="Southwind Recordkeeping LLC",
                term_start_date="2028-01-01",
                term_end_date="2029-12-31",
            ),
            sponsor_headers(),
        ),
        201,
    )
    assert_status(successor, EngagementStatus.PENDING)

    # The exclusion is per plan and provider role, so an advisor may hold the
    # incumbent's exact window.
    advisor = get_success_data(
        api.post(
            Paths.ENGAGEMENTS,
            engagement_payload(
                ctx.plan_id,
                provider_name="Cedar Ridge Advisors LLC",
                provider_role=ProviderRole.ADVISOR,
                term_start_date="2026-01-01",
                term_end_date="2027-12-31",
            ),
            sponsor_headers(),
        ),
        201,
    )
    assert_fields(advisor, provider_role=ProviderRole.ADVISOR, term_start_date="2026-01-01")


def test_seat_occupancy_answers_before_any_term_arithmetic(api, governed_plan):
    """Appointing onto a filled seat is refused for occupancy, and once the
    sitting member's term is ended the identical window is free again.

    Design: Corner/validations/interval_algebra_bites_on_engagements_and_is_vacuous_on_seats
    """
    ctx = governed_plan
    hr_seat = ctx.seats["hr"]
    sitting = ctx.members["hr"]
    plan_before = read_plan(api, ctx.plan_id)

    # The seat is FILLED and the requested window overlaps the sitting term, so
    # PRD 2.12 answers the state check at priority 42 before the overlap at 66.
    refused = api.post(
        Paths.MEMBERS,
        member_payload(
            hr_seat["id"],
            member_name="Priya Raghunathan",
            person_email="priya.raghunathan@example.com",
            term_start_date="2026-06-01",
            term_end_date="2027-06-30",
        ),
        sponsor_headers(),
    )
    validate_error(refused, ApiErrorId.SEAT_NOT_VACANT)

    ended = get_success_data(
        api.post(
            Paths.end_term(sitting["id"]),
            end_term_payload(EndTermReason.RESIGNATION),
            sponsor_headers(),
        )
    )
    assert_status(ended, MemberStatus.RESIGNED)
    vacated = get_success_data(api.get(Paths.seat(hr_seat["id"]), sponsor_headers()))
    assert_status(vacated, SeatStatus.VACANT)
    plan_after = read_plan(api, ctx.plan_id)
    assert (
        plan_after["documented_acceptance_count"]
        == plan_before["documented_acceptance_count"] - 1
    )

    # A terminal appointment is invisible to the overlap check.
    successor = get_success_data(
        api.post(
            Paths.MEMBERS,
            member_payload(
                hr_seat["id"],
                member_name="Priya Raghunathan",
                person_email="priya.raghunathan@example.com",
                term_start_date=sitting["term_start_date"],
                term_end_date=sitting["term_end_date"],
            ),
            sponsor_headers(),
        ),
        201,
    )
    assert_status(successor, MemberStatus.APPOINTED)
    assert_fields(
        successor,
        term_start_date=sitting["term_start_date"],
        term_end_date=sitting["term_end_date"],
    )


def test_charter_adoption_counts_only_non_retired_voting_seats(api):
    """Adoption needs at least two voting seats, and non-voting seats do not
    help the count.

    Design: Corner/validations/charter_adoption_counts_seats_two_ways_and_the_shape_check_beats_both
    """
    plan = register_plan(
        api,
        plan_name="Larkspur Dairy Co-operative 401(k) Plan",
        plan_sponsor_name="Larkspur Dairy Co-operative",
    )
    create_seat(api, plan["id"], seat_code="S-CHAIR", seat_class=SeatClass.CHAIR, seat_index=1)

    too_few = api.post(
        Paths.charter_adopt(plan["id"]),
        charter_payload(quorum_min_voting_members=2, max_voting_seats=2),
        sponsor_headers(),
    )
    validate_error(too_few, ApiErrorId.CHARTER_SEATS_INSUFFICIENT)

    # A non-voting seat is not a voting seat, so the count is still one.
    create_seat(
        api,
        plan["id"],
        seat_code="S-PART",
        seat_class=SeatClass.PARTICIPANT_REP,
        voting=False,
        seat_index=2,
    )
    still_too_few = api.post(
        Paths.charter_adopt(plan["id"]),
        charter_payload(quorum_min_voting_members=2, max_voting_seats=2),
        sponsor_headers(),
    )
    validate_error(still_too_few, ApiErrorId.CHARTER_SEATS_INSUFFICIENT)


def test_charter_adoption_refuses_a_cap_below_the_seats_that_already_exist(api, committee):
    """The submitted max_voting_seats is checked against the seats the plan
    already carries, and a cap that clears them adopts.

    Design: Corner/validations/charter_adoption_counts_seats_two_ways_and_the_shape_check_beats_both
    """
    ctx = committee
    before = read_plan(api, ctx.plan_id)

    too_many = api.post(
        Paths.charter_adopt(ctx.plan_id),
        charter_payload(quorum_min_voting_members=2, max_voting_seats=2),
        sponsor_headers(),
    )
    validate_error(too_many, ApiErrorId.CHARTER_SEATS_INSUFFICIENT)
    assert read_plan(api, ctx.plan_id)["version"] == before["version"]

    adopted = get_success_data(
        api.post(
            Paths.charter_adopt(ctx.plan_id),
            charter_payload(
                quorum_min_voting_members=3,
                max_voting_seats=5,
                charter_doc_ref="CHARTER-2026-B",
            ),
            sponsor_headers(),
        )
    )
    assert_fields(
        adopted,
        charter_status=CharterStatus.ADOPTED,
        quorum_min_voting_members=3,
        max_voting_seats=5,
        charter_doc_ref="CHARTER-2026-B",
        charter_adopted_quarter_index=0,
    )
    assert adopted["version"] == before["version"] + 1


def test_identity_and_scope_answer_in_ladder_order_not_in_request_order(api, full_menu):
    """Eight rejected calls walk the top of the ladder in order: missing
    identity, role, committee identity, self, existence and finally cross-plan
    scope, and none of them mutates anything.

    Design: Corner/validations/the_auth_and_existence_ladder_answers_in_priority_order_not_in_request_order
    """
    ctx = full_menu
    finance_id = ctx.members["finance"]["id"]
    meeting = open_meeting(ctx, "2026-08-22", key="ladder")
    motion = move_motion(
        ctx, meeting["id"], MotionSubjectType.WATCH_LIST_ACTION, ctx.fund("small")["id"], key="ladder"
    )
    empty_slot = create_slot(ctx, "em", AssetClass.EMERGING_MKTS, 6)
    other_plan = register_plan(
        api,
        plan_name="Beacon Foods 401(k) Plan",
        plan_sponsor_name="Beacon Foods Incorporated",
    )
    foreign_fund = get_success_data(
        api.post(
            Paths.FUNDS,
            fund_payload(
                other_plan["id"],
                ticker="EMGFX",
                fund_name="Beacon Emerging Markets Equity",
                asset_class_code=AssetClass.EMERGING_MKTS,
                plan_assets_cents=0,
            ),
            consultant_headers(),
        ),
        201,
    )

    # 1. No identity headers at all, on a motion that does not exist either.
    validate_error(
        api.request(
            "POST",
            Paths.votes(NON_EXISTENT_UUID),
            vote_payload(finance_id),
            JSON_ONLY_HEADERS,
        ),
        ApiErrorId.MISSING_USER_CONTEXT,
    )
    # 2. A role that may never vote.
    validate_error(
        api.post(Paths.votes(NON_EXISTENT_UUID), vote_payload(finance_id), recordkeeper_headers()),
        ApiErrorId.ROLE_NOT_PERMITTED,
    )
    # 3. A permitted role whose user id is not a committee member.
    validate_error(
        api.post(
            Paths.votes(NON_EXISTENT_UUID),
            vote_payload(finance_id),
            headers_for(TestUsers.INVESTMENT_CONSULTANT, Role.COMMITTEE_MEMBER),
        ),
        ApiErrorId.ACTOR_NOT_COMMITTEE_MEMBER,
    )
    # 4. A chair-only act attempted by a member whose seat is not the CHAIR seat.
    validate_error(
        api.post(Paths.adjourn(meeting["id"]), {}, chair_headers(finance_id)),
        ApiErrorId.ACTOR_NOT_COMMITTEE_MEMBER,
    )
    # 5. A member voting in someone else's name: identity beats existence.
    validate_error(
        api.post(
            Paths.votes(motion["id"]),
            vote_payload(NON_EXISTENT_UUID),
            member_headers(finance_id),
        ),
        ApiErrorId.ACTOR_NOT_SELF,
    )
    # 6. The same member voting as himself, on a motion that does not exist.
    validate_error(
        api.post(Paths.votes(NON_EXISTENT_UUID), vote_payload(finance_id), member_headers(finance_id)),
        ApiErrorId.RESOURCE_NOT_FOUND,
    )
    # 7. A body reference that resolves to nothing.
    validate_error(
        api.post(
            Paths.seat_fund(empty_slot["id"]),
            seat_fund_payload(NON_EXISTENT_UUID),
            consultant_headers(),
        ),
        ApiErrorId.RESOURCE_NOT_FOUND,
    )
    # 8. Every reference resolves, but they belong to two different plans.
    validate_error(
        api.post(
            Paths.seat_fund(empty_slot["id"]),
            seat_fund_payload(foreign_fund["id"]),
            consultant_headers(),
        ),
        ApiErrorId.CROSS_PLAN_REFERENCE,
    )

    assert_status(read_slot(api, empty_slot["id"]), SlotStatus.EMPTY)
    assert_status(read_meeting(api, meeting["id"]), MeetingStatus.IN_SESSION)
    assert_status(read_motion(api, motion["id"]), MotionStatus.OPEN)
    assert_capacity_triple(read_plan(api, ctx.plan_id), occupied=5, reserved=0, available=1)


def _adopt_stricter_statement(ctx):
    """Adopt a second statement, IPS-2026-B, whose track-record floor is 24
    quarters and whose peer multiple is 1.10 (PRD 3.3 policy eligibility)."""
    stricter = draft_ips(
        ctx.client,
        ctx.plan_id,
        version_label="IPS-2026-B",
        effective_date="2026-08-05",
        min_track_record_quarters=24,
        expense_peer_multiple=1.10,
    )
    motion = hold_meeting_and_carry_motion(
        ctx,
        MotionSubjectType.IPS_ADOPTION,
        stricter["id"],
        meeting_date="2026-08-05",
        minutes_doc_ref="MIN-2026-Q0-002",
        key="ips_b",
    )
    ctx.ips = adopt_ips(ctx, stricter["id"], motion["id"])
    return ctx.ips


def test_the_criteria_gate_answers_before_the_pinned_statement_is_stale(api, adopted_ips):
    """A fund that fails policy eligibility under either statement is refused
    for its criteria even though the slot's pinned statement is also stale,
    while an eligible fund gets the staleness answer.

    Design: Corner/validations/the_criteria_gate_runs_before_the_gate_that_says_which_ips_is_current
    """
    ctx = adopted_ips
    slot = create_slot(ctx, "lc", AssetClass.US_LARGE_CAP, 1)
    _adopt_stricter_statement(ctx)

    # 60 basis points against a peer median of 40 is over the cap of both
    # statements (50 under IPS-2026-A, 44 under IPS-2026-B).
    rich = create_fund(
        ctx,
        "rich",
        ticker="RAINX",
        fund_name="Rainier Large Cap Growth",
        asset_class_code=AssetClass.US_LARGE_CAP,
        gross_expense_ratio_bps=60,
        net_expense_ratio_bps=60,
        revenue_share_bps=10,
        peer_median_expense_bps=40,
        track_record_quarters=40,
        manager_tenure_quarters=20,
        style_drift_r2=0.9200,
        plan_assets_cents=0,
    )
    validate_error(
        api.post(Paths.seat_fund(slot["id"]), seat_fund_payload(rich["id"]), consultant_headers()),
        ApiErrorId.FUND_FAILS_IPS_CRITERIA,
    )

    # 40 basis points clears both caps, so only the stale pin is left.
    lean = create_fund(
        ctx,
        "lean",
        ticker="RAINY",
        fund_name="Rainier Large Cap Index",
        asset_class_code=AssetClass.US_LARGE_CAP,
        gross_expense_ratio_bps=40,
        net_expense_ratio_bps=40,
        revenue_share_bps=10,
        peer_median_expense_bps=40,
        track_record_quarters=40,
        manager_tenure_quarters=20,
        style_drift_r2=0.9200,
        plan_assets_cents=0,
    )
    validate_error(
        api.post(Paths.seat_fund(slot["id"]), seat_fund_payload(lean["id"]), consultant_headers()),
        ApiErrorId.IPS_VERSION_STALE,
    )

    assert_status(read_slot(api, slot["id"]), SlotStatus.EMPTY)
    assert_capacity_triple(read_plan(api, ctx.plan_id), occupied=0, reserved=0, available=6)


def test_eligibility_boundaries_are_inclusive_and_a_slot_needs_an_adopted_statement(api, adopted_ips):
    """Against the statement the slot is actually pinned to, one basis point
    over the cap fails while the exact cap, the exact track-record floor and the
    exact r-squared floor all pass; a plan with no adopted statement cannot own
    a slot at all.

    Design: Corner/validations/the_criteria_gate_runs_before_the_gate_that_says_which_ips_is_current
    """
    ctx = adopted_ips
    _adopt_stricter_statement(ctx)
    slot = create_slot(ctx, "em", AssetClass.EMERGING_MKTS, 2)
    assert_fields(slot, ips_id=ctx.ips_id, status=SlotStatus.EMPTY)

    over_cap = create_fund(
        ctx,
        "over_cap",
        ticker="EMBRX",
        fund_name="Emerald Bay Emerging Markets",
        asset_class_code=AssetClass.EMERGING_MKTS,
        gross_expense_ratio_bps=45,
        net_expense_ratio_bps=45,
        revenue_share_bps=0,
        peer_median_expense_bps=40,
        track_record_quarters=40,
        manager_tenure_quarters=20,
        style_drift_r2=0.9200,
        plan_assets_cents=0,
    )
    validate_error(
        api.post(
            Paths.seat_fund(slot["id"]), seat_fund_payload(over_cap["id"]), consultant_headers()
        ),
        ApiErrorId.FUND_FAILS_IPS_CRITERIA,
    )

    # Exactly at the cap of 44 basis points, exactly 24 quarters of track record
    # and exactly at the 0.8000 style floor.
    at_cap = create_fund(
        ctx,
        "at_cap",
        ticker="EMOKX",
        fund_name="Emerald Bay Emerging Markets Select",
        asset_class_code=AssetClass.EMERGING_MKTS,
        gross_expense_ratio_bps=44,
        net_expense_ratio_bps=44,
        revenue_share_bps=0,
        peer_median_expense_bps=40,
        track_record_quarters=24,
        manager_tenure_quarters=20,
        style_drift_r2=0.8000,
        plan_assets_cents=0,
    )
    seated = seat_fund(ctx, "em", "at_cap")
    assert_fields(seated, status=SlotStatus.ACTIVE, current_fund_id=at_cap["id"])
    assert_fields(
        read_fund(api, at_cap["id"]),
        menu_status=FundMenuStatus.ACTIVE,
        credit_accrual_status=CreditAccrualStatus.ACCRUING,
    )
    assert_capacity_triple(read_plan(api, ctx.plan_id), occupied=1, reserved=0, available=5)

    bare_plan = register_plan(
        api,
        plan_name="Copperfield Tooling 401(k) Plan",
        plan_sponsor_name="Copperfield Tooling LLC",
    )
    bare_statement = draft_ips(api, bare_plan["id"])
    validate_error(
        api.post(
            Paths.SLOTS,
            slot_payload(
                bare_plan["id"],
                bare_statement["id"],
                asset_class_code=AssetClass.CORE_BOND,
                slot_index=1,
            ),
            consultant_headers(),
        ),
        ApiErrorId.NO_ADOPTED_IPS,
    )


def test_review_state_answers_before_the_scorecard_concurrency_token(api, breach_quarter):
    """A scorecard carrying a stale expected_review_version against a review
    that has already left scoring gets the state answer, not the 412.

    Design: Corner/validations/the_state_and_posture_gates_both_outrank_the_optimistic_concurrency_check
    """
    ctx = breach_quarter
    review = read_review(api, ctx.review["id"])
    assert_status(review, ReviewStatus.PENDING_MINUTES)
    assert review["version"] > 1

    stale = api.post(
        Paths.SCORECARDS,
        scorecard_payload(review["id"], ctx.fund("tips")["id"], 1, **CLEAN_SCORECARDS["tips"]),
        consultant_headers(),
    )
    validate_error(stale, ApiErrorId.REVIEW_NOT_SCORING)
    unchanged = read_review(api, review["id"])
    assert unchanged["version"] == review["version"]
    assert unchanged["submitted_scorecard_count"] == review["submitted_scorecard_count"]

    finalize_review(ctx)
    finalized = read_review(api, review["id"])
    assert_status(finalized, ReviewStatus.FINALIZED)

    # A perfectly fresh token does not help either: the state gate is above it.
    fresh = api.post(
        Paths.SCORECARDS,
        scorecard_payload(
            review["id"], ctx.fund("tips")["id"], finalized["version"], **CLEAN_SCORECARDS["tips"]
        ),
        consultant_headers(),
    )
    validate_error(fresh, ApiErrorId.REVIEW_NOT_SCORING)


def test_a_frozen_posture_answers_before_the_plan_concurrency_token(api, breach_quarter):
    """Once retiring a clean slot pushes the at-risk ratio to 0.5000, a proposal
    creation is refused for the posture whether its expected_plan_version is
    stale or current.

    Design: Corner/validations/the_state_and_posture_gates_both_outrank_the_optimistic_concurrency_check
    """
    ctx = breach_quarter
    finalize_review(ctx)
    restricted = read_plan(api, ctx.plan_id)
    assert_ratio(restricted["at_risk_slot_ratio"], "0.4000")
    assert_status(restricted, MenuPosture.RESTRICTED, field="menu_posture")

    retired = get_success_data(
        api.post(
            Paths.slot_retire(ctx.slot("tips")["id"]),
            {"reason": "Consolidating the inflation-protected sleeve."},
            sponsor_headers(),
        )
    )
    assert_status(retired, SlotStatus.RETIRED)
    frozen = read_plan(api, ctx.plan_id)
    assert_ratio(frozen["at_risk_slot_ratio"], "0.5000")
    assert_status(frozen, MenuPosture.FROZEN, field="menu_posture")

    stale_token = api.post(
        Paths.REPLACEMENTS,
        proposal_payload(
            ctx.plan_id,
            ctx.slot("lc")["id"],
            ctx.fund("lc_a")["id"],
            ctx.fund("lc_b")["id"],
            1,
        ),
        consultant_headers(),
    )
    validate_error(stale_token, ApiErrorId.MENU_FROZEN)

    current_token = api.post(
        Paths.REPLACEMENTS,
        proposal_payload(
            ctx.plan_id,
            ctx.slot("lc")["id"],
            ctx.fund("lc_a")["id"],
            ctx.fund("lc_b")["id"],
            frozen["version"],
        ),
        consultant_headers(),
    )
    validate_error(current_token, ApiErrorId.MENU_FROZEN)
    assert read_plan(api, ctx.plan_id)["version"] == frozen["version"]


def test_restricted_posture_blocks_only_writes_touching_an_impaired_slot(api, breach_quarter):
    """Under RESTRICTED, a replacement on the at-risk international slot is
    refused while the identical write on the healthy large-cap slot and a
    seating into an untouched empty slot both go through.

    Design: Corner/validations/restricted_posture_blocks_only_the_writes_that_touch_an_impaired_slot
    """
    ctx = breach_quarter
    finalize_review(ctx)
    plan = read_plan(api, ctx.plan_id)
    assert_status(plan, MenuPosture.RESTRICTED, field="menu_posture")
    assert_ratio(plan["at_risk_slot_ratio"], "0.4000")
    assert_status(read_slot(api, ctx.slot("intl")["id"]), SlotStatus.AT_RISK)
    assert_status(read_slot(api, ctx.slot("lc")["id"]), SlotStatus.ACTIVE)

    create_fund(
        ctx,
        "intl_b",
        ticker="INTGX",
        fund_name="Ironwood International Growth",
        asset_class_code=AssetClass.INTL_DEVELOPED,
        gross_expense_ratio_bps=30,
        net_expense_ratio_bps=30,
        revenue_share_bps=0,
        peer_median_expense_bps=35,
        track_record_quarters=40,
        manager_tenure_quarters=20,
        style_drift_r2=0.9100,
        plan_assets_cents=0,
    )
    create_fund(
        ctx,
        "em",
        ticker="EMOKX",
        fund_name="Ironwood Emerging Markets",
        asset_class_code=AssetClass.EMERGING_MKTS,
        gross_expense_ratio_bps=30,
        net_expense_ratio_bps=30,
        revenue_share_bps=0,
        peer_median_expense_bps=35,
        track_record_quarters=40,
        manager_tenure_quarters=20,
        style_drift_r2=0.9100,
        plan_assets_cents=0,
    )
    version = read_plan(api, ctx.plan_id)["version"]

    blocked = api.post(
        Paths.REPLACEMENTS,
        proposal_payload(
            ctx.plan_id,
            ctx.slot("intl")["id"],
            ctx.fund("intl")["id"],
            ctx.fund("intl_b")["id"],
            version,
        ),
        consultant_headers(),
    )
    validate_error(blocked, ApiErrorId.MENU_FROZEN)

    # The rejection changed nothing, so the very same token is still current.
    allowed = get_success_data(
        api.post(
            Paths.REPLACEMENTS,
            proposal_payload(
                ctx.plan_id,
                ctx.slot("lc")["id"],
                ctx.fund("lc_a")["id"],
                ctx.fund("lc_b")["id"],
                version,
            ),
            consultant_headers(),
        ),
        201,
    )
    assert_fields(
        allowed, status=ProposalStatus.DRAFT, revision_round=0, pinned_ips_id=ctx.ips_id
    )
    submitted = submit_proposal(ctx, allowed["id"], key="lc_replacement")
    assert_status(submitted, ProposalStatus.UNDER_REVIEW)

    create_slot(ctx, "em", AssetClass.EMERGING_MKTS, 6)
    seated = seat_fund(ctx, "em", "em")
    assert_status(seated, SlotStatus.ACTIVE)

    after = read_plan(api, ctx.plan_id)
    assert_ratio(after["at_risk_slot_ratio"], "0.3333")
    assert_status(after, MenuPosture.RESTRICTED, field="menu_posture")
    assert_capacity_triple(after, occupied=6, reserved=0, available=0)


def test_an_approved_decision_locks_the_reopen_until_it_is_rescinded(api, finalized_quarter):
    """A replacement approved under a motion carried at the review's own meeting
    bars the reopen, and rescinding that approval releases it.

    Design: Corner/validations/an_approved_decision_from_the_reviews_own_meeting_locks_the_reopen_until_it_is_rescinded
    """
    ctx = finalized_quarter
    proposal = draft_proposal(ctx, "lc", "lc_a", "lc_b")
    submit_proposal(ctx, proposal["id"])

    meeting, motion = _reopen_and_refinalize(
        ctx,
        "2026-08-24",
        "MIN-2026-Q0-004",
        "lap1",
        (MotionSubjectType.FUND_REPLACEMENT, proposal["id"]),
    )
    review = read_review(api, ctx.review["id"])
    assert_fields(
        review, status=ReviewStatus.FINALIZED, reopen_count=1, meeting_id=meeting["id"]
    )

    approved = approve_proposal(ctx, proposal["id"], motion["id"])
    assert_status(approved, ProposalStatus.APPROVED)
    assert_capacity_triple(read_plan(api, ctx.plan_id), occupied=5, reserved=1, available=0)
    assert_status(read_slot(api, ctx.slot("lc")["id"]), SlotStatus.PENDING_REPLACEMENT)

    locked = api.post(
        Paths.review_reopen(review["id"]),
        {"reason": "The consultant found a data error in the peer ranks."},
        sponsor_headers(),
    )
    validate_error(locked, ApiErrorId.REVIEW_DECISIONS_EXECUTED)
    assert_status(read_review(api, review["id"]), ReviewStatus.FINALIZED)

    rescinded = get_success_data(
        api.post(
            Paths.proposal_rescind(proposal["id"]),
            {"reason": "The committee wants the peer data re-run before mapping."},
            ctx.chair,
        )
    )
    assert_fields(
        rescinded, status=ProposalStatus.UNDER_REVIEW, approving_motion_id=None
    )
    assert_capacity_triple(read_plan(api, ctx.plan_id), occupied=5, reserved=0, available=1)
    assert_status(read_slot(api, ctx.slot("lc")["id"]), SlotStatus.ACTIVE)

    # The identical request now succeeds.
    reopened = get_success_data(
        api.post(
            Paths.review_reopen(review["id"]),
            {"reason": "The consultant found a data error in the peer ranks."},
            sponsor_headers(),
        )
    )
    assert_fields(
        reopened, status=ReviewStatus.REOPENED, reopen_count=2, finalized_at=None
    )
    assert_status(read_motion(api, motion["id"]), MotionStatus.CARRIED)


def test_the_quarter_window_answers_before_the_reopen_ceiling(api, finalized_quarter):
    """With the reopen count already at its ceiling, the answer stays
    REOPEN_LIMIT_REACHED while the review is still inside its window and becomes
    QUARTER_CLOSED once the plan is two quarters ahead of it.

    Design: Corner/validations/the_quarter_window_answers_before_the_reopen_ceiling_when_both_are_blown
    """
    ctx = finalized_quarter
    _reopen_and_refinalize(ctx, "2026-08-24", "MIN-2026-Q0-004", "lap1")
    _reopen_and_refinalize(ctx, "2026-08-26", "MIN-2026-Q0-005", "lap2")
    review = read_review(api, ctx.review["id"])
    assert_fields(
        review, status=ReviewStatus.FINALIZED, reopen_count=2, quarter_index=0
    )
    reason = {"reason": "A third look at the quarter was requested."}

    # Same quarter: only the repetition limit is blown.
    validate_error(
        api.post(Paths.review_reopen(review["id"]), reason, sponsor_headers()),
        ApiErrorId.REOPEN_LIMIT_REACHED,
    )

    advance_quarter(ctx)
    assert read_plan(api, ctx.plan_id)["fiscal_quarter_index"] == 1
    validate_error(
        api.post(Paths.review_reopen(review["id"]), reason, sponsor_headers()),
        ApiErrorId.REOPEN_LIMIT_REACHED,
    )

    # Two quarters on, both gates are blown and the window answers first.
    advance_quarter(ctx)
    assert read_plan(api, ctx.plan_id)["fiscal_quarter_index"] == 2
    validate_error(
        api.post(Paths.review_reopen(review["id"]), reason, sponsor_headers()),
        ApiErrorId.QUARTER_CLOSED,
    )
    assert_fields(read_review(api, review["id"]), status=ReviewStatus.FINALIZED, reopen_count=2)
