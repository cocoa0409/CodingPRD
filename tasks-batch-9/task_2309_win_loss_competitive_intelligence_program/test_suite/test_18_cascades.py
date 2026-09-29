"""
Cascades: the completion chain applies every one of its declared links in one call,
and the bulk sweep skips what is not due instead of rolling the call back.
"""

from test_helpers.assertions import (
    assert_adoption,
    assert_analyst_workload,
    assert_deal_dimensions,
    assert_field,
    assert_fields,
    assert_ledger,
    assert_money,
)
from test_helpers.fixtures import WinLossWorld

CLOCK = "2026-08-01T00:00:00.000Z"


def _drawn_lost_deal(world: WinLossWorld) -> WinLossWorld:
    """One consented ECONOMIC_BUYER loss drawn from a sealed frame."""
    world.set_clock(CLOCK)
    world.active_program()
    world.create_competitor()
    world.create_analyst()
    world.create_deal(primary_competitor_id=world.competitor["id"])
    world.consented_contact(incentive_eligibility="ELIGIBLE")
    world.create_frame()
    world.seal_frame()
    world.draw("LOST", requested_count=1)
    return world


def test_completion_applies_every_declared_link_in_one_call(world):
    """One call, the whole chain: money, ledger, posture, contact, deal and calendar.

    "Completion is the head of the completion posture cascade. Its first link stores the
    two actual instants, sets `coverage_complete` to true, computes `incentive_final_usd`
    by the final variant, moves `incentive_status` `COMMITTED → PAID`, and moves the
    interview `SCHEDULED → COMPLETED`."

    "The fourth link, caused by the third yielding `FROZEN`, transitions every `SEALED`
    sampling frame of the program to `SUSPENDED`."

    Design: Corner/cascading_side_effects/interview_completion_applies_all_seven_declared_links_in_one_call
    """
    _drawn_lost_deal(world)
    world.schedule_interview()
    world.cover_guide(recorded_at="2026-08-10T14:10:00.000Z", rating=4)
    world.set_clock("2026-08-10T15:30:00.000Z")

    completed = world.complete_interview(
        actual_start_at="2026-08-10T14:00:00.000Z",
        actual_end_at="2026-08-10T14:45:00.000Z",
    )

    assert_fields(
        completed,
        {"status": "COMPLETED", "incentive_status": "PAID", "coverage_complete": True},
    )
    assert_money(completed["incentive_final_usd"], 250.00, "incentive_final_usd")
    assert_ledger(world.refresh_program(), committed_usd=0.00, paid_usd=250.00, posture="OPEN")
    assert_field(world.get_frame(), "status", "SEALED")
    assert_fields(
        world.get_contact(),
        {
            "completed_interview_count": 1,
            "last_completed_interview_end_at": "2026-08-10T14:45:00.000Z",
        },
    )
    assert_deal_dimensions(
        world.get_deal(), research_status="INTERVIEWED", interview_coverage_count=1
    )
    assert_analyst_workload(world.get_analyst(), open_interview_count=0, committed_minutes=0)


def test_one_sweep_expires_across_two_cards_and_leaves_the_open_row_alone(world):
    """Skip semantics: the not-due assignment survives and both cards recompute.

    "Every assignment whose `status` is `ASSIGNED` or `FAILED` and whose `due_at` is
    earlier than the logical clock transitions to `EXPIRED`, and every touched card has its
    `assigned_count`, `trained_count` and `adoption_rate` recomputed"

    "The sweep has **skip semantics, not rollback**: assignments that are not past due are
    left untouched and do not cause the call to fail. Its response reports an
    `expired_count`, an `expired_assignment_ids` array and a `recomputed_battlecard_ids`
    array."

    Design: Corner/cascading_side_effects/enablement_sweep_expires_past_due_assignments_on_two_cards_and_skips_the_rest
    """
    _drawn_lost_deal(world)
    second_competitor = world.create_competitor(name="Initech", tier="SECONDARY")
    world.schedule_interview()
    world.cover_guide(recorded_at="2026-08-10T14:10:00.000Z", rating=4)
    world.set_clock("2026-08-10T15:30:00.000Z")
    world.complete_interview(
        actual_start_at="2026-08-10T14:00:00.000Z",
        actual_end_at="2026-08-10T15:00:00.000Z",
    )
    evidence = [world.response_of("COMPETITOR_POSITIONING")["id"]]

    first_card = world.create_battlecard(title="Northwind Battlecard")
    world.add_claim(
        evidence,
        claim_text="Enterprise buyers rate our analytics depth against Northwind",
        claim_type="FEATURE",
    )
    world.submit_legal()
    world.decide_claim("APPROVE")
    world.publish_battlecard()

    second_card = world.create_battlecard(
        competitor_id=second_competitor["id"], title="Initech Battlecard"
    )
    second_claim = world.add_claim(
        evidence,
        battlecard_id=second_card["id"],
        claim_text="Enterprise buyers rate our analytics depth against Initech",
        claim_type="FEATURE",
    )
    world.submit_legal(second_card["id"])
    world.decide_claim(
        "APPROVE", claim_id=second_claim["id"], battlecard_id=second_card["id"]
    )
    world.publish_battlecard(second_card["id"])

    past_due = world.assign(
        sales_rep_user_ref="rep-77", due_at="2026-08-15T00:00:00.000Z"
    )
    still_open = world.assign(
        sales_rep_user_ref="rep-78", due_at="2026-09-30T00:00:00.000Z"
    )
    other_card_past_due = world.assign(
        sales_rep_user_ref="rep-79",
        due_at="2026-08-20T00:00:00.000Z",
        battlecard_id=second_card["id"],
    )
    world.set_clock("2026-08-25T00:00:00.000Z")

    outcome = world.sweep()

    assert_field(outcome, "expired_count", 2)
    expired_ids = set(outcome["expired_assignment_ids"])
    assert past_due["id"] in expired_ids, (
        f"the 2026-08-15 assignment must be reported expired, got {expired_ids}"
    )
    assert other_card_past_due["id"] in expired_ids, (
        f"the 2026-08-20 assignment must be reported expired, got {expired_ids}"
    )
    assert still_open["id"] not in expired_ids, (
        f"the 2026-09-30 assignment must be skipped, got {expired_ids}"
    )
    recomputed = set(outcome["recomputed_battlecard_ids"])
    assert {first_card["id"], second_card["id"]} <= recomputed, (
        f"both touched cards must be reported recomputed, got {recomputed}"
    )

    assert_field(world.get_assignment(past_due["id"]), "status", "EXPIRED")
    assert_field(world.get_assignment(still_open["id"]), "status", "ASSIGNED")
    assert_field(world.get_assignment(other_card_past_due["id"]), "status", "EXPIRED")
    assert_adoption(
        world.get_battlecard(first_card["id"]),
        assigned_count=2,
        trained_count=0,
        adoption_rate=0.0000,
    )
    assert_adoption(
        world.get_battlecard(second_card["id"]),
        assigned_count=1,
        trained_count=0,
        adoption_rate=0.0000,
    )
