"""Two refusals earned at once, and the declared band order picking the winner."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import ConsultingApiClient
from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_fields, assert_money, assert_two_dp

# 167.76 ANALYST hours price to a cumulative 40.00 percent exactly, so the
# ceiling still admits them; the 10.00-hour request assessed afterwards would
# push the cumulative figure to 42.38 and breach it.
LARGE_CHANGE_HOURS = 167.76
SMALL_CHANGE_HOURS = 10.0
OTHER_PRACTICE_CODE = "RISK"


def _engagement_with_a_routed_small_change(api: ConsultingApiClient) -> fx.Scenario:
    """A pending small change, plus a large sibling already fully approved."""
    sc = fx.build_burned_engagement(api)

    small = fx.raise_change_request(
        sc,
        summary="Add one distribution-centre sensitivity run",
        added_hours=SMALL_CHANGE_HOURS,
        requested_schedule_days=0,
    )
    sc.extras["small_id"] = small["id"]
    sc.extras["small_assessed"] = fx.assess_change_request(sc, small["id"])

    large = fx.raise_change_request(
        sc,
        summary="Model two additional distribution-centre scenarios in full",
        added_hours=LARGE_CHANGE_HOURS,
    )
    fx.assess_change_request(sc, large["id"])
    fx.leadership_approve_change(sc, large["id"])
    fx.client_approve_change(sc, large["id"])
    sc.extras["large_id"] = large["id"]
    return sc


def test_change_request_state_refusal_outranks_the_materiality_ceiling(
    api: ConsultingApiClient,
) -> None:
    """Re-assessing a routed request earns both refusals; state is reported.

    PRD 2.10: "State checks then run in three steps: the target row's own state
    per its transition table, then the governing parent row's state, then the
    scope-frozen check (`ERR_SCOPE_FROZEN`)."

    PRD 2.10: "Fiscal rules are evaluated last, in this order: budget
    verification (`ERR_BUDGET_NOT_VERIFIED`), timesheet hour bounds
    (`ERR_TIMESHEET_HOURS_OUT_OF_RANGE`), change materiality
    (`ERR_CHANGE_EXCEEDS_MATERIALITY`), the not-to-exceed ceiling
    (`ERR_NOT_TO_EXCEED_BREACHED`) and follow-on eligibility
    (`ERR_FOLLOW_ON_NOT_ELIGIBLE`)."

    Design: Difficulty/priority_pair_validation_conflict/assess_impact_state_error_precedes_materiality_error
    """
    sc = _engagement_with_a_routed_small_change(api)

    response = api.assess_impact(sc.extras["small_id"], {}, sc.manager)

    validate_error(response, E.ERR_CHANGE_REQUEST_STATE_INVALID)

    # The approved sibling alone moved the contract, confirming the materiality
    # denominator that the refused re-assessment would have breached
    engagement = fx.read_engagement(sc)
    assert_money(engagement, "contracted_fee_cents", 14392176)
    assert_two_dp(engagement, "contracted_hours", 368.51)
    assert_two_dp(engagement, "cumulative_change_pct", 40.00)


def test_the_refused_reassessment_leaves_the_frozen_figures_untouched(
    api: ConsultingApiClient,
) -> None:
    """The losing rule never runs, so nothing on the request is rewritten.

    PRD 3.8: "In both branches the routed status arrives in the very same
    response that carries `gross_delta_cents`, `fee_delta_cents`,
    `cumulative_change_pct_at_assessment` and `routing`, so a request is never
    observed resting at `IMPACT_ASSESSED`."

    Design: Difficulty/priority_pair_validation_conflict/assess_impact_state_error_precedes_materiality_error
    """
    sc = _engagement_with_a_routed_small_change(api)
    assessed = sc.extras["small_assessed"]
    # 10.00 ANALYST hours at 21500 less the pinned 0.05, loaded by 1.20
    assert_money(assessed, "gross_delta_cents", 204250)
    assert_money(assessed, "fee_delta_cents", 245100)
    assert_two_dp(assessed, "cumulative_change_pct_at_assessment", 2.38)
    assert_fields(
        assessed,
        routing=C.ROUTING_CLIENT_ONLY,
        status=C.CR_PENDING_CLIENT_APPROVAL,
    )

    validate_error(
        api.assess_impact(sc.extras["small_id"], {}, sc.manager),
        E.ERR_CHANGE_REQUEST_STATE_INVALID,
    )

    unchanged = fx.read_change_request(sc, sc.extras["small_id"])
    # Figures frozen at the first assessment, not re-derived against 42.38
    assert_money(unchanged, "gross_delta_cents", 204250)
    assert_money(unchanged, "fee_delta_cents", 245100)
    assert_two_dp(unchanged, "cumulative_change_pct_at_assessment", 2.38)
    assert_fields(
        unchanged,
        routing=C.ROUTING_CLIENT_ONLY,
        status=C.CR_PENDING_CLIENT_APPROVAL,
        version=assessed["version"],
    )


def _consultant_leading_two_overlapping_deliverables(
    api: ConsultingApiClient,
) -> fx.Scenario:
    """An out-of-practice consultant already at the capacity limit."""
    sc = fx.build_scoped_pursuit(api)
    outsider_id = fx.create_consultant(
        api,
        name="F. Duarte",
        grade=C.GRADE_CONSULTANT,
        practice_code=OTHER_PRACTICE_CODE,
        cost_rate_cents_per_hour=C.SEED_CONSULTANT_COST_RATE,
    )["id"]
    sc.extras["outsider_id"] = outsider_id

    sibling = fx.build_sibling_pursuit(
        sc,
        practice_code=OTHER_PRACTICE_CODE,
        objective_summary="Working-capital diagnostic",
        deliverables=[
            dict(
                C.SEED_D1,
                name="Payables baseline",
                planned_start_date="2026-09-01",
                planned_end_date="2026-10-15",
            ),
            dict(
                C.SEED_D2,
                name="Receivables baseline",
                planned_start_date="2026-09-15",
                planned_end_date="2026-10-31",
            ),
        ],
    )
    for deliverable_id in sibling.deliverable_ids:
        fx.assign_lead(sibling, deliverable_id, outsider_id)
    sc.extras["sibling"] = sibling
    return sc


def test_practice_mismatch_outranks_the_capacity_conflict(
    api: ConsultingApiClient,
) -> None:
    """The candidate fails both gates; the referential band reports first.

    PRD 2.10: "Business referential rules follow in order: practice match
    (`ERR_CONSULTANT_PRACTICE_MISMATCH`), reviewer certification
    (`ERR_REVIEWER_NOT_CERTIFIED`), cross-engagement scope of a referenced row
    (`ERR_DELIVERABLE_NOT_IN_ENGAGEMENT_SCOPE`), dependency cycles
    (`ERR_DEPENDENCY_CYCLE`), predecessor acceptance
    (`ERR_DEPENDENCY_NOT_ACCEPTED`), then lead assignment
    (`ERR_DELIVERABLE_LEAD_UNASSIGNED`)."

    PRD 2.10: "Temporal rules follow, in this order: lead capacity overlap
    (`ERR_CONSULTANT_CAPACITY_CONFLICT`), review window spacing
    (`ERR_REVIEW_WINDOW_CONFLICT`), review window openness
    (`ERR_REVIEW_WINDOW_NOT_OPEN`), the timesheet week falling inside the
    engagement window (`ERR_TIME_ENTRY_OUTSIDE_ENGAGEMENT_WINDOW`), the
    timesheet week not being in the future (`ERR_FUTURE_TIMESHEET_LINE`), the
    opportunity target start date not being in the past
    (`ERR_TARGET_DATE_IN_PAST`) and clock rewind
    (`ERR_CLOCK_REWIND_FORBIDDEN`)."

    Design: Difficulty/priority_pair_validation_conflict/assign_lead_practice_mismatch_precedes_capacity_conflict
    """
    sc = _consultant_leading_two_overlapping_deliverables(api)
    before = fx.read_deliverable(sc, sc.d1_id)

    response = api.assign_lead(
        sc.d1_id, {"lead_consultant_id": sc.extras["outsider_id"]}, sc.manager
    )

    validate_error(response, E.ERR_CONSULTANT_PRACTICE_MISMATCH)
    after = fx.read_deliverable(sc, sc.d1_id)
    assert_fields(after, lead_consultant_id=None, version=before["version"])


def test_the_refused_assignment_leaves_the_capacity_count_alone(
    api: ConsultingApiClient,
) -> None:
    """A refusal on the first gate never reaches the counter the second reads.

    PRD 3.3: "A successful assignment writes `lead_consultant_id`, advances the
    deliverable's `version`, and increments the consultant's
    `active_lead_deliverable_count` while advancing that consultant's `version`
    too."

    Design: Difficulty/priority_pair_validation_conflict/assign_lead_practice_mismatch_precedes_capacity_conflict
    """
    sc = _consultant_leading_two_overlapping_deliverables(api)
    outsider_id = sc.extras["outsider_id"]

    validate_error(
        api.assign_lead(sc.d1_id, {"lead_consultant_id": outsider_id}, sc.manager),
        E.ERR_CONSULTANT_PRACTICE_MISMATCH,
    )

    outsider = fx.read_consultant(sc, outsider_id)
    # The two overlapping leads that earned the capacity conflict, and no third
    assert_fields(outsider, active_lead_deliverable_count=2)

    # An in-practice consultant with no overlapping leads is accepted at once
    assigned = fx.assign_lead(sc, sc.d1_id, sc.consultant_id)
    assert_fields(assigned, lead_consultant_id=sc.consultant_id)
    assert_fields(fx.read_consultant(sc, sc.consultant_id), active_lead_deliverable_count=1)
