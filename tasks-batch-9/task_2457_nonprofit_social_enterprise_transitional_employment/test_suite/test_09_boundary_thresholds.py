"""Inclusive boundaries: the weekly hours cap and the composite viability floor."""

from test_helpers import (
    ApiErrorId,
    BusinessLineStatus,
    ReviewDecision,
    ShiftAssignmentStatus,
    assert_business_line,
    assert_hours,
    assert_score,
    factories,
    fixtures,
    make_case_manager_headers,
    make_program_director_headers,
    validate_error,
    validate_success,
)


class TestWeeklyHoursCapBoundary:
    """Twelve plus twelve plus four is exactly twenty-eight; half an hour more is not."""

    def test_reaching_exactly_28_000_hours_is_accepted(self, api):
        """The cap is inclusive at exactly 28.000 hours.

        "Exactly 28.000 is accepted; anything beyond it is refused with
        `ERR_WEEKLY_HOURS_CAP_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/weekly_hours_cap_boundary_28_000_inclusive
        """
        program = fixtures.weekly_hours_ladder_program(api)

        response = api.create_shift_assignment(
            factories.shift_assignment_payload(
                program["wednesday_shift"]["id"], program["participant"]["id"]
            ),
            make_case_manager_headers(),
        )
        assignment = validate_success(response, 201)

        assert assignment["status"] == ShiftAssignmentStatus.ASSIGNED

        participant = fixtures.read_participant(api, program["participant"]["id"])
        assert_hours(
            participant["scheduled_hours_current_week"],
            28.000,
            "scheduled_hours_current_week",
        )

    def test_a_further_half_hour_breaches_the_cap(self, api):
        """Half an hour past the cap is refused and no seat is taken.

        "And the weekly hours cap must hold: the participant's already-committed
        hours in the ISO week containing the new shift — the sum of
        `duration_hours` over that participant's assignments in `ASSIGNED` or
        `COMPLETED` status whose shift `starts_at` falls in the same ISO week —
        plus the new shift's `duration_hours` must come to no more than 28 hours."

        Design: Difficulty/boundary_precision_check/weekly_hours_cap_boundary_28_000_inclusive
        """
        program = fixtures.weekly_hours_ladder_program(api)
        fixtures.seat_participant(
            api, program["wednesday_shift"]["id"], program["participant"]["id"]
        )

        response = api.create_shift_assignment(
            factories.shift_assignment_payload(
                program["thursday_shift"]["id"], program["participant"]["id"]
            ),
            make_case_manager_headers(),
        )

        validate_error(response, ApiErrorId.ERR_WEEKLY_HOURS_CAP_EXCEEDED, 409)

        thursday = fixtures.read_work_shift(api, program["thursday_shift"]["id"])
        assert thursday["assigned_count"] == 0

        participant = fixtures.read_participant(api, program["participant"]["id"])
        assert_hours(
            participant["scheduled_hours_current_week"],
            28.000,
            "scheduled_hours_current_week",
        )


class TestCompositeViabilityFloorBoundary:
    """A line scoring exactly 70.00 passes; one scoring 69.75 does not."""

    def test_a_composite_of_exactly_70_00_clears_the_gate(self, api):
        """The composite floor is inclusive at 70.00.

        "On the approving branch, `DRAFT → APPROVED`, the viability gate is
        enforced: the line's `composite_viability_score` must be at least 70.00
        **and** the smallest of the three individual dimension scores must be at
        least 50."

        Design: Difficulty/boundary_precision_check/viability_composite_floor_boundary_exactly_70_00
        """
        line = fixtures.create_draft_business_line(
            api,
            name="Grounds Crew",
            market_viability_score=70,
            training_relevance_score=70,
            mission_alignment_score=70,
            target_gross_margin_pct=0.15,
        )
        assert_score(line["composite_viability_score"], 70.00, "composite_viability_score")

        approved = validate_success(
            api.review_business_line(
                line["id"],
                factories.review_payload(ReviewDecision.APPROVED),
                make_program_director_headers(),
            )
        )

        assert_business_line(approved)
        assert approved["status"] == BusinessLineStatus.APPROVED
        assert approved["rejection_reason"] is None

    def test_a_composite_of_69_75_is_refused_and_the_line_stays_draft(self, api):
        """One point off the third dimension drops the composite below the floor.

        "On creation the system derives the line's **composite viability score** and
        stores it as `composite_viability_score`: forty percent of
        `market_viability_score`, plus thirty-five percent of
        `training_relevance_score`, plus twenty-five percent of
        `mission_alignment_score`, with the sum rounded half up to two decimal
        places."

        Design: Difficulty/boundary_precision_check/viability_composite_floor_boundary_exactly_70_00
        """
        line = fixtures.create_draft_business_line(
            api,
            name="Print Shop",
            market_viability_score=70,
            training_relevance_score=70,
            mission_alignment_score=69,
            target_gross_margin_pct=0.15,
        )
        assert_score(line["composite_viability_score"], 69.75, "composite_viability_score")

        response = api.review_business_line(
            line["id"],
            factories.review_payload(ReviewDecision.APPROVED),
            make_program_director_headers(),
        )

        validate_error(response, ApiErrorId.ERR_VIABILITY_GATE_NOT_MET, 422)

        unchanged = fixtures.read_business_line(api, line["id"])
        assert unchanged["status"] == BusinessLineStatus.DRAFT
        assert unchanged["rejection_reason"] is None
