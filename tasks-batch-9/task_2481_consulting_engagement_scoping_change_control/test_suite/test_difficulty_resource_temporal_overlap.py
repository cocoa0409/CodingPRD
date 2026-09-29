"""Windows that touch without overlapping, and the counts they feed."""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import ConsultingApiClient
from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_fields, assert_pagination_meta

EXTRA_DELIVERABLE = {
    "primary_grade": C.GRADE_CONSULTANT,
    "effort_hours_estimate": 20.0,
    "completion_weight_pct": 10.0,
    "acceptance_criteria": "Signed working paper",
}


def _consultant_with_two_overlapping_leads(api: ConsultingApiClient) -> fx.Scenario:
    """One consultant leading two windows that both cover mid-October."""
    sc = fx.build_scoped_pursuit(api)
    for spec in (
        dict(
            EXTRA_DELIVERABLE,
            name="Cost driver deep-dive",
            planned_start_date="2026-09-15",
            planned_end_date="2026-10-31",
        ),
        dict(
            EXTRA_DELIVERABLE,
            name="Service-level modelling",
            planned_start_date="2026-10-01",
            planned_end_date="2026-11-30",
        ),
        dict(
            EXTRA_DELIVERABLE,
            name="Transition readiness check",
            planned_start_date="2026-10-15",
            planned_end_date="2026-11-30",
        ),
    ):
        fx.add_deliverable(sc, spec)
    # d1 runs 2026-09-01 to 2026-10-15, the deep-dive 2026-09-15 to 2026-10-31
    fx.assign_lead(sc, sc.d1_id, sc.consultant_id)
    fx.assign_lead(sc, sc.deliverable_ids[2], sc.consultant_id)
    return sc


def test_the_third_overlapping_lead_assignment_is_refused(
    api: ConsultingApiClient,
) -> None:
    """Two concurrent leads are allowed; a window overlapping both is not.

    PRD 3.3: "If that count is two or more, the assignment is refused with
    `ERR_CONSULTANT_CAPACITY_CONFLICT` — meaning two overlapping lead
    assignments are permitted and the third overlapping one is not."

    Design: Difficulty/resource_temporal_overlap/consultant_capacity_half_open_boundary_and_aggregate_cap
    """
    sc = _consultant_with_two_overlapping_leads(api)
    # 2026-10-01 to 2026-11-30 overlaps d1 and the deep-dive at once
    contested_id = sc.deliverable_ids[3]

    response = api.assign_lead(
        contested_id, {"lead_consultant_id": sc.consultant_id}, sc.manager
    )

    validate_error(response, E.ERR_CONSULTANT_CAPACITY_CONFLICT)
    assert_fields(fx.read_deliverable(sc, contested_id), lead_consultant_id=None)
    assert_fields(
        fx.read_consultant(sc, sc.consultant_id), active_lead_deliverable_count=2
    )


def test_a_window_starting_on_a_predecessors_end_date_does_not_overlap_it(
    api: ConsultingApiClient,
) -> None:
    """The half-open rule drops d1 out of the count, so only one lead overlaps.

    PRD 3.3: "The deliverable's own planned window is treated as half-open —
    the start date is included and the end date is excluded — so a deliverable
    ending on 2026-10-01 does not overlap one starting on 2026-10-01."

    Design: Difficulty/resource_temporal_overlap/consultant_capacity_half_open_boundary_and_aggregate_cap
    """
    sc = _consultant_with_two_overlapping_leads(api)
    # 2026-10-15 to 2026-11-30 starts exactly where d1's window ends
    boundary_id = sc.deliverable_ids[4]

    assigned = fx.assign_lead(sc, boundary_id, sc.consultant_id)

    assert_fields(assigned, lead_consultant_id=sc.consultant_id)
    assert_fields(
        fx.read_consultant(sc, sc.consultant_id), active_lead_deliverable_count=3
    )
    # Nothing else was staffed by the accepted assignment
    assert_fields(fx.read_deliverable(sc, sc.d2_id), lead_consultant_id=None)


def test_a_two_day_gap_between_checkpoint_windows_is_refused(
    api: ConsultingApiClient,
) -> None:
    """The first window ends 2026-09-30; a 2026-10-02 start is too close.

    PRD 3.9: "And the new window must keep a gap of at least 3 days from every
    other non-terminal checkpoint window on the same engagement — checkpoints
    must not be stacked back-to-back — otherwise `ERR_REVIEW_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/quality_review_window_three_day_gap_closed_interval
    """
    sc = fx.build_active_engagement(api)
    fx.schedule_review(sc)

    response = api.create_quality_review(
        {
            "engagement_id": sc.engagement_id,
            "reviewer_consultant_id": sc.reviewer_id,
            "checkpoint_type": C.CHECKPOINT_PRE_DELIVERY,
            "window_start_date": "2026-10-02",
            "window_end_date": "2026-10-10",
        },
        sc.manager,
    )

    validate_error(response, E.ERR_REVIEW_WINDOW_CONFLICT)
    _, meta = validate_paginated(
        api.list_quality_reviews(sc.manager, {"engagement_id": sc.engagement_id})
    )
    assert_pagination_meta(meta, total_count=1, has_more=False)


def test_a_gap_of_exactly_three_days_between_windows_is_accepted(
    api: ConsultingApiClient,
) -> None:
    """One day later the spacing rule is satisfied at its lower bound.

    PRD 3.9: "A newly scheduled checkpoint sits at `SCHEDULED` with
    `findings_severity` defaulting to `NONE` and a null `note`."

    Design: Difficulty/resource_temporal_overlap/quality_review_window_three_day_gap_closed_interval
    """
    sc = fx.build_active_engagement(api)
    fx.schedule_review(sc)

    second = fx.schedule_review(
        sc,
        checkpoint_type=C.CHECKPOINT_PRE_DELIVERY,
        window_start_date="2026-10-03",
        window_end_date="2026-10-10",
    )

    assert_fields(
        second,
        status=C.REVIEW_SCHEDULED,
        findings_severity=C.SEVERITY_NONE,
        note=None,
        checkpoint_type=C.CHECKPOINT_PRE_DELIVERY,
    )
    _, meta = validate_paginated(
        api.list_quality_reviews(sc.manager, {"engagement_id": sc.engagement_id})
    )
    assert_pagination_meta(meta, total_count=2, has_more=False)
