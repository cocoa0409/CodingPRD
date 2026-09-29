"""
Thresholds read in both directions: the posture ladder falls back when the ledger is
released, and the open-interview cap blocks at the boundary then frees the slot.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import ERR_ANALYST_CAPACITY_EXCEEDED
from test_helpers.assertions import (
    assert_analyst_workload,
    assert_field,
    assert_fields,
    assert_ledger,
    assert_money,
    assert_null,
    assert_pagination_meta,
)

CLOCK = "2026-08-01T00:00:00.000Z"


def test_cancelling_the_only_interview_returns_the_posture_to_open(world):
    """The ladder is re-evaluated downward, not latched at its tightest reading.

    "The ladder is evaluated from the top and its boundaries are inclusive: utilization of
    at least 1.0000 yields `FROZEN`; otherwise utilization of at least 0.8500 yields
    `RESTRICTED`; otherwise `OPEN`."

    "From `SCHEDULED`, cancellation is a compensating transition: `incentive_status` moves
    `COMMITTED → RELEASED`, the program's `incentive_committed_usd` decreases by the
    provisional amount so the ledger returns to exactly its pre-scheduling value, `posture`
    is recomputed, and the analyst's still-held counters are released."

    Design: Corner/rate_threshold_triggers/cancelling_the_only_interview_resets_the_posture_from_restricted_to_open
    """
    world.set_clock(CLOCK)
    world.active_program(incentive_budget_usd=280.00)
    world.create_competitor()
    world.create_analyst()
    world.create_deal(primary_competitor_id=world.competitor["id"])
    world.consented_contact(incentive_eligibility="ELIGIBLE")
    world.create_frame()
    world.seal_frame()
    world.draw("LOST", requested_count=1)
    interview = world.schedule_interview()

    before = world.refresh_program()
    assert_ledger(before, committed_usd=250.00, paid_usd=0.00, posture="RESTRICTED")
    assert_money(before["incentive_budget_usd"], 280.00, "incentive_budget_usd")

    cancelled = validate_success(
        world.api.cancel_interview(
            interview["id"],
            world.analyst_headers,
            f.cancel_payload(cancel_reason="buyer withdrew"),
        ),
        200,
    )

    assert_fields(
        cancelled, {"status": "CANCELLED", "incentive_status": "RELEASED"}
    )
    assert_null(cancelled["incentive_final_usd"], "incentive_final_usd")
    assert_ledger(world.refresh_program(), committed_usd=0.00, paid_usd=0.00, posture="OPEN")
    assert_field(world.get_frame(), "status", "SEALED")
    assert_analyst_workload(world.get_analyst(), open_interview_count=0, committed_minutes=0)
    assert_field(world.get_deal(), "research_status", "SELECTED")


def test_the_open_interview_cap_blocks_until_a_completion_frees_the_slot(world):
    """Being at the cap is already a violation, and completion is what releases it.

    "The analyst's `open_interview_count` must be strictly less than the program's
    `max_open_interviews_per_analyst`, or the request fails with
    `ERR_ANALYST_CAPACITY_EXCEEDED` — each individual interview may be legal while the
    collective open workload is not."

    "the analyst's `open_interview_count` decreases by one while its `committed_minutes`
    decreases by the scheduled duration plus fifteen"

    Design: Corner/rate_threshold_triggers/analyst_at_the_open_interview_cap_is_blocked_until_a_completion_frees_the_slot
    """
    world.set_clock(CLOCK)
    world.active_program(max_open_interviews_per_analyst=1)
    world.create_competitor()
    analyst = world.create_analyst()
    first_deal = world.create_deal(
        crm_deal_ref="CRM-3001", primary_competitor_id=world.competitor["id"]
    )
    second_deal = world.create_deal(
        crm_deal_ref="CRM-3002", primary_competitor_id=world.competitor["id"]
    )
    world.consented_contact(deal_id=first_deal["id"], email="buyer1@acme.test")
    second_contact = world.consented_contact(
        deal_id=second_deal["id"], email="buyer2@acme.test"
    )
    world.create_frame()
    world.seal_frame()
    world.draw("LOST", requested_count=2)
    first_interview = world.schedule_interview(
        deal_id=first_deal["id"], buyer_contact_id=world.contact["id"]
    )
    world.cover_guide(
        interview_id=first_interview["id"],
        recorded_at="2026-08-10T14:10:00.000Z",
        rating=4,
    )
    second_booking = f.interview_payload(
        second_deal["id"],
        second_contact["id"],
        analyst["id"],
        scheduled_start_at="2026-08-11T09:00:00.000Z",
        scheduled_end_at="2026-08-11T10:00:00.000Z",
    )

    validate_error(
        world.api.create_interview(second_booking, world.analyst_headers),
        ERR_ANALYST_CAPACITY_EXCEEDED,
        409,
    )

    assert_analyst_workload(world.get_analyst(), open_interview_count=1, committed_minutes=75)
    _, meta = validate_paginated(world.api.list_interviews(world.admin))
    assert_pagination_meta(meta, expected_total=1)

    world.set_clock("2026-08-10T15:30:00.000Z")
    completed = validate_success(
        world.api.complete_interview(
            first_interview["id"],
            f.complete_interview_payload(
                "2026-08-10T14:00:00.000Z", "2026-08-10T14:45:00.000Z"
            ),
            world.analyst_headers,
        ),
        200,
    )
    assert_field(completed, "status", "COMPLETED")
    assert_money(completed["incentive_final_usd"], 250.00, "incentive_final_usd")
    assert_analyst_workload(world.get_analyst(), open_interview_count=0, committed_minutes=0)

    accepted = validate_success(
        world.api.create_interview(second_booking, world.analyst_headers), 201
    )

    assert_field(accepted, "status", "SCHEDULED")
    assert_money(
        accepted["incentive_provisional_usd"], 250.00, "incentive_provisional_usd"
    )
    assert_analyst_workload(world.get_analyst(), open_interview_count=1, committed_minutes=75)
    assert_ledger(world.refresh_program(), committed_usd=250.00, paid_usd=250.00, posture="OPEN")
