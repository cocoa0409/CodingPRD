"""
Multi-link cascades where each link is caused by the one before it.

An over-running completion pushes the ledger past the budget and suspends the
sampling frame; a rejection on the last approved claim withdraws a published card
and expires its outstanding training.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_adoption,
    assert_claim_counters,
    assert_deal_dimensions,
    assert_field,
    assert_frame_slots,
    assert_ledger,
    assert_money,
    assert_not_null,
    assert_risk_indices,
    assert_substantiation,
)
from test_helpers.fixtures import WinLossWorld


def _tight_budget_interview(world: WinLossWorld) -> WinLossWorld:
    """A 60-minute booking against a 300.00 budget, answered and ready to complete."""
    world.set_clock("2026-08-01T00:00:00.000Z")
    world.active_program(incentive_budget_usd=300.00)
    world.create_competitor()
    world.create_analyst()
    world.create_deal(primary_competitor_id=world.competitor["id"])
    world.consented_contact(incentive_eligibility="ELIGIBLE")
    world.create_frame()
    world.seal_frame()
    world.draw("LOST", requested_count=1)
    world.schedule_interview()
    world.cover_guide(recorded_at="2026-08-10T14:10:00.000Z", rating=4)
    world.set_clock("2026-08-10T15:30:00.000Z")
    return world


def _published_card_with_one_assignment(world: WinLossWorld) -> WinLossWorld:
    """A published card carrying exactly one approved claim and one assignment."""
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
        question_key="EVALUATION_CRITERIA",
        verbatim_text="Integration depth decided it.",
        recorded_at="2026-08-10T14:10:00.000Z",
        rating=4,
    )
    world.record_response(
        question_key="COMPETITOR_POSITIONING",
        verbatim_text="Northwind claimed a 30 day rollout in the bake-off.",
        recorded_at="2026-08-10T14:15:00.000Z",
        rating=4,
        competitor_name_verbatim="Northwind",
    )
    world.record_response(
        question_key="PRICING_PERCEPTION",
        verbatim_text="We were 20 percent above.",
        recorded_at="2026-08-10T14:20:00.000Z",
        rating=2,
    )
    world.set_clock("2026-08-10T15:30:00.000Z")
    world.complete_interview(
        actual_start_at="2026-08-10T14:00:00.000Z", actual_end_at="2026-08-10T15:00:00.000Z"
    )
    world.create_battlecard(title="Northwind", version_label="v1")
    world.add_claim(
        [world.response_of("COMPETITOR_POSITIONING")["id"]],
        claim_text="Northwind cites a 30 day rollout in competitive bake-offs.",
        claim_type="REFERENCE",
    )
    world.submit_legal()
    world.decide_claim("APPROVE")
    world.publish_battlecard()
    world.assign(sales_rep_user_ref="rep-90", due_at="2026-09-30T00:00:00.000Z")
    return world


# ---------------------------------------------------------------------------
# Completion posture cascade
# ---------------------------------------------------------------------------


def test_an_over_running_completion_pays_more_than_it_committed(world):
    """An 80-minute actual interval reaches the extended duration tier.

    "a duration factor is selected from a ladder evaluated from the top with the
    first match winning: at least 75 minutes gives a factor of 1.25, otherwise at
    least 45 minutes gives 1.00, otherwise at least 25 minutes gives 0.60, and
    anything shorter gives 0.00."

    Design: Difficulty/transitive_cascade/overrun_completion_cascades_to_frozen_posture_and_suspended_frame
    """
    _tight_budget_interview(world)
    assert_field(world.refresh_program(), "posture", "OPEN")

    body = validate_success(
        world.api.complete_interview(
            world.interview["id"],
            f.complete_interview_payload("2026-08-10T14:00:00.000Z", "2026-08-10T15:20:00.000Z"),
            world.analyst_headers,
        ),
        200,
    )
    interview = body

    assert_field(interview, "status", "COMPLETED")
    assert_money(interview["incentive_final_usd"], 312.50, "incentive_final_usd")
    assert_field(interview, "incentive_status", "PAID")


def test_the_overrun_drives_the_ledger_past_the_budget_and_freezes_the_posture(world):
    """Paying 312.50 out of a 300.00 budget takes utilization over the freeze line.

    "The third link, caused by that ledger change, recomputes the program's
    `posture`."

    Design: Difficulty/transitive_cascade/overrun_completion_cascades_to_frozen_posture_and_suspended_frame
    """
    _tight_budget_interview(world)
    assert_ledger(world.refresh_program(), 250.00, 0.00, "OPEN")

    validate_success(
        world.api.complete_interview(
            world.interview["id"],
            f.complete_interview_payload("2026-08-10T14:00:00.000Z", "2026-08-10T15:20:00.000Z"),
            world.analyst_headers,
        ),
        200,
    )

    assert_ledger(world.refresh_program(), 0.00, 312.50, "FROZEN")


def test_the_frozen_posture_suspends_the_sealed_sampling_frame(world):
    """The fourth link reaches an entity the completion never named.

    "The fourth link, caused by the third yielding `FROZEN`, transitions every
    `SEALED` sampling frame of the program to `SUSPENDED`."

    Design: Difficulty/transitive_cascade/overrun_completion_cascades_to_frozen_posture_and_suspended_frame
    """
    _tight_budget_interview(world)
    assert_field(world.get_frame(), "status", "SEALED")

    validate_success(
        world.api.complete_interview(
            world.interview["id"],
            f.complete_interview_payload("2026-08-10T14:00:00.000Z", "2026-08-10T15:20:00.000Z"),
            world.analyst_headers,
        ),
        200,
    )

    frame = world.get_frame()
    assert_field(frame, "status", "SUSPENDED")
    assert_frame_slots(frame, selected_lost=1, open_lost=1)
    assert_deal_dimensions(world.get_deal(), research_status="INTERVIEWED")


# ---------------------------------------------------------------------------
# Claim rejection withdrawal cascade
# ---------------------------------------------------------------------------


def test_rejecting_the_only_approved_claim_empties_the_risk_input_set(world):
    """The rejected claim leaves the card's risk entirely, collapsing both indices.

    "Stage one fixes the input set as the card's claims whose `legal_status` is
    anything other than `REJECTED`; a rejected claim is removed from the card's
    risk entirely. If that set is empty, both `risk_index_pre` and
    `risk_index_final` are 0.00 and no further stage runs."

    Design: Difficulty/transitive_cascade/claim_rejection_cascades_to_withdrawn_card_and_expired_assignments
    """
    _published_card_with_one_assignment(world)
    assert_substantiation(world.get_claim(), 1.00, "ANECDOTAL", "LOW")
    before = world.get_battlecard()
    assert_field(before, "status", "PUBLISHED")
    assert_risk_indices(before, 1.00, 1.00)
    assert_claim_counters(before, approved=1)

    validate_success(
        world.api.legal_decision(
            world.battlecard["id"],
            world.claim["id"],
            f.legal_decision_payload(
                "REJECT",
                conditions_note="Substantiating verbatim retracted by the buyer.",
            ),
            world.legal,
        ),
        200,
    )

    assert_field(world.get_claim(), "legal_status", "REJECTED")
    after = world.get_battlecard()
    assert_claim_counters(after, approved=0, rejected=1)
    assert_risk_indices(after, 0.00, 0.00)


def test_the_rejection_withdraws_the_published_card_and_keeps_its_publication_stamp(world):
    """With no approved claim left, the published card is withdrawn.

    "the card moves `PUBLISHED → WITHDRAWN` while retaining `published_at` for
    audit"

    Design: Difficulty/transitive_cascade/claim_rejection_cascades_to_withdrawn_card_and_expired_assignments
    """
    _published_card_with_one_assignment(world)
    assert_not_null(world.get_battlecard()["published_at"], "published_at")

    validate_success(
        world.api.legal_decision(
            world.battlecard["id"],
            world.claim["id"],
            f.legal_decision_payload(
                "REJECT",
                conditions_note="Substantiating verbatim retracted by the buyer.",
            ),
            world.legal,
        ),
        200,
    )

    card = world.get_battlecard()
    assert_field(card, "status", "WITHDRAWN")
    assert_not_null(card["published_at"], "published_at")


def test_the_withdrawal_expires_the_assignment_and_decrements_the_competitor(world):
    """The third link reaches the assignment and the competitor's card counter.

    "every assignment on it whose `status` is `ASSIGNED` or `FAILED` transitions to
    `EXPIRED`, the competitor's `published_battlecard_count` decreases by one, and
    `adoption_rate`, `assigned_count` and `trained_count` are all recomputed"

    Design: Difficulty/transitive_cascade/claim_rejection_cascades_to_withdrawn_card_and_expired_assignments
    """
    _published_card_with_one_assignment(world)
    assert_field(world.get_competitor(), "published_battlecard_count", 1)
    assert_field(world.get_assignment(), "status", "ASSIGNED")

    validate_success(
        world.api.legal_decision(
            world.battlecard["id"],
            world.claim["id"],
            f.legal_decision_payload(
                "REJECT",
                conditions_note="Substantiating verbatim retracted by the buyer.",
            ),
            world.legal,
        ),
        200,
    )

    assert_field(world.get_assignment(), "status", "EXPIRED")
    assert_field(world.get_competitor(), "published_battlecard_count", 0)
    assert_adoption(
        world.get_battlecard(), assigned_count=1, trained_count=0, adoption_rate=0.0000
    )
