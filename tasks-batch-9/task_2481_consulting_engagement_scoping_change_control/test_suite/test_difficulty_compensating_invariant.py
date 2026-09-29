"""Undo paths that must restore the ledger they moved, and no more than that."""

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

REVERSAL_REASON = "Hours were booked to the wrong engagement"
RESCIND_NOTE = "Client withdrew the second-wave request"


def _reverse_the_second_week(api: ConsultingApiClient) -> fx.Scenario:
    """100.00 approved hours, then the 40.00-hour line reversed."""
    sc = fx.build_burned_engagement(api)
    first_id, second_id = sc.extras["time_entry_ids"]
    sc.extras["first_id"] = first_id
    sc.extras["reversed_row"] = get_success_data(
        api.reverse_time_entry(
            second_id, {"reversal_reason": REVERSAL_REASON}, sc.manager
        )
    )
    return sc


def test_reversal_restores_the_exact_pre_approval_ledger(
    api: ConsultingApiClient,
) -> None:
    """Three counters fall back to the values the approval found them at.

    PRD 3.7: "The compensation is precise rather than approximate: the line's
    `hours` are subtracted from `approved_hours_burned`, its `cost_cents` are
    subtracted from `burned_cost_cents`, and its `hours` are subtracted from the
    deliverable's `hours_consumed`, restoring the exact pre-approval ledger
    values."

    Design: Difficulty/compensating_invariant/time_entry_reversal_restores_burn_ledger
    """
    sc = _reverse_the_second_week(api)

    engagement = fx.read_engagement(sc)
    assert_two_dp(engagement, "approved_hours_burned", 60.00)
    assert_money(engagement, "burned_cost_cents", 3720000)
    assert_two_dp(fx.read_deliverable(sc, sc.d1_id), "hours_consumed", 60.00)

    view = get_success_data(api.get_economics(sc.engagement_id, sc.partner))
    assert_economics_view(
        view,
        hours_burn_pct=29.89,
        completion_pct=40.00,
        progress_variance_pct=-10.11,
        projected_cost_cents=8505500,
        projected_margin_pct=17.26,
        # Back above both bands, so the reversal moved economics too
        economics_state=C.ECONOMICS_ON_TRACK,
    )
    # No overrun was ever entered, so nothing was escalated either
    assert fx.list_escalations(sc) == []


def test_the_reversed_line_keeps_its_own_figures_and_leaves_siblings_alone(
    api: ConsultingApiClient,
) -> None:
    """The contribution is withdrawn from the ledger, not erased from the line.

    PRD 3.7: "A reversal removes the line's contribution outright; it does not
    post a compensating negative row."

    Design: Difficulty/compensating_invariant/time_entry_reversal_restores_burn_ledger
    """
    sc = _reverse_the_second_week(api)

    row = sc.extras["reversed_row"]
    assert_fields(row, status=C.TIME_ENTRY_REVERSED, reversal_reason=REVERSAL_REASON)
    # 40.00 partner hours still priced at cost 62000 and billed 92500 less 0.05
    assert_money(row, "cost_cents", 2480000)
    assert_money(row, "billed_value_cents", 3515000)
    assert_two_dp(row, "hours", 40.00)

    survivor = fx.read_time_entry(sc, sc.extras["first_id"])
    assert_fields(survivor, status=C.TIME_ENTRY_APPROVED)
    assert_money(survivor, "cost_cents", 3720000)


def _rescind_the_approved_change(api: ConsultingApiClient) -> fx.Scenario:
    """A fully approved 160.00-hour change, withdrawn by firm leadership."""
    sc = fx.build_pending_client_change(api)
    change_request_id = sc.extras["change_request_id"]
    sc.extras["approved_row"] = fx.client_approve_change(sc, change_request_id)
    sc.extras["rescinded_row"] = get_success_data(
        api.rescind_change_request(
            change_request_id, {"note": RESCIND_NOTE}, sc.leadership
        )
    )
    return sc


def test_rescission_recomputes_the_contract_back_to_the_signed_terms(
    api: ConsultingApiClient,
) -> None:
    """With no surviving approved sibling the contract returns to its origin.

    PRD 3.8: "Once the row has left `APPROVED`, the engagement's
    `contracted_fee_cents` is recomputed as `original_fee_cents` plus the sum of
    `fee_delta_cents` across the engagement's change requests that remain
    `APPROVED`; `contracted_hours` and `planned_end_date` are recomputed the
    same way from the surviving requests' `added_hours` and
    `requested_schedule_days` respectively, and `schedule_relief_days` follows
    from the same surviving set; and `cumulative_change_pct` is recomputed from
    the surviving approved set alone."

    Design: Difficulty/compensating_invariant/change_request_rescind_restores_contracted_terms
    """
    sc = _rescind_the_approved_change(api)

    rescinded = sc.extras["rescinded_row"]
    assert_fields(rescinded, status=C.CR_RESCINDED)
    assert rescinded["rescinded_at"].startswith("2026-09-14T09:00:00")
    # The history of the withdrawn request survives the withdrawal
    assert_money(rescinded, "fee_delta_cents", 3921600)
    assert rescinded["approved_at"] is not None

    engagement = fx.read_engagement(sc)
    assert_money(engagement, "contracted_fee_cents", C.CANON_FIXED_FEE_QUOTED_CENTS)
    assert_money(engagement, "original_fee_cents", C.CANON_FIXED_FEE_QUOTED_CENTS)
    assert_two_dp(engagement, "contracted_hours", C.CANON_TOTAL_ESTIMATED_HOURS)
    assert_two_dp(engagement, "cumulative_change_pct", 0.00)
    assert_fields(
        engagement,
        schedule_relief_days=0,
        planned_end_date=C.SEED_TARGET_END_DATE,
    )


def test_rescission_moves_economics_back_but_leaves_the_escalation_open(
    api: ConsultingApiClient,
) -> None:
    """The forecast is restored; the escalation the overrun raised is not undone.

    PRD 3.8: "`rescinded_at` is stamped from the logical clock, the economics
    forecast is recomputed — which may move `economics_state` in either
    direction — and the engagement's `version` advances by 1 alongside the
    request's."

    Design: Difficulty/compensating_invariant/change_request_rescind_restores_contracted_terms
    """
    sc = _rescind_the_approved_change(api)

    view = get_success_data(api.get_economics(sc.engagement_id, sc.partner))
    assert_economics_view(
        view,
        hours_burn_pct=49.81,
        completion_pct=40.00,
        progress_variance_pct=9.81,
        projected_cost_cents=9625500,
        projected_margin_pct=6.37,
        # Off OVERRUN, but the thin margin still keeps it out of ON_TRACK
        economics_state=C.ECONOMICS_AT_RISK,
    )

    escalation = fx.first_escalation(sc)
    assert_fields(escalation, status=C.ESCALATION_OPEN, resolved_at=None)
    assert_fields(fx.read_engagement(sc), leadership_review_required=True)
    assert_fields(fx.read_client(sc), at_risk_engagement_count=1)
