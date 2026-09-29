"""Guard rails: uniqueness keys, cycles, clocks, cross-entity preconditions."""

from test_helpers import (
    ApiErrorId,
    assert_assignment_verdict,
    assert_clock_instant,
    assert_fields,
    assert_hours,
    assert_ordered_codes,
    assert_roster_snapshot,
    assert_version_advanced_by,
    assignment_payload,
    contract_payload,
    credential_record_payload,
    discipline_payload,
    evaluation_payload,
    faculty_payload,
    file_credential,
    issue_findings,
    make_assignment,
    make_credentialed_faculty,
    make_discipline,
    make_faculty,
    make_generated_roster,
    make_roster,
    make_section,
    make_started_review,
    move_term,
    pd_record_payload,
    read_assignment,
    read_faculty,
    read_roster,
    read_section,
    response_payload,
    roster_payload,
    separate_faculty,
    set_clock,
    term_payload,
    term_status_payload,
    total_count,
    validate_error,
    validate_success,
    CLOCK_DEFAULT,
    TEST_USERS,
)


def _uniqueness_state(env):
    """One instructor, two sections, one assignment and one DRAFT roster."""
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
    make_assignment(monday["id"], morgan["id"], env.prog_df_id)
    roster = make_roster(env.prog_df_id, env.term_id)
    return {
        "morgan_id": morgan["id"],
        "monday": monday,
        "tuesday": tuesday,
        "roster": roster,
    }


class TestUniquenessKeys:
    def test_each_uniqueness_rule_reports_its_own_duplicate_code(self, api, env):
        """PRD §2.10: "No existing assignment shares the same section and faculty
        member with a status other than `SUPERSEDED` or `WITHDRAWN` → otherwise
        `ERR_DUPLICATE_ASSIGNMENT` (409). Applies to assignment creation."

        Design: Corner/validations/every_uniqueness_rule_rejects_its_own_duplicate_key
        """
        state = _uniqueness_state(env)
        monday_version = read_section(state["monday"]["id"])["version"]

        validate_error(
            api.create_discipline(
                discipline_payload(
                    "09.04", "Journalism Studies", min_graduate_credit_hours=18
                ),
                TEST_USERS["admin"],
            ),
            ApiErrorId.ERR_DUPLICATE_DISCIPLINE_CODE,
        )
        validate_error(
            api.create_term(
                term_payload(
                    "2026FA",
                    start_date="2027-01-10",
                    end_date="2027-05-10",
                    census_date="2027-01-25",
                ),
                TEST_USERS["registrar"],
            ),
            ApiErrorId.ERR_DUPLICATE_TERM_CODE,
        )
        validate_error(
            api.create_faculty_member(
                faculty_payload(
                    "Morgan Ellis II",
                    "morgan.ellis@example.edu",
                    "ADJUNCT",
                    env.prog_df_id,
                ),
                TEST_USERS["registrar"],
            ),
            ApiErrorId.ERR_DUPLICATE_FACULTY_EMAIL,
        )
        validate_error(
            api.create_course_assignment(
                assignment_payload(
                    state["monday"]["id"],
                    state["morgan_id"],
                    monday_version,
                    assignment_role="CO_INSTRUCTOR",
                ),
                env.dean_df,
            ),
            ApiErrorId.ERR_DUPLICATE_ASSIGNMENT,
        )
        accepted = validate_success(
            api.create_course_assignment(
                assignment_payload(
                    state["tuesday"]["id"],
                    state["morgan_id"],
                    state["tuesday"]["version"],
                ),
                env.dean_df,
            ),
            201,
        )
        validate_error(
            api.create_roster(
                roster_payload(env.prog_df_id, env.term_id), TEST_USERS["liaison"]
            ),
            ApiErrorId.ERR_DUPLICATE_ROSTER,
        )

        assert read_section(state["monday"]["id"])["version"] == monday_version, (
            "the rejected repeat pair must not advance the section it addressed"
        )
        assert_version_advanced_by(
            read_section(state["tuesday"]["id"]), state["tuesday"]["version"], 1
        )
        assert_fields(accepted, assignment_role="INSTRUCTOR_OF_RECORD")
        assert_fields(read_roster(state["roster"]["id"]), status="DRAFT")
        assert total_count(api.list_terms(TEST_USERS["registrar"])) == 1
        assert total_count(api.list_rosters(TEST_USERS["liaison"])) == 1
        assert total_count(api.list_faculty_members(TEST_USERS["registrar"])) == 1


class TestDisciplineCycles:
    def test_self_and_ancestor_targets_are_both_rejected(self, api):
        """PRD §3.1: "Neither creation nor update may point a node at itself or close
        a loop in the forest; either attempt yields `ERR_DISCIPLINE_CYCLE`."

        Design: Corner/validations/discipline_reparent_rejects_self_and_ancestor_targets
        """
        set_clock()
        communication = make_discipline("09.01", "Communication")
        journalism = make_discipline(
            "09.04",
            "Journalism",
            parent_discipline_id=communication["id"],
            min_graduate_credit_hours=18,
        )
        broadcast = make_discipline(
            "09.05",
            "Broadcast Journalism",
            parent_discipline_id=journalism["id"],
            min_graduate_credit_hours=18,
        )
        public_relations = make_discipline(
            "09.07", "Public Relations", min_graduate_credit_hours=18
        )

        validate_error(
            api.update_discipline(
                journalism["id"],
                {"parent_discipline_id": journalism["id"]},
                TEST_USERS["admin"],
            ),
            ApiErrorId.ERR_DISCIPLINE_CYCLE,
        )
        validate_error(
            api.update_discipline(
                communication["id"],
                {"parent_discipline_id": broadcast["id"]},
                TEST_USERS["admin"],
            ),
            ApiErrorId.ERR_DISCIPLINE_CYCLE,
        )
        reparented = validate_success(
            api.update_discipline(
                public_relations["id"],
                {"parent_discipline_id": communication["id"]},
                TEST_USERS["admin"],
            )
        )

        assert_fields(reparented, parent_discipline_id=communication["id"])
        assert_version_advanced_by(reparented, public_relations["version"], 1)
        assert_fields(
            validate_success(
                api.get_discipline(communication["id"], TEST_USERS["admin"])
            ),
            parent_discipline_id=None,
            version=communication["version"],
        )
        assert_fields(
            validate_success(api.get_discipline(journalism["id"], TEST_USERS["admin"])),
            parent_discipline_id=communication["id"],
            version=journalism["version"],
        )


def _temporal_state(env):
    """A contractable adjunct, a flagged roster and a review awaiting a response."""
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
    make_assignment(tuesday["id"], alex["id"], env.prog_df_id)
    make_generated_roster(env.prog_df_id, env.term_id)
    review = make_started_review(env.prog_df_id, "COMPREHENSIVE")
    remediating = issue_findings(
        review["id"], 1, narrative="One unqualified instructor of record"
    )
    return {"dana_id": dana["id"], "review": remediating}


class TestTemporalGuards:
    def test_three_clock_comparisons_answer_against_three_reference_dates(
        self, api, env
    ):
        """PRD §2.10: "The clock date is strictly before the contracted term's
        `start_date` → otherwise `ERR_CONTRACT_WINDOW_CLOSED` (422). Applies to
        contract issuance. Reported only once rung 16 is satisfied." And: "`activity_date`
        is on or before the clock date → otherwise `ERR_PD_DATE_IN_FUTURE` (422).
        Applies to professional-development logging."

        Design: Corner/validations/temporal_guards_reject_future_pd_closed_contract_window_and_late_response
        """
        state = _temporal_state(env)
        dana_version = read_faculty(state["dana_id"])["version"]
        assert state["review"]["response_due_date"] is not None, (
            "findings must publish the date the response is measured against"
        )

        validate_error(
            api.create_pd_record(
                pd_record_payload(
                    state["dana_id"], env.pr_id, "CONFERENCE", 4.0, "2026-08-02"
                ),
                TEST_USERS["registrar"],
            ),
            ApiErrorId.ERR_PD_DATE_IN_FUTURE,
        )

        set_clock("2026-09-15T00:00:00Z")
        validate_error(
            api.create_contract(
                contract_payload(
                    state["dana_id"], env.term_id, "ADJUNCT", 6, dana_version
                ),
                env.dean_df,
            ),
            ApiErrorId.ERR_CONTRACT_WINDOW_CLOSED,
        )

        set_clock("2027-01-05T00:00:00Z")
        validate_error(
            api.submit_response(
                state["review"]["id"],
                response_payload("Remediation plan attached."),
                TEST_USERS["liaison"],
            ),
            ApiErrorId.ERR_RESPONSE_WINDOW_CLOSED,
        )

        assert total_count(api.list_contracts(TEST_USERS["registrar"])) == 0
        assert total_count(api.list_pd_records(TEST_USERS["registrar"])) == 0
        dana = read_faculty(state["dana_id"])
        assert_fields(
            dana, appointment_status="CREDENTIALED_ELIGIBLE", version=dana_version
        )
        assert_hours(dana["pd_hours_current_cycle"], 0.0, "pd_hours_current_cycle")
        assert_fields(
            validate_success(
                api.get_review(state["review"]["id"], TEST_USERS["reviewer"])
            ),
            status="REMEDIATION_REQUIRED",
            response_round=0,
        )


class TestCrossEntityPreconditions:
    def test_the_dossier_the_foreign_flag_and_separation_report_distinct_codes(
        self, api, env
    ):
        """PRD §3.7: "Then `dossier_status` must be `VERIFIED`, or the issuance fails
        with `ERR_DOSSIER_NOT_VERIFIED` — this is the gate that stops adjunct and
        clinical faculty from being hired ahead of their credentialing, and it applies
        identically to every employment class."

        Design: Corner/validations/dossier_and_foreign_credential_preconditions_block_downstream_writes
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
        sam = make_faculty(
            "Sam Okafor", "sam.okafor@example.edu", "FULL_TIME", env.prog_cw_id
        )
        sam_record = file_credential(
            sam["id"],
            "MASTERS",
            env.journ_id,
            "Riverbend University",
            graduate_credit_hours_in_discipline=20,
        )
        dana_version = dana["faculty"]["version"]

        validate_error(
            api.create_contract(
                contract_payload(
                    sam["id"],
                    env.term_id,
                    "FULL_TIME",
                    12,
                    read_faculty(sam["id"])["version"],
                ),
                env.dean_cw,
            ),
            ApiErrorId.ERR_DOSSIER_NOT_VERIFIED,
        )
        validate_error(
            api.create_credential_evaluation(
                evaluation_payload(
                    dana["record"]["id"],
                    env.prog_df_id,
                    evaluator_agency="WES",
                    page_count=6,
                    service_level="STANDARD",
                ),
                TEST_USERS["analyst"],
            ),
            ApiErrorId.ERR_NOT_FOREIGN_CREDENTIAL,
        )
        separate_faculty(sam["id"], reason="Resigned before term start")
        validate_error(
            api.create_credential_record(
                credential_record_payload(
                    sam["id"],
                    "DOCTORATE",
                    env.journ_id,
                    "Riverbend University",
                    graduate_credit_hours_in_discipline=40,
                ),
                TEST_USERS["registrar"],
            ),
            ApiErrorId.ERR_FACULTY_SEPARATED,
        )

        assert_fields(read_faculty(sam["id"]), appointment_status="SEPARATED")
        assert_fields(
            validate_success(
                api.get_credential_record(sam_record["id"], TEST_USERS["registrar"])
            ),
            verification_status="PENDING",
            transcript_status="NOT_REQUESTED",
        )
        assert total_count(api.list_credential_evaluations(TEST_USERS["analyst"])) == 0
        assert total_count(api.list_contracts(TEST_USERS["registrar"])) == 0
        assert_fields(read_faculty(dana["faculty"]["id"]), version=dana_version)


def _loaded_adjunct(env):
    """An adjunct holding exactly nine credit hours, plus one spare 1-credit seat."""
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
    three_credit = [
        make_section(
            env.prog_df_id,
            env.term_id,
            env.journ_id,
            course_code,
            title,
            credit_hours=3,
            meeting_days=[day],
            meeting_start_minute=540,
            meeting_end_minute=620,
        )
        for course_code, title, day in (
            ("JOUR101", "News Writing", "MON"),
            ("JOUR104", "Data Journalism", "TUE"),
            ("JOUR105", "Feature Writing", "WED"),
        )
    ]
    one_credit = make_section(
        env.prog_df_id,
        env.term_id,
        env.journ_id,
        "JOUR106",
        "Newsroom Practicum",
        credit_hours=1,
        meeting_days=["THU"],
        meeting_start_minute=540,
        meeting_end_minute=600,
    )
    held = [
        make_assignment(section["id"], alex["id"], env.prog_df_id)
        for section in three_credit
    ]
    return {
        "alex_id": alex["id"],
        "morgan_id": morgan["id"],
        "held": held,
        "one_credit": one_credit,
    }


class TestPerTermLoadCeiling:
    def test_the_ceiling_is_checked_against_the_running_term_total(self, api, env):
        """PRD §3.4: "This is an aggregate rule: each individual assignment may be
        perfectly legal while the collective load is not. Exceeding it is
        `ERR_TERM_LOAD_EXCEEDED`."

        Design: Corner/validations/adjunct_load_cap_is_an_aggregate_check_across_sections
        """
        state = _loaded_adjunct(env)
        spare = state["one_credit"]
        assert read_faculty(state["alex_id"])["assigned_credit_hours"] == 9, (
            "three legal three-credit assignments sit exactly on the adjunct ceiling"
        )

        validate_error(
            api.create_course_assignment(
                assignment_payload(spare["id"], state["alex_id"], spare["version"]),
                env.dean_df,
            ),
            ApiErrorId.ERR_TERM_LOAD_EXCEEDED,
        )
        accepted = validate_success(
            api.create_course_assignment(
                assignment_payload(spare["id"], state["morgan_id"], spare["version"]),
                env.dean_df,
            ),
            201,
        )

        assert read_faculty(state["alex_id"])["assigned_credit_hours"] == 9, (
            "the refused assignment left the adjunct's ledger untouched"
        )
        assert read_faculty(state["morgan_id"])["assigned_credit_hours"] == 1, (
            "the identical one-credit section fits under the full-time ceiling of 15"
        )
        assert_fields(accepted, status="VERIFIED_QUALIFIED")
        assert_version_advanced_by(read_section(spare["id"]), spare["version"], 1)
        for assignment in state["held"]:
            assert_assignment_verdict(
                read_assignment(assignment["id"]),
                status="EXCEPTION_FLAGGED",
                qualification_basis="NONE",
                exception_code="DISCIPLINE_MISALIGNED",
                alignment_score=0.6500,
            )


def _blocked_roster_state(env):
    """A generated roster carrying one flagged instructor of record."""
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
    assignment = make_assignment(monday["id"], alex["id"], env.prog_df_id)
    roster = make_generated_roster(env.prog_df_id, env.term_id)
    move_term(env.term_id, "ROSTER_LOCKED")
    return {"assignment": assignment, "roster": roster}


class TestRosterReadinessGate:
    def test_one_blocked_roster_stops_certification_and_term_closure(self, api, env):
        """PRD §2.10: "`certification_readiness` is `READY` → otherwise
        `ERR_ROSTER_NOT_READY` (409). Applies to roster certification and to term
        status changes; on the term endpoint the rule reads that every roster of the
        term must already be `CERTIFIED` or `SUPERSEDED` before the term may close."

        Design: Corner/validations/roster_readiness_gates_certification_and_term_closure
        """
        state = _blocked_roster_state(env)

        validate_error(
            api.certify_roster(
                state["roster"]["id"],
                {"attestation_note": "Ready for accreditor submission."},
                TEST_USERS["liaison_2"],
            ),
            ApiErrorId.ERR_ROSTER_NOT_READY,
        )
        validate_error(
            api.set_term_status(
                env.term_id, term_status_payload("CLOSED"), TEST_USERS["registrar"]
            ),
            ApiErrorId.ERR_ROSTER_NOT_READY,
        )

        assert_roster_snapshot(
            read_roster(state["roster"]["id"]),
            status="GENERATED",
            certification_readiness="BLOCKED",
            certified_at=None,
            certified_by_user_id=None,
        )
        assert_ordered_codes(
            read_roster(state["roster"]["id"])["blocking_reason_codes"],
            ["EXCEPTIONS_OUTSTANDING", "ADEQUACY_BELOW_MINIMUM"],
            "blocking_reason_codes",
        )
        assert_fields(
            validate_success(api.get_term(env.term_id, TEST_USERS["registrar"])),
            status="ROSTER_LOCKED",
        )
        assert_assignment_verdict(
            read_assignment(state["assignment"]["id"]),
            status="EXCEPTION_FLAGGED",
            qualification_basis="NONE",
            exception_code="DISCIPLINE_MISALIGNED",
        )


class TestSatisfiedCertificationChain:
    def test_a_clean_roster_certifies_and_then_locks_its_term(self, api, env):
        """PRD §3.6: "On success, `certified_at` is stamped with the logical clock
        instant and `certified_by_user_id` with the acting `X-User-ID`, the roster's
        `version` increments by 1, and every included assignment becomes immutable —
        remediation, reverification and withdrawal against it are all thereafter
        rejected with `ERR_ROSTER_CERTIFIED`, as is attaching a new assignment to any
        of its sections."

        Design: Corner/validations/fully_satisfied_preconditions_let_the_certification_chain_succeed
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
        assignment = make_assignment(monday["id"], morgan["id"], env.prog_df_id)
        roster = make_generated_roster(env.prog_df_id, env.term_id)
        assert_roster_snapshot(
            roster, certification_readiness="READY", blocking_reason_codes=[]
        )

        certified = validate_success(
            api.certify_roster(
                roster["id"],
                {
                    "attestation_note": (
                        "All instructors of record hold terminal degrees in discipline."
                    )
                },
                TEST_USERS["liaison_2"],
            )
        )
        locked = validate_success(
            api.set_term_status(
                env.term_id, term_status_payload("ROSTER_LOCKED"), TEST_USERS["registrar"]
            )
        )

        assert_roster_snapshot(
            certified,
            status="CERTIFIED",
            certified_by_user_id="liaison-02",
            certification_readiness="READY",
            blocking_reason_codes=[],
            adequacy_ratio_snapshot=1.0000,
            total_assignment_count=1,
            flagged_exception_count=0,
            terminal_qualified_headcount=1,
        )
        assert_clock_instant(certified.get("certified_at"), CLOCK_DEFAULT, "certified_at")
        assert_version_advanced_by(certified, roster["version"], 1)
        assert_fields(locked, status="ROSTER_LOCKED")
        assert_fields(
            read_assignment(assignment["id"]), status="VERIFIED_QUALIFIED"
        )
        validate_error(
            api.withdraw_assignment(assignment["id"], {}, env.dean_df),
            ApiErrorId.ERR_ROSTER_CERTIFIED,
        )
