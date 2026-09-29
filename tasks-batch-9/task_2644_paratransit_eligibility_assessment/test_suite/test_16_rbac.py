"""Role scoping: exclusive operations, shared operations, and one segregated step."""
from test_helpers import factories, validate_error, validate_paginated, validate_success
from test_helpers.api_errors import (
    ERR_FORBIDDEN_ROLE,
    ERR_SIGNOFF_NOT_INDEPENDENT,
)
from test_helpers.fixtures import (
    create_applicant,
    create_vehicle,
    ingest_trip_event,
    set_clock,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    CLERK_HEADERS,
    CONDUCT_OFFICER_HEADERS,
    EVALUATOR_HEADERS,
    REVIEWER_HEADERS,
    SPECIALIST_2_HEADERS,
    SPECIALIST_HEADERS,
    TRAINER_HEADERS,
    make_applicant_headers,
    make_staff_headers,
)

_UNKNOWN = "00000000-0000-4000-8000-0000000000{:02d}"


def test_exclusive_operations_reject_peer_roles_before_any_existence_check(api):
    """Each specialist role is refused on every other role's exclusive step.

    "When both headers are well formed but the acting role is not among the roles
    the addressed endpoint authorizes, the rejection is `ERR_FORBIDDEN_ROLE`
    (HTTP 403). These two checks run before everything else — before resource
    lookup, before request-shape validation, and before any state check."

    "| POST | `/assessments/{id}/scores` | Record the evaluator's observed scores
    for an assessment. | `Evaluator` |"

    "| POST | `/appeals/{id}/decision` | Record the independent reviewer's
    disposition of an appeal. | `IndependentReviewer` |"

    "| POST | `/trip-events` | Ingest one trip event for a rider. |
    `ConductOfficer`, `AccessibilityOfficeAdmin` |"

    Design: Corner/rbac/exclusive_operations_rejects_peer_roles_before_any_existence_check
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Abel Fournier",
        date_of_birth="1968-08-28",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="NONE",
    )
    rider = validate_success(api.get_applicant(rider["id"], CONDUCT_OFFICER_HEADERS))
    assert rider["version"] == 1

    validate_error(
        api.record_scores(
            _UNKNOWN.format(41),
            factories.scores_payload(
                board_alight_score=2,
                wayfinding_score=2,
                distance_meters_walked=100,
                heat_sensitivity_flag=False,
            ),
            SPECIALIST_HEADERS,
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api.sign_off_assessment(
            _UNKNOWN.format(41), factories.sign_off_payload(), EVALUATOR_HEADERS
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api.issue_determination(
            _UNKNOWN.format(42), factories.issue_payload(), REVIEWER_HEADERS
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api.decide_appeal(
            _UNKNOWN.format(43),
            factories.appeal_decision_payload("UPHELD"),
            SPECIALIST_HEADERS,
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api.complete_referral(
            _UNKNOWN.format(44),
            factories.referral_completion_payload(fixed_route_competency_score=90),
            CONDUCT_OFFICER_HEADERS,
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api.propose_suspension(
            rider["id"],
            factories.suspension_proposal_payload(
                rider["version"], review_window_end_date="2026-08-01"
            ),
            TRAINER_HEADERS,
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )

    rider = validate_success(api.get_applicant(rider["id"], CONDUCT_OFFICER_HEADERS))
    assert rider["version"] == 1
    _proceedings, proceeding_meta = validate_paginated(
        api.list_suspension_proceedings(rider["id"], CONDUCT_OFFICER_HEADERS)
    )
    assert proceeding_meta["total_count"] == 0

    officer_event = ingest_trip_event(
        api, rider["id"], trip_date="2026-07-20", event_type="COMPLETED"
    )
    admin_event = validate_success(
        api.create_trip_event(
            factories.trip_event_payload(
                rider["id"], trip_date="2026-07-21", event_type="COMPLETED"
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    assert officer_event["points_assessed"] == 0
    assert admin_event["points_assessed"] == 0

    events, event_meta = validate_paginated(
        api.list_trip_events(rider["id"], CONDUCT_OFFICER_HEADERS)
    )
    assert event_meta["total_count"] == 2
    assert [event["trip_date"] for event in events] == ["2026-07-20", "2026-07-21"]


def test_an_applicant_cannot_reach_staff_only_reads_but_keeps_the_shared_writes(api):
    """Role scoping refuses four reads that the ownership rule would have allowed.

    "| GET | `/assessments` | List functional assessments. | `IntakeClerk`,
    `Evaluator`, `EligibilitySpecialist`, `AccessibilityOfficeAdmin` |"

    "| GET | `/transportation-bookings` | List agency-provided ride reservations.
    | `IntakeClerk`, `AccessibilityOfficeAdmin` |"

    "| GET | `/applications/{id}/verifications` | List the professional
    verifications requested for one intake packet. | `IntakeClerk`,
    `EligibilitySpecialist`, `IndependentReviewer`, `AccessibilityOfficeAdmin` |"

    "| POST | `/applications` | Open an intake packet for a rider. | `Applicant`,
    `IntakeClerk` |"

    Design: Corner/rbac/an_applicant_cannot_reach_staff_only_reads_but_keeps_the_shared_writes
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Bea Solberg",
        date_of_birth="1975-05-25",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="CANE",
    )
    vehicle = create_vehicle(
        api,
        vehicle_number="V-8200",
        wheelchair_positions=1,
        ambulatory_seats=4,
        status="IN_SERVICE",
    )
    rider_headers = make_applicant_headers(rider["id"])

    application = validate_success(
        api.create_application(
            factories.application_payload(
                rider["id"],
                functional_answers=factories.functional_answers(
                    can_board_bus_steps=False,
                    can_navigate_unfamiliar_route=True,
                    max_walk_distance_meters=150,
                    uses_mobility_aid_outdoors=True,
                    has_cognitive_impairment=False,
                ),
            ),
            rider_headers,
        ),
        201,
    )
    assert application["status"] == "DRAFT"

    submitted = validate_success(
        api.submit_application(
            application["id"], factories.submit_payload(), rider_headers
        )
    )
    assert submitted["status"] == "SUBMITTED"

    validate_error(
        api.list_assessments(rider_headers), ERR_FORBIDDEN_ROLE, 403
    )
    validate_error(
        api.list_transportation_bookings(rider_headers), ERR_FORBIDDEN_ROLE, 403
    )
    validate_error(
        api.list_verifications(application["id"], rider_headers),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api.get_vehicle(vehicle["id"], rider_headers), ERR_FORBIDDEN_ROLE, 403
    )

    own, own_meta = validate_paginated(
        api.list_applications(rider_headers, params={"applicant_id": rider["id"]})
    )
    assert own_meta["total_count"] == 1
    assert own[0]["id"] == application["id"]
    assert own[0]["status"] == "SUBMITTED"


def test_the_same_user_cannot_score_and_sign_off_one_assessment(api):
    """Segregation compares operator identifiers, not the role pair.

    "First, the person who signs off an assessment must not be the person who
    scored it: if the signing `X-User-ID` equals the assessment's
    `scored_by_user_id`, the sign-off is rejected with
    `ERR_SIGNOFF_NOT_INDEPENDENT` (HTTP 422)."

    "Recording scores moves the scoring dimension to `SCORED` and writes
    `scored_by_user_id` from the acting `X-User-ID`."

    "A successful sign-off writes `signed_off_by_user_id` from the acting header,
    moves the scoring dimension `SCORED → SIGNED_OFF`, and bubbles up to the
    parent packet: an application sitting in `ASSESSMENT_SCHEDULED` whose
    assessment has attendance `ATTENDED` and scoring `SCORED` advances to
    `ASSESSMENT_COMPLETE`, and the packet's `version` increments with it."

    Design: Corner/rbac/the_same_user_cannot_score_and_sign_off_one_assessment
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Cato Lindqvist",
        date_of_birth="1962-02-22",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="WALKER",
    )
    application = validate_success(
        api.create_application(
            factories.application_payload(
                rider["id"],
                functional_answers=factories.functional_answers(
                    can_board_bus_steps=False,
                    can_navigate_unfamiliar_route=False,
                    max_walk_distance_meters=105,
                    uses_mobility_aid_outdoors=True,
                    has_cognitive_impairment=False,
                ),
                claimed_conditions=["multiple sclerosis"],
            ),
            CLERK_HEADERS,
        ),
        201,
    )
    validate_success(
        api.submit_application(
            application["id"], factories.submit_payload(), CLERK_HEADERS
        )
    )
    verification = validate_success(
        api.request_verification(
            application["id"],
            factories.verification_request_payload(
                provider_name="Dr. T Marek",
                provider_type="PHYSICIAN",
                provider_license_number="MD-90029",
            ),
            CLERK_HEADERS,
        ),
        201,
    )
    validate_success(
        api.receive_verification(
            application["id"],
            verification["id"],
            factories.verification_accepted_payload(
                attests_conditions=["multiple sclerosis"], attests_permanent=True
            ),
            CLERK_HEADERS,
        )
    )
    slot = validate_success(
        api.create_assessment_slot(
            factories.assessment_slot_payload(
                site_name="Central Mobility Center",
                evaluator_user_id="spec-1",
                starts_at="2026-08-05T09:00:00Z",
                ends_at="2026-08-05T10:00:00Z",
                capacity=2,
                site_is_wheelchair_accessible=True,
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    assessment = validate_success(
        api.book_assessment(
            application["id"],
            factories.assessment_booking_payload(
                slot["id"], requires_wheelchair_position=False
            ),
            CLERK_HEADERS,
        ),
        201,
    )

    scoring_evaluator = make_staff_headers("spec-1", "Evaluator")
    set_clock(api, "2026-08-05T09:30:00Z")
    validate_success(
        api.record_attendance(
            assessment["id"], factories.attendance_payload("ATTENDED"), scoring_evaluator
        )
    )
    scored = validate_success(
        api.record_scores(
            assessment["id"],
            factories.scores_payload(
                board_alight_score=1,
                wayfinding_score=1,
                distance_meters_walked=105,
                heat_sensitivity_flag=False,
            ),
            scoring_evaluator,
        )
    )
    assert scored["scored_by_user_id"] == "spec-1"
    assert scored["scoring_status"] == "SCORED"

    validate_error(
        api.sign_off_assessment(
            assessment["id"], factories.sign_off_payload(), SPECIALIST_HEADERS
        ),
        ERR_SIGNOFF_NOT_INDEPENDENT,
        422,
    )

    midway = validate_success(api.get_assessment(assessment["id"], CLERK_HEADERS))
    assert midway["scoring_status"] == "SCORED"
    assert midway["signed_off_by_user_id"] is None
    mid_application = validate_success(
        api.get_application(application["id"], CLERK_HEADERS)
    )
    assert mid_application["status"] == "ASSESSMENT_SCHEDULED"

    signed = validate_success(
        api.sign_off_assessment(
            assessment["id"], factories.sign_off_payload(), SPECIALIST_2_HEADERS
        )
    )
    assert signed["scoring_status"] == "SIGNED_OFF"
    assert signed["signed_off_by_user_id"] == "spec-2"

    final_application = validate_success(
        api.get_application(application["id"], CLERK_HEADERS)
    )
    assert final_application["status"] == "ASSESSMENT_COMPLETE"
