"""Depth tests: an operation blocked by the state of a *different* entity.

Each family pairs a rejection against the depended-on entity in its blocking
state with the identical call issued while that entity is healthy, so the
dependency itself — not an incidental precondition — is what moves.
"""

import pytest

from test_helpers import (
    DEFAULT_CLOCK,
    EDUCATION_DIRECTOR_ID,
    ApiErrorId,
    create_booking,
    create_booking_payload,
    create_cleared_educator,
    create_offering_under_review,
    create_published_offering,
    create_school,
    find_material,
    find_training_record,
    refresh_booking,
    refresh_educator,
    refresh_offering,
    refresh_school,
    set_clock,
    setup_school_with_strikes,
    validate_error,
    validate_success,
)


def _setup_educator_with_dated_curriculum_pass(
    booking_clock: str, booking_start: str, booking_end: str
) -> dict:
    """A CLEARED educator whose CURRICULUM pass was recorded at the default clock,
    plus a REQUESTED booking created after the clock has been moved to
    ``booking_clock``. Nothing is attached to the booking yet.
    """
    set_clock(DEFAULT_CLOCK)
    offering = create_published_offering()
    school = create_school()
    staffing = create_cleared_educator()
    set_clock(booking_clock)
    booking = create_booking(
        school["id"],
        offering["id"],
        start_utc=booking_start,
        end_utc=booking_end,
        student_count=20,
        chaperone_count=3,
    )
    return {
        "offering": offering,
        "school": school,
        "educator": staffing["educator"],
        "curriculum_record": staffing["curriculum_records"][0],
        "booking": booking,
    }


class TestBookingCreateAgainstSuspendedSchool:
    def test_booking_create_rejected_when_school_reached_two_no_show_strikes(
        self, api, booking_coordinator_headers
    ):
        """PRD §3.2: "A suspended school cannot have new bookings created for it and cannot have existing ones confirmed; both attempts answer `ERR_SCHOOL_SUSPENDED`."

        Design: Difficulty/cross_entity_state_dependency/booking_create_blocked_when_school_partner_is_suspended
        """
        scenario = setup_school_with_strikes(strikes=2)
        school = scenario["school"]
        offering = scenario["offering"]
        assert school["status"] == "SUSPENDED"
        assert school["no_show_strikes"] == 2

        response = api.create_booking(
            create_booking_payload(
                school["id"],
                offering["id"],
                start_utc="2026-10-01T14:00:00Z",
                end_utc="2026-10-01T16:00:00Z",
                student_count=30,
                chaperone_count=3,
            ),
            booking_coordinator_headers,
        )
        validate_error(response, ApiErrorId.ERR_SCHOOL_SUSPENDED.value)

        school_after = refresh_school(school["id"])
        assert school_after["status"] == "SUSPENDED"
        assert school_after["no_show_strikes"] == 2
        assert refresh_offering(offering["id"])["status"] == "PUBLISHED"

    @pytest.mark.parametrize(
        "strikes, expected_school_status",
        [(0, "ACTIVE"), (1, "PROBATION")],
    )
    def test_booking_create_succeeds_while_school_is_not_suspended(
        self, api, booking_coordinator_headers, strikes, expected_school_status
    ):
        """PRD §2.9: "The referenced school partner is not `SUSPENDED` — otherwise `ERR_SCHOOL_SUSPENDED` (409)."

        Design: Difficulty/cross_entity_state_dependency/booking_create_blocked_when_school_partner_is_suspended
        """
        scenario = setup_school_with_strikes(strikes=strikes)
        school = scenario["school"]
        offering = scenario["offering"]
        assert school["status"] == expected_school_status
        assert school["no_show_strikes"] == strikes

        response = api.create_booking(
            create_booking_payload(
                school["id"],
                offering["id"],
                start_utc="2026-10-01T14:00:00Z",
                end_utc="2026-10-01T16:00:00Z",
                student_count=30,
                chaperone_count=3,
            ),
            booking_coordinator_headers,
        )
        booking = validate_success(response, expected_status=201)
        assert booking["delivery_status"] == "REQUESTED"
        assert booking["funding_status"] == "UNFUNDED"
        assert booking["school_id"] == school["id"]

        school_after = refresh_school(school["id"])
        assert school_after["status"] == expected_school_status
        assert school_after["no_show_strikes"] == strikes


class TestOfferingPublishDependsOnChildMaterials:
    def test_publish_decision_rejected_while_post_visit_material_is_still_draft(
        self, api, education_director_headers
    ):
        """PRD §3.1: "The `PUBLISH` branch carries three further requirements: `standard_alignment_count` must be at least 2 (a single claim is enough to enter review but not to ship, and a shortfall is again `ERR_INSUFFICIENT_STANDARD_ALIGNMENT`), and `materials_ready` must be true or the decision is rejected with `ERR_MATERIALS_NOT_READY`."

        Design: Difficulty/cross_entity_state_dependency/offering_publish_blocked_until_both_child_materials_are_published
        """
        set_clock(DEFAULT_CLOCK)
        bundle = create_offering_under_review(publish_post_visit=False)
        offering = bundle["offering"]
        assert offering["status"] == "UNDER_REVIEW"
        assert offering["standard_alignment_count"] == 2
        assert offering["materials_ready"] is False

        response = api.review_program_offering(
            offering["id"], {"decision": "PUBLISH"}, education_director_headers
        )
        validate_error(response, ApiErrorId.ERR_MATERIALS_NOT_READY.value)

        offering_after = refresh_offering(offering["id"])
        assert offering_after["status"] == "UNDER_REVIEW"
        assert offering_after["materials_ready"] is False
        assert (
            find_material(offering["id"], bundle["pre_visit_material"]["id"])["status"]
            == "PUBLISHED"
        )
        assert (
            find_material(offering["id"], bundle["post_visit_material"]["id"])["status"]
            == "DRAFT"
        )

    def test_publish_decision_succeeds_once_the_post_visit_material_is_published(
        self, api, curriculum_specialist_headers, education_director_headers
    ):
        """PRD §3.1: "Every publish recomputes the parent's `materials_ready`, which is true precisely when the offering has at least one `PRE_VISIT` material in `PUBLISHED` **and** at least one `POST_VISIT` material in `PUBLISHED`."

        Design: Difficulty/cross_entity_state_dependency/offering_publish_blocked_until_both_child_materials_are_published
        """
        set_clock(DEFAULT_CLOCK)
        bundle = create_offering_under_review(publish_post_visit=False)
        offering = bundle["offering"]
        post_visit_material = bundle["post_visit_material"]

        published_material = validate_success(
            api.publish_curriculum_material(
                post_visit_material["id"], curriculum_specialist_headers
            )
        )
        assert published_material["status"] == "PUBLISHED"

        decided = validate_success(
            api.review_program_offering(
                offering["id"], {"decision": "PUBLISH"}, education_director_headers
            )
        )
        assert decided["status"] == "PUBLISHED"
        assert decided["materials_ready"] is True
        assert decided["published_at"] == "2026-09-28T07:00:00.000Z"
        assert decided["reviewed_by_user_id"] == EDUCATION_DIRECTOR_ID

        assert (
            find_material(offering["id"], post_visit_material["id"])["status"]
            == "PUBLISHED"
        )


class TestAssignResourcesDependsOnTrainingValidity:
    def test_assignment_rejected_when_the_curriculum_pass_lapsed_into_expiry(
        self, api, booking_coordinator_headers
    ):
        """PRD §3.3: "The consequence matters: an educator whose curriculum pass lapsed last week is still nominally `CLEARED`, but the grade-band check at assignment time will see the expired record and reject with `ERR_EDUCATOR_NOT_CERTIFIED_FOR_GRADE_BAND`."

        Design: Difficulty/cross_entity_state_dependency/assign_resources_blocked_when_curriculum_training_lapsed_into_expiry
        """
        scenario = _setup_educator_with_dated_curriculum_pass(
            booking_clock="2027-10-01T00:00:00Z",
            booking_start="2027-10-02T14:00:00Z",
            booking_end="2027-10-02T16:00:00Z",
        )
        booking = scenario["booking"]
        educator_id = scenario["educator"]["id"]

        response = api.assign_booking_resources(
            booking["id"],
            {
                "expected_booking_version": booking["version"],
                "lead_educator_id": educator_id,
            },
            booking_coordinator_headers,
        )
        validate_error(
            response, ApiErrorId.ERR_EDUCATOR_NOT_CERTIFIED_FOR_GRADE_BAND.value
        )

        record_after = find_training_record(
            educator_id, scenario["curriculum_record"]["id"]
        )
        assert record_after["status"] == "EXPIRED"

        educator_after = refresh_educator(educator_id)
        assert educator_after["status"] == "CLEARED"
        assert educator_after["curriculum_certified_grade_bands"] == []

        booking_after = refresh_booking(booking["id"])
        assert booking_after["lead_educator_id"] is None
        assert booking_after["delivery_status"] == "REQUESTED"

    def test_assignment_succeeds_while_the_curriculum_pass_is_still_inside_its_window(
        self, api, booking_coordinator_headers
    ):
        """PRD §3.3: "At the moment a coordinator attaches resources to a booking, every `ASSESSED_PASS` record belonging to the named educator whose `expires_on` is at or before the logical clock transitions `ASSESSED_PASS → EXPIRED`, and only then are `curriculum_certified_grade_bands` (with the lapsed band dropped) and `animal_handling_tier` (downgraded, possibly all the way to `NONE`) re-derived."

        Design: Difficulty/cross_entity_state_dependency/assign_resources_blocked_when_curriculum_training_lapsed_into_expiry
        """
        scenario = _setup_educator_with_dated_curriculum_pass(
            booking_clock="2027-09-01T00:00:00Z",
            booking_start="2027-09-02T14:00:00Z",
            booking_end="2027-09-02T16:00:00Z",
        )
        booking = scenario["booking"]
        educator_id = scenario["educator"]["id"]

        assigned = validate_success(
            api.assign_booking_resources(
                booking["id"],
                {
                    "expected_booking_version": booking["version"],
                    "lead_educator_id": educator_id,
                },
                booking_coordinator_headers,
            )
        )
        assert assigned["lead_educator_id"] == educator_id
        assert assigned["version"] == booking["version"] + 1

        record_after = find_training_record(
            educator_id, scenario["curriculum_record"]["id"]
        )
        assert record_after["status"] == "ASSESSED_PASS"

        educator_after = refresh_educator(educator_id)
        assert educator_after["status"] == "CLEARED"
        assert educator_after["curriculum_certified_grade_bands"] == ["G3_5"]
