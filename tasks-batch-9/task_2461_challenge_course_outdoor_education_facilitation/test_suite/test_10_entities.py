"""Entity surfaces: declared defaults, computed fields, reads, listing and shape rejections."""

from test_helpers import (
    ERR_BOOKING_NOT_FOUND,
    ERR_COURSE_NOT_FOUND,
    ERR_ELEMENT_COURSE_MISMATCH,
    ERR_INVALID_REQUEST,
    assert_append_only_record,
    assert_belay_requirement,
    assert_course_counters,
    assert_element_forecast,
    assert_error_envelope_meta,
    assert_ledger,
    assert_posture,
    assert_versioned_record,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import (
    CLIENT_NAME,
    CLOCK_TEST_DATE,
    CLOCK_TEST_UTC,
    COURSE_EMS_MINUTES,
    COURSE_NAME_PRIMARY,
    COURSE_NAME_SECONDARY,
    COURSE_NOTE_SECONDARY,
    ELEMENT_NAME_GROUND,
    ELEMENT_NAME_LOW,
    ELEMENT_NAME_LOW_ALT,
    MINOR_NAME,
)
from test_helpers.factories import (
    belay_equipment_payload,
    course_payload,
    element_payload,
    facilitator_payload,
    group_client_payload,
    participant_payload,
    program_block_payload,
)
from test_helpers.fixtures import (
    add_blocks,
    clear_log,
    create_booking,
    create_course,
    create_element,
    create_funded_client,
    create_safety_officer,
    create_staff_facilitator,
    set_clock,
)
from test_helpers.test_users import (
    PROGRAM_DIRECTOR,
    make_facilitator_headers,
    make_group_coordinator_headers,
    make_safety_officer_headers,
)

CLIENT_SUPPLIED_ID = "11111111-1111-4111-8111-111111111111"
UNKNOWN_BOOKING_ID = "00000000-0000-4000-8000-000000000abc"
UNKNOWN_COURSE_ID = "00000000-0000-4000-8000-0000000000ff"


class TestCourseCreationDefaults:
    """A fresh site reads its declared opening values, not a recomputed posture."""

    def test_a_new_course_returns_every_declared_default(self, api):
        """Nothing about the empty site is derived from observations that never happened.

        PRD 3.1: "The new site starts with `posture` `OPEN`, `posture_reason`
        `NONE`, `daily_open_index` zero, `last_daily_open_date` null,
        `lightning_hold_until` null and every derived counter —
        `restricted_element_count`, `out_of_service_element_count`,
        `quarantined_equipment_count`, `rescue_ready_facilitator_count`,
        `at_risk_booking_count` — at zero."

        PRD 3.1: "`latest_wind_speed_kph` starts at 0, `latest_air_temp_c` at 20,
        and `latest_lightning_distance_km`, `latest_observation_at` and
        `next_professional_inspection_due_on` all start null."

        PRD 3.1: "`rescue_readiness_ok` is derived immediately and is therefore
        false on a fresh site, since no facilitator holds active certification
        yet."

        Design: Corner/entities/create_course_returns_declared_defaults_for_every_computed_field
        """
        set_clock(api, CLOCK_TEST_UTC)

        course = validate_success(
            api.create_course(course_payload(), PROGRAM_DIRECTOR), 201
        )

        assert course["course_name"] == COURSE_NAME_PRIMARY
        assert course["ems_response_minutes"] == COURSE_EMS_MINUTES
        assert_posture(course, "OPEN", "NONE")
        assert course["daily_open_index"] == 0
        assert course["last_daily_open_date"] is None
        assert course["lightning_hold_until"] is None
        assert_course_counters(
            course, restricted=0, out_of_service=0, quarantined=0, at_risk_bookings=0
        )
        assert course["rescue_ready_facilitator_count"] == 0
        assert course["rescue_readiness_ok"] is False
        assert course["latest_wind_speed_kph"] == 0
        assert course["latest_air_temp_c"] == 20
        assert course["latest_lightning_distance_km"] is None
        assert course["latest_observation_at"] is None
        assert course["next_professional_inspection_due_on"] is None
        assert_versioned_record(course, version=1)


class TestElementReadBack:
    """The stored installation record and the lifecycle figures derived from it."""

    def test_reading_a_zero_usage_ground_initiative_returns_its_life_figures(self, api):
        """Both manufacturer limits are stamped from the type, and the calendar variant stands alone.

        PRD 3.1: "`design_life_years` is 20 years for a ground initiative, 15 for
        a low element, 12 for a high element, 15 for a climbing wall and 10 for a
        zip line."

        PRD 3.1: "`cycle_life_limit` — the participant-cycle count at which the
        element must leave service — is 43,800 for a ground initiative, 29,200 for
        a low element, 21,900 for a high element, 25,550 for a climbing wall and
        18,250 for a zip line."

        PRD 3.1: "The **calendar variant** produces `calendar_life_forecast_date`
        by adding `design_life_years` whole years to `installed_on`."

        PRD 3.1: "If the average daily rate is zero there is no history to project
        from, so `usage_life_forecast_date` is null and the calendar date stands
        alone."

        PRD 3.4: "Every element carries a `required_belay_set_count` derived from
        its type: zero for a ground initiative, zero for a low element, two for a
        high element, two for a climbing wall, three for a zip line."

        Design: Corner/entities/get_element_returns_stored_and_computed_lifecycle_fields
        """
        set_clock(api, CLOCK_TEST_UTC)
        course_id = create_course(api)
        g_id = create_element(api, course_id, "GROUND_INITIATIVE")

        element = validate_success(api.get_element(g_id, PROGRAM_DIRECTOR))

        assert element["element_name"] == ELEMENT_NAME_GROUND
        assert element["status"] == "SERVICEABLE"
        assert element["restricting_log_id"] is None
        assert element["design_life_years"] == 20
        assert element["cycle_life_limit"] == 43800
        assert element["cumulative_cycle_count"] == 0
        assert_element_forecast(
            element,
            calendar="2044-08-10",
            usage=None,
            forecast="2044-08-10",
            basis="CALENDAR",
        )
        assert_belay_requirement(element, required_sets=0, ready=True)
        assert element["latest_inspection_outcome"] == "NONE"


class TestElementListing:
    """Two equality filters combine, and the window is reported in `meta`."""

    def test_a_filtered_window_reports_the_total_before_pagination(self, api):
        """Three matching elements read through a window of two leave one behind.

        PRD 2.3: "The list-endpoint envelope reports `limit`, `offset`,
        `total_count` and `has_more` inside `meta`, where `total_count` counts the
        records matching the filters before pagination is applied and `has_more`
        states whether records remain beyond the current window."

        PRD 2.3: "Elements accept `course_id`, `status`, `element_type` and
        `restricting_log_id`."

        Design: Corner/entities/list_elements_filtered_by_course_and_status_returns_pagination_envelope
        """
        set_clock(api, CLOCK_TEST_UTC)
        course_id = create_course(api)
        so_id = create_safety_officer(api, course_id)
        create_element(api, course_id, "GROUND_INITIATIVE")
        create_element(api, course_id, "LOW_ELEMENT")
        create_element(api, course_id, "HIGH_ELEMENT")

        rows, meta = validate_paginated(
            api.list_elements(
                make_safety_officer_headers(so_id),
                params={
                    "course_id": course_id,
                    "status": "SERVICEABLE",
                    "limit": 2,
                    "offset": 0,
                },
            )
        )

        assert len(rows) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        assert all(row["course_id"] == course_id for row in rows)
        assert all(row["status"] == "SERVICEABLE" for row in rows)


class TestUnknownIdentifierReads:
    """A well-formed identifier that resolves to nothing is a 404, not an empty body."""

    def test_reading_a_booking_that_was_never_created_is_not_found(self, api):
        """Path resolution runs before anything else and names the booking code.

        PRD 2.8: "The mapping from path variable to error code is fixed:
        `course_id` yields `ERR_COURSE_NOT_FOUND`, `element_id` yields
        `ERR_ELEMENT_NOT_FOUND`, `facilitator_id` yields
        `ERR_FACILITATOR_NOT_FOUND`, `inspection_id` yields
        `ERR_INSPECTION_NOT_FOUND`, `log_id` yields
        `ERR_OPERATIONAL_LOG_NOT_FOUND`, `group_client_id` yields
        `ERR_GROUP_CLIENT_NOT_FOUND`, `booking_id` yields
        `ERR_BOOKING_NOT_FOUND`, `participant_id` yields
        `ERR_PARTICIPANT_NOT_FOUND`, `program_block_id` yields
        `ERR_PROGRAM_BLOCK_NOT_FOUND`, `equipment_id` yields
        `ERR_EQUIPMENT_NOT_FOUND`, `incident_id` yields
        `ERR_INCIDENT_NOT_FOUND`, `training_record_id` yields
        `ERR_TRAINING_RECORD_NOT_FOUND`, `block_assignment_id` yields
        `ERR_BLOCK_ASSIGNMENT_NOT_FOUND` and `observation_id` yields
        `ERR_WEATHER_OBSERVATION_NOT_FOUND`."

        PRD 2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/entities/get_booking_with_unknown_id_not_found
        """
        set_clock(api, CLOCK_TEST_UTC)
        create_course(api)

        response = api.get_booking(UNKNOWN_BOOKING_ID, PROGRAM_DIRECTOR)
        validate_error(response, ERR_BOOKING_NOT_FOUND, 404)
        assert_error_envelope_meta(response.json())


class TestElementRequestShape:
    """Request shape is checked before any foreign key or business rule."""

    def test_omitting_the_element_type_is_rejected_and_stores_nothing(self, api):
        """A required field with no declared default cannot be defaulted by the server.

        PRD 2.12: "Request shape: the body parses, every required field is
        present, every enum value belongs to its declared set, every number sits
        inside its declared range, `limit` is between 1 and 100 with a
        non-negative `offset`, and a block's `planned_start_at` is strictly before
        its `planned_end_at` — `ERR_INVALID_REQUEST`. Applies to every endpoint."

        PRD 2.3: "`total_count` counts the records matching the filters before
        pagination is applied"

        Design: Corner/entities/create_element_missing_required_element_type_rejected
        """
        set_clock(api, CLOCK_TEST_UTC)
        course_id = create_course(api)

        payload = element_payload(course_id, "LOW_ELEMENT", element_name=ELEMENT_NAME_LOW)
        payload.pop("element_type")

        validate_error(
            api.create_element(payload, PROGRAM_DIRECTOR),
            ERR_INVALID_REQUEST,
            400,
        )

        rows, meta = validate_paginated(
            api.list_elements(PROGRAM_DIRECTOR, params={"course_id": course_id})
        )
        assert meta["total_count"] == 0
        assert rows == []

    def test_an_element_type_outside_the_closed_enum_is_rejected(self, api):
        """`ROPES_COURSE` is not one of the five declared members.

        PRD 3.1: "classifies it with an `element_type` of `GROUND_INITIATIVE`,
        `LOW_ELEMENT`, `HIGH_ELEMENT`, `CLIMBING_WALL` or `ZIP_LINE`"

        PRD 2.12: "Request shape: the body parses, every required field is
        present, every enum value belongs to its declared set, every number sits
        inside its declared range, `limit` is between 1 and 100 with a
        non-negative `offset`, and a block's `planned_start_at` is strictly before
        its `planned_end_at` — `ERR_INVALID_REQUEST`. Applies to every endpoint."

        Design: Corner/entities/create_element_with_unknown_element_type_enum_rejected
        """
        set_clock(api, CLOCK_TEST_UTC)
        course_id = create_course(api)

        payload = element_payload(course_id, "LOW_ELEMENT", element_name=ELEMENT_NAME_LOW)
        payload["element_type"] = "ROPES_COURSE"

        validate_error(
            api.create_element(payload, PROGRAM_DIRECTOR),
            ERR_INVALID_REQUEST,
            400,
        )

        _, meta = validate_paginated(
            api.list_elements(PROGRAM_DIRECTOR, params={"course_id": course_id})
        )
        assert meta["total_count"] == 0


class TestParticipantCreationDefaults:
    """An unscreened person is blocked, and the blocking answer reaches the booking."""

    def test_a_participant_added_before_any_packet_is_blocked(self, api):
        """The declared defaults feed the screening walk, which feeds the roster walk.

        PRD 3.6: "A new participant opens with `health_form_status` `MISSING`,
        `agreement_signed` false, `guardian_signature_provided` false,
        `medical_clearance_granted` false, `health_flags` an empty list, and
        `screening_status` `BLOCKED`."

        PRD 3.6: "`age_years` is the participant's whole-year age **on the
        booking's `program_date`**, not on the day the record was created, so
        somebody who turns eighteen between enrolment and delivery counts as an
        adult. `is_minor` is true exactly when `age_years` is below eighteen."

        PRD 3.6: "A booking where any participant — chaperones included — is
        `BLOCKED` or `CONDITIONAL` is `BLOCKED`."

        Design: Corner/entities/participant_created_before_packet_defaults_to_missing_health_form
        """
        set_clock(api, CLOCK_TEST_UTC)
        course_id = create_course(api)
        gc_id = create_funded_client(api, amount_cents=0)
        b_id, b_version = create_booking(api, course_id, gc_id, 1)

        participant = validate_success(
            api.create_participant(
                participant_payload(b_id, b_version, "MINOR"),
                make_group_coordinator_headers(gc_id),
            ),
            201,
        )

        assert participant["full_name"] == MINOR_NAME
        assert participant["health_form_status"] == "MISSING"
        assert participant["agreement_signed"] is False
        assert participant["guardian_signature_provided"] is False
        assert participant["medical_clearance_granted"] is False
        assert participant["health_flags"] == []
        assert participant["age_years"] == 13
        assert participant["is_minor"] is True
        assert participant["screening_status"] == "BLOCKED"

        booking = validate_success(api.get_booking(b_id, PROGRAM_DIRECTOR))
        assert booking["roster_status"] == "BLOCKED"


class TestServerOwnedFields:
    """Fields the server derives or mints are never taken from the request body."""

    def test_a_supplied_supervision_capacity_is_replaced_by_the_level_derivation(self, api):
        """Capacity follows the certification ladder, not the caller's number.

        PRD 3.2: "The record's `supervision_capacity` is derived directly from the
        level: eight participants for `LEVEL_1`, twelve for `LEVEL_2`, sixteen for
        `LEVEL_3`."

        PRD 3.2: "Otherwise, if `rescue_drill_last_passed_on` is null, or more
        than 180 days have elapsed between the drill date and the clock date, or
        `refresher_hours_24mo` is below eight hours, the status is `PROBATION`."

        Design: Corner/entities/facilitator_supervision_capacity_computed_input_ignored
        """
        set_clock(api, CLOCK_TEST_UTC)
        course_id = create_course(api)

        facilitator = validate_success(
            api.create_facilitator(
                facilitator_payload(
                    course_id, "STAFF_FACILITATOR", supervision_capacity=99
                ),
                PROGRAM_DIRECTOR,
            ),
            201,
        )

        assert facilitator["certification_level"] == "LEVEL_2"
        assert facilitator["supervision_capacity"] == 12
        assert facilitator["cert_status"] == "PROBATION"
        assert facilitator["refresher_hours_24mo"] == 0
        assert facilitator["rescue_drill_last_passed_on"] is None

    def test_a_supplied_id_and_version_on_a_group_client_are_ignored(self, api):
        """The row opens at version 1 under a server-minted identifier.

        PRD 2.9: "Client-supplied values for `id`, `created_at`, `updated_at` or
        `version` are silently ignored rather than rejected."

        PRD 2.9: "a `version`: an integer that is 1 when the row is created and
        increases by exactly one on every mutating write to that row, including
        writes the server performs on its own initiative while settling a
        cascade."

        PRD 3.5: "A new client opens with `payments_received_cents` and
        `credit_balance_cents` both zero and `late_cancellation_count` zero."

        Design: Corner/entities/group_client_system_fields_input_ignored
        """
        set_clock(api, CLOCK_TEST_UTC)

        client = validate_success(
            api.create_group_client(
                group_client_payload(id=CLIENT_SUPPLIED_ID, version=47),
                PROGRAM_DIRECTOR,
            ),
            201,
        )

        assert client["client_name"] == CLIENT_NAME
        assert client["id"] != CLIENT_SUPPLIED_ID
        assert_versioned_record(client, version=1)
        assert_ledger(client, credit=0, payments=0)
        assert client["late_cancellation_count"] == 0


class TestAppendOnlyEvidence:
    """The four evidence types carry no version and no update route."""

    def test_a_stored_clear_log_reads_back_without_version_or_updated_at(self, api):
        """The log is narrower than a mutable row and still drives the element's clear date.

        PRD 2.9: "Four record types are immutable append-only evidence and are
        deliberately narrower: training records, operational inspection logs,
        block assignments and weather observations carry only `id` and
        `created_at`. They have no `updated_at`, no `version`, and no update or
        delete endpoint; once written they are never edited, and corrections are
        made by writing a further record."

        PRD 3.3: "A `CLEAR` result clears that element's daily-inspection gate for
        its `log_date` and updates `last_clear_log_date`, which tracks the
        `log_date` of the newest clear log for the element, ordered by `log_date`
        descending with `created_at` descending as the tie-break."

        PRD 3.3: "`caused_restriction` is false on every other log."

        Design: Corner/entities/operational_inspection_log_is_immutable_and_carries_no_version
        """
        set_clock(api, CLOCK_TEST_UTC)
        course_id = create_course(api)
        f1_id = create_staff_facilitator(api, course_id, trained=False)
        l_id = create_element(api, course_id, "LOW_ELEMENT", element_name=ELEMENT_NAME_LOW)
        written = clear_log(api, l_id, f1_id, make_facilitator_headers(f1_id))

        log = validate_success(api.get_operational_log(written["id"], PROGRAM_DIRECTOR))

        assert log["result"] == "CLEAR"
        assert log["caused_restriction"] is False
        assert_append_only_record(log)

        element = validate_success(api.get_element(l_id, PROGRAM_DIRECTOR))
        assert element["last_clear_log_date"] == CLOCK_TEST_DATE
        assert element["status"] == "SERVICEABLE"


class TestBodyForeignKeys:
    """A body reference is resolved after the shape check and before business rules."""

    def test_belay_equipment_naming_an_unknown_course_is_not_found(self, api):
        """The acting identity resolves; the referenced course does not.

        PRD 2.12: "Body foreign-key resolution, in declared field order — the
        matching not-found code. Applies to the creation endpoints for elements,
        facilitators, training records, professional inspections, operational
        logs, bookings, participants, program blocks, block assignments, belay
        equipment, weather observations and incidents."

        PRD 3.4: "Life-safety hardware is inventoried per site by either a
        `ProgramDirector` or a `SafetyOfficer`. Each item names its owning
        `course_id`"

        Design: Corner/entities/create_belay_equipment_with_unknown_course_id_not_found
        """
        set_clock(api, CLOCK_TEST_UTC)
        course_id = create_course(api)
        so_id = create_safety_officer(api, course_id)

        validate_error(
            api.create_belay_equipment(
                belay_equipment_payload(UNKNOWN_COURSE_ID, "ROPE", serial_number="RP-404"),
                make_safety_officer_headers(so_id),
            ),
            ERR_COURSE_NOT_FOUND,
            404,
        )

        course = validate_success(api.get_course(course_id, PROGRAM_DIRECTOR))
        assert_course_counters(course, quarantined=0)

    def test_a_block_rigged_to_another_courses_element_is_refused(self, api):
        """Type and phase agree; the owning site does not.

        PRD 3.7: "The element must also sit on the same course as the booking, or
        the refusal is `ERR_ELEMENT_COURSE_MISMATCH`."

        PRD 2.12: "Element belongs to the same course —
        `ERR_ELEMENT_COURSE_MISMATCH`. Applies to program-block creation and
        belay-equipment creation."

        Design: Corner/entities/program_block_rigging_element_from_another_course_rejects
        """
        set_clock(api, CLOCK_TEST_UTC)
        course_a = create_course(api)
        course_b = create_course(
            api, course_name=COURSE_NAME_SECONDARY, ems_access_note=COURSE_NOTE_SECONDARY
        )
        lb_id = create_element(
            api, course_b, "LOW_ELEMENT", element_name=ELEMENT_NAME_LOW_ALT
        )
        gc_id = create_funded_client(api, amount_cents=0)
        b_id, _ = create_booking(api, course_a, gc_id, 1)
        add_blocks(
            api,
            b_id,
            [(1, "ICEBREAKER", "2026-09-15T09:00:00Z", "2026-09-15T09:45:00Z", None)],
        )

        validate_error(
            api.create_program_block(
                program_block_payload(
                    b_id,
                    2,
                    "LOW_ELEMENT",
                    "2026-09-15T09:45:00Z",
                    "2026-09-15T10:45:00Z",
                    element_id=lb_id,
                ),
                PROGRAM_DIRECTOR,
            ),
            ERR_ELEMENT_COURSE_MISMATCH,
            422,
        )

        booking = validate_success(api.get_booking(b_id, PROGRAM_DIRECTOR))
        assert booking["block_count"] == 1
