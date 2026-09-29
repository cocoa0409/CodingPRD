"""Derived-number tests for the Nature Center Education API.

Every expected figure here is derived from the pinned calculation prose of the
PRD: the six-step fee assessment and its rain credit (§3.8), the award waterfall
(§3.8), the learning gain index and funder rollup (§3.9), the animal exposure
counters (§3.4), school standing and the flat no-show charge (§3.2, §3.7), and
the weekly trail and educator counters (§3.5, §3.3).
"""

import pytest

from test_helpers import (
    BC,
    DEFAULT_CLOCK,
    ED,
    GO,
    TEST_DEFAULTS,
    assert_booking,
    assert_three_decimal_string_value,
    assign_resources,
    apply_for_aid,
    confirm_booking,
    create_booking,
    create_booking_payload,
    create_equipment_manifest_payload,
    create_evaluation_report_payload,
    create_fund,
    create_published_offering,
    create_school,
    deliver_booking,
    make_teacher_contact_headers,
    refresh_animal,
    refresh_booking,
    refresh_educator,
    refresh_school,
    refresh_trail_segment,
    set_clock,
    setup_animal_booking_scenario,
    setup_booking_scenario,
    setup_confirmed_booking,
    setup_outreach_booking_with_manifest,
    setup_school_with_strikes,
    setup_trail_booking_scenario,
    validate_success,
)

SECOND_DAY_START = "2026-09-30T14:00:00Z"
SECOND_DAY_END = "2026-09-30T16:00:00Z"


def _publish_rain_alternate(primary_offering_id: str) -> dict:
    """Publish a cheaper offering that declares itself the rain plan of another."""
    return create_published_offering(
        slug_prefix="indoor",
        title="Indoor Watershed Lab",
        base_fee_cents_per_student=700,
        rain_alternate_for_offering_id=primary_offering_id,
    )


class TestFeeAssessmentAtBookingCreation:
    @pytest.mark.parametrize(
        "student_count,chaperone_count,expected_chaperones,expected_gross_cents",
        [
            (30, 3, 3, 33300),
            (31, 4, 4, 34410),
        ],
    )
    def test_chaperone_requirement_steps_up_while_the_band_fee_moves_linearly(
        self,
        api,
        student_count,
        chaperone_count,
        expected_chaperones,
        expected_gross_cents,
    ):
        """PRD §3.6: "`required_chaperones` is the `student_count` divided by the offering's `min_chaperone_ratio_students_per_adult`, rounded **up** to the next whole adult — a class of 61 students on a program written for one adult per 15 students needs 5 chaperones, not 4."

        Design: Corner/calculations/chaperone_requirement_rounds_up_on_the_first_student_past_a_full_group
        """
        set_clock(DEFAULT_CLOCK)
        offering = create_published_offering()
        school = create_school()

        booking = validate_success(
            api.create_booking(
                create_booking_payload(
                    school["id"],
                    offering["id"],
                    start_utc=TEST_DEFAULTS["BOOKING_START_UTC"],
                    end_utc=TEST_DEFAULTS["BOOKING_END_UTC"],
                    student_count=student_count,
                    chaperone_count=chaperone_count,
                ),
                BC,
            ),
            201,
        )

        assert_booking(booking)
        assert booking["student_count"] == student_count
        assert booking["chaperone_count"] == chaperone_count
        assert booking["required_chaperones"] == expected_chaperones
        assert booking["provisional_gross_fee_cents"] == expected_gross_cents
        assert booking["net_due_cents"] == expected_gross_cents

    @pytest.mark.parametrize(
        "student_count,chaperone_count,expected_chaperones,expected_gross_cents",
        [
            (6, 1, 1, 12330),
            (11, 2, 2, 13563),
        ],
    )
    def test_billable_headcount_floor_lifts_a_tiny_group_to_ten_students(
        self,
        api,
        student_count,
        chaperone_count,
        expected_chaperones,
        expected_gross_cents,
    ):
        """PRD §3.8: "Step one establishes the billable headcount as the larger of the applicable headcount and a floor of ten billable students, so a class of six is priced as ten."

        Design: Corner/calculations/tiny_groups_are_priced_at_the_minimum_billable_headcount
        """
        set_clock(DEFAULT_CLOCK)
        offering = create_published_offering()
        school = create_school()

        booking = validate_success(
            api.create_booking(
                create_booking_payload(
                    school["id"],
                    offering["id"],
                    start_utc=TEST_DEFAULTS["BOOKING_START_UTC"],
                    end_utc=TEST_DEFAULTS["BOOKING_END_UTC"],
                    student_count=student_count,
                    chaperone_count=chaperone_count,
                ),
                BC,
            ),
            201,
        )

        assert_booking(booking)
        assert booking["student_count"] == student_count
        assert booking["required_chaperones"] == expected_chaperones
        assert booking["provisional_gross_fee_cents"] == expected_gross_cents

    def test_rain_credit_is_taken_off_the_originally_booked_offering_s_gross(self, api):
        """PRD §3.8: "Step six applies the rain credit: when the booking carries a non-null `rain_diverted_to_offering_id`, the gross is multiplied by one minus a 20 percent credit and rounded half up to a whole cent."

        Design: Corner/calculations/rain_credit_is_applied_to_the_assembled_gross_after_the_selector_runs
        """
        scenario = setup_confirmed_booking(student_count=30, chaperone_count=3)
        alternate = _publish_rain_alternate(scenario["offering"]["id"])

        diverted = validate_success(
            api.rain_divert_booking(
                scenario["booking"]["id"],
                {"reason": "Thunderstorm warning through mid-afternoon"},
                BC,
            )
        )

        assert diverted["delivery_status"] == "RAIN_DIVERTED"
        assert diverted["rain_diverted_to_offering_id"] == alternate["id"]
        assert diverted["offering_id"] == scenario["offering"]["id"]
        assert diverted["provisional_gross_fee_cents"] == 26640
        assert diverted["net_due_cents"] == 26640


class TestOutreachTravelFee:
    def test_travel_fee_doubles_only_once_the_box_truck_manifest_is_loaded(self, api):
        """PRD §3.8: "The vehicle factor is 2.0 when an equipment manifest of this booking whose `status` is `LOADED`, `RETURNED` or `SHORTAGE_REPORTED` carries a `vehicle_class` of `BOX_TRUCK`, and 1.0 otherwise; manifests still sitting in `DRAFT` are excluded from that test, which is why loading a manifest re-prices the booking."

        Design: Corner/calculations/outreach_travel_fee_doubles_only_once_the_box_truck_manifest_is_loaded
        """
        scenario = setup_outreach_booking_with_manifest(
            total_weight_kg=300.0,
            kit_codes=("KIT-POND-A", "KIT-POND-B"),
            load=False,
        )
        assert scenario["booking"]["provisional_gross_fee_cents"] == 39488

        loaded = validate_success(
            api.advance_equipment_manifest(
                scenario["manifest"]["id"], {"action": "LOAD"}, BC
            )
        )
        assert loaded["status"] == "LOADED"
        assert loaded["vehicle_class"] == "BOX_TRUCK"

        repriced = refresh_booking(scenario["booking"]["id"])
        assert repriced["provisional_gross_fee_cents"] == 41675
        assert repriced["net_due_cents"] == 41675

    def test_vehicle_class_stays_a_van_at_exactly_the_threshold_weight(self, api):
        """PRD §3.9: "Loading is also the moment `vehicle_class` is decided: a manifest heavier than 250 kilograms requires a `BOX_TRUCK`, and one at or below that threshold travels in a `VAN` — the comparison is strictly greater-than, so a manifest weighing exactly 250 kilograms goes in a van."

        Design: Corner/calculations/vehicle_class_stays_a_van_at_exactly_the_threshold_weight
        """
        scenario = setup_outreach_booking_with_manifest(
            total_weight_kg=250.0, kit_codes=("KIT-A",), load=True
        )
        assert scenario["manifest"]["vehicle_class"] == "VAN"
        assert scenario["booking"]["provisional_gross_fee_cents"] == 39488

        heavier = validate_success(
            api.create_equipment_manifest(
                scenario["booking"]["id"],
                create_equipment_manifest_payload(
                    kit_codes=["KIT-B"], total_weight_kg=250.5
                ),
                BC,
            ),
            201,
        )
        loaded = validate_success(
            api.advance_equipment_manifest(heavier["id"], {"action": "LOAD"}, BC)
        )
        assert loaded["vehicle_class"] == "BOX_TRUCK"
        assert loaded["total_weight_kg"] == pytest.approx(250.5, abs=0.01)

        repriced = refresh_booking(scenario["booking"]["id"])
        assert repriced["provisional_gross_fee_cents"] == 41675


class TestAidAwardWaterfall:
    def test_scholarship_fills_first_and_transport_caps_at_the_mileage_entitlement(
        self, api
    ):
        """PRD §3.8: "The mileage entitlement is 260 cents per mile applied to **round-trip** distance — the school's `distance_miles` multiplied by two, then by 260, rounded half up to whole cents."

        Design: Corner/calculations/aid_award_fills_scholarship_first_then_caps_transport_at_the_mileage_entitlement
        """
        scenario = setup_booking_scenario(student_count=30, chaperone_count=3)
        fund = create_fund()
        teacher = make_teacher_contact_headers(scenario["school"]["id"])

        application = apply_for_aid(
            scenario["booking"]["id"],
            fund["id"],
            requested_scholarship_cents=28000,
            requested_transport_cents=9000,
            headers=teacher,
        )
        assert application["status"] == "SUBMITTED"

        decided = validate_success(
            api.review_aid_application(
                application["id"],
                {
                    "decision": "APPROVE",
                    "reviewer_note": "Transport trimmed to the mileage entitlement",
                },
                GO,
            )
        )
        assert decided["status"] == "PARTIALLY_APPROVED"
        assert decided["awarded_scholarship_cents"] == 28000
        assert decided["awarded_transport_cents"] == 6500

        booking = refresh_booking(scenario["booking"]["id"])
        assert booking["aid_amount_cents"] == 28000
        assert booking["transport_subsidy_cents"] == 6500
        assert booking["net_due_cents"] == 5300
        assert booking["funding_status"] == "AID_APPROVED"

        ledger = validate_success(api.get_scholarship_fund(fund["id"], GO))
        assert ledger["pending_cents"] == 0
        assert ledger["committed_cents"] == 34500
        assert ledger["transport_awarded_cents"] == 6500
        assert ledger["available_cents"] == 4965500


class TestLearningGainIndex:
    def test_diverted_fidelity_and_thin_alignment_penalty_both_multiply_in(self, api):
        """PRD §3.9: "Step five combines everything: six tenths of the normalised gain plus four tenths of the teacher composite, that sum multiplied by the fidelity factor and then by the alignment factor, the product clamped into the closed range 0 through 1, and finally rounded half up to two decimal places — the single rounding in the whole computation."

        Design: Corner/calculations/learning_gain_index_multiplies_the_diverted_fidelity_by_the_thin_alignment_penalty
        """
        scenario = setup_confirmed_booking(student_count=30, chaperone_count=3)
        offering = scenario["offering"]
        school = scenario["school"]
        educator_id = scenario["educator"]["id"]
        alternate = _publish_rain_alternate(offering["id"])

        diverted_booking = scenario["booking"]
        validate_success(
            api.rain_divert_booking(
                diverted_booking["id"], {"reason": "Lightning within ten miles"}, BC
            )
        )
        deliver_booking(diverted_booking["id"], 30, 3)

        straight_booking = create_booking(
            school["id"],
            offering["id"],
            start_utc=SECOND_DAY_START,
            end_utc=SECOND_DAY_END,
            student_count=30,
            chaperone_count=3,
        )
        assign_resources(straight_booking["id"], lead_educator_id=educator_id)
        confirm_booking(straight_booking["id"])
        deliver_booking(straight_booking["id"], 30, 3)

        teacher = make_teacher_contact_headers(school["id"])

        diverted_report = validate_success(
            api.create_evaluation_report(
                diverted_booking["id"],
                create_evaluation_report_payload(
                    teacher_score_standards_alignment=5,
                    teacher_score_logistics=4,
                    teacher_score_engagement=4,
                    student_pre_score_avg=8,
                    student_post_score_avg=15,
                ),
                teacher,
            ),
            201,
        )
        assert diverted_report["learning_gain_index"] == pytest.approx(0, abs=0.01)

        submitted_diverted = validate_success(
            api.submit_evaluation_report(diverted_report["id"], teacher)
        )
        assert submitted_diverted["status"] == "SUBMITTED"
        assert submitted_diverted["learning_gain_index"] == pytest.approx(
            0.51, abs=0.01
        )

        clamped_report = validate_success(
            api.create_evaluation_report(
                straight_booking["id"],
                create_evaluation_report_payload(
                    teacher_score_standards_alignment=5,
                    teacher_score_logistics=5,
                    teacher_score_engagement=5,
                    student_pre_score_avg=12,
                    student_post_score_avg=8,
                ),
                teacher,
            ),
            201,
        )
        submitted_clamped = validate_success(
            api.submit_evaluation_report(clamped_report["id"], teacher)
        )
        assert submitted_clamped["learning_gain_index"] == pytest.approx(0.36, abs=0.01)

        assert refresh_booking(diverted_booking["id"])[
            "rain_diverted_to_offering_id"
        ] == alternate["id"]
        assert refresh_booking(straight_booking["id"])["rain_diverted_to_offering_id"] is None


class TestFunderOutcomeRollup:
    def test_awarded_count_ignores_delivery_while_outcomes_wait_for_acceptance(
        self, api
    ):
        """PRD §3.9: "Reports in `DRAFT`, `SUBMITTED` or `RETURNED` are excluded, and a booking whose aid was approved but not yet delivered contributes to `awarded_application_count` while contributing nothing to the outcome figures."

        Design: Corner/calculations/funder_rollup_counts_awarded_aid_but_weights_only_accepted_evaluations
        """
        scenario = setup_booking_scenario(student_count=30, chaperone_count=3)
        offering = scenario["offering"]
        school = scenario["school"]
        delivered_booking = scenario["booking"]
        fund = create_fund()
        teacher = make_teacher_contact_headers(school["id"])

        disbursing_application = apply_for_aid(
            delivered_booking["id"],
            fund["id"],
            requested_scholarship_cents=20000,
            requested_transport_cents=0,
            headers=teacher,
        )
        approved = validate_success(
            api.review_aid_application(
                disbursing_application["id"], {"decision": "APPROVE"}, GO
            )
        )
        assert approved["status"] == "APPROVED"

        confirm_booking(delivered_booking["id"])
        deliver_booking(delivered_booking["id"], 30, 3)

        undelivered_booking = create_booking(
            school["id"],
            offering["id"],
            start_utc=SECOND_DAY_START,
            end_utc=SECOND_DAY_END,
            student_count=20,
            chaperone_count=2,
        )
        pending_application = apply_for_aid(
            undelivered_booking["id"],
            fund["id"],
            requested_scholarship_cents=5000,
            requested_transport_cents=0,
            headers=teacher,
        )
        second_approved = validate_success(
            api.review_aid_application(
                pending_application["id"], {"decision": "APPROVE"}, GO
            )
        )
        assert second_approved["status"] == "APPROVED"

        report = validate_success(
            api.create_evaluation_report(
                delivered_booking["id"],
                create_evaluation_report_payload(
                    teacher_score_standards_alignment=5,
                    teacher_score_logistics=4,
                    teacher_score_engagement=4,
                    student_pre_score_avg=8,
                    student_post_score_avg=15,
                ),
                teacher,
            ),
            201,
        )
        submitted = validate_success(api.submit_evaluation_report(report["id"], teacher))
        assert submitted["learning_gain_index"] == pytest.approx(0.64, abs=0.01)

        before = validate_success(api.get_fund_outcome_report(fund["id"], GO))
        assert before["fund_id"] == fund["id"]
        assert before["students_served_count"] == 0
        assert_three_decimal_string_value(
            before["weighted_learning_gain_index"], 0.000, "weighted_learning_gain_index"
        )
        assert_three_decimal_string_value(
            before["tier_1_student_share_pct"], 0.000, "tier_1_student_share_pct"
        )
        assert before["awarded_application_count"] == 2
        assert before["committed_cents"] == 5000
        assert before["disbursed_cents"] == 20000
        assert before["available_cents"] == 4975000

        accepted = validate_success(
            api.review_evaluation_report(report["id"], {"decision": "ACCEPT"}, ED)
        )
        assert accepted["status"] == "ACCEPTED"

        after = validate_success(api.get_fund_outcome_report(fund["id"], GO))
        assert after["fund_id"] == fund["id"]
        assert after["students_served_count"] == 30
        assert_three_decimal_string_value(
            after["weighted_learning_gain_index"], 0.640, "weighted_learning_gain_index"
        )
        assert_three_decimal_string_value(
            after["tier_1_student_share_pct"], 1.000, "tier_1_student_share_pct"
        )
        assert after["awarded_application_count"] == 2


class TestAnimalExposureCounters:
    def test_posture_turns_restricted_at_exactly_sixty_percent_of_the_weekly_cap(
        self, api
    ):
        """PRD §3.4: "Otherwise, if the projected total has reached or passed sixty percent of the ceiling — that is, `weekly_exposure_cap_minutes` multiplied by 0.60 and rounded half up to whole minutes — the posture is `RESTRICTED`."

        Design: Corner/calculations/welfare_posture_turns_restricted_at_exactly_sixty_percent_of_the_weekly_cap
        """
        scenario = setup_animal_booking_scenario(
            student_count=20,
            chaperone_count=2,
            animal_overrides={
                "contact_rule": "SUPERVISED_TOUCH",
                "weekly_exposure_cap_minutes": 200,
            },
            offering_overrides={"duration_minutes": 120, "public_contact_required": False},
            confirm=False,
        )
        animal_id = scenario["animal"]["id"]

        confirmed = confirm_booking(scenario["booking"]["id"])
        assert confirmed["delivery_status"] == "CONFIRMED"

        after_confirm = refresh_animal(animal_id)
        assert after_confirm["projected_exposure_minutes_7d"] == 120
        assert after_confirm["realized_exposure_minutes_7d"] == 0
        assert after_confirm["welfare_posture"] == "RESTRICTED"
        assert after_confirm["effective_contact_rule"] == "VIEW_ONLY"
        assert after_confirm["contact_rule"] == "SUPERVISED_TOUCH"

        deliver_booking(
            scenario["booking"]["id"], 20, 2, actual_contact_minutes=95
        )

        after_delivery = refresh_animal(animal_id)
        assert after_delivery["projected_exposure_minutes_7d"] == 0
        assert after_delivery["realized_exposure_minutes_7d"] == 95
        assert after_delivery["welfare_posture"] == "OPEN"
        assert after_delivery["effective_contact_rule"] == "SUPERVISED_TOUCH"


class TestSchoolStandingAndNoShowCharge:
    def test_first_strike_lands_on_probation_and_bills_the_flat_no_show_fee(self, api):
        """PRD §3.7: "This is reachable from `REQUESTED` and from `CONFIRMED` alike, and both branches set `delivery_status` to `NO_SHOW`, set `final_gross_fee_cents` and `net_due_cents` to the flat no-show fee of 7,500 cents, set `funding_status` to `WRITTEN_OFF`, set `resource_release_reason` to `NO_SHOW`, increment the school's `no_show_strikes` and recompute `SchoolPartner.status`."

        Design: Corner/calculations/first_no_show_puts_the_school_on_probation_and_bills_the_flat_fee
        """
        scenario = setup_school_with_strikes(strikes=1)
        no_show_booking = scenario["no_show_bookings"][0]

        assert no_show_booking["delivery_status"] == "NO_SHOW"
        assert no_show_booking["funding_status"] == "WRITTEN_OFF"
        assert no_show_booking["final_gross_fee_cents"] == 7500
        assert no_show_booking["net_due_cents"] == 7500
        assert no_show_booking["resource_release_reason"] == "NO_SHOW"
        assert no_show_booking["provisional_gross_fee_cents"] == 33300

        school = refresh_school(scenario["school"]["id"])
        assert school["status"] == "PROBATION"
        assert school["no_show_strikes"] == 1
        assert school["outstanding_balance_cents"] == 0


class TestCancelledBookingsAreOutsideEveryCounter:
    def test_cancelled_booking_frees_the_window_the_trail_and_the_weekly_load(self, api):
        """PRD §3.5: "`visitors_this_week` is the sum of `student_count` plus `chaperone_count` over the bookings on this segment whose `delivery_status` is `CONFIRMED`, `RAIN_DIVERTED` or `DELIVERED` and whose `start_utc` falls inside the ISO program week containing the logical clock."

        Design: Corner/calculations/trail_and_educator_counters_ignore_cancelled_bookings_in_the_same_window
        """
        scenario = setup_trail_booking_scenario(
            student_count=30,
            chaperone_count=3,
            trail_overrides={
                "capacity_persons": 100,
                "weekly_visitor_budget_persons": 300,
            },
        )
        trail_id = scenario["trail_segment"]["id"]
        educator_id = scenario["educator"]["id"]

        cancelled = validate_success(
            api.cancel_booking(
                scenario["booking"]["id"], {"reason": "District pulled the bus"}, BC
            )
        )
        assert cancelled["delivery_status"] == "CANCELLED"
        assert cancelled["resource_release_reason"] == "CANCELLED_BY_SCHOOL"

        replacement = create_booking(
            scenario["school"]["id"],
            scenario["offering"]["id"],
            start_utc=TEST_DEFAULTS["BOOKING_START_UTC"],
            end_utc=TEST_DEFAULTS["BOOKING_END_UTC"],
            student_count=30,
            chaperone_count=3,
        )
        assigned = assign_resources(
            replacement["id"],
            lead_educator_id=educator_id,
            trail_segment_id=trail_id,
        )
        assert assigned["lead_educator_id"] == educator_id

        confirmed = confirm_booking(replacement["id"])
        assert confirmed["delivery_status"] == "CONFIRMED"

        assert refresh_trail_segment(trail_id)["visitors_this_week"] == 33
        assert refresh_educator(educator_id)["delivery_load_minutes_this_week"] == 120
