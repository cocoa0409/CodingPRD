"""The declared shape of each record: envelope, derivations, defaults, absences.

These tests read the contract at its narrowest: what a create returns, what a
read gives back, which fields the server owns, which defaults materialise when
the client says nothing, and which identifiers refuse to resolve. Nothing here
depends on a workflow reaching a later state.
"""

from test_helpers import (
    ApiErrorId,
    CASE_MANAGER_USER_ID,
    CM_HEADERS,
    MIDDLE_IN_HOME_RULE,
    MISSING_UUID,
    PA_HEADERS,
    api_client,
    create_assignment_payload,
    create_case_payload,
    create_certification_payload,
    create_entitlement_rule_payload,
    create_extension_request_payload,
    create_pacing_sync_payload,
    create_safety_review_payload,
    create_session_payload,
    create_student_payload,
    create_teacher_payload,
    is_valid_uuid,
    ledger_entries_for_case,
    read_case,
    register_student,
    set_clock,
    setup_active_case,
    setup_delivered_session,
    validate_error,
    validate_paginated,
    validate_success,
    void_session_payload,
)

CLOCK = "2026-09-01T00:00:00Z"

CERT_WINDOW = {
    "expected_absence_days": 30,
    "certified_start_date": "2026-09-07",
    "certified_end_date": "2026-10-07",
    "signature_date": "2026-09-01",
}

CLEARED_SAFETY_REVIEW = {
    "hazard_findings": ["UNLIT_ACCESS"],
    "escort_available": False,
}


def _create_student(**overrides):
    return api_client.create_student(create_student_payload(**overrides), PA_HEADERS)


def _students_meta():
    _, meta = validate_paginated(api_client.list_students(PA_HEADERS))
    return meta


class TestCreationEnvelopeAndDerivedBand:
    """A create answers 201 inside the declared envelope, with the band derived."""

    def test_student_creation_returns_the_declared_envelope_and_derives_middle(self):
        """The response body carries exactly meta, response_type and data, and
        grade_level 7 becomes grade_band MIDDLE rather than an echo of the input.

        The PRD states: "From `grade_level` the server derives `grade_band`, which is
        the key the entitlement catalogue is looked up by: `PRIMARY` when `grade_level`
        is 5 or below, `MIDDLE` when `grade_level` is 6, 7 or 8, and `HIGH` when
        `grade_level` is 9 or above."

        The PRD states: "Operations that bring a new resource into existence return
        `201 Created`."

        The PRD states: "The `api_request_id` is a server-generated unique identifier for
        the request that starts with `req_`."

        Design: Corner/entities/student_creation_returns_201_with_derived_grade_band_and_success_envelope
        """
        set_clock(CLOCK)

        response = _create_student(
            student_number="S-0001",
            full_name="Ada Lin",
            grade_level=7,
            campus_code="MS-01",
            special_ed_status="IEP",
            iep_service_minutes_weekly=300,
            enrollment_status="ENROLLED",
        )
        data = validate_success(response, 201)

        body = response.json()
        assert set(body.keys()) == {"meta", "response_type", "data"}, (
            "the success envelope carries exactly these three keys"
        )
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert "api_request_timestamp" in body["meta"]

        assert data["student_number"] == "S-0001"
        assert data["full_name"] == "Ada Lin"
        assert data["grade_level"] == 7
        assert data["campus_code"] == "MS-01"
        assert data["special_ed_status"] == "IEP"
        assert data["iep_service_minutes_weekly"] == 300
        assert data["enrollment_status"] == "ENROLLED"
        assert data["grade_band"] == "MIDDLE", "grade_level 7 falls in 6, 7 or 8"
        assert is_valid_uuid(data["id"])


class TestRetrievalReturnsTheStoredRow:
    """A read gives the row back, derived caseload fields included."""

    def test_a_teacher_with_no_assignments_reads_back_at_zero_committed_minutes(self):
        """Every registered field survives the round trip, and the derived caseload pair
        is present on the read even though no assignment exists anywhere.

        The PRD states: "At registration `committed_weekly_minutes` initializes to 0 and
        `over_cap` initializes to false."

        The PRD states: "`safety_clearance_status` is one of `CLEARED`, `RESTRICTED`, or
        `EXPIRED` and defaults to `CLEARED`; `clearance_expires_on` is the date the
        clearance lapses; and `home_visit_eligible`, defaulting to true, states whether
        this teacher may perform in-home visits at all."

        Design: Corner/entities/teacher_retrieval_returns_the_stored_row_with_zero_committed_minutes
        """
        set_clock(CLOCK)
        created = validate_success(
            api_client.create_teacher(
                create_teacher_payload(
                    full_name="Tara Ng",
                    employee_number="E-1001",
                    credential_areas=["MATH", "ELA"],
                    grade_bands=["MIDDLE", "HIGH"],
                    max_weekly_caseload_minutes=1200,
                    safety_clearance_status="CLEARED",
                    clearance_expires_on="2027-06-30",
                    home_visit_eligible=True,
                ),
                PA_HEADERS,
            ),
            201,
        )

        response = api_client.get_teacher(created["id"], PA_HEADERS)
        data = validate_success(response)
        assert response.json()["response_type"] == "object"

        assert data["id"] == created["id"]
        assert data["employee_number"] == "E-1001"
        assert data["credential_areas"] == ["MATH", "ELA"]
        assert data["grade_bands"] == ["MIDDLE", "HIGH"]
        assert data["max_weekly_caseload_minutes"] == 1200
        assert data["safety_clearance_status"] == "CLEARED"
        assert data["clearance_expires_on"] == "2027-06-30"
        assert data["home_visit_eligible"] is True
        assert data["committed_weekly_minutes"] == 0
        assert data["over_cap"] is False


class TestListingPaginatesAcrossTheOffsetBoundary:
    """total_count counts the population; has_more flips at the window edge."""

    def test_total_count_ignores_the_page_size_and_has_more_flips_at_the_edge(self):
        """Three students read two at a time report total_count 3 on both pages, with
        has_more true on the first window and false on the second.

        The PRD states: "`limit` sets the maximum number of rows returned; it defaults
        to 10, has a minimum of 1, and has a maximum of 100."

        The PRD states: "`total_count` reflects the number of rows matching the supplied
        filters before the page window is applied, and `has_more` is true exactly when
        rows matching those filters remain beyond the current window."

        Design: Corner/entities/student_listing_paginates_and_filters_with_total_count_and_has_more
        """
        set_clock(CLOCK)
        register_student(student_number="S-0001", full_name="Ada Lin", grade_level=7)
        register_student(student_number="S-0002", full_name="Ben Ortiz", grade_level=4)
        register_student(student_number="S-0003", full_name="Cara Voss", grade_level=10)

        first_response = api_client.list_students(
            CM_HEADERS, params={"limit": 2, "offset": 0}
        )
        first, first_meta = validate_paginated(first_response)
        assert first_response.json()["response_type"] == "array"
        assert len(first) == 2
        assert first_meta["total_count"] == 3, "the population, not the page"
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0
        assert first_meta["has_more"] is True

        second, second_meta = validate_paginated(
            api_client.list_students(CM_HEADERS, params={"limit": 2, "offset": 2})
        )
        assert len(second) == 1, "one row remains beyond the first window"
        assert second_meta["total_count"] == 3
        assert second_meta["offset"] == 2
        assert second_meta["has_more"] is False

        bands = {row["student_number"]: row["grade_band"] for row in first + second}
        assert bands == {"S-0001": "MIDDLE", "S-0002": "PRIMARY", "S-0003": "HIGH"}


class TestUnknownIdentifiersAnswerPerEntity:
    """Thirteen path-level 404 codes, each keyed to its own path segment."""

    def test_each_path_segment_returns_its_own_not_found_code(self):
        """A well-formed but unknown UUID never collapses to a generic 404 and never
        answers 200 with an empty body.

        The PRD states: "Identifiers embedded in the URL are resolved in the order they appear in the
        path, and the first one that does not resolve determines the 404:
        `ERR_STUDENT_NOT_FOUND` for a student id in the path of a student read or an
        enrollment change; `ERR_TEACHER_NOT_FOUND` for a teacher id in the path of a
        teacher read or a clearance update; `ERR_ENTITLEMENT_RULE_NOT_FOUND` for an
        entitlement-rule id in the path of a rule read or a retirement;
        `ERR_CASE_NOT_FOUND` for a case id in the path of any case-scoped operation;
        `ERR_CERTIFICATION_NOT_FOUND` for a certification id in the path of a
        certification read or review; `ERR_ASSIGNMENT_NOT_FOUND` for an assignment
        id in the path of an assignment read, accept, decline or release;
        `ERR_SESSION_NOT_FOUND` for a session id in the path of a session read, log,
        verify, void, cancel or make-up; `ERR_SAFETY_REVIEW_NOT_FOUND` for a
        safety-review id in the path of a review read or finalization;
        `ERR_EXTENSION_REQUEST_NOT_FOUND` for an extension-request id in the path of
        a request read, start-review, request-info, resubmit or decide;
        `ERR_TRANSITION_PLAN_NOT_FOUND` for a plan id in the path of a plan read,
        coordinate, complete or abort; `ERR_PACING_SYNC_NOT_FOUND` for a pacing-sync
        id in the path of a sync read, acknowledge or dispute;
        `ERR_SPED_LOG_NOT_FOUND` for a special-education log id in the path of a log
        read, delivery recording or continuation change; and
        `ERR_LEDGER_ENTRY_NOT_FOUND` for an attendance-entry id in the path of a
        ledger read."

        The PRD states: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/entities/nonexistent_path_ids_return_the_entity_specific_not_found_error
        """
        set_clock(CLOCK)

        probes = [
            (api_client.get_student, ApiErrorId.ERR_STUDENT_NOT_FOUND),
            (api_client.get_teacher, ApiErrorId.ERR_TEACHER_NOT_FOUND),
            (api_client.get_entitlement_rule, ApiErrorId.ERR_ENTITLEMENT_RULE_NOT_FOUND),
            (api_client.get_case, ApiErrorId.ERR_CASE_NOT_FOUND),
            (api_client.get_certification, ApiErrorId.ERR_CERTIFICATION_NOT_FOUND),
            (api_client.get_assignment, ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND),
            (api_client.get_session, ApiErrorId.ERR_SESSION_NOT_FOUND),
            (api_client.get_safety_review, ApiErrorId.ERR_SAFETY_REVIEW_NOT_FOUND),
            (
                api_client.get_extension_request,
                ApiErrorId.ERR_EXTENSION_REQUEST_NOT_FOUND,
            ),
            (api_client.get_transition_plan, ApiErrorId.ERR_TRANSITION_PLAN_NOT_FOUND),
            (api_client.get_pacing_sync, ApiErrorId.ERR_PACING_SYNC_NOT_FOUND),
            (api_client.get_sped_service_log, ApiErrorId.ERR_SPED_LOG_NOT_FOUND),
            (api_client.get_attendance_entry, ApiErrorId.ERR_LEDGER_ENTRY_NOT_FOUND),
        ]

        for read, expected in probes:
            response = read(MISSING_UUID, PA_HEADERS)
            error = validate_error(response, expected.value, 404)
            body = response.json()
            assert body["response_type"] == "error", f"{expected.value} envelope"
            assert set(error.keys()) == {"error_id", "message"}, (
                f"{expected.value} data carries only the code and the message"
            )
            assert set(body["meta"].keys()) == {
                "api_request_id",
                "api_request_timestamp",
            }


class TestSchemaValidationRunsBeforeAnyLookup:
    """A missing required field answers before the body foreign key is resolved."""

    def test_validation_answers_even_when_the_same_body_names_a_missing_parent(self):
        """Three creates each omitting one required field are all refused with
        ERR_VALIDATION, including the two whose bodies also name identifiers that do not
        exist, and nothing is persisted.

        The PRD states: "The body and query conform to the endpoint's input schema:
        every required field present, no unknown field, every enum value a member of its
        declared set, every integer inside its declared range, every date formatted as
        `YYYY-MM-DD`, every datetime a valid ISO 8601 UTC instant, `physician_npi`
        exactly ten digits, `hazard_findings` free of duplicate members, `limit` inside
        the inclusive range 1 to 100, and `offset` not negative."

        The PRD states: "Checks are grouped into fourteen tiers and evaluated strictly
        in tier order; the first tier that produces a failure determines the response,
        and no later tier is consulted."

        Design: Corner/entities/missing_required_input_fields_are_rejected_with_validation_before_any_lookup
        """
        set_clock(CLOCK)

        validate_error(
            api_client.create_student(
                {"student_number": "S-0001", "grade_level": 7, "campus_code": "MS-01"},
                PA_HEADERS,
            ),
            ApiErrorId.ERR_VALIDATION.value,
            400,
        )

        no_mode = validate_error(
            api_client.create_case(
                {"student_id": MISSING_UUID, "referral_date": "2026-09-01"},
                CM_HEADERS,
            ),
            ApiErrorId.ERR_VALIDATION.value,
            400,
        )
        assert no_mode["error_id"] != ApiErrorId.ERR_STUDENT_NOT_FOUND.value, (
            "the tier-5 body foreign key is never resolved"
        )

        no_version = validate_error(
            api_client.create_certification(
                create_certification_payload(MISSING_UUID, **CERT_WINDOW),
                CM_HEADERS,
            ),
            ApiErrorId.ERR_VALIDATION.value,
            400,
        )
        assert no_version["error_id"] != ApiErrorId.ERR_CASE_NOT_FOUND.value

        assert _students_meta()["total_count"] == 0, "no partial row survives"
        _, teachers_meta = validate_paginated(api_client.list_teachers(PA_HEADERS))
        assert teachers_meta["total_count"] == 0


class TestOmittedOptionalFieldsTakeTheirDefaults:
    """Every declared default materialises when the client says nothing."""

    def test_student_teacher_rule_and_review_defaults_all_materialise(self):
        """A student defaults to NONE / 0 / ENROLLED, a teacher to CLEARED and
        home-visit eligible, a rule to PUBLISHED, and a review to no hazards, no
        escort, risk score 0 and a sixty-day expiry.

        The PRD states: "`special_ed_status` describes the special-education posture at
        referral time and is one of `NONE`, `IEP`, or `SECTION_504`, defaulting to
        `NONE`."

        The PRD states: "A rule's `status` is either `PUBLISHED` or `RETIRED` and
        defaults to `PUBLISHED`."

        The PRD states: "The new review starts with `status` `DRAFT` and `clearance`
        `PENDING`."

        The PRD states: "The server also derives `expires_on` as the `review_date`
        advanced by sixty days, and computes an initial `risk_score`."

        Design: Corner/entities/omitted_optional_fields_take_their_declared_defaults
        """
        set_clock(CLOCK)
        student = register_student(
            student_number="S-0001",
            full_name="Ada Lin",
            grade_level=7,
            campus_code="MS-01",
        )
        assert student["special_ed_status"] == "NONE"
        assert student["iep_service_minutes_weekly"] == 0
        assert student["enrollment_status"] == "ENROLLED"

        case = validate_success(
            api_client.create_case(create_case_payload(student["id"]), CM_HEADERS), 201
        )

        teacher = validate_success(
            api_client.create_teacher(
                {
                    "full_name": "Tara Ng",
                    "employee_number": "E-1001",
                    "credential_areas": ["MATH"],
                    "grade_bands": ["MIDDLE"],
                    "max_weekly_caseload_minutes": 1200,
                    "clearance_expires_on": "2027-06-30",
                },
                PA_HEADERS,
            ),
            201,
        )
        assert teacher["safety_clearance_status"] == "CLEARED"
        assert teacher["home_visit_eligible"] is True
        assert teacher["committed_weekly_minutes"] == 0
        assert teacher["over_cap"] is False

        rule = validate_success(
            api_client.create_entitlement_rule(
                create_entitlement_rule_payload(), PA_HEADERS
            ),
            201,
        )
        assert rule["status"] == "PUBLISHED", "an omitted status is immediately resolvable"

        review = validate_success(
            api_client.create_safety_review(
                create_safety_review_payload(
                    case["id"],
                    evidence_source="ONSITE_WALKTHROUGH",
                    review_date="2026-09-02",
                ),
                CM_HEADERS,
            ),
            201,
        )
        assert review["hazard_findings"] == []
        assert review["escort_available"] is False
        assert review["risk_score"] == 0, "an empty finding set weighs nothing"
        assert review["status"] == "DRAFT"
        assert review["clearance"] == "PENDING", (
            "a draft review reads PENDING whatever the score"
        )
        assert review["scoring_variant"] == "ONSITE_VERIFIED"
        assert review["expires_on"] == "2026-11-01", "2026-09-02 advanced by sixty days"


class TestComputedFieldsAreDerivedNotSupplied:
    """The two timestamps decide the span and the date; the rule decides the week."""

    def test_the_session_and_case_carry_only_server_computed_figures(self):
        """A 09:00-to-11:00 booking derives 120 minutes on 2026-09-07 at zero credit,
        and the case behind it carries the 390-minute weekly entitlement.

        The PRD states: "From those two instants the server derives `scheduled_minutes`
        as the whole-minute span between them and `service_date` as the UTC calendar
        date of `scheduled_start`."

        The PRD states: "A new session starts with `status` `SCHEDULED` and
        `credited_minutes` 0."

        The PRD states: "The case then advances from `PENDING_CERT_REVIEW` to `ELIGIBLE`
        and absorbs the accepted document: the case's `diagnosis_category`,
        `certified_start_date` and `certified_end_date` are copied from the accepted
        certification, and `certification_count` is recomputed as the number of that
        case's certifications whose `status` is `ACCEPTED`."

        Design: Corner/entities/session_computed_fields_are_derived_and_client_supplied_values_are_ignored
        """
        bundle = setup_active_case(
            rules=[MIDDLE_IN_HOME_RULE],
            certification=dict(CERT_WINDOW),
            safety_review=dict(CLEARED_SAFETY_REVIEW),
        )
        session = validate_success(
            api_client.create_session(
                create_session_payload(
                    bundle["case"]["id"],
                    bundle["primary_assignment"]["id"],
                    scheduled_start="2026-09-07T09:00:00Z",
                    scheduled_end="2026-09-07T11:00:00Z",
                    delivery_mode="IN_HOME",
                    subject="MATH",
                ),
                CM_HEADERS,
            ),
            201,
        )
        assert session["scheduled_minutes"] == 120
        assert session["service_date"] == "2026-09-07"
        assert session["status"] == "SCHEDULED"
        assert session["credited_minutes"] == 0

        case = read_case(bundle["case"]["id"])
        assert case["weekly_entitled_minutes"] == 390
        assert case["entitlement_rule_id"] == bundle["rule"]["id"]
        assert case["diagnosis_category"] == "MEDICAL_ACUTE"
        assert case["certified_start_date"] == "2026-09-07"
        assert case["certified_end_date"] == "2026-10-07"
        assert case["service_start_date"] == "2026-09-07", "the clock date at activation"


class TestSystemFieldsAreServerOwned:
    """Identity, timestamps and the acting user come from the server, not the body."""

    def test_the_acting_user_is_recorded_and_the_case_version_moves_on_its_own(self):
        """A case records the header's user id, a certification records the same id as
        its submitter with no reviewer yet, and the case's version advances by exactly
        one across the certification write.

        The PRD states: "The new case starts with `service_status` `DRAFT` and
        `funding_status` `NOT_REPORTED`, and the server stamps `created_by_user_id` with
        the acting `X-User-ID` — a value that later governs who may verify this case's
        sessions."

        The PRD states: "A newly submitted certification starts with `status`
        `SUBMITTED`, `is_current` false, and `submitted_by_user_id` set to the acting
        `X-User-ID`."

        The PRD states: "A `CaseManager` submits one against a `DRAFT` case, which
        advances `service_status` from `DRAFT` to `PENDING_CERT_REVIEW` and increments
        the case's `version` by one."

        Design: Corner/entities/system_fields_are_server_generated_and_version_starts_at_one
        """
        set_clock(CLOCK)
        student = register_student(student_number="S-0001", full_name="Ada Lin")

        case = validate_success(
            api_client.create_case(create_case_payload(student["id"]), CM_HEADERS), 201
        )
        assert is_valid_uuid(case["id"]), "the id is server-minted, not client-supplied"
        assert case["version"] >= 1
        assert case["created_at"] == case["updated_at"], "nothing has mutated it yet"
        assert case["created_by_user_id"] == CASE_MANAGER_USER_ID
        assert case["service_status"] == "DRAFT"
        assert case["funding_status"] == "NOT_REPORTED"

        certification = validate_success(
            api_client.create_certification(
                create_certification_payload(case["id"], case["version"], **CERT_WINDOW),
                CM_HEADERS,
            ),
            201,
        )
        assert certification["submitted_by_user_id"] == CASE_MANAGER_USER_ID
        assert certification.get("reviewed_by_user_id") is None
        assert certification["status"] == "SUBMITTED"
        assert certification["is_current"] is False

        after = read_case(case["id"])
        assert after["version"] == case["version"] + 1, (
            "the certification write moves the parent case exactly one version"
        )
        assert after["updated_at"] > after["created_at"]
        assert after["service_status"] == "PENDING_CERT_REVIEW"


class TestTypeAndRangeViolationsAreSchemaLevel:
    """Enum membership, ranges and the conditional IEP rule all answer 400."""

    def test_five_shape_violations_all_answer_validation_and_persist_nothing(self):
        """An out-of-range grade, a non-member special-education status, a positive IEP
        minute count on a NONE student, a zero caseload ceiling and a non-member
        delivery mode are each ERR_VALIDATION rather than a domain conflict.

        The PRD states: "Registration supplies a `student_number`, which must be unique
        across all students and between one and thirty-two characters long — a collision
        is rejected with `ERR_DUPLICATE_STUDENT_NUMBER` — together with the student's
        legal `full_name`, a `grade_level` from 0 through 12 inclusive where 0 denotes
        kindergarten, and a `campus_code` naming the home campus used for classroom
        coordination."

        The PRD states: "`iep_service_minutes_weekly` records the weekly specialized
        service minutes the IEP requires; it may not be negative, defaults to 0, must be
        exactly 0 when `special_ed_status` is `NONE`, and must be greater than 0 when
        `special_ed_status` is `IEP`."

        The PRD states: "`max_weekly_caseload_minutes`, which must be greater than zero,
        is the contractual weekly ceiling on committed homebound instruction minutes."

        Design: Corner/entities/invalid_enum_members_and_out_of_range_integers_are_rejected
        """
        set_clock(CLOCK)
        register_student(student_number="S-0001", full_name="Ada Lin")

        rejected = [
            _create_student(student_number="S-0009", full_name="Out Of Band", grade_level=13),
            _create_student(
                student_number="S-0010", full_name="Bad Enum", special_ed_status="GIFTED"
            ),
            _create_student(
                student_number="S-0011",
                full_name="Bad Iep",
                special_ed_status="NONE",
                iep_service_minutes_weekly=120,
            ),
            api_client.create_teacher(
                create_teacher_payload(
                    full_name="Zero Cap",
                    employee_number="E-1099",
                    credential_areas=["MATH"],
                    grade_bands=["MIDDLE"],
                    max_weekly_caseload_minutes=0,
                ),
                PA_HEADERS,
            ),
            api_client.create_entitlement_rule(
                create_entitlement_rule_payload(delivery_mode="HOMEROOM"), PA_HEADERS
            ),
        ]
        for response in rejected:
            validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)

        assert _students_meta()["total_count"] == 1, "only the valid student persisted"


class TestLedgerRowsAreAppendOnly:
    """No version, no update in place, and a reversal that leaves the original alone."""

    def test_the_voided_row_is_re_read_unchanged_beside_its_new_reversal(self):
        """The delivered row carries neither version nor updated_at, survives the void
        byte-for-byte, and is joined by a separate negating row.

        The PRD states: "Because nothing ever mutates them, they carry only `id` and
        `created_at` — both `updated_at` and `version` are absent from an
        `AttendanceLedgerEntry` entirely."

        The PRD states: "It appends a compensating ledger row with `attendance_code`
        `HB_REVERSAL`, whose `reversal_of_entry_id` points at the entry being reversed
        and whose `apportionment_minutes` is the arithmetic negation of that entry's
        `apportionment_minutes`."

        Design: Corner/entities/attendance_ledger_entries_are_append_only_and_carry_no_version_field
        """
        bundle = setup_delivered_session(
            rules=[MIDDLE_IN_HOME_RULE],
            certification=dict(CERT_WINDOW),
            safety_review=dict(CLEARED_SAFETY_REVIEW),
            session={
                "scheduled_start": "2026-09-07T09:00:00Z",
                "scheduled_end": "2026-09-07T11:00:00Z",
                "delivery_mode": "IN_HOME",
                "subject": "MATH",
            },
        )
        case_id = bundle["case"]["id"]

        before = ledger_entries_for_case(case_id)
        assert len(before) == 1
        original = before[0]
        assert original["attendance_code"] == "HB_PRESENT"
        assert original["apportionment_minutes"] == 120
        assert original["delivery_mode"] == "IN_HOME"
        assert "version" not in original
        assert "updated_at" not in original
        assert "created_at" in original

        validate_success(
            api_client.void_session(
                bundle["session"]["id"],
                void_session_payload(void_reason="DOCUMENTATION_DEFECT"),
                PA_HEADERS,
            )
        )

        re_read = validate_success(
            api_client.get_attendance_entry(original["id"], PA_HEADERS)
        )
        assert re_read["attendance_code"] == "HB_PRESENT"
        assert re_read["apportionment_minutes"] == 120
        assert re_read.get("reversal_of_entry_id") is None
        assert "version" not in re_read

        after = ledger_entries_for_case(case_id)
        assert len(after) == 2, "the original row was never deleted"
        reversals = [
            row for row in after if row.get("reversal_of_entry_id") == original["id"]
        ]
        assert len(reversals) == 1
        assert reversals[0]["attendance_code"] == "HB_REVERSAL"
        assert reversals[0]["apportionment_minutes"] == -120
        assert reversals[0]["session_id"] == bundle["session"]["id"]


class TestBodyForeignKeysAnswerPerEntity:
    """Tier five resolves body identifiers before any state guard is consulted."""

    def test_each_unresolved_body_identifier_names_its_own_entity(self):
        """Six creates carrying one unknown identifier each answer with the code named
        for the referenced entity, including a classroom teacher answering as a teacher
        and a missing case outranking a stale version guard.

        The PRD states: "Foreign keys supplied in the request body are resolved in this
        fixed order: `student_id`, then `teacher_id`, then `case_id`, then
        `certification_id`, then `assignment_id`, then `session_id`, then
        `classroom_teacher_id`."

        The PRD states: "A `student_id` that does not resolve yields
        `ERR_STUDENT_NOT_FOUND`; a `teacher_id` or `classroom_teacher_id` that does not
        resolve yields `ERR_TEACHER_NOT_FOUND`; a `case_id` that does not resolve yields
        `ERR_CASE_NOT_FOUND`; a `certification_id` that does not resolve yields
        `ERR_CERTIFICATION_NOT_FOUND`; an `assignment_id` that does not resolve yields
        `ERR_ASSIGNMENT_NOT_FOUND`."

        Design: Corner/entities/body_level_foreign_keys_must_resolve_to_their_entity_specific_not_found
        """
        bundle = setup_active_case(
            rules=[MIDDLE_IN_HOME_RULE],
            certification=dict(CERT_WINDOW),
            safety_review=dict(CLEARED_SAFETY_REVIEW),
        )
        case_id = bundle["case"]["id"]
        case_version_active = read_case(case_id)["version"]

        validate_error(
            api_client.create_case(create_case_payload(MISSING_UUID), CM_HEADERS),
            ApiErrorId.ERR_STUDENT_NOT_FOUND.value,
            404,
        )
        validate_error(
            api_client.create_assignment(
                create_assignment_payload(case_id, "SUPPORT", MISSING_UUID), CM_HEADERS
            ),
            ApiErrorId.ERR_TEACHER_NOT_FOUND.value,
            404,
        )
        validate_error(
            api_client.create_pacing_sync(
                create_pacing_sync_payload(case_id, MISSING_UUID), CM_HEADERS
            ),
            ApiErrorId.ERR_TEACHER_NOT_FOUND.value,
            404,
        )
        stale_on_a_missing_case = validate_error(
            api_client.create_certification(
                create_certification_payload(MISSING_UUID, 1, **CERT_WINDOW), CM_HEADERS
            ),
            ApiErrorId.ERR_CASE_NOT_FOUND.value,
            404,
        )
        assert (
            stale_on_a_missing_case["error_id"]
            != ApiErrorId.ERR_STALE_CASE_VERSION.value
        ), "the tier-7 version guard is never reached"
        validate_error(
            api_client.create_extension_request(
                create_extension_request_payload(
                    case_id, MISSING_UUID, case_version_active
                ),
                CM_HEADERS,
            ),
            ApiErrorId.ERR_CERTIFICATION_NOT_FOUND.value,
            404,
        )
        validate_error(
            api_client.create_session(
                create_session_payload(
                    case_id,
                    MISSING_UUID,
                    scheduled_start="2026-09-09T09:00:00Z",
                    scheduled_end="2026-09-09T11:00:00Z",
                ),
                CM_HEADERS,
            ),
            ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND.value,
            404,
        )

        case = read_case(case_id)
        assert case["service_status"] == "ACTIVE"
        assert case["version"] == case_version_active, (
            "six refused requests leave the parent case untouched"
        )
