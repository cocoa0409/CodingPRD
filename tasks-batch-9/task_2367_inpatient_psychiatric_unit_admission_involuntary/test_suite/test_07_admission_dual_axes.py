"""An admission's legal axis and placement axis never move each other.

The same admission is walked through a hold certification, a safety search, a
placement and a voluntary conversion. Each step moves one axis and leaves the
other exactly where it stood.
"""

from test_helpers import (
    LegalStatus,
    PlacementStatus,
    SafetySearchStatus,
    SearchType,
    assert_axes,
    assert_ok,
    certification_payload,
    complete_safety_search,
    conversion_payload,
    create_admission,
    create_hold,
    create_patient,
    determine_capacity,
    place_admission,
    read_admission,
    signed_evaluation,
)


def _voluntary_admission_and_an_uncertified_hold(api, roster, ward):
    """One patient with a voluntary admission pending placement and a fresh hold."""
    patient = create_patient(
        api,
        mrn="MRN-2367-AX",
        legal_name="Ada Xiong",
        age_years=38,
        gender_care_category="FEMALE",
    )
    voluntary_evaluation = signed_evaluation(
        api,
        roster.intake_headers,
        patient["id"],
        danger_to_self=False,
        danger_to_others=True,
        grave_disability=True,
        capacity_present=True,
    )
    admission = create_admission(
        api,
        roster,
        patient["id"],
        voluntary_evaluation["id"],
        ward.id,
        LegalStatus.VOLUNTARY.value,
    )
    hold_evaluation = signed_evaluation(
        api,
        roster.intake_headers,
        patient["id"],
        danger_to_self=True,
        capacity_present=False,
    )
    hold = create_hold(
        api, roster.intake_headers, patient["id"], hold_evaluation["id"]
    )
    return {"patient": patient, "admission": admission, "hold": hold}


class TestAdmissionParallelAxes:
    """Two axes, four steps, and no implicit coupling between them."""

    def test_certification_flips_the_legal_axis_and_leaves_placement_alone(
        self, api, clock, roster, ward
    ):
        """A voluntary admission awaiting a bed becomes involuntary without being placed.

        PRD 3.3: "The placement axis of those admissions is untouched — the two
        axes move independently, always."

        Design: Difficulty/non_linear_state_machine/admission_parallel_axes_evolve_independently
        """
        case = _voluntary_admission_and_an_uncertified_hold(api, roster, ward)
        assert_axes(
            case["admission"],
            legal_status=LegalStatus.VOLUNTARY.value,
            placement_status=PlacementStatus.PENDING_PLACEMENT.value,
        )

        assert_ok(
            api.certify_hold(
                roster.psychiatrist_headers,
                case["hold"]["id"],
                certification_payload(),
            )
        )

        admission = read_admission(api, case["admission"]["id"])
        assert_axes(
            admission,
            legal_status=LegalStatus.INVOLUNTARY.value,
            placement_status=PlacementStatus.PENDING_PLACEMENT.value,
        )
        assert admission["bed_id"] is None
        assert admission["placed_at"] is None

    def test_placement_advances_only_the_placement_axis(
        self, api, clock, roster, ward
    ):
        """The search and the placement carry the patient into a bed at the same legal status.

        PRD 3.5: "A successful placement sets `bed_id` to the selected bed, stamps
        `placed_at` from the logical clock, and advances the placement axis
        `PENDING_PLACEMENT → PLACED` while leaving `legal_status` exactly as it
        was."

        Design: Difficulty/non_linear_state_machine/admission_parallel_axes_evolve_independently
        """
        case = _voluntary_admission_and_an_uncertified_hold(api, roster, ward)
        assert_ok(
            api.certify_hold(
                roster.psychiatrist_headers,
                case["hold"]["id"],
                certification_payload(),
            )
        )

        searched = complete_safety_search(
            api,
            roster,
            case["admission"]["id"],
            search_type=SearchType.FULL_BODY_WITH_CONSENT.value,
            items_secured=3,
            contraband_found=True,
        )
        assert searched["safety_search_status"] == SafetySearchStatus.COMPLETED.value
        assert_axes(
            searched,
            legal_status=LegalStatus.INVOLUNTARY.value,
            placement_status=PlacementStatus.PENDING_PLACEMENT.value,
        )

        placed = place_admission(
            api, roster, case["admission"]["id"], ward.id, bed_id=ward.beds[0]["id"]
        )
        assert_axes(
            placed,
            legal_status=LegalStatus.INVOLUNTARY.value,
            placement_status=PlacementStatus.PLACED.value,
        )
        assert placed["bed_id"] == ward.beds[0]["id"]

    def test_voluntary_conversion_never_touches_the_placement_axis(
        self, api, clock, roster, ward
    ):
        """The patient stays in the same bed while the legal axis flips back.

        PRD 3.5: "It flips `legal_status` `INVOLUNTARY → VOLUNTARY` and closes the
        hold as described in §3.3, and it never touches the placement axis."

        Design: Difficulty/non_linear_state_machine/admission_parallel_axes_evolve_independently
        """
        case = _voluntary_admission_and_an_uncertified_hold(api, roster, ward)
        assert_ok(
            api.certify_hold(
                roster.psychiatrist_headers,
                case["hold"]["id"],
                certification_payload(),
            )
        )
        complete_safety_search(
            api,
            roster,
            case["admission"]["id"],
            search_type=SearchType.FULL_BODY_WITH_CONSENT.value,
            items_secured=3,
            contraband_found=True,
        )
        place_admission(
            api, roster, case["admission"]["id"], ward.id, bed_id=ward.beds[0]["id"]
        )
        determine_capacity(api, roster, case["admission"]["id"], True)

        converted = assert_ok(
            api.convert_admission_to_voluntary(
                roster.psychiatrist_headers,
                case["admission"]["id"],
                conversion_payload(),
            )
        )

        assert_axes(
            converted,
            legal_status=LegalStatus.VOLUNTARY.value,
            placement_status=PlacementStatus.PLACED.value,
        )
        assert converted["bed_id"] == ward.beds[0]["id"]
