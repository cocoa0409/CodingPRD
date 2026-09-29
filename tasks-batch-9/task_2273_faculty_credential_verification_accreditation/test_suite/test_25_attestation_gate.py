"""The attestation precondition, which no tested-experience score can buy off."""

from test_helpers import (
    ApiErrorId,
    assert_assignment_verdict,
    assert_fields,
    assert_program_adequacy,
    assert_roster_snapshot,
    assert_score,
    justification_decision_payload,
    make_assignment,
    make_credentialed_faculty,
    make_generated_roster,
    make_reviewed_justification,
    make_section,
    read_assignment,
    read_program,
    read_roster,
    validate_error,
    validate_success,
    TEST_USERS,
)

PERFECT_CODES = ["SPJ-CERT", "AP-STYLE", "INVEST-01", "DIGITAL-02"]


def _two_flagged_justifications(env):
    """Two identical top-scoring justifications, only one of them attested."""
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
    dana_assignment = make_assignment(monday["id"], dana["id"], env.prog_df_id)
    alex_assignment = make_assignment(tuesday["id"], alex["id"], env.prog_df_id)
    roster = make_generated_roster(env.prog_df_id, env.term_id)
    unattested = make_reviewed_justification(
        dana_assignment["id"],
        env.prog_df_id,
        documented_years_experience=8,
        industry_certification_level="BOARD_CERTIFIED",
        alternative_credential_codes=PERFECT_CODES,
        supervisor_attestation_on_file=False,
    )
    attested = make_reviewed_justification(
        alex_assignment["id"],
        env.prog_df_id,
        documented_years_experience=8,
        industry_certification_level="BOARD_CERTIFIED",
        alternative_credential_codes=PERFECT_CODES,
        supervisor_attestation_on_file=True,
    )
    return {
        "dana_assignment": dana_assignment,
        "alex_assignment": alex_assignment,
        "roster": roster,
        "unattested": unattested,
        "attested": attested,
    }


class TestAttestationGate:
    def test_a_perfect_score_cannot_substitute_for_the_attestation(self, api, env):
        """PRD §3.5: "`supervisor_attestation_on_file` must be true, or the decision
        fails with `ERR_ATTESTATION_MISSING` — a signed supervisor attestation is a
        hard precondition and no score compensates for its absence."

        Design: Corner/errors/attestation_gate_is_independent_of_the_tested_experience_score
        """
        state = _two_flagged_justifications(env)
        assert_score(
            state["unattested"]["tested_experience_score"],
            1.0000,
            "tested_experience_score without the attestation",
        )
        assert_score(
            state["attested"]["tested_experience_score"],
            1.0000,
            "tested_experience_score with the attestation",
        )
        assert_roster_snapshot(
            state["roster"], total_assignment_count=2, flagged_exception_count=2
        )

        validate_error(
            api.decide_justification(
                state["unattested"]["id"],
                justification_decision_payload(
                    "APPROVE", decision_rationale="Experience is ample"
                ),
                TEST_USERS["analyst_2"],
            ),
            ApiErrorId.ERR_ATTESTATION_MISSING,
        )

        assert_fields(
            validate_success(
                api.get_justification(
                    state["unattested"]["id"], TEST_USERS["analyst_2"]
                )
            ),
            status="UNDER_REVIEW",
            decided_by_user_id=None,
        )
        assert_fields(
            read_assignment(state["dana_assignment"]["id"]), status="EXCEPTION_FLAGGED"
        )
        assert_roster_snapshot(read_roster(state["roster"]["id"]), flagged_exception_count=2)

        approved = validate_success(
            api.decide_justification(
                state["attested"]["id"],
                justification_decision_payload(
                    "APPROVE",
                    decision_rationale="Experience documented and attested",
                ),
                TEST_USERS["analyst_2"],
            )
        )

        assert_fields(approved, status="APPROVED", decided_by_user_id="analyst-02")
        assert_assignment_verdict(
            read_assignment(state["alex_assignment"]["id"]),
            status="VERIFIED_QUALIFIED",
            qualification_basis="TESTED_EXPERIENCE",
            exception_code=None,
        )
        assert_fields(
            read_assignment(state["alex_assignment"]["id"]), remediation_action=None
        )
        assert_roster_snapshot(
            read_roster(state["roster"]["id"]),
            flagged_exception_count=1,
            adequacy_ratio_snapshot=0.0000,
            terminal_qualified_headcount=0,
            certification_readiness="BLOCKED",
            blocking_reason_codes=["EXCEPTIONS_OUTSTANDING", "ADEQUACY_BELOW_MINIMUM"],
        )
        assert_program_adequacy(
            read_program(env.prog_df_id),
            unqualified_assignment_count=1,
            adequacy_status="INSUFFICIENT",
        )
