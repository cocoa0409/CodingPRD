"""Cascade A (repudiation, five hops) and Cascade B (tested-experience approval)."""

from test_helpers import (
    assert_fields,
    assert_ordered_codes,
    assert_risk_value,
    assert_score,
    issue_findings,
    justification_decision_payload,
    make_assignment,
    make_credentialed_faculty,
    make_generated_roster,
    make_reviewed_justification,
    make_section,
    make_started_review,
    make_verified_credential,
    open_remediation,
    read_assignment,
    read_faculty,
    read_program,
    read_roster,
    submit_response,
    TEST_USERS,
    validate_success,
    verification_payload,
)


def _cascade_a_state(env):
    """A clean degree-field program whose only accreditor review has already
    reached RESPONSE_SUBMITTED."""
    morgan = make_credentialed_faculty(
        "Morgan Ellis",
        "morgan.ellis@example.edu",
        "FULL_TIME",
        env.prog_cw_id,
        "MASTERS",
        env.journ_id,
        "Northern University",
        graduate_credit_hours_in_discipline=36,
    )["faculty"]
    sacrificial = make_verified_credential(
        morgan["id"],
        "NON_DEGREE_GRADUATE",
        env.pr_id,
        "Northern Extension",
        graduate_credit_hours_in_discipline=6,
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
    assignment = make_assignment(section["id"], morgan["id"], env.prog_df_id)
    roster = make_generated_roster(env.prog_df_id, env.term_id)
    review = make_started_review(env.prog_df_id, "COMPREHENSIVE")
    issue_findings(
        review["id"],
        2,
        narrative="Syllabus documentation gaps; no unqualified assignments identified",
    )
    submitted = submit_response(review["id"], "Syllabi refreshed and archived")
    return {
        "faculty_id": morgan["id"],
        "sacrificial_id": sacrificial["id"],
        "assignment_id": assignment["id"],
        "roster_id": roster["id"],
        "review_id": review["id"],
        "review_before": submitted,
    }


def _repudiate(api, record_id):
    return validate_success(
        api.decide_verification(
            record_id,
            verification_payload("REPUDIATE", note="Issuing body revoked the certificate"),
            TEST_USERS["analyst"],
        )
    )


class TestCascadeARepudiation:
    def test_hops_one_and_two_leave_the_appointment_alone(self, api, env):
        """PRD §2.11: "`appointment_status` is deliberately not touched anywhere in
        cascade A."

        Design: Difficulty/transitive_cascade/cascade_a_repudiation_five_hops_to_accreditor_review_bounce_back
        """
        state = _cascade_a_state(env)

        record = _repudiate(api, state["sacrificial_id"])

        assert_fields(record, verification_status="REPUDIATED")
        faculty = read_faculty(state["faculty_id"])
        assert_fields(
            faculty,
            dossier_status="DEFICIENT",
            appointment_status="CREDENTIALED_ELIGIBLE",
        )
        assert_ordered_codes(
            faculty["deficiency_codes"], ["CREDENTIAL_REPUDIATED"], "deficiency_codes"
        )

    def test_hops_three_and_four_rebuild_the_roster_without_a_new_epoch(self, api, env):
        """PRD §2.11: "`blocking_reason_codes` gains both `DOSSIER_DEFICIENT` and
        `EXCEPTIONS_OUTSTANDING`, and `certification_readiness` becomes `BLOCKED`.
        `generation_epoch` is **not** advanced."

        Design: Difficulty/transitive_cascade/cascade_a_repudiation_five_hops_to_accreditor_review_bounce_back
        """
        state = _cascade_a_state(env)

        _repudiate(api, state["sacrificial_id"])

        assert_fields(
            read_assignment(state["assignment_id"]),
            status="EXCEPTION_FLAGGED",
            exception_code="DOSSIER_DEFICIENT",
            qualification_basis="NONE",
        )
        roster = read_roster(state["roster_id"])
        assert_fields(
            roster,
            flagged_exception_count=1,
            terminal_qualified_headcount=0,
            certification_readiness="BLOCKED",
            generation_epoch=1,
        )
        assert_score(
            roster["adequacy_ratio_snapshot"], 0.0000, "adequacy_ratio_snapshot"
        )
        assert_ordered_codes(
            roster["blocking_reason_codes"],
            ["EXCEPTIONS_OUTSTANDING", "ADEQUACY_BELOW_MINIMUM", "DOSSIER_DEFICIENT"],
            "blocking_reason_codes",
        )
        program = read_program(env.prog_df_id)
        assert_fields(
            program, adequacy_status="INSUFFICIENT", unqualified_assignment_count=1
        )
        assert_score(program["adequacy_ratio"], 0.0000, "adequacy_ratio")

    def test_hop_five_bounces_the_review_and_keeps_the_response_round(self, api, env):
        """PRD §2.11: "every accreditor review of that program sitting in
        `RESPONSE_SUBMITTED` returns to `REMEDIATION_REQUIRED`, its risk metrics are
        recomputed against the current anchor roster, and `response_due_date` is
        reset to the clock date plus that tier's response days. `response_round` is
        left exactly as it was."

        Design: Difficulty/transitive_cascade/cascade_a_repudiation_five_hops_to_accreditor_review_bounce_back
        """
        state = _cascade_a_state(env)
        before = state["review_before"]
        assert_fields(
            before,
            status="RESPONSE_SUBMITTED",
            response_round=1,
            risk_tier="LOW",
            response_due_date="2026-10-30",
        )

        _repudiate(api, state["sacrificial_id"])

        review = validate_success(
            api.get_review(state["review_id"], TEST_USERS["reviewer"])
        )
        assert_fields(
            review,
            status="REMEDIATION_REQUIRED",
            risk_tier="HIGH",
            response_round=1,
            response_due_date="2026-08-31",
        )
        assert_risk_value(
            review["preliminary_risk_index"], 80.00, "preliminary_risk_index"
        )
        assert_risk_value(review["risk_index"], 100.00, "risk_index")


def _cascade_b_state(env):
    """Alex Stone, flagged on a sibling-discipline master's, with a reviewed
    tested-experience justification scoring 0.7500."""
    alex = make_credentialed_faculty(
        "Alex Stone",
        "alex.stone@example.edu",
        "ADJUNCT",
        env.prog_df_id,
        "MASTERS",
        env.pr_id,
        "Coastal University",
        graduate_credit_hours_in_discipline=33,
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
    assignment = make_assignment(section["id"], alex["id"], env.prog_df_id)
    roster = make_generated_roster(env.prog_df_id, env.term_id)
    open_remediation(assignment["id"], env.prog_df_id, "TESTED_EXPERIENCE_PENDING")
    justification = make_reviewed_justification(
        assignment["id"],
        env.prog_df_id,
        documented_years_experience=6,
        industry_certification_level="ADVANCED",
        alternative_credential_codes=["APR", "CPRC", "SMPS"],
        supervisor_attestation_on_file=True,
    )
    return {
        "faculty_id": alex["id"],
        "assignment_id": assignment["id"],
        "roster_id": roster["id"],
        "justification_id": justification["id"],
    }


def _approve(api, justification_id):
    return validate_success(
        api.decide_justification(
            justification_id,
            justification_decision_payload(
                "APPROVE",
                decision_rationale="Tested experience documented and attested",
            ),
            TEST_USERS["analyst_2"],
        )
    )


class TestCascadeBTestedExperienceApproval:
    def test_hop_one_qualifies_the_assignment_on_tested_experience(self, api, env):
        """PRD §3.5: "*Hop 1* — the backed assignment moves to `VERIFIED_QUALIFIED`
        with `qualification_basis` `TESTED_EXPERIENCE`, `exception_code` null and
        `remediation_action` null."

        Design: Difficulty/transitive_cascade/cascade_b_tested_experience_approval_three_hops_without_adequacy_relief
        """
        state = _cascade_b_state(env)

        justification = _approve(api, state["justification_id"])

        assert_fields(justification, status="APPROVED", decided_by_user_id="analyst-02")
        assert_score(
            justification["tested_experience_score"], 0.7500, "tested_experience_score"
        )
        assignment = read_assignment(state["assignment_id"])
        assert_fields(
            assignment,
            status="VERIFIED_QUALIFIED",
            qualification_basis="TESTED_EXPERIENCE",
            exception_code=None,
            remediation_action=None,
        )
        assert_score(assignment["alignment_score"], 0.6500, "alignment_score")

    def test_hop_two_clears_the_exception_without_lifting_adequacy(self, api, env):
        """PRD §3.5: "*Hop 2* — because that assignment left the exception set, the
        covering `GENERATED` roster's snapshot recomputes:
        `flagged_exception_count` decreases by 1, while `adequacy_ratio_snapshot`
        does **not** rise, because `TESTED_EXPERIENCE` is excluded from the
        qualified numerator."

        Design: Difficulty/transitive_cascade/cascade_b_tested_experience_approval_three_hops_without_adequacy_relief
        """
        state = _cascade_b_state(env)

        _approve(api, state["justification_id"])

        roster = read_roster(state["roster_id"])
        assert_fields(
            roster,
            flagged_exception_count=0,
            total_assignment_count=1,
            terminal_qualified_headcount=0,
            generation_epoch=1,
        )
        assert_score(
            roster["adequacy_ratio_snapshot"], 0.0000, "adequacy_ratio_snapshot"
        )

    def test_hop_three_leaves_the_roster_blocked_on_adequacy_alone(self, api, env):
        """PRD §3.5: "`blocking_reason_codes` may well retain
        `ADEQUACY_BELOW_MINIMUM`, leaving `certification_readiness` at `BLOCKED`
        even though the roster now has zero exceptions."

        Design: Difficulty/transitive_cascade/cascade_b_tested_experience_approval_three_hops_without_adequacy_relief
        """
        state = _cascade_b_state(env)

        _approve(api, state["justification_id"])

        roster = read_roster(state["roster_id"])
        assert_ordered_codes(
            roster["blocking_reason_codes"],
            ["ADEQUACY_BELOW_MINIMUM"],
            "blocking_reason_codes",
        )
        assert_fields(roster, certification_readiness="BLOCKED")
        program = read_program(env.prog_df_id)
        assert_fields(
            program, unqualified_assignment_count=0, adequacy_status="INSUFFICIENT"
        )
