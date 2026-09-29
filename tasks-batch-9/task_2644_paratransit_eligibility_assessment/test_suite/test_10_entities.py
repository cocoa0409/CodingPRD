"""Field-level behaviour of the records the workflow is built out of."""
from test_helpers import (
    factories,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import (
    ERR_APPLICANT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_SLOT_IN_PAST,
    ERR_SLOT_NOT_FOUND,
    ERR_VEHICLE_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_applicant_shape,
    assert_conduct_mirrors,
    assert_creation_timestamp,
)
from test_helpers.fixtures import (
    assessment_required,
    create_applicant,
    scheduled_assessment,
    set_clock,
    submitted_application,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    CLERK_HEADERS,
    CONDUCT_OFFICER_HEADERS,
)

_UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"


def test_registering_a_rider_publishes_every_mirror_at_its_starting_value(api):
    """A fresh rider carries zeros and enums, never nulls or absent keys.

    "All of the rider's derived mirrors take the starting values listed in §2.10,
    and the new record's `version` is 1."

    "The conduct mirrors are recomputed together, on every trip-event ingestion, on
    every excusal, and on every read of the rider: `no_show_points_event_basis` and
    `no_show_points_report_basis` (both starting at 0), `chargeable_miss_count_90d`
    and `scheduled_trip_count_90d` (both starting at 0), and `no_show_ratio_pct`
    (starting at 0.0)."

    Design: Corner/entities/applicant_create_returns_every_declared_field_at_version_one
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = validate_success(
        api.create_applicant(
            factories.applicant_payload(
                full_name="Aurelia Vance",
                date_of_birth="1957-04-11",
                residence_zone="IN_SERVICE_AREA",
                mobility_aid="WALKER",
                primary_language="en",
                home_agency_name="Metro Transit",
            ),
            CLERK_HEADERS,
        ),
        201,
    )

    assert_applicant_shape(rider)
    assert rider["full_name"] == "Aurelia Vance"
    assert rider["residence_zone"] == "IN_SERVICE_AREA"
    assert rider["mobility_aid"] == "WALKER"
    assert rider["primary_language"] == "en"
    assert rider["version"] == 1
    assert rider["created_at"] == "2026-08-01T00:00:00.000Z"
    assert rider["updated_at"] == "2026-08-01T00:00:00.000Z"

    assert rider["current_eligibility_status"] == "NONE"
    assert rider["eligibility_category"] is None
    assert rider["active_determination_id"] is None
    assert rider["service_status"] == "ACTIVE"
    assert_conduct_mirrors(
        rider,
        event_basis=0,
        report_basis=0,
        miss_count=0,
        scheduled_count=0,
        ratio_pct=0.0,
    )
    assert rider["prior_upheld_suspension_count"] == 0
    assert rider["suspension_days_ledger_total"] == 0
    assert rider["fixed_route_competency_confirmed"] is False
    assert rider["continued_service_during_appeal"] is False


def test_reading_a_rider_leaves_the_version_and_the_timestamps_alone(api):
    """A read is not a mutation, so nothing about the row moves.

    "Most resources additionally carry `updated_at`, an ISO 8601 UTC timestamp
    refreshed on every mutation, and `version`, an integer that begins at 1 when
    the record is created and increments by exactly one on every mutation of that
    record — including mutations produced as a side effect of an operation
    addressed at a different resource."

    Design: Corner/entities/applicant_get_by_id_returns_the_stored_row_unchanged
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Bram Odell",
        date_of_birth="1944-02-29",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="CANE",
    )

    set_clock(api, "2026-08-02T00:00:00Z")
    read = validate_success(api.get_applicant(rider["id"], CLERK_HEADERS))

    assert read["id"] == rider["id"]
    assert read["full_name"] == "Bram Odell"
    assert read["version"] == 1
    assert read["created_at"] == "2026-08-01T00:00:00.000Z"
    assert read["updated_at"] == "2026-08-01T00:00:00.000Z"


def test_the_application_listing_pages_three_drafts_and_filters_by_rider(api):
    """total_count counts the filter, has_more counts what is left after the page.

    "Every list response carries `limit`, `offset`, `total_count` and `has_more`
    inside `meta`. The `total_count` is the number of records matching the
    request's filters before the page window is applied, and `has_more` is true
    exactly when records matching the filters remain beyond the current page."

    "`limit` is an integer bounded to the inclusive range 1 through 100 and
    defaults to 10 when omitted."

    Design: Corner/entities/applications_list_returns_pagination_envelope_with_has_more
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    first = create_applicant(
        api, full_name="Rider One", date_of_birth="1950-01-02", mobility_aid="NONE"
    )
    second = create_applicant(
        api, full_name="Rider Two", date_of_birth="1951-03-04", mobility_aid="CANE"
    )
    third = create_applicant(
        api, full_name="Rider Three", date_of_birth="1952-05-06", mobility_aid="WALKER"
    )
    for rider, answers in (
        (first, factories.functional_answers(max_walk_distance_meters=120)),
        (
            second,
            factories.functional_answers(
                can_navigate_unfamiliar_route=True, max_walk_distance_meters=300
            ),
        ),
        (
            third,
            factories.functional_answers(
                can_board_bus_steps=True,
                max_walk_distance_meters=500,
                uses_mobility_aid_outdoors=False,
                has_cognitive_impairment=True,
            ),
        ),
    ):
        validate_success(
            api.create_application(
                factories.application_payload(rider["id"], functional_answers=answers),
                CLERK_HEADERS,
            ),
            201,
        )

    page_one, meta_one = validate_paginated(
        api.list_applications(CLERK_HEADERS, params={"limit": 2, "offset": 0})
    )
    assert meta_one["limit"] == 2
    assert meta_one["offset"] == 0
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True
    assert len(page_one) == 2

    page_two, meta_two = validate_paginated(
        api.list_applications(CLERK_HEADERS, params={"limit": 2, "offset": 2})
    )
    assert meta_two["limit"] == 2
    assert meta_two["offset"] == 2
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False
    assert len(page_two) == 1

    filtered, meta_filtered = validate_paginated(
        api.list_applications(CLERK_HEADERS, params={"applicant_id": second["id"]})
    )
    assert meta_filtered["total_count"] == 1
    assert meta_filtered["has_more"] is False
    assert meta_filtered["limit"] == 10
    assert filtered[0]["applicant_id"] == second["id"]

    for application in page_one + page_two:
        assert application["status"] == "DRAFT"
        assert application["days_pending_statutory"] == 0
        assert application["completeness_established_at"] is None
        assert application["determination_due_date"] is None


def test_an_unminted_rider_id_answers_with_the_applicant_not_found_error(api):
    """The miss is entity-specific and leaves the stored rows readable.

    "**Path existence.** Every identifier appearing in the request path must
    resolve to a stored record, and the identifiers are resolved strictly left to
    right, so the outermost segment's 404 always wins over an inner segment's."

    "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/entities/applicant_get_with_unknown_uuid_returns_applicant_not_found
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    other = create_applicant(
        api, full_name="Unrelated Rider", date_of_birth="1960-06-06"
    )

    error = validate_error(
        api.get_applicant(_UNKNOWN_UUID, CLERK_HEADERS), ERR_APPLICANT_NOT_FOUND, 404
    )
    assert isinstance(error["message"], str)
    assert error["message"] != ""

    still_there = validate_success(api.get_applicant(other["id"], CLERK_HEADERS))
    assert still_there["id"] == other["id"]


def test_a_vehicle_registered_with_only_its_number_takes_the_declared_defaults(api):
    """Both capacities default to zero and the vehicle is born in service.

    "An `AccessibilityOfficeAdmin` registers a vehicle by its `vehicle_number`,
    with `wheelchair_positions` counting securement positions on board and
    `ambulatory_seats` counting non-securement seats; both are optional, default to
    zero, and may not be negative. `status` is optional and defaults to
    `IN_SERVICE`; the only other value is `OUT_OF_SERVICE`. Both open-reservation
    counters start at zero."

    Design: Corner/entities/vehicle_create_omitting_optional_fields_applies_declared_defaults
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    vehicle = validate_success(
        api.create_vehicle({"vehicle_number": "V-9100"}, ADMIN_HEADERS), 201
    )

    assert vehicle["vehicle_number"] == "V-9100"
    assert vehicle["status"] == "IN_SERVICE"
    assert vehicle["wheelchair_positions"] == 0
    assert vehicle["ambulatory_seats"] == 0
    assert vehicle["open_wheelchair_reservations"] == 0
    assert vehicle["open_ambulatory_reservations"] == 0
    assert vehicle["version"] == 1


def test_a_trip_event_ignores_client_supplied_points_stamps_and_excusals(api):
    """The three computed fields are the server's, whatever the client sends.

    "The event is stored with `recorded_at` stamped from the logical clock,
    `excused` false, `excuse_reason` null, and `points_assessed` set to 2 for an
    unexcused `NO_SHOW`, 1 for an unexcused `LATE_CANCEL`, and 0 for every other
    event type."

    "A miss beyond the rider's control can be excused afterwards by the same two
    roles, supplying an `excuse_reason`."

    Design: Corner/entities/trip_event_points_assessed_is_computed_and_client_input_ignored
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api, full_name="Dov Halperin", date_of_birth="1972-09-09"
    )

    event = validate_success(
        api.create_trip_event(
            {
                "applicant_id": rider["id"],
                "trip_date": "2026-07-30",
                "event_type": "LATE_CANCEL",
                "points_assessed": 99,
                "recorded_at": "1999-01-01T00:00:00Z",
                "excused": True,
            },
            CONDUCT_OFFICER_HEADERS,
        ),
        201,
    )

    assert event["points_assessed"] == 1
    assert event["recorded_at"] == "2026-08-01T00:00:00.000Z"
    assert event["excused"] is False
    assert event["excuse_reason"] is None

    rider = validate_success(api.get_applicant(rider["id"], CLERK_HEADERS))
    assert rider["no_show_points_event_basis"] == 1
    assert rider["scheduled_trip_count_90d"] == 1


def test_a_rider_create_that_supplies_system_fields_has_them_all_overwritten(api):
    """Identity, stamps and version belong to the server alone.

    "Every resource is assigned a server-minted UUID as its `id`. Identifiers carry
    no type prefix and are never supplied by the client. Every resource also
    carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits
    recorded at creation from the logical clock."

    Design: Corner/entities/applicant_system_fields_are_server_minted_and_client_input_ignored
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = validate_success(
        api.create_applicant(
            factories.applicant_payload(
                full_name="Esme Radcliffe",
                date_of_birth="1948-12-24",
                mobility_aid="NONE",
                id="applicant-supplied-id",
                created_at="1990-01-01T00:00:00Z",
                version=77,
            ),
            CLERK_HEADERS,
        ),
        201,
    )

    assert rider["id"] != "applicant-supplied-id"
    assert is_valid_uuid(rider["id"])
    assert_creation_timestamp(rider["created_at"])
    assert rider["created_at"] == "2026-08-01T00:00:00.000Z"
    assert rider["updated_at"] == "2026-08-01T00:00:00.000Z"
    assert rider["version"] == 1

    validate_error(
        api.get_applicant("applicant-supplied-id", CLERK_HEADERS),
        ERR_APPLICANT_NOT_FOUND,
        404,
    )


def test_a_residence_zone_outside_the_closed_enum_is_refused(api):
    """The zone has exactly two legal tokens and no row survives a third.

    "An `IntakeClerk` or an `AccessibilityOfficeAdmin` records the rider's
    `full_name` and `date_of_birth` — the latter as an ISO 8601 calendar date in
    year-month-day form — together with `residence_zone`, which is either
    `IN_SERVICE_AREA` or `OUT_OF_SERVICE_AREA` and states whether the rider lives
    inside the agency's ADA complementary service area."

    Design: Corner/entities/applicant_unknown_residence_zone_enum_value_is_rejected
    """
    set_clock(api, "2026-08-01T00:00:00Z")

    validate_error(
        api.create_applicant(
            factories.applicant_payload(
                full_name="Faisal Rahman",
                date_of_birth="1965-05-05",
                residence_zone="SUBURBAN_FRINGE",
                mobility_aid="NONE",
            ),
            CLERK_HEADERS,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    accepted = validate_success(
        api.create_applicant(
            factories.applicant_payload(
                full_name="Faisal Rahman",
                date_of_birth="1965-05-05",
                residence_zone="OUT_OF_SERVICE_AREA",
                mobility_aid="NONE",
            ),
            CLERK_HEADERS,
        ),
        201,
    )
    assert accepted["residence_zone"] == "OUT_OF_SERVICE_AREA"
    assert accepted["version"] == 1


def test_an_inverted_slot_interval_is_a_request_shape_error_and_a_past_slot_is_not(api):
    """The interval check answers 400 while the clock check answers 422.

    "A slot names its `site_name`, the `evaluator_user_id` of the evaluator who
    staffs it, a `starts_at` and `ends_at` pair of UTC instants with the end
    strictly after the start, and a `capacity` of at least one assessment."

    "A slot whose `starts_at` is not strictly after the logical clock's current
    instant is refused with `ERR_SLOT_IN_PAST` (422)."

    Design: Corner/entities/assessment_slot_with_ends_at_before_starts_at_is_rejected
    """
    set_clock(api, "2026-08-01T00:00:00Z")

    validate_error(
        api.create_assessment_slot(
            factories.assessment_slot_payload(
                starts_at="2026-08-05T11:00:00Z", ends_at="2026-08-05T10:00:00Z"
            ),
            ADMIN_HEADERS,
        ),
        ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_assessment_slot(
            factories.assessment_slot_payload(
                starts_at="2026-07-20T09:00:00Z", ends_at="2026-07-20T10:00:00Z"
            ),
            ADMIN_HEADERS,
        ),
        ERR_SLOT_IN_PAST,
        422,
    )


def test_booking_an_assessment_onto_an_unknown_slot_names_the_slot(api):
    """The body reference is resolved before any capacity or safety rule.

    "**Body reference existence.** Every reference carried in a request body —
    `applicant_id`, `application_id`, `slot_id`, `vehicle_id`, `assessment_id`,
    `determination_id` — must resolve to a stored record."

    Design: Corner/entities/assessment_create_with_unknown_slot_id_returns_slot_not_found
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Gita Naraine",
        date_of_birth="1959-08-08",
        mobility_aid="WALKER",
    )
    context = assessment_required(api, applicant=rider)
    assert context["application"]["status"] == "ASSESSMENT_REQUIRED"

    validate_error(
        api.book_assessment(
            context["application"]["id"],
            factories.assessment_booking_payload(
                "00000000-0000-4000-8000-0000000000aa",
                requires_wheelchair_position=False,
            ),
            CLERK_HEADERS,
        ),
        ERR_SLOT_NOT_FOUND,
        404,
    )

    unchanged = validate_success(
        api.get_application(context["application"]["id"], CLERK_HEADERS)
    )
    assert unchanged["status"] == "ASSESSMENT_REQUIRED"

    _rows, meta = validate_paginated(
        api.list_assessments(
            CLERK_HEADERS, params={"application_id": context["application"]["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_reserving_a_ride_on_an_unknown_vehicle_names_the_vehicle(api):
    """A good assessment_id paired with a bad vehicle_id resolves to the vehicle.

    "The affected operations are opening an application, booking an assessment,
    reserving a ride, filing an appeal, ingesting a trip event, and referring a
    rider to travel training; the codes are the corresponding not-found
    identifiers with HTTP 404."

    Design: Corner/entities/booking_create_with_unknown_vehicle_id_returns_vehicle_not_found
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api, full_name="Hana Ito", date_of_birth="1962-11-11", mobility_aid="CANE"
    )
    context = scheduled_assessment(api, applicant=rider)

    validate_error(
        api.create_transportation_booking(
            factories.transportation_booking_payload(
                context["assessment"]["id"],
                "00000000-0000-4000-8000-0000000000bb",
                pickup_window_end="2026-08-05T09:00:00Z",
                requires_wheelchair_position=False,
            ),
            CLERK_HEADERS,
        ),
        ERR_VEHICLE_NOT_FOUND,
        404,
    )

    _rows, meta = validate_paginated(
        api.list_transportation_bookings(
            CLERK_HEADERS, params={"assessment_id": context["assessment"]["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert meta["has_more"] is False

    assessment = validate_success(
        api.get_assessment(context["assessment"]["id"], CLERK_HEADERS)
    )
    assert assessment["attendance_status"] == "SCHEDULED"
    assert assessment["scoring_status"] == "NOT_STARTED"


def test_the_verification_wait_starts_at_zero_and_lands_on_whole_days_only(api):
    """Five and a half days of waiting are published as five.

    "The new record starts in `REQUESTED` with `requested_at` stamped from the
    logical clock, `received_at` null, `wait_days` zero, and `attests_conditions`,
    `attests_permanent` and `insufficiency_reason` all null."

    "The verification moves `REQUESTED → RECEIVED`, `received_at` is stamped from
    the clock, and `wait_days` is computed as the whole days elapsed from
    `requested_at` to `received_at`, discarding any partial day. That figure is
    added to the packet's `verification_excluded_days`."

    Design: Corner/entities/verification_wait_days_computed_from_request_and_receive_instants
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Ines Barrera",
        date_of_birth="1953-01-31",
        mobility_aid="WALKER",
    )
    context = submitted_application(
        api,
        applicant=rider,
        functional_answers=factories.functional_answers(
            max_walk_distance_meters=180
        ),
    )
    requested = validate_success(
        api.request_verification(
            context["application"]["id"],
            factories.verification_request_payload(
                provider_name="Dr. M Farrow",
                provider_type="OCCUPATIONAL_THERAPIST",
                provider_license_number="OT-4102",
            ),
            CLERK_HEADERS,
        ),
        201,
    )
    assert requested["status"] == "REQUESTED"
    assert requested["requested_at"] == "2026-08-01T00:00:00.000Z"
    assert requested["received_at"] is None
    assert requested["wait_days"] == 0

    set_clock(api, "2026-08-06T12:00:00Z")
    received = validate_success(
        api.receive_verification(
            context["application"]["id"],
            requested["id"],
            factories.verification_accepted_payload(
                attests_conditions=["post-stroke hemiparesis"], attests_permanent=True
            ),
            CLERK_HEADERS,
        )
    )
    assert received["status"] == "RECEIVED"
    assert received["received_at"] == "2026-08-06T12:00:00.000Z"
    assert received["wait_days"] == 5

    application = validate_success(
        api.get_application(context["application"]["id"], CLERK_HEADERS)
    )
    assert application["verification_excluded_days"] == 5
    assert application["attests_permanent"] is True
    assert application["days_pending_statutory"] == 5
    assert application["days_pending_net_agency"] == 0
    assert application["status"] == "ASSESSMENT_REQUIRED"


def test_a_new_visitor_record_opens_with_a_full_allowance_of_days(api):
    """Twenty-one days remain, none are used, and the rider reads VISITOR.

    "A new visitor record starts in `ACTIVE` with an empty `service_dates` list,
    `days_used_365` at 0 and `days_remaining_365` at 21. Where the rider holds no
    determination in `ISSUED` at all, their `current_eligibility_status` becomes
    `VISITOR`; where they hold an `INELIGIBLE` one, that status is left as it
    stands."

    Design: Corner/entities/visitor_eligibility_create_initializes_the_rolling_day_counters
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Jonas Wexler",
        date_of_birth="1946-10-10",
        residence_zone="OUT_OF_SERVICE_AREA",
        mobility_aid="MANUAL_WHEELCHAIR",
        home_agency_name="Lakeshore RTA",
    )

    record = validate_success(
        api.create_visitor_eligibility(
            rider["id"],
            factories.visitor_eligibility_payload(
                home_agency_name="Lakeshore RTA",
                home_agency_certification_provided=True,
                visit_start_date="2026-08-01",
            ),
            CLERK_HEADERS,
        ),
        201,
    )

    assert record["status"] == "ACTIVE"
    assert record["service_dates"] == []
    assert record["days_used_365"] == 0
    assert record["days_remaining_365"] == 21
    assert record["home_agency_certification_provided"] is True
    assert record["visit_start_date"] == "2026-08-01"

    rider = validate_success(api.get_applicant(rider["id"], CLERK_HEADERS))
    assert rider["current_eligibility_status"] == "VISITOR"
    assert rider["eligibility_category"] is None

    _rows, meta = validate_paginated(
        api.list_visitor_eligibilities(rider["id"], CLERK_HEADERS)
    )
    assert meta["total_count"] == 1
