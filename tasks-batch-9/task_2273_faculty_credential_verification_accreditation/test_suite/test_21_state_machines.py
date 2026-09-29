"""State machines: legal edges, guarded edges, terminal lockdown and replays."""

from test_helpers import (
    advance_transcript,
    ApiErrorId,
    assert_clock_instant,
    assert_fields,
    assert_hours,
    assert_ordered_codes,
    assert_risk_value,
    assert_score,
    assert_cents,
    certify_roster,
    CLOCK_DEFAULT,
    countersign_contract,
    decide_verification,
    evaluation_completion_payload,
    evaluation_payload,
    evaluation_status_payload,
    file_credential,
    issue_findings,
    justification_status_payload,
    make_assignment,
    make_contract,
    make_credentialed_faculty,
    make_faculty,
    make_generated_roster,
    make_justification,
    make_pd_record,
    make_program_dean_headers,
    make_review,
    make_roster,
    make_section,
    make_started_review,
    move_review,
    move_term,
    read_assignment,
    read_faculty,
    read_program,
    read_roster,
    read_section,
    review_status_payload,
    section_payload,
    set_clock,
    set_pd_status,
    submit_response,
    pd_status_payload,
    validate_error,
    validate_success,
    verification_payload,
    withdraw_assignment,
    withdrawal_payload,
    TEST_USERS,
)


class TestTermRevisionLoop:
    def test_the_roster_lock_holds_and_can_be_reversed(self, api, planning_env):
        """PRD §3.1: "Locking the roster is what stops the term's course sections from
        multiplying: while a term is `ROSTER_LOCKED`, new section creation is rejected
        with `ERR_TERM_LOCKED`, though assignment remediation, reverification,
        withdrawal and all roster work remain permitted."

        Design: Corner/state_machines/term_status_walks_forward_and_back_through_roster_locked
        """
        env = planning_env
        assert_fields(env.term, status="PLANNING", version=1)
        body = section_payload(
            env.prog_df_id,
            env.term_id,
            env.journ_id,
            "JOUR120",
            "Locked Out Section",
            meeting_days=["FRI"],
        )

        opened = move_term(env.term_id, "OPEN")
        locked = move_term(env.term_id, "ROSTER_LOCKED")
        refused = api.create_course_section(body, env.dean_df)
        after_refusal = validate_success(
            api.get_term(env.term_id, TEST_USERS["registrar"])
        )
        reopened = move_term(env.term_id, "OPEN")
        section = validate_success(api.create_course_section(body, env.dean_df), 201)

        assert_fields(opened, status="OPEN", version=2)
        assert_fields(locked, status="ROSTER_LOCKED", version=3)
        validate_error(refused, ApiErrorId.ERR_TERM_LOCKED)
        assert_fields(after_refusal, status="ROSTER_LOCKED", version=3)
        assert_fields(reopened, status="OPEN", version=4)
        assert_fields(section, course_code="JOUR120", version=1)


def _flagged_alex(env):
    """Alex Stone flagged on a Journalism section: PR master's, 0.6500 alignment."""
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
    section = make_section(
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
    assignment = make_assignment(section["id"], alex["id"], env.prog_df_id)
    return {
        "faculty_id": alex["id"],
        "section": section,
        "assignment": assignment,
    }


class TestJustificationInitialState:
    def test_a_justification_is_born_in_draft_with_its_score_already_computed(
        self, api, env
    ):
        """PRD §3.5: "The justification is created in `DRAFT` with
        `tested_experience_score` already computed, `decided_by_user_id` null and
        `decision_rationale` null."

        Design: Corner/state_machines/justification_created_in_draft_with_score_computed_at_creation
        """
        state = _flagged_alex(env)
        assert_fields(
            state["assignment"],
            status="EXCEPTION_FLAGGED",
            exception_code="DISCIPLINE_MISALIGNED",
        )

        justification = make_justification(
            state["assignment"]["id"],
            env.prog_df_id,
            documented_years_experience=4,
            industry_certification_level="PRACTITIONER",
            alternative_credential_codes=["APR", "CPRC"],
            supervisor_attestation_on_file=True,
            narrative="Four years in agency communications",
        )

        assert_fields(
            justification,
            status="DRAFT",
            version=1,
            decided_by_user_id=None,
            decision_rationale=None,
            supervisor_attestation_on_file=True,
        )
        assert_score(
            justification["tested_experience_score"],
            0.5000,
            "tested_experience_score",
        )
        assert_ordered_codes(
            justification["alternative_credential_codes"],
            ["APR", "CPRC"],
            "alternative_credential_codes",
        )
        after = read_assignment(state["assignment"]["id"])
        assert_fields(
            after, status="EXCEPTION_FLAGGED", exception_code="DISCIPLINE_MISALIGNED"
        )
        assert_score(after["alignment_score"], 0.6500, "alignment_score")


class TestVerificationTranscriptPrecondition:
    def test_verify_needs_a_transcript_and_an_unofficial_one_leaves_a_deficiency(
        self, api, env
    ):
        """PRD §3.2: "`PENDING → VERIFIED` requires the transcript to have reached
        `UNOFFICIAL_ONLY` or `OFFICIAL_RECEIVED`; verifying a record whose transcript
        is still `NOT_REQUESTED` is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/verification_before_transcript_rejected_then_unofficial_transcript_yields_deficient
        """
        alex = make_faculty(
            "Alex Stone", "alex.stone@example.edu", "ADJUNCT", env.prog_cw_id
        )
        record = file_credential(
            alex["id"],
            "MASTERS",
            env.pr_id,
            "Harbor College",
            is_foreign_institution=False,
            graduate_credit_hours_in_discipline=30,
        )

        too_early = api.decide_verification(
            record["id"], verification_payload("VERIFY"), TEST_USERS["analyst"]
        )

        validate_error(too_early, ApiErrorId.ERR_INVALID_STATE)
        assert_fields(
            validate_success(
                api.get_credential_record(record["id"], TEST_USERS["analyst"])
            ),
            verification_status="PENDING",
            verified_by_user_id=None,
        )

        unofficial = advance_transcript(record["id"], "UNOFFICIAL_ONLY")
        verified = decide_verification(record["id"], "VERIFY")

        assert_fields(unofficial, transcript_status="UNOFFICIAL_ONLY")
        assert_fields(
            verified, verification_status="VERIFIED", verified_by_user_id="analyst-01"
        )
        faculty = read_faculty(alex["id"])
        assert_ordered_codes(
            faculty["deficiency_codes"],
            ["TRANSCRIPT_NOT_OFFICIAL"],
            "deficiency_codes",
        )
        assert_fields(
            faculty,
            dossier_status="DEFICIENT",
            appointment_status="PROSPECT",
            highest_verified_degree_level="MASTERS",
        )


class TestReviewStartGuardedByTheClock:
    def test_a_review_cannot_go_in_progress_before_its_window_opens(self, api, env):
        """PRD §3.9: "`SCHEDULED → IN_PROGRESS` is legal only once the clock date has
        reached `window_start_date`; attempting it earlier is rejected with
        `ERR_INVALID_WINDOW`."

        Design: Corner/state_machines/accreditor_review_cannot_start_before_its_window_opens
        """
        review = make_review(
            env.prog_df_id, "COMPREHENSIVE", "2026-09-01", "2026-09-30"
        )

        too_early = api.set_review_status(
            review["id"], review_status_payload("IN_PROGRESS"), TEST_USERS["reviewer"]
        )

        validate_error(too_early, ApiErrorId.ERR_INVALID_WINDOW)
        assert_fields(
            validate_success(api.get_review(review["id"], TEST_USERS["reviewer"])),
            status="SCHEDULED",
        )

        set_clock("2026-09-01T00:00:00Z")
        started = move_review(review["id"], "IN_PROGRESS")

        assert_fields(
            started,
            status="IN_PROGRESS",
            finding_count=0,
            risk_tier="LOW",
            response_due_date=None,
        )
        assert_risk_value(started["risk_index"], 0.00, "risk_index")


FLOOR_FEE_CENTS = 15000


def _ordered_evaluation(api, env):
    """Dana's foreign master's with a four-page STANDARD evaluation at the floor."""
    dana = make_faculty(
        "Dana Reyes", "dana.reyes@example.edu", "ADJUNCT", env.prog_df_id
    )
    record = file_credential(
        dana["id"],
        "MASTERS",
        env.journ_id,
        "Universidad Central",
        is_foreign_institution=True,
        graduate_credit_hours_in_discipline=24,
    )
    evaluation = validate_success(
        api.create_credential_evaluation(
            evaluation_payload(
                record["id"],
                env.prog_df_id,
                evaluator_agency="WES",
                page_count=4,
                service_level="STANDARD",
            ),
            TEST_USERS["analyst"],
        ),
        201,
    )
    return {
        "faculty_id": dana["id"],
        "record_id": record["id"],
        "evaluation": evaluation,
    }


class TestEvaluationCannotSkipInReview:
    def test_completing_a_freshly_ordered_evaluation_is_not_a_declared_edge(
        self, api, env
    ):
        """PRD §2.10: "The requested state transition exists for the entity's current
        state → otherwise `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/evaluation_cannot_skip_the_in_review_step
        """
        state = _ordered_evaluation(api, env)
        evaluation = state["evaluation"]
        assert_cents(evaluation["fee_cents"], FLOOR_FEE_CENTS, "fee_cents")

        skipped = api.set_evaluation_status(
            evaluation["id"],
            evaluation_completion_payload("MASTERS", env.journ_id, "EQUIVALENT"),
            TEST_USERS["analyst"],
        )

        validate_error(skipped, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(
            api.get_credential_evaluation(evaluation["id"], TEST_USERS["analyst"])
        )
        assert_fields(
            after,
            status="ORDERED",
            equivalency_degree_level=None,
            equivalency_discipline_id=None,
            equivalency_verdict=None,
            allocation_shares=[],
        )
        program = read_program(env.prog_df_id)
        assert_cents(
            program["budget_reserved_cents"], FLOOR_FEE_CENTS, "budget_reserved_cents"
        )
        assert_cents(program["budget_spent_cents"], 0, "budget_spent_cents")
        assert_fields(
            validate_success(
                api.get_credential_record(state["record_id"], TEST_USERS["analyst"])
            ),
            effective_degree_level=None,
        )


class TestTerminalStateLockdown:
    def test_three_terminal_machines_refuse_every_further_trigger(self, api, env):
        """PRD §2.10: "Idempotency is **not** granted: repeating a trigger that
        already fired fails, because the second attempt is no longer a legal
        transition out of the new state. This code also covers terminal-state
        lockdown".

        Design: Corner/state_machines/terminal_states_reject_every_further_trigger
        """
        evaluation_state = _ordered_evaluation(api, env)
        validate_success(
            api.set_evaluation_status(
                evaluation_state["evaluation"]["id"],
                evaluation_status_payload("VOIDED"),
                TEST_USERS["analyst"],
            )
        )
        pd_record = make_pd_record(
            evaluation_state["faculty_id"],
            env.journ_id,
            "CONFERENCE",
            12.0,
            "2026-07-01",
        )
        set_pd_status(pd_record["id"], "VERIFIED")
        justification_state = _flagged_alex(env)
        justification = make_justification(
            justification_state["assignment"]["id"],
            env.prog_df_id,
            documented_years_experience=4,
            industry_certification_level="PRACTITIONER",
            alternative_credential_codes=["APR"],
            supervisor_attestation_on_file=True,
            narrative="Withdrawn before submission",
        )
        validate_success(
            api.set_justification_status(
                justification["id"],
                justification_status_payload("WITHDRAWN"),
                make_program_dean_headers(env.prog_df_id),
            )
        )

        void_poke = api.set_evaluation_status(
            evaluation_state["evaluation"]["id"],
            evaluation_status_payload("IN_REVIEW"),
            TEST_USERS["analyst"],
        )
        pd_poke = api.set_pd_record_status(
            pd_record["id"],
            pd_status_payload("REJECTED"),
            TEST_USERS["analyst"],
        )
        justification_poke = api.set_justification_status(
            justification["id"],
            justification_status_payload("SUBMITTED"),
            make_program_dean_headers(env.prog_df_id),
        )

        validate_error(void_poke, ApiErrorId.ERR_INVALID_STATE)
        assert_fields(
            validate_success(
                api.get_credential_evaluation(
                    evaluation_state["evaluation"]["id"], TEST_USERS["analyst"]
                )
            ),
            status="VOIDED",
        )
        program = read_program(env.prog_df_id)
        assert_cents(program["budget_reserved_cents"], 0, "budget_reserved_cents")
        assert_cents(program["budget_spent_cents"], 0, "budget_spent_cents")

        validate_error(pd_poke, ApiErrorId.ERR_INVALID_STATE)
        assert_fields(
            validate_success(
                api.get_pd_record(pd_record["id"], TEST_USERS["registrar"])
            ),
            status="VERIFIED",
        )
        dana = read_faculty(evaluation_state["faculty_id"])
        assert_hours(dana["pd_hours_current_cycle"], 12.0, "pd_hours_current_cycle")
        assert_fields(dana, pd_compliant=False)

        validate_error(justification_poke, ApiErrorId.ERR_INVALID_STATE)
        assert_fields(
            validate_success(
                api.get_justification(justification["id"], TEST_USERS["analyst"])
            ),
            status="WITHDRAWN",
        )


def _certified_roster_state(env):
    """Morgan qualified on a Journalism section, roster generated and certified."""
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
    assignment = make_assignment(
        section["id"], morgan["faculty"]["id"], env.prog_df_id
    )
    roster = make_generated_roster(env.prog_df_id, env.term_id)
    certified = certify_roster(
        roster["id"], attestation_note="All faculty verified for the term"
    )
    return {
        "faculty_id": morgan["faculty"]["id"],
        "record_id": morgan["record"]["id"],
        "section": section,
        "assignment": assignment,
        "roster": certified,
    }


class TestRepeatedTriggersAreNotIdempotent:
    def test_replaying_a_verification_or_a_certification_is_an_error(self, api, env):
        """PRD §2.10: "Idempotency is **not** granted: repeating a trigger that
        already fired fails, because the second attempt is no longer a legal
        transition out of the new state."

        Design: Corner/state_machines/repeated_verification_and_repeated_certification_are_not_idempotent
        """
        state = _certified_roster_state(env)
        assert_fields(state["roster"], status="CERTIFIED", generation_epoch=1)

        double_verify = api.decide_verification(
            state["record_id"],
            verification_payload("VERIFY"),
            TEST_USERS["analyst_2"],
        )
        double_certify = api.certify_roster(
            state["roster"]["id"],
            {"attestation_note": "Certifying again"},
            TEST_USERS["liaison_2"],
        )

        validate_error(double_verify, ApiErrorId.ERR_INVALID_STATE)
        assert_fields(
            validate_success(
                api.get_credential_record(state["record_id"], TEST_USERS["analyst"])
            ),
            verification_status="VERIFIED",
            verified_by_user_id="analyst-01",
        )
        validate_error(double_certify, ApiErrorId.ERR_INVALID_STATE)
        replayed_roster = read_roster(state["roster"]["id"])
        assert_fields(
            replayed_roster,
            status="CERTIFIED",
            certified_by_user_id="liaison-01",
            generation_epoch=1,
        )
        assert_clock_instant(
            replayed_roster.get("certified_at"), CLOCK_DEFAULT, "certified_at"
        )


class TestContractSideEffects:
    def test_issuance_freezes_the_evidence_and_the_edges_move_the_appointment(
        self, api, env
    ):
        """PRD §3.7: "Countersignature is the instructor's own act. An `Instructor`
        whose `X-User-ID` equals the contract's `faculty_member_id` countersigns an
        `ISSUED` contract, moving it `ISSUED → COUNTERSIGNED` and simultaneously
        moving the faculty member's appointment `CREDENTIALED_ELIGIBLE →
        CONTRACTED`."

        Design: Corner/state_machines/contract_countersignature_and_void_move_the_appointment_dimension
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
        frozen_version = read_faculty(morgan["id"])["version"]

        contract = make_contract(
            morgan["id"],
            env.term_id,
            "FULL_TIME",
            9,
            env.prog_cw_id,
            expected_faculty_version=frozen_version,
        )

        assert_clock_instant(contract.get("issued_at"), CLOCK_DEFAULT, "issued_at")
        assert_fields(
            contract,
            status="ISSUED",
            countersigned_at=None,
            dossier_snapshot_status="VERIFIED",
            credential_snapshot_version=frozen_version,
        )
        assert_fields(
            read_faculty(morgan["id"]), appointment_status="CREDENTIALED_ELIGIBLE"
        )

        countersigned = countersign_contract(contract["id"], morgan["id"])

        assert_fields(countersigned, status="COUNTERSIGNED")
        assert_clock_instant(
            countersigned.get("countersigned_at"), CLOCK_DEFAULT, "countersigned_at"
        )
        assert_fields(read_faculty(morgan["id"]), appointment_status="CONTRACTED")

        voided = validate_success(
            api.void_contract(
                contract["id"],
                {"reason": "Section cancelled before the term opened"},
                make_program_dean_headers(env.prog_cw_id),
            )
        )

        assert_fields(voided, status="VOIDED")
        assert_fields(
            read_faculty(morgan["id"]),
            appointment_status="CREDENTIALED_ELIGIBLE",
            dossier_status="VERIFIED",
        )


class TestRosterSupersession:
    def test_a_fresh_roster_supersedes_the_certified_one_and_thaws_its_assignments(
        self, api, env
    ):
        """PRD §3.6: "A `CERTIFIED` roster, by contrast, is not a duplicate — it moves
        to `SUPERSEDED`, which is terminal, and the assignments it had frozen become
        mutable again."

        Design: Corner/state_machines/new_roster_supersedes_the_certified_one_and_restores_assignment_mutability
        """
        state = _certified_roster_state(env)

        frozen = api.withdraw_assignment(
            state["assignment"]["id"],
            withdrawal_payload(reason="Attempting to withdraw from a certified roster"),
            make_program_dean_headers(env.prog_df_id),
        )

        validate_error(frozen, ApiErrorId.ERR_ROSTER_CERTIFIED)
        assert_fields(
            read_assignment(state["assignment"]["id"]), status="VERIFIED_QUALIFIED"
        )

        replacement = make_roster(env.prog_df_id, env.term_id)

        assert_fields(replacement, status="DRAFT", generation_epoch=0)
        assert_fields(
            read_roster(state["roster"]["id"]),
            status="SUPERSEDED",
            certified_by_user_id="liaison-01",
            total_assignment_count=1,
        )

        withdrawn = withdraw_assignment(
            state["assignment"]["id"], env.prog_df_id, reason="Section cancelled"
        )

        assert_fields(withdrawn, status="WITHDRAWN")
        assert read_faculty(state["faculty_id"])["assigned_credit_hours"] == 0
        assert_fields(
            read_section(state["section"]["id"]), instructor_of_record_id=None
        )
        assert_fields(read_roster(replacement["id"]), total_assignment_count=0)


class TestSanctionRequiresTwoRounds:
    def test_sanctioning_is_guarded_by_the_response_round_counter(self, api, env):
        """PRD §3.9: "Sanctioning, `RESPONSE_SUBMITTED → CLOSED_SANCTION`, is
        available only from a `response_round` of at least 2, so a program gets at
        least two attempts before a sanction is possible; an earlier attempt is
        rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/sanction_closure_requires_two_response_rounds
        """
        state = _flagged_alex(env)
        make_generated_roster(env.prog_df_id, env.term_id)
        review = make_started_review(env.prog_df_id, "COMPREHENSIVE")
        issue_findings(
            review["id"], 2, narrative="Two unqualified assignments observed"
        )
        first_response = submit_response(review["id"], "First remediation plan filed")
        assert_fields(first_response, status="RESPONSE_SUBMITTED", response_round=1)

        too_soon = api.set_review_status(
            review["id"],
            review_status_payload(
                "CLOSED_SANCTION", note="Attempting sanction after one round"
            ),
            TEST_USERS["reviewer"],
        )

        validate_error(too_soon, ApiErrorId.ERR_INVALID_STATE)
        assert_fields(
            validate_success(api.get_review(review["id"], TEST_USERS["reviewer"])),
            status="RESPONSE_SUBMITTED",
            response_round=1,
        )

        bounced = move_review(
            review["id"], "REMEDIATION_REQUIRED", note="Plan inadequate"
        )
        assert_fields(bounced, status="REMEDIATION_REQUIRED", response_round=1)

        second_response = submit_response(
            review["id"], "Second remediation plan filed"
        )
        assert_fields(second_response, status="RESPONSE_SUBMITTED", response_round=2)

        sanctioned = move_review(
            review["id"], "CLOSED_SANCTION", note="Sanction after the second round"
        )

        assert_fields(sanctioned, status="CLOSED_SANCTION", response_round=2)
        assert_fields(
            read_assignment(state["assignment"]["id"]),
            status="REMEDIATION_IN_PROGRESS",
        )
        assert_fields(read_program(env.prog_df_id), launch_status="PLANNING")
