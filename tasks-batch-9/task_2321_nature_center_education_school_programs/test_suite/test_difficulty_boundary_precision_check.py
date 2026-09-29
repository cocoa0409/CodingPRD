"""Exact edges: the last admitted value, the first rejected one, and a zero divisor.

Each ceiling is driven from both sides, and every rejected attempt is checked to
have left its accumulator and its target row exactly as they were.
"""

from test_helpers import (
    ApiErrorId,
    assert_outcome_report,
    assert_three_decimal_string_value,
    assign_resources,
    assign_resources_payload,
    confirm_booking,
    create_booking,
    create_cleared_educator,
    create_evaluation_report_payload,
    create_fund,
    deliver_booking,
    make_teacher_contact_headers,
    refresh_animal,
    refresh_booking,
    refresh_educator,
    setup_animal_at_projected_exposure,
    setup_booking_with_approved_aid,
    setup_educator_at_weekly_load,
    validate_error,
    validate_success,
)


def _second_animal_booking(scenario: dict) -> dict:
    """A second REQUESTED booking on the day after, carrying the same ambassador."""
    booking = create_booking(
        scenario["school"]["id"],
        scenario["offering"]["id"],
        start_utc="2026-09-30T14:00:00Z",
        end_utc="2026-09-30T16:00:00Z",
        student_count=20,
        chaperone_count=3,
    )
    staffing = create_cleared_educator(handling_tier="TIER_1")
    assign_resources(
        booking["id"],
        lead_educator_id=staffing["educator"]["id"],
        animal_id=scenario["animal"]["id"],
    )
    return refresh_booking(booking["id"])


def _next_free_day_booking(scenario: dict) -> dict:
    """A REQUESTED booking on the first still-unused day inside the program week."""
    day = scenario["free_days"][0]
    return create_booking(
        scenario["school"]["id"],
        scenario["offering"]["id"],
        start_utc=f"{day}T14:00:00Z",
        end_utc=f"{day}T16:00:00Z",
        student_count=20,
        chaperone_count=3,
    )


class TestAnimalWelfareCapAtTheWeeklyCeiling:
    """A 120-minute programme against an ambassador already booked for 120 minutes."""

    def test_confirmation_landing_exactly_on_the_ceiling_is_rejected(
        self, api, booking_coordinator_headers
    ):
        """PRD §3.4: "Confirmation is refused when the animal's `projected_exposure_minutes_7d` plus the booked offering's `duration_minutes` has reached or exceeded `weekly_exposure_cap_minutes`; landing exactly on the ceiling is a rejection, carrying `ERR_ANIMAL_WELFARE_CAP_REACHED`."

        Design: Difficulty/boundary_precision_check/animal_welfare_cap_rejects_at_exactly_the_weekly_ceiling
        """
        scenario = setup_animal_at_projected_exposure(
            target_minutes=120,
            weekly_exposure_cap_minutes=240,
            duration_minutes=120,
        )
        assert scenario["animal"]["projected_exposure_minutes_7d"] == 120
        booking = _second_animal_booking(scenario)
        animal_before = refresh_animal(scenario["animal"]["id"])

        # 120 already committed plus a 120-minute programme lands on 240 of 240.
        response = api.confirm_booking(booking["id"], booking_coordinator_headers)
        validate_error(response, ApiErrorId.ERR_ANIMAL_WELFARE_CAP_REACHED.value)

        after = refresh_booking(booking["id"])
        assert after["delivery_status"] == "REQUESTED"
        assert after["version"] == booking["version"]

        animal_after = refresh_animal(scenario["animal"]["id"])
        assert animal_after["projected_exposure_minutes_7d"] == 120
        assert animal_after["welfare_posture"] == "OPEN"
        assert animal_after["version"] == animal_before["version"]

    def test_confirmation_one_minute_below_the_ceiling_is_accepted(
        self, api, booking_coordinator_headers
    ):
        """PRD §2.9: "Confirming would leave the animal's projected weekly exposure strictly below its ceiling: `projected_exposure_minutes_7d` plus the offering's `duration_minutes` is strictly less than `weekly_exposure_cap_minutes` — otherwise `ERR_ANIMAL_WELFARE_CAP_REACHED` (422)."

        Design: Difficulty/boundary_precision_check/animal_welfare_cap_rejects_at_exactly_the_weekly_ceiling
        """
        scenario = setup_animal_at_projected_exposure(
            target_minutes=120,
            weekly_exposure_cap_minutes=241,
            duration_minutes=120,
        )
        assert scenario["animal"]["projected_exposure_minutes_7d"] == 120
        booking = _second_animal_booking(scenario)

        # 120 already committed plus 120 lands on 240, strictly below a 241 ceiling.
        confirmed = validate_success(
            api.confirm_booking(booking["id"], booking_coordinator_headers)
        )
        assert confirmed["delivery_status"] == "CONFIRMED"

        animal_after = refresh_animal(scenario["animal"]["id"])
        assert animal_after["projected_exposure_minutes_7d"] == 240


class TestEducatorWeeklyLoadAtTheSeasonalCap:
    """A seasonal educator carrying 120-minute programmes against a 360-minute week."""

    def test_assignment_landing_exactly_on_the_cap_is_allowed(
        self, api, booking_coordinator_headers
    ):
        """PRD §3.3: "The check is strict: adding the candidate offering's `duration_minutes` to the current load must not exceed the cap, and a total that lands above it is rejected with `ERR_EDUCATOR_WEEKLY_LOAD_EXCEEDED` while a total landing exactly on the cap is allowed."

        Design: Difficulty/boundary_precision_check/educator_weekly_load_allowed_at_exactly_the_seasonal_cap
        """
        scenario = setup_educator_at_weekly_load(
            target_minutes=240,
            employment_type="SEASONAL_EDUCATOR",
            season_end_date="2026-11-30T00:00:00Z",
            duration_minutes=120,
        )
        educator_id = scenario["educator"]["id"]
        assert scenario["educator"]["delivery_load_minutes_this_week"] == 240
        booking = _next_free_day_booking(scenario)

        # 240 carried plus a third 120-minute programme lands on 360 of 360.
        assigned = validate_success(
            api.assign_booking_resources(
                booking["id"],
                assign_resources_payload(
                    booking["version"], lead_educator_id=educator_id
                ),
                booking_coordinator_headers,
            )
        )
        assert assigned["lead_educator_id"] == educator_id
        assert refresh_educator(educator_id)["delivery_load_minutes_this_week"] == 360

    def test_assignment_one_programme_past_the_cap_is_rejected(
        self, api, booking_coordinator_headers
    ):
        """PRD §3.3: "That running total is checked against a cap that depends on employment type: a seasonal educator may carry six hours of delivery per week — 360 minutes — while a staff naturalist may carry ten hours, or 600 minutes."

        Design: Difficulty/boundary_precision_check/educator_weekly_load_allowed_at_exactly_the_seasonal_cap
        """
        scenario = setup_educator_at_weekly_load(
            target_minutes=360,
            employment_type="SEASONAL_EDUCATOR",
            season_end_date="2026-11-30T00:00:00Z",
            duration_minutes=120,
        )
        educator_id = scenario["educator"]["id"]
        assert scenario["educator"]["delivery_load_minutes_this_week"] == 360
        booking = _next_free_day_booking(scenario)

        # 360 carried plus a fourth 120-minute programme would reach 480.
        response = api.assign_booking_resources(
            booking["id"],
            assign_resources_payload(booking["version"], lead_educator_id=educator_id),
            booking_coordinator_headers,
        )
        validate_error(response, ApiErrorId.ERR_EDUCATOR_WEEKLY_LOAD_EXCEEDED.value)

        after = refresh_booking(booking["id"])
        assert after["lead_educator_id"] is None
        assert after["version"] == booking["version"]
        assert refresh_educator(educator_id)["delivery_load_minutes_this_week"] == 360


class TestOutcomeReportZeroStudentDenominator:
    """The funder rollup when nothing qualifying has been delivered yet."""

    def test_awarded_but_undelivered_pool_reports_zero_indices(
        self, api, grants_officer_headers
    ):
        """PRD §2.7: "The funder rollup's `weighted_learning_gain_index` and `tier_1_student_share_pct` each carry exactly three decimal places, rounded half up, and both report `0.000` when the student denominator they divide by is zero."

        Design: Difficulty/boundary_precision_check/outcome_report_zero_denominator_yields_zero_index_not_a_division_error
        """
        scenario = setup_booking_with_approved_aid()

        report = validate_success(
            api.get_fund_outcome_report(scenario["fund"]["id"], grants_officer_headers)
        )
        assert_outcome_report(report)
        assert report["students_served_count"] == 0
        assert_three_decimal_string_value(
            report["weighted_learning_gain_index"], 0.000, "weighted_learning_gain_index"
        )
        assert_three_decimal_string_value(
            report["tier_1_student_share_pct"], 0.000, "tier_1_student_share_pct"
        )
        assert report["awarded_application_count"] == 1
        assert report["committed_cents"] == 35300
        assert report["disbursed_cents"] == 0
        assert report["available_cents"] == 4964700

    def test_delivered_pool_whose_report_is_only_submitted_still_reports_zero_indices(
        self, api, booking_coordinator_headers, grants_officer_headers
    ):
        """PRD §3.9: "Reports in `DRAFT`, `SUBMITTED` or `RETURNED` are excluded, and a booking whose aid was approved but not yet delivered contributes to `awarded_application_count` while contributing nothing to the outcome figures."

        Design: Difficulty/boundary_precision_check/outcome_report_zero_denominator_yields_zero_index_not_a_division_error
        """
        scenario = setup_booking_with_approved_aid()
        booking_id = scenario["booking"]["id"]
        confirm_booking(booking_id)
        deliver_booking(booking_id, 30, 3)

        teacher = make_teacher_contact_headers(scenario["school"]["id"])
        evaluation = validate_success(
            api.create_evaluation_report(
                booking_id, create_evaluation_report_payload(), teacher
            ),
            expected_status=201,
        )
        submitted = validate_success(api.submit_evaluation_report(evaluation["id"], teacher))
        assert submitted["status"] == "SUBMITTED"

        report = validate_success(
            api.get_fund_outcome_report(scenario["fund"]["id"], grants_officer_headers)
        )
        assert_outcome_report(report)
        assert report["students_served_count"] == 0
        assert_three_decimal_string_value(
            report["weighted_learning_gain_index"], 0.000, "weighted_learning_gain_index"
        )
        assert_three_decimal_string_value(
            report["tier_1_student_share_pct"], 0.000, "tier_1_student_share_pct"
        )
        assert report["awarded_application_count"] == 1

    def test_pool_with_no_applications_reports_zero_indices(
        self, api, grants_officer_headers
    ):
        """PRD §3.8: "A new pool opens at `OPEN` with `pending_cents`, `committed_cents`, `disbursed_cents` and `transport_awarded_cents` all at 0 and `available_cents` equal to `total_cents`."

        Design: Difficulty/boundary_precision_check/outcome_report_zero_denominator_yields_zero_index_not_a_division_error
        """
        fund = create_fund(total_cents=5000000, transport_sublimit_pct=0.25)

        report = validate_success(
            api.get_fund_outcome_report(fund["id"], grants_officer_headers)
        )
        assert_outcome_report(report)
        assert report["students_served_count"] == 0
        assert_three_decimal_string_value(
            report["weighted_learning_gain_index"], 0.000, "weighted_learning_gain_index"
        )
        assert_three_decimal_string_value(
            report["tier_1_student_share_pct"], 0.000, "tier_1_student_share_pct"
        )
        assert report["awarded_application_count"] == 0
        assert report["committed_cents"] == 0
        assert report["disbursed_cents"] == 0
        assert report["available_cents"] == 5000000
