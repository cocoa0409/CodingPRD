"""Automatic bed selection: filter the pool, then rank it on five keys in order.

Cohort and bed-type conditions decide which beds are candidates at all; only then
does the five-key ranking run, and its first key — how crowded the room already
is — outranks both the exact-fit bed type and the room number.
"""

from test_helpers import (
    BedStatus,
    BedType,
    LegalStatus,
    UnitPosture,
    assert_unit_availability,
    build_ward,
    place_admission,
    placed_admission,
    read_bed,
    read_unit,
    searched_admission,
    voluntary_case,
)

#: Two beds in room 501, a lone standard bed in 505, an observation bed in 506
#: and a seclusion bed in 509 that can never be a placement destination.
WARD_BEDS = (
    {"room_number": "501", "wing_code": "A", "bed_label": "A"},
    {"room_number": "501", "wing_code": "A", "bed_label": "B"},
    {"room_number": "505", "wing_code": "B", "bed_label": "A"},
    {
        "room_number": "506",
        "wing_code": "B",
        "bed_label": "A",
        "bed_type": BedType.LIGATURE_RESISTANT_OBSERVATION.value,
    },
    {
        "room_number": "509",
        "wing_code": "B",
        "bed_label": "A",
        "bed_type": BedType.SECLUSION.value,
    },
)


def _moderate_voluntary_case(api, roster, mrn, legal_name, age_years, gender):
    """A voluntary admission candidate whose acuity tier is MODERATE."""
    return voluntary_case(
        api,
        roster,
        mrn=mrn,
        legal_name=legal_name,
        age_years=age_years,
        gender_care_category=gender,
        danger_to_self=False,
        danger_to_others=True,
        grave_disability=True,
    )


def _ward_with_one_male_in_room_501(api, roster):
    """Stock the unit and occupy the first bed of room 501 with a male patient."""
    ward = build_ward(api, name="Ward 5 South", seclusion_room_count=1, bed_specs=WARD_BEDS)
    case = _moderate_voluntary_case(api, roster, "MRN-2367-S1", "Sol Ibarra", 45, "MALE")
    case["admission"] = placed_admission(
        api,
        roster,
        ward,
        case,
        requested_legal_status=LegalStatus.VOLUNTARY.value,
        bed_id=ward.beds[0]["id"],
    )
    return ward, case


def _auto_place(api, roster, ward, case):
    """Open, search and place an admission without naming a bed."""
    admission = searched_admission(
        api,
        roster,
        case["patient"]["id"],
        case["evaluation"]["id"],
        ward.id,
        LegalStatus.VOLUNTARY.value,
    )
    return place_admission(api, roster, admission["id"], ward.id)


class TestAutomaticBedSelection:
    """The candidate filter runs first, then the five ranking keys in order."""

    def test_cohort_and_bed_type_filters_remove_beds_before_ranking_runs(
        self, api, clock, roster
    ):
        """The free bed beside a male roommate and the seclusion bed are both unreachable.

        PRD 3.5: "A bed is a candidate only when it belongs to the requested
        unit, its `status` is exactly `AVAILABLE`, its `bed_type` is `STANDARD`
        or `LIGATURE_RESISTANT_OBSERVATION` — a `SECLUSION` bed is never a
        placement destination — and, when the admission's `acuity_tier` is
        `HIGH`, its `bed_type` is specifically `LIGATURE_RESISTANT_OBSERVATION`."

        Design: Difficulty/combinatorial_formula/bed_selector_cohort_filter_then_exact_fit_then_occupancy_rank
        """
        ward, _ = _ward_with_one_male_in_room_501(api, roster)
        female = _moderate_voluntary_case(
            api, roster, "MRN-2367-S2", "Sabine Wray", 29, "FEMALE"
        )

        placed = _auto_place(api, roster, ward, female)

        assert placed["bed_id"] != ward.beds[1]["id"]
        assert placed["bed_id"] != ward.beds[4]["id"]
        second_bed_of_room_501 = read_bed(api, ward.beds[1]["id"], ward.id)
        assert second_bed_of_room_501["status"] == BedStatus.AVAILABLE.value

    def test_exact_fit_bed_type_outranks_a_lower_room_number(self, api, clock, roster):
        """Between two empty rooms the observation bed in 506 beats the standard bed in 505.

        PRD 3.5: "First it fixes the exact-fit bed type for this admission:
        `LIGATURE_RESISTANT_OBSERVATION` when the `acuity_tier` is `HIGH` or
        `MODERATE`, and `STANDARD` when it is `LOW`."

        Design: Difficulty/combinatorial_formula/bed_selector_cohort_filter_then_exact_fit_then_occupancy_rank
        """
        ward, _ = _ward_with_one_male_in_room_501(api, roster)
        female = _moderate_voluntary_case(
            api, roster, "MRN-2367-S2", "Sabine Wray", 29, "FEMALE"
        )

        placed = _auto_place(api, roster, ward, female)

        assert placed["bed_id"] == ward.beds[3]["id"]

    def test_an_emptier_room_outranks_both_the_exact_fit_type_and_the_room_number(
        self, api, clock, roster
    ):
        """A second male goes to the empty room 505, not to the free bed beside his cohort.

        PRD 3.5: "Candidates are then ranked on five keys, compared in order,
        with the smallest winning: the number of current roommates in the bed's
        room, so emptier rooms come first; then whether the bed's `bed_type` is
        the exact-fit type, with exact fits ahead of the rest; then the bed's
        `room_number` in ascending lexicographic order; then the bed's
        `bed_label` in ascending lexicographic order; and finally the bed's
        `created_at`, earliest first."

        Design: Difficulty/combinatorial_formula/bed_selector_cohort_filter_then_exact_fit_then_occupancy_rank
        """
        ward, _ = _ward_with_one_male_in_room_501(api, roster)
        female = _moderate_voluntary_case(
            api, roster, "MRN-2367-S2", "Sabine Wray", 29, "FEMALE"
        )
        _auto_place(api, roster, ward, female)
        second_male = _moderate_voluntary_case(
            api, roster, "MRN-2367-S3", "Silas Roche", 52, "MALE"
        )

        placed = _auto_place(api, roster, ward, second_male)

        assert placed["bed_id"] == ward.beds[2]["id"]
        assert placed["bed_id"] != ward.beds[1]["id"]

    def test_three_placements_leave_the_unit_restricted_over_one_free_bed(
        self, api, clock, roster
    ):
        """The seclusion bed never counts, so four licensed beds carry a threshold of one.

        PRD 3.1: "Step one counts inventory from bed statuses alone, and it
        considers only beds of type `STANDARD` or `LIGATURE_RESISTANT_OBSERVATION`
        — a `SECLUSION` bed is never counted and therefore can never influence
        posture."

        Design: Difficulty/combinatorial_formula/bed_selector_cohort_filter_then_exact_fit_then_occupancy_rank
        """
        ward, _ = _ward_with_one_male_in_room_501(api, roster)
        female = _moderate_voluntary_case(
            api, roster, "MRN-2367-S2", "Sabine Wray", 29, "FEMALE"
        )
        _auto_place(api, roster, ward, female)
        second_male = _moderate_voluntary_case(
            api, roster, "MRN-2367-S3", "Silas Roche", 52, "MALE"
        )
        _auto_place(api, roster, ward, second_male)

        unit = read_unit(api, ward.id)
        assert_unit_availability(unit, licensed=4, raw_available=1, occupied=3)
        assert unit["posture"] == UnitPosture.RESTRICTED.value
        assert unit["effective_available_bed_count"] == 0
