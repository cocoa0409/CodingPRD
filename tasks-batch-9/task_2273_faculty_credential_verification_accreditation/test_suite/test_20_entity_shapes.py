"""Entity shapes: echoed inputs, minted system fields, defaults and reads."""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_common_entity_fields,
    assert_fields,
    assert_ordered_codes,
    assert_program_adequacy,
    assert_roster_snapshot,
    assert_score,
    assert_total_count,
    discipline_payload,
    faculty_payload,
    file_credential,
    generate_roster,
    ids_of,
    make_assignment,
    make_credentialed_faculty,
    make_faculty,
    make_roster,
    make_section,
    make_verified_credential,
    NON_EXISTENT_ID,
    program_payload,
    read_faculty,
    read_program,
    section_payload,
    set_clock,
    term_payload,
    total_count,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)


class TestCourseSectionCreation:
    def test_section_creation_echoes_its_inputs_and_leaves_the_instructor_null(
        self, api, env
    ):
        """PRD §3.4: "A new section begins with `instructor_of_record_id` null."

        Design: Corner/entities/course_section_creation_returns_declared_fields_with_null_instructor
        """
        payload = section_payload(
            env.prog_df_id,
            env.term_id,
            env.journ_id,
            "JOUR101",
            "News Writing",
            credit_hours=3,
            course_level="LOWER_DIVISION",
            delivery_mode="IN_PERSON",
            building_code="HALL-A",
            meeting_days=["MON"],
            meeting_start_minute=540,
            meeting_end_minute=620,
        )

        section = validate_success(
            api.create_course_section(payload, env.dean_df), 201
        )

        assert_fields(
            section,
            course_code="JOUR101",
            title="News Writing",
            course_level="LOWER_DIVISION",
            credit_hours=3,
            delivery_mode="IN_PERSON",
            building_code="HALL-A",
            meeting_start_minute=540,
            meeting_end_minute=620,
            program_id=env.prog_df_id,
            term_id=env.term_id,
            discipline_id=env.journ_id,
            instructor_of_record_id=None,
        )
        assert_ordered_codes(section["meeting_days"], ["MON"], "meeting_days")
        assert_common_entity_fields(section, expected_version=1)


class TestDeclaredDefaults:
    def test_optional_inputs_fall_back_to_their_declared_defaults(self, api):
        """PRD §3.1: "an optional `min_graduate_credit_hours` that defaults to 18 and
        may not be negative".

        Design: Corner/entities/program_and_discipline_defaults_applied_when_optional_inputs_omitted
        """
        set_clock()

        discipline = validate_success(
            api.create_discipline(
                discipline_payload("52.14", "Marketing", "DOCTORATE"),
                TEST_USERS["admin"],
            ),
            201,
        )
        program = validate_success(
            api.create_program(
                program_payload(
                    "MS Marketing Analytics",
                    discipline["id"],
                    degree_level="MASTERS",
                    qualification_policy="DEGREE_FIELD",
                    adequacy_basis="HEADCOUNT",
                    credential_budget_cents=250000,
                ),
                TEST_USERS["admin"],
            ),
            201,
        )

        assert_fields(
            discipline, min_graduate_credit_hours=18, parent_discipline_id=None
        )
        assert_score(program["min_terminal_ratio"], 0.75, "min_terminal_ratio")
        assert_fields(
            program,
            is_substantive_change=False,
            launch_status="PLANNING",
            adequacy_status="INSUFFICIENT",
            unqualified_assignment_count=0,
            adequacy_term_id=None,
            budget_reserved_cents=0,
            budget_spent_cents=0,
            credential_budget_cents=250000,
            version=1,
        )
        assert_score(program["adequacy_ratio"], 0.0000, "adequacy_ratio")


class TestCredentialRecordSystemFields:
    def test_filing_a_record_mints_its_system_fields(self, api, env):
        """PRD §3.2: "A new record begins with `verification_status` `PENDING`,
        `transcript_status` `NOT_REQUESTED`, `verified_by_user_id` null, and both
        `effective_degree_level` and `effective_discipline_id` null."

        Design: Corner/entities/credential_record_system_fields_minted_and_dossier_moves_under_review
        """
        dana = make_faculty(
            "Dana Reyes", "dana.reyes@example.edu", "ADJUNCT", env.prog_df_id
        )
        assert_fields(dana, dossier_status="INCOMPLETE", appointment_status="PROSPECT")

        record = file_credential(
            dana["id"],
            "MASTERS",
            env.pr_id,
            "State University",
            is_foreign_institution=False,
            graduate_credit_hours_in_discipline=30,
        )

        assert_fields(
            record,
            transcript_status="NOT_REQUESTED",
            verification_status="PENDING",
            verified_by_user_id=None,
            effective_degree_level=None,
            effective_discipline_id=None,
            version=1,
        )
        faculty = read_faculty(dana["id"])
        assert_fields(
            faculty,
            dossier_status="UNDER_REVIEW",
            appointment_status="PROSPECT",
            highest_verified_degree_level=None,
        )
        assert_ordered_codes(
            faculty["deficiency_codes"], ["TRANSCRIPT_NOT_OFFICIAL"], "deficiency_codes"
        )


class TestFacultyMemberRetrieval:
    def test_reading_a_faculty_member_returns_stored_and_derived_fields(self, api, env):
        """PRD §3.2: "Alongside this, `highest_verified_degree_level` is set to the
        greatest effective degree level over the records whose `verification_status`
        is `VERIFIED`, ranking `NON_DEGREE_GRADUATE` below `BACHELORS`, below
        `MASTERS`, below `DOCTORATE`, and set to null when there are no verified
        records."

        Design: Corner/entities/faculty_member_retrieval_returns_stored_and_computed_dossier_fields
        """
        dana = make_credentialed_faculty(
            "Dana Reyes",
            "dana.reyes@example.edu",
            "ADJUNCT",
            env.prog_df_id,
            "MASTERS",
            env.pr_id,
            "State University",
            graduate_credit_hours_in_discipline=30,
        )
        record = dana["record"]
        make_verified_credential(
            dana["faculty"]["id"],
            "NON_DEGREE_GRADUATE",
            env.journ_id,
            "State University",
            graduate_credit_hours_in_discipline=18,
        )

        faculty = validate_success(
            api.get_faculty_member(dana["faculty"]["id"], TEST_USERS["registrar"])
        )

        assert_fields(
            faculty,
            full_name="Dana Reyes",
            email="dana.reyes@example.edu",
            employment_class="ADJUNCT",
            home_program_id=env.prog_df_id,
            dossier_status="VERIFIED",
            appointment_status="CREDENTIALED_ELIGIBLE",
            highest_verified_degree_level="MASTERS",
            assigned_credit_hours=0,
            pd_hours_current_cycle=0,
            pd_compliant=False,
        )
        assert_ordered_codes(faculty["deficiency_codes"], [], "deficiency_codes")
        assert_fields(
            validate_success(
                api.get_credential_record(record["id"], TEST_USERS["analyst"])
            ),
            verified_by_user_id="analyst-01",
        )


class TestCredentialRecordListing:
    def test_listing_paginates_and_filters_over_the_same_collection(self, api, env):
        """PRD §2.3: "Every list response reports `limit`, `offset`, `total_count`
        and `has_more` inside the `meta` object of the envelope, where `total_count`
        is the number of rows matching the filter before pagination and `has_more`
        indicates whether rows remain beyond the current page."

        Design: Corner/entities/credential_record_listing_filters_and_paginates_consistently
        """
        dana = make_credentialed_faculty(
            "Dana Reyes",
            "dana.reyes@example.edu",
            "ADJUNCT",
            env.prog_df_id,
            "MASTERS",
            env.pr_id,
            "State University",
            graduate_credit_hours_in_discipline=30,
        )["faculty"]
        make_verified_credential(
            dana["id"],
            "NON_DEGREE_GRADUATE",
            env.journ_id,
            "State University",
            graduate_credit_hours_in_discipline=18,
        )
        pending = file_credential(
            dana["id"],
            "BACHELORS",
            env.pr_id,
            "Riverside College",
            is_foreign_institution=False,
            graduate_credit_hours_in_discipline=0,
        )

        first_rows, first_meta = validate_paginated(
            api.list_credential_records(
                TEST_USERS["analyst"],
                {"faculty_member_id": dana["id"], "limit": 2, "offset": 0},
            )
        )
        second_rows, second_meta = validate_paginated(
            api.list_credential_records(
                TEST_USERS["analyst"],
                {"faculty_member_id": dana["id"], "limit": 2, "offset": 2},
            )
        )
        filtered_rows, filtered_meta = validate_paginated(
            api.list_credential_records(
                TEST_USERS["analyst"],
                {"faculty_member_id": dana["id"], "verification_status": "PENDING"},
            )
        )

        assert_total_count(first_meta, 3, "unfiltered first page")
        assert_fields(first_meta, has_more=True, limit=2, offset=0)
        assert len(first_rows) == 2, f"expected 2 rows on the first page, got {first_rows}"
        assert_total_count(second_meta, 3, "unfiltered second page")
        assert_fields(second_meta, has_more=False)
        assert len(second_rows) == 1, f"expected 1 row on the second page, got {second_rows}"
        assert_total_count(filtered_meta, 1, "PENDING filter")
        assert ids_of(filtered_rows) == [pending["id"]], (
            "the filter must count and return only the pending record"
        )
        assert_fields(read_faculty(dana["id"]), dossier_status="UNDER_REVIEW")


class TestRosterComputedFields:
    def test_roster_counters_are_computed_at_draft_and_at_generation(self, api, env):
        """PRD §3.6: "The new roster begins with `generation_epoch` 0, every snapshot
        count at 0, `adequacy_ratio_snapshot` 0.0, `certification_readiness`
        `BLOCKED`, `blocking_reason_codes` empty, and both `certified_at` and
        `certified_by_user_id` null."

        Design: Corner/entities/roster_snapshot_fields_are_computed_not_client_supplied
        """
        morgan = make_credentialed_faculty(
            "Morgan Ellis",
            "morgan.ellis@example.edu",
            "FULL_TIME",
            env.prog_cw_id,
            "MASTERS",
            env.journ_id,
            "Lakeside University",
            graduate_credit_hours_in_discipline=36,
        )["faculty"]
        section = make_section(
            env.prog_df_id,
            env.term_id,
            env.journ_id,
            "JOUR101",
            "News Writing",
            credit_hours=3,
            meeting_days=["MON"],
            meeting_start_minute=540,
            meeting_end_minute=620,
        )
        make_assignment(section["id"], morgan["id"], env.prog_df_id)

        draft = make_roster(env.prog_df_id, env.term_id)

        assert_roster_snapshot(
            draft,
            status="DRAFT",
            generation_epoch=0,
            total_assignment_count=0,
            distinct_faculty_count=0,
            flagged_exception_count=0,
            terminal_qualified_headcount=0,
            credit_hours_total=0,
            credit_hours_terminal_qualified=0,
            adequacy_ratio_snapshot=0.0000,
            certification_readiness="BLOCKED",
            blocking_reason_codes=[],
            certified_at=None,
            certified_by_user_id=None,
        )

        generated = generate_roster(draft["id"])

        assert_roster_snapshot(
            generated,
            status="GENERATED",
            generation_epoch=1,
            total_assignment_count=1,
            distinct_faculty_count=1,
            flagged_exception_count=0,
            terminal_qualified_headcount=1,
            credit_hours_total=3,
            credit_hours_terminal_qualified=3,
            adequacy_ratio_snapshot=1.0000,
            blocking_reason_codes=[],
            certification_readiness="READY",
        )
        assert_program_adequacy(
            read_program(env.prog_df_id),
            adequacy_ratio=1.0000,
            adequacy_status="ADEQUATE",
            adequacy_term_id=env.term_id,
            unqualified_assignment_count=0,
        )


NOT_FOUND_PROBES = [
    ("get_discipline", "admin", ApiErrorId.ERR_DISCIPLINE_NOT_FOUND),
    ("get_program", "admin", ApiErrorId.ERR_PROGRAM_NOT_FOUND),
    ("get_term", "registrar", ApiErrorId.ERR_TERM_NOT_FOUND),
    ("get_faculty_member", "registrar", ApiErrorId.ERR_FACULTY_NOT_FOUND),
    ("get_credential_record", "analyst", ApiErrorId.ERR_CREDENTIAL_RECORD_NOT_FOUND),
    ("get_credential_evaluation", "analyst", ApiErrorId.ERR_EVALUATION_NOT_FOUND),
    ("get_course_section", "registrar", ApiErrorId.ERR_SECTION_NOT_FOUND),
    ("get_course_assignment", "registrar", ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND),
    ("get_justification", "analyst", ApiErrorId.ERR_JUSTIFICATION_NOT_FOUND),
    ("get_roster", "liaison", ApiErrorId.ERR_ROSTER_NOT_FOUND),
    ("get_contract", "registrar", ApiErrorId.ERR_CONTRACT_NOT_FOUND),
    ("get_pd_record", "registrar", ApiErrorId.ERR_PD_RECORD_NOT_FOUND),
    ("get_review", "reviewer", ApiErrorId.ERR_REVIEW_NOT_FOUND),
]


class TestEntitySpecificNotFound:
    @pytest.mark.parametrize(
        "method_name,role,expected_error",
        NOT_FOUND_PROBES,
        ids=[probe[2].value for probe in NOT_FOUND_PROBES],
    )
    def test_a_well_formed_unknown_id_returns_the_addressed_entitys_404(
        self, api, method_name, role, expected_error
    ):
        """PRD §2.10: "Every identifier in the request path resolves → otherwise the
        entity's own 404 code. Applies to every path-parameterised endpoint."

        Design: Corner/entities/unknown_path_ids_return_entity_specific_not_found_errors
        """
        set_clock()

        response = getattr(api, method_name)(NON_EXISTENT_ID, TEST_USERS[role])

        validate_error(response, expected_error)
        body = response.json()["data"]
        assert isinstance(body.get("message"), str) and body["message"], (
            f"{method_name} must report a non-empty message, got {body!r}"
        )


class TestRequiredInputs:
    def test_omitting_a_required_field_is_rejected_before_any_state_check(
        self, api, env
    ):
        """PRD §2.10: "Request body and query parameters satisfy the declared shape —
        required fields present, types correct, enum literals known, numeric bounds
        respected, dates well formed, arrays non-null → otherwise
        `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/missing_required_input_fields_rejected_before_any_state_check
        """
        faculty_body = faculty_payload(
            "Nameless Person", "nameless@example.edu", "ADJUNCT", env.prog_df_id
        )
        faculty_body.pop("employment_class")
        section_body = section_payload(
            env.prog_df_id,
            env.term_id,
            env.journ_id,
            "JOUR199",
            "Special Topics",
            meeting_days=["FRI"],
        )
        section_body.pop("credit_hours")

        no_class = api.create_faculty_member(faculty_body, TEST_USERS["registrar"])
        no_hours = api.create_course_section(section_body, env.dean_df)

        validate_error(no_class, ApiErrorId.ERR_INVALID_REQUEST)
        validate_error(no_hours, ApiErrorId.ERR_INVALID_REQUEST)
        assert total_count(
            api.list_faculty_members(
                TEST_USERS["registrar"], {"home_program_id": env.prog_df_id}
            )
        ) == 0, "a shape violation may not create a faculty member"
        assert total_count(
            api.list_course_sections(
                TEST_USERS["registrar"], {"program_id": env.prog_df_id}
            )
        ) == 0, "a shape violation may not create a section"


class TestTypeAndWindowConstraints:
    def test_bad_enums_and_inverted_windows_report_different_codes(self, api, env):
        """PRD §3.4: "A start at or after the end is rejected with
        `ERR_INVALID_WINDOW`, while a minute value outside the permitted range is a
        shape violation reported as `ERR_INVALID_REQUEST`."

        Design: Corner/entities/invalid_enum_and_inverted_windows_rejected_with_their_own_codes
        """
        bad_enum = api.create_faculty_member(
            faculty_payload(
                "Tenure Track",
                "tenure.track@example.edu",
                "TENURED",
                env.prog_df_id,
            ),
            TEST_USERS["registrar"],
        )
        bad_term_window = api.create_term(
            term_payload(
                code="2027SP",
                start_date="2027-05-10",
                end_date="2027-01-11",
                census_date="2027-01-25",
            ),
            TEST_USERS["registrar"],
        )
        empty_block = api.create_course_section(
            section_payload(
                env.prog_df_id,
                env.term_id,
                env.journ_id,
                "JOUR198",
                "Inverted Meeting",
                meeting_days=["FRI"],
                meeting_start_minute=700,
                meeting_end_minute=700,
            ),
            env.dean_df,
        )

        validate_error(bad_enum, ApiErrorId.ERR_INVALID_REQUEST)
        validate_error(bad_term_window, ApiErrorId.ERR_INVALID_WINDOW)
        validate_error(empty_block, ApiErrorId.ERR_INVALID_WINDOW)
        assert total_count(api.list_terms(TEST_USERS["registrar"])) == 1, (
            "only the accepted 2026FA term may exist"
        )
        assert total_count(
            api.list_course_sections(
                TEST_USERS["registrar"], {"program_id": env.prog_df_id}
            )
        ) == 0, "the empty meeting block may not create a section"


class TestBodyForeignKeys:
    def test_body_references_must_resolve_to_their_own_entities(self, api, env):
        """PRD §2.10: "Every foreign-key identifier in the request body resolves →
        otherwise the referenced entity's 404 code, checked in field-declaration
        order."

        Design: Corner/entities/foreign_keys_must_resolve_before_the_write_is_accepted
        """
        dana = make_faculty(
            "Dana Reyes", "dana.reyes@example.edu", "ADJUNCT", env.prog_df_id
        )

        unknown_discipline = api.create_credential_record(
            {
                "faculty_member_id": dana["id"],
                "degree_level": "MASTERS",
                "discipline_id": NON_EXISTENT_ID,
                "conferring_institution": "Nowhere University",
                "is_foreign_institution": False,
                "graduate_credit_hours_in_discipline": 30,
            },
            TEST_USERS["registrar"],
        )
        unknown_term = api.create_course_section(
            section_payload(
                env.prog_df_id,
                NON_EXISTENT_ID,
                env.journ_id,
                "JOUR197",
                "Orphan Section",
                meeting_days=["FRI"],
            ),
            env.dean_df,
        )
        unknown_faculty = api.create_credential_record(
            {
                "faculty_member_id": NON_EXISTENT_ID,
                "degree_level": "MASTERS",
                "discipline_id": env.journ_id,
                "conferring_institution": "Nowhere University",
                "is_foreign_institution": False,
                "graduate_credit_hours_in_discipline": 30,
            },
            TEST_USERS["registrar"],
        )

        validate_error(unknown_discipline, ApiErrorId.ERR_DISCIPLINE_NOT_FOUND)
        validate_error(unknown_term, ApiErrorId.ERR_TERM_NOT_FOUND)
        validate_error(unknown_faculty, ApiErrorId.ERR_FACULTY_NOT_FOUND)
        faculty = read_faculty(dana["id"])
        assert_fields(faculty, dossier_status="INCOMPLETE")
        assert_ordered_codes(faculty["deficiency_codes"], [], "deficiency_codes")
