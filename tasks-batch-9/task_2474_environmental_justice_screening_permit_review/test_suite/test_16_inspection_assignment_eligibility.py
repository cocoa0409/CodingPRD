"""The inspection selector when the eligible pool narrows away to nothing.

Every complaint in the narrowed block group fails the eligibility filter for a
different reason, so the queue has nothing to hand out — while the same request
without the narrowing finds the one eligible complaint next door.
"""

from test_helpers import (
    ANALYST_HEADERS,
    ApiErrorId,
    COMPLAINT_DISMISSED,
    COMPLAINT_INSPECTION_ASSIGNED,
    COMPLAINT_TRIAGED,
    INSPECTION_SCHEDULED,
    INSPECTOR_1_USER_ID,
    TIER_3,
    assert_amount,
    assert_area_scores,
    assert_empty_listing,
    assert_field,
    assert_fields,
    assert_rejected,
    assign_next,
    assign_next_payload,
    read_area,
    read_complaint,
)


def _ask_for_the_next_visit(api, screening_area_id=None):
    """Pull the next assignment, optionally narrowed to one block group."""
    return api.assign_next_inspection(
        assign_next_payload(
            inspector_user_id=INSPECTOR_1_USER_ID,
            scheduled_date="2026-08-05",
            screening_area_id=screening_area_id,
        ),
        ANALYST_HEADERS,
    )


class TestEmptyEligiblePool:
    """PRD §3.8 refuses rather than reaching outside the requested area."""

    def test_a_facility_less_and_a_dismissed_complaint_leave_nothing_to_assign(
        self, api, area_e_f_complaint_pool
    ):
        """Narrowed to the one area, the candidate set is empty and nothing is written.

        PRD §3.8: "The candidate set is then the complaints whose `status` is
        `TRIAGED`, whose `facility_id` is not null, and for which no inspection row is
        currently `SCHEDULED`, narrowed to the requested `screening_area_id` when that
        field was supplied." and "If the candidate set is empty the request is refused
        with `ERR_NO_ELIGIBLE_COMPLAINT`, no inspection row is created and no complaint
        is mutated."
        PRD §2.10: "Inspection assignment: the selector's candidate set is non-empty —
        otherwise `ERR_NO_ELIGIBLE_COMPLAINT` (409)."
        PRD §3.8: "Dismissing requires a `dismissal_reason`, moves the complaint
        `RECEIVED → DISMISSED` (terminal), decrements the area's `open_complaint_count`
        by 1, and increments the complaint's `version` by 1."

        Design: Difficulty/boundary_precision_check/assign_next_empty_eligible_pool_returns_no_eligible_complaint
        """
        state = area_e_f_complaint_pool
        assert_field(
            read_complaint(api, state["complaint_no_facility_id"]),
            "status",
            COMPLAINT_TRIAGED,
        )
        assert_field(
            read_complaint(api, state["complaint_dismissed_id"]),
            "status",
            COMPLAINT_DISMISSED,
        )

        response = _ask_for_the_next_visit(api, screening_area_id=state["area_id"])

        assert_rejected(response, ApiErrorId.NO_ELIGIBLE_COMPLAINT)
        assert response.status_code == 409, (
            "an empty candidate set is an HTTP 409 conflict"
        )

        # No row was written and neither ineligible complaint moved.
        assert_empty_listing(
            api.list_complaint_inspections(
                state["complaint_no_facility_id"], ANALYST_HEADERS
            )
        )
        assert_empty_listing(
            api.list_complaint_inspections(
                state["complaint_dismissed_id"], ANALYST_HEADERS
            )
        )
        assert_field(
            read_complaint(api, state["complaint_no_facility_id"]),
            "status",
            COMPLAINT_TRIAGED,
        )
        assert_field(
            read_complaint(api, state["complaint_dismissed_id"]),
            "status",
            COMPLAINT_DISMISSED,
        )

    def test_the_same_request_without_the_narrowing_finds_the_neighbour(
        self, api, area_e_f_complaint_pool
    ):
        """Dropping `screening_area_id` widens the queue to the eligible 15.00 filing.

        PRD §3.8: "An `EJAnalyst` asks for the next assignment by supplying an
        `inspector_user_id` — the opaque identifier of the `Inspector` the visit is
        assigned to — a `scheduled_date` for the visit as an ISO date in UTC, and
        optionally a `screening_area_id` to narrow the queue to one block group."
        PRD §3.8: "A successful assignment creates an inspection in `status`
        `SCHEDULED` naming the `community_complaint_id` that earned it, copying the
        selected complaint's `facility_id` into the inspection's own `facility_id`,
        recording `priority_score_at_assignment` as a snapshot of the winning
        complaint's `priority_score`, and leaving `finding` null." and "The complaint
        moves `TRIAGED → INSPECTION_ASSIGNED` and its `version` increments by 1."
        PRD §3.8: "Then `priority_score` is the sum of five terms, rounded half up to
        two decimals: the area's **county** screening score multiplied by 0.40;
        severity points of 5 for `LOW`, 15 for `MEDIUM` or 30 for `HIGH`; the smaller
        of 20 and four points per prior repeat, so the repeat contribution saturates at
        five priors; a flat 10 points when a `facility_id` was named and that facility's
        `compliance_status` is `VIOLATION_ON_RECORD`; and a flat 5 points when the
        area's `designation` is `SEVERELY_OVERBURDENED`."
        PRD §3.8: "From the score comes `priority_tier`: `TIER_1` when the score is at
        least 70.00, otherwise `TIER_2` when it is at least 45.00, otherwise `TIER_3`."

        Design: Difficulty/boundary_precision_check/assign_next_empty_eligible_pool_returns_no_eligible_complaint
        """
        state = area_e_f_complaint_pool
        assert_rejected(
            _ask_for_the_next_visit(api, screening_area_id=state["area_id"]),
            ApiErrorId.NO_ELIGIBLE_COMPLAINT,
        )
        # The neighbour has no indicators, so only the severity term scores.
        assert_area_scores(
            read_area(api, state["area_f_id"]), statewide=0.00, county=0.00
        )

        inspection = assign_next(api, state, INSPECTOR_1_USER_ID, "2026-08-05")

        assert_fields(
            inspection,
            {
                "status": INSPECTION_SCHEDULED,
                "community_complaint_id": state["complaint_f_id"],
                "facility_id": state["facility_f_id"],
                "finding": None,
            },
        )
        # 0.00 county score x 0.40 plus 15 severity points for MEDIUM.
        assert_amount(
            inspection.get("priority_score_at_assignment"),
            15.00,
            "priority_score_at_assignment",
        )

        complaint = read_complaint(api, state["complaint_f_id"])
        assert_field(complaint, "status", COMPLAINT_INSPECTION_ASSIGNED)
        assert_field(complaint, "priority_tier", TIER_3)
        assert_amount(complaint.get("priority_score"), 15.00, "priority_score")
