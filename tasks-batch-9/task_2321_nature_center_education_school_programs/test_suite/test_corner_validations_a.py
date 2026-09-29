"""Corner cases for the validation battery of the Nature Center Education API.

Each test drives one rule stated in the PRD to its boundary through
PRD-declared endpoints only, starting from an empty database.
"""

import pytest

from test_helpers import (
    DEFAULT_CLOCK,
    ApiErrorId,
    assign_resources,
    assign_resources_payload,
    attach_alignments,
    attach_materials,
    create_booking,
    create_booking_payload,
    create_cleared_educator,
    create_draft_offering,
    create_onboarding_educator,
    create_permit_payload,
    create_permitted_animal,
    create_published_offering,
    create_school,
    create_standard_alignment_payload,
    create_trail_segment,
    refresh_animal,
    refresh_booking,
    refresh_educator,
    refresh_offering,
    refresh_trail_segment,
    set_clock,
    setup_animal_booking_scenario,
    setup_booking_scenario,
    setup_trail_at_weekly_visitors,
    validate_error,
    validate_success,
)

BOOKING_START = "2026-09-29T14:00:00Z"
BOOKING_END = "2026-09-29T16:00:00Z"


# ======================================================================
# Local composite setups (no helper in the shared package builds these)
# ======================================================================

def _published_offering_and_school(**offering_overrides) -> tuple:
    """A PUBLISHED offering plus one ACTIVE school partner, clock pinned."""
    set_clock(DEFAULT_CLOCK)
    offering = create_published_offering(**offering_overrides)
    school = create_school()
    return offering, school


def _booking_needing_an_animal(handling_tier_required: str = "TIER_2") -> dict:
    """A REQUESTED booking on an offering that needs a live animal, nothing assigned."""
    offering, school = _published_offering_and_school(
        requires_live_animal=True, slug_prefix="raptor"
    )
    bundle = create_permitted_animal(handling_tier_required=handling_tier_required)
    booking = create_booking(
        school["id"], offering["id"], start_utc=BOOKING_START, end_utc=BOOKING_END
    )
    return {
        "offering": offering,
        "school": school,
        "permit": bundle["permit"],
        "animal": bundle["animal"],
        "booking": booking,
    }


def _booking_needing_a_sensitive_trail() -> dict:
    """A REQUESTED booking on an offering that needs a trail, plus a HIGH-sensitivity
    segment with capacity 60 and a 300-person weekly budget."""
    offering, school = _published_offering_and_school(
        requires_trail_segment=True, slug_prefix="bog", title="Bog Boardwalk Study"
    )
    trail = create_trail_segment(
        name="Bog Boardwalk",
        capacity_persons=60,
        habitat_sensitivity="HIGH",
        weekly_visitor_budget_persons=300,
    )
    return {"offering": offering, "school": school, "trail_segment": trail}


# ======================================================================
# Interval ordering on booking and permit creation
# ======================================================================

class TestIntervalOrdering:
    def test_zero_length_booking_window_is_rejected(
        self, api, booking_coordinator_headers
    ):
        """PRD §3.6: "The interval must be properly ordered, with `end_utc` strictly after `start_utc`, or the create fails with `ERR_INVALID_TIME_RANGE`."

        Design: Corner/validations/interval_fields_must_be_strictly_ordered_or_the_write_is_rejected
        """
        offering, school = _published_offering_and_school()
        response = api.create_booking(
            create_booking_payload(
                school["id"],
                offering["id"],
                start_utc=BOOKING_START,
                end_utc=BOOKING_START,
                student_count=30,
                chaperone_count=3,
            ),
            booking_coordinator_headers,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_TIME_RANGE.value)

    def test_permit_validity_window_ending_before_it_starts_is_rejected(
        self, api, stewardship_manager_headers
    ):
        """PRD §3.4: "A `StewardshipManager` records a permit with the issuing `agency` — `USFWS`, `STATE_DNR` or `USDA` — the `permit_number` as issued, and the `valid_from` and `valid_to` instants bounding the authorisation; `valid_to` must fall strictly after `valid_from` or the create is rejected with `ERR_INVALID_TIME_RANGE`."

        Design: Corner/validations/interval_fields_must_be_strictly_ordered_or_the_write_is_rejected
        """
        set_clock(DEFAULT_CLOCK)
        response = api.create_permit(
            create_permit_payload(
                permit_number="MB-2026-400",
                valid_from="2027-01-01T00:00:00Z",
                valid_to="2026-06-01T00:00:00Z",
            ),
            stewardship_manager_headers,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_TIME_RANGE.value)

    def test_a_strictly_increasing_booking_window_is_accepted(
        self, api, booking_coordinator_headers
    ):
        """PRD §2.9: "Interval fields are correctly ordered: a booking's `end_utc` is strictly after its `start_utc`, and a permit's `valid_to` is strictly after its `valid_from` — otherwise `ERR_INVALID_TIME_RANGE` (422). Applies to booking creation and permit creation."

        Design: Corner/validations/interval_fields_must_be_strictly_ordered_or_the_write_is_rejected
        """
        offering, school = _published_offering_and_school()
        response = api.create_booking(
            create_booking_payload(
                school["id"],
                offering["id"],
                start_utc=BOOKING_START,
                end_utc=BOOKING_END,
                student_count=30,
                chaperone_count=3,
            ),
            booking_coordinator_headers,
        )
        booking = validate_success(response, expected_status=201)
        assert booking["delivery_status"] == "REQUESTED"
        assert booking["end_utc"].startswith("2026-09-29T16:00:00")


# ======================================================================
# Track-dependent training fields
# ======================================================================

class TestTrainingTrackFields:
    @pytest.mark.parametrize(
        "payload",
        [
            {"track": "CURRICULUM"},
            {"track": "CURRICULUM", "grade_band": "G3_5", "handling_tier": "TIER_1"},
            {"track": "LIVE_ANIMAL_HANDLING", "grade_band": "G3_5"},
        ],
        ids=[
            "curriculum_without_grade_band",
            "curriculum_carrying_a_handling_tier",
            "handling_carrying_a_grade_band",
        ],
    )
    def test_enrolment_fields_that_contradict_the_track_are_rejected(
        self, api, curriculum_specialist_headers, payload
    ):
        """PRD §2.9: "Track-dependent training fields agree with the declared `track`, and a passing assessment carries a `score` — otherwise `ERR_TRACK_FIELD_MISMATCH` (422). Applies to enrolling an educator in a training track and to recording an assessment."

        Design: Corner/validations/training_records_whose_fields_contradict_the_track_are_rejected
        """
        set_clock(DEFAULT_CLOCK)
        educator = create_onboarding_educator()
        response = api.create_training_record(
            educator["id"], payload, curriculum_specialist_headers
        )
        validate_error(response, ApiErrorId.ERR_TRACK_FIELD_MISMATCH.value)

    def test_a_handling_enrolment_carrying_only_its_tier_is_accepted(
        self, api, curriculum_specialist_headers
    ):
        """PRD §3.3: "Enrolment records the `educator_id`, a `track` of either `CURRICULUM` or `LIVE_ANIMAL_HANDLING`, and exactly one track-dependent field: a `grade_band` is required for a `CURRICULUM` enrolment and must be absent for a handling enrolment, while a `handling_tier` of `TIER_1` or `TIER_2` is required for a `LIVE_ANIMAL_HANDLING` enrolment and must be absent for a curriculum enrolment."

        Design: Corner/validations/training_records_whose_fields_contradict_the_track_are_rejected
        """
        set_clock(DEFAULT_CLOCK)
        educator = create_onboarding_educator()
        response = api.create_training_record(
            educator["id"],
            {"track": "LIVE_ANIMAL_HANDLING", "handling_tier": "TIER_2"},
            curriculum_specialist_headers,
        )
        record = validate_success(response, expected_status=201)
        assert record["status"] == "ENROLLED"
        assert record["handling_tier"] == "TIER_2"
        assert record.get("grade_band") is None


# ======================================================================
# The offering-published gate on booking creation
# ======================================================================

class TestOfferingPublishedGate:
    def test_a_draft_offering_cannot_be_booked_until_it_is_published(
        self,
        api,
        booking_coordinator_headers,
        curriculum_specialist_headers,
        education_director_headers,
    ):
        """PRD §2.9: "The referenced program offering is `PUBLISHED` — otherwise `ERR_OFFERING_NOT_PUBLISHED` (409). Applies to booking creation and booking confirmation."

        Design: Corner/validations/bookings_against_an_unpublished_offering_are_rejected
        """
        set_clock(DEFAULT_CLOCK)
        offering = create_draft_offering()
        attach_alignments(offering["id"])
        attach_materials(offering["id"])
        school = create_school()
        payload = create_booking_payload(
            school["id"],
            offering["id"],
            start_utc=BOOKING_START,
            end_utc=BOOKING_END,
            student_count=30,
            chaperone_count=3,
        )

        validate_error(
            api.create_booking(payload, booking_coordinator_headers),
            ApiErrorId.ERR_OFFERING_NOT_PUBLISHED.value,
        )

        under_review = validate_success(
            api.submit_offering_for_review(
                offering["id"], curriculum_specialist_headers
            )
        )
        assert under_review["status"] == "UNDER_REVIEW"
        published = validate_success(
            api.review_program_offering(
                offering["id"], {"decision": "PUBLISH"}, education_director_headers
            )
        )
        assert published["status"] == "PUBLISHED"

        booking = validate_success(
            api.create_booking(payload, booking_coordinator_headers),
            expected_status=201,
        )
        assert booking["delivery_status"] == "REQUESTED"
        assert booking["offering_id"] == offering["id"]


# ======================================================================
# The group-size ceiling counts chaperones too
# ======================================================================

class TestGroupSizeCap:
    def test_sixty_one_persons_exceed_a_sixty_person_program(
        self, api, booking_coordinator_headers
    ):
        """PRD §2.9: "`student_count` plus `chaperone_count` is at most the offering's `max_group_size` — otherwise `ERR_GROUP_SIZE_EXCEEDED` (409). Applies to booking creation and booking confirmation."

        Design: Corner/validations/group_size_cap_admits_exactly_sixty_persons_and_rejects_sixty_one
        """
        offering, school = _published_offering_and_school()
        assert offering["max_group_size"] == 60
        response = api.create_booking(
            create_booking_payload(
                school["id"],
                offering["id"],
                start_utc=BOOKING_START,
                end_utc=BOOKING_END,
                student_count=55,
                chaperone_count=6,
            ),
            booking_coordinator_headers,
        )
        validate_error(response, ApiErrorId.ERR_GROUP_SIZE_EXCEEDED.value)

    def test_exactly_sixty_persons_are_admitted(self, api, booking_coordinator_headers):
        """PRD §2.9: "`student_count` plus `chaperone_count` is at most the offering's `max_group_size` — otherwise `ERR_GROUP_SIZE_EXCEEDED` (409). Applies to booking creation and booking confirmation."

        Design: Corner/validations/group_size_cap_admits_exactly_sixty_persons_and_rejects_sixty_one
        """
        offering, school = _published_offering_and_school()
        response = api.create_booking(
            create_booking_payload(
                school["id"],
                offering["id"],
                start_utc=BOOKING_START,
                end_utc=BOOKING_END,
                student_count=54,
                chaperone_count=6,
            ),
            booking_coordinator_headers,
        )
        booking = validate_success(response, expected_status=201)
        assert booking["student_count"] == 54
        assert booking["chaperone_count"] == 6
        assert booking["required_chaperones"] == 6
        assert booking["provisional_gross_fee_cents"] == 59940


# ======================================================================
# Stewardship gates on resource assignment
# ======================================================================

class TestStewardshipGatesOnAssignment:
    def test_a_lapsed_permit_blocks_its_ambassador(
        self, api, booking_coordinator_headers, stewardship_manager_headers
    ):
        """PRD §2.9: "The permit covering the referenced animal ambassador is `ACTIVE` — otherwise `ERR_PERMIT_NOT_ACTIVE` (409). Applies to resource assignment and booking confirmation."

        Design: Corner/validations/assign_resources_rejects_a_lapsed_permit_a_resting_animal_and_a_closed_trail
        """
        scenario = _booking_needing_an_animal(handling_tier_required="TIER_1")
        lapsed = validate_success(
            api.set_permit_status(
                scenario["permit"]["id"],
                {"status": "LAPSED", "note": "Annual renewal paperwork outstanding"},
                stewardship_manager_headers,
            )
        )
        assert lapsed["status"] == "LAPSED"

        booking = scenario["booking"]
        response = api.assign_booking_resources(
            booking["id"],
            assign_resources_payload(
                booking["version"], animal_id=scenario["animal"]["id"]
            ),
            booking_coordinator_headers,
        )
        validate_error(response, ApiErrorId.ERR_PERMIT_NOT_ACTIVE.value)
        assert refresh_booking(booking["id"])["animal_id"] is None

    def test_a_resting_ambassador_cannot_be_attached(
        self, api, booking_coordinator_headers, stewardship_manager_headers
    ):
        """PRD §2.9: "The referenced animal ambassador's care status is `AVAILABLE` — otherwise `ERR_ANIMAL_NOT_AVAILABLE` (409). Applies to resource assignment and booking confirmation."

        Design: Corner/validations/assign_resources_rejects_a_lapsed_permit_a_resting_animal_and_a_closed_trail
        """
        scenario = _booking_needing_an_animal(handling_tier_required="TIER_1")
        resting = validate_success(
            api.set_animal_care_status(
                scenario["animal"]["id"],
                {"status": "RESTING", "note": "Post-program rest day"},
                stewardship_manager_headers,
            )
        )
        assert resting["status"] == "RESTING"

        booking = scenario["booking"]
        response = api.assign_booking_resources(
            booking["id"],
            assign_resources_payload(
                booking["version"], animal_id=scenario["animal"]["id"]
            ),
            booking_coordinator_headers,
        )
        validate_error(response, ApiErrorId.ERR_ANIMAL_NOT_AVAILABLE.value)
        assert refresh_booking(booking["id"])["animal_id"] is None

    def test_a_closed_trail_segment_cannot_be_attached(
        self, api, booking_coordinator_headers, stewardship_manager_headers
    ):
        """PRD §2.9: "The referenced trail segment's status is `OPEN` — otherwise `ERR_TRAIL_NOT_OPEN` (409). Applies to resource assignment and booking confirmation."

        Design: Corner/validations/assign_resources_rejects_a_lapsed_permit_a_resting_animal_and_a_closed_trail
        """
        offering, school = _published_offering_and_school(
            requires_trail_segment=True, slug_prefix="wetland"
        )
        trail = create_trail_segment(
            capacity_persons=60, weekly_visitor_budget_persons=300
        )
        booking = create_booking(
            school["id"], offering["id"], start_utc=BOOKING_START, end_utc=BOOKING_END
        )
        closed = validate_success(
            api.set_trail_segment_status(
                trail["id"],
                {"status": "CLOSED", "note": "Boardwalk plank replacement"},
                stewardship_manager_headers,
            )
        )
        assert closed["status"] == "CLOSED"

        response = api.assign_booking_resources(
            booking["id"],
            assign_resources_payload(booking["version"], trail_segment_id=trail["id"]),
            booking_coordinator_headers,
        )
        validate_error(response, ApiErrorId.ERR_TRAIL_NOT_OPEN.value)
        assert refresh_booking(booking["id"])["trail_segment_id"] is None


# ======================================================================
# Educator clearance and handling tier on assignment
# ======================================================================

class TestEducatorCredentialGatesOnAssignment:
    def test_an_educator_still_onboarding_cannot_lead_a_booking(
        self, api, booking_coordinator_headers
    ):
        """PRD §2.9: "The referenced educator's status is `CLEARED` — otherwise `ERR_EDUCATOR_NOT_CLEARED` (422). Applies to resource assignment and booking confirmation."

        Design: Corner/validations/assign_resources_rejects_an_uncleared_educator_and_an_undertrained_handler
        """
        scenario = _booking_needing_an_animal()
        educator = create_onboarding_educator(full_name="Nils Prat")
        assert educator["status"] == "ONBOARDING"

        booking = scenario["booking"]
        response = api.assign_booking_resources(
            booking["id"],
            assign_resources_payload(booking["version"], lead_educator_id=educator["id"]),
            booking_coordinator_headers,
        )
        validate_error(response, ApiErrorId.ERR_EDUCATOR_NOT_CLEARED.value)
        assert refresh_booking(booking["id"])["lead_educator_id"] is None

    def test_a_tier_1_handler_may_not_lead_a_tier_2_ambassador(
        self, api, booking_coordinator_headers
    ):
        """PRD §2.9: "When both an educator and an animal are attached, the educator's `animal_handling_tier` is at least the animal's `handling_tier_required` under the ordering `NONE` below `TIER_1` below `TIER_2` — otherwise `ERR_HANDLING_TIER_INSUFFICIENT` (422). Applies to resource assignment and booking confirmation."

        Design: Corner/validations/assign_resources_rejects_an_uncleared_educator_and_an_undertrained_handler
        """
        scenario = _booking_needing_an_animal(handling_tier_required="TIER_2")
        staffing = create_cleared_educator(handling_tier="TIER_1", full_name="Kim Fen")
        assert staffing["educator"]["animal_handling_tier"] == "TIER_1"

        booking = scenario["booking"]
        response = api.assign_booking_resources(
            booking["id"],
            assign_resources_payload(
                booking["version"],
                lead_educator_id=staffing["educator"]["id"],
                animal_id=scenario["animal"]["id"],
            ),
            booking_coordinator_headers,
        )
        validate_error(response, ApiErrorId.ERR_HANDLING_TIER_INSUFFICIENT.value)
        refreshed = refresh_booking(booking["id"])
        assert refreshed["lead_educator_id"] is None
        assert refreshed["animal_id"] is None

    def test_a_tier_2_handler_clears_the_same_ambassador(
        self, api, booking_coordinator_headers
    ):
        """PRD §2.9: "When both an educator and an animal are attached, the educator's `animal_handling_tier` is at least the animal's `handling_tier_required` under the ordering `NONE` below `TIER_1` below `TIER_2` — otherwise `ERR_HANDLING_TIER_INSUFFICIENT` (422). Applies to resource assignment and booking confirmation."

        Design: Corner/validations/assign_resources_rejects_an_uncleared_educator_and_an_undertrained_handler
        """
        scenario = _booking_needing_an_animal(handling_tier_required="TIER_2")
        staffing = create_cleared_educator(handling_tier="TIER_2", full_name="Lio Marsh")
        assert staffing["educator"]["animal_handling_tier"] == "TIER_2"

        booking = scenario["booking"]
        assigned = validate_success(
            api.assign_booking_resources(
                booking["id"],
                assign_resources_payload(
                    booking["version"],
                    lead_educator_id=staffing["educator"]["id"],
                    animal_id=scenario["animal"]["id"],
                ),
                booking_coordinator_headers,
            )
        )
        assert assigned["lead_educator_id"] == staffing["educator"]["id"]
        assert assigned["animal_id"] == scenario["animal"]["id"]
        assert refresh_educator(staffing["educator"]["id"])["animal_handling_tier"] == "TIER_2"


# ======================================================================
# Habitat ceiling and seasonal end date on assignment
# ======================================================================

class TestHabitatCeilingAndSeasonEnd:
    def test_a_thirty_three_person_party_is_refused_by_a_sensitive_habitat(
        self, api, booking_coordinator_headers
    ):
        """PRD §2.9: "When the trail segment's `habitat_sensitivity` is `HIGH`, the booking's `student_count` plus `chaperone_count` is at most 25 persons — otherwise `ERR_HABITAT_SENSITIVITY_LIMIT` (422). Applies to resource assignment and booking confirmation."

        Design: Corner/validations/high_sensitivity_habitat_and_an_ended_season_reject_the_assignment
        """
        scenario = _booking_needing_a_sensitive_trail()
        trail = scenario["trail_segment"]
        booking = create_booking(
            scenario["school"]["id"],
            scenario["offering"]["id"],
            start_utc=BOOKING_START,
            end_utc=BOOKING_END,
            student_count=30,
            chaperone_count=3,
        )
        response = api.assign_booking_resources(
            booking["id"],
            assign_resources_payload(booking["version"], trail_segment_id=trail["id"]),
            booking_coordinator_headers,
        )
        validate_error(response, ApiErrorId.ERR_HABITAT_SENSITIVITY_LIMIT.value)
        assert refresh_trail_segment(trail["id"])["capacity_persons"] == 60
        assert refresh_booking(booking["id"])["trail_segment_id"] is None

    def test_a_twenty_two_person_party_fits_the_same_sensitive_habitat(
        self, api, booking_coordinator_headers
    ):
        """PRD §2.9: "When the trail segment's `habitat_sensitivity` is `HIGH`, the booking's `student_count` plus `chaperone_count` is at most 25 persons — otherwise `ERR_HABITAT_SENSITIVITY_LIMIT` (422). Applies to resource assignment and booking confirmation."

        Design: Corner/validations/high_sensitivity_habitat_and_an_ended_season_reject_the_assignment
        """
        scenario = _booking_needing_a_sensitive_trail()
        trail = scenario["trail_segment"]
        booking = create_booking(
            scenario["school"]["id"],
            scenario["offering"]["id"],
            start_utc="2026-09-30T14:00:00Z",
            end_utc="2026-09-30T16:00:00Z",
            student_count=20,
            chaperone_count=2,
        )
        assigned = validate_success(
            api.assign_booking_resources(
                booking["id"],
                assign_resources_payload(
                    booking["version"], trail_segment_id=trail["id"]
                ),
                booking_coordinator_headers,
            )
        )
        assert assigned["trail_segment_id"] == trail["id"]

    def test_a_seasonal_educator_may_not_lead_a_booking_past_the_season(
        self, api, booking_coordinator_headers
    ):
        """PRD §2.9: "When the assigned educator's `employment_type` is `SEASONAL_EDUCATOR`, the booking's `end_utc` is at or before that educator's `season_end_date` — otherwise `ERR_EDUCATOR_SEASON_ENDED` (409). Applies to resource assignment."

        Design: Corner/validations/high_sensitivity_habitat_and_an_ended_season_reject_the_assignment
        """
        scenario = setup_booking_scenario(
            assign_educator=False,
            student_count=30,
            chaperone_count=3,
            educator_overrides={
                "full_name": "Tam Ives",
                "employment_type": "SEASONAL_EDUCATOR",
                "season_end_date": "2026-09-28T23:59:59Z",
            },
        )
        booking = scenario["booking"]
        assert booking["end_utc"].startswith("2026-09-29T16:00:00")

        response = api.assign_booking_resources(
            booking["id"],
            assign_resources_payload(
                booking["version"], lead_educator_id=scenario["educator"]["id"]
            ),
            booking_coordinator_headers,
        )
        validate_error(response, ApiErrorId.ERR_EDUCATOR_SEASON_ENDED.value)
        assert refresh_booking(booking["id"])["lead_educator_id"] is None


# ======================================================================
# The ambassador's own half-open conflict window
# ======================================================================

class TestAnimalTimeConflict:
    def test_an_overlapping_window_refuses_the_same_ambassador(
        self, api, booking_coordinator_headers
    ):
        """PRD §2.9: "The candidate booking's `start_utc`-to-`end_utc` window, treated as half-open, does not intersect the same window of another booking with `delivery_status` of `CONFIRMED`, `RAIN_DIVERTED` or `DELIVERED` that references the same animal ambassador — otherwise `ERR_ANIMAL_TIME_CONFLICT` (409). Applies to resource assignment."

        Design: Corner/validations/assigning_an_animal_inside_an_occupied_window_is_rejected
        """
        scenario = setup_animal_booking_scenario(
            confirm=True, animal_overrides={"weekly_exposure_cap_minutes": 600}
        )
        assert scenario["booking"]["delivery_status"] == "CONFIRMED"
        candidate = create_booking(
            scenario["school"]["id"],
            scenario["offering"]["id"],
            start_utc=BOOKING_START,
            end_utc=BOOKING_END,
            student_count=20,
            chaperone_count=2,
        )
        response = api.assign_booking_resources(
            candidate["id"],
            assign_resources_payload(
                candidate["version"], animal_id=scenario["animal"]["id"]
            ),
            booking_coordinator_headers,
        )
        validate_error(response, ApiErrorId.ERR_ANIMAL_TIME_CONFLICT.value)
        assert refresh_booking(candidate["id"])["animal_id"] is None
        assert refresh_booking(scenario["booking"]["id"])["delivery_status"] == "CONFIRMED"

    def test_a_booking_starting_when_the_confirmed_one_ends_may_reuse_the_ambassador(
        self, api, booking_coordinator_headers
    ):
        """PRD §2.9: "The candidate booking's `start_utc`-to-`end_utc` window, treated as half-open, does not intersect the same window of another booking with `delivery_status` of `CONFIRMED`, `RAIN_DIVERTED` or `DELIVERED` that references the same animal ambassador — otherwise `ERR_ANIMAL_TIME_CONFLICT` (409). Applies to resource assignment."

        Design: Corner/validations/assigning_an_animal_inside_an_occupied_window_is_rejected
        """
        scenario = setup_animal_booking_scenario(
            confirm=True, animal_overrides={"weekly_exposure_cap_minutes": 600}
        )
        adjacent = create_booking(
            scenario["school"]["id"],
            scenario["offering"]["id"],
            start_utc="2026-09-29T16:00:00Z",
            end_utc="2026-09-29T18:00:00Z",
            student_count=20,
            chaperone_count=2,
        )
        assigned = validate_success(
            api.assign_booking_resources(
                adjacent["id"],
                assign_resources_payload(
                    adjacent["version"], animal_id=scenario["animal"]["id"]
                ),
                booking_coordinator_headers,
            )
        )
        assert assigned["animal_id"] == scenario["animal"]["id"]


# ======================================================================
# Required resources at confirmation
# ======================================================================

class TestRequiredResourcesAtConfirmation:
    def test_confirm_needs_the_trail_and_the_animal_the_offering_declares(
        self, api, booking_coordinator_headers
    ):
        """PRD §2.9: "`lead_educator_id` is set; `trail_segment_id` is set when the offering's `requires_trail_segment` is true; `animal_id` is set when the offering's `requires_live_animal` is true — otherwise `ERR_REQUIRED_RESOURCE_MISSING` (422). Applies to booking confirmation."

        Design: Corner/validations/confirm_without_the_offering_s_required_resources_is_rejected
        """
        scenario = setup_booking_scenario(
            offering_overrides={
                "requires_live_animal": True,
                "requires_trail_segment": True,
            },
            handling_tier="TIER_1",
            slug_prefix="raptor",
        )
        booking = scenario["booking"]
        assert booking["version"] == 2
        assert booking["lead_educator_id"] == scenario["educator"]["id"]

        validate_error(
            api.confirm_booking(booking["id"], booking_coordinator_headers),
            ApiErrorId.ERR_REQUIRED_RESOURCE_MISSING.value,
        )

        bundle = create_permitted_animal(handling_tier_required="TIER_1")
        trail = create_trail_segment(
            capacity_persons=60, weekly_visitor_budget_persons=300
        )
        completed = validate_success(
            api.assign_booking_resources(
                booking["id"],
                assign_resources_payload(
                    booking["version"],
                    trail_segment_id=trail["id"],
                    animal_id=bundle["animal"]["id"],
                ),
                booking_coordinator_headers,
            )
        )
        assert completed["version"] == 3

        confirmed = validate_success(
            api.confirm_booking(booking["id"], booking_coordinator_headers)
        )
        assert confirmed["delivery_status"] == "CONFIRMED"
        assert confirmed["trail_segment_id"] == trail["id"]
        assert confirmed["animal_id"] == bundle["animal"]["id"]


# ======================================================================
# Public contact at confirmation reads the effective rule
# ======================================================================

class TestPublicContactAtConfirmation:
    def test_a_view_only_ambassador_cannot_carry_a_hands_on_program(
        self, api, booking_coordinator_headers
    ):
        """PRD §2.9: "When the offering's `public_contact_required` is true, the animal's `effective_contact_rule` is `SUPERVISED_TOUCH` — otherwise `ERR_PUBLIC_CONTACT_NOT_PERMITTED` (422). Applies to booking confirmation."

        Design: Corner/validations/public_contact_programs_reject_a_view_only_animal_at_confirm
        """
        scenario = setup_animal_booking_scenario(
            student_count=30,
            chaperone_count=3,
            offering_overrides={"public_contact_required": True},
            animal_overrides={
                "contact_rule": "VIEW_ONLY",
                "weekly_exposure_cap_minutes": 600,
            },
        )
        assert scenario["animal"]["effective_contact_rule"] == "VIEW_ONLY"
        assert scenario["booking"]["animal_id"] == scenario["animal"]["id"]

        validate_error(
            api.confirm_booking(scenario["booking"]["id"], booking_coordinator_headers),
            ApiErrorId.ERR_PUBLIC_CONTACT_NOT_PERMITTED.value,
        )
        assert refresh_booking(scenario["booking"]["id"])["delivery_status"] == "REQUESTED"

    def test_swapping_in_a_supervised_touch_ambassador_clears_the_confirmation(
        self, api, booking_coordinator_headers
    ):
        """PRD §2.9: "When the offering's `public_contact_required` is true, the animal's `effective_contact_rule` is `SUPERVISED_TOUCH` — otherwise `ERR_PUBLIC_CONTACT_NOT_PERMITTED` (422). Applies to booking confirmation."

        Design: Corner/validations/public_contact_programs_reject_a_view_only_animal_at_confirm
        """
        scenario = setup_animal_booking_scenario(
            student_count=30,
            chaperone_count=3,
            offering_overrides={"public_contact_required": True},
            animal_overrides={
                "contact_rule": "VIEW_ONLY",
                "weekly_exposure_cap_minutes": 600,
            },
        )
        touchable = create_permitted_animal(
            permit_overrides={"permit_number": "MB-2026-119"},
            common_name="Corn Snake",
            species_code="PAGU",
            handling_tier_required="TIER_1",
            contact_rule="SUPERVISED_TOUCH",
            weekly_exposure_cap_minutes=600,
        )
        swapped = assign_resources(
            scenario["booking"]["id"], animal_id=touchable["animal"]["id"]
        )
        assert swapped["animal_id"] == touchable["animal"]["id"]

        confirmed = validate_success(
            api.confirm_booking(scenario["booking"]["id"], booking_coordinator_headers)
        )
        assert confirmed["delivery_status"] == "CONFIRMED"
        after = refresh_animal(touchable["animal"]["id"])
        assert after["effective_contact_rule"] == "SUPERVISED_TOUCH"
        assert after["welfare_posture"] == "OPEN"


# ======================================================================
# The weekly visitor budget of a trail segment
# ======================================================================

class TestTrailWeeklyVisitorBudget:
    def test_an_eleven_person_group_overflows_a_forty_person_allowance(
        self, api, booking_coordinator_headers
    ):
        """PRD §2.9: "The segment's `visitors_this_week` plus the candidate's `student_count` plus `chaperone_count` is at most `weekly_visitor_budget_persons` — otherwise `ERR_TRAIL_WEEKLY_BUDGET_EXCEEDED` (409). Applies to booking confirmation."

        Design: Corner/validations/weekly_visitor_budget_rejects_the_overflow_but_admits_the_exact_allowance
        """
        scenario = setup_trail_at_weekly_visitors(
            persons_per_booking=33,
            bookings_to_confirm=1,
            trail_overrides={
                "capacity_persons": 100,
                "habitat_sensitivity": "LOW",
                "weekly_visitor_budget_persons": 40,
                "recovery_buffer_minutes": 30,
            },
        )
        trail = scenario["trail_segment"]
        assert trail["visitors_this_week"] == 33

        staffing = create_cleared_educator()
        candidate = create_booking(
            scenario["school"]["id"],
            scenario["offering"]["id"],
            start_utc="2026-09-30T14:00:00Z",
            end_utc="2026-09-30T16:00:00Z",
            student_count=10,
            chaperone_count=1,
        )
        assign_resources(
            candidate["id"],
            lead_educator_id=staffing["educator"]["id"],
            trail_segment_id=trail["id"],
        )
        validate_error(
            api.confirm_booking(candidate["id"], booking_coordinator_headers),
            ApiErrorId.ERR_TRAIL_WEEKLY_BUDGET_EXCEEDED.value,
        )
        assert refresh_booking(candidate["id"])["delivery_status"] == "REQUESTED"
        assert refresh_trail_segment(trail["id"])["visitors_this_week"] == 33

    def test_a_seven_person_group_landing_exactly_on_forty_is_admitted(
        self, api, booking_coordinator_headers
    ):
        """PRD §2.9: "The segment's `visitors_this_week` plus the candidate's `student_count` plus `chaperone_count` is at most `weekly_visitor_budget_persons` — otherwise `ERR_TRAIL_WEEKLY_BUDGET_EXCEEDED` (409). Applies to booking confirmation."

        Design: Corner/validations/weekly_visitor_budget_rejects_the_overflow_but_admits_the_exact_allowance
        """
        scenario = setup_trail_at_weekly_visitors(
            persons_per_booking=33,
            bookings_to_confirm=1,
            trail_overrides={
                "capacity_persons": 100,
                "habitat_sensitivity": "LOW",
                "weekly_visitor_budget_persons": 40,
                "recovery_buffer_minutes": 30,
            },
        )
        trail = scenario["trail_segment"]
        staffing = create_cleared_educator()
        candidate = create_booking(
            scenario["school"]["id"],
            scenario["offering"]["id"],
            start_utc="2026-10-01T14:00:00Z",
            end_utc="2026-10-01T16:00:00Z",
            student_count=6,
            chaperone_count=1,
        )
        assign_resources(
            candidate["id"],
            lead_educator_id=staffing["educator"]["id"],
            trail_segment_id=trail["id"],
        )
        confirmed = validate_success(
            api.confirm_booking(candidate["id"], booking_coordinator_headers)
        )
        assert confirmed["delivery_status"] == "CONFIRMED"
        after = refresh_trail_segment(trail["id"])
        assert after["visitors_this_week"] == 40
        assert after["capacity_persons"] == 100


# ======================================================================
# Uniqueness of a standard code and dimension pairing
# ======================================================================

class TestDuplicateStandardAlignment:
    def test_the_same_code_and_dimension_pairing_cannot_repeat(
        self, api, curriculum_specialist_headers
    ):
        """PRD §3.1: "Two claims on the same offering may not share the same combination of `standard_code` and `dimension` — a repeat is rejected with `ERR_DUPLICATE_STANDARD_ALIGNMENT`."

        Design: Corner/validations/a_repeated_standard_code_and_dimension_pair_is_rejected
        """
        set_clock(DEFAULT_CLOCK)
        offering = create_draft_offering()
        attach_alignments(offering["id"])
        assert refresh_offering(offering["id"])["standard_alignment_count"] == 2

        response = api.create_standard_alignment(
            offering["id"],
            create_standard_alignment_payload(
                standard_code="3-LS4-3", dimension="DISCIPLINARY_CORE_IDEA"
            ),
            curriculum_specialist_headers,
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_STANDARD_ALIGNMENT.value)
        assert refresh_offering(offering["id"])["standard_alignment_count"] == 2

    def test_the_same_code_under_another_dimension_is_a_new_claim(
        self, api, curriculum_specialist_headers
    ):
        """PRD §2.9: "No existing standard alignment on this offering already claims the same pairing of `standard_code` and `dimension` — otherwise `ERR_DUPLICATE_STANDARD_ALIGNMENT` (422). Applies to attaching a standard alignment."

        Design: Corner/validations/a_repeated_standard_code_and_dimension_pair_is_rejected
        """
        set_clock(DEFAULT_CLOCK)
        offering = create_draft_offering()
        attach_alignments(offering["id"])

        alignment = validate_success(
            api.create_standard_alignment(
                offering["id"],
                create_standard_alignment_payload(
                    standard_code="3-LS4-3", dimension="SCIENCE_PRACTICE"
                ),
                curriculum_specialist_headers,
            ),
            expected_status=201,
        )
        assert alignment["dimension"] == "SCIENCE_PRACTICE"
        assert alignment["offering_id"] == offering["id"]
        assert refresh_offering(offering["id"])["standard_alignment_count"] == 3
