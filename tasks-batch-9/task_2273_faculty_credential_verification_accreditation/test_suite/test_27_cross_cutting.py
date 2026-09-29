"""Concurrency guards, the version ledger and the substantive-change feature flag."""

from test_helpers import (
    ApiErrorId,
    assert_assignment_verdict,
    assert_fields,
    assert_program_adequacy,
    assert_roster_snapshot,
    assert_version_advanced_by,
    assignment_payload,
    contract_payload,
    issue_findings,
    launch_decision_payload,
    make_assignment,
    make_credentialed_faculty,
    make_generated_roster,
    make_program,
    make_review,
    make_section,
    make_verified_credential,
    move_review,
    read_assignment,
    read_faculty,
    read_program,
    read_section,
    submit_launch_review,
    total_count,
    validate_error,
    validate_success,
    TEST_USERS,
)


def _held_section(env):
    """A section already held by its instructor of record, plus a second candidate."""
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
    incumbent = make_assignment(
        monday["id"],
        morgan["id"],
        env.prog_df_id,
        expected_section_version=monday["version"],
    )
    return {
        "morgan": morgan,
        "dana": dana,
        "section": monday,
        "stale_version": monday["version"],
        "incumbent": incumbent,
    }


class TestStaleSectionVersion:
    def test_the_replayed_section_version_is_refused_then_the_refreshed_one_lands(
        self, api, env
    ):
        """PRD §2.7: "If that value does not equal the section's current `version`, the
        create is rejected with `ERR_STALE_SECTION_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/stale_section_version_blocks_assignment_creation_then_refresh_succeeds
        """
        state = _held_section(env)
        body = assignment_payload(
            state["section"]["id"],
            state["dana"]["id"],
            state["stale_version"],
            assignment_role="CO_INSTRUCTOR",
        )

        validate_error(
            api.create_course_assignment(body, env.dean_df),
            ApiErrorId.ERR_STALE_SECTION_VERSION,
        )

        assert (
            total_count(
                api.list_course_assignments(
                    TEST_USERS["admin"],
                    {
                        "faculty_member_id": state["dana"]["id"],
                        "limit": 10,
                        "offset": 0,
                    },
                )
            )
            == 0
        ), "the refused create must not have attached Dana to the section"
        assert read_faculty(state["dana"]["id"])["assigned_credit_hours"] == 0
        refreshed = read_section(state["section"]["id"])
        assert refreshed["version"] == state["stale_version"] + 1, (
            "only the incumbent's assignment advanced the section; the refusal did not"
        )

        accepted = validate_success(
            api.create_course_assignment(
                assignment_payload(
                    state["section"]["id"],
                    state["dana"]["id"],
                    refreshed["version"],
                    assignment_role="CO_INSTRUCTOR",
                ),
                env.dean_df,
            ),
            201,
        )

        assert_assignment_verdict(
            accepted,
            status="EXCEPTION_FLAGGED",
            qualification_basis="NONE",
            exception_code="DISCIPLINE_MISALIGNED",
            alignment_score=0.6500,
        )
        final_section = read_section(state["section"]["id"])
        assert final_section["version"] == state["stale_version"] + 2, (
            "one refused and two accepted assignment writes total two increments"
        )
        assert_fields(final_section, instructor_of_record_id=state["morgan"]["id"])
        assert_fields(
            read_assignment(state["incumbent"]["id"]),
            status="VERIFIED_QUALIFIED",
            superseded_by_assignment_id=None,
        )
        assert read_faculty(state["dana"]["id"])["assigned_credit_hours"] == 3


def _moved_dossier(env):
    """One faculty version captured before a second credential is verified."""
    morgan = make_credentialed_faculty(
        "Morgan Ellis",
        "morgan.ellis@example.edu",
        "FULL_TIME",
        env.prog_cw_id,
        "MASTERS",
        env.journ_id,
        "Lakeside University",
        graduate_credit_hours_in_discipline=36,
    )
    stale_version = morgan["faculty"]["version"]
    doctorate = make_verified_credential(
        morgan["faculty"]["id"],
        "DOCTORATE",
        env.journ_id,
        "Lakeside University",
        graduate_credit_hours_in_discipline=54,
    )
    return {
        "faculty_id": morgan["faculty"]["id"],
        "masters": morgan["record"],
        "doctorate": doctorate,
        "stale_version": stale_version,
    }


class TestStaleFacultyVersion:
    def test_a_verified_doctorate_invalidates_the_deans_captured_faculty_version(
        self, api, env
    ):
        """PRD §2.7: "If that value does not equal the faculty member's current
        `version`, the issuance is rejected with `ERR_STALE_FACULTY_VERSION` (HTTP 412).
        A faculty member's `version` advances on every dossier movement — verification,
        repudiation, evaluation completion, contract supersession — so a stale value
        means the credentialing evidence the dean relied upon is no longer the evidence
        of record."

        Design: Corner/cross_cutting_complexity_layers/stale_faculty_version_blocks_contract_issuance_after_dossier_movement
        """
        state = _moved_dossier(env)

        validate_error(
            api.create_contract(
                contract_payload(
                    state["faculty_id"],
                    env.term_id,
                    "FULL_TIME",
                    9,
                    state["stale_version"],
                ),
                env.dean_cw,
            ),
            ApiErrorId.ERR_STALE_FACULTY_VERSION,
        )

        assert (
            total_count(
                api.list_contracts(
                    TEST_USERS["admin"],
                    {
                        "faculty_member_id": state["faculty_id"],
                        "term_id": env.term_id,
                        "limit": 10,
                        "offset": 0,
                    },
                )
            )
            == 0
        ), "the refused issuance must not have created a contract"
        refreshed = read_faculty(state["faculty_id"])
        assert_fields(refreshed, appointment_status="CREDENTIALED_ELIGIBLE")
        assert refreshed["version"] > state["stale_version"], (
            "verifying the doctorate advanced the faculty version"
        )

        contract = validate_success(
            api.create_contract(
                contract_payload(
                    state["faculty_id"],
                    env.term_id,
                    "FULL_TIME",
                    9,
                    refreshed["version"],
                ),
                env.dean_cw,
            ),
            201,
        )

        assert_fields(
            contract,
            status="ISSUED",
            dossier_snapshot_status="VERIFIED",
            credential_snapshot_version=refreshed["version"],
            contract_credit_hours=9,
            term_id=env.term_id,
        )
        assert_fields(
            validate_success(
                api.get_credential_record(
                    state["doctorate"]["id"], TEST_USERS["admin"]
                )
            ),
            verification_status="VERIFIED",
        )
        assert_fields(
            validate_success(
                api.get_credential_record(state["masters"]["id"], TEST_USERS["admin"])
            ),
            verification_status="VERIFIED",
            version=state["masters"]["version"],
        )
        assert_fields(
            read_faculty(state["faculty_id"]), highest_verified_degree_level="DOCTORATE"
        )


def _three_dossiers(env):
    """Two instructors bound for one section and a third who is never touched."""
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
    return {"morgan": morgan, "alex": alex, "dana": dana, "section": monday}


class TestVersionLedger:
    def test_two_accepted_writes_move_the_parent_twice_and_the_refusal_not_at_all(
        self, api, env
    ):
        """PRD §2.7: "Both writes also advance their parent: creating an assignment
        increments the `CourseSection.version`, and issuing a contract increments the
        `FacultyMember.version`. A client that wants to issue two contracts, or attach
        two assignments to one section, must therefore re-read the parent between the
        two calls."

        Design: Corner/cross_cutting_complexity_layers/every_accepted_write_advances_its_own_version_by_exactly_one
        """
        state = _three_dossiers(env)
        baseline = state["section"]["version"]

        first = validate_success(
            api.create_course_assignment(
                assignment_payload(
                    state["section"]["id"], state["morgan"]["id"], baseline
                ),
                env.dean_df,
            ),
            201,
        )
        validate_error(
            api.create_course_assignment(
                assignment_payload(
                    state["section"]["id"],
                    state["alex"]["id"],
                    baseline,
                    assignment_role="CO_INSTRUCTOR",
                ),
                env.dean_df,
            ),
            ApiErrorId.ERR_STALE_SECTION_VERSION,
        )
        mid = read_section(state["section"]["id"])["version"]
        second = validate_success(
            api.create_course_assignment(
                assignment_payload(
                    state["section"]["id"],
                    state["alex"]["id"],
                    mid,
                    assignment_role="CO_INSTRUCTOR",
                ),
                env.dean_df,
            ),
            201,
        )
        end = read_section(state["section"]["id"])["version"]

        assert mid == baseline + 1, "one accepted write, one increment"
        assert end == baseline + 2, (
            "two accepted writes and one refusal must total two increments"
        )
        assert read_section(state["section"]["id"])["version"] == end, (
            "reading the section must not advance it"
        )
        assert second["version"] == 1, "a freshly created assignment starts at version 1"

        morgan_after = read_faculty(state["morgan"]["id"])
        alex_after = read_faculty(state["alex"]["id"])
        dana_after = read_faculty(state["dana"]["id"])
        assert_fields(morgan_after, assigned_credit_hours=3)
        assert_version_advanced_by(morgan_after, state["morgan"]["version"], 1)
        assert_fields(alex_after, assigned_credit_hours=3)
        assert_version_advanced_by(alex_after, state["alex"]["version"], 1)
        assert_fields(
            dana_after,
            assigned_credit_hours=0,
            version=state["dana"]["version"],
        )
        assert_fields(read_assignment(first["id"]), status="VERIFIED_QUALIFIED")


def _two_adequate_programs(env):
    """Identical adequacy evidence either side of the substantive-change flag."""
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
    make_assignment(monday["id"], morgan["id"], env.prog_df_id)
    plain_roster = make_generated_roster(env.prog_df_id, env.term_id)

    flagged_program = make_program(
        "MS Journalism (New Program)",
        env.journ_id,
        degree_level="MASTERS",
        qualification_policy="DEGREE_FIELD",
        adequacy_basis="HEADCOUNT",
        min_terminal_ratio=0.60,
        is_substantive_change=True,
        credential_budget_cents=500000,
    )
    friday = make_section(
        flagged_program["id"],
        env.term_id,
        env.journ_id,
        "JOUR501",
        "Graduate Reporting",
        credit_hours=3,
        course_level="UPPER_DIVISION",
        building_code="HALL-D",
        meeting_days=["FRI"],
        meeting_start_minute=540,
        meeting_end_minute=620,
    )
    make_assignment(friday["id"], morgan["id"], flagged_program["id"])
    flagged_roster = make_generated_roster(flagged_program["id"], env.term_id)

    return {
        "flagged_program_id": flagged_program["id"],
        "plain_roster": plain_roster,
        "flagged_roster": flagged_roster,
        "plain_review": submit_launch_review(env.prog_df_id, env.term_id),
        "flagged_review": submit_launch_review(flagged_program["id"], env.term_id),
    }


class TestSubstantiveChangeFlag:
    def test_one_boolean_adds_an_accreditor_precondition_to_an_otherwise_equal_case(
        self, api, env
    ):
        """PRD §3.1: "Approval moves `ADEQUACY_REVIEW → APPROVED_TO_LAUNCH` and requires
        both that `adequacy_status` is `ADEQUATE` and that `unqualified_assignment_count`
        is 0 — otherwise `ERR_PROGRAM_ADEQUACY_INSUFFICIENT` — and, when
        `is_substantive_change` is true, additionally requires an accreditor review of
        type `SUBSTANTIVE_CHANGE` already in `CLOSED_ACCEPTED` for that program, absent
        which the request is rejected with `ERR_INVALID_STATE`."

        Design: Corner/cross_cutting_complexity_layers/substantive_change_flag_adds_a_review_precondition_to_launch_approval
        """
        state = _two_adequate_programs(env)
        for program in (state["plain_review"], state["flagged_review"]):
            assert_program_adequacy(
                program,
                launch_status="ADEQUACY_REVIEW",
                adequacy_status="ADEQUATE",
                unqualified_assignment_count=0,
                adequacy_ratio=1.0000,
            )
        assert_roster_snapshot(
            state["flagged_roster"],
            certification_readiness="READY",
            terminal_qualified_headcount=1,
        )

        plain_decision = validate_success(
            api.decide_launch(
                env.prog_df_id,
                launch_decision_payload(
                    "APPROVE", rationale="Not a substantive change"
                ),
                TEST_USERS["liaison"],
            )
        )
        validate_error(
            api.decide_launch(
                state["flagged_program_id"],
                launch_decision_payload(
                    "APPROVE",
                    rationale="Requesting approval before the accreditor closes",
                ),
                TEST_USERS["liaison"],
            ),
            ApiErrorId.ERR_INVALID_STATE,
        )
        assert_fields(plain_decision, launch_status="APPROVED_TO_LAUNCH")
        assert_fields(
            read_program(state["flagged_program_id"]), launch_status="ADEQUACY_REVIEW"
        )

        review = make_review(
            state["flagged_program_id"],
            "SUBSTANTIVE_CHANGE",
            "2026-07-28",
            "2026-08-03",
        )
        move_review(review["id"], "IN_PROGRESS")
        issued = issue_findings(
            review["id"], 0, narrative="No findings on the substantive change"
        )
        closed = move_review(
            review["id"], "CLOSED_ACCEPTED", note="Substantive change accepted"
        )
        flagged_decision = validate_success(
            api.decide_launch(
                state["flagged_program_id"],
                launch_decision_payload(
                    "APPROVE",
                    rationale="Substantive change accepted by the accreditor",
                ),
                TEST_USERS["liaison"],
            )
        )

        assert_fields(issued, status="FINDINGS_ISSUED", finding_count=0)
        assert_fields(closed, status="CLOSED_ACCEPTED")
        assert_fields(
            flagged_decision,
            launch_status="APPROVED_TO_LAUNCH",
            is_substantive_change=True,
        )
