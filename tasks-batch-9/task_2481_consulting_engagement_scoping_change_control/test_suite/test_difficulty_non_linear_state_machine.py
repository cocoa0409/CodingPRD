"""Backward edges and loops: states revisited, and revisits that are not inert."""

from typing import Tuple

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import ConsultingApiClient
from test_helpers import constants as C
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_economics_view,
    assert_fields,
    assert_money,
    assert_two_dp,
)

SECOND_EXCLUSION = "Change management and training"


def _drive_to_revision_requested(api: ConsultingApiClient) -> fx.Scenario:
    """A released document the client pushed back, re-scoped and re-baselined."""
    sc = fx.build_sow_client_review(api)
    get_success_data(
        api.sow_client_decision(
            sc.sow_id,
            {"decision": "REQUEST_REVISION", "note": "Please carve out change management"},
            sc.client_contact,
        )
    )
    # A second exclusion retires four more points of the specification component
    fx.edit_scope(sc, exclusions=list(C.SEED_EXCLUSIONS) + [SECOND_EXCLUSION])
    fx.baseline_scope(sc)
    return sc


def test_revise_returns_the_document_to_draft_and_counts_the_loop(
    api: ConsultingApiClient,
) -> None:
    """DRAFT is re-entered by a backward edge, and the round is counted.

    PRD 3.5: "On success `revision_round` increments by 1 and the entire
    pricing chain is re-run against the **new** baseline, overwriting
    `risk_score`, `risk_premium_pct`, `pinned_scope_discount_pct`, the
    document's `baseline_effort_cost_cents`, `quoted_fee_cents`,
    `fixed_component_cents`, `at_risk_component_cents` and
    `not_to_exceed_cents`."

    Design: Difficulty/non_linear_state_machine/sow_negotiation_cycle_revision_round_reprice
    """
    sc = _drive_to_revision_requested(api)

    revised = get_success_data(
        api.revise_sow(
            sc.sow_id, {"acceptance_summary": C.SEED_ACCEPTANCE_SUMMARY}, sc.partner
        )
    )

    assert_fields(revised, status="DRAFT", revision_round=1)
    pursuit = fx.read_opportunity(sc)
    # SCOPE_BASELINED -> SOW_ISSUED fired a second time on the same row
    assert_fields(pursuit, status="SOW_ISSUED")
    assert_two_dp(pursuit, "total_estimated_hours", C.CANON_TOTAL_ESTIMATED_HOURS)
    assert pursuit["baselined_at"].startswith("2026-08-03T09:00:00")


def test_revise_reprices_the_same_baseline_into_a_lower_tier(
    api: ConsultingApiClient,
) -> None:
    """The re-entered DRAFT carries a different price on identical effort.

    PRD 3.5: "The tier in turn fixes `risk_premium_pct` at exactly 0.05 for
    low, 0.12 for medium and 0.20 for high."

    Design: Difficulty/non_linear_state_machine/sow_negotiation_cycle_revision_round_reprice
    """
    sc = _drive_to_revision_requested(api)

    revised = get_success_data(
        api.revise_sow(
            sc.sow_id, {"acceptance_summary": C.SEED_ACCEPTANCE_SUMMARY}, sc.partner
        )
    )

    # 25 + 15 + 4 specification + 10 dependency + 3 obligation lands in medium
    assert_fields(revised, risk_score=57)
    assert_two_dp(revised, "risk_premium_pct", C.RISK_PREMIUM_MEDIUM)
    assert_money(revised, "quoted_fee_cents", 9595020)
    assert_money(revised, "fixed_component_cents", 9595020)
    # Identical baseline, different price: the re-price follows the narrative
    assert_money(
        revised, "baseline_effort_cost_cents", C.CANON_BASELINE_EFFORT_COST_CENTS
    )


def _drive_through_rework(api: ConsultingApiClient) -> Tuple[fx.Scenario, int]:
    """A deliverable already back at IN_PROGRESS after a client rework loop."""
    sc = fx.build_active_engagement(api)
    fx.start_deliverable(sc, sc.d1_id, lead_id=sc.consultant_id)
    fx.set_status(sc, sc.d1_id, C.DELIVERABLE_SUBMITTED)
    fx.set_status(sc, sc.d1_id, C.DELIVERABLE_REWORK, headers=sc.client_contact)
    restarted = fx.set_status(sc, sc.d1_id, C.DELIVERABLE_IN_PROGRESS)
    return sc, restarted["version"]


def test_second_submitted_visit_is_the_one_that_gets_accepted(
    api: ConsultingApiClient,
) -> None:
    """The loop is counted rather than collapsed: one version per transition.

    PRD 3.6: "A deliverable's lifecycle is `PLANNED`, `IN_PROGRESS`,
    `SUBMITTED`, and then either `ACCEPTED` — which is terminal — or `REWORK`
    and back to `IN_PROGRESS`."

    PRD 3.6: "Every one of these transitions advances the deliverable's
    `version` by 1."

    Design: Difficulty/non_linear_state_machine/deliverable_rework_cycle_returns_to_submitted
    """
    sc, version_before = _drive_through_rework(api)

    resubmitted = fx.set_status(sc, sc.d1_id, C.DELIVERABLE_SUBMITTED)
    assert_fields(resubmitted, status=C.DELIVERABLE_SUBMITTED)

    accepted = fx.set_status(
        sc, sc.d1_id, C.DELIVERABLE_ACCEPTED, headers=sc.client_contact
    )
    assert_fields(accepted, status=C.DELIVERABLE_ACCEPTED)
    assert accepted["version"] == version_before + 2


def test_acceptance_after_rework_credits_the_weight_exactly_once(
    api: ConsultingApiClient,
) -> None:
    """Two visits to SUBMITTED, one acceptance side effect.

    PRD 3.7: "The completion percentage, `completion_pct`, is the sum of
    `completion_weight_pct` across those deliverables of the engagement's
    pursuit whose status is `ACCEPTED`, rounded half up to two decimal places;
    deliverables at `SUBMITTED` or `REWORK` contribute nothing."

    Design: Difficulty/non_linear_state_machine/deliverable_rework_cycle_returns_to_submitted
    """
    sc, _ = _drive_through_rework(api)
    fx.set_status(sc, sc.d1_id, C.DELIVERABLE_SUBMITTED)
    fx.set_status(sc, sc.d1_id, C.DELIVERABLE_ACCEPTED, headers=sc.client_contact)

    view = get_success_data(api.get_economics(sc.engagement_id, sc.partner))

    assert_economics_view(
        view,
        completion_pct=40.00,
        hours_burn_pct=0.00,
        progress_variance_pct=-40.00,
        projected_cost_cents=6825500,
        projected_margin_pct=33.61,
        economics_state=C.ECONOMICS_ON_TRACK,
    )
    # The predecessor only just reached ACCEPTED, so its successor has not moved
    assert_fields(fx.read_deliverable(sc, sc.d2_id), status=C.DELIVERABLE_PLANNED)


def test_second_approval_walks_economics_to_overrun_while_delivery_holds_still(
    api: ConsultingApiClient,
) -> None:
    """Two dimensions on one row: economics moves, delivery does not.

    PRD 3.7: "The engagement is `OVERRUN` when `progress_variance_pct` is
    30.00 or greater, or when `projected_margin_pct` is below 0.00."

    Design: Difficulty/non_linear_state_machine/engagement_economics_state_moves_while_delivery_state_unchanged
    """
    sc = fx.build_started_engagement(api)
    fx.log_and_approve_time(sc, 60.0, C.SEED_WEEK_1)
    at_risk = fx.read_engagement(sc)
    assert_fields(at_risk, economics_state=C.ECONOMICS_AT_RISK)

    fx.log_and_approve_time(sc, 15.0, C.SEED_WEEK_2)

    engagement = fx.read_engagement(sc)
    assert_two_dp(engagement, "approved_hours_burned", 75.00)
    assert_money(engagement, "burned_cost_cents", 4650000)
    assert_fields(
        engagement,
        economics_state=C.ECONOMICS_OVERRUN,
        delivery_state=C.DELIVERY_ACTIVE,
        suspended_deliverable_count=0,
    )
    assert_fields(fx.read_deliverable(sc, sc.d1_id), status=C.DELIVERABLE_IN_PROGRESS)

    view = get_success_data(api.get_economics(sc.engagement_id, sc.partner))
    assert_economics_view(
        view,
        hours_burn_pct=37.36,
        completion_pct=0.00,
        progress_variance_pct=37.36,
        projected_cost_cents=8925500,
        projected_margin_pct=13.18,
        economics_state=C.ECONOMICS_OVERRUN,
    )


def test_only_the_overrun_entry_raises_a_risk_escalation(
    api: ConsultingApiClient,
) -> None:
    """The AT_RISK step raised nothing; the OVERRUN step raises exactly one.

    PRD 3.7: "Whenever a recompute lands on `OVERRUN` from a state that was not
    already `OVERRUN` — whether `ON_TRACK → OVERRUN` in a single step or
    `AT_RISK → OVERRUN` — the system raises exactly one risk escalation on the
    engagement with `source` set to `ECONOMICS`, `severity` set to `HIGH`,
    handling status `OPEN`, and an `opened_reason` naming the threshold that was
    breached."

    Design: Difficulty/non_linear_state_machine/engagement_economics_state_moves_while_delivery_state_unchanged
    """
    sc = fx.build_started_engagement(api)
    fx.log_and_approve_time(sc, 60.0, C.SEED_WEEK_1)
    assert fx.list_escalations(sc) == []

    fx.log_and_approve_time(sc, 15.0, C.SEED_WEEK_2)

    rows = fx.list_escalations(sc)
    assert len(rows) == 1, f"expected exactly one escalation, got {len(rows)}"
    assert_fields(
        rows[0],
        source=C.ESCALATION_SOURCE_ECONOMICS,
        severity=C.SEVERITY_HIGH,
        status=C.ESCALATION_OPEN,
        engagement_id=sc.engagement_id,
    )
    assert_fields(fx.read_engagement(sc), leadership_review_required=True)
    client = validate_success(api.get_client(sc.client_id, sc.partner))
    assert_fields(client, at_risk_engagement_count=1)
