"""The arithmetic surface: health selection, final weights, deadlines and aggregates."""
import pytest

from test_helpers import (
    ADMIN_HEADERS,
    FIRST_VISIT_END,
    FIRST_VISIT_START,
    INTEGRATOR_HEADERS,
    SCORE_SHEET_PERFECT,
    api_client,
    advance_clock,
    assert_instant,
    create_health_inspection,
    create_location,
    disregard_payload,
    finalize_visit,
    schedule_visit,
    score_visit,
    setup_brand_program,
    setup_finalized_visit,
    setup_submitted_visit,
    start_visit,
    submit_visit,
    validate_paginated,
    validate_success,
)

SECOND_WINDOW_START = "2026-08-19T09:00:00Z"
SECOND_WINDOW_END = "2026-08-19T13:00:00Z"


class TestFinalCompositeWeights:
    def test_the_final_composite_admits_health_at_one_quarter_weight(self):
        """A grade-C inspection dilutes the rubric and moves the visit out of PASS.

        PRD: "The `FINAL` variant admits the health figure and dilutes the rubric:
        `composite_score` becomes the base score multiplied by forty-five hundredths, plus
        `food_safety_percent` multiplied by three tenths, plus `health_component_percent`
        multiplied by twenty-five hundredths, rounded half up to two decimal places."

        Design: Corner/calculations/final_composite_admits_the_health_component_at_one_quarter_weight
        """
        program = setup_submitted_visit(health_points=74, health_grade="C")
        assert program["visit"]["composite_score"] == pytest.approx(90.70, abs=0.01)
        assert program["visit"]["composite_variant"] == "PROVISIONAL"
        assert program["visit"]["grade"] == "PASS"

        finalized = finalize_visit(program, program["visit"]["id"], at=FIRST_VISIT_END)
        assert finalized["status"] == "FINALIZED"
        assert finalized["health_component_percent"] == pytest.approx(74.00, abs=0.01), \
            "74 of 100 is already under the letter-C ceiling of 79.00"
        assert finalized["linked_health_inspection_id"] == program["health_inspection"]["id"]
        assert finalized["composite_score"] == pytest.approx(86.52, abs=0.01), \
            "0.45 * 87.83 + 0.30 * 95.00 + 0.25 * 74.00"
        assert finalized["composite_variant"] == "FINAL"
        assert finalized["grade"] == "CONDITIONAL", \
            "admitting the health component pushed the visit below 90.00"

        location = validate_success(
            api_client.get_location(program["location"]["id"], ADMIN_HEADERS)
        )
        assert location["standing_score"] == pytest.approx(86.52, abs=0.01)
        assert location["latest_grade"] == "CONDITIONAL"

    def test_the_final_variant_is_labelled_final_even_without_a_health_figure(self):
        """The label reflects the operation, not the weight set that was used.

        PRD: "When no eligible inspection was found and `health_component_percent` is null,
        the final composite falls back to the provisional weight set — base score at six tenths
        plus `food_safety_percent` at four tenths — but `composite_variant` is still recorded as
        `FINAL`."

        Design: Corner/calculations/final_variant_is_labelled_final_even_when_it_borrows_the_provisional_weights
        """
        program = setup_submitted_visit()
        assert program["visit"]["composite_score"] == pytest.approx(90.70, abs=0.01)
        assert program["visit"]["composite_variant"] == "PROVISIONAL"

        finalized = finalize_visit(program, program["visit"]["id"], at=FIRST_VISIT_END)
        assert finalized["health_component_percent"] is None
        assert finalized["linked_health_inspection_id"] is None
        assert finalized["composite_score"] == pytest.approx(90.70, abs=0.01), \
            "numerically identical to the provisional value"
        assert finalized["composite_variant"] == "FINAL"
        assert finalized["grade"] == "PASS"

        advance_clock("2026-08-06T09:00:00Z")
        create_health_inspection(
            program["location"]["id"], 100, "A", inspection_date="2026-07-25T00:00:00Z",
        )

        reread = validate_success(
            api_client.get_audit_visit(program["visit"]["id"], ADMIN_HEADERS)
        )
        assert reread["composite_score"] == pytest.approx(90.70, abs=0.01)
        assert reread["composite_variant"] == "FINAL"
        assert reread["health_component_percent"] is None, \
            "a late import does not retro-fit an already finalized visit"
        assert reread["linked_health_inspection_id"] is None
        assert reread["grade"] == "PASS"

        location = validate_success(
            api_client.get_location(program["location"]["id"], ADMIN_HEADERS)
        )
        assert location["standing_score"] == pytest.approx(90.70, abs=0.01)


class TestHealthSelection:
    def test_health_selection_ignores_disregarded_and_out_of_window_inspections(self):
        """The newest eligible inspection wins even though it is the lowest scoring one.

        PRD: "An inspection is eligible when it belongs to the visit's location, its `status`
        is `RECORDED`, its `inspection_date` is at or before that window end, and its
        `inspection_date` is no earlier than 180 days before that window end."

        Design: Corner/calculations/health_selection_ignores_disregarded_and_out_of_window_inspections
        """
        program = setup_brand_program()
        location_id = program["location"]["id"]

        newest = create_health_inspection(
            location_id, 100, "A", inspection_date="2026-07-20T00:00:00Z",
        )
        stale = create_health_inspection(
            location_id, 100, "A", inspection_date="2026-01-15T00:00:00Z",
        )
        on_edge = create_health_inspection(
            location_id, 79, "C", inspection_date="2026-02-06T09:00:00Z",
        )

        disregarded = validate_success(
            api_client.disregard_health_inspection(
                newest["id"], disregard_payload("SUPERSEDED_BY_REINSPECTION"),
                INTEGRATOR_HEADERS,
            )
        )
        assert disregarded["status"] == "DISREGARDED"
        assert disregarded["disregard_reason"] == "SUPERSEDED_BY_REINSPECTION"

        program = setup_submitted_visit(program=program)
        finalized = finalize_visit(program, program["visit"]["id"], at=FIRST_VISIT_END)

        assert finalized["linked_health_inspection_id"] == on_edge["id"], \
            "the disregarded newest and the out-of-window one are both excluded"
        assert finalized["linked_health_inspection_id"] != stale["id"]
        assert finalized["health_component_percent"] == pytest.approx(79.00, abs=0.01), \
            "79 of 100 ties the letter-C ceiling exactly"
        assert finalized["composite_score"] == pytest.approx(87.77, abs=0.01), \
            "0.45 * 87.83 + 0.30 * 95.00 + 0.25 * 79.00"
        assert finalized["grade"] == "CONDITIONAL", \
            "either excluded inspection would have given 93.02 and PASS"

        rows, meta = validate_paginated(
            api_client.list_location_health_inspections(
                location_id, ADMIN_HEADERS,
                params={"status": "RECORDED", "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 2, "the disregarded record left the eligibility pool"
        assert {row["id"] for row in rows} == {stale["id"], on_edge["id"]}

    def test_same_day_inspections_are_broken_by_creation_order(self):
        """Equal inspection dates resolve by created_at descending, not by score.

        PRD: "Otherwise, order the eligible inspections by `inspection_date` descending,
        breaking ties by `created_at` descending, and take the first; its `id` is stored as
        `linked_health_inspection_id`."

        Design: Corner/calculations/same_day_inspections_are_broken_by_creation_order
        """
        program = setup_brand_program()
        location_id = program["location"]["id"]

        first_written = create_health_inspection(
            location_id, 60, "B", inspection_date="2026-07-20T00:00:00Z",
        )
        second_written = create_health_inspection(
            location_id, 92, "A", inspection_date="2026-07-20T00:00:00Z",
        )

        program = setup_submitted_visit(program=program)
        finalized = finalize_visit(program, program["visit"]["id"], at=FIRST_VISIT_END)

        assert finalized["linked_health_inspection_id"] == second_written["id"]
        assert finalized["linked_health_inspection_id"] != first_written["id"]
        assert finalized["health_component_percent"] == pytest.approx(92.00, abs=0.01), \
            "the letter-A ceiling of 100.00 imposes nothing"
        assert finalized["composite_score"] == pytest.approx(91.02, abs=0.01), \
            "0.45 * 87.83 + 0.30 * 95.00 + 0.25 * 92.00"
        assert finalized["grade"] == "PASS", \
            "picking the earlier record would have given 83.02 and CONDITIONAL"

        location = validate_success(api_client.get_location(location_id, ADMIN_HEADERS))
        assert location["standing_score"] == pytest.approx(91.02, abs=0.01)
        assert location["latest_grade"] == "PASS"


class TestCorrectiveActionDeadlines:
    def test_deadlines_use_seventy_two_hours_and_fourteen_days_exactly(self):
        """Both offsets preserve the time of day and neither is shifted off a weekend.

        PRD: "Severity drives the deadline: `due_at` is 72 hours after the visit's
        `finalized_at` for a `CRITICAL` action and 14 days after `finalized_at` for a
        `STANDARD` one, expressed to whole seconds in ISO 8601 UTC."

        Design: Corner/calculations/corrective_action_deadlines_use_seventy_two_hours_and_fourteen_days_exactly
        """
        program = setup_submitted_visit(
            start_at="2026-08-25T09:00:00Z", end_at="2026-08-25T13:00:00Z",
        )
        finalized = finalize_visit(
            program, program["visit"]["id"], at="2026-08-25T18:30:00Z",
        )
        assert_instant(finalized["finalized_at"], "2026-08-25T18:30:00Z", "finalized_at")
        assert finalized["composite_score"] == pytest.approx(90.70, abs=0.01)

        deadlines = {}
        for code in ("FS-1", "BS-1", "FC-1"):
            rows, _ = validate_paginated(
                api_client.list_corrective_actions(
                    ADMIN_HEADERS, params={"scored_item_id": program["scored"][code]["id"]}
                )
            )
            assert len(rows) == 1
            deadlines[code] = validate_success(
                api_client.get_corrective_action(rows[0]["id"], ADMIN_HEADERS)
            )

        assert deadlines["FS-1"]["severity"] == "CRITICAL"
        assert_instant(
            deadlines["FS-1"]["due_at"], "2026-08-28T18:30:00Z", "critical due_at",
        )
        assert deadlines["FC-1"]["severity"] == "STANDARD"
        assert_instant(
            deadlines["BS-1"]["due_at"], "2026-09-08T18:30:00Z", "standard due_at",
        )
        assert_instant(
            deadlines["FC-1"]["due_at"], "2026-09-08T18:30:00Z", "standard due_at",
        )
        assert deadlines["BS-1"]["due_at"] == deadlines["FC-1"]["due_at"], \
            "severity alone drives the offset"


class TestBrandAggregation:
    def test_the_brand_index_averages_rated_locations_only(self):
        """A never-audited location belongs to the brand but not to the average.

        PRD: "Only *rated* locations participate: those whose `latest_grade` is not null,
        meaning they have at least one finalized visit."

        Design: Corner/calculations/brand_index_averages_rated_locations_only
        """
        program = setup_finalized_visit()
        brand_id = program["brand"]["id"]
        unaudited = create_location(
            brand_id, program["franchisee"]["id"], store_number="SKWR-021",
        )

        second = validate_success(api_client.get_location(unaudited["id"], ADMIN_HEADERS))
        assert second["standing_score"] == pytest.approx(0.00, abs=0.01)
        assert second["latest_grade"] is None

        risk = validate_success(api_client.get_brand_risk_index(brand_id, ADMIN_HEADERS))
        assert risk["rated_location_count"] == 1
        assert risk["average_standing_score"] == pytest.approx(90.70, abs=0.01), \
            "averaging the unrated location in would give 45.35 and tier ELEVATED"
        assert risk["brand_risk_index"] == pytest.approx(11.58, abs=0.01), \
            "0.60 * 9.30 plus 6.00 for the single open critical action"
        assert risk["brand_risk_tier"] == "BASELINE"
        assert risk["open_critical_action_count"] == 1
        assert risk["default_location_count"] == 0
        assert risk["fail_grade_surcharge_applied"] is False

        brand = validate_success(api_client.get_brand(brand_id, ADMIN_HEADERS))
        assert brand["location_count"] == 2, "membership and rating are different sets"
        assert brand["brand_risk_index"] == pytest.approx(11.58, abs=0.01), \
            "the computed read persists its result on the brand"
        assert brand["brand_risk_tier"] == "BASELINE"


class TestStandingRenormalization:
    def test_two_finalized_visits_renormalize_the_recency_weights(self):
        """With one weight truncated away the remaining two become five and three eighths.

        PRD: "Otherwise the recency weights one half, three tenths, and one fifth are
        truncated to the number of visits actually available and then renormalized by dividing
        each by the sum of the truncated weights — so a location with only two finalized visits
        weights them five eighths and three eighths."

        Design: Corner/calculations/standing_score_renormalizes_recency_weights_when_fewer_than_three_visits_exist
        """
        program = setup_brand_program()
        first = schedule_visit(program, FIRST_VISIT_START, FIRST_VISIT_END)
        second = schedule_visit(program, SECOND_WINDOW_START, SECOND_WINDOW_END)

        start_visit(program, first["id"], at=FIRST_VISIT_START)
        score_visit(program, first["id"])
        submit_visit(program, first["id"])
        first_final = finalize_visit(program, first["id"], at=FIRST_VISIT_END)
        assert first_final["composite_score"] == pytest.approx(90.70, abs=0.01)

        after_one = validate_success(
            api_client.get_location(program["location"]["id"], ADMIN_HEADERS)
        )
        assert after_one["standing_score"] == pytest.approx(90.70, abs=0.01), \
            "a single visit renormalizes its 0.50 weight up to 1.00"
        assert after_one["latest_grade"] == "PASS"

        start_visit(program, second["id"], at=SECOND_WINDOW_START)
        score_visit(program, second["id"], SCORE_SHEET_PERFECT)
        submit_visit(program, second["id"])
        second_final = finalize_visit(program, second["id"], at=SECOND_WINDOW_END)
        assert second_final["critical_violation_count"] == 0
        assert second_final["critical_penalty_points"] == pytest.approx(0.00, abs=0.01)
        assert second_final["composite_score"] == pytest.approx(100.00, abs=0.01)
        assert second_final["grade"] == "PASS"

        location = validate_success(
            api_client.get_location(program["location"]["id"], ADMIN_HEADERS)
        )
        assert location["standing_score"] == pytest.approx(96.51, abs=0.01), \
            "0.625 * 100.00 + 0.375 * 90.70, not the un-renormalized 77.21 or an even 95.35"
        assert location["latest_grade"] == "PASS"
        assert location["repeat_violation_count"] == 0, "so no penalty is subtracted"
        assert location["open_corrective_action_count"] == 3, \
            "the clean second visit created no corrective action"

        risk = validate_success(
            api_client.get_brand_risk_index(program["brand"]["id"], ADMIN_HEADERS)
        )
        assert risk["rated_location_count"] == 1
        assert risk["average_standing_score"] == pytest.approx(96.51, abs=0.01)
        assert risk["brand_risk_index"] == pytest.approx(8.09, abs=0.01)
