"""Ordering of the rejection gates when a single request breaks two rules.

PRD 2.12 numbers every check, and the number is part of the contract: when one
call violates two gates at once the caller must see the lower-numbered gate's
error, and only after that violation is repaired does the higher-numbered one
become visible.  Each test here breaks both gates together, pins the winning
error, then flips exactly one thing and pins the loser.
"""

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    NON_EXISTENT_UUID,
    assert_fields,
    assert_score,
    assert_status,
    get_success_data,
    validate_error,
)
from test_helpers.factories import Paths, convene_payload, scorecard_payload
from test_helpers.fixtures import (
    adjourn,
    convene,
    create_fund,
    create_slot,
    open_meeting,
    open_review,
    present_review,
    read_meeting,
    read_review,
    review_version,
    schedule_meeting,
    seat_fund,
    setup_adopted_ips,
    submit_scorecard,
)
from test_helpers.test_users import chair_headers, consultant_headers
from test_helpers.types import (
    AssetClass,
    MeetingStatus,
    ReviewStatus,
    ScorecardStatus,
)

# --------------------------------------------------------------------------
# Scenario builders
# --------------------------------------------------------------------------

#: One quarter's measurement of the large-cap holding, scoring 77.40 under the
#: default policy weights of PRD 3.6.
LARGE_CAP_MEASUREMENT = {
    "trailing_return_3y_bps": 900,
    "trailing_return_5y_bps": 850,
    "benchmark_return_3y_bps": 800,
    "benchmark_return_5y_bps": 800,
    "peer_rank_pct": 25,
    "style_drift_r2": 0.9000,
    "net_expense_ratio_bps": 42,
    "peer_median_expense_bps": 40,
    "manager_tenure_quarters": 24,
    "manager_change_flag": False,
}

#: The core-bond holding's measurement, scoring 79.52.
CORE_BOND_MEASUREMENT = {
    "trailing_return_3y_bps": 850,
    "trailing_return_5y_bps": 820,
    "benchmark_return_3y_bps": 800,
    "benchmark_return_5y_bps": 800,
    "peer_rank_pct": 10,
    "style_drift_r2": 0.9500,
    "net_expense_ratio_bps": 30,
    "peer_median_expense_bps": 40,
    "manager_tenure_quarters": 24,
    "manager_change_flag": False,
}


def _large_cap_fund(ctx):
    return create_fund(
        ctx,
        "lg",
        ticker="LRLGX",
        fund_name="Larkspur Large Cap Core",
        asset_class_code=AssetClass.US_LARGE_CAP,
        gross_expense_ratio_bps=48,
        net_expense_ratio_bps=42,
        revenue_share_bps=6,
        peer_median_expense_bps=40,
        track_record_quarters=24,
        manager_tenure_quarters=24,
        manager_change_flag=False,
        style_drift_r2=0.9000,
        plan_assets_cents=2500000,
    )


def _single_slot_review(client):
    """A governed plan with one seated large-cap slot and a scoring review that
    already holds that fund's scorecard."""
    ctx = setup_adopted_ips(client)
    _large_cap_fund(ctx)
    create_slot(ctx, "lg", AssetClass.US_LARGE_CAP, 1)
    seat_fund(ctx, "lg", "lg")
    open_review(ctx, 0)
    submit_scorecard(ctx, "lg", LARGE_CAP_MEASUREMENT)
    return ctx


def _two_slot_review(client):
    """Two seated slots but only the large-cap scorecard submitted, so the
    coverage gate of PRD 3.5 is still unsatisfied."""
    ctx = setup_adopted_ips(client)
    _large_cap_fund(ctx)
    create_fund(
        ctx,
        "bd",
        ticker="LRCBX",
        fund_name="Larkspur Core Bond Institutional",
        asset_class_code=AssetClass.CORE_BOND,
        gross_expense_ratio_bps=34,
        net_expense_ratio_bps=30,
        revenue_share_bps=4,
        peer_median_expense_bps=40,
        track_record_quarters=24,
        manager_tenure_quarters=24,
        manager_change_flag=False,
        style_drift_r2=0.9500,
        plan_assets_cents=1500000,
    )
    create_slot(ctx, "lg", AssetClass.US_LARGE_CAP, 1)
    create_slot(ctx, "bd", AssetClass.CORE_BOND, 2)
    seat_fund(ctx, "lg", "lg")
    seat_fund(ctx, "bd", "bd")
    open_review(ctx, 0)
    submit_scorecard(ctx, "lg", LARGE_CAP_MEASUREMENT)
    return ctx


# --------------------------------------------------------------------------
# Convene: role authorisation (20) and committee identity (25) before
# existence (30)
# --------------------------------------------------------------------------


def test_convene_role_check_beats_unknown_meeting_id(api, governed_plan):
    """A consultant convening a meeting that does not exist is refused for the
    role, and the missing meeting only surfaces once the chair calls.

    Design: Difficulty/priority_pair_validation_conflict/auth_ladder_20_and_25_precede_existence_30_on_convene
    """
    ctx = governed_plan
    body = convene_payload(ctx.member_ids)

    wrong_role = ctx.client.post(
        Paths.convene(NON_EXISTENT_UUID), body, consultant_headers()
    )
    validate_error(wrong_role, ApiErrorId.ROLE_NOT_PERMITTED)

    right_role = ctx.client.post(Paths.convene(NON_EXISTENT_UUID), body, ctx.chair)
    validate_error(right_role, ApiErrorId.RESOURCE_NOT_FOUND)


def test_convene_seat_identity_check_beats_unknown_attendee(api, governed_plan):
    """A non-chair seat holder convening with a bogus attendee on the roster is
    refused on identity; the unresolvable attendee only surfaces for the chair.

    Design: Difficulty/priority_pair_validation_conflict/auth_ladder_20_and_25_precede_existence_30_on_convene
    """
    ctx = governed_plan
    meeting = schedule_meeting(ctx, "2026-08-05")
    body = convene_payload(ctx.member_ids + [NON_EXISTENT_UUID])

    not_the_chair = ctx.client.post(
        Paths.convene(meeting["id"]),
        body,
        chair_headers(ctx.members["finance"]["id"]),
    )
    validate_error(not_the_chair, ApiErrorId.ACTOR_NOT_COMMITTEE_MEMBER)

    actual_chair = ctx.client.post(Paths.convene(meeting["id"]), body, ctx.chair)
    validate_error(actual_chair, ApiErrorId.RESOURCE_NOT_FOUND)

    assert_status(read_meeting(ctx.client, meeting["id"]), MeetingStatus.SCHEDULED)


def test_convene_opens_the_meeting_once_every_gate_is_satisfied(api, governed_plan):
    """With the chair calling and every attendee resolvable, convening freezes
    the quorum figures and pins the charter version.

    Design: Difficulty/priority_pair_validation_conflict/auth_ladder_20_and_25_precede_existence_30_on_convene
    """
    ctx = governed_plan
    meeting = schedule_meeting(ctx, "2026-08-05")
    charter_version = ctx.plan_version

    convened = convene(ctx, meeting["id"])

    assert_fields(
        convened,
        status=MeetingStatus.IN_SESSION,
        voting_attendee_count=3,
        eligible_voting_seat_count=3,
        quorum_met=True,
        charter_version_pinned=charter_version,
    )


# --------------------------------------------------------------------------
# Scorecards: the review's state (42) before the concurrency token (46)
# --------------------------------------------------------------------------


def test_stale_token_is_a_concurrency_failure_while_the_review_scores(api):
    """PRD 3.5: a scorecard carrying a superseded review version is refused with
    the concurrency error while the review is still scoring, and nothing is
    written.

    Design: Difficulty/priority_pair_validation_conflict/review_state_42_precedes_stale_review_version_46
    """
    ctx = _single_slot_review(api)
    stale = ctx.review["version"]
    first_card = ctx.scorecards["lg"]

    resp = ctx.client.post(
        Paths.SCORECARDS,
        scorecard_payload(
            ctx.review["id"], ctx.fund("lg")["id"], stale, **LARGE_CAP_MEASUREMENT
        ),
        consultant_headers(),
    )
    validate_error(resp, ApiErrorId.STALE_REVIEW_VERSION)

    review = read_review(ctx.client, ctx.review["id"])
    assert_fields(
        review, status=ReviewStatus.SCORING, submitted_scorecard_count=1
    )
    assert review["version"] > stale, (
        "the accepted submission should already have moved the review past the "
        f"snapshot version {stale}"
    )
    stored = get_success_data(
        ctx.client.get(Paths.scorecard(first_card["id"]), consultant_headers())
    )
    assert_fields(
        stored,
        status=ScorecardStatus.SUBMITTED,
        supersedes_scorecard_id=None,
    )


def test_presented_review_reports_state_not_concurrency_for_a_stale_token(api):
    """Once the review is presented the state gate fires first, so both a stale
    and an exactly-current token get the not-scoring error rather than a 412.

    Design: Difficulty/priority_pair_validation_conflict/review_state_42_precedes_stale_review_version_46
    """
    ctx = _single_slot_review(api)
    stale = ctx.review["version"]

    meeting = open_meeting(ctx, "2026-08-10")
    presented = present_review(ctx, meeting["id"])
    assert_fields(
        presented, status=ReviewStatus.PENDING_MINUTES, meeting_id=meeting["id"]
    )

    review_id = presented["id"]
    fund_id = ctx.fund("lg")["id"]

    with_stale_token = ctx.client.post(
        Paths.SCORECARDS,
        scorecard_payload(review_id, fund_id, stale, **LARGE_CAP_MEASUREMENT),
        consultant_headers(),
    )
    validate_error(with_stale_token, ApiErrorId.REVIEW_NOT_SCORING)

    with_current_token = ctx.client.post(
        Paths.SCORECARDS,
        scorecard_payload(
            review_id,
            fund_id,
            review_version(ctx.client, review_id),
            **LARGE_CAP_MEASUREMENT,
        ),
        consultant_headers(),
    )
    validate_error(with_current_token, ApiErrorId.REVIEW_NOT_SCORING)

    assert_fields(
        read_review(ctx.client, review_id),
        status=ReviewStatus.PENDING_MINUTES,
        submitted_scorecard_count=1,
    )


# --------------------------------------------------------------------------
# Presentation: quorum (58) before scorecard coverage (78)
# --------------------------------------------------------------------------


def test_presentation_reports_quorum_before_missing_coverage(api):
    """PRD 3.5 checks the meeting's frozen quorum before it checks that every
    occupied slot has been scored.

    Design: Difficulty/priority_pair_validation_conflict/quorum_58_precedes_scorecard_coverage_78_on_present
    """
    ctx = _two_slot_review(api)
    assert_score(ctx.scorecards["lg"]["composite_score"], "77.40", "large cap score")

    thin_meeting = schedule_meeting(ctx, "2026-08-10")
    convened = convene(ctx, thin_meeting["id"], [ctx.chair_id])
    assert_fields(
        convened,
        voting_attendee_count=1,
        eligible_voting_seat_count=3,
        quorum_met=False,
    )

    resp = ctx.client.post(
        Paths.review_present(ctx.review["id"]),
        {"meeting_id": thin_meeting["id"]},
        consultant_headers(),
    )
    validate_error(resp, ApiErrorId.QUORUM_NOT_MET)

    assert_fields(
        read_review(ctx.client, ctx.review["id"]),
        status=ReviewStatus.SCORING,
        meeting_id=None,
    )


def test_coverage_gate_surfaces_only_after_the_meeting_is_quorate(api):
    """With the quorum repaired the same presentation is refused for incomplete
    coverage, and it succeeds once the second holding is scored.

    Design: Difficulty/priority_pair_validation_conflict/quorum_58_precedes_scorecard_coverage_78_on_present
    """
    ctx = _two_slot_review(api)
    review_id = ctx.review["id"]

    thin_meeting = schedule_meeting(ctx, "2026-08-10")
    convene(ctx, thin_meeting["id"], [ctx.chair_id])
    not_quorate = ctx.client.post(
        Paths.review_present(review_id),
        {"meeting_id": thin_meeting["id"]},
        consultant_headers(),
    )
    validate_error(not_quorate, ApiErrorId.QUORUM_NOT_MET)
    adjourn(ctx, thin_meeting["id"])

    quorate = open_meeting(ctx, "2026-08-17")
    assert_fields(
        quorate,
        voting_attendee_count=3,
        eligible_voting_seat_count=3,
        quorum_met=True,
    )

    uncovered = ctx.client.post(
        Paths.review_present(review_id),
        {"meeting_id": quorate["id"]},
        consultant_headers(),
    )
    validate_error(uncovered, ApiErrorId.SCORECARD_COVERAGE_INCOMPLETE)

    bond_card = submit_scorecard(ctx, "bd", CORE_BOND_MEASUREMENT)
    assert_score(bond_card["composite_score"], "79.52", "core bond score")

    presented = present_review(ctx, quorate["id"])
    assert_fields(
        presented,
        status=ReviewStatus.PENDING_MINUTES,
        meeting_id=quorate["id"],
        submitted_scorecard_count=2,
    )
    assert_fields(
        read_meeting(ctx.client, thin_meeting["id"]),
        status=MeetingStatus.ADJOURNED,
        quorum_met=False,
    )
