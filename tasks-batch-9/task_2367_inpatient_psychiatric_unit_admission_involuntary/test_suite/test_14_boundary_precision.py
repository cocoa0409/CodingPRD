"""Two boundaries probed on both sides: integer tiers and a millisecond deadline.

The acuity tiers sit on inclusive lower bounds, so 6 and 7 differ and 11 and 12
differ. The follow-up guarantee sits on an inclusive upper bound, so an appointment
exactly at the deadline is good and one millisecond later is not.
"""

from test_helpers import (
    AcuityTier,
    ApiErrorId,
    DischargePlanStatus,
    EvaluationStatus,
    FOLLOW_UP_BASE_DAYS,
    LegalStatus,
    MINOR_FOLLOW_UP_DAY_CAP,
    RecommendedStatus,
    assert_error,
    assert_ok,
    build_ward,
    create_evaluation,
    create_patient,
    discharge_plan_payload,
    placed_admission,
    read_admission,
    signed_evaluation,
)

SOUTH_BEDS = (
    {"room_number": "901", "wing_code": "A", "bed_label": "A"},
    {"room_number": "902", "wing_code": "A", "bed_label": "A"},
    {"room_number": "903", "wing_code": "B", "bed_label": "A"},
)

ADULT_DEADLINE = "2026-09-17T08:00:00.000Z"
ADULT_ONE_MILLISECOND_LATE = "2026-09-17T08:00:00.001Z"
MINOR_DEADLINE = "2026-09-08T08:00:00.000Z"
MINOR_ONE_MILLISECOND_LATE = "2026-09-08T08:00:00.001Z"
ADULT_PROVIDER = "Eastside Community Mental Health"
MINOR_PROVIDER = "Adolescent Aftercare Clinic"


def _tier_boundary_patient(api, roster):
    """One adult with no admission history, so recency contributes nothing to any score."""
    return create_patient(
        api,
        mrn="MRN-2367-TB",
        legal_name="Tomas Bergqvist",
        age_years=46,
        gender_care_category="NONBINARY",
    )


def _draft_evaluation(api, roster, patient_id, **criteria):
    """Start one unsigned evaluation on the boundary patient."""
    return create_evaluation(api, roster.intake_headers, patient_id, **criteria)


def _placed_voluntary_admission(api, roster, ward, *, mrn, legal_name, age_years, gender, bed_id):
    """A voluntary agitation case, searched and placed in the named bed."""
    patient = create_patient(
        api,
        mrn=mrn,
        legal_name=legal_name,
        age_years=age_years,
        gender_care_category=gender,
    )
    evaluation = signed_evaluation(
        api,
        roster.intake_headers,
        patient["id"],
        danger_to_self=False,
        danger_to_others=True,
        grave_disability=True,
        capacity_present=True,
    )
    admission = placed_admission(
        api,
        roster,
        ward,
        {"patient": patient, "evaluation": evaluation},
        requested_legal_status=LegalStatus.VOLUNTARY.value,
        bed_id=bed_id,
    )
    return {"patient": patient, "evaluation": evaluation, "admission": admission}


def _submit_plan(api, roster, admission_id, appointment_at, provider_name):
    """Attempt one discharge plan, performed by the charge nurse."""
    return api.submit_discharge_plan(
        roster.charge_nurse_headers,
        admission_id,
        discharge_plan_payload(
            follow_up_appointment_at=appointment_at,
            follow_up_provider_name=provider_name,
        ),
    )


class TestAcuityTierThresholds:
    """Both inclusive lower bounds are probed at threshold minus one and at threshold."""

    def test_six_is_low_and_seven_is_moderate(self, api, clock, roster):
        """Grave disability with no capacity scores 6; danger to self with no capacity scores 7.

        PRD 3.2: "The `acuity_score` is then an integer sum of five contributions:
        4 points when `danger_to_self` is true, 5 points when `danger_to_others` is
        true, 3 points when `grave_disability` is true, 2 points for each recent
        prior admission counted but crediting no more than three of them, and 3
        points when `capacity_present` is false. The `acuity_tier` follows from the
        score with inclusive lower bounds: `HIGH` when the score is 12 or more,
        `MODERATE` when the score is at least 7 but below 12, and `LOW` for any
        lower score — so a score of exactly 12 is `HIGH` and a score of exactly 7 is
        `MODERATE`."

        Design: Difficulty/boundary_precision_check/acuity_tier_thresholds_at_six_seven_eleven_and_twelve
        """
        patient = _tier_boundary_patient(api, roster)

        six = _draft_evaluation(
            api,
            roster,
            patient["id"],
            danger_to_self=False,
            danger_to_others=False,
            grave_disability=True,
            capacity_present=False,
        )
        seven = _draft_evaluation(
            api,
            roster,
            patient["id"],
            danger_to_self=True,
            danger_to_others=False,
            grave_disability=False,
            capacity_present=False,
        )

        assert six["acuity_score"] == 6
        assert six["acuity_tier"] == AcuityTier.LOW.value
        assert seven["acuity_score"] == 7
        assert seven["acuity_tier"] == AcuityTier.MODERATE.value

    def test_eleven_is_moderate_and_twelve_is_high(self, api, clock, roster):
        """Others plus grave disability scores 11; both dangers score 12.

        PRD 3.2: "The `acuity_tier` follows from the score with inclusive lower
        bounds: `HIGH` when the score is 12 or more, `MODERATE` when the score is at
        least 7 but below 12, and `LOW` for any lower score — so a score of exactly
        12 is `HIGH` and a score of exactly 7 is `MODERATE`."

        Design: Difficulty/boundary_precision_check/acuity_tier_thresholds_at_six_seven_eleven_and_twelve
        """
        patient = _tier_boundary_patient(api, roster)

        eleven = _draft_evaluation(
            api,
            roster,
            patient["id"],
            danger_to_self=False,
            danger_to_others=True,
            grave_disability=True,
            capacity_present=False,
        )
        twelve = _draft_evaluation(
            api,
            roster,
            patient["id"],
            danger_to_self=True,
            danger_to_others=True,
            grave_disability=False,
            capacity_present=False,
        )

        assert eleven["acuity_score"] == 11
        assert eleven["acuity_tier"] == AcuityTier.MODERATE.value
        assert twelve["acuity_score"] == 12
        assert twelve["acuity_tier"] == AcuityTier.HIGH.value

    def test_the_tier_and_the_recommendation_are_independent_outputs(
        self, api, clock, roster
    ):
        """All three criteria with capacity intact still scores 12 but recommends voluntary.

        PRD 3.2: "Independently of the score, the `recommended_status` follows from
        the criteria: if none of the three statutory criteria is true it is
        `NO_ADMISSION`; if at least one is true and `capacity_present` is true it is
        `VOLUNTARY`; and if at least one is true while `capacity_present` is false it
        is `INVOLUNTARY_HOLD`."

        Design: Difficulty/boundary_precision_check/acuity_tier_thresholds_at_six_seven_eleven_and_twelve
        """
        patient = _tier_boundary_patient(api, roster)

        with_capacity = _draft_evaluation(
            api,
            roster,
            patient["id"],
            danger_to_self=True,
            danger_to_others=True,
            grave_disability=True,
            capacity_present=True,
        )
        without_capacity = _draft_evaluation(
            api,
            roster,
            patient["id"],
            danger_to_self=False,
            danger_to_others=False,
            grave_disability=True,
            capacity_present=False,
        )

        assert with_capacity["acuity_score"] == 12
        assert with_capacity["acuity_tier"] == AcuityTier.HIGH.value
        assert with_capacity["recommended_status"] == RecommendedStatus.VOLUNTARY.value
        assert (
            without_capacity["recommended_status"]
            == RecommendedStatus.INVOLUNTARY_HOLD.value
        )
        for evaluation in (with_capacity, without_capacity):
            assert evaluation["prior_admission_count_30d"] == 0
            assert evaluation["status"] == EvaluationStatus.DRAFT.value


class TestFollowUpGuaranteeBoundary:
    """The guarantee deadline is inclusive to the millisecond, and minors get less of it."""

    def test_an_adult_appointment_exactly_at_the_deadline_is_accepted(
        self, api, clock, roster
    ):
        """One millisecond past fourteen days is refused; the deadline instant itself is not.

        PRD 3.8: "The resulting figure is stored as `follow_up_guarantee_days`, and
        `follow_up_guarantee_deadline_at` is the logical clock **at plan
        submission** plus that many 24-hour days; the window is anchored to
        submission time and never to the later discharge instant. The plan is
        accepted only when `follow_up_appointment_at` is strictly after the current
        clock and at or before `follow_up_guarantee_deadline_at` — an appointment
        exactly at the deadline is accepted, one exactly at the current clock is not
        — and a violation of either bound is `ERR_FOLLOW_UP_WINDOW_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/follow_up_appointment_exactly_at_guarantee_deadline_is_accepted
        """
        ward = build_ward(api, name="Ward 9 South", bed_specs=SOUTH_BEDS)
        adult = _placed_voluntary_admission(
            api,
            roster,
            ward,
            mrn="MRN-2367-FA",
            legal_name="Fiona Aldarov",
            age_years=30,
            gender="FEMALE",
            bed_id=ward.beds[0]["id"],
        )

        too_late = _submit_plan(
            api,
            roster,
            adult["admission"]["id"],
            ADULT_ONE_MILLISECOND_LATE,
            ADULT_PROVIDER,
        )
        assert_error(too_late, ApiErrorId.FOLLOW_UP_WINDOW_EXCEEDED)

        accepted = assert_ok(
            _submit_plan(
                api, roster, adult["admission"]["id"], ADULT_DEADLINE, ADULT_PROVIDER
            )
        )

        assert (
            accepted["discharge_plan_status"]
            == DischargePlanStatus.APPOINTMENT_SECURED.value
        )
        assert (
            accepted["follow_up_guarantee_days"]
            == FOLLOW_UP_BASE_DAYS[LegalStatus.VOLUNTARY.value][AcuityTier.MODERATE.value]
        )
        assert accepted["follow_up_guarantee_deadline_at"] == ADULT_DEADLINE
        assert accepted["follow_up_appointment_at"] == ADULT_DEADLINE
        assert adult["patient"]["is_minor"] is False

    def test_the_minor_ceiling_moves_the_same_boundary_to_five_days(
        self, api, clock, roster
    ):
        """A voluntary minor gets five days, so the boundary sits nine days earlier.

        PRD 3.8: "For a patient whose `is_minor` is true the window is tightened to
        the lesser of that base figure and 5 days — so a voluntary minor gets 5
        days, not 14."

        Design: Difficulty/boundary_precision_check/follow_up_appointment_exactly_at_guarantee_deadline_is_accepted
        """
        ward = build_ward(api, name="Ward 9 South", bed_specs=SOUTH_BEDS)
        minor = _placed_voluntary_admission(
            api,
            roster,
            ward,
            mrn="MRN-2367-FM",
            legal_name="Finn Merrow",
            age_years=15,
            gender="MALE",
            bed_id=ward.beds[1]["id"],
        )
        assert minor["patient"]["is_minor"] is True

        too_late = _submit_plan(
            api,
            roster,
            minor["admission"]["id"],
            MINOR_ONE_MILLISECOND_LATE,
            MINOR_PROVIDER,
        )
        assert_error(too_late, ApiErrorId.FOLLOW_UP_WINDOW_EXCEEDED)

        accepted = assert_ok(
            _submit_plan(
                api, roster, minor["admission"]["id"], MINOR_DEADLINE, MINOR_PROVIDER
            )
        )

        assert accepted["follow_up_guarantee_days"] == MINOR_FOLLOW_UP_DAY_CAP
        assert accepted["follow_up_guarantee_deadline_at"] == MINOR_DEADLINE
        assert (
            accepted["follow_up_guarantee_days"]
            != FOLLOW_UP_BASE_DAYS[LegalStatus.VOLUNTARY.value][AcuityTier.MODERATE.value]
        )
        assert (
            read_admission(api, minor["admission"]["id"])["follow_up_appointment_at"]
            == MINOR_DEADLINE
        )
