"""The four-factor risk index and its single-pass tier selection."""

from test_helpers import (
    advance_transcript,
    assert_fields,
    assert_risk_value,
    assert_score,
    decide_verification,
    file_credential,
    findings_payload,
    make_assignment,
    make_credentialed_faculty,
    make_generated_roster,
    make_section,
    make_started_review,
    open_remediation,
    read_assignment,
    read_roster,
    TEST_USERS,
    validate_success,
)


def _risk_state(env):
    """Four assignments, three of them unqualified, one already remediating."""
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
    alex = make_credentialed_faculty(
        "Alex Stone",
        "alex.stone@example.edu",
        "ADJUNCT",
        env.prog_cw_id,
        "MASTERS",
        env.pr_id,
        "Coastal University",
        graduate_credit_hours_in_discipline=33,
    )["faculty"]
    unofficial = file_credential(
        alex["id"],
        "NON_DEGREE_GRADUATE",
        env.pr_id,
        "Coastal Extension",
        graduate_credit_hours_in_discipline=6,
    )
    advance_transcript(unofficial["id"], "UNOFFICIAL_ONLY")
    decide_verification(unofficial["id"], "VERIFY")

    plan = [
        ("JOUR201", "Feature Writing", 3, ["MON"], 620),
        ("JOUR202", "Editing I", 3, ["TUE"], 620),
        ("JOUR203", "Editing II", 3, ["WED"], 620),
        ("JOUR204", "Editing Studio", 1, ["THU"], 600),
    ]
    sections = [
        make_section(
            env.prog_cw_id,
            env.term_id,
            env.journ_id,
            code,
            title,
            credit_hours=hours,
            meeting_days=days,
            meeting_start_minute=540,
            meeting_end_minute=end,
        )
        for code, title, hours, days, end in plan
    ]
    asn_q = make_assignment(sections[0]["id"], morgan["id"], env.prog_cw_id)
    asn_x1 = make_assignment(sections[1]["id"], alex["id"], env.prog_cw_id)
    asn_x2 = make_assignment(sections[2]["id"], alex["id"], env.prog_cw_id)
    asn_x3 = make_assignment(sections[3]["id"], alex["id"], env.prog_cw_id)
    roster = make_generated_roster(env.prog_cw_id, env.term_id)
    open_remediation(asn_x2["id"], env.prog_cw_id, "CREDENTIAL_UPDATE_PENDING")
    review = make_started_review(env.prog_cw_id, "FOCUSED_FOLLOWUP")
    return {
        "review_id": review["id"],
        "roster_id": roster["id"],
        "asn_q": asn_q["id"],
        "asn_x1": asn_x1["id"],
        "asn_x2": asn_x2["id"],
        "asn_x3": asn_x3["id"],
    }


class TestAccreditorRiskIndex:
    def test_preliminary_index_is_the_weighted_sum_of_four_factors(self, api, env):
        """PRD §3.9: "`preliminary_risk_index` is 100 multiplied by the weighted
        sum of those four — the unqualified share weighted 0.40, the dossier share
        0.25, the exception-persistence share 0.20 and the adequacy gap 0.15 —
        rounded half up to 2 decimal places."

        Design: Difficulty/combinatorial_formula/accreditor_risk_index_weighted_sum_then_single_pass_tier_multiplier
        """
        state = _risk_state(env)

        review = validate_success(
            api.issue_findings(
                state["review_id"],
                findings_payload(
                    finding_count=3,
                    narrative=(
                        "Three Journalism assignments are taught on a Public "
                        "Relations credential"
                    ),
                ),
                TEST_USERS["reviewer"],
            )
        )

        assert_risk_value(
            review["preliminary_risk_index"], 55.00, "preliminary_risk_index"
        )
        assert_fields(
            review,
            status="REMEDIATION_REQUIRED",
            finding_count=3,
            response_round=0,
        )
        roster = read_roster(state["roster_id"])
        assert_score(
            roster["adequacy_ratio_snapshot"], 0.3000, "adequacy_ratio_snapshot"
        )

    def test_tier_is_read_from_the_preliminary_index_and_nothing_else(self, api, env):
        """PRD §3.9: "`risk_tier` is then selected from `preliminary_risk_index`
        **and from nothing else**: `LOW` when it is below 30, `MODERATE` when it is
        below 60, and `HIGH` otherwise."

        Design: Difficulty/combinatorial_formula/accreditor_risk_index_weighted_sum_then_single_pass_tier_multiplier
        """
        state = _risk_state(env)

        review = validate_success(
            api.issue_findings(
                state["review_id"],
                findings_payload(finding_count=3, narrative="Credential mismatch"),
                TEST_USERS["reviewer"],
            )
        )

        assert review["risk_tier"] == "MODERATE", (
            "a preliminary index of 55.00 selects MODERATE, and the multiplied "
            f"60.50 must not re-tier it, got {review['risk_tier']}"
        )
        assert_risk_value(review["risk_index"], 60.50, "risk_index")
        assert review["response_due_date"] == "2026-09-30", (
            "MODERATE allows 60 days from the clock date 2026-08-01; a HIGH "
            f"re-tier would have written 2026-08-31, got {review['response_due_date']}"
        )

    def test_findings_cascade_reads_state_before_it_moves_the_flagged_rows(
        self, api, env
    ):
        """PRD §3.9: "Every listed assignment currently in `EXCEPTION_FLAGGED`
        moves to `REMEDIATION_IN_PROGRESS` with `remediation_action` set to
        `REASSIGN_PENDING`."

        Design: Difficulty/combinatorial_formula/accreditor_risk_index_weighted_sum_then_single_pass_tier_multiplier
        """
        state = _risk_state(env)

        review = validate_success(
            api.issue_findings(
                state["review_id"],
                findings_payload(finding_count=3, narrative="Credential mismatch"),
                TEST_USERS["reviewer"],
            )
        )

        assert review["unqualified_assignment_ids"] == [
            state["asn_x1"],
            state["asn_x2"],
            state["asn_x3"],
        ], (
            "the unqualified list is the anchor roster's flagged and remediating "
            f"assignments in created_at order, got {review['unqualified_assignment_ids']!r}"
        )
        assert_fields(
            read_assignment(state["asn_x1"]),
            status="REMEDIATION_IN_PROGRESS",
            remediation_action="REASSIGN_PENDING",
        )
        assert_fields(
            read_assignment(state["asn_x3"]),
            status="REMEDIATION_IN_PROGRESS",
            remediation_action="REASSIGN_PENDING",
        )
        assert_fields(
            read_assignment(state["asn_x2"]),
            status="REMEDIATION_IN_PROGRESS",
            remediation_action="CREDENTIAL_UPDATE_PENDING",
        )
        assert_fields(read_assignment(state["asn_q"]), status="VERIFIED_QUALIFIED")
