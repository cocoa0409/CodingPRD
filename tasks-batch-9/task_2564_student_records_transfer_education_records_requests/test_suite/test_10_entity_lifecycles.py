"""Single-row behaviour: creation cascades, defaults, retrieval, listing, immutability.

Each scenario builds only the reference data it needs and then checks what one
call writes, what it refuses to write, and what a later read must still show.
"""
from test_helpers import (
    ADMIN,
    CLERK,
    COMPONENT_TYPE_ORDER,
    OFFICER_1,
    api_client,
    assert_common_fields,
    assert_components_in_fixed_order,
    assert_cumulative_file,
    assert_disclosure_log_entry,
    assert_error_envelope_shape,
    assert_file_component,
    assert_records_request,
    assert_state_records_rule,
    assert_student,
    create_district,
    create_state_rule,
    create_student,
    directory_disclosure_payload,
    discipline_incident_payload,
    get_component_list,
    get_disclosure_log,
    make_receiving_registrar_headers,
    make_records_clerk_headers,
    records_request_payload,
    set_clock,
    student_payload,
    validate_error,
    validate_paginated,
    validate_success,
    withdrawal_payload,
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
UNKNOWN_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


def _ca_district():
    """The minimum reference data any student needs: one state rule, one
    district."""
    create_state_rule("CA", **CA_RULE)
    return create_district("SEND01", state_code="CA", name="Sending Unified")


def _students_in_district(district_id):
    data, _meta = validate_paginated(
        api_client.list_students(OFFICER_1, params={"district_id": district_id})
    )
    return data


def _enroll_aiko_with_an_iep():
    """One enrolling call for a student with an active IEP, so all four
    component types are required of the file."""
    district = _ca_district()
    return validate_success(
        api_client.create_student(
            student_payload(
                district["id"],
                first_name="Aiko",
                last_name="Berenson",
                dob="2012-04-04",
                grade_level=8,
                has_iep=True,
                guardian_user_id="guardian-aiko",
                student_user_id="student-aiko",
            ),
            CLERK,
        ),
        201,
    )


def _files_of(student_id):
    data, _meta = validate_paginated(
        api_client.list_student_cumulative_files(student_id, CLERK)
    )
    return data


class TestEnrollmentMintsTheRecordsSkeleton:
    def test_the_new_student_owns_exactly_one_not_started_file(self):
        """The enrolling call answers 201 with the student at version 1, and the
        single file it mints sits in NOT_STARTED with all four types required and
        every counter at zero.

        PRD: "In the same transaction the student receives exactly one **cumulative file** whose `student_id` names them, whose `assembly_status` is `NOT_STARTED`, and whose `required_component_types` is pinned from the student's `has_iep` value: `ACADEMIC`, `HEALTH`, and `DISCIPLINE` always, plus `SPECIAL_EDUCATION` when an IEP is active."

        Design: Corner/entities/student_creation_mints_cumulative_file_and_four_components
        """
        student = _enroll_aiko_with_an_iep()

        assert_student(student)
        assert student["enrollment_status"] == "ENROLLED"
        assert student["has_iep"] is True
        assert student["is_eligible_student"] is False
        assert student["directory_optout_deadline_at"] == "2026-08-15T00:00:00.000Z"
        assert student["directory_optout_effective"] is False
        assert student["exit_effective_date"] is None
        assert student["version"] == 1

        files = _files_of(student["id"])
        assert len(files) == 1, f"a student owns exactly one file, got {len(files)}"
        file = files[0]
        assert_cumulative_file(file)
        assert file["student_id"] == student["id"]
        assert file["assembly_status"] == "NOT_STARTED"
        assert file["required_component_types"] == COMPONENT_TYPE_ORDER
        assert file["certified_component_count"] == 0
        assert file["completeness_pct"] == 0.0
        assert file["total_page_count"] == 0

    def test_four_components_are_minted_pending_and_all_of_them_required(self):
        """Four components arrive by cascade in the fixed type order, each still
        PENDING with no pages, and with the IEP active every one of them is
        flagged required.

        PRD: "Four **file components** are minted alongside it, one for each `component_type` in `ACADEMIC`, `HEALTH`, `DISCIPLINE`, and `SPECIAL_EDUCATION`, regardless of IEP status; each carries the file's identifier as its `cumulative_file_id`, a `status` of `PENDING`, a `page_count` and `redacted_page_count` of 0, an `amendment_count` of 0, `statement_of_disagreement_present` false, `exclusion_reason`, `certified_by_user_id`, and `certified_at` all null, and an `is_required` flag set true exactly when its type appears in the file's `required_component_types`."

        Design: Corner/entities/student_creation_mints_cumulative_file_and_four_components
        """
        student = _enroll_aiko_with_an_iep()
        file = _files_of(student["id"])[0]

        components = get_component_list(file["id"])

        assert len(components) == 4, f"four components are minted, got {len(components)}"
        assert_components_in_fixed_order(components)
        for component in components:
            assert_file_component(component)
            assert component["cumulative_file_id"] == file["id"]
            assert component["status"] == "PENDING"
            assert component["is_required"] is True
            assert component["page_count"] == 0
            assert component["redacted_page_count"] == 0
            assert component["certified_at"] is None
            assert component["exclusion_reason"] is None


class TestStudentComputedFieldsAreServerDerived:
    def test_client_supplied_values_for_derived_fields_do_not_survive(self):
        """The body asks for a WITHDRAWN status, a false eligibility flag and a
        disposition date; the enrolment still lands ENROLLED, eligible on the
        student's eighteenth birthday, and with no disposition date at all.

        PRD: "Both `exit_effective_date` and `records_disposition_date` start null: the first is filled from the withdrawal that ends the student's enrollment, the second mirrors a retention schedule that does not yet exist."

        Design: Corner/entities/student_computed_fields_input_ignored
        """
        district = _ca_district()

        student = validate_success(
            api_client.create_student(
                student_payload(
                    district["id"],
                    first_name="Hugo",
                    last_name="Petrov",
                    dob="2008-08-01",
                    grade_level=12,
                    has_iep=False,
                    guardian_user_id="guardian-hugo",
                    student_user_id="student-hugo",
                    enrollment_status="WITHDRAWN",
                    is_eligible_student=False,
                    records_disposition_date="2020-01-01T00:00:00.000Z",
                ),
                CLERK,
            ),
            201,
        )

        assert_student(student)
        assert student["enrollment_status"] == "ENROLLED"
        assert student["is_eligible_student"] is True, (
            "a student born 2008-08-01 is eligible from 2026-08-01T00:00:00.000Z"
        )
        assert student["records_disposition_date"] is None
        assert student["directory_optout_categories"] == []
        assert student["directory_optout_effective"] is False


TX_RULE_WITHOUT_THRESHOLD = {
    "state_code": "TX",
    "transfer_response_days": 30,
    "discipline_inclusion_mode": "ALL_INCIDENTS",
    "include_pending_investigations": True,
    "sped_requires_consent": False,
    "amendment_hearing_days": 45,
    "destruction_min_age_years": 7,
    "directory_optout_grace_days": 10,
    "notification_wait_days": 3,
}


class TestStateRuleReadByItsNaturalKey:
    def test_a_rule_registered_without_the_threshold_reads_back_the_default_ten(self):
        """The rule is addressed by its two-letter code rather than by a UUID, and
        the omitted instructional-day threshold comes back as 10 with every other
        configured parameter round-tripped.

        PRD: "`discipline_min_days_removed` is the instructional-day threshold a suspension must meet under the middle mode, defaults to 10 when omitted, and is ignored by the other two modes."

        Design: Corner/entities/state_rule_retrieval_by_natural_key
        """
        validate_success(api_client.create_state_rule(TX_RULE_WITHOUT_THRESHOLD, ADMIN), 201)

        response = api_client.get_state_rule("TX", OFFICER_1)

        rule = validate_success(response)
        assert response.json()["response_type"] == "object"
        assert_state_records_rule(rule)
        assert rule["state_code"] == "TX"
        assert rule["transfer_response_days"] == 30
        assert rule["discipline_inclusion_mode"] == "ALL_INCIDENTS"
        assert rule["discipline_min_days_removed"] == 10
        assert rule["include_pending_investigations"] is True
        assert rule["sped_requires_consent"] is False
        assert rule["destruction_min_age_years"] == 7
        assert rule["amendment_hearing_days"] == 45
        assert rule["directory_optout_grace_days"] == 10
        assert rule["notification_wait_days"] == 3


LING_SIBLINGS = (
    ("Bo", "2012-01-01", 8, False, "guardian-bo"),
    ("Cai", "2011-01-01", 9, False, "guardian-cai"),
    ("Dara", "2010-01-01", 10, True, "guardian-dara"),
)


def _three_students_here_and_one_elsewhere():
    """SEND01 in CA holds the three Ling siblings; SEND02 in TX holds Eli Stone,
    who must never appear under the SEND01 filter."""
    create_state_rule("CA", **CA_RULE)
    create_state_rule("TX", **TX_RULE)
    here = create_district("SEND01", state_code="CA", name="Sending Unified")
    elsewhere = create_district("SEND02", state_code="TX", name="Second Unified")
    for first_name, dob, grade_level, has_iep, guardian in LING_SIBLINGS:
        create_student(
            here["id"],
            first_name=first_name,
            last_name="Ling",
            dob=dob,
            grade_level=grade_level,
            has_iep=has_iep,
            guardian_user_id=guardian,
        )
    create_student(
        elsewhere["id"],
        first_name="Eli",
        last_name="Stone",
        dob="2010-02-02",
        grade_level=10,
        has_iep=False,
        guardian_user_id="guardian-eli",
    )
    return here, elsewhere


class TestStudentListingFiltersAndPaginates:
    def test_the_district_filter_narrows_to_three_rows_across_two_pages(self):
        """With limit 2 the first page carries two of the three matching rows and
        reports more to come; offset 2 returns the last row and closes the page
        run, and the other district's student never appears.

        PRD: "Both are echoed back in the `meta` object of the envelope alongside `total_count`, the number of items matching the query before pagination, and `has_more`, which is true whenever items remain beyond the current page."

        Design: Corner/entities/students_list_filters_by_district_and_paginates
        """
        here, elsewhere = _three_students_here_and_one_elsewhere()

        page_one, meta_one = validate_paginated(
            api_client.list_students(
                OFFICER_1, params={"district_id": here["id"], "limit": 2, "offset": 0}
            )
        )
        page_two, meta_two = validate_paginated(
            api_client.list_students(
                OFFICER_1, params={"district_id": here["id"], "limit": 2, "offset": 2}
            )
        )

        assert len(page_one) == 2, f"limit 2 returns two rows, got {len(page_one)}"
        assert meta_one["total_count"] == 3
        assert meta_one["limit"] == 2
        assert meta_one["offset"] == 0
        assert meta_one["has_more"] is True

        assert len(page_two) == 1, f"one row remains, got {len(page_two)}"
        assert meta_two["total_count"] == 3
        assert meta_two["offset"] == 2
        assert meta_two["has_more"] is False

        for row in page_one + page_two:
            assert_student(row)
            assert row["district_id"] == here["id"]
            assert row["district_id"] != elsewhere["id"]
        assert len(_students_in_district(here["id"])) == 3

        with_iep, _meta = validate_paginated(
            api_client.list_students(OFFICER_1, params={"has_iep": "true"})
        )
        assert len(with_iep) == 1, f"only Dara Ling holds an IEP, got {len(with_iep)}"
        assert with_iep[0]["has_iep"] is True


class TestUnknownIdentifiersAnswerWithTheirOwnCode:
    def test_an_unknown_student_uuid_and_an_unknown_state_code_each_404(self):
        """A well-formed UUID that resolves to nothing is a 404 in the error
        envelope rather than an empty object, and the natural-key state segment
        behaves the same way with its own code.

        PRD: "Every identifier in a path is resolved left to right, and the first one that does not resolve terminates the request with the 404 that names that resource: a bad file identifier yields `ERR_CUMULATIVE_FILE_NOT_FOUND` before the component is looked at, and a component identifier that resolves to a row belonging to a different file is treated as unresolved and yields `ERR_FILE_COMPONENT_NOT_FOUND`."

        Design: Corner/entities/get_student_with_unknown_id_returns_4xx
        """
        _ca_district()

        response = api_client.get_student(UNKNOWN_ID, OFFICER_1)

        assert_error_envelope_shape(response)
        validate_error(response, "ERR_STUDENT_NOT_FOUND", 404)

        missing_state = api_client.get_state_rule("WY", OFFICER_1)
        assert_error_envelope_shape(missing_state)
        validate_error(missing_state, "ERR_STATE_RULE_NOT_FOUND", 404)


class TestRequiredEnrollmentFields:
    def test_omitting_the_guardian_rejects_the_enrolment_and_stores_nothing(self):
        """`guardian_user_id` has no default, so an otherwise sound body without it
        is a payload error and leaves no student behind to carry a file.

        PRD: "The bands, in order, are: **path and body reference existence** (HTTP 404 — every identifier resolves, left to right); **authorization** (HTTP 403 — role permission, rights transfer, guardianship, district ownership, segregation of duties); **payload schema** (HTTP 400 — required fields present and non-null, enum membership, numeric ranges, parseable instants, interval sanity); **optimistic locking** (HTTP 412 — the supplied expected version matches the parent's current version); **entity state** (HTTP 409 — the target resource is in a state that permits the action); **cross-entity state** (HTTP 409 — a different resource is in the state the action requires); **temporal conflict** (HTTP 409 — interval overlap or capacity over a time window); **business rule** (HTTP 422 — statutory windows, consent, custody, conservation); and finally **uniqueness** (HTTP 409 — natural-key and one-active-per-scope collisions)."

        Design: Corner/entities/student_missing_required_guardian_user_id_returns_4xx
        """
        district = _ca_district()

        response = api_client.create_student(
            {
                "district_id": district["id"],
                "first_name": "Fern",
                "last_name": "Okafor",
                "dob": "2012-05-05",
                "grade_level": 8,
            },
            CLERK,
        )

        validate_error(response, "ERR_VALIDATION", 400)

        rows, meta = validate_paginated(api_client.list_students(OFFICER_1))
        assert rows == [], f"no student may have been stored, got {len(rows)}"
        assert meta["total_count"] == 0


def _two_districts_and_one_student_on_the_third_of_august():
    """SEND01 in CA owns the record and answers; RECV01 in TX asks. The clock
    stands at Monday 2026-08-03, so ten business days land on 2026-08-17."""
    create_state_rule("CA", **CA_RULE)
    create_state_rule("TX", **TX_RULE)
    responding = create_district("SEND01", state_code="CA", name="Sending Unified")
    requesting = create_district("RECV01", state_code="TX", name="Receiving Unified")
    student = create_student(
        responding["id"],
        first_name="Gita",
        last_name="Halim",
        dob="2011-03-03",
        grade_level=9,
        has_iep=False,
        guardian_user_id="guardian-gita",
    )
    set_clock("2026-08-03T00:00:00Z")
    return responding, requesting, student


class TestRecordsRequestDefaults:
    def test_the_three_omitted_facts_take_their_declared_defaults(self):
        """A filing that names only the two districts, the student and the
        authorization reference lands STANDARD, without special education, without
        consent on file, unverified, in RECEIVED with no packet.

        PRD: "Four further facts are optional at filing: `request_priority`, either `STANDARD` or `UNACCOMPANIED_YOUTH`, defaulting to `STANDARD`; `includes_special_education`, declaring whether the requesting district demands the special-education component, defaulting to false; `sped_consent_on_file`, declaring whether signed consent for special-education release is held, defaulting to false; and `authorization_reference`, the enrollment-authorization document reference supplied by the requesting district, defaulting to null."

        Design: Corner/entities/records_request_defaults_applied_when_optional_fields_omitted
        """
        responding, requesting, student = _two_districts_and_one_student_on_the_third_of_august()

        request = validate_success(
            api_client.create_records_request(
                records_request_payload(
                    student["id"],
                    requesting["id"],
                    responding["id"],
                    authorization_reference="ENR-2026-9001",
                ),
                make_receiving_registrar_headers(requesting["id"]),
            ),
            201,
        )

        assert_records_request(request)
        assert request["request_priority"] == "STANDARD"
        assert request["includes_special_education"] is False
        assert request["sped_consent_on_file"] is False
        assert request["authorization_verified"] is False
        assert request["status"] == "RECEIVED"
        assert request["packet_status"] == "NONE"
        assert request["packet_page_count"] is None
        assert request["reopen_count"] == 0
        assert request["is_overdue"] is False
        assert request["statutory_days_allowed"] == 10
        assert request["statutory_due_at"] == "2026-08-17T23:59:59.999Z"


class TestDisclosureLogEntrySystemFields:
    def test_a_directory_disclosure_stamps_the_clock_and_the_acting_operator(self):
        """Nothing about the log entry is client-supplied beyond the recipient and
        the categories: the type, the source, the page count, the instant and the
        operator are all derived by the server.

        PRD: "An accepted release appends a **disclosure log entry** whose `student_id` names the student, whose `disclosure_type` is `DIRECTORY_INFORMATION` and `source_type` is `STUDENT_DIRECTORY`, whose `source_id` is the student's own identifier, whose `disclosed_categories` are stored in the fixed directory order `NAME`, `ADDRESS`, `PHONE`, `PHOTO`, `HONORS`, `SPORTS_PARTICIPATION`, whose `page_count` is 0 because no pages leave the office, whose `disclosed_at` is the current logical clock instant, and whose `logged_by_user_id` is the acting `X-User-ID`."

        Design: Corner/entities/disclosure_log_entry_system_fields_generated
        """
        district = _ca_district()
        student = create_student(
            district["id"],
            first_name="Ines",
            last_name="Duarte",
            dob="2012-07-07",
            grade_level=8,
            has_iep=False,
            guardian_user_id="guardian-ines",
        )
        set_clock("2026-08-05T16:45:00Z")

        validate_success(
            api_client.create_directory_disclosure(
                student["id"],
                directory_disclosure_payload(
                    recipient_name="Alta County Sports League",
                    disclosed_categories=["NAME", "SPORTS_PARTICIPATION"],
                    legitimate_interest_note="Team roster publication",
                ),
                make_records_clerk_headers("clerk-7"),
            ),
            201,
        )

        entries = get_disclosure_log(student["id"], headers=CLERK)
        assert len(entries) == 1, f"one release appends one entry, got {len(entries)}"
        entry = entries[0]
        assert_disclosure_log_entry(entry)
        assert entry["student_id"] == student["id"]
        assert entry["disclosure_type"] == "DIRECTORY_INFORMATION"
        assert entry["source_type"] == "STUDENT_DIRECTORY"
        assert entry["source_id"] == student["id"]
        assert entry["page_count"] == 0
        assert entry["disclosed_at"] == "2026-08-05T16:45:00.000Z"
        assert entry["logged_by_user_id"] == "clerk-7"
        assert entry["recipient_name"] == "Alta County Sports League"
        assert entry["disclosed_categories"] == ["NAME", "SPORTS_PARTICIPATION"]


class TestDisclosureLogEntryIsAppendOnly:
    def test_two_entries_carry_no_version_and_the_earlier_one_never_moves(self):
        """The log exposes only `id` and `created_at` from the common fields, and a
        second release at a later instant leaves the first entry's instant and
        operator exactly as they were written.

        PRD: "A **disclosure log entry** is append-only: entries are written by the operations they document and are never edited, so they too expose neither `updated_at` nor `version`."

        Design: Corner/entities/disclosure_log_entry_is_immutable_without_version
        """
        district = _ca_district()
        student = create_student(
            district["id"],
            first_name="Kofi",
            last_name="Mensah",
            dob="2012-02-02",
            grade_level=8,
            has_iep=False,
            guardian_user_id="guardian-kofi",
        )
        validate_success(
            api_client.create_directory_disclosure(
                student["id"],
                directory_disclosure_payload(
                    recipient_name="Yearbook Vendor", disclosed_categories=["NAME"]
                ),
                make_records_clerk_headers("clerk-7"),
            ),
            201,
        )
        set_clock("2026-08-06T09:00:00Z")

        validate_success(
            api_client.create_directory_disclosure(
                student["id"],
                directory_disclosure_payload(
                    recipient_name="Class Ring Vendor",
                    disclosed_categories=["NAME", "HONORS"],
                ),
                make_records_clerk_headers("clerk-9"),
            ),
            201,
        )

        entries = get_disclosure_log(student["id"], headers=CLERK)
        assert len(entries) == 2, f"the log holds two entries, got {len(entries)}"
        for entry in entries:
            assert_common_fields(entry, versioned=False)
            assert "version" not in entry, "an append-only entry exposes no version"
            assert "updated_at" not in entry, "an append-only entry exposes no updated_at"

        earlier, later = entries
        assert earlier["disclosed_at"] == "2026-08-01T00:00:00.000Z"
        assert earlier["logged_by_user_id"] == "clerk-7"
        assert earlier["recipient_name"] == "Yearbook Vendor"
        assert later["disclosed_at"] == "2026-08-06T09:00:00.000Z"
        assert later["logged_by_user_id"] == "clerk-9"
        assert later["disclosed_categories"] == ["NAME", "HONORS"]


class TestDisciplineIncidentTypeConstraints:
    def test_an_unlisted_action_type_and_an_over_range_day_count_are_both_refused(self):
        """`action_type` is a closed set and `days_removed` is capped at 365, so
        each body is a payload error and the student's incident list stays empty.

        PRD: "Recording an incident takes the `incident_date` as an ISO 8601 calendar date, an `action_type` of `SUSPENSION`, `EXPULSION`, `DETENTION`, or `BEHAVIOR_PLAN`, a `description` narrative that is filed into the discipline component, and three optional facts: `days_removed`, the number of instructional days the student was removed, which defaults to 0 and must be at least 0 and at most 365; `incident_status`, one of `SUSTAINED`, `PENDING_INVESTIGATION`, or `DISMISSED`, which defaults to `SUSTAINED`; and `adjudicated_by_court`, recording whether a court adjudicated the underlying conduct, which defaults to false."

        Design: Corner/entities/discipline_incident_invalid_action_type_rejected
        """
        district = _ca_district()
        student = create_student(
            district["id"],
            first_name="Jae",
            last_name="Moreau",
            dob="2011-06-06",
            grade_level=9,
            has_iep=False,
            guardian_user_id="guardian-jae",
        )

        out_of_set = api_client.create_discipline_incident(
            student["id"],
            discipline_incident_payload(
                incident_date="2026-05-05",
                action_type="SATURDAY_SCHOOL",
                days_removed=1,
                incident_status="SUSTAINED",
                description="Not a declared action type",
            ),
            CLERK,
        )
        over_range = api_client.create_discipline_incident(
            student["id"],
            discipline_incident_payload(
                incident_date="2026-05-06",
                action_type="SUSPENSION",
                days_removed=400,
                incident_status="SUSTAINED",
                description="Over the 365 day ceiling",
            ),
            CLERK,
        )

        validate_error(out_of_set, "ERR_VALIDATION", 400)
        validate_error(over_range, "ERR_VALIDATION", 400)

        rows, meta = validate_paginated(
            api_client.list_student_discipline_incidents(student["id"], CLERK)
        )
        assert rows == [], f"neither body may have been stored, got {len(rows)}"
        assert meta["total_count"] == 0


class TestUnresolvedParentAndBodyReferences:
    def test_a_withdrawal_under_an_unknown_student_never_reaches_the_body(self):
        """The withdrawal body is entirely well formed, but its parent does not
        exist, so the student's own 404 answers and no orphan row can be created.

        PRD: "Each resource family has its own code: `ERR_DISTRICT_NOT_FOUND`, `ERR_STATE_RULE_NOT_FOUND`, `ERR_STUDENT_NOT_FOUND`, `ERR_WITHDRAWAL_NOT_FOUND`, `ERR_CUMULATIVE_FILE_NOT_FOUND`, `ERR_FILE_COMPONENT_NOT_FOUND`, `ERR_DISCIPLINE_INCIDENT_NOT_FOUND`, `ERR_RECORDS_REQUEST_NOT_FOUND`, `ERR_INSPECTION_ROOM_NOT_FOUND`, `ERR_INSPECTION_REQUEST_NOT_FOUND`, `ERR_REVIEW_APPOINTMENT_NOT_FOUND`, `ERR_HEARING_OFFICER_NOT_FOUND`, `ERR_AMENDMENT_REQUEST_NOT_FOUND`, `ERR_LEGAL_DEMAND_NOT_FOUND`, and `ERR_RETENTION_SCHEDULE_NOT_FOUND`."

        Design: Corner/entities/withdrawal_under_unknown_student_returns_4xx
        """
        _ca_district()

        response = api_client.create_withdrawal(
            UNKNOWN_ID,
            withdrawal_payload(
                effective_date="2026-08-14",
                destination_district_code="RECV01",
                withdrawal_reason="MOVED",
            ),
            CLERK,
        )

        assert_error_envelope_shape(response)
        validate_error(response, "ERR_STUDENT_NOT_FOUND", 404)

    def test_an_unknown_requesting_district_in_the_body_is_a_district_404(self):
        """The path-level student resolves and the responding district resolves;
        the unresolvable requesting district in the same body answers with the
        district's own code and files nothing.

        PRD: "References supplied in a request body are resolved with the same codes and at the same precedence as path identifiers, before roles are considered against payload contents."

        Design: Corner/entities/records_request_with_unknown_requesting_district_returns_4xx
        """
        district = _ca_district()
        student = create_student(
            district["id"],
            first_name="Lior",
            last_name="Ben-Ami",
            dob="2011-08-08",
            grade_level=9,
            has_iep=False,
            guardian_user_id="guardian-lior",
        )

        response = api_client.create_records_request(
            records_request_payload(
                student["id"],
                UNKNOWN_ID,
                district["id"],
                authorization_reference="ENR-2026-9002",
            ),
            OFFICER_1,
        )

        validate_error(response, "ERR_DISTRICT_NOT_FOUND", 404)

        rows, meta = validate_paginated(
            api_client.list_records_requests(OFFICER_1, params={"student_id": student["id"]})
        )
        assert rows == [], f"no request may have been filed, got {len(rows)}"
        assert meta["total_count"] == 0
