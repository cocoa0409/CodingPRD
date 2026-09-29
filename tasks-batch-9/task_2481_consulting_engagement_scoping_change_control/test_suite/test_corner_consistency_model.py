"""Immediate consistency: every cascade has landed before the response returns."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import ConsultingApiClient
from test_helpers import constants as C
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_economics_view,
    assert_fields,
    assert_money,
    assert_two_dp,
)


def test_one_approval_reconciles_the_ledger_the_rollup_and_the_forecast(
    api: ConsultingApiClient,
) -> None:
    """Three rows and one computed view, all settled by the decision response.

    PRD 2.9: "The rule is that cascades run to completion within the same
    request, synchronously, before the response is emitted, and every row a
    cascade touches has its `updated_at` refreshed and its `version` incremented
    by 1."

    PRD 2.9: "There is no eventual consistency and no deferred recomputation: a
    read immediately following a write observes every consequence of that write."

    PRD 3.7: "Approval moves the line `SUBMITTED → APPROVED` and synchronises the
    ledger in three places at once: the line's `hours` are added to the
    engagement's `approved_hours_burned`, the line's `cost_cents` are added to
    the engagement's `burned_cost_cents`, and the line's `hours` are also added
    to the deliverable's `hours_consumed`."

    Design: Corner/consistency_model/every_cascade_is_visible_in_the_same_response
    """
    sc = fx.build_burned_engagement(api, hours=[60.0])
    second_line = fx.log_time(sc, 40.0, C.SEED_WEEK_2)

    decision = fx.approve_time(sc, second_line["id"])

    # The trigger response already carries the new status and the line's costing
    assert_fields(decision, status=C.TIME_ENTRY_APPROVED)
    assert_money(decision, "cost_cents", 2480000)

    engagement = fx.read_engagement(sc)
    assert_two_dp(engagement, "approved_hours_burned", 100.00)
    assert_money(engagement, "burned_cost_cents", 6200000)
    assert_fields(engagement, economics_state=C.ECONOMICS_AT_RISK)

    assert_two_dp(fx.read_deliverable(sc, sc.d1_id), "hours_consumed", 100.00)

    first_view = get_success_data(api.get_economics(sc.engagement_id, sc.partner))
    second_view = get_success_data(api.get_economics(sc.engagement_id, sc.manager))

    # Re-reading converges on nothing new: there is no window to re-poll
    for view in (first_view, second_view):
        assert_economics_view(
            view,
            hours_burn_pct=49.81,
            completion_pct=40.00,
            progress_variance_pct=9.81,
            projected_cost_cents=9625500,
            projected_margin_pct=6.37,
            economics_state=C.ECONOMICS_AT_RISK,
        )
    assert first_view == second_view


def test_a_failed_checkpoint_settles_the_counter_one_aggregate_away(
    api: ConsultingApiClient,
) -> None:
    """The escalation, the engagement flag and the client counter all land at once.

    PRD 3.9: "A failed checkpoint moves `SCHEDULED → FAILED` and starts a
    three-hop cascade."

    PRD 3.9: "Third, the engagement's `leadership_review_required` is written
    true and the client's `at_risk_engagement_count` is incremented by 1 — with
    the client's `version` advancing — whenever the engagement's count of
    unresolved escalations at severity `HIGH` or above moves from zero to one."

    PRD 2.9: "There is no eventual consistency and no deferred recomputation: a
    read immediately following a write observes every consequence of that write."

    Design: Corner/consistency_model/cross_aggregate_counters_settle_before_the_response_returns
    """
    sc = fx.build_active_engagement(api)
    review = fx.schedule_review(sc)
    assert_fields(fx.read_engagement(sc), leadership_review_required=False)
    assert_fields(fx.read_client(sc), at_risk_engagement_count=0)
    fx.set_clock(api, C.SEED_REVIEW_CLOCK)

    recorded = fx.record_review_outcome(
        sc, review["id"], C.REVIEW_FAILED, C.SEVERITY_HIGH
    )

    assert_fields(
        recorded, status=C.REVIEW_FAILED, findings_severity=C.SEVERITY_HIGH
    )

    escalations = fx.list_escalations(sc)
    assert len(escalations) == 1
    assert_fields(
        escalations[0],
        source=C.ESCALATION_SOURCE_QUALITY,
        severity=C.SEVERITY_HIGH,
        status=C.ESCALATION_OPEN,
        source_quality_review_id=review["id"],
    )

    assert_fields(
        fx.read_engagement(sc),
        leadership_review_required=True,
        # HIGH opens in OPEN, so no hold was placed
        delivery_state=C.DELIVERY_ACTIVE,
        suspended_deliverable_count=0,
    )

    partner_read = get_success_data(api.get_client(sc.client_id, sc.partner))
    admin_read = get_success_data(api.get_client(sc.client_id, sc.admin))

    for row in (partner_read, admin_read):
        assert_fields(row, at_risk_engagement_count=1, completed_engagement_count=0)
    assert partner_read["version"] == admin_read["version"]
