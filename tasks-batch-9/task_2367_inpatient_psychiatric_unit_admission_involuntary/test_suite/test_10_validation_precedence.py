"""Which error a client sees when two guards are violated by the same request.

Both scenarios break two rules at once. The reported error is the earlier one in
the fixed order, and the later violation only becomes visible once the earlier one
is repaired.
"""

from test_helpers import (
    ApiErrorId,
    COMPLIANCE_OFFICER_HEADERS,
    LegalStatus,
    SearchType,
    active_hold_case,
    assert_error,
    assert_first_failing_check,
    assert_page,
    build_ward,
    complete_safety_search,
    create_admission,
    create_hold,
    involuntary_case,
    petition_payload,
    placement_payload,
    read_hold,
    set_clock,
    unit_version,
    voluntary_case,
    voluntary_placed_admission,
)

WEST_BEDS = (
    {"room_number": "801", "wing_code": "A", "bed_label": "A"},
    {"room_number": "801", "wing_code": "A", "bed_label": "B"},
    {"room_number": "802", "wing_code": "B", "bed_label": "A"},
)

FILING_DEADLINE = "2026-09-08T09:00:00.000Z"
AFTER_THE_DEADLINE = "2026-09-09T10:00:00Z"


def _male_roommate_and_an_unsearched_female_admission(api, roster):
    """Room 801 holds a male patient; a female admission is opened but not searched."""
    ward = build_ward(
        api, name="Ward 8 West", seclusion_room_count=0, bed_specs=WEST_BEDS
    )
    voluntary_placed_admission(
        api,
        roster,
        ward,
        mrn="MRN-2367-M1",
        legal_name="Malik Osei",
        age_years=39,
        gender_care_category="MALE",
        bed_id=ward.beds[0]["id"],
    )
    incoming = voluntary_case(
        api,
        roster,
        mrn="MRN-2367-F1",
        legal_name="Fern Adeyemi",
        age_years=42,
        gender_care_category="FEMALE",
    )
    incoming["admission"] = create_admission(
        api,
        roster,
        incoming["patient"]["id"],
        incoming["evaluation"]["id"],
        ward.id,
        LegalStatus.VOLUNTARY.value,
    )
    return ward, incoming


class TestPlacementCheckOrder:
    """The safety search is settled before any bed is examined."""

    def test_the_safety_search_check_fires_before_the_room_cohort_check(
        self, api, clock, roster
    ):
        """A bed that also breaks the cohort rule still reports the incomplete search.

        PRD 2.9: "Checks are evaluated in the following fixed order, and the first
        failing check terminates the request."

        Design: Difficulty/priority_pair_validation_conflict/place_safety_search_precedes_room_cohort_check
        """
        ward, incoming = _male_roommate_and_an_unsearched_female_admission(api, roster)
        pinned_version = unit_version(api, ward.id)

        refusal = api.place_admission(
            roster.charge_nurse_headers,
            incoming["admission"]["id"],
            placement_payload(
                unit_id=ward.id,
                expected_unit_version=pinned_version,
                bed_id=ward.beds[1]["id"],
            ),
        )

        assert_first_failing_check(
            refusal,
            ApiErrorId.SAFETY_SEARCH_INCOMPLETE,
            [ApiErrorId.ROOM_COHORT_VIOLATION],
        )
        assert unit_version(api, ward.id) == pinned_version

    def test_the_cohort_violation_surfaces_only_once_the_search_is_complete(
        self, api, clock, roster
    ):
        """Completing the search reveals the second violation and still changes no unit.

        PRD 3.5: "The room cohort rule reads the unit's `gender_mixing_policy`:
        under `MIXED_ALLOWED` it always passes; under `SEPARATE_BY_ROOM` every
        roommate — meaning every admission in `PLACED` whose bed sits in the same
        unit and the same `room_number` — must have a patient whose
        `gender_care_category` matches the incoming patient's; under
        `SEPARATE_BY_WING` the same equality must hold across every wingmate,
        meaning every `PLACED` admission whose bed shares the `wing_code`."

        Design: Difficulty/priority_pair_validation_conflict/place_safety_search_precedes_room_cohort_check
        """
        ward, incoming = _male_roommate_and_an_unsearched_female_admission(api, roster)
        pinned_version = unit_version(api, ward.id)
        complete_safety_search(
            api,
            roster,
            incoming["admission"]["id"],
            search_type=SearchType.WANDED.value,
            items_secured=1,
        )

        refusal = api.place_admission(
            roster.charge_nurse_headers,
            incoming["admission"]["id"],
            placement_payload(
                unit_id=ward.id,
                expected_unit_version=pinned_version,
                bed_id=ward.beds[1]["id"],
            ),
        )

        assert_error(refusal, ApiErrorId.ROOM_COHORT_VIOLATION)
        assert unit_version(api, ward.id) == pinned_version


class TestPetitionCheckOrder:
    """The hold's state is settled before the filing window is consulted."""

    def test_the_hold_state_check_fires_before_the_filing_window_check(
        self, api, clock, roster
    ):
        """An uncertified hold past its filing deadline reports the state error, not the window.

        PRD 2.9: "Authentication precedes authorization, authorization precedes
        schema validation, schema validation precedes existence resolution,
        existence resolution precedes version guards, version guards precede state
        checks, and state checks precede the clinical, temporal and capacity
        rules."

        Design: Difficulty/priority_pair_validation_conflict/petition_hold_state_precedes_filing_window
        """
        case = involuntary_case(
            api,
            roster,
            mrn="MRN-2367-W1",
            legal_name="Wren Halloran",
            age_years=28,
            gender_care_category="MALE",
        )
        hold = create_hold(
            api, roster.intake_headers, case["patient"]["id"], case["evaluation"]["id"]
        )
        assert read_hold(api, hold["id"])["petition_filing_deadline_at"] == FILING_DEADLINE
        set_clock(api, AFTER_THE_DEADLINE)

        refusal = api.create_petition(
            roster.psychiatrist_headers, petition_payload(hold_id=hold["id"])
        )

        assert_first_failing_check(
            refusal,
            ApiErrorId.HOLD_NOT_ACTIVE,
            [ApiErrorId.PETITION_WINDOW_CLOSED],
        )
        assert_page(api.list_petitions(COMPLIANCE_OFFICER_HEADERS, hold_id=hold["id"]), 0)

    def test_an_active_hold_past_its_filing_deadline_reports_the_window_error(
        self, api, clock, roster
    ):
        """With the state check satisfied the temporal check is what refuses the filing.

        PRD 3.4: "Filing requires the target hold to be `ACTIVE` — otherwise
        `ERR_HOLD_NOT_ACTIVE` — requires that no other petition for that hold is
        already in `FILED`, `HEARING_SCHEDULED` or `CONTINUED`, which is
        `ERR_PETITION_PENDING`, and must arrive at or before the hold's
        `petition_filing_deadline_at`; a later filing is refused with
        `ERR_PETITION_WINDOW_CLOSED`."

        Design: Difficulty/priority_pair_validation_conflict/petition_hold_state_precedes_filing_window
        """
        case = active_hold_case(
            api,
            roster,
            mrn="MRN-2367-W2",
            legal_name="Winona Sarr",
            age_years=55,
            gender_care_category="FEMALE",
        )
        assert (
            read_hold(api, case["hold"]["id"])["petition_filing_deadline_at"]
            == FILING_DEADLINE
        )
        set_clock(api, AFTER_THE_DEADLINE)

        refusal = api.create_petition(
            roster.psychiatrist_headers, petition_payload(hold_id=case["hold"]["id"])
        )

        assert_error(refusal, ApiErrorId.PETITION_WINDOW_CLOSED)
        assert_page(
            api.list_petitions(COMPLIANCE_OFFICER_HEADERS, hold_id=case["hold"]["id"]), 0
        )
