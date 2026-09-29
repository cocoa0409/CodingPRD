"""
Read-after-write: a triage that enlarges the evidence set answers with the already
re-scored gap, and the following read repeats it exactly.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_field,
    assert_fields,
    assert_money,
)
from test_helpers.fixtures import WinLossWorld

CLOCK = "2026-08-01T00:00:00.000Z"


def _gap_verbatim_deal(
    world: WinLossWorld,
    crm_deal_ref: str,
    email: str,
    acr_usd: float,
    scheduled_start_at: str,
    scheduled_end_at: str,
    recorded_at: str,
) -> dict:
    """One drawn loss with a fully covered interview and a PRODUCT_GAP verbatim on file."""
    deal = world.create_deal(
        crm_deal_ref=crm_deal_ref,
        acr_usd=acr_usd,
        primary_competitor_id=world.competitor["id"],
    )
    contact = world.consented_contact(deal_id=deal["id"], email=email)
    world.draw("LOST", requested_count=1, deal_id=deal["id"])
    interview = world.schedule_interview(
        deal_id=deal["id"],
        buyer_contact_id=contact["id"],
        scheduled_start_at=scheduled_start_at,
        scheduled_end_at=scheduled_end_at,
    )
    world.cover_guide(interview_id=interview["id"], recorded_at=recorded_at, rating=4)
    gap_response = world.record_response(
        interview_id=interview["id"],
        question_key="PRODUCT_GAP",
        verbatim_text="Scheduled evidence exports could not reach our own bucket.",
        recorded_at=recorded_at,
    )
    return {"deal": deal, "interview": interview, "gap_response": gap_response}


def test_a_triage_answers_with_the_already_rescored_gap(world):
    """The enlarged evidence set is scored inside the same call, not on the next read.

    "When that array is supplied, the evidence set grows and `linked_deal_count`,
    `affected_acr_usd`, `impact_score` and `roadmap_priority_band` are all recomputed
    **before** any band gate is evaluated."

    "`affected_acr_usd` is the sum of `acr_usd` over only those linked deals whose
    `attribution_status` is `RATIFIED`, each counted once, rounded to two decimal places"

    Design: Corner/consistency_model/triage_response_already_carries_the_rescored_impact_and_band
    """
    world.set_clock(CLOCK)
    world.active_program()
    competitor = world.create_competitor()
    world.create_two_analysts()
    root = world.create_reason("PRICE", "Price")
    leaf = world.create_reason(
        "PRICE_DISCOUNT", "Discount depth", parent_reason_id=root["id"]
    )
    world.create_frame()
    world.seal_frame()
    first = _gap_verbatim_deal(
        world,
        crm_deal_ref="CRM-4001",
        email="buyer1@acme.test",
        acr_usd=300000.00,
        scheduled_start_at="2026-08-10T14:00:00.000Z",
        scheduled_end_at="2026-08-10T15:00:00.000Z",
        recorded_at="2026-08-10T14:10:00.000Z",
    )
    second = _gap_verbatim_deal(
        world,
        crm_deal_ref="CRM-4002",
        email="buyer2@acme.test",
        acr_usd=200000.00,
        scheduled_start_at="2026-08-11T09:00:00.000Z",
        scheduled_end_at="2026-08-11T10:00:00.000Z",
        recorded_at="2026-08-11T09:10:00.000Z",
    )
    world.set_clock("2026-08-11T11:00:00.000Z")
    for record, start, end in (
        (first, "2026-08-10T14:00:00.000Z", "2026-08-10T14:45:00.000Z"),
        (second, "2026-08-11T09:00:00.000Z", "2026-08-11T09:45:00.000Z"),
    ):
        world.complete_interview(
            interview_id=record["interview"]["id"],
            actual_start_at=start,
            actual_end_at=end,
        )
        attribution = world.create_attribution(leaf["id"], deal_id=record["deal"]["id"])
        world.ratify_attribution(attribution["id"])
    gap = world.create_gap(first["gap_response"]["id"])

    triaged = validate_success(
        world.api.triage_product_gap(
            gap["id"],
            f.triage_payload(
                "ACCEPT", additional_response_ids=[second["gap_response"]["id"]]
            ),
            world.product,
        ),
        200,
    )

    assert_fields(
        triaged,
        {
            "status": "ACCEPTED",
            "linked_deal_count": 2,
            "roadmap_priority_band": "P1",
            "derived_competitor_id": competitor["id"],
        },
    )
    assert_money(triaged["affected_acr_usd"], 500000.00, "affected_acr_usd")
    assert_money(triaged["impact_score"], 62.40, "impact_score")

    reread = world.get_gap(gap["id"])
    for field in (
        "impact_score",
        "roadmap_priority_band",
        "linked_deal_count",
        "affected_acr_usd",
    ):
        assert reread[field] == triaged[field], (
            f"{field} must read back exactly as the triage reported it: "
            f"{triaged[field]!r} vs {reread[field]!r}"
        )
    assert_field(world.get_reason(leaf["id"]), "ratified_attribution_count", 2)
    assert_field(
        world.get_competitor(competitor["id"]), "ratified_loss_count", 2
    )
