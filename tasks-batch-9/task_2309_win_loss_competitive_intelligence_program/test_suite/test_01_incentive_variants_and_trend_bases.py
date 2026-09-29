"""
Two-variant computations: the interview incentive and the loss-reason trend read.

One formula produces both of an interview's money fields, and one report produces
two different sets of shares depending on which attribution statuses participate.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_analyst_workload,
    assert_deal_dimensions,
    assert_field,
    assert_ledger,
    assert_money,
    assert_ratio,
    assert_trend_row,
)
from test_helpers.fixtures import WinLossWorld


# ---------------------------------------------------------------------------
# Setups
# ---------------------------------------------------------------------------


def _interview_ready_for_short_completion(world: WinLossWorld) -> WinLossWorld:
    """A 60-minute booked interview whose three guide topics are all answered.

    The clock is left at 2026-08-10T15:30:00.000Z so the booked interval is in the
    past and the completion instants below are admissible.
    """
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
        verbatim_text="Ranked on integration depth.",
        recorded_at="2026-08-10T14:10:00.000Z",
        rating=4,
    )
    world.record_response(
        question_key="COMPETITOR_POSITIONING",
        verbatim_text="Northwind pitched a bundled suite.",
        recorded_at="2026-08-10T14:15:00.000Z",
        rating=4,
    )
    world.record_response(
        question_key="PRICING_PERCEPTION",
        verbatim_text="List price felt 20 percent high.",
        recorded_at="2026-08-10T14:20:00.000Z",
        rating=2,
    )
    world.set_clock("2026-08-10T15:30:00.000Z")
    return world


def _two_attributions_one_ratified(world: WinLossWorld) -> WinLossWorld:
    """Two interviewed ENTERPRISE losses: one RATIFIED on PRICE, one PROVISIONAL.

    Both deals close inside the reporting window and both carry a single-reason
    attribution at weight 1.00, so the only thing separating the two bases is the
    status of the second attribution.
    """
    world.set_clock("2026-08-01T00:00:00.000Z")
    world.active_program()
    world.create_competitor()
    world.create_reason("PRICE", "Price")
    world.create_reason("FEATURE_GAP", "Feature gap")
    world.create_two_analysts()
    deal_one = world.create_deal(primary_competitor_id=world.competitor["id"])
    deal_two = world.create_deal(
        crm_deal_ref="CRM-1002",
        acr_usd=260000.00,
        close_date="2026-06-20T00:00:00.000Z",
        sales_rep_user_ref="rep-78",
        primary_competitor_id=world.competitor["id"],
    )
    contact_one = world.consented_contact(deal_id=deal_one["id"])
    contact_two = world.consented_contact(
        deal_id=deal_two["id"], email="buyer2@brava.test", full_name="Cal Dos"
    )
    world.create_frame()
    world.seal_frame()
    world.draw("LOST", requested_count=2)
    interview_one = world.schedule_interview(
        deal_id=deal_one["id"], buyer_contact_id=contact_one["id"]
    )
    interview_two = world.schedule_interview(
        deal_id=deal_two["id"],
        buyer_contact_id=contact_two["id"],
        scheduled_start_at="2026-08-11T14:00:00.000Z",
        scheduled_end_at="2026-08-11T15:00:00.000Z",
    )
    world.cover_guide(interview_id=interview_one["id"], recorded_at="2026-08-10T14:10:00.000Z")
    world.cover_guide(interview_id=interview_two["id"], recorded_at="2026-08-11T14:10:00.000Z")
    world.set_clock("2026-08-12T00:00:00.000Z")
    world.complete_interview(
        interview_id=interview_one["id"],
        actual_start_at="2026-08-10T14:00:00.000Z",
        actual_end_at="2026-08-10T15:00:00.000Z",
    )
    world.complete_interview(
        interview_id=interview_two["id"],
        actual_start_at="2026-08-11T14:00:00.000Z",
        actual_end_at="2026-08-11T15:00:00.000Z",
    )
    world.attribution = world.create_attribution(
        world.reasons["PRICE"]["id"], deal_id=deal_one["id"]
    )
    world.ratify_attribution(analyst=world.analyst2)
    world.second_attribution = world.create_attribution(
        world.reasons["FEATURE_GAP"]["id"], deal_id=deal_two["id"]
    )
    return world


# ---------------------------------------------------------------------------
# incentive: provisional versus final
# ---------------------------------------------------------------------------


def test_provisional_and_final_incentive_diverge_on_a_short_actual_interval(world):
    """A 60-minute booking pays only the 30-minute actual amount.

    "The **provisional** variant measures `scheduled_end_at` minus
    `scheduled_start_at`, stores its output in `incentive_provisional_usd`, and
    adds that amount to the program's `incentive_committed_usd`. The **final**
    variant measures `actual_end_at` minus `actual_start_at`, stores its output in
    `incentive_final_usd`, removes the provisional amount from
    `incentive_committed_usd` and adds the final amount to `incentive_paid_usd`."

    Design: Difficulty/dual_variant_calc/incentive_provisional_vs_final_diverge_on_short_interview
    """
    _interview_ready_for_short_completion(world)
    interview_id = world.interview["id"]
    assert_money(world.interview["incentive_provisional_usd"], 250.00, "provisional")

    body = validate_success(
        world.api.complete_interview(
            interview_id,
            f.complete_interview_payload("2026-08-10T14:05:00.000Z", "2026-08-10T14:35:00.000Z"),
            world.analyst_headers,
        ),
        200,
    )
    completed = body

    assert_money(completed["incentive_provisional_usd"], 250.00, "provisional")
    assert_money(completed["incentive_final_usd"], 150.00, "final")
    assert completed["incentive_provisional_usd"] != completed["incentive_final_usd"], (
        "the two variants must not collapse to one amount"
    )
    assert_field(completed, "incentive_status", "PAID")


def test_completion_moves_the_provisional_out_and_only_the_final_in(world):
    """The program ledger drops 250.00 from committed and adds 150.00 to paid.

    "The second link, caused by that incentive-status change, decreases the
    program's `incentive_committed_usd` by the provisional amount, increases its
    `incentive_paid_usd` by the final amount, and increments the program's
    `version`."

    Design: Difficulty/dual_variant_calc/incentive_provisional_vs_final_diverge_on_short_interview
    """
    _interview_ready_for_short_completion(world)
    before = world.refresh_program()
    assert_ledger(before, 250.00, 0.00, "OPEN")

    validate_success(
        world.api.complete_interview(
            world.interview["id"],
            f.complete_interview_payload("2026-08-10T14:05:00.000Z", "2026-08-10T14:35:00.000Z"),
            world.analyst_headers,
        ),
        200,
    )

    after = world.refresh_program()
    assert_ledger(after, 0.00, 150.00, "OPEN")


def test_short_completion_still_advances_the_deal_contact_and_analyst_counters(world):
    """The divergent amount does not disturb the non-monetary completion effects.

    "Alongside the cascade, the buyer contact's `completed_interview_count`
    increases by one and its `last_completed_interview_end_at` is set to
    `actual_end_at`; the deal advances `SELECTED → INTERVIEWED` with its
    `interview_coverage_count` increased by one, which is the count of that deal's
    `COMPLETED` interviews; and the analyst's `open_interview_count` decreases by
    one while its `committed_minutes` decreases by the scheduled duration plus
    fifteen."

    Design: Difficulty/dual_variant_calc/incentive_provisional_vs_final_diverge_on_short_interview
    """
    _interview_ready_for_short_completion(world)

    validate_success(
        world.api.complete_interview(
            world.interview["id"],
            f.complete_interview_payload("2026-08-10T14:05:00.000Z", "2026-08-10T14:35:00.000Z"),
            world.analyst_headers,
        ),
        200,
    )

    assert_deal_dimensions(
        world.get_deal(), research_status="INTERVIEWED", interview_coverage_count=1
    )
    contact = world.get_contact()
    assert_field(contact, "completed_interview_count", 1)
    assert contact["last_completed_interview_end_at"] == "2026-08-10T14:35:00.000Z", (
        "the contact must record the actual end instant"
    )
    assert_analyst_workload(world.get_analyst(), 0, 0)


# ---------------------------------------------------------------------------
# loss trends: the two bases
# ---------------------------------------------------------------------------


def test_ratified_only_basis_reports_a_single_reason_at_a_full_share(world):
    """The default basis sees only the ratified attribution.

    "under a `basis` of `RATIFIED_ONLY`, which is the default, only attributions
    whose `status` is `RATIFIED` participate"

    Design: Difficulty/dual_variant_calc/loss_trend_shares_diverge_between_ratified_only_and_include_provisional
    """
    _two_attributions_one_ratified(world)

    trends = world.loss_trends(basis="RATIFIED_ONLY")

    assert_field(trends, "attribution_count", 1)
    assert len(trends["segments"]) == 1, (
        f"expected only ENTERPRISE, got {[s['segment'] for s in trends['segments']]}"
    )
    segment = trends["segments"][0]
    assert_field(segment, "segment", "ENTERPRISE")
    assert_money(segment["segment_total"], 1.00, "segment_total")
    assert len(segment["rows"]) == 1, f"expected one row, got {segment['rows']}"
    assert_trend_row(segment["rows"][0], "PRICE", 1.00, 1.0000)


def test_include_provisional_basis_halves_every_share_by_changing_the_denominator(world):
    """Admitting the provisional attribution rewrites the whole report.

    "under a `basis` of `INCLUDE_PROVISIONAL`, attributions in `PROVISIONAL` join
    them, changing every denominator and therefore every share"

    Design: Difficulty/dual_variant_calc/loss_trend_shares_diverge_between_ratified_only_and_include_provisional
    """
    _two_attributions_one_ratified(world)

    trends = world.loss_trends(basis="INCLUDE_PROVISIONAL")

    assert_field(trends, "attribution_count", 2)
    assert len(trends["segments"]) == 1, (
        f"expected only ENTERPRISE, got {[s['segment'] for s in trends['segments']]}"
    )
    segment = trends["segments"][0]
    assert_field(segment, "segment", "ENTERPRISE")
    assert_money(segment["segment_total"], 2.00, "segment_total")
    rows = segment["rows"]
    assert len(rows) == 2, f"expected two rows, got {rows}"
    assert_trend_row(rows[0], "FEATURE_GAP", 1.00, 0.5000)
    assert_trend_row(rows[1], "PRICE", 1.00, 0.5000)


def test_the_two_attributions_hold_the_statuses_that_separate_the_bases(world):
    """Both attributions score the same confidence; only their statuses differ.

    "Its `confidence_score` is fixed at creation time as `weight_primary`
    multiplied by a coverage confidence factor, where that factor is forty
    hundredths plus twenty hundredths per completed interview on the deal as
    counted by `interview_coverage_count`, capped at 1.00; the product is rounded
    to two decimal places."

    Design: Difficulty/dual_variant_calc/loss_trend_shares_diverge_between_ratified_only_and_include_provisional
    """
    _two_attributions_one_ratified(world)

    ratified = world.get_attribution(world.attribution["id"])
    provisional = world.get_attribution(world.second_attribution["id"])

    assert_field(ratified, "status", "RATIFIED")
    assert_ratio(ratified["confidence_score"], 0.60, "confidence_score")
    assert_field(provisional, "status", "PROVISIONAL")
    assert_ratio(provisional["confidence_score"], 0.60, "confidence_score")
