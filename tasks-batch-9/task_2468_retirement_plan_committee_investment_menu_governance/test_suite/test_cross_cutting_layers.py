"""Layered behaviour: concurrency tokens underneath lifecycle gates, the
finalize cascade walked hop by hop, the two scoring variants, and the quarter
roll.

Every scenario here stacks at least two of the PRD's mechanisms on top of one
another, so each test drives the whole chain through the documented endpoints
and pins every derived number to an exact literal.
"""

from typing import Any, Dict

import pytest

from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_capacity_triple,
    assert_common_fields,
    assert_fields,
    assert_ordered_by,
    assert_ratio,
    assert_score,
    assert_status,
    assert_version_bumped,
    assert_version_unchanged,
    ids_of,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    Paths,
    proposal_payload,
    scorecard_payload,
)
from test_helpers.fixtures import (
    BREACH_SCORECARDS,
    CLEAN_SCORECARDS,
    Ctx,
    activate_member,
    adopt_ips,
    advance_quarter,
    appoint_member,
    assign_training,
    complete_training,
    create_fund,
    create_levelization_run,
    create_seat,
    draft_ips,
    draft_proposal,
    finalize_review,
    hold_meeting_and_carry_motion,
    make_member_active,
    open_meeting,
    open_review,
    present_and_document,
    present_review,
    read_meeting,
    read_member,
    read_plan,
    read_proposal,
    read_review,
    read_run,
    read_slot,
    schedule_meeting,
    set_clock,
    setup_full_menu,
    setup_scored_quarter,
    sign_acceptance,
    submit_quarter_scorecards,
    submit_scorecard,
)
from test_helpers.test_users import consultant_headers, sponsor_headers
from test_helpers.types import (
    AssetClass,
    EndTermReason,
    FiduciaryTrainingStatus,
    FundMenuStatus,
    LevelizationStatus,
    MappingStrategy,
    MeetingStatus,
    MemberStatus,
    MenuPosture,
    MotionSubjectType,
    ProposalStatus,
    ReviewStatus,
    ScorecardStatus,
    ScoringVariant,
    SeatClass,
    SeatStatus,
    SlotStatus,
    TrainingModule,
    TrainingStatus,
    WatchRecommendation,
    WatchStatus,
)

# --------------------------------------------------------------------------
# Local helpers: raw calls, because these tests need the rejected responses
# --------------------------------------------------------------------------


def _post_proposal(
    api: ApiClient,
    ctx: Ctx,
    slot_key: str,
    outgoing_key: str,
    incoming_key: str,
    expected_plan_version: int,
    **overrides: Any,
):
    """Create a replacement proposal with a caller-chosen concurrency token."""
    return api.post(
        Paths.REPLACEMENTS,
        proposal_payload(
            ctx.plan_id,
            ctx.slot(slot_key)["id"],
            ctx.fund(outgoing_key)["id"],
            ctx.fund(incoming_key)["id"],
            expected_plan_version,
            **overrides,
        ),
        consultant_headers(),
    )


def _post_scorecard(
    api: ApiClient,
    ctx: Ctx,
    fund_key: str,
    expected_review_version: int,
    inputs: Dict[str, Any],
):
    """Submit a scorecard with a caller-chosen concurrency token."""
    return api.post(
        Paths.SCORECARDS,
        scorecard_payload(
            ctx.review["id"],
            ctx.fund(fund_key)["id"],
            expected_review_version,
            **inputs,
        ),
        consultant_headers(),
    )


def _read_scorecard(api: ApiClient, scorecard_id: str) -> Dict[str, Any]:
    return validate_success(api.get(Paths.scorecard(scorecard_id), sponsor_headers()))


def _list(api: ApiClient, path: str, **filters: Any):
    return validate_paginated(api.get(path, sponsor_headers(), filters))


def _retire_slot(api: ApiClient, slot_id: str) -> Dict[str, Any]:
    return validate_success(api.post(Paths.slot_retire(slot_id), {}, sponsor_headers()))


def _recompute_posture(api: ApiClient, plan_id: str) -> Dict[str, Any]:
    return validate_success(
        api.post(Paths.recompute_posture(plan_id), {}, sponsor_headers())
    )


#: A watch-grade international measurement: 36.00, inside the 25.01 - 40.00
#: band, so the fund is a breach that the PRD 3.6 ladder puts on WATCH.
WATCH_GRADE_INTL: Dict[str, Any] = {
    "trailing_return_3y_bps": 0,
    "trailing_return_5y_bps": 0,
    "benchmark_return_3y_bps": 700,
    "benchmark_return_5y_bps": 700,
    "peer_rank_pct": 70,
    "style_drift_r2": 0.9100,
    "net_expense_ratio_bps": 60,
    "peer_median_expense_bps": 35,
    "manager_tenure_quarters": 26,
    "manager_change_flag": False,
}

#: Candidate funds for the three slots the cascade tests keep proposals on.
CANDIDATE_SPECS: Dict[str, Dict[str, Any]] = {
    "small_b": {
        "ticker": "SMLGX",
        "fund_name": "Granite Small Cap Value R6",
        "asset_class_code": AssetClass.US_SMALL_CAP,
        "share_class_code": "R6",
        "gross_expense_ratio_bps": 45,
        "net_expense_ratio_bps": 45,
        "revenue_share_bps": 0,
        "peer_median_expense_bps": 55,
        "track_record_quarters": 36,
        "manager_tenure_quarters": 20,
        "style_drift_r2": 0.9000,
        "plan_assets_cents": 0,
    },
    "intl_b": {
        "ticker": "INTGX",
        "fund_name": "Glacier International Developed Institutional",
        "asset_class_code": AssetClass.INTL_DEVELOPED,
        "share_class_code": "INSTITUTIONAL",
        "gross_expense_ratio_bps": 30,
        "net_expense_ratio_bps": 30,
        "revenue_share_bps": 0,
        "peer_median_expense_bps": 35,
        "track_record_quarters": 40,
        "manager_tenure_quarters": 24,
        "style_drift_r2": 0.9400,
        "plan_assets_cents": 0,
    },
    "bond_b": {
        "ticker": "BNDGX",
        "fund_name": "Granite Core Bond Institutional",
        "asset_class_code": AssetClass.CORE_BOND,
        "share_class_code": "INSTITUTIONAL",
        "gross_expense_ratio_bps": 22,
        "net_expense_ratio_bps": 22,
        "revenue_share_bps": 0,
        "peer_median_expense_bps": 30,
        "track_record_quarters": 52,
        "manager_tenure_quarters": 28,
        "style_drift_r2": 0.9600,
        "plan_assets_cents": 0,
    },
}

#: Quarter-0 trailing measurement for the large-cap fund: 33.00, watch-grade.
TRAILING_LC_Q0: Dict[str, Any] = {
    "trailing_return_3y_bps": 0,
    "trailing_return_5y_bps": 0,
    "benchmark_return_3y_bps": 500,
    "benchmark_return_5y_bps": 500,
    "peer_rank_pct": 95,
    "style_drift_r2": 0.9200,
    "net_expense_ratio_bps": 65,
    "peer_median_expense_bps": 45,
    "manager_tenure_quarters": 20,
    "manager_change_flag": False,
}

#: Quarter-1 measurement for the large-cap fund carrying a rolling window that
#: clears the cure margin.  The trailing pair is ignored under the rolling
#: variant (PRD 3.5), so it is left where quarter 0 had it.
ROLLING_LC_Q1: Dict[str, Any] = {
    "trailing_return_3y_bps": 0,
    "trailing_return_5y_bps": 0,
    "benchmark_return_3y_bps": 500,
    "benchmark_return_5y_bps": 500,
    "rolling_since_watch_return_bps": 900,
    "rolling_since_watch_benchmark_bps": 400,
    "peer_rank_pct": 20,
    "style_drift_r2": 0.9200,
    "net_expense_ratio_bps": 45,
    "peer_median_expense_bps": 45,
    "manager_tenure_quarters": 24,
    "manager_change_flag": False,
}

#: Quarter-1 measurement for the small-cap fund whose rolling window has kept
#: falling, so the same review escalates it while it cures the large-cap fund.
ROLLING_SMALL_Q1: Dict[str, Any] = {
    "trailing_return_3y_bps": 200,
    "trailing_return_5y_bps": 200,
    "benchmark_return_3y_bps": 500,
    "benchmark_return_5y_bps": 500,
    "rolling_since_watch_return_bps": 0,
    "rolling_since_watch_benchmark_bps": 2000,
    "peer_rank_pct": 90,
    "style_drift_r2": 0.8800,
    "net_expense_ratio_bps": 75,
    "peer_median_expense_bps": 55,
    "manager_tenure_quarters": 14,
    "manager_change_flag": False,
}


# --------------------------------------------------------------------------
# Module-local scenarios
# --------------------------------------------------------------------------


@pytest.fixture
def single_breach_quarter(api: ApiClient) -> Ctx:
    """Quarter 0 scored with exactly one breaching fund — the small-cap fund at
    40.00 — presented and minuted but not finalized, with a live draft
    replacement proposal already sitting on that same slot."""
    ctx = setup_scored_quarter(
        api,
        scorecard_overrides={"small": BREACH_SCORECARDS["small"]},
        finalize=False,
    )
    create_fund(ctx, "small_b", **CANDIDATE_SPECS["small_b"])
    draft_proposal(ctx, "small", "small", "small_b", key="small_prop")
    return ctx


@pytest.fixture
def impaired_pair_quarter(api: ApiClient) -> Ctx:
    """Quarter 0 scored with two watch-grade funds — the small-cap slot at 40.00
    and the international slot at 36.00 — plus four draft proposals: two on the
    small-cap slot so one supersedes the other, one on the international slot
    and one on the healthy core-bond slot."""
    ctx = setup_scored_quarter(
        api,
        scorecard_overrides={
            "small": BREACH_SCORECARDS["small"],
            "intl": WATCH_GRADE_INTL,
        },
        finalize=False,
    )
    for key, spec in CANDIDATE_SPECS.items():
        create_fund(ctx, key, **spec)
    draft_proposal(ctx, "small", "small", "small_b", key="superseded")
    draft_proposal(ctx, "small", "small", "small_b", key="small_prop")
    draft_proposal(ctx, "intl", "intl", "intl_b", key="intl_prop")
    draft_proposal(ctx, "bond", "bond", "bond_b", key="bond_prop")
    return ctx


@pytest.fixture
def watch_pair_rolling(api: ApiClient) -> Ctx:
    """A two-slot menu whose large-cap and small-cap funds both went onto watch
    in quarter 0 under the trailing blend; the committee then adopts a statement
    scoring on the rolling window, the quarter rolls, and a quarter-1 review is
    open and pinned to that new statement."""
    ctx = setup_full_menu(api)
    for slot_key in ("bond", "intl", "tips"):
        _retire_slot(api, ctx.slot(slot_key)["id"])

    open_review(ctx, 0)
    submit_scorecard(ctx, "lc_a", TRAILING_LC_Q0, key="lc_a_q0")
    submit_scorecard(ctx, "small", BREACH_SCORECARDS["small"], key="small_q0")
    present_and_document(ctx)
    finalize_review(ctx)
    ctx.review_q0 = ctx.review

    rolling = draft_ips(
        api,
        ctx.plan_id,
        version_label="IPS-2026-R2",
        scoring_variant=ScoringVariant.ROLLING_SINCE_WATCH,
    )
    motion = hold_meeting_and_carry_motion(
        ctx,
        MotionSubjectType.IPS_ADOPTION,
        rolling["id"],
        meeting_date="2026-08-17",
        minutes_doc_ref="MIN-2026-Q0-003",
        key="rolling",
    )
    ctx.ips = adopt_ips(ctx, rolling["id"], motion["id"])

    advance_quarter(ctx)
    open_review(ctx, 1)
    return ctx


@pytest.fixture
def expiring_committee(api: ApiClient) -> Ctx:
    """A seated menu whose committee is about to lose two seats to the calendar:
    one member's fiduciary-duties module is valid for a single quarter and
    another member's term ends before the clock this fixture leaves behind.  An
    abandoned meeting, the review that points at it and a draft levelization run
    are all left in quarter 0."""
    ctx = setup_full_menu(api)

    ctx.seats["training"] = create_seat(
        api,
        ctx.plan_id,
        seat_code="S-PART",
        seat_class=SeatClass.PARTICIPANT_REP,
        voting=True,
        seat_index=4,
    )
    lapsing = appoint_member(
        api,
        ctx.seats["training"]["id"],
        member_name="Priya Raman",
        person_email="priya.raman@example.com",
    )
    ctx.members["training"] = lapsing
    ctx.short_record = assign_training(
        api,
        lapsing["id"],
        module_code=TrainingModule.FIDUCIARY_DUTIES,
        validity_quarters=1,
    )
    complete_training(api, ctx.short_record["id"], lapsing["id"], 88.00)
    ctx.long_record = assign_training(
        api, lapsing["id"], module_code=TrainingModule.IPS_MECHANICS
    )
    complete_training(api, ctx.long_record["id"], lapsing["id"], 88.00)
    sign_acceptance(api, lapsing["id"])
    activate_member(api, lapsing["id"])

    ctx.seats["expiring"] = create_seat(
        api,
        ctx.plan_id,
        seat_code="S-IND",
        seat_class=SeatClass.INDEPENDENT,
        voting=True,
        seat_index=5,
    )
    leaving = appoint_member(
        api,
        ctx.seats["expiring"]["id"],
        member_name="Elena Fischer",
        person_email="elena.fischer@example.com",
        term_start_date="2026-01-01",
        term_end_date="2026-09-30",
    )
    ctx.members["expiring"] = leaving
    make_member_active(api, leaving["id"], 90.00)

    abandoned = schedule_meeting(ctx, "2026-08-20", 0, key="abandoned")
    open_review(ctx, 0, meeting_id=abandoned["id"])
    submit_scorecard(ctx, "lc_a", CLEAN_SCORECARDS["lc_a"])
    create_levelization_run(ctx, 0, method="PRO_RATA")

    set_clock(api, "2026-10-15T00:00:00Z")
    ctx.refresh_plan()
    return ctx


# --------------------------------------------------------------------------
# The plan concurrency token under the posture and supersede machinery
# --------------------------------------------------------------------------


def test_stale_plan_snapshot_is_refused_and_writes_nothing(api, full_menu):
    """A proposal create carrying a plan version that an unrelated posture
    recomputation has already superseded is refused with 412 and leaves no
    proposal row and no counter movement behind.

    Design: Corner/cross_cutting_complexity_layers/the_plan_version_gate_rejects_a_client_holding_any_snapshot_older_than_the_last_write_including_its_own
    """
    ctx = full_menu
    before = read_plan(api, ctx.plan_id)
    stale_token = before["version"]
    assert_status(before, MenuPosture.OPEN, "menu_posture")
    assert_ratio(before["at_risk_slot_ratio"], "0.0000", "at_risk_slot_ratio")
    assert before["draft_proposal_count"] == 0, before["draft_proposal_count"]

    # A recomputation that changes no posture still advances the plan row
    # (PRD 3.9 explicit posture recompute).
    bumped = _recompute_posture(api, ctx.plan_id)
    assert_status(bumped, MenuPosture.OPEN, "menu_posture")
    assert_ratio(bumped["at_risk_slot_ratio"], "0.0000", "at_risk_slot_ratio")
    assert_version_bumped(before, bumped)

    rejected = _post_proposal(api, ctx, "lc", "lc_a", "lc_b", stale_token)
    validate_error(rejected, ApiErrorId.STALE_PLAN_VERSION, 412)

    rows, meta = _list(api, Paths.REPLACEMENTS, plan_id=ctx.plan_id)
    assert rows == [], rows
    assert meta["total_count"] == 0, meta
    assert meta["has_more"] is False, meta

    after = read_plan(api, ctx.plan_id)
    assert_version_unchanged(bumped, after)
    assert after["draft_proposal_count"] == 0, after["draft_proposal_count"]
    assert_capacity_triple(after, occupied=5, reserved=0, available=1)


def test_accepted_plan_snapshot_supersedes_and_then_invalidates_itself(api, full_menu):
    """The token the plan currently reports is accepted once: the proposal is
    created against it, the plan version moves past it, replaying it is refused,
    and a re-read token drives the create-with-supersede withdrawal.

    Design: Corner/cross_cutting_complexity_layers/the_plan_version_gate_rejects_a_client_holding_any_snapshot_older_than_the_last_write_including_its_own
    """
    ctx = full_menu
    token = read_plan(api, ctx.plan_id)["version"]

    first = validate_success(
        _post_proposal(api, ctx, "lc", "lc_a", "lc_b", token), 201
    )
    assert_common_fields(first)
    assert_status(first, ProposalStatus.DRAFT)
    assert_fields(
        first,
        revision_round=0,
        mapped_assets_cents=0,
        approving_motion_id=None,
        pre_block_status=None,
        superseded_by_proposal_id=None,
        pinned_plan_version=token,
        pinned_ips_id=ctx.ips_id,
        mapping_strategy=MappingStrategy.DIRECT_MAP,
    )

    after_first = read_plan(api, ctx.plan_id)
    assert after_first["version"] == token + 1, after_first["version"]
    assert after_first["draft_proposal_count"] == 1, after_first["draft_proposal_count"]
    assert_capacity_triple(after_first, occupied=5, reserved=0, available=1)

    # The very client that succeeded now holds a stale snapshot of its own
    # making, so its next attempt is refused and withdraws nothing.
    replay = _post_proposal(api, ctx, "lc", "lc_a", "lc_b", token)
    validate_error(replay, ApiErrorId.STALE_PLAN_VERSION, 412)
    untouched = read_proposal(api, first["id"])
    assert_status(untouched, ProposalStatus.DRAFT)
    assert untouched["superseded_by_proposal_id"] is None, untouched

    fresh = read_plan(api, ctx.plan_id)["version"]
    assert fresh == token + 1, fresh
    second = validate_success(
        _post_proposal(
            api,
            ctx,
            "lc",
            "lc_a",
            "lc_b",
            fresh,
            mapping_strategy=MappingStrategy.REENROLLMENT,
        ),
        201,
    )
    assert_status(second, ProposalStatus.DRAFT)
    assert_fields(
        second,
        pinned_plan_version=fresh,
        mapping_strategy=MappingStrategy.REENROLLMENT,
        superseded_by_proposal_id=None,
    )

    loser = read_proposal(api, first["id"])
    assert_status(loser, ProposalStatus.WITHDRAWN)
    assert loser["superseded_by_proposal_id"] == second["id"], loser

    after_second = read_plan(api, ctx.plan_id)
    assert after_second["version"] == fresh + 1, after_second["version"]
    assert after_second["draft_proposal_count"] == 1, after_second[
        "draft_proposal_count"
    ]


# --------------------------------------------------------------------------
# The review concurrency token, and the lifecycle check that outranks it
# --------------------------------------------------------------------------


def test_one_review_snapshot_cannot_carry_two_funds(api, full_menu):
    """The first scorecard consumes the review snapshot it was submitted
    against, so a second fund offered from that same snapshot is refused with
    412 and no row is written; a re-read then supersedes cleanly.

    Design: Corner/cross_cutting_complexity_layers/the_review_version_gate_yields_to_the_lifecycle_gate_and_two_consultants_cannot_both_score_from_one_snapshot
    """
    ctx = full_menu
    review = open_review(ctx, 0)
    assert_status(review, ReviewStatus.DRAFT)
    assert review["submitted_scorecard_count"] == 0, review
    shared_token = review["version"]

    first = validate_success(
        _post_scorecard(api, ctx, "lc_a", shared_token, CLEAN_SCORECARDS["lc_a"]), 201
    )
    assert_status(first, ScorecardStatus.SUBMITTED)
    assert first["supersedes_scorecard_id"] is None, first
    assert_score(first["composite_score"], "76.20", "composite_score")

    scoring = read_review(api, review["id"])
    assert_status(scoring, ReviewStatus.SCORING)
    assert scoring["version"] == shared_token + 1, scoring["version"]
    assert scoring["submitted_scorecard_count"] == 1, scoring

    # A colleague still holding the pre-submission snapshot loses the race.
    loser = _post_scorecard(api, ctx, "bond", shared_token, CLEAN_SCORECARDS["bond"])
    validate_error(loser, ApiErrorId.STALE_REVIEW_VERSION, 412)
    rows, meta = _list(
        api,
        Paths.SCORECARDS,
        review_id=review["id"],
        fund_id=ctx.fund("bond")["id"],
    )
    assert rows == [], rows
    assert meta["total_count"] == 0, meta
    assert_version_unchanged(scoring, read_review(api, review["id"]))

    # With a re-read token the same fund may be rescored, superseding its own
    # earlier row without moving the submitted count (PRD 3.5).
    fresh = read_review(api, review["id"])["version"]
    second = validate_success(
        _post_scorecard(api, ctx, "lc_a", fresh, CLEAN_SCORECARDS["lc_a"]), 201
    )
    assert second["supersedes_scorecard_id"] == first["id"], second
    assert_status(second, ScorecardStatus.SUBMITTED)
    assert_status(_read_scorecard(api, first["id"]), ScorecardStatus.SUPERSEDED)

    after = read_review(api, review["id"])
    assert after["version"] == fresh + 1, after["version"]
    assert after["submitted_scorecard_count"] == 1, after

    # The token just consumed is refused in its turn.
    validate_error(
        _post_scorecard(api, ctx, "bond", fresh, CLEAN_SCORECARDS["bond"]),
        ApiErrorId.STALE_REVIEW_VERSION,
        412,
    )
    assert_version_unchanged(after, read_review(api, review["id"]))


def test_presented_review_answers_the_state_check_before_the_version_check(
    api, full_menu
):
    """Once the review has left its scoring state, both a stale token and the
    review's own current token are answered with 409 for the lifecycle, never
    with the 412 the concurrency gate would give.

    Design: Corner/cross_cutting_complexity_layers/the_review_version_gate_yields_to_the_lifecycle_gate_and_two_consultants_cannot_both_score_from_one_snapshot
    """
    ctx = full_menu
    review = open_review(ctx, 0)
    ancient_token = review["version"]
    submit_quarter_scorecards(ctx)

    meeting = open_meeting(ctx, "2026-08-10", 0, key="review")
    presented = present_review(ctx, meeting["id"])
    assert_status(presented, ReviewStatus.PENDING_MINUTES)
    assert presented["submitted_scorecard_count"] == 5, presented

    # The token is stale *and* the review is closed to scoring: the lifecycle
    # check at the lower priority number wins (PRD 2.12).
    stale = _post_scorecard(api, ctx, "lc_a", ancient_token, CLEAN_SCORECARDS["lc_a"])
    validate_error(stale, ApiErrorId.REVIEW_NOT_SCORING, 409)
    assert_version_unchanged(presented, read_review(api, review["id"]))

    # A perfectly fresh token gets the same answer, which is what shows the
    # ordering rather than a coincidence.
    current = read_review(api, review["id"])["version"]
    fresh = _post_scorecard(api, ctx, "lc_a", current, CLEAN_SCORECARDS["lc_a"])
    validate_error(fresh, ApiErrorId.REVIEW_NOT_SCORING, 409)

    unchanged = read_review(api, review["id"])
    assert unchanged["version"] == current, unchanged["version"]
    assert unchanged["submitted_scorecard_count"] == 5, unchanged
    assert_status(unchanged, ReviewStatus.PENDING_MINUTES)
    rows, meta = _list(
        api,
        Paths.SCORECARDS,
        review_id=review["id"],
        fund_id=ctx.fund("lc_a")["id"],
    )
    assert meta["total_count"] == 1, meta
    assert_status(rows[0], ScorecardStatus.SUBMITTED)


# --------------------------------------------------------------------------
# Where the finalize cascade stops, and what the recompute path will not do
# --------------------------------------------------------------------------


def test_one_breach_in_five_slots_stops_the_cascade_before_the_blocking_hop(
    api, single_breach_quarter
):
    """One at-risk slot out of five is a ratio of 0.2000, which leaves the
    posture OPEN; the cascade therefore runs through the slot hop and stops,
    and the draft proposal on the impaired slot is untouched.

    Design: Corner/cross_cutting_complexity_layers/the_ratio_one_notch_below_the_ladder_halts_the_cascade_at_hop_three_and_the_recompute_path_never_blocks
    """
    ctx = single_breach_quarter
    proposal_id = ctx.proposals["small_prop"]["id"]
    assert_status(read_proposal(api, proposal_id), ProposalStatus.DRAFT)

    finalized = finalize_review(ctx)
    assert_status(finalized, ReviewStatus.FINALIZED)
    assert finalized["watch_additions_count"] == 1, finalized
    assert finalized["finalized_quarter_index"] == 0, finalized

    breaching = ctx.fund("small")
    fund = validate_success(api.get(Paths.fund(breaching["id"]), sponsor_headers()))
    assert_score(fund["latest_composite_score"], "40.00", "latest_composite_score")
    assert_fields(
        fund,
        watch_status=WatchStatus.WATCH,
        watch_status_before_last_review=WatchStatus.CLEAR,
        watch_started_quarter_index=0,
        last_scored_quarter_index=0,
        consecutive_breach_quarters=1,
        menu_status=FundMenuStatus.ACTIVE,
    )

    slot = read_slot(api, ctx.slot("small")["id"])
    assert_fields(
        slot,
        status=SlotStatus.AT_RISK,
        status_before_last_review=SlotStatus.ACTIVE,
        at_risk_since_quarter_index=0,
    )

    plan = read_plan(api, ctx.plan_id)
    assert_ratio(plan["at_risk_slot_ratio"], "0.2000", "at_risk_slot_ratio")
    assert_status(plan, MenuPosture.OPEN, "menu_posture")
    assert_capacity_triple(plan, occupied=5, reserved=0, available=1)

    # The posture never moved, so the blocking hop had nothing to do.
    still_draft = read_proposal(api, proposal_id)
    assert_status(still_draft, ProposalStatus.DRAFT)
    assert still_draft["pre_block_status"] is None, still_draft
    blocked, meta = _list(
        api, Paths.REPLACEMENTS, plan_id=ctx.plan_id, status=ProposalStatus.BLOCKED
    )
    assert blocked == [], blocked
    assert meta["total_count"] == 0, meta


def test_retiring_a_healthy_slot_restricts_the_menu_without_blocking_anything(
    api, single_breach_quarter
):
    """Retiring an untroubled slot shrinks the ratio's denominator from five to
    four, which lands it on exactly 0.2500 and moves the posture to RESTRICTED
    inline; a standalone recomputation repeats that answer and still refuses to
    block the draft proposal, because only finalization ever blocks.

    Design: Corner/cross_cutting_complexity_layers/the_ratio_one_notch_below_the_ladder_halts_the_cascade_at_hop_three_and_the_recompute_path_never_blocks
    """
    ctx = single_breach_quarter
    proposal_id = ctx.proposals["small_prop"]["id"]
    finalize_review(ctx)

    retired = _retire_slot(api, ctx.slot("tips")["id"])
    assert_status(retired, SlotStatus.RETIRED)

    released = validate_success(
        api.get(Paths.fund(ctx.fund("tips")["id"]), sponsor_headers())
    )
    assert_fields(
        released,
        menu_status=FundMenuStatus.PENDING_REMOVAL,
        watch_status=WatchStatus.CLEAR,
        watch_status_before_last_review=None,
    )

    plan = read_plan(api, ctx.plan_id)
    assert_capacity_triple(plan, occupied=4, reserved=0, available=2)
    assert_ratio(plan["at_risk_slot_ratio"], "0.2500", "at_risk_slot_ratio")
    assert_status(plan, MenuPosture.RESTRICTED, "menu_posture")

    # The explicit recomputation is idempotent on the derived pair and only
    # moves the version (PRD 3.9).
    again = _recompute_posture(api, ctx.plan_id)
    assert_ratio(again["at_risk_slot_ratio"], "0.2500", "at_risk_slot_ratio")
    assert_status(again, MenuPosture.RESTRICTED, "menu_posture")
    assert_version_bumped(plan, again)
    assert_capacity_triple(again, occupied=4, reserved=0, available=2)
    assert again["draft_proposal_count"] == 1, again["draft_proposal_count"]

    # The recompute path has a release arm and no blocking arm.
    survivor = read_proposal(api, proposal_id)
    assert_status(survivor, ProposalStatus.DRAFT)
    assert survivor["pre_block_status"] is None, survivor
    blocked, meta = _list(
        api, Paths.REPLACEMENTS, plan_id=ctx.plan_id, status=ProposalStatus.BLOCKED
    )
    assert blocked == [], blocked
    assert meta["total_count"] == 0, meta


# --------------------------------------------------------------------------
# The blocking hop under a RESTRICTED posture
# --------------------------------------------------------------------------


def test_the_blocking_hop_reaches_only_the_impaired_asset_classes(
    api, impaired_pair_quarter
):
    """Two of five slots go at risk, which restricts the menu, and the blocking
    sweep then takes only the live proposals whose incoming fund shares an asset
    class with an at-risk slot — walked from the lower slot index upwards — while
    the core-bond proposal and the already-superseded predecessor are left alone.

    Design: Corner/cross_cutting_complexity_layers/hop_four_blocks_only_live_proposals_on_impaired_slots_and_walks_them_in_slot_index_order
    """
    ctx = impaired_pair_quarter
    superseded_id = ctx.proposals["superseded"]["id"]
    small_prop_id = ctx.proposals["small_prop"]["id"]
    intl_prop_id = ctx.proposals["intl_prop"]["id"]
    bond_prop_id = ctx.proposals["bond_prop"]["id"]

    # The second draft on the small-cap slot already withdrew the first one
    # (PRD 3.7 create-with-supersede), so the sweep must not touch it again.
    predecessor = read_proposal(api, superseded_id)
    assert_status(predecessor, ProposalStatus.WITHDRAWN)
    assert predecessor["superseded_by_proposal_id"] == small_prop_id, predecessor

    finalized = finalize_review(ctx)
    assert_status(finalized, ReviewStatus.FINALIZED)
    assert finalized["watch_additions_count"] == 2, finalized

    small_fund = validate_success(
        api.get(Paths.fund(ctx.fund("small")["id"]), sponsor_headers())
    )
    assert_score(small_fund["latest_composite_score"], "40.00", "small composite")
    assert_status(small_fund, WatchStatus.WATCH, "watch_status")
    intl_fund = validate_success(
        api.get(Paths.fund(ctx.fund("intl")["id"]), sponsor_headers())
    )
    assert_score(intl_fund["latest_composite_score"], "36.00", "intl composite")
    assert_status(intl_fund, WatchStatus.WATCH, "watch_status")

    assert_status(read_slot(api, ctx.slot("small")["id"]), SlotStatus.AT_RISK)
    assert_status(read_slot(api, ctx.slot("intl")["id"]), SlotStatus.AT_RISK)

    plan = read_plan(api, ctx.plan_id)
    assert_ratio(plan["at_risk_slot_ratio"], "0.4000", "at_risk_slot_ratio")
    assert_status(plan, MenuPosture.RESTRICTED, "menu_posture")
    assert_capacity_triple(plan, occupied=5, reserved=0, available=1)

    blocked, meta = _list(
        api, Paths.REPLACEMENTS, plan_id=ctx.plan_id, status=ProposalStatus.BLOCKED
    )
    assert meta["total_count"] == 2, meta
    assert meta["has_more"] is False, meta
    assert ids_of(blocked) == [small_prop_id, intl_prop_id], ids_of(blocked)
    assert_ordered_by(blocked, "created_at")
    for row in blocked:
        assert row["pre_block_status"] == ProposalStatus.DRAFT, row

    # The healthy core-bond slot shields its proposal from a RESTRICTED sweep.
    bond_prop = read_proposal(api, bond_prop_id)
    assert_status(bond_prop, ProposalStatus.DRAFT)
    assert bond_prop["pre_block_status"] is None, bond_prop
    bond_fund = validate_success(
        api.get(Paths.fund(ctx.fund("bond")["id"]), sponsor_headers())
    )
    assert_fields(
        bond_fund,
        watch_status=WatchStatus.CLEAR,
        watch_status_before_last_review=None,
        menu_status=FundMenuStatus.ACTIVE,
    )
    bond_slot = read_slot(api, ctx.slot("bond")["id"])
    assert_fields(
        bond_slot,
        status=SlotStatus.ACTIVE,
        status_before_last_review=None,
        at_risk_since_quarter_index=None,
    )

    # A terminal row keeps its terminal status and never acquires a snapshot.
    untouched = read_proposal(api, superseded_id)
    assert_status(untouched, ProposalStatus.WITHDRAWN)
    assert untouched["pre_block_status"] is None, untouched


# --------------------------------------------------------------------------
# Two scoring variants over one pair of watched funds
# --------------------------------------------------------------------------


def test_the_rolling_variant_scores_one_watched_fund_up_and_the_other_down(
    api, watch_pair_rolling
):
    """Both funds went onto watch in quarter 0 under the trailing blend; under a
    statement scoring the rolling window since watch, the same pair of quarter-1
    rows splits — the large-cap window is 500 basis points ahead and scores 96.00
    for a cure, the small-cap window is 2000 behind and scores 32.20, which the
    grace count turns into a remediation.

    Design: Corner/cross_cutting_complexity_layers/the_same_two_scorecard_rows_cure_under_one_variant_and_escalate_under_the_other
    """
    ctx = watch_pair_rolling
    assert ctx.review_q0["scoring_variant"] == ScoringVariant.TRAILING_PERIOD

    # Quarter 0, trailing blend: 0.6 of the 3-year gap plus 0.4 of the 5-year gap.
    lc_q0 = _read_scorecard(api, ctx.scorecards["lc_a_q0"]["id"])
    assert_score(lc_q0["composite_score"], "33.00", "composite_score")
    assert lc_q0["watch_recommendation"] == WatchRecommendation.WATCH, lc_q0
    small_q0 = _read_scorecard(api, ctx.scorecards["small_q0"]["id"])
    assert_score(small_q0["composite_score"], "40.00", "composite_score")
    assert small_q0["watch_recommendation"] == WatchRecommendation.WATCH, small_q0

    for fund_key, score in (("lc_a", "33.00"), ("small", "40.00")):
        fund = validate_success(
            api.get(Paths.fund(ctx.fund(fund_key)["id"]), sponsor_headers())
        )
        assert_score(fund["latest_composite_score"], score, "latest_composite_score")
        assert_fields(
            fund,
            watch_status=WatchStatus.WATCH,
            watch_started_quarter_index=0,
            consecutive_breach_quarters=1,
            last_scored_quarter_index=0,
        )

    review = ctx.review
    assert_fields(
        review,
        quarter_index=1,
        scoring_variant=ScoringVariant.ROLLING_SINCE_WATCH,
        status=ReviewStatus.DRAFT,
        submitted_scorecard_count=0,
    )

    cured = submit_scorecard(ctx, "lc_a", ROLLING_LC_Q1, key="lc_a_q1")
    assert_score(cured["composite_score"], "96.00", "composite_score")
    assert_score(cured["performance_component"], "100.00", "performance_component")
    assert_score(cured["peer_component"], "80.00", "peer_component")
    assert_score(cured["expense_component"], "100.00", "expense_component")
    assert_score(cured["style_component"], "100.00", "style_component")
    assert_score(cured["manager_component"], "100.00", "manager_component")
    assert cured["watch_recommendation"] == WatchRecommendation.NONE, cured
    # The trailing pair is stored but plays no part under this variant: on its
    # own it is 500 basis points behind the benchmark.
    assert cured["trailing_3y_return_bps"] == 0, cured
    assert cured["benchmark_3y_return_bps"] == 500, cured

    escalated = submit_scorecard(ctx, "small", ROLLING_SMALL_Q1, key="small_q1")
    assert_score(escalated["composite_score"], "32.20", "composite_score")
    assert_score(escalated["performance_component"], "0.00", "performance_component")
    assert_score(escalated["peer_component"], "10.00", "peer_component")
    assert_score(escalated["expense_component"], "60.00", "expense_component")
    assert_score(escalated["style_component"], "100.00", "style_component")
    assert_score(escalated["manager_component"], "82.00", "manager_component")
    assert escalated["watch_recommendation"] == WatchRecommendation.REMEDIATION, escalated
    # Its trailing pair is only 300 behind, which would have scored above the
    # 40.00 watch trigger; the rolling window is what condemns it.
    assert escalated["trailing_3y_return_bps"] == 200, escalated
    assert escalated["benchmark_3y_return_bps"] == 500, escalated

    scoring = read_review(api, review["id"])
    assert_status(scoring, ReviewStatus.SCORING)
    assert scoring["submitted_scorecard_count"] == 2, scoring


def test_finalizing_the_rolling_quarter_cures_one_fund_and_escalates_the_other(
    api, watch_pair_rolling
):
    """Finalizing the rolling-window quarter applies both recommendations in the
    same cascade: the cured fund returns to CLEAR and its slot to ACTIVE, the
    escalated fund reaches REMEDIATION on its second consecutive breach with its
    slot still at risk, and one at-risk slot out of the two survivors is a ratio
    of 0.5000, which freezes the menu.

    Design: Corner/cross_cutting_complexity_layers/the_same_two_scorecard_rows_cure_under_one_variant_and_escalate_under_the_other
    """
    ctx = watch_pair_rolling
    submit_scorecard(ctx, "lc_a", ROLLING_LC_Q1, key="lc_a_q1")
    submit_scorecard(ctx, "small", ROLLING_SMALL_Q1, key="small_q1")
    present_and_document(
        ctx,
        meeting_date="2026-11-10",
        minutes_doc_ref="MIN-2026-Q1-001",
        quarter_index=1,
    )

    finalized = finalize_review(ctx)
    assert_status(finalized, ReviewStatus.FINALIZED)
    assert finalized["finalized_quarter_index"] == 1, finalized
    # Neither fund left CLEAR in this quarter: one arrived there, one moved
    # deeper into the ladder.
    assert finalized["watch_additions_count"] == 0, finalized

    cured_fund = validate_success(
        api.get(Paths.fund(ctx.fund("lc_a")["id"]), sponsor_headers())
    )
    assert_score(cured_fund["latest_composite_score"], "96.00", "latest_composite_score")
    assert_fields(
        cured_fund,
        watch_status=WatchStatus.CLEAR,
        watch_status_before_last_review=WatchStatus.WATCH,
        watch_started_quarter_index=None,
        consecutive_breach_quarters=0,
        last_scored_quarter_index=1,
        menu_status=FundMenuStatus.ACTIVE,
    )
    cured_slot = read_slot(api, ctx.slot("lc")["id"])
    assert_fields(
        cured_slot,
        status=SlotStatus.ACTIVE,
        status_before_last_review=SlotStatus.AT_RISK,
        at_risk_since_quarter_index=None,
    )

    escalated_fund = validate_success(
        api.get(Paths.fund(ctx.fund("small")["id"]), sponsor_headers())
    )
    assert_score(
        escalated_fund["latest_composite_score"], "32.20", "latest_composite_score"
    )
    assert_fields(
        escalated_fund,
        watch_status=WatchStatus.REMEDIATION,
        watch_status_before_last_review=WatchStatus.WATCH,
        watch_started_quarter_index=0,
        consecutive_breach_quarters=2,
        last_scored_quarter_index=1,
        menu_status=FundMenuStatus.ACTIVE,
    )
    escalated_slot = read_slot(api, ctx.slot("small")["id"])
    assert_fields(
        escalated_slot,
        status=SlotStatus.AT_RISK,
        at_risk_since_quarter_index=0,
    )

    in_remediation, meta = _list(
        api, Paths.FUNDS, plan_id=ctx.plan_id, watch_status=WatchStatus.REMEDIATION
    )
    assert meta["total_count"] == 1, meta
    assert ids_of(in_remediation) == [ctx.fund("small")["id"]], ids_of(in_remediation)

    plan = read_plan(api, ctx.plan_id)
    assert_ratio(plan["at_risk_slot_ratio"], "0.5000", "at_risk_slot_ratio")
    assert_status(plan, MenuPosture.FROZEN, "menu_posture")


# --------------------------------------------------------------------------
# The quarter roll: three independent expiries, then the stale-review sweep
# --------------------------------------------------------------------------


def test_one_quarter_roll_expires_a_term_a_module_and_a_scheduled_meeting(
    api, expiring_committee
):
    """A single quarter advance fires three sweeps at once: the member whose term
    has passed leaves and vacates a seat, the training module valid for one
    quarter expires while the eight-quarter modules survive, and the meeting that
    was never convened is voided with the review that pointed at it losing its
    meeting reference — but the review, only one quarter old, is untouched.

    Design: Corner/cross_cutting_complexity_layers/one_quarter_roll_expires_a_term_a_training_module_and_a_meeting_and_the_second_roll_voids_the_stale_review
    """
    ctx = expiring_committee
    plan_before = read_plan(api, ctx.plan_id)
    assert plan_before["fiscal_quarter_index"] == 0, plan_before
    expiring_seat_id = ctx.seats["expiring"]["id"]
    seat_before = validate_success(
        api.get(Paths.seat(expiring_seat_id), sponsor_headers())
    )
    assert_status(seat_before, SeatStatus.FILLED)
    assert seat_before["consecutive_vacant_quarters"] == 0, seat_before

    rolled = advance_quarter(ctx)
    assert rolled["fiscal_quarter_index"] == 1, rolled
    assert_version_bumped(plan_before, rolled)

    # Sweep: the term that has passed the logical clock.
    leaving = read_member(api, ctx.members["expiring"]["id"])
    assert_status(leaving, MemberStatus.TERM_EXPIRED)
    assert leaving["end_term_reason"] == EndTermReason.TERM_EXPIRY, leaving
    seat_after = validate_success(
        api.get(Paths.seat(expiring_seat_id), sponsor_headers())
    )
    assert_status(seat_after, SeatStatus.VACANT)
    assert seat_after["consecutive_vacant_quarters"] == 1, seat_after

    # Sweep: the module whose validity was a single quarter.
    short = validate_success(
        api.get(Paths.training_record(ctx.short_record["id"]), sponsor_headers())
    )
    assert_status(short, TrainingStatus.EXPIRED)
    long_module = validate_success(
        api.get(Paths.training_record(ctx.long_record["id"]), sponsor_headers())
    )
    assert_status(long_module, TrainingStatus.COMPLETED)
    expired_rows, expired_meta = _list(
        api, Paths.TRAINING_RECORDS, status=TrainingStatus.EXPIRED
    )
    assert expired_meta["total_count"] == 1, expired_meta
    assert ids_of(expired_rows) == [ctx.short_record["id"]], ids_of(expired_rows)

    lapsed = read_member(api, ctx.members["training"]["id"])
    assert_fields(
        lapsed,
        status=MemberStatus.ACTIVE,
        fiduciary_training_status=FiduciaryTrainingStatus.EXPIRED,
    )
    chair = read_member(api, ctx.chair_id)
    assert_fields(
        chair,
        status=MemberStatus.ACTIVE,
        fiduciary_training_status=FiduciaryTrainingStatus.CURRENT,
    )

    # Sweep: the meeting nobody ever convened.
    abandoned = read_meeting(api, ctx.meetings["abandoned"]["id"])
    assert_status(abandoned, MeetingStatus.VOID)
    voided, void_meta = _list(
        api, Paths.MEETINGS, plan_id=ctx.plan_id, status=MeetingStatus.VOID
    )
    assert void_meta["total_count"] == 1, void_meta
    assert ids_of(voided) == [ctx.meetings["abandoned"]["id"]], ids_of(voided)

    review = read_review(api, ctx.review["id"])
    assert_status(review, ReviewStatus.SCORING)
    assert review["meeting_id"] is None, review
    assert read_run(api, ctx.runs["run"]["id"])["status"] == LevelizationStatus.DRAFT

    # Training expiry alone leaves the posture where it was (PRD 3.9).
    assert_ratio(rolled["at_risk_slot_ratio"], "0.0000", "at_risk_slot_ratio")
    assert_status(rolled, MenuPosture.OPEN, "menu_posture")


def test_the_second_quarter_roll_voids_the_stale_review_and_the_stale_draft_run(
    api, expiring_committee
):
    """The review and the levelization run both survive the first roll and only
    the second one carries them past "more than one quarter old": the review is
    voided together with its submitted scorecard and the draft run follows, while
    the expiries the first roll already applied stay exactly as they were and the
    plan's version has moved once per roll.

    Design: Corner/cross_cutting_complexity_layers/one_quarter_roll_expires_a_term_a_training_module_and_a_meeting_and_the_second_roll_voids_the_stale_review
    """
    ctx = expiring_committee
    plan_before = read_plan(api, ctx.plan_id)
    review_id = ctx.review["id"]
    scorecard_id = ctx.scorecards["lc_a"]["id"]
    run_id = ctx.runs["run"]["id"]

    advance_quarter(ctx)
    survivor = read_review(api, review_id)
    assert_status(survivor, ReviewStatus.SCORING)
    assert read_run(api, run_id)["status"] == LevelizationStatus.DRAFT

    rolled_twice = advance_quarter(ctx)
    assert rolled_twice["fiscal_quarter_index"] == 2, rolled_twice
    assert_version_bumped(plan_before, rolled_twice, by=2)

    voided_review = read_review(api, review_id)
    assert_status(voided_review, ReviewStatus.VOID)
    assert voided_review["meeting_id"] is None, voided_review
    assert_status(_read_scorecard(api, scorecard_id), ScorecardStatus.VOID)
    void_rows, void_meta = _list(
        api, Paths.SCORECARDS, review_id=review_id, status=ScorecardStatus.VOID
    )
    assert void_meta["total_count"] == 1, void_meta
    assert ids_of(void_rows) == [scorecard_id], ids_of(void_rows)
    assert_status(read_run(api, run_id), LevelizationStatus.VOID)

    # The arms that already fired stay fired.
    assert_status(read_meeting(api, ctx.meetings["abandoned"]["id"]), MeetingStatus.VOID)
    leaving = read_member(api, ctx.members["expiring"]["id"])
    assert_status(leaving, MemberStatus.TERM_EXPIRED)
    assert leaving["end_term_reason"] == EndTermReason.TERM_EXPIRY, leaving
    assert_status(
        validate_success(
            api.get(Paths.training_record(ctx.short_record["id"]), sponsor_headers())
        ),
        TrainingStatus.EXPIRED,
    )
    assert_status(
        validate_success(
            api.get(Paths.training_record(ctx.long_record["id"]), sponsor_headers())
        ),
        TrainingStatus.COMPLETED,
    )

    # Voiding paperwork never touches the menu itself.
    assert_capacity_triple(rolled_twice, occupied=5, reserved=0, available=1)
    assert_ratio(rolled_twice["at_risk_slot_ratio"], "0.0000", "at_risk_slot_ratio")
    assert_status(rolled_twice, MenuPosture.OPEN, "menu_posture")
