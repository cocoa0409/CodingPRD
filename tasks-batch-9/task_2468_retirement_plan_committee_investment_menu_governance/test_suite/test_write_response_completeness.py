"""Immediate consistency: a write's own response already carries what it derived.

PRD §2.2 says an operation that creates or modifies a resource returns that
resource in `data`, and PRD §2.4 says `version` advances on every mutation.  Put
together, there is no window in which a derived field is missing from the write
that produced it: the follow-up read is confirmation, never the first sighting.
"""

import pytest

from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_capacity_triple,
    assert_fields,
    assert_ratio,
    assert_score,
    assert_status,
    validate_error,
    validate_success,
)
from test_helpers.factories import (
    Paths,
    convene_payload,
    meeting_payload,
    proposal_payload,
    scorecard_payload,
)
from test_helpers.fixtures import (
    CLEAN_SCORECARDS,
    FUND_SPECS,
    Ctx,
    create_fund,
    hold_meeting_and_carry_motion,
    open_review,
    read_plan,
)
from test_helpers.test_users import consultant_headers, sponsor_headers
from test_helpers.types import (
    MeetingStatus,
    MenuPosture,
    MotionSubjectType,
    ProposalStatus,
    ReviewStatus,
    ScorecardStatus,
    SlotStatus,
    WatchRecommendation,
)


def _object_body(response, expected_status: int = 200) -> dict:
    """Validate a single-resource envelope (PRD 2.2) and return its ``data``."""
    data = validate_success(response, expected_status)
    body = response.json()
    assert body["response_type"] == "object", body["response_type"]
    assert body["meta"]["api_request_id"].startswith("req_"), body["meta"]["api_request_id"]
    assert body["meta"]["api_request_timestamp"], "the envelope carries a request timestamp"
    return data


def test_scheduling_and_convening_a_meeting_return_their_own_quorum_figures(
    api: ApiClient, full_menu: Ctx
):
    """The documented starting values are in the create response and the frozen
    quorum verdict is in the convene response, both confirmed by a re-read.

    Design: Corner/consistency_model/every_field_a_write_derives_is_already_in_that_writes_own_response_body
    """
    ctx = full_menu

    scheduled = _object_body(
        api.post(Paths.MEETINGS, meeting_payload(ctx.plan_id, "2026-08-25", 0), sponsor_headers()),
        201,
    )
    # PRD 3.4: a scheduled meeting is born with every derived figure at rest.
    assert_fields(
        scheduled,
        status=MeetingStatus.SCHEDULED,
        quorum_met=False,
        voting_attendee_count=0,
        eligible_voting_seat_count=0,
        carried_motion_count=0,
        charter_version_pinned=None,
        minutes_doc_ref=None,
        minutes_approved_at=None,
    )
    reread = _object_body(api.get(Paths.meeting(scheduled["id"]), sponsor_headers()))
    assert_fields(
        reread,
        status=MeetingStatus.SCHEDULED,
        quorum_met=False,
        voting_attendee_count=0,
        eligible_voting_seat_count=0,
        carried_motion_count=0,
        version=scheduled["version"],
    )

    pinned_version = read_plan(api, ctx.plan_id)["version"]
    convened = _object_body(
        api.post(Paths.convene(scheduled["id"]), convene_payload(ctx.member_ids), ctx.chair)
    )
    # PRD 3.4: convening is the moment quorum is decided, and the verdict is
    # frozen into this very response.
    assert_fields(
        convened,
        status=MeetingStatus.IN_SESSION,
        eligible_voting_seat_count=3,
        voting_attendee_count=3,
        quorum_met=True,
        charter_version_pinned=pinned_version,
    )
    after_convene = _object_body(api.get(Paths.meeting(scheduled["id"]), sponsor_headers()))
    assert_fields(
        after_convene,
        eligible_voting_seat_count=3,
        voting_attendee_count=3,
        quorum_met=True,
        charter_version_pinned=pinned_version,
        version=convened["version"],
    )


def test_a_scorecard_returns_all_five_components_and_moves_its_review_at_once(
    api: ApiClient, full_menu: Ctx
):
    """The 201 already carries the five components, the composite and the watch
    recommendation, and the parent review is already SCORING.

    Design: Corner/consistency_model/every_field_a_write_derives_is_already_in_that_writes_own_response_body
    """
    ctx = full_menu
    review = open_review(ctx, 0)
    assert_status(review, ReviewStatus.DRAFT)
    review_version_before = review["version"]

    submitted = _object_body(
        api.post(
            Paths.SCORECARDS,
            scorecard_payload(
                review["id"],
                ctx.fund("lc_a")["id"],
                review_version_before,
                **CLEAN_SCORECARDS["lc_a"],
            ),
            consultant_headers(),
        ),
        201,
    )
    # PRD 3.5: 80 bps of excess, a top-quartile peer rank, five basis points of
    # expense over the median, no style drift and a twenty-quarter manager.
    assert_status(submitted, ScorecardStatus.SUBMITTED)
    assert_score(submitted["performance_component"], "58.00", "performance_component")
    assert_score(submitted["peer_component"], "75.00", "peer_component")
    assert_score(submitted["expense_component"], "90.00", "expense_component")
    assert_score(submitted["style_component"], "100.00", "style_component")
    assert_score(submitted["manager_component"], "100.00", "manager_component")
    assert_score(submitted["composite_score"], "76.20", "composite_score")
    assert_status(submitted, WatchRecommendation.NONE, field="watch_recommendation")

    stored = _object_body(api.get(Paths.scorecard(submitted["id"]), consultant_headers()))
    for field in (
        "performance_component",
        "peer_component",
        "expense_component",
        "style_component",
        "manager_component",
        "composite_score",
        "watch_recommendation",
    ):
        assert stored[field] == submitted[field], (
            f"{field} differs between the write response and the read"
        )

    # PRD 3.5: the first scorecard on a DRAFT review moves it to SCORING and the
    # counters move with it.
    parent = _object_body(api.get(Paths.review(review["id"]), consultant_headers()))
    assert_fields(
        parent,
        status=ReviewStatus.SCORING,
        scorecard_count=1,
        submitted_scorecard_count=1,
    )
    assert parent["version"] > review_version_before, (
        "an accepted submission advances the review's version"
    )


def test_the_posture_recompute_returns_the_recomputed_ratio_in_its_own_body(
    api: ApiClient, full_menu: Ctx
):
    """The explicit recompute answers with the plan it just recomputed, version
    bump included, and a fresh read adds nothing.

    Design: Corner/consistency_model/every_field_a_write_derives_is_already_in_that_writes_own_response_body
    """
    ctx = full_menu
    before = read_plan(api, ctx.plan_id)

    recomputed = _object_body(
        api.post(Paths.recompute_posture(ctx.plan_id), {}, consultant_headers())
    )
    # PRD 2.9: five seated slots, none at risk, so the ratio is 0.0000 and the
    # posture stays OPEN; PRD 3.9 still increments the plan's version.
    assert_ratio(recomputed["at_risk_slot_ratio"], "0.0000", "at_risk_slot_ratio")
    assert_status(recomputed, MenuPosture.OPEN, field="menu_posture")
    assert recomputed["version"] == before["version"] + 1
    assert_capacity_triple(recomputed, occupied=5, reserved=0, available=1)

    after = _object_body(api.get(Paths.plan(ctx.plan_id), consultant_headers()))
    assert_fields(
        after,
        at_risk_slot_ratio=recomputed["at_risk_slot_ratio"],
        menu_posture=recomputed["menu_posture"],
        version=recomputed["version"],
    )


@pytest.fixture
def replacement_awaiting_approval(api: ApiClient, submitted_replacement: Ctx):
    """A large-cap replacement in UNDER_REVIEW behind a carried motion whose
    meeting minutes are approved, so approval is one call away."""
    ctx = submitted_replacement
    motion = hold_meeting_and_carry_motion(
        ctx,
        MotionSubjectType.FUND_REPLACEMENT,
        ctx.proposals["proposal"]["id"],
        meeting_date="2026-08-17",
        minutes_doc_ref="MIN-2026-Q0-003",
        key="replacement",
    )
    return ctx, motion


def test_the_approval_fan_out_is_whole_on_the_first_read_of_every_row(
    api: ApiClient, replacement_awaiting_approval
):
    """Approving reserves a menu position, and the reservation, the counter move
    and the slot's new status are all there the first time each row is read.

    Design: Corner/consistency_model/the_approval_fan_out_is_complete_on_the_first_read_and_the_version_bump_is_not_deferred
    """
    ctx, motion = replacement_awaiting_approval
    proposal_id = ctx.proposals["proposal"]["id"]
    slot_id = ctx.slot("lc")["id"]
    before = read_plan(api, ctx.plan_id)

    approved = _object_body(
        api.post(
            Paths.proposal_approve(proposal_id),
            {"approving_motion_id": motion["id"]},
            ctx.chair,
        )
    )
    # PRD 3.7: the approval response itself shows the transition out of
    # UNDER_REVIEW together with the authorising motion and the pinned statement.
    assert_status(approved, ProposalStatus.APPROVED)
    assert approved["approving_motion_id"] == motion["id"]
    assert approved["pinned_ips_id"] == ctx.ips_id

    first_read = _object_body(api.get(Paths.plan(ctx.plan_id), sponsor_headers()))
    assert_capacity_triple(first_read, occupied=5, reserved=1, available=0)
    assert first_read["draft_proposal_count"] == 0
    assert first_read["version"] == before["version"] + 1, (
        "the plan's version bump is not deferred past the approval"
    )

    second_read = _object_body(api.get(Paths.plan(ctx.plan_id), sponsor_headers()))
    assert_fields(
        second_read,
        occupied_menu_slots=first_read["occupied_menu_slots"],
        reserved_menu_slots=first_read["reserved_menu_slots"],
        available_menu_slots=first_read["available_menu_slots"],
        draft_proposal_count=first_read["draft_proposal_count"],
        at_risk_slot_ratio=first_read["at_risk_slot_ratio"],
        menu_posture=first_read["menu_posture"],
        version=first_read["version"],
    )

    slot = _object_body(api.get(Paths.slot(slot_id), sponsor_headers()))
    assert_status(slot, SlotStatus.PENDING_REPLACEMENT)
    assert slot["current_fund_id"] == ctx.fund("lc_a")["id"], (
        "the outgoing fund keeps the seat until the mapping executes"
    )


def test_the_version_bump_is_visible_to_the_very_next_concurrency_check(
    api: ApiClient, replacement_awaiting_approval
):
    """A token minted before the approval is already stale afterwards, and the
    post-approval token is accepted immediately.

    Design: Corner/consistency_model/the_approval_fan_out_is_complete_on_the_first_read_and_the_version_bump_is_not_deferred
    """
    ctx, motion = replacement_awaiting_approval

    # A second small-cap candidate, so the probe below aims at an untouched slot
    # and no state gate can pre-empt the concurrency check (PRD 2.12).
    spare = dict(FUND_SPECS["small"])
    spare.update(ticker="SMLVB", fund_name="Summit Small Cap Value Institutional")
    create_fund(ctx, "small_b", **spare)

    stale_token = read_plan(api, ctx.plan_id)["version"]
    validate_success(
        api.post(
            Paths.proposal_approve(ctx.proposals["proposal"]["id"]),
            {"approving_motion_id": motion["id"]},
            ctx.chair,
        )
    )
    fresh_token = read_plan(api, ctx.plan_id)["version"]
    assert fresh_token == stale_token + 1

    body = proposal_payload(
        ctx.plan_id,
        ctx.slot("small")["id"],
        ctx.fund("small")["id"],
        ctx.fund("small_b")["id"],
        stale_token,
    )
    validate_error(
        api.post(Paths.REPLACEMENTS, body, consultant_headers()),
        ApiErrorId.STALE_PLAN_VERSION,
    )
    unchanged = read_plan(api, ctx.plan_id)
    assert unchanged["version"] == fresh_token, "a refused creation writes nothing"
    assert unchanged["draft_proposal_count"] == 0

    body["expected_plan_version"] = fresh_token
    created = _object_body(api.post(Paths.REPLACEMENTS, body, consultant_headers()), 201)
    assert_status(created, ProposalStatus.DRAFT)
    assert created["pinned_plan_version"] == fresh_token, (
        "the accepted token is what the proposal pins"
    )
    after = read_plan(api, ctx.plan_id)
    assert after["draft_proposal_count"] == 1
    assert after["version"] == fresh_token + 1
