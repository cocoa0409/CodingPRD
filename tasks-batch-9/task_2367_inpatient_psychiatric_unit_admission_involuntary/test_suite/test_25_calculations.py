"""Three computations that a naive implementation gets numerically close but wrong.

The recency count filters on both placement state and a half-open window; the
follow-up budget is read out of a table keyed by two fields; and both compliance
percentages are rounded half up to exactly one decimal place.
"""

from test_helpers import (
    AcuityTier,
    ApiErrorId,
    CheckType,
    DischargePlanStatus,
    FOLLOW_UP_BASE_DAYS,
    InterventionType,
    LegalStatus,
    MONITORING_INTERVAL_MINUTES,
    PlacementStatus,
    RecommendedStatus,
    RestraintStatus,
    active_hold_case,
    active_restraint,
    assert_error,
    assert_monitoring_compliance,
    assert_observation_quarter_hours,
    assert_ok,
    build_ward,
    complete_safety_search,
    create_admission,
    create_evaluation,
    create_patient,
    discharge_plan_payload,
    monitoring_check_payload,
    place_admission,
    read_admission,
    release_payload,
    request_discharge,
    set_clock,
    signed_evaluation,
    voluntary_case,
)

RECENCY_UNIT = "Ward 27 Recency"
RECENCY_BEDS = (
    {"room_number": "511", "wing_code": "A", "bed_label": "A"},
    {"room_number": "512", "wing_code": "A", "bed_label": "A"},
    {"room_number": "513", "wing_code": "A", "bed_label": "A"},
    {"room_number": "514", "wing_code": "A", "bed_label": "A"},
)
JUST_OUTSIDE_THE_WINDOW = "2026-08-04T07:59:59.999Z"
ON_THE_INCLUSIVE_EDGE = "2026-08-04T08:00:00Z"
ON_THE_INCLUSIVE_EDGE_INSTANT = "2026-08-04T08:00:00.000Z"
MID_WINDOW = "2026-08-20T08:00:00Z"
LATE_WINDOW = "2026-08-25T08:00:00Z"
EVALUATION_INSTANT = "2026-09-03T08:00:00.000Z"
PINNED_CLOCK = "2026-09-03T08:00:00Z"

GUARANTEE_UNIT = "Ward 28 Guarantee"
NO_BEDS = ()
EIGHT_DAYS_OUT = "2026-09-11T08:00:00Z"
EIGHT_DAYS_OUT_INSTANT = "2026-09-11T08:00:00.000Z"
HIGH_TIER_DEADLINE = "2026-09-10T08:00:00.000Z"
HIGH_TIER_DEADLINE_REQUEST = "2026-09-10T08:00:00Z"
MODERATE_TIER_DEADLINE = "2026-09-13T08:00:00.000Z"
PROVIDER = "Eastside Community Mental Health"

ROUNDING_UNIT = "Ward 29 Rounding"
MECHANICAL_MINUTES = 45
FIRST_CHECK_AT = "2026-09-03T08:02:00Z"
SECOND_CHECK_AT = "2026-09-03T08:05:00Z"
RELEASE_AT = "2026-09-03T08:45:00Z"
STARTED_AT = "2026-09-03T08:00:00.000Z"
RELEASED_AT = "2026-09-03T08:45:00.000Z"
REQUIRED_CHECKS = 3
SATISFIED_SLOTS = 1
LOGGED_CHECKS = 2
GRID_PCT = 33.3
RAW_PCT = 66.7
QUARTER_HOURS = 3


def _placed_prior(api, roster, ward, patient_id, evaluation_id, bed_id):
    """One completed prior episode: admitted, searched and placed at the current clock."""
    admission = create_admission(
        api,
        roster,
        patient_id,
        evaluation_id,
        ward.id,
        requested_legal_status=LegalStatus.VOLUNTARY.value,
    )
    complete_safety_search(api, roster, admission["id"])
    return place_admission(api, roster, admission["id"], ward.id, bed_id=bed_id)


def _involuntary_admission(api, roster, unit_id, *, mrn, legal_name, **criteria):
    """A certified emergency hold and the involuntary admission it authorizes."""
    case = active_hold_case(
        api,
        roster,
        mrn=mrn,
        legal_name=legal_name,
        age_years=39,
        gender_care_category="MALE",
        **criteria,
    )
    case["admission"] = create_admission(
        api,
        roster,
        case["patient"]["id"],
        case["evaluation"]["id"],
        unit_id,
        requested_legal_status=LegalStatus.INVOLUNTARY.value,
    )
    return case


def _submit_plan(api, roster, admission_id, appointment_at):
    """Attempt one discharge plan without asserting the outcome."""
    return api.submit_discharge_plan(
        roster.psychiatrist_headers,
        admission_id,
        discharge_plan_payload(
            follow_up_appointment_at=appointment_at,
            follow_up_provider_name=PROVIDER,
        ),
    )


class TestPriorAdmissionRecencyWindow:
    """Four priors sit around the window and only one of them counts."""

    def test_the_recency_count_filters_on_placement_state_and_a_half_open_window(
        self, api, clock, roster
    ):
        """The inclusive lower edge counts, its millisecond-earlier twin does not, and two states are ignored.

        PRD 3.2: "First the system counts the patient's recent history into
        `prior_admission_count_30d`: the number of that patient's admissions whose
        `placement_status` is `PLACED`, `DISCHARGE_READY` or `DISCHARGED`, and whose
        `admitted_at` is at or after the instant 30 days before
        `evaluation_started_at` and strictly before `evaluation_started_at` itself. The
        lower bound of that window is inclusive and the upper bound is exclusive;
        admissions in `PENDING_PLACEMENT` or `CANCELLED` are excluded entirely, because
        neither represents a completed episode of care."

        PRD 3.2: "The `acuity_score` is then an integer sum of five contributions: 4
        points when `danger_to_self` is true, 5 points when `danger_to_others` is true,
        3 points when `grave_disability` is true, 2 points for each recent prior
        admission counted but crediting no more than three of them, and 3 points when
        `capacity_present` is false."

        Design: Corner/calculations/prior_admission_recency_window_and_placement_state_filter
        """
        ward = build_ward(
            api,
            name=RECENCY_UNIT,
            gender_mixing_policy="MIXED_ALLOWED",
            seclusion_room_count=0,
            bed_specs=RECENCY_BEDS,
        )
        set_clock(api, JUST_OUTSIDE_THE_WINDOW)
        patient = create_patient(
            api,
            mrn="MRN-2367-RC",
            legal_name="Recency Case",
            age_years=46,
            gender_care_category="MALE",
        )
        baseline = signed_evaluation(
            api,
            roster.intake_headers,
            patient["id"],
            danger_to_self=False,
            danger_to_others=True,
            grave_disability=True,
            capacity_present=True,
        )
        too_early = _placed_prior(
            api, roster, ward, patient["id"], baseline["id"], ward.beds[0]["id"]
        )

        set_clock(api, ON_THE_INCLUSIVE_EDGE)
        on_the_edge = _placed_prior(
            api, roster, ward, patient["id"], baseline["id"], ward.beds[1]["id"]
        )

        set_clock(api, MID_WINDOW)
        never_placed = create_admission(
            api,
            roster,
            patient["id"],
            baseline["id"],
            ward.id,
            requested_legal_status=LegalStatus.VOLUNTARY.value,
        )

        set_clock(api, LATE_WINDOW)
        cancelled = create_admission(
            api,
            roster,
            patient["id"],
            baseline["id"],
            ward.id,
            requested_legal_status=LegalStatus.VOLUNTARY.value,
        )
        request = request_discharge(api, roster, cancelled["id"])
        assert_ok(
            api.respond_to_discharge_request(
                roster.psychiatrist_headers,
                request["id"],
                {
                    "decision": "GRANT",
                    "response_note": "Voluntary patient; request granted before placement.",
                },
            )
        )

        assert too_early["admitted_at"] == JUST_OUTSIDE_THE_WINDOW
        assert too_early["placement_status"] == PlacementStatus.PLACED.value
        assert on_the_edge["admitted_at"] == ON_THE_INCLUSIVE_EDGE_INSTANT
        assert on_the_edge["placement_status"] == PlacementStatus.PLACED.value
        assert (
            read_admission(api, never_placed["id"])["placement_status"]
            == PlacementStatus.PENDING_PLACEMENT.value
        )
        assert (
            read_admission(api, cancelled["id"])["placement_status"]
            == PlacementStatus.CANCELLED.value
        )

        set_clock(api, PINNED_CLOCK)
        fresh = create_evaluation(
            api,
            roster.intake_headers,
            patient["id"],
            danger_to_self=True,
            danger_to_others=False,
            grave_disability=False,
            capacity_present=False,
        )

        assert fresh["evaluation_started_at"] == EVALUATION_INSTANT
        assert fresh["prior_admission_count_30d"] == 1
        assert fresh["acuity_score"] == 9
        assert fresh["acuity_tier"] == AcuityTier.MODERATE.value
        assert fresh["recommended_status"] == RecommendedStatus.INVOLUNTARY_HOLD.value
        assert fresh["acuity_score"] != 13
        assert fresh["acuity_tier"] != AcuityTier.HIGH.value


class TestFollowUpBaseDaysTable:
    """Same legal status, different tier, and the same appointment date splits the verdict."""

    def test_the_guarantee_budget_is_selected_by_legal_status_and_acuity_tier(
        self, api, clock, roster
    ):
        """An appointment eight days out is refused for the high-tier patient and accepted for the moderate one.

        PRD 3.8: "The permitted lead time depends on how the patient was held and how
        sick they were: 7 days when the `legal_status` is `INVOLUNTARY` and the
        `acuity_tier` is `HIGH`, 10 days when the `legal_status` is `INVOLUNTARY` and
        the tier is `MODERATE` or `LOW`, and 14 days when the `legal_status` is
        `VOLUNTARY`."

        PRD 3.8: "The plan is accepted only when `follow_up_appointment_at` is strictly
        after the current clock and at or before `follow_up_guarantee_deadline_at` — an
        appointment exactly at the deadline is accepted, one exactly at the current
        clock is not — and a violation of either bound is
        `ERR_FOLLOW_UP_WINDOW_EXCEEDED`."

        Design: Corner/calculations/follow_up_base_days_table_by_legal_status_and_tier
        """
        ward = build_ward(
            api,
            name=GUARANTEE_UNIT,
            gender_mixing_policy="MIXED_ALLOWED",
            seclusion_room_count=0,
            bed_specs=NO_BEDS,
        )
        high = _involuntary_admission(
            api,
            roster,
            ward.id,
            mrn="MRN-2367-GH",
            legal_name="Guarantee High",
            danger_to_self=True,
            danger_to_others=True,
            grave_disability=False,
        )
        moderate = _involuntary_admission(
            api,
            roster,
            ward.id,
            mrn="MRN-2367-GM",
            legal_name="Guarantee Moderate",
            danger_to_self=True,
            danger_to_others=False,
            grave_disability=False,
        )
        assert high["admission"]["legal_status"] == LegalStatus.INVOLUNTARY.value
        assert high["admission"]["acuity_tier"] == AcuityTier.HIGH.value
        assert moderate["admission"]["legal_status"] == LegalStatus.INVOLUNTARY.value
        assert moderate["admission"]["acuity_tier"] == AcuityTier.MODERATE.value

        refused = _submit_plan(api, roster, high["admission"]["id"], EIGHT_DAYS_OUT)
        assert_error(refused, ApiErrorId.FOLLOW_UP_WINDOW_EXCEEDED)
        assert (
            read_admission(api, high["admission"]["id"])["discharge_plan_status"]
            == DischargePlanStatus.NOT_STARTED.value
        )

        high_plan = assert_ok(
            _submit_plan(
                api, roster, high["admission"]["id"], HIGH_TIER_DEADLINE_REQUEST
            )
        )
        assert (
            high_plan["follow_up_guarantee_days"]
            == FOLLOW_UP_BASE_DAYS[LegalStatus.INVOLUNTARY.value][
                AcuityTier.HIGH.value
            ]
        )
        assert high_plan["follow_up_guarantee_deadline_at"] == HIGH_TIER_DEADLINE
        assert high_plan["follow_up_appointment_at"] == HIGH_TIER_DEADLINE
        assert (
            high_plan["discharge_plan_status"]
            == DischargePlanStatus.APPOINTMENT_SECURED.value
        )

        moderate_plan = assert_ok(
            _submit_plan(api, roster, moderate["admission"]["id"], EIGHT_DAYS_OUT)
        )
        assert (
            moderate_plan["follow_up_guarantee_days"]
            == FOLLOW_UP_BASE_DAYS[LegalStatus.INVOLUNTARY.value][
                AcuityTier.MODERATE.value
            ]
        )
        assert moderate_plan["follow_up_guarantee_deadline_at"] == MODERATE_TIER_DEADLINE
        assert moderate_plan["follow_up_appointment_at"] == EIGHT_DAYS_OUT_INSTANT
        assert (
            moderate_plan["discharge_plan_status"]
            == DischargePlanStatus.APPOINTMENT_SECURED.value
        )
        assert high["patient"]["is_minor"] is False
        assert moderate["patient"]["is_minor"] is False


class TestCompliancePercentageRounding:
    """One episode, three slots, two clustered entries and two differently rounded figures."""

    def test_both_percentages_are_rounded_half_up_to_one_decimal_place(
        self, api, clock, roster
    ):
        """One satisfied slot of three reads 33.3 while two raw entries of three read 66.7.

        PRD 3.6: "`grid_satisfied_slot_count` is the number of those slots holding at
        least one log entry whose `recorded_at` falls inside the slot, and
        `grid_compliance_pct` is 100 multiplied by `grid_satisfied_slot_count`, divided
        by `required_check_count`, rounded half up to one decimal place."

        PRD 3.6: "The raw measure ignores slots entirely: `raw_compliance_pct` is 100
        multiplied by the lesser of `required_check_count` and the number of entries in
        `monitoring_check_log`, divided by `required_check_count`, rounded half up to
        one decimal place."

        PRD 3.6: "`observation_staff_quarter_hours` is the sum, over every episode of
        that admission whose `status` is `RELEASED`, `DEBRIEFED` or
        `EXPIRED_UNAUTHORIZED`, of that episode's `actual_duration_minutes` divided by
        15 and rounded up to the next whole number."

        Design: Corner/calculations/compliance_percentages_rounded_to_one_decimal_half_up
        """
        ward = build_ward(
            api,
            name=ROUNDING_UNIT,
            gender_mixing_policy="MIXED_ALLOWED",
            seclusion_room_count=0,
            bed_specs=NO_BEDS,
        )
        case = voluntary_case(
            api,
            roster,
            mrn="MRN-2367-RD",
            legal_name="Rounding Case",
            age_years=42,
            gender_care_category="FEMALE",
            danger_to_self=False,
            danger_to_others=True,
            grave_disability=True,
        )
        admission = create_admission(
            api,
            roster,
            case["patient"]["id"],
            case["evaluation"]["id"],
            ward.id,
            requested_legal_status=LegalStatus.VOLUNTARY.value,
        )
        episode = active_restraint(
            api,
            roster,
            admission["id"],
            InterventionType.MECHANICAL_RESTRAINT.value,
            MECHANICAL_MINUTES,
        )
        assert episode["started_at"] == STARTED_AT
        assert (
            episode["monitoring_interval_minutes"]
            == MONITORING_INTERVAL_MINUTES[
                InterventionType.MECHANICAL_RESTRAINT.value
            ]
        )

        for moment, check_type in (
            (FIRST_CHECK_AT, CheckType.CIRCULATION.value),
            (SECOND_CHECK_AT, CheckType.HYDRATION_OFFERED.value),
        ):
            set_clock(api, moment)
            assert_ok(
                api.add_monitoring_check(
                    roster.charge_nurse_headers,
                    episode["id"],
                    monitoring_check_payload(check_type=check_type),
                )
            )

        set_clock(api, RELEASE_AT)
        released = assert_ok(
            api.release_restraint(
                roster.charge_nurse_headers, episode["id"], release_payload()
            )
        )

        assert released["status"] == RestraintStatus.RELEASED.value
        assert released["released_at"] == RELEASED_AT
        assert released["actual_duration_minutes"] == MECHANICAL_MINUTES
        assert len(released["monitoring_check_log"]) == LOGGED_CHECKS
        assert_monitoring_compliance(
            released,
            required=REQUIRED_CHECKS,
            grid_satisfied=SATISFIED_SLOTS,
            logged=LOGGED_CHECKS,
        )
        assert released["grid_compliance_pct"] == GRID_PCT
        assert released["raw_compliance_pct"] == RAW_PCT

        after = read_admission(api, admission["id"])
        assert_observation_quarter_hours(after, [MECHANICAL_MINUTES])
        assert after["observation_staff_quarter_hours"] == QUARTER_HOURS
