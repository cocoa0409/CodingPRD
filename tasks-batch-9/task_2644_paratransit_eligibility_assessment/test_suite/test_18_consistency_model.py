"""The declared consistency model: no read-after-write lag anywhere."""
from test_helpers import factories, validate_success
from test_helpers.assertions import assert_eligibility_mirrors, assert_slot_mirror
from test_helpers.fixtures import (
    attended_assessment,
    create_applicant,
    create_slot,
    set_clock,
)
from test_helpers.test_users import (
    CLERK_HEADERS,
    EVALUATOR_HEADERS,
    SPECIALIST_2_HEADERS,
    SPECIALIST_HEADERS,
)


def test_each_intake_write_already_carries_the_values_it_derived(api):
    """Submit, receive and book each answer with their own derived fields.

    "The `data` field contains the resource object or an array of resource
    objects. For 2xx responses with no data, it contains an empty object. Unless
    otherwise noted, operations that create or modify a resource will return the
    created or updated resource object in the data field."

    "A successful submission does four things. It stamps `submitted_at` with the
    logical clock's current instant. It sets `completeness_established_at` equal to
    `submitted_at`, which is the moment the statutory determination window begins.
    It sets `determination_due_date` to the calendar date of
    `completeness_established_at` plus 21 days. And it clears `missing_items` back
    to an empty list."

    "The verification moves `REQUESTED → RECEIVED`, `received_at` is stamped from
    the clock, and `wait_days` is computed as the whole days elapsed from
    `requested_at` to `received_at`, discarding any partial day."

    "A successful booking creates the assessment with `attendance_status`
    `SCHEDULED` and `scoring_status` `NOT_STARTED`, all five score inputs null,
    `recommended_category`, `recommended_term_days`, `scored_by_user_id`,
    `signed_off_by_user_id` and `attendance_recorded_at` null"

    Design: Corner/consistency_model/every_derived_value_is_visible_in_the_response_that_caused_it
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = validate_success(
        api.create_applicant(
            factories.applicant_payload(
                full_name="Liesel Brandt",
                date_of_birth="1949-09-09",
                residence_zone="IN_SERVICE_AREA",
                mobility_aid="MANUAL_WHEELCHAIR",
            ),
            CLERK_HEADERS,
        ),
        201,
    )
    assert_eligibility_mirrors(rider, "NONE", None, None)

    application = validate_success(
        api.create_application(
            factories.application_payload(
                rider["id"],
                application_type="NEW",
                functional_answers=factories.functional_answers(
                    can_board_bus_steps=False,
                    can_navigate_unfamiliar_route=False,
                    max_walk_distance_meters=25,
                    uses_mobility_aid_outdoors=True,
                    has_cognitive_impairment=False,
                ),
                claimed_conditions=["c5 spinal cord injury"],
            ),
            CLERK_HEADERS,
        ),
        201,
    )
    assert application["status"] == "DRAFT"
    assert application["determination_due_date"] is None
    assert application["completeness_established_at"] is None
    assert application["missing_items"] == []

    submitted = validate_success(
        api.submit_application(
            application["id"], factories.submit_payload(), CLERK_HEADERS
        )
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_at"] == "2026-08-01T00:00:00.000Z"
    assert submitted["completeness_established_at"] == "2026-08-01T00:00:00.000Z"
    assert submitted["determination_due_date"] == "2026-08-22"
    assert submitted["missing_items"] == []

    requested = validate_success(
        api.request_verification(
            application["id"],
            factories.verification_request_payload(
                provider_name="Dr. X Ferreira",
                provider_type="PHYSICIAN",
                provider_license_number="MD-90033",
            ),
            CLERK_HEADERS,
        ),
        201,
    )
    assert requested["status"] == "REQUESTED"
    assert requested["requested_at"] == "2026-08-01T00:00:00.000Z"
    assert requested["received_at"] is None
    assert requested["wait_days"] == 0

    received = validate_success(
        api.receive_verification(
            application["id"],
            requested["id"],
            factories.verification_accepted_payload(
                attests_conditions=["c5 spinal cord injury"], attests_permanent=True
            ),
            CLERK_HEADERS,
        )
    )
    assert received["status"] == "RECEIVED"
    assert received["received_at"] == "2026-08-01T00:00:00.000Z"
    assert received["wait_days"] == 0

    slot = create_slot(
        api,
        site_name="Central Mobility Center",
        evaluator_user_id="eval-1",
        starts_at="2026-08-05T09:00:00Z",
        ends_at="2026-08-05T10:00:00Z",
        capacity=2,
        site_is_wheelchair_accessible=True,
    )
    assert_slot_mirror(slot, booked_count=0, status="OPEN")

    assessment = validate_success(
        api.book_assessment(
            application["id"],
            factories.assessment_booking_payload(
                slot["id"], requires_wheelchair_position=True
            ),
            CLERK_HEADERS,
        ),
        201,
    )
    assert assessment["attendance_status"] == "SCHEDULED"
    assert assessment["scoring_status"] == "NOT_STARTED"
    assert assessment["board_alight_score"] is None
    assert assessment["wayfinding_score"] is None
    assert assessment["distance_meters_walked"] is None
    assert assessment["heat_sensitivity_flag"] is None
    assert assessment["evaluator_notes"] is None
    assert assessment["recommended_category"] is None
    assert assessment["recommended_term_days"] is None
    assert assessment["scored_by_user_id"] is None
    assert assessment["signed_off_by_user_id"] is None
    assert assessment["attendance_recorded_at"] is None

    booked_slot = validate_success(api.get_assessment_slot(slot["id"], CLERK_HEADERS))
    assert_slot_mirror(booked_slot, booked_count=1, status="OPEN")


def test_the_issue_response_and_the_next_read_agree_without_a_sweep(api):
    """Scoring, issuance and the rider's mirrors are all visible immediately.

    "Recording scores moves the scoring dimension to `SCORED` and writes
    `scored_by_user_id` from the acting `X-User-ID`."

    "`recommended_term_days` is then set from the recommended category using the
    same term table the determination itself uses: 1,825 days (five years) for
    `UNCONDITIONAL`, 1,095 days (three years) for `CONDITIONAL`, 180 days for
    `TEMPORARY`, and 0 days for `INELIGIBLE`."

    "A successful draft creates the determination in `DRAFT`, copies `applicant_id`
    down from the parent packet so the grant is addressable by rider, records
    `determined_by_user_id` from the acting `X-User-ID` — the identity the appeal
    reviewer must later differ from — leaves `issued_at` and `expires_at` null, sets
    `under_appeal` false, `origin` to `SPECIALIST_DETERMINATION`, and
    `fixed_route_competency_confirmed` false."

    "It rewrites the rider's mirrors: `current_eligibility_status` becomes
    `ELIGIBLE`, or `INELIGIBLE` when the category is `INELIGIBLE`;
    `eligibility_category` becomes the issued category; and
    `active_determination_id` becomes this determination's `id`."

    Design: Corner/consistency_model/every_derived_value_is_visible_in_the_response_that_caused_it
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Liesel Brandt",
        date_of_birth="1949-09-09",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="MANUAL_WHEELCHAIR",
    )
    slot = create_slot(
        api,
        site_name="Central Mobility Center",
        evaluator_user_id="eval-1",
        starts_at="2026-08-05T09:00:00Z",
        ends_at="2026-08-05T10:00:00Z",
        capacity=2,
        site_is_wheelchair_accessible=True,
    )
    context = attended_assessment(
        api,
        applicant=rider,
        slot=slot,
        functional_answers=factories.functional_answers(
            can_board_bus_steps=False,
            can_navigate_unfamiliar_route=False,
            max_walk_distance_meters=25,
            uses_mobility_aid_outdoors=True,
            has_cognitive_impairment=False,
        ),
        claimed_conditions=["c5 spinal cord injury"],
        booking_overrides={"requires_wheelchair_position": True},
        attendance_at="2026-08-05T09:30:00Z",
    )
    application_id = context["application"]["id"]
    assert context["assessment"]["attendance_recorded_at"] == "2026-08-05T09:30:00.000Z"

    scored = validate_success(
        api.record_scores(
            context["assessment"]["id"],
            factories.scores_payload(
                board_alight_score=0,
                wayfinding_score=1,
                distance_meters_walked=25,
                heat_sensitivity_flag=False,
            ),
            EVALUATOR_HEADERS,
        )
    )
    assert scored["scoring_status"] == "SCORED"
    assert scored["scored_by_user_id"] == "eval-1"
    assert scored["recommended_category"] == "UNCONDITIONAL"
    assert scored["recommended_term_days"] == 1825

    signed = validate_success(
        api.sign_off_assessment(
            context["assessment"]["id"],
            factories.sign_off_payload(),
            SPECIALIST_2_HEADERS,
        )
    )
    assert signed["scoring_status"] == "SIGNED_OFF"

    packet = validate_success(api.get_application(application_id, SPECIALIST_HEADERS))
    assert packet["status"] == "ASSESSMENT_COMPLETE"

    draft = validate_success(
        api.draft_determination(
            application_id,
            factories.determination_draft_payload(
                packet["version"],
                category="UNCONDITIONAL",
                effective_date="2026-08-06",
                rationale="cannot use fixed route at all",
            ),
            SPECIALIST_HEADERS,
        ),
        201,
    )
    assert draft["status"] == "DRAFT"
    assert draft["applicant_id"] == rider["id"]
    assert draft["determined_by_user_id"] == "spec-1"
    assert draft["issued_at"] is None
    assert draft["expires_at"] is None
    assert draft["under_appeal"] is False
    assert draft["origin"] == "SPECIALIST_DETERMINATION"
    assert draft["fixed_route_competency_confirmed"] is False

    issued = validate_success(
        api.issue_determination(
            draft["id"], factories.issue_payload(), SPECIALIST_HEADERS
        )
    )
    assert issued["status"] == "ISSUED"
    assert issued["issued_at"] == "2026-08-05T09:30:00.000Z"
    assert issued["term_days"] == 1825
    assert issued["expires_at"] == "2031-08-05"
    assert issued["determined_by_user_id"] == "spec-1"

    mirrors = validate_success(api.get_applicant(rider["id"], SPECIALIST_HEADERS))
    assert_eligibility_mirrors(mirrors, "ELIGIBLE", "UNCONDITIONAL", issued["id"])

    determined = validate_success(
        api.get_application(application_id, SPECIALIST_HEADERS)
    )
    assert determined["status"] == "DETERMINED"
