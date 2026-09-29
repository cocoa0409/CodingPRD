"""Who may act: role exclusivity, ownership, authentication and separation of duties."""

from test_helpers import (
    ApiErrorId,
    anonymous_headers,
    assert_assignment_verdict,
    assert_fields,
    assert_ordered_codes,
    assert_roster_snapshot,
    assert_score,
    assert_total_count,
    assert_version_advanced_by,
    discipline_payload,
    faculty_payload,
    ids_of,
    justification_decision_payload,
    make_assignment,
    make_contract,
    make_credentialed_faculty,
    make_generated_roster,
    make_instructor_headers,
    make_justification,
    make_roster,
    make_section,
    read_assignment,
    read_faculty,
    read_program,
    read_roster,
    read_section,
    review_justification,
    review_payload,
    section_payload,
    submit_justification,
    total_count,
    validate_error,
    validate_paginated,
    validate_success,
    verification_payload,
    Role,
    TEST_USERS,
)


PERFECT_CODES = ["SPJ-CERT", "AP-STYLE", "INVEST-01", "DIGITAL-02"]


def _one_of_everything(env):
    """A verified instructor, a section that holds him and a draft roster."""
    built = make_credentialed_faculty(
        "Morgan Ellis",
        "morgan.ellis@example.edu",
        "FULL_TIME",
        env.prog_cw_id,
        "MASTERS",
        env.journ_id,
        "Lakeside University",
        graduate_credit_hours_in_discipline=36,
    )
    monday = make_section(
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
    roster = make_roster(env.prog_df_id, env.term_id)
    return {
        "faculty": built["faculty"],
        "record": built["record"],
        "section": monday,
        "roster": roster,
    }


class TestRoleExclusivity:
    def test_each_role_is_refused_the_operations_reserved_for_the_others(
        self, api, env
    ):
        """PRD §2.1: "A request whose `X-User-Role` header is missing, or whose value
        is not among the roles authorized for the endpoint being called, is rejected
        with `ERR_FORBIDDEN_ROLE` (HTTP 403) — a missing role header is treated as an
        unauthorized role, never as a malformed request."

        Design: Corner/rbac/each_role_is_locked_out_of_the_other_roles_exclusive_operations
        """
        state = _one_of_everything(env)
        program_version = read_program(env.prog_df_id)["version"]

        validate_error(
            api.create_discipline(
                discipline_payload("09.09", "Sports Journalism"), env.dean_df
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
        )
        validate_error(
            api.create_faculty_member(
                faculty_payload(
                    "Unauthorized Hire",
                    "unauth@example.edu",
                    "ADJUNCT",
                    env.prog_df_id,
                ),
                TEST_USERS["analyst"],
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
        )
        validate_error(
            api.decide_verification(
                state["record"]["id"],
                verification_payload("VERIFY"),
                TEST_USERS["registrar"],
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
        )
        validate_error(
            api.create_course_section(
                section_payload(
                    env.prog_df_id,
                    env.term_id,
                    env.journ_id,
                    "JOUR199",
                    "Unauthorized Section",
                    credit_hours=3,
                    building_code="HALL-Z",
                    meeting_days=["FRI"],
                    meeting_start_minute=540,
                    meeting_end_minute=620,
                ),
                TEST_USERS["liaison"],
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
        )
        validate_error(
            api.generate_roster(state["roster"]["id"], {}, TEST_USERS["reviewer"]),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
        )
        validate_error(
            api.create_review(
                review_payload(
                    env.prog_df_id, "FOCUSED_FOLLOWUP", "2026-08-05", "2026-08-09"
                ),
                TEST_USERS["liaison"],
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
        )

        assert_total_count(
            validate_paginated(
                api.list_disciplines(TEST_USERS["admin"], {"limit": 20, "offset": 0})
            )[1],
            3,
            "the discipline taxonomy after the refused create",
        )
        assert_total_count(
            validate_paginated(
                api.list_faculty_members(
                    TEST_USERS["registrar"], {"limit": 20, "offset": 0}
                )
            )[1],
            1,
            "the faculty roll after the refused create",
        )
        record = validate_success(
            api.get_credential_record(state["record"]["id"], TEST_USERS["admin"])
        )
        assert_fields(
            record, verification_status="VERIFIED", verified_by_user_id="analyst-01"
        )
        assert record["version"] == state["record"]["version"], (
            "the refused verification must not touch the credential record"
        )

        sections, section_meta = validate_paginated(
            api.list_course_sections(TEST_USERS["admin"], {"limit": 20, "offset": 0})
        )
        assert_total_count(section_meta, 1, "the section list after the refused create")
        assert ids_of(sections) == [state["section"]["id"]]
        assert [row["course_code"] for row in sections] == ["JOUR101"], (
            "JOUR199 must never have been created"
        )

        assert_roster_snapshot(
            read_roster(state["roster"]["id"]),
            status="DRAFT",
            generation_epoch=0,
            total_assignment_count=0,
            version=state["roster"]["version"],
        )
        assert (
            total_count(
                api.list_reviews(
                    TEST_USERS["reviewer"],
                    {"program_id": env.prog_df_id, "limit": 10, "offset": 0},
                )
            )
            == 0
        ), "the liaison's review scheduling attempt must have written nothing"
        assert_fields(read_program(env.prog_df_id), version=program_version)
        assert_fields(read_section(state["section"]["id"]), version=state["section"]["version"])
        assert_fields(
            read_faculty(state["faculty"]["id"]), version=state["faculty"]["version"]
        )


CROSS_PROGRAM_SECTION = dict(
    course_code="JOUR210",
    title="Cross-Program Section",
    course_level="UPPER_DIVISION",
    credit_hours=3,
    building_code="HALL-B",
    meeting_days=["MON"],
    meeting_start_minute=660,
    meeting_end_minute=740,
)


def _two_owners(env):
    """One faculty member per program, and a contract owned by one of them."""
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
    contract = make_contract(
        morgan["id"], env.term_id, "FULL_TIME", 9, env.prog_cw_id
    )
    return {"morgan": morgan, "dana": dana, "contract": contract}


class TestResourceOwnership:
    def test_an_entity_backed_role_cannot_reach_another_owners_resource(self, api, env):
        """PRD §2.1: "When `X-User-Role` is `ProgramDean`, `X-User-ID` is the `id` of
        the acting `Program`; ownership checks on any resource that references a
        `Program` compare the resource's program foreign-key field to `X-User-ID`."

        Design: Corner/rbac/entity_backed_roles_cannot_reach_across_to_another_owners_resource
        """
        state = _two_owners(env)
        body = section_payload(
            env.prog_df_id, env.term_id, env.journ_id, **CROSS_PROGRAM_SECTION
        )
        assert (
            total_count(
                api.list_course_sections(
                    TEST_USERS["admin"], {"limit": 10, "offset": 0}
                )
            )
            == 0
        ), "no section exists before the ownership probes"

        validate_error(
            api.create_course_section(body, env.dean_cw),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        )
        validate_error(
            api.get_contract(
                state["contract"]["id"], make_instructor_headers(state["dana"]["id"])
            ),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        )
        validate_error(
            api.get_faculty_member(
                state["morgan"]["id"], make_instructor_headers(state["dana"]["id"])
            ),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        )

        owned_section = validate_success(
            api.create_course_section(
                section_payload(
                    env.prog_df_id, env.term_id, env.journ_id, **CROSS_PROGRAM_SECTION
                ),
                env.dean_df,
            ),
            201,
        )
        own_contract = validate_success(
            api.get_contract(
                state["contract"]["id"], make_instructor_headers(state["morgan"]["id"])
            )
        )

        assert_fields(
            owned_section,
            course_code="JOUR210",
            program_id=env.prog_df_id,
            version=1,
        )
        assert_fields(own_contract, status="ISSUED", faculty_member_id=state["morgan"]["id"])
        sections, meta = validate_paginated(
            api.list_course_sections(TEST_USERS["admin"], {"limit": 10, "offset": 0})
        )
        assert_total_count(meta, 1, "the section list after one refusal and one success")
        assert ids_of(sections) == [owned_section["id"]]
        assert_fields(
            validate_success(
                api.get_faculty_member(state["morgan"]["id"], TEST_USERS["registrar"])
            ),
            full_name="Morgan Ellis",
        )


class TestAuthenticationOutranksEverything:
    def test_an_empty_user_id_answers_401_before_role_or_ownership(self, api, env):
        """PRD §2.1: "A request whose `X-User-ID` header is missing or empty is
        rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any routing, existence or
        shape checking happens."

        Design: Corner/rbac/missing_user_identity_outranks_role_and_ownership_checks
        """
        program_version = read_program(env.prog_df_id)["version"]

        validate_error(
            api.create_course_section(
                section_payload(
                    env.prog_df_id,
                    env.term_id,
                    env.journ_id,
                    "JOUR220",
                    "Anonymous Section",
                    credit_hours=3,
                    building_code="HALL-B",
                    meeting_days=["FRI"],
                    meeting_start_minute=540,
                    meeting_end_minute=620,
                ),
                anonymous_headers(Role.ACCREDITATION_LIAISON.value),
            ),
            ApiErrorId.ERR_UNAUTHENTICATED,
        )
        validate_error(
            api.list_faculty_members(
                anonymous_headers(Role.REGISTRAR_OFFICER.value),
                {"limit": 10, "offset": 0},
            ),
            ApiErrorId.ERR_UNAUTHENTICATED,
        )

        assert (
            total_count(
                api.list_course_sections(
                    TEST_USERS["admin"], {"limit": 10, "offset": 0}
                )
            )
            == 0
        ), "the anonymous section-creation attempt must have written nothing"
        assert_fields(read_program(env.prog_df_id), version=program_version)


def _decidable_justification(env):
    """A blocked roster covering one flagged assignment with a perfect case for it."""
    alex = make_credentialed_faculty(
        "Alex Stone",
        "alex.stone@example.edu",
        "ADJUNCT",
        env.prog_cw_id,
        "MASTERS",
        env.pr_id,
        "Harbor College",
        graduate_credit_hours_in_discipline=30,
    )["faculty"]
    tuesday = make_section(
        env.prog_df_id,
        env.term_id,
        env.journ_id,
        "JOUR104",
        "Data Journalism",
        credit_hours=3,
        meeting_days=["TUE"],
        meeting_start_minute=540,
        meeting_end_minute=620,
    )
    assignment = make_assignment(tuesday["id"], alex["id"], env.prog_df_id)
    roster = make_generated_roster(env.prog_df_id, env.term_id)
    justification = make_justification(
        assignment["id"],
        env.prog_df_id,
        8,
        "BOARD_CERTIFIED",
        PERFECT_CODES,
        True,
        narrative="Eight years running a wire desk",
    )
    submit_justification(justification["id"], env.prog_df_id)
    return {
        "assignment": assignment,
        "roster": roster,
        "justification": review_justification(
            justification["id"], TEST_USERS["analyst"]
        ),
    }


class TestSegregationOfDuties:
    def test_the_deciding_user_can_neither_be_the_verifier_nor_the_certifier(
        self, api, env
    ):
        """PRD §3.6: "And segregation of duties applies: the acting `X-User-ID` must not
        appear as `decided_by_user_id` on any tested-experience justification whose
        backed assignment is included in this roster, or the request fails with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/one_user_cannot_both_decide_a_justification_and_certify_the_roster
        """
        state = _decidable_justification(env)
        under_review = state["justification"]
        assert_score(
            under_review["tested_experience_score"], 1.0000, "tested_experience_score"
        )
        assert_roster_snapshot(
            state["roster"],
            status="GENERATED",
            flagged_exception_count=1,
            certification_readiness="BLOCKED",
            blocking_reason_codes=["EXCEPTIONS_OUTSTANDING", "ADEQUACY_BELOW_MINIMUM"],
        )

        validate_error(
            api.decide_justification(
                under_review["id"],
                justification_decision_payload(
                    "APPROVE",
                    decision_rationale="Self-review attempt by the verifying analyst",
                ),
                TEST_USERS["analyst"],
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        )
        approved = validate_success(
            api.decide_justification(
                under_review["id"],
                justification_decision_payload(
                    "APPROVE",
                    decision_rationale="Independent analyst approves the tested experience",
                ),
                TEST_USERS["shared_analyst"],
            )
        )
        validate_error(
            api.certify_roster(
                state["roster"]["id"],
                {"attestation_note": "Certifying the roster I just decided on"},
                TEST_USERS["shared_liaison"],
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        )
        validate_error(
            api.certify_roster(
                state["roster"]["id"],
                {"attestation_note": "Independent liaison attempt"},
                TEST_USERS["liaison_2"],
            ),
            ApiErrorId.ERR_ROSTER_NOT_READY,
        )

        assert_fields(
            approved, status="APPROVED", decided_by_user_id="shared-user-1"
        )
        assert_version_advanced_by(approved, under_review["version"], 1)
        assert_assignment_verdict(
            read_assignment(state["assignment"]["id"]),
            status="VERIFIED_QUALIFIED",
            qualification_basis="TESTED_EXPERIENCE",
            exception_code=None,
        )
        final_roster = read_roster(state["roster"]["id"])
        assert_roster_snapshot(
            final_roster,
            status="GENERATED",
            flagged_exception_count=0,
            terminal_qualified_headcount=0,
            certification_readiness="BLOCKED",
            blocking_reason_codes=["ADEQUACY_BELOW_MINIMUM"],
        )
        assert_fields(final_roster, certified_by_user_id=None, certified_at=None)
        assert_ordered_codes(
            final_roster["blocking_reason_codes"],
            ["ADEQUACY_BELOW_MINIMUM"],
            "blocking_reason_codes after the approval cleared the exception",
        )
