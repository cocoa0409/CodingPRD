"""
Writes that are valid in themselves but blocked by the state of a parent entity.

Interview scheduling reads the deal's sampling frame, and legal submission walks a
card's competitor up to the owning program.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_BATTLECARD_STATE_INVALID,
    ERR_CLAIM_UNSUBSTANTIATED,
    ERR_FRAME_STATE_INVALID,
    ERR_PROGRAM_POSTURE_FROZEN,
    ERR_PROGRAM_STATE_INVALID,
)
from test_helpers.assertions import (
    assert_analyst_workload,
    assert_deal_dimensions,
    assert_field,
    assert_ledger,
    assert_ratio,
    assert_substantiation,
)
from test_helpers.fixtures import WinLossWorld


def _selected_deal_whose_frame_was_closed(world: WinLossWorld) -> WinLossWorld:
    """Everything an interview needs, except that the parent frame is CLOSED."""
    world.set_clock("2026-08-01T00:00:00.000Z")
    world.active_program()
    world.create_competitor()
    world.create_analyst()
    world.create_deal(primary_competitor_id=world.competitor["id"])
    world.consented_contact(incentive_eligibility="ELIGIBLE")
    world.create_frame()
    world.seal_frame()
    world.draw("LOST", requested_count=1)
    world.close_frame()
    return world


def _draft_card_under_a_closing_program(world: WinLossWorld) -> WinLossWorld:
    """A submittable DRAFT card whose competitor's program has begun closing."""
    world.set_clock("2026-08-01T00:00:00.000Z")
    world.active_program()
    world.create_competitor()
    world.create_analyst()
    world.create_deal(primary_competitor_id=world.competitor["id"])
    world.consented_contact(incentive_eligibility="ELIGIBLE")
    world.create_frame()
    world.seal_frame()
    world.draw("LOST", requested_count=1)
    world.schedule_interview()
    world.record_response(
        question_key="COMPETITOR_POSITIONING",
        verbatim_text="Northwind names the same three references every time.",
        recorded_at="2026-08-02T14:15:00.000Z",
        rating=4,
        competitor_name_verbatim="Northwind",
    )
    world.record_response(
        question_key="EVALUATION_CRITERIA",
        verbatim_text="Integration depth outranked everything else.",
        recorded_at="2026-08-02T14:20:00.000Z",
    )
    world.record_response(
        question_key="PRICING_PERCEPTION",
        verbatim_text="List price read as fair for the tier.",
        recorded_at="2026-08-02T14:25:00.000Z",
    )
    world.set_clock("2026-08-10T15:30:00.000Z")
    world.complete_interview(
        actual_start_at="2026-08-10T14:00:00.000Z",
        actual_end_at="2026-08-10T14:30:00.000Z",
    )
    world.create_battlecard(title="Northwind", version_label="v1")
    world.add_claim(
        [world.response_of("COMPETITOR_POSITIONING")["id"]],
        claim_text="Northwind reuses the same three references.",
        claim_type="REFERENCE",
    )
    world.begin_closing()
    return world


# ---------------------------------------------------------------------------
# Interview <- SamplingFrame
# ---------------------------------------------------------------------------


def test_the_deal_remains_selected_after_its_frame_is_closed(world):
    """Closing the frame freezes its coverage without touching the drawn deal.

    "A `ResearchAnalyst` may close a frame from either `SEALED` or `SUSPENDED`, which
    freezes `coverage_ratio` at its current value and increments `version`"

    Design: Difficulty/cross_entity_state_dependency/interview_scheduling_blocked_by_closed_sampling_frame
    """
    _selected_deal_whose_frame_was_closed(world)

    frame = world.get_frame()
    assert_field(frame, "status", "CLOSED")
    assert_ratio(frame["coverage_ratio"], 0.2000, "coverage_ratio")
    assert_deal_dimensions(world.get_deal(), research_status="SELECTED")
    program = world.refresh_program()
    assert_field(program, "status", "ACTIVE")
    assert_field(program, "posture", "OPEN")


def test_scheduling_is_refused_because_the_parent_frame_is_no_longer_sealed(world):
    """Every attribute of the request is valid; only the frame's status is wrong.

    "the frame named by the deal's `sampling_frame_id` must be `SEALED`"

    Design: Difficulty/cross_entity_state_dependency/interview_scheduling_blocked_by_closed_sampling_frame
    """
    _selected_deal_whose_frame_was_closed(world)

    validate_error(
        world.api.create_interview(
            f.interview_payload(
                world.deal["id"],
                world.contact["id"],
                world.analyst["id"],
                scheduled_start_at="2026-08-10T14:00:00.000Z",
                scheduled_end_at="2026-08-10T15:00:00.000Z",
            ),
            world.analyst_headers,
        ),
        ERR_FRAME_STATE_INVALID,
        409,
    )


def test_the_refused_scheduling_commits_no_money_and_no_calendar(world):
    """No interview row, no ledger movement and no analyst reservation survive.

    "Scheduling an interview adds its provisional amount to the committed total"

    Design: Difficulty/cross_entity_state_dependency/interview_scheduling_blocked_by_closed_sampling_frame
    """
    _selected_deal_whose_frame_was_closed(world)

    validate_error(
        world.api.create_interview(
            f.interview_payload(
                world.deal["id"],
                world.contact["id"],
                world.analyst["id"],
                scheduled_start_at="2026-08-10T14:00:00.000Z",
                scheduled_end_at="2026-08-10T15:00:00.000Z",
            ),
            world.analyst_headers,
        ),
        ERR_FRAME_STATE_INVALID,
        409,
    )

    items, _ = validate_paginated(world.api.list_interviews(world.admin))
    assert all(item["deal_id"] != world.deal["id"] for item in items), (
        "the refused request must not have left an interview row behind"
    )
    assert_ledger(world.refresh_program(), 0.00, 0.00)
    assert_analyst_workload(world.get_analyst(), 0, 0)
    assert_ratio(world.get_frame()["coverage_ratio"], 0.2000, "coverage_ratio")


# ---------------------------------------------------------------------------
# Battlecard <- Competitor <- Program
# ---------------------------------------------------------------------------


def test_beginning_to_close_the_program_restricts_it_and_closes_its_frames(world):
    """The program moves to CLOSING and drags its frame closed with it.

    "The `ACTIVE → CLOSING` step requires that no interview belonging to any of the
    program's deals is still `SCHEDULED`; it recomputes `posture` under the
    `CLOSING` floor, which forces the result to at least `RESTRICTED`, closes every
    sampling frame of the program whose `status` is `DRAFT`, `SEALED` or
    `SUSPENDED`, and increments `version`."

    Design: Difficulty/cross_entity_state_dependency/battlecard_legal_submission_blocked_by_closing_program
    """
    _draft_card_under_a_closing_program(world)

    program = world.refresh_program()
    assert_field(program, "status", "CLOSING")
    assert_field(program, "posture", "RESTRICTED")
    assert_field(world.get_frame(), "status", "CLOSED")


def test_the_card_itself_is_a_perfectly_submittable_draft(world):
    """Nothing about the card or its claim explains the refusal that follows.

    "The item starts from a source weight read off the response's `question_key`:
    1.00 for `COMPETITOR_POSITIONING`, 0.90 for `PRICING_PERCEPTION`, 0.70 for
    `EVALUATION_CRITERIA`, 0.50 for `LOSS_REASON` and 0.40 for `PRODUCT_GAP`."

    Design: Difficulty/cross_entity_state_dependency/battlecard_legal_submission_blocked_by_closing_program
    """
    _draft_card_under_a_closing_program(world)

    assert_field(world.get_battlecard(), "status", "DRAFT")
    assert_substantiation(world.get_claim(), 1.00, "ANECDOTAL", "LOW")


def test_legal_submission_is_refused_by_the_programs_status_alone(world):
    """The guard is reached only by walking the card's competitor up to the program.

    "the program owning the card's competitor must have `status` `ACTIVE` and a
    `posture` other than `FROZEN`"

    Design: Difficulty/cross_entity_state_dependency/battlecard_legal_submission_blocked_by_closing_program
    """
    _draft_card_under_a_closing_program(world)

    body = validate_error(
        world.api.submit_legal(world.battlecard["id"], world.analyst_headers),
        ERR_PROGRAM_STATE_INVALID,
        409,
    )

    reported = body["error_id"]
    assert reported not in (
        ERR_BATTLECARD_STATE_INVALID,
        ERR_PROGRAM_POSTURE_FROZEN,
        ERR_CLAIM_UNSUBSTANTIATED,
    ), f"the refusal must name the program's lifecycle, got {reported}"
    assert_field(world.get_battlecard(), "status", "DRAFT")
    assert_field(world.get_claim(), "legal_status", "PENDING")
