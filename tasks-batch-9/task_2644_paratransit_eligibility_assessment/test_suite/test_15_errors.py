"""Reachability of the catalog: every not-found id, and the three gate errors."""
from test_helpers import factories, validate_error, validate_paginated, validate_success
from test_helpers.api_errors import (
    ERR_APPEAL_NOT_FOUND,
    ERR_APPLICANT_NOT_FOUND,
    ERR_APPLICATION_NOT_FOUND,
    ERR_ASSESSMENT_NOT_FOUND,
    ERR_BOOKING_NOT_FOUND,
    ERR_DETERMINATION_NOT_FOUND,
    ERR_FORBIDDEN_ROLE,
    ERR_INVALID_APPLICATION_STATE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_PROCEEDING_NOT_FOUND,
    ERR_REFERRAL_NOT_FOUND,
    ERR_SLOT_NOT_FOUND,
    ERR_TRIP_EVENT_NOT_FOUND,
    ERR_UNAUTHENTICATED,
    ERR_VEHICLE_NOT_FOUND,
    ERR_VERIFICATION_NOT_FOUND,
    ERR_VERIFICATION_PENDING,
    ERR_VERIFICATION_STATE_INVALID,
    ERR_VISITOR_RECORD_NOT_FOUND,
)
from test_helpers.assertions import assert_all_sweep_counters_present
from test_helpers.fixtures import (
    create_applicant,
    draft_application,
    ingest_trip_event,
    issued_determination,
    set_clock,
    submitted_application,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    CLERK_HEADERS,
    CONDUCT_OFFICER_HEADERS,
    EVALUATOR_HEADERS,
    TRAINER_HEADERS,
    headers_with_undeclared_role,
    headers_without_role,
    headers_without_user_id,
    make_applicant_headers,
)

_UNKNOWN = "00000000-0000-4000-8000-0000000000{:02d}"


def test_every_declared_not_found_id_is_reachable_with_an_unknown_path_id(api):
    """All thirteen not-found identifiers answer their own path parameter.

    "Every identifier appearing in the request path must resolve to a stored
    record, and the identifiers are resolved strictly left to right, so the
    outermost segment's 404 always wins over an inner segment's. The code names
    the entity that could not be found: `ERR_APPLICANT_NOT_FOUND`,
    `ERR_APPLICATION_NOT_FOUND`, `ERR_VERIFICATION_NOT_FOUND`,
    `ERR_SLOT_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`,
    `ERR_BOOKING_NOT_FOUND`, `ERR_DETERMINATION_NOT_FOUND`,
    `ERR_APPEAL_NOT_FOUND`, `ERR_TRIP_EVENT_NOT_FOUND`,
    `ERR_PROCEEDING_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND` or
    `ERR_VISITOR_RECORD_NOT_FOUND`, each with HTTP 404."

    "The server screens every request through the following stages in this exact
    order, and returns the first failure it finds:"

    Design: Corner/errors/every_declared_not_found_id_is_reachable_with_an_unknown_path_parameter
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Viktor Salazar",
        date_of_birth="1959-09-09",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="CANE",
    )
    context = draft_application(
        api,
        applicant=rider,
        functional_answers=factories.functional_answers(
            can_navigate_unfamiliar_route=True, max_walk_distance_meters=170
        ),
    )
    application_id = context["application"]["id"]

    validate_error(
        api.get_applicant(_UNKNOWN.format(1), CLERK_HEADERS),
        ERR_APPLICANT_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_application(_UNKNOWN.format(2), CLERK_HEADERS),
        ERR_APPLICATION_NOT_FOUND,
        404,
    )
    nested = validate_error(
        api.receive_verification(
            application_id,
            _UNKNOWN.format(3),
            factories.verification_accepted_payload(
                attests_conditions=["limited stamina"], attests_permanent=True
            ),
            CLERK_HEADERS,
        ),
        ERR_VERIFICATION_NOT_FOUND,
        404,
    )
    assert isinstance(nested["message"], str)
    validate_error(
        api.get_assessment_slot(_UNKNOWN.format(4), CLERK_HEADERS),
        ERR_SLOT_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_assessment(_UNKNOWN.format(5), CLERK_HEADERS),
        ERR_ASSESSMENT_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_vehicle(_UNKNOWN.format(6), CLERK_HEADERS),
        ERR_VEHICLE_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_transportation_booking(_UNKNOWN.format(7), CLERK_HEADERS),
        ERR_BOOKING_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_determination(_UNKNOWN.format(8), CLERK_HEADERS),
        ERR_DETERMINATION_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_appeal(_UNKNOWN.format(9), ADMIN_HEADERS),
        ERR_APPEAL_NOT_FOUND,
        404,
    )
    validate_error(
        api.excuse_trip_event(
            _UNKNOWN.format(10),
            factories.excuse_payload(excuse_reason="unknown event"),
            CONDUCT_OFFICER_HEADERS,
        ),
        ERR_TRIP_EVENT_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_suspension_proceeding(_UNKNOWN.format(11), CONDUCT_OFFICER_HEADERS),
        ERR_PROCEEDING_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_travel_training_referral(_UNKNOWN.format(12), TRAINER_HEADERS),
        ERR_REFERRAL_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_visitor_eligibility(_UNKNOWN.format(13), CLERK_HEADERS),
        ERR_VISITOR_RECORD_NOT_FOUND,
        404,
    )

    application = validate_success(api.get_application(application_id, CLERK_HEADERS))
    assert application["status"] == "DRAFT"
    assert application["version"] == 1

    _verifications, meta = validate_paginated(
        api.list_verifications(application_id, CLERK_HEADERS)
    )
    assert meta["total_count"] == 0


def test_a_missing_or_undeclared_role_header_is_unauthenticated_first(api):
    """Authentication outranks even the not-found sweep on an unknown id.

    "Every request to every endpoint must carry two headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, naming the role that user is
    acting in. If either header is absent, or if `X-User-Role` is not one of the
    eight declared role names, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    "These two checks run before everything else — before resource lookup, before
    request-shape validation, and before any state check."

    "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/errors/a_missing_or_undeclared_role_header_is_unauthenticated_before_anything_else
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Wanda Kirchner",
        date_of_birth="1966-06-16",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="NONE",
    )

    no_role = validate_error(
        api.get_applicant(_UNKNOWN.format(21), headers_without_role("clerk-1")),
        ERR_UNAUTHENTICATED,
        401,
    )
    assert isinstance(no_role["message"], str)

    undeclared = validate_error(
        api.get_applicant(
            rider["id"], headers_with_undeclared_role("ghost-1", "PhantomRole")
        ),
        ERR_UNAUTHENTICATED,
        401,
    )
    assert isinstance(undeclared["message"], str)

    no_user = validate_error(
        api.get_applicant(rider["id"], headers_without_user_id("IntakeClerk")),
        ERR_UNAUTHENTICATED,
        401,
    )
    assert isinstance(no_user["message"], str)

    unchanged = validate_success(api.get_applicant(rider["id"], CLERK_HEADERS))
    assert unchanged["version"] == 1
    assert unchanged["current_eligibility_status"] == "NONE"


def test_roles_outside_an_endpoints_list_are_forbidden_before_any_effect(api):
    """Three well-formed payloads are refused on the role list alone.

    "When both headers are well formed but the acting role is not among the roles
    the addressed endpoint authorizes, the rejection is `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."

    "Every resource also carries `created_at`, an ISO 8601 UTC timestamp with
    three fractional digits recorded at creation from the logical clock."

    "The conflict test treats each slot as a closed interval expanded by that
    buffer on both sides: the new slot conflicts with an existing one when the
    new slot's start falls earlier than the existing slot's end extended forward
    by 15 minutes **and** the existing slot's start falls earlier than the new
    slot's end extended forward by 15 minutes."

    Design: Corner/errors/roles_outside_an_endpoints_list_are_forbidden_at_priority_two
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    slot_payload = factories.assessment_slot_payload(
        site_name="Central Mobility Center",
        evaluator_user_id="eval-1",
        starts_at="2026-08-05T09:00:00Z",
        ends_at="2026-08-05T10:00:00Z",
        capacity=2,
        site_is_wheelchair_accessible=True,
    )

    validate_error(
        api.create_assessment_slot(slot_payload, TRAINER_HEADERS),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api.set_clock(
            factories.clock_payload(current_utc="2026-09-01T00:00:00Z"),
            EVALUATOR_HEADERS,
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(api.day_close(CLERK_HEADERS), ERR_FORBIDDEN_ROLE, 403)

    rider = create_applicant(
        api,
        full_name="Wanda Kirchner",
        date_of_birth="1966-06-16",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="NONE",
    )
    assert rider["created_at"] == "2026-08-01T00:00:00.000Z"

    published = validate_success(
        api.create_assessment_slot(slot_payload, ADMIN_HEADERS), 201
    )
    assert published["status"] == "OPEN"
    assert published["booked_count"] == 0

    sweep = validate_success(api.day_close(ADMIN_HEADERS))
    assert_all_sweep_counters_present(sweep)


def test_an_applicant_cannot_read_or_act_on_another_applicants_records(api):
    """Ownership is decided per addressed resource, on reads and on writes alike.

    "Concretely, an `Applicant` may read and act only where the owning applicant
    matches: an `Application` through its `applicant_id`, a `Determination`
    through its `applicant_id`, an `Appeal` through the applicant of the
    determination it contests, a `SuspensionProceeding` through its
    `applicant_id`, a `VisitorEligibility` through its `applicant_id`, and a
    `FunctionalAssessment` through the `applicant_id` of the application being
    assessed. A mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    "This ownership rule guards exactly fifteen operations: fetching one
    applicant, fetching one application, listing applications, fetching one
    determination, listing determinations, listing a determination's trip
    conditions, listing a determination's appeals, listing a rider's trip events,
    listing a rider's suspension proceedings, listing a rider's
    visitor-eligibility records, opening an application, submitting an
    application, filing an appeal, responding to a suspension notice, and
    responding to a travel-training referral."

    Design: Corner/errors/an_applicant_cannot_read_another_applicants_records
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider_a = create_applicant(
        api,
        full_name="Xenia Marchetti",
        date_of_birth="1947-07-27",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="WALKER",
    )
    rider_b = create_applicant(
        api,
        full_name="Yusuf Karim",
        date_of_birth="1983-03-13",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="NONE",
    )
    context = issued_determination(
        api,
        applicant=rider_a,
        functional_answers=factories.functional_answers(
            can_board_bus_steps=False,
            can_navigate_unfamiliar_route=False,
            max_walk_distance_meters=100,
            uses_mobility_aid_outdoors=True,
            has_cognitive_impairment=False,
        ),
        claimed_conditions=["severe osteoarthritis"],
        score_overrides={
            "board_alight_score": 1,
            "wayfinding_score": 3,
            "distance_meters_walked": 100,
            "heat_sensitivity_flag": False,
        },
        draft_overrides={
            "category": "UNCONDITIONAL",
            "effective_date": "2026-08-06",
            "rationale": "cannot board steps",
        },
    )
    application_id = context["application"]["id"]
    determination_id = context["determination"]["id"]
    ingest_trip_event(
        api, rider_a["id"], trip_date="2026-08-04", event_type="COMPLETED"
    )

    intruder = make_applicant_headers(rider_b["id"])
    validate_error(
        api.get_application(application_id, intruder), ERR_NOT_RESOURCE_OWNER, 403
    )
    validate_error(
        api.get_determination(determination_id, intruder), ERR_NOT_RESOURCE_OWNER, 403
    )
    validate_error(
        api.list_trip_events(rider_a["id"], intruder), ERR_NOT_RESOURCE_OWNER, 403
    )
    validate_error(
        api.create_appeal(
            factories.appeal_payload(
                determination_id, grounds="not my determination"
            ),
            intruder,
        ),
        ERR_NOT_RESOURCE_OWNER,
        403,
    )

    _appeals, appeal_meta = validate_paginated(
        api.list_determination_appeals(determination_id, ADMIN_HEADERS)
    )
    assert appeal_meta["total_count"] == 0

    owner = make_applicant_headers(rider_a["id"])
    own_application = validate_success(api.get_application(application_id, owner))
    assert own_application["status"] == "DETERMINED"
    own_determination = validate_success(api.get_determination(determination_id, owner))
    assert own_determination["status"] == "ISSUED"
    assert own_determination["category"] == "UNCONDITIONAL"


def test_receiving_the_same_verification_twice_is_a_verification_state_error(api):
    """Two rules share the state stage, and the replay keys them apart.

    "Only one request may be outstanding at a time: if any verification of this
    packet is still in `REQUESTED`, the new request is refused with
    `ERR_VERIFICATION_PENDING` (409)."

    "The verification must still be in `REQUESTED`; a second response against an
    already-answered verification is `ERR_VERIFICATION_STATE_INVALID` (409)."

    "The verification moves `REQUESTED → RECEIVED`, `received_at` is stamped from
    the clock, and `wait_days` is computed as the whole days elapsed from
    `requested_at` to `received_at`, discarding any partial day."

    "That re-request is the second self-loop on `PENDING_VERIFICATION`: it is
    permitted when no verification of the packet is in `REQUESTED` and at least
    one is in `INSUFFICIENT`, it creates a fresh record in `REQUESTED` with a new
    `requested_at`, and it leaves the packet's `status` and
    `completeness_established_at` exactly as they were."

    Design: Corner/errors/receiving_the_same_verification_twice_is_a_verification_state_error
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Zofia Wieczorek",
        date_of_birth="1971-11-11",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="CANE",
    )
    context = submitted_application(
        api,
        applicant=rider,
        functional_answers=factories.functional_answers(
            can_navigate_unfamiliar_route=True, max_walk_distance_meters=130
        ),
        claimed_conditions=["lumbar stenosis"],
    )
    application_id = context["application"]["id"]

    verification = validate_success(
        api.request_verification(
            application_id,
            factories.verification_request_payload(
                provider_name="Dr. R Aguilar",
                provider_type="PHYSICIAN",
                provider_license_number="MD-90028",
            ),
            CLERK_HEADERS,
        ),
        201,
    )
    assert verification["status"] == "REQUESTED"

    second_request = factories.verification_request_payload(
        provider_name="Dr. S Lindgren",
        provider_type="OCCUPATIONAL_THERAPIST",
        provider_license_number="OT-3301",
    )
    validate_error(
        api.request_verification(application_id, second_request, CLERK_HEADERS),
        ERR_VERIFICATION_PENDING,
        409,
    )

    response = factories.verification_accepted_payload(
        attests_conditions=["lumbar stenosis"], attests_permanent=True
    )
    received = validate_success(
        api.receive_verification(
            application_id, verification["id"], response, CLERK_HEADERS
        )
    )
    assert received["status"] == "RECEIVED"
    assert received["wait_days"] == 0

    validate_error(
        api.receive_verification(
            application_id, verification["id"], response, CLERK_HEADERS
        ),
        ERR_VERIFICATION_STATE_INVALID,
        409,
    )

    application = validate_success(api.get_application(application_id, CLERK_HEADERS))
    assert application["status"] == "ASSESSMENT_REQUIRED"
    assert application["attests_permanent"] is True

    validate_error(
        api.request_verification(application_id, second_request, CLERK_HEADERS),
        ERR_INVALID_APPLICATION_STATE,
        409,
    )

    verifications, meta = validate_paginated(
        api.list_verifications(application_id, CLERK_HEADERS)
    )
    assert meta["total_count"] == 1
    assert verifications[0]["id"] == verification["id"]
