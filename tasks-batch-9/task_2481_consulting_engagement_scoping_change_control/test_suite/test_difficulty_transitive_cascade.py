"""One write, several hops: contracted terms, escalations and client counters."""

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

FAILURE_NOTE = "Cost-to-serve model is not reconcilable to the client ledger"


def test_client_approval_moves_all_five_contracted_figures_together(
    api: ConsultingApiClient,
) -> None:
    """The client's single APPROVE rewrites the whole contract envelope.

    PRD 3.8: "Then five contracted figures move on the engagement in one step:
    `fee_delta_cents` is added to `contracted_fee_cents`, `added_hours` is added
    to `contracted_hours`, `requested_schedule_days` is added to
    `schedule_relief_days`, `planned_end_date` is pushed out by that same number
    of calendar days, and `cumulative_change_pct` is overwritten with the
    request's frozen `cumulative_change_pct_at_assessment`; the engagement's
    `version` advances."

    Design: Difficulty/transitive_cascade/change_request_approval_cascade_to_client_risk_counter
    """
    sc = fx.build_pending_client_change(api)
    change_request_id = sc.extras["change_request_id"]

    approved = fx.client_approve_change(sc, change_request_id)

    assert_fields(approved, status=C.CR_APPROVED)
    assert approved["approved_at"].startswith("2026-09-14T09:00:00")
    # 160.00 ANALYST hours at 21500 with the pinned 0.05 discount, loaded 1.20
    assert_money(approved, "gross_delta_cents", 3268000)
    assert_money(approved, "fee_delta_cents", 3921600)

    engagement = fx.read_engagement(sc)
    assert_money(engagement, "contracted_fee_cents", 14201978)
    assert_two_dp(engagement, "contracted_hours", 360.75)
    assert_two_dp(engagement, "cumulative_change_pct", 38.15)
    assert_fields(
        engagement,
        schedule_relief_days=30,
        planned_end_date="2027-01-17",
    )
    # The signed price is the immovable denominator of materiality
    assert_money(engagement, "original_fee_cents", C.CANON_FIXED_FEE_QUOTED_CENTS)


def test_client_approval_reaches_through_economics_to_the_client_counter(
    api: ConsultingApiClient,
) -> None:
    """Approve -> recompute -> OVERRUN -> escalation -> leadership -> client.

    PRD 3.8: "The economics forecast is then recomputed against the new
    `contracted_fee_cents` and `contracted_hours`, and if that recompute lands
    on `OVERRUN` from a non-overrun state, the full escalation cascade of §3.7
    follows — an `ECONOMICS` escalation at `HIGH` severity,
    `leadership_review_required` written true, and the client's
    `at_risk_engagement_count` incremented."

    Design: Difficulty/transitive_cascade/change_request_approval_cascade_to_client_risk_counter
    """
    sc = fx.build_pending_client_change(api)
    assert fx.list_escalations(sc) == []

    fx.client_approve_change(sc, sc.extras["change_request_id"])

    view = get_success_data(api.get_economics(sc.engagement_id, sc.partner))
    assert_economics_view(
        view,
        hours_burn_pct=27.72,
        completion_pct=40.00,
        progress_variance_pct=-12.28,
        projected_cost_cents=15065500,
        # The enlarged forecast overtakes the enlarged fee
        projected_margin_pct=-6.08,
        economics_state=C.ECONOMICS_OVERRUN,
    )

    rows = fx.list_escalations(sc)
    assert len(rows) == 1, f"expected exactly one escalation, got {len(rows)}"
    assert_fields(
        rows[0],
        source=C.ESCALATION_SOURCE_ECONOMICS,
        severity=C.SEVERITY_HIGH,
        status=C.ESCALATION_OPEN,
        source_quality_review_id=None,
    )
    assert_fields(
        fx.read_engagement(sc),
        leadership_review_required=True,
        # Only the money moved: delivery is untouched by change approval
        delivery_state=C.DELIVERY_ACTIVE,
    )
    assert_fields(fx.read_client(sc), at_risk_engagement_count=1)
    assert_fields(fx.read_deliverable(sc, sc.d2_id), status=C.DELIVERABLE_PLANNED)


def _fail_a_critical_checkpoint(api: ConsultingApiClient) -> fx.Scenario:
    """Delivery under way, then a CRITICAL midpoint failure inside the window."""
    sc = fx.build_active_engagement(api)
    fx.start_deliverable(sc, sc.d1_id, lead_id=sc.consultant_id)
    review = fx.schedule_review(sc)
    sc.extras["review_id"] = review["id"]
    fx.set_clock(api, C.SEED_REVIEW_CLOCK)
    sc.extras["failed_review"] = get_success_data(
        api.record_outcome(
            sc.extras["review_id"],
            {
                "outcome": C.REVIEW_FAILED,
                "findings_severity": C.SEVERITY_CRITICAL,
                "note": FAILURE_NOTE,
            },
            sc.reviewer,
        )
    )
    return sc


def test_critical_failure_holds_delivery_and_suspends_every_open_deliverable(
    api: ConsultingApiClient,
) -> None:
    """One recorded outcome reaches the engagement and both deliverables.

    PRD 3.9: "Second, the severity decides where that escalation starts: at
    `HIGH` it is created in `OPEN`, but at `CRITICAL` it is created directly in
    `DELIVERY_HELD`, which itself drives the engagement `ACTIVE → ON_HOLD` and
    triggers the deliverable suspension chain described in §3.6 along with the
    recomputation of `suspended_deliverable_count`."

    PRD 3.6: "Any deliverable of the engagement's pursuit sitting in `PLANNED`,
    `IN_PROGRESS` or `REWORK` is written to `SUSPENDED`, and the status it held
    immediately before is recorded in `prior_status`; each suspended row's
    `version` advances."

    Design: Difficulty/transitive_cascade/critical_quality_failure_suspends_open_deliverables
    """
    sc = _fail_a_critical_checkpoint(api)

    assert_fields(
        sc.extras["failed_review"],
        status=C.REVIEW_FAILED,
        findings_severity=C.SEVERITY_CRITICAL,
        note=FAILURE_NOTE,
    )

    escalation = fx.first_escalation(sc)
    assert_fields(
        escalation,
        source=C.ESCALATION_SOURCE_QUALITY,
        severity=C.SEVERITY_CRITICAL,
        status=C.ESCALATION_DELIVERY_HELD,
        source_quality_review_id=sc.extras["review_id"],
    )

    assert_fields(
        fx.read_engagement(sc),
        delivery_state=C.DELIVERY_ON_HOLD,
        suspended_deliverable_count=2,
    )
    # Each deliverable remembers the different status it was taken from
    assert_fields(
        fx.read_deliverable(sc, sc.d1_id),
        status=C.DELIVERABLE_SUSPENDED,
        prior_status=C.DELIVERABLE_IN_PROGRESS,
    )
    assert_fields(
        fx.read_deliverable(sc, sc.d2_id),
        status=C.DELIVERABLE_SUSPENDED,
        prior_status=C.DELIVERABLE_PLANNED,
    )


def test_critical_failure_flags_leadership_and_the_client_but_not_economics(
    api: ConsultingApiClient,
) -> None:
    """The quality cascade stops at the money: economics is left alone.

    PRD 3.9: "Third, the engagement's `leadership_review_required` is written
    true and the client's `at_risk_engagement_count` is incremented by 1 — with
    the client's `version` advancing — whenever the engagement's count of
    unresolved escalations at severity `HIGH` or above moves from zero to one."

    Design: Difficulty/transitive_cascade/critical_quality_failure_suspends_open_deliverables
    """
    sc = _fail_a_critical_checkpoint(api)

    engagement = fx.read_engagement(sc)
    assert_fields(
        engagement,
        leadership_review_required=True,
        economics_state=C.ECONOMICS_ON_TRACK,
    )
    assert_two_dp(engagement, "approved_hours_burned", 0.00)
    assert_money(engagement, "burned_cost_cents", 0)

    # DELIVERY_HELD counts as unresolved, so the client's risk counter moves
    assert_fields(fx.read_client(sc), at_risk_engagement_count=1)
