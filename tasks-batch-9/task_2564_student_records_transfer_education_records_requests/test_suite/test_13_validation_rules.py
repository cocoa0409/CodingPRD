"""Each guard refused on its own terms, with the passing call beside it.

Consent flags, authorization references, opt-out coverage, rights-holder
identity, scheduling windows and component lifecycle targets, each driven to the
one error the contract names and then to the outcome that satisfies it.
"""
from test_helpers import (
    ADMIN,
    CLERK,
    NON_EXISTENT_UUID,
    OFFICER_1,
    OFFICER_2,
    amendment_decision_payload,
    api_client,
    appointment_payload,
    assert_amendment_request,
    assert_cumulative_file,
    assert_disclosure_log_entry,
    assert_file_component,
    assert_inspection_request,
    assert_page_custody_identity,
    assert_records_request,
    assert_review_appointment,
    assert_student,
    certify_component,
    close_inspection_room,
    collect_component,
    create_amendment,
    create_district,
    create_hearing_officer,
    create_inspection_request,
    create_inspection_room,
    create_records_request,
    create_state_rule,
    create_student,
    deactivate_hearing_officer,
    decide_amendment,
    directory_disclosure_payload,
    directory_optout_payload,
    exclude_component,
    file_statement,
    file_version,
    get_components,
    get_cumulative_file_id,
    get_disclosure_log,
    get_file,
    get_inspection_request,
    hearing_schedule_payload,
    inspection_request_payload,
    make_eligible_student_headers,
    make_parent_headers,
    make_receiving_registrar_headers,
    make_records_clerk_headers,
    mark_ready_payload,
    records_request_payload,
    reinstate_component,
    request_hearing,
    schedule_hearing,
    set_clock,
    statement_payload,
    validate_error,
    validate_paginated,
    validate_request,
    validate_request_payload,
    validate_success,
)

CA_RULE = dict(
    transfer_response_days=10,
    discipline_inclusion_mode="SUSPENSIONS_AND_EXPULSIONS",
    discipline_min_days_removed=10,
    include_pending_investigations=False,
    sped_requires_consent=True,
    amendment_hearing_days=30,
    destruction_min_age_years=5,
    directory_optout_grace_days=14,
    notification_wait_days=7,
)
TX_RULE = dict(
    transfer_response_days=30,
    discipline_inclusion_mode="ALL_INCIDENTS",
    discipline_min_days_removed=10,
    include_pending_investigations=True,
    sped_requires_consent=False,
    amendment_hearing_days=45,
    destruction_min_age_years=7,
    directory_optout_grace_days=10,
    notification_wait_days=3,
)


def _ca_only():
    create_state_rule("CA", **CA_RULE)
    return create_district("SEND01", state_code="CA", name="Sending Unified")


def _both_rules():
    create_state_rule("CA", **CA_RULE)
    create_state_rule("TX", **TX_RULE)


def _get_request(request_id):
    return validate_success(api_client.get_records_request(request_id, OFFICER_1))


def _get_amendment(amendment_request_id):
    return validate_success(
        api_client.get_amendment_request(amendment_request_id, OFFICER_1)
    )


def _faye_with_two_requests():
    """One has_iep true student with all four components certified at 10 / 20 /
    30 / 40 pages, and two validated requests from two different districts that
    differ only in sped_consent_on_file."""
    _both_rules()
    sending = create_district("SEND01", state_code="CA", name="Sending Unified")
    receiving = create_district("RECV01", state_code="TX", name="Receiving Unified")
    second = create_district("CAD02", state_code="CA", name="Second Receiving Unified")
    student = create_student(
        sending["id"],
        first_name="Faye",
        last_name="Nakamura",
        dob="2011-07-17",
        grade_level=10,
        has_iep=True,
        guardian_user_id="guardian-faye",
    )
    file_id = get_cumulative_file_id(student["id"])
    components = get_components(file_id)
    for component_type, pages in (
        ("ACADEMIC", 10),
        ("HEALTH", 20),
        ("DISCIPLINE", 30),
        ("SPECIAL_EDUCATION", 40),
    ):
        collect_component(file_id, components[component_type]["id"], pages, 0)
        certify_component(file_id, components[component_type]["id"])

    without_consent = create_records_request(
        student["id"],
        receiving["id"],
        sending["id"],
        includes_special_education=True,
        sped_consent_on_file=False,
        authorization_reference="ENR-2026-9030",
    )
    with_consent = create_records_request(
        student["id"],
        second["id"],
        sending["id"],
        includes_special_education=True,
        sped_consent_on_file=True,
        authorization_reference="ENR-2026-9031",
    )
    validate_request(without_consent["id"])
    validate_request(with_consent["id"])
    return file_id, without_consent, with_consent


class TestSpedConsentIsConditionalOnTheStateRuleFlag:
    def test_a_missing_consent_flag_leaves_the_request_parked_in_assembling(self):
        """The student's has_iep is true and the responding California rule
        requires consent, so a request carrying sped_consent_on_file false cannot
        snapshot and nothing about it moves.

        PRD: "Finally the consent condition: when the student's `has_iep` is true and the responding state's `sped_requires_consent` is true, the request's `sped_consent_on_file` must be true, and a request that fails this is refused with `ERR_SPED_CONSENT_REQUIRED`."

        Design: Corner/validations/sped_consent_conditional_on_state_rule_flag
        """
        file_id, without_consent, _with_consent = _faye_with_two_requests()

        response = api_client.mark_ready_records_request(
            without_consent["id"], mark_ready_payload(file_version(file_id)), OFFICER_1
        )

        validate_error(response, "ERR_SPED_CONSENT_REQUIRED", 422)

        parked = _get_request(without_consent["id"])
        assert_records_request(parked)
        assert parked["status"] == "ASSEMBLING"
        assert parked["packet_status"] == "NONE"
        assert parked["packet_page_count"] is None

    def test_the_sibling_request_snapshots_on_the_identical_version_token(self):
        """Only the consent flag differs, so the same file at the same version
        yields a hundred-page packet for the request that carries consent.

        PRD: "Sum, over the certified components of the student's file, each component's `page_count` minus its `redacted_page_count`; call that the raw page figure."

        Design: Corner/validations/sped_consent_conditional_on_state_rule_flag
        """
        file_id, without_consent, with_consent = _faye_with_two_requests()
        token = file_version(file_id)

        refused = api_client.mark_ready_records_request(
            without_consent["id"], mark_ready_payload(token), OFFICER_1
        )
        validate_error(refused, "ERR_SPED_CONSENT_REQUIRED", 422)

        accepted = api_client.mark_ready_records_request(
            with_consent["id"], mark_ready_payload(token), OFFICER_1
        )

        ready = validate_success(accepted)
        assert_records_request(ready)
        assert ready["status"] == "READY_FOR_RELEASE"
        assert ready["packet_status"] == "SNAPSHOT"
        assert ready["packet_page_count"] == 100

        snapshotted = get_file(file_id)
        assert_cumulative_file(snapshotted)
        assert snapshotted["last_packet_snapshot_at"] == "2026-08-01T00:00:00.000Z"


def _gunnar_with_a_referenced_and_an_unreferenced_request():
    """Two requests for one student: the first carries an enrollment reference,
    the second is filed without the field at all."""
    _both_rules()
    sending = create_district("SEND01", state_code="CA", name="Sending Unified")
    receiving = create_district("RECV01", state_code="TX", name="Receiving Unified")
    second = create_district("CAD02", state_code="CA", name="Second Receiving Unified")
    student = create_student(
        sending["id"],
        first_name="Gunnar",
        last_name="Holm",
        dob="2011-08-18",
        grade_level=10,
        has_iep=False,
        guardian_user_id="guardian-gunnar",
    )
    referenced = create_records_request(
        student["id"],
        receiving["id"],
        sending["id"],
        authorization_reference="ENR-2026-9040",
    )
    payload = records_request_payload(student["id"], second["id"], sending["id"])
    del payload["authorization_reference"]
    unreferenced = validate_success(
        api_client.create_records_request(
            payload, make_receiving_registrar_headers(second["id"])
        ),
        201,
    )
    return referenced, unreferenced


class TestValidationNeedsTheFlagAndTheReference:
    def test_a_false_flag_and_a_null_reference_are_the_same_refusal(self):
        """Verification fails two different ways with one code: the officer who
        declines to verify, and the officer who verifies a request that never
        carried an enrollment reference to verify against.

        PRD: "The officer supplies `authorization_verified` as true, and the request must already hold a non-null `authorization_reference`; a call with `authorization_verified` false, or against a request whose `authorization_reference` is null, is refused with `ERR_AUTHORIZATION_NOT_VERIFIED`, and the correct disposition of an unverifiable request is denial with the reason `NO_ENROLLMENT_AUTHORIZATION` rather than validation."

        Design: Corner/validations/validate_requires_flag_and_reference_and_received_state
        """
        referenced, unreferenced = _gunnar_with_a_referenced_and_an_unreferenced_request()

        declined = api_client.validate_records_request(
            referenced["id"], validate_request_payload(authorization_verified=False), OFFICER_1
        )
        validate_error(declined, "ERR_AUTHORIZATION_NOT_VERIFIED", 422)

        nothing_to_verify = api_client.validate_records_request(
            unreferenced["id"], validate_request_payload(), OFFICER_1
        )
        validate_error(nothing_to_verify, "ERR_AUTHORIZATION_NOT_VERIFIED", 422)

        untouched = _get_request(unreferenced["id"])
        assert_records_request(untouched)
        assert untouched["authorization_reference"] is None
        assert untouched["status"] == "RECEIVED"
        assert untouched["authorization_verified"] is False

    def test_the_second_validation_of_a_validated_request_is_refused(self):
        """Validation is a one-way move out of RECEIVED, so the repeat call finds
        the request in the wrong state rather than re-verifying it.

        PRD: "It requires the request to be in `RECEIVED`; a request in any other status is refused with `ERR_REQUEST_NOT_RECEIVED`, and a request already `RELEASED` or `DENIED` is refused with `ERR_REQUEST_TERMINAL`."

        Design: Corner/validations/validate_requires_flag_and_reference_and_received_state
        """
        referenced, _unreferenced = _gunnar_with_a_referenced_and_an_unreferenced_request()

        first = api_client.validate_records_request(
            referenced["id"], validate_request_payload(), OFFICER_1
        )

        validated = validate_success(first)
        assert_records_request(validated)
        assert validated["status"] == "VALIDATED"
        assert validated["authorization_verified"] is True
        assert validated["statutory_days_allowed"] == 10

        second = api_client.validate_records_request(
            referenced["id"], validate_request_payload(), OFFICER_1
        )

        validate_error(second, "ERR_REQUEST_NOT_RECEIVED", 409)
        assert _get_request(referenced["id"])["status"] == "VALIDATED"


def _hana_opted_out_of_sports_only():
    """A minor whose guardian opts out of SPORTS_PARTICIPATION alone, filed on
    2026-08-10 well inside the fourteen-day grace window."""
    district = _ca_only()
    student = create_student(
        district["id"],
        first_name="Hana",
        last_name="Ito",
        dob="2013-09-09",
        grade_level=6,
        has_iep=False,
        guardian_user_id="guardian-hana",
    )
    set_clock("2026-08-10T12:00:00Z")
    opted_out = validate_success(
        api_client.update_directory_optout(
            student["id"],
            directory_optout_payload(["SPORTS_PARTICIPATION"]),
            make_parent_headers("guardian-hana"),
        )
    )
    return student, opted_out


class TestDirectoryOptOutCoverage:
    def test_an_optout_filed_inside_the_window_is_stored_and_effective(self):
        """The filing instant is recorded and, being inside the window, turns the
        opt-out on while covering only the single category supplied.

        PRD: "The rights-holder supplies `directory_optout_categories`, a non-empty list drawn from `NAME`, `ADDRESS`, `PHONE`, `PHOTO`, `HONORS`, and `SPORTS_PARTICIPATION`; the server stores it in that fixed order regardless of the order supplied, sets `directory_optout_received_at` to the current logical clock instant, and sets `directory_optout_effective` true exactly when that instant is at or before `directory_optout_deadline_at`."

        Design: Corner/validations/directory_disclosure_blocked_only_when_all_categories_opted_out
        """
        _student, opted_out = _hana_opted_out_of_sports_only()

        assert_student(opted_out)
        assert opted_out["directory_optout_received_at"] == "2026-08-10T12:00:00.000Z"
        assert opted_out["directory_optout_categories"] == ["SPORTS_PARTICIPATION"]
        assert opted_out["directory_optout_effective"] is True

    def test_the_deadline_is_pinned_to_the_enrolment_instant_plus_the_grace_days(self):
        """The student is enrolled at the default clock and California allows a
        fourteen-day grace window, so the deadline is fixed at 2026-08-15.

        PRD: "`directory_optout_deadline_at` is pinned to the student's `created_at` advanced by the governing state rule's `directory_optout_grace_days` calendar days, at the identical time of day, and is never recomputed afterwards even if the state rule changes."

        Design: Corner/validations/directory_disclosure_blocked_only_when_all_categories_opted_out
        """
        student, opted_out = _hana_opted_out_of_sports_only()

        assert student["created_at"] == "2026-08-01T00:00:00.000Z"
        assert opted_out["directory_optout_deadline_at"] == "2026-08-15T00:00:00.000Z"

    def test_only_a_release_wholly_covered_by_the_optout_is_refused(self):
        """A release of the opted-out category alone is refused, while the same
        category travelling beside a category never opted out is permitted and
        logged once.

        PRD: "The release is refused with `ERR_DIRECTORY_OPTOUT_ACTIVE` when the student's `directory_optout_effective` is true and every requested category appears in `directory_optout_categories`; a category that was not opted out may still be disclosed in the same call."

        Design: Corner/validations/directory_disclosure_blocked_only_when_all_categories_opted_out
        """
        student, _opted_out = _hana_opted_out_of_sports_only()
        clerk = make_records_clerk_headers("clerk-7")

        covered = api_client.create_directory_disclosure(
            student["id"],
            directory_disclosure_payload(
                recipient_name="Regional Sports League",
                disclosed_categories=["SPORTS_PARTICIPATION"],
            ),
            clerk,
        )
        validate_error(covered, "ERR_DIRECTORY_OPTOUT_ACTIVE", 422)

        partly_covered = api_client.create_directory_disclosure(
            student["id"],
            directory_disclosure_payload(
                recipient_name="Yearbook Vendor",
                disclosed_categories=["NAME", "SPORTS_PARTICIPATION"],
            ),
            clerk,
        )

        logged = validate_success(partly_covered, 201)
        assert_disclosure_log_entry(logged)
        assert logged["disclosure_type"] == "DIRECTORY_INFORMATION"
        assert logged["source_type"] == "STUDENT_DIRECTORY"
        assert logged["source_id"] == student["id"]
        assert logged["disclosed_categories"] == ["NAME", "SPORTS_PARTICIPATION"]
        assert logged["page_count"] == 0
        assert logged["logged_by_user_id"] == "clerk-7"

        entries = get_disclosure_log(student["id"], headers=CLERK)
        assert len(entries) == 1, f"one release was accepted, log holds {len(entries)}"
        assert entries[0]["recipient_name"] == "Yearbook Vendor"


def _two_families_of_minors():
    """Two twelve-year-olds in one district, each with their own guardian id and
    their own student id, so neither child's rights have transferred yet."""
    district = _ca_only()
    ivo = create_student(
        district["id"],
        first_name="Ivo",
        last_name="Petkov",
        dob="2013-10-10",
        grade_level=6,
        has_iep=False,
        guardian_user_id="guardian-ivo",
        student_user_id="student-ivo",
    )
    jules = create_student(
        district["id"],
        first_name="Jules",
        last_name="Marchand",
        dob="2013-11-11",
        grade_level=6,
        has_iep=False,
        guardian_user_id="guardian-jules",
        student_user_id="student-jules",
    )
    return ivo, jules


def _inspection_requests_of(student_id):
    rows, _meta = validate_paginated(
        api_client.list_student_inspection_requests(student_id, CLERK)
    )
    return rows


class TestRightsHolderIdentityOnOneEndpoint:
    def test_the_child_and_another_familys_guardian_are_refused_differently(self):
        """The twelve-year-old is not yet the rights-holder, and the guardian of
        record for a different child holds a permitted role but the wrong
        identity, so the two refusals carry different codes.

        PRD: "While `is_eligible_student` is true, a `Parent` is refused with `ERR_RIGHTS_TRANSFERRED` even though they remain the recorded guardian; while it is false, an `EligibleStudent` is refused with `ERR_RIGHTS_NOT_TRANSFERRED`."

        Design: Corner/validations/rights_holder_identity_checks_reject_wrong_role_and_wrong_user
        """
        ivo, _jules = _two_families_of_minors()
        payload = inspection_request_payload(["ACADEMIC"], False)

        by_the_child = api_client.create_inspection_request(
            ivo["id"], payload, make_eligible_student_headers("student-ivo")
        )
        validate_error(by_the_child, "ERR_RIGHTS_NOT_TRANSFERRED", 403)

        by_another_guardian = api_client.create_inspection_request(
            ivo["id"], payload, make_parent_headers("guardian-jules")
        )
        validate_error(by_another_guardian, "ERR_NOT_STUDENT_GUARDIAN", 403)

        assert _inspection_requests_of(ivo["id"]) == [], (
            "neither refusal may leave an inspection request behind"
        )

    def test_the_recorded_guardian_files_successfully_for_their_own_child(self):
        """The acting user id matches the student's recorded guardian, so the same
        endpoint accepts the filing and stamps the parent as requester.

        PRD: "A `Parent` may act only when `X-User-ID` equals the student's `guardian_user_id`, and an `EligibleStudent` may act only when `X-User-ID` equals the student's `student_user_id`; another family's guardian holds a permitted role but is still refused with `ERR_NOT_STUDENT_GUARDIAN`."

        Design: Corner/validations/rights_holder_identity_checks_reject_wrong_role_and_wrong_user
        """
        ivo, jules = _two_families_of_minors()

        response = api_client.create_inspection_request(
            ivo["id"],
            inspection_request_payload(["ACADEMIC"], False),
            make_parent_headers("guardian-ivo"),
        )

        filed = validate_success(response, 201)
        assert_inspection_request(filed)
        assert filed["requester_role"] == "PARENT"
        assert filed["requester_user_id"] == "guardian-ivo"

        assert len(_inspection_requests_of(ivo["id"])) == 1
        assert _inspection_requests_of(jules["id"]) == [], (
            "the other family's record is untouched"
        )


def _kira_with_a_room_and_a_free_inspection():
    """One active four-seat room and one no-copies inspection request filed at
    the default clock, so the statutory window closes 2026-09-15."""
    district = _ca_only()
    room = create_inspection_room("ROOM-A", 4, site_name="District Office")
    student = create_student(
        district["id"],
        first_name="Kira",
        last_name="Osei",
        dob="2013-12-12",
        grade_level=6,
        has_iep=False,
        guardian_user_id="guardian-kira",
    )
    request = create_inspection_request(
        student["id"],
        make_parent_headers("guardian-kira"),
        categories=["ACADEMIC", "HEALTH"],
        copies_requested=False,
    )
    return room, request


def _appointments_of(inspection_request_id):
    rows, _meta = validate_paginated(
        api_client.list_review_appointments(
            OFFICER_1, params={"inspection_request_id": inspection_request_id}
        )
    )
    return rows


class TestAppointmentBookingGuards:
    def test_a_booking_in_the_past_and_one_past_the_deadline_are_both_refused(self):
        """The window runs from the current clock instant to the statutory due
        instant inclusive, so yesterday and the day after the deadline fail with
        the same code and neither touches the request.

        PRD: "Finally the appointment must fall inside the statutory inspection window: `start_at` must be at or after the current logical clock instant and at or before the request's `statutory_inspection_due_at`, and a booking into the past or beyond the window is refused with `ERR_APPOINTMENT_OUTSIDE_STATUTORY_WINDOW`."

        Design: Corner/validations/appointment_booking_guards_window_then_room_state
        """
        room, request = _kira_with_a_room_and_a_free_inspection()
        token = request["version"]

        assert_inspection_request(request)
        assert request["statutory_inspection_due_at"] == "2026-09-15T00:00:00.000Z"
        assert request["fee_assessed_cents"] == 0
        assert request["fee_outstanding_cents"] == 0

        too_early = api_client.create_review_appointment(
            request["id"],
            appointment_payload(
                room["id"], "2026-07-31T09:00:00Z", "2026-07-31T10:00:00Z", token
            ),
            OFFICER_1,
        )
        validate_error(too_early, "ERR_APPOINTMENT_OUTSIDE_STATUTORY_WINDOW", 422)

        too_late = api_client.create_review_appointment(
            request["id"],
            appointment_payload(
                room["id"], "2026-09-16T09:00:00Z", "2026-09-16T10:00:00Z", token
            ),
            OFFICER_1,
        )
        validate_error(too_late, "ERR_APPOINTMENT_OUTSIDE_STATUTORY_WINDOW", 422)

        assert _appointments_of(request["id"]) == []
        assert get_inspection_request(request["id"])["status"] == "SUBMITTED"

    def test_an_unknown_room_in_the_body_is_a_404_before_anything_else(self):
        """The room reference travels in the body rather than the path, and it is
        resolved with the same 404 and at the same precedence.

        PRD: "References supplied in a request body are resolved with the same codes and at the same precedence as path identifiers, before roles are considered against payload contents."

        Design: Corner/validations/appointment_booking_guards_window_then_room_state
        """
        _room, request = _kira_with_a_room_and_a_free_inspection()

        response = api_client.create_review_appointment(
            request["id"],
            appointment_payload(
                NON_EXISTENT_UUID,
                "2026-09-14T09:00:00Z",
                "2026-09-14T10:00:00Z",
                request["version"],
            ),
            OFFICER_1,
        )

        validate_error(response, "ERR_INSPECTION_ROOM_NOT_FOUND", 404)
        assert _appointments_of(request["id"]) == []

    def test_a_closed_room_refuses_the_booking_the_reopened_room_accepts(self):
        """Closing the room blocks the identical call, and reopening it lets the
        same window through on the same untouched version token.

        PRD: "The room must be `ACTIVE`, or the booking is refused with `ERR_ROOM_CLOSED`."

        Design: Corner/validations/appointment_booking_guards_window_then_room_state
        """
        room, request = _kira_with_a_room_and_a_free_inspection()
        token = request["version"]
        booking = appointment_payload(
            room["id"], "2026-09-14T09:00:00Z", "2026-09-14T10:00:00Z", token
        )

        close_inspection_room(room["id"])
        refused = api_client.create_review_appointment(request["id"], booking, OFFICER_1)
        validate_error(refused, "ERR_ROOM_CLOSED", 409)

        validate_success(
            api_client.update_inspection_room(room["id"], {"status": "ACTIVE"}, ADMIN)
        )
        accepted = api_client.create_review_appointment(request["id"], booking, OFFICER_1)

        appointment = validate_success(accepted, 201)
        assert_review_appointment(appointment)
        assert appointment["status"] == "SCHEDULED"
        assert appointment["duration_minutes"] == 60
        assert appointment["room_id"] == room["id"]

        assert get_inspection_request(request["id"])["status"] == "SCHEDULED"
        assert len(_appointments_of(request["id"])) == 1


def _lior_with_a_requested_hearing():
    """One denied amendment standing in HEARING_REQUESTED, with one active
    hearing officer and one deactivated after registration."""
    district = _ca_only()
    active_officer = create_hearing_officer("Marion Vetter", "DISTRICT_DESIGNEE")
    inactive_officer = create_hearing_officer("Dana Rook", "EXTERNAL_CONTRACTOR")
    deactivate_hearing_officer(inactive_officer["id"])
    student = create_student(
        district["id"],
        first_name="Lior",
        last_name="Ben-Ami",
        dob="2012-01-13",
        grade_level=8,
        has_iep=False,
        guardian_user_id="guardian-lior",
    )
    file_id = get_cumulative_file_id(student["id"])
    academic = get_components(file_id)["ACADEMIC"]
    collect_component(file_id, academic["id"], 10, 0)
    certify_component(file_id, academic["id"])
    parent = make_parent_headers("guardian-lior")
    amendment = create_amendment(
        student["id"],
        academic["id"],
        parent,
        contested_field="gpa",
        requested_change="Restate term GPA as 3.10",
        rationale="Transcript arithmetic error",
    )
    decide_amendment(
        amendment["id"],
        "DENY",
        headers=OFFICER_1,
        decision_note="Grade verified with teacher of record",
    )
    request_hearing(amendment["id"], parent)
    return active_officer, inactive_officer, amendment


def _amendments_for_officer(officer_id):
    rows, _meta = validate_paginated(
        api_client.list_amendment_requests(
            OFFICER_1, params={"hearing_officer_id": officer_id}
        )
    )
    return rows


class TestHearingScheduleNeedsAKnownActiveOfficer:
    def test_an_unknown_officer_is_a_404_and_a_deactivated_one_a_409(self):
        """The officer reference is resolved before anything else, and an officer
        who exists but has been deactivated is refused on state instead — neither
        refusal names an officer on the challenge.

        PRD: "The named officer must exist and must be `ACTIVE`, or the call is refused with `ERR_OFFICER_INACTIVE`."

        Design: Corner/validations/hearing_schedule_requires_known_active_officer_inside_window
        """
        _active, inactive, amendment = _lior_with_a_requested_hearing()

        unknown = api_client.create_hearing_schedule(
            amendment["id"],
            hearing_schedule_payload(
                NON_EXISTENT_UUID, "2026-08-20T09:00:00Z", "2026-08-20T11:00:00Z"
            ),
            OFFICER_2,
        )
        validate_error(unknown, "ERR_HEARING_OFFICER_NOT_FOUND", 404)

        deactivated = api_client.create_hearing_schedule(
            amendment["id"],
            hearing_schedule_payload(
                inactive["id"], "2026-08-20T09:00:00Z", "2026-08-20T11:00:00Z"
            ),
            OFFICER_2,
        )
        validate_error(deactivated, "ERR_OFFICER_INACTIVE", 409)

        untouched = _get_amendment(amendment["id"])
        assert_amendment_request(untouched)
        assert untouched["status"] == "HEARING_REQUESTED"
        assert untouched["hearing_officer_id"] is None
        assert untouched["denied_at"] == "2026-08-01T00:00:00.000Z"
        assert untouched["hearing_due_at"] == "2026-08-31T00:00:00.000Z"

    def test_a_start_past_the_due_instant_is_refused_then_an_earlier_one_stands(self):
        """September is beyond the 31 August deadline, so the window arithmetic
        refuses it; the identical booking on 20 August is accepted and its
        duration is the whole number of minutes between the instants.

        PRD: "Finally the statutory window: `hearing_start_at` must be at or before `hearing_due_at`, inclusive to the millisecond, and a later start is refused with `ERR_HEARING_WINDOW_EXCEEDED`."

        Design: Corner/validations/hearing_schedule_requires_known_active_officer_inside_window
        """
        active, inactive, amendment = _lior_with_a_requested_hearing()

        beyond = api_client.create_hearing_schedule(
            amendment["id"],
            hearing_schedule_payload(
                active["id"], "2026-09-01T09:00:00Z", "2026-09-01T11:00:00Z"
            ),
            OFFICER_2,
        )
        validate_error(beyond, "ERR_HEARING_WINDOW_EXCEEDED", 422)
        assert _get_amendment(amendment["id"])["hearing_officer_id"] is None

        inside = api_client.create_hearing_schedule(
            amendment["id"],
            hearing_schedule_payload(
                active["id"], "2026-08-20T09:00:00Z", "2026-08-20T11:00:00Z"
            ),
            OFFICER_2,
        )

        scheduled = validate_success(inside)
        assert_amendment_request(scheduled)
        assert scheduled["status"] == "HEARING_SCHEDULED"
        assert scheduled["hearing_officer_id"] == active["id"]
        assert scheduled["hearing_duration_minutes"] == 120

        assert len(_amendments_for_officer(active["id"])) == 1
        assert _amendments_for_officer(inactive["id"]) == []


def _mina_with_three_challenges():
    """Three challenges on one student: two denied at the default clock and one
    left standing in SUBMITTED."""
    district = _ca_only()
    student = create_student(
        district["id"],
        first_name="Mina",
        last_name="Farouk",
        dob="2012-02-14",
        grade_level=8,
        has_iep=False,
        guardian_user_id="guardian-mina",
    )
    file_id = get_cumulative_file_id(student["id"])
    components = get_components(file_id)
    for component_type, pages in (("ACADEMIC", 10), ("HEALTH", 20), ("DISCIPLINE", 30)):
        collect_component(file_id, components[component_type]["id"], pages, 0)

    parent = make_parent_headers("guardian-mina")
    denied_academic = create_amendment(
        student["id"],
        components["ACADEMIC"]["id"],
        parent,
        contested_field="gpa",
        requested_change="Restate term GPA as 3.10",
        rationale="Transcript arithmetic error",
    )
    submitted_health = create_amendment(
        student["id"],
        components["HEALTH"]["id"],
        parent,
        contested_field="immunization_note",
        requested_change="Remove duplicate MMR entry",
        rationale="Clinic filed the dose twice",
    )
    denied_discipline = create_amendment(
        student["id"],
        components["DISCIPLINE"]["id"],
        parent,
        contested_field="action_type",
        requested_change="Reclassify as INFORMAL_RESOLUTION",
        rationale="Hearing was never held",
    )
    decide_amendment(
        denied_academic["id"],
        "DENY",
        headers=OFFICER_1,
        decision_note="Grade verified with teacher of record",
    )
    decide_amendment(
        denied_discipline["id"],
        "DENY",
        headers=OFFICER_1,
        decision_note="Removal upheld on review",
    )
    return components, denied_academic, submitted_health, denied_discipline, parent


class TestHearingRightIsStateGuardedAndTimeBoxed:
    def test_a_hearing_on_a_submitted_challenge_and_a_decision_on_a_denied_one_both_fail(self):
        """The hearing right opens only on a denial and the initial decision closes
        with it, so each call lands in the other's state and is refused with its
        own code.

        PRD: "The rights-holder requests a hearing with no payload at all; the challenge must be in `DENIED`, or the request is refused with `ERR_AMENDMENT_NOT_DENIED`, and the current logical clock instant must be at or before `hearing_due_at`, the boundary being inclusive — a request filed after that instant is refused with `ERR_HEARING_REQUEST_WINDOW_CLOSED`."

        Design: Corner/validations/hearing_request_window_inclusive_and_state_guarded
        """
        components, denied_academic, submitted_health, _denied_discipline, parent = (
            _mina_with_three_challenges()
        )

        too_soon = api_client.create_hearing_request(submitted_health["id"], parent)
        validate_error(too_soon, "ERR_AMENDMENT_NOT_DENIED", 409)
        assert _get_amendment(submitted_health["id"])["status"] == "SUBMITTED"

        already_decided = api_client.create_amendment_decision(
            denied_academic["id"], amendment_decision_payload("GRANT"), OFFICER_1
        )
        validate_error(already_decided, "ERR_AMENDMENT_NOT_SUBMITTED", 409)

        still_denied = _get_amendment(denied_academic["id"])
        assert still_denied["status"] == "DENIED"
        assert still_denied["hearing_due_at"] == "2026-08-31T00:00:00.000Z"

        contested = get_components(components["ACADEMIC"]["cumulative_file_id"])
        assert contested["ACADEMIC"]["amendment_count"] == 0, (
            "no grant ever landed on the record"
        )

    def test_the_hearing_request_deadline_is_inclusive_to_the_millisecond(self):
        """A request filed at exactly the due instant is inside the window, and the
        same request one millisecond later is outside it.

        PRD: "On success the challenge moves `DENIED → HEARING_REQUESTED`."

        Design: Corner/validations/hearing_request_window_inclusive_and_state_guarded
        """
        _components, denied_academic, _submitted, denied_discipline, parent = (
            _mina_with_three_challenges()
        )

        set_clock("2026-08-31T00:00:00Z")
        on_the_deadline = api_client.create_hearing_request(denied_academic["id"], parent)

        opened = validate_success(on_the_deadline)
        assert_amendment_request(opened)
        assert opened["status"] == "HEARING_REQUESTED"

        set_clock("2026-08-31T00:00:00.001Z")
        one_millisecond_late = api_client.create_hearing_request(
            denied_discipline["id"], parent
        )

        validate_error(one_millisecond_late, "ERR_HEARING_REQUEST_WINDOW_CLOSED", 422)
        shut_out = _get_amendment(denied_discipline["id"])
        assert shut_out["status"] == "DENIED"
        assert shut_out["hearing_due_at"] == "2026-08-31T00:00:00.000Z"


def _noor_with_a_scheduled_hearing():
    """A challenge denied by officer-1 and scheduled before Marion Vetter for
    2026-08-20T09:00Z to 11:00Z, read at the default clock."""
    district = _ca_only()
    officer = create_hearing_officer("Marion Vetter", "DISTRICT_DESIGNEE")
    student = create_student(
        district["id"],
        first_name="Noor",
        last_name="Rahimi",
        dob="2012-03-15",
        grade_level=8,
        has_iep=False,
        guardian_user_id="guardian-noor",
    )
    file_id = get_cumulative_file_id(student["id"])
    academic = get_components(file_id)["ACADEMIC"]
    collect_component(file_id, academic["id"], 10, 0)
    parent = make_parent_headers("guardian-noor")
    amendment = create_amendment(
        student["id"],
        academic["id"],
        parent,
        contested_field="attendance_total",
        requested_change="Reduce unexcused absences to 3",
        rationale="Two absences were medically excused",
    )
    decide_amendment(
        amendment["id"],
        "DENY",
        headers=OFFICER_1,
        decision_note="Attendance clerk confirmed the record",
    )
    request_hearing(amendment["id"], parent)
    schedule_hearing(
        amendment["id"],
        officer["id"],
        "2026-08-20T09:00:00Z",
        "2026-08-20T11:00:00Z",
        headers=OFFICER_1,
    )
    return file_id, academic, amendment, parent


class TestSegregationOfDutiesOutranksTheHearingState:
    def test_the_identity_check_answers_before_the_not_held_check(self):
        """A second officer calling too early is told the hearing has not been
        held, while the officer who issued the denial is refused on identity from
        the identical call — and is still refused once the hearing is over.

        PRD: "The challenge must be in `HEARING_SCHEDULED`, the current logical clock instant must be at or after `hearing_end_at` — a decision issued before the hearing has actually been held is refused with `ERR_HEARING_NOT_HELD` — and the acting `X-User-ID` must differ from the stored `initial_decided_by_user_id`, or the decision is refused with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/segregation_of_duties_outranks_hearing_not_held_then_terminality
        """
        _file_id, _academic, amendment, _parent = _noor_with_a_scheduled_hearing()

        early_by_a_second_officer = api_client.create_amendment_decision(
            amendment["id"],
            amendment_decision_payload("DENY", decision_note="Too early"),
            OFFICER_2,
        )
        validate_error(early_by_a_second_officer, "ERR_HEARING_NOT_HELD", 409)

        early_by_the_denying_officer = api_client.create_amendment_decision(
            amendment["id"],
            amendment_decision_payload("DENY", decision_note="Too early and same officer"),
            OFFICER_1,
        )
        validate_error(early_by_the_denying_officer, "ERR_SEGREGATION_OF_DUTIES", 403)

        set_clock("2026-08-20T11:00:00Z")
        after_the_hearing = api_client.create_amendment_decision(
            amendment["id"],
            amendment_decision_payload("DENY", decision_note="Same officer after the hearing"),
            OFFICER_1,
        )
        validate_error(after_the_hearing, "ERR_SEGREGATION_OF_DUTIES", 403)

        standing = _get_amendment(amendment["id"])
        assert_amendment_request(standing)
        assert standing["status"] == "HEARING_SCHEDULED"
        assert standing["initial_decided_by_user_id"] == "officer-1"
        assert standing["hearing_decided_by_user_id"] is None

    def test_the_upheld_record_takes_one_statement_and_then_refuses_everything(self):
        """The second officer upholds the record, the family's statement joins it as
        a single extra page, and the terminal row then refuses both a second
        statement and any further decision.

        PRD: "The rights-holder files a statement of disagreement by supplying `statement_text`; the challenge must be in `UPHELD`, and a filing from any other status — including a second filing against a challenge already in `STATEMENT_FILED` — is refused with `ERR_STATEMENT_ALREADY_FILED`."

        Design: Corner/validations/segregation_of_duties_outranks_hearing_not_held_then_terminality
        """
        file_id, academic, amendment, parent = _noor_with_a_scheduled_hearing()
        set_clock("2026-08-20T11:00:00Z")

        upheld = validate_success(
            api_client.create_amendment_decision(
                amendment["id"],
                amendment_decision_payload("DENY", decision_note="Panel upheld the record"),
                OFFICER_2,
            )
        )
        assert upheld["status"] == "UPHELD"
        assert upheld["hearing_decided_by_user_id"] == "officer-2"
        assert upheld["initial_decided_by_user_id"] == "officer-1"

        annotated = file_statement(
            amendment["id"],
            parent,
            statement_text="The family disagrees with the attendance findings.",
        )
        assert annotated["status"] == "STATEMENT_FILED"
        assert annotated["statement_filed_at"] == "2026-08-20T11:00:00.000Z"

        component = get_components(file_id)["ACADEMIC"]
        assert_file_component(component)
        assert component["statement_of_disagreement_present"] is True
        assert component["page_count"] == 11
        assert component["disclosable_page_count"] == 11
        assert component["amendment_count"] == 0
        assert component["status"] == "COLLECTED"

        repaginated = get_file(file_id)
        assert_page_custody_identity(repaginated)
        assert repaginated["total_page_count"] == 11
        assert repaginated["included_page_count"] == 11

        second_statement = api_client.create_statement_of_disagreement(
            amendment["id"], statement_payload("A second statement."), parent
        )
        validate_error(second_statement, "ERR_STATEMENT_ALREADY_FILED", 409)

        late_grant = api_client.create_amendment_decision(
            amendment["id"], amendment_decision_payload("GRANT"), OFFICER_2
        )
        validate_error(late_grant, "ERR_AMENDMENT_TERMINAL", 409)

        settled = get_components(file_id)["ACADEMIC"]
        assert settled["id"] == academic["id"]
        assert settled["page_count"] == 11, "the refused calls added no further page"


def _omar_with_one_certified_component():
    """ACADEMIC collected at 10 pages with 2 of them redacted and then certified;
    HEALTH is left exactly as the file minted it."""
    district = _ca_only()
    student = create_student(
        district["id"],
        first_name="Omar",
        last_name="Duarte",
        dob="2012-04-16",
        grade_level=8,
        has_iep=False,
        guardian_user_id="guardian-omar",
    )
    file_id = get_cumulative_file_id(student["id"])
    components = get_components(file_id)
    academic = components["ACADEMIC"]
    collect_component(file_id, academic["id"], 10, 2)
    certify_component(file_id, academic["id"])
    return file_id, academic["id"], components["HEALTH"]["id"]


class TestComponentLifecycleTargetGuards:
    def test_certification_refuses_a_pending_and_an_already_certified_component(self):
        """Certification is reachable only from COLLECTED, so the untouched HEALTH
        component and the already-certified ACADEMIC component fail with their own
        codes and neither call moves the file on.

        PRD: "Certification attempted against a component that is not `COLLECTED` — a `PENDING` one included — is refused with `ERR_COMPONENT_NOT_COLLECTED`, and certification attempted against a component that is already `CERTIFIED` is refused with `ERR_COMPONENT_ALREADY_CERTIFIED`."

        Design: Corner/validations/component_lifecycle_target_guards_and_missing_parents
        """
        file_id, academic_id, health_id = _omar_with_one_certified_component()
        before = file_version(file_id)

        pending = api_client.update_file_component(
            file_id, health_id, {"status": "CERTIFIED"}, OFFICER_1
        )
        validate_error(pending, "ERR_COMPONENT_NOT_COLLECTED", 409)

        again = api_client.update_file_component(
            file_id, academic_id, {"status": "CERTIFIED"}, OFFICER_1
        )
        validate_error(again, "ERR_COMPONENT_ALREADY_CERTIFIED", 409)

        untouched = get_file(file_id)
        assert untouched["version"] == before
        assert untouched["total_page_count"] == 10
        assert untouched["disclosable_page_count"] == 8

        left_alone = get_components(file_id)["HEALTH"]
        assert_file_component(left_alone)
        assert left_alone["status"] == "PENDING"
        assert left_alone["page_count"] == 0

    def test_a_collected_target_aimed_at_a_certified_component_is_refused(self):
        """Re-collecting a certified component is neither a collection nor a
        reinstatement, so it carries the reinstatement guard's code.

        PRD: "Reinstatement attempted against a component that is not `EXCLUDED` is refused with `ERR_COMPONENT_NOT_EXCLUDED`, and a `COLLECTED` target aimed at a `CERTIFIED` component — which is neither a valid collection nor a valid reinstatement — carries that same `ERR_COMPONENT_NOT_EXCLUDED`."

        Design: Corner/validations/component_lifecycle_target_guards_and_missing_parents
        """
        file_id, academic_id, _health_id = _omar_with_one_certified_component()
        before = file_version(file_id)

        response = api_client.update_file_component(
            file_id, academic_id, {"status": "COLLECTED", "page_count": 10}, CLERK
        )

        validate_error(response, "ERR_COMPONENT_NOT_EXCLUDED", 409)

        unmoved = get_components(file_id)["ACADEMIC"]
        assert unmoved["status"] == "CERTIFIED"
        assert unmoved["page_count"] == 10
        assert unmoved["redacted_page_count"] == 2
        assert file_version(file_id) == before

    def test_the_path_resolves_left_to_right_before_any_state_check(self):
        """A component identifier that resolves to nothing under a real file and a
        real component addressed under a file that does not exist each answer with
        the 404 that names the unresolved resource.

        PRD: "Every identifier in a path is resolved left to right, and the first one that does not resolve terminates the request with the 404 that names that resource: a bad file identifier yields `ERR_CUMULATIVE_FILE_NOT_FOUND` before the component is looked at, and a component identifier that resolves to a row belonging to a different file is treated as unresolved and yields `ERR_FILE_COMPONENT_NOT_FOUND`."

        Design: Corner/validations/component_lifecycle_target_guards_and_missing_parents
        """
        file_id, academic_id, _health_id = _omar_with_one_certified_component()
        before = file_version(file_id)

        unknown_component = api_client.update_file_component(
            file_id, NON_EXISTENT_UUID, {"status": "CERTIFIED"}, OFFICER_1
        )
        validate_error(unknown_component, "ERR_FILE_COMPONENT_NOT_FOUND", 404)

        unknown_file = api_client.update_file_component(
            NON_EXISTENT_UUID, academic_id, {"status": "CERTIFIED"}, OFFICER_1
        )
        validate_error(unknown_file, "ERR_CUMULATIVE_FILE_NOT_FOUND", 404)

        assert file_version(file_id) == before
        assert get_file(file_id)["included_page_count"] == 10

    def test_exclusion_and_reinstatement_bump_the_version_twice_and_restore_custody(self):
        """Each accepted component change re-derives the parent's counters and
        counts as a mutation of the file, so the excluded-then-reinstated pair
        leaves the pages exactly where they started two versions later.

        PRD: "Reconciliation of a derived field counts as a mutation for both purposes: when a component change re-derives a cumulative file's counters, the file's `updated_at` is refreshed and its `version` is incremented even though no client wrote to the file directly."

        Design: Corner/validations/component_lifecycle_target_guards_and_missing_parents
        """
        file_id, academic_id, _health_id = _omar_with_one_certified_component()
        before = file_version(file_id)

        excluded = exclude_component(
            file_id, academic_id, "SEALED_BY_COURT", headers=OFFICER_1
        )
        assert_file_component(excluded)
        assert excluded["status"] == "EXCLUDED"
        assert excluded["exclusion_reason"] == "SEALED_BY_COURT"

        held_back = get_file(file_id)
        assert_page_custody_identity(held_back)
        assert held_back["total_page_count"] == 10
        assert held_back["included_page_count"] == 0
        assert held_back["excluded_page_count"] == 10

        reinstated = reinstate_component(file_id, academic_id, headers=OFFICER_1)
        assert reinstated["status"] == "COLLECTED"
        assert reinstated["exclusion_reason"] is None
        assert reinstated["page_count"] == 10
        assert reinstated["redacted_page_count"] == 2

        restored = get_file(file_id)
        assert_page_custody_identity(restored)
        assert restored["included_page_count"] == 10
        assert restored["excluded_page_count"] == 0
        assert restored["version"] == before + 2
