"""Non-linear walks: the assignment remediation cycle and the two faculty dimensions."""

from test_helpers import (
    advance_transcript,
    assert_fields,
    assert_ordered_codes,
    assert_score,
    countersign_contract,
    decide_verification,
    file_credential,
    make_assignment,
    make_contract,
    make_credentialed_faculty,
    make_section,
    make_verified_credential,
    open_remediation,
    read_assignment,
    read_faculty,
    reverify_assignment,
    validate_success,
    verification_payload,
    TEST_USERS,
)


def _cycle_state(env):
    """Morgan Ellis, qualified on an aligned master's, whose second credential
    is about to be repudiated."""
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
    return {
        "faculty_id": morgan["id"],
        "sacrificial_id": sacrificial["id"],
        "assignment_id": assignment["id"],
    }


def _repudiate(api, record_id, note):
    return validate_success(
        api.decide_verification(
            record_id,
            verification_payload("REPUDIATE", note=note),
            TEST_USERS["analyst"],
        )
    )


class TestAssignmentRemediationCycle:
    def test_reverification_can_walk_back_to_exception_flagged(self, api, env):
        """PRD §3.4: "When the determination still fails and no approved
        justification exists, the assignment instead moves
        `REMEDIATION_IN_PROGRESS → EXCEPTION_FLAGGED`, `remediation_action` is
        cleared to null, `exception_code` is recomputed, and the covering roster
        recomputes."

        Design: Difficulty/non_linear_state_machine/assignment_walks_qualified_flagged_remediation_flagged_qualified_cycle
        """
        state = _cycle_state(env)
        assert_fields(
            read_assignment(state["assignment_id"]), status="VERIFIED_QUALIFIED"
        )

        _repudiate(api, state["sacrificial_id"], "Institution withdrew the certificate")
        assert_fields(
            read_assignment(state["assignment_id"]),
            status="EXCEPTION_FLAGGED",
            exception_code="DOSSIER_DEFICIENT",
        )
        open_remediation(
            state["assignment_id"], env.prog_df_id, "CREDENTIAL_UPDATE_PENDING"
        )
        file_credential(
            state["faculty_id"],
            "NON_DEGREE_GRADUATE",
            env.pr_id,
            "Northern Extension",
            graduate_credit_hours_in_discipline=6,
        )

        reverified = validate_success(
            api.reverify_assignment(state["assignment_id"], {}, TEST_USERS["analyst"])
        )

        assert_fields(
            reverified,
            status="EXCEPTION_FLAGGED",
            exception_code="DOSSIER_DEFICIENT",
            remediation_action=None,
        )
        assert_score(reverified["alignment_score"], 1.0000, "alignment_score")

    def test_dossier_walks_deficient_then_under_review_then_verified(self, api, env):
        """PRD §3.2: "Filing a replacement record in `PENDING` moves
        `DEFICIENT → UNDER_REVIEW`."

        Design: Difficulty/non_linear_state_machine/assignment_walks_qualified_flagged_remediation_flagged_qualified_cycle
        """
        state = _cycle_state(env)

        _repudiate(api, state["sacrificial_id"], "Institution withdrew the certificate")
        after_repudiation = read_faculty(state["faculty_id"])
        assert after_repudiation["dossier_status"] == "DEFICIENT", (
            "an uncured repudiation leaves the dossier DEFICIENT, got "
            f"{after_repudiation['dossier_status']}"
        )
        assert_ordered_codes(
            after_repudiation["deficiency_codes"],
            ["CREDENTIAL_REPUDIATED"],
            "deficiency_codes",
        )

        replacement = file_credential(
            state["faculty_id"],
            "NON_DEGREE_GRADUATE",
            env.pr_id,
            "Northern Extension",
            graduate_credit_hours_in_discipline=6,
        )
        assert read_faculty(state["faculty_id"])["dossier_status"] == "UNDER_REVIEW", (
            "a pending record outranks any deficiency"
        )

        advance_transcript(replacement["id"], "OFFICIAL_RECEIVED")
        decide_verification(replacement["id"], "VERIFY")

        cured = read_faculty(state["faculty_id"])
        assert_fields(cured, dossier_status="VERIFIED")
        assert_ordered_codes(cured["deficiency_codes"], [], "deficiency_codes")

    def test_cycle_closes_back_on_terminal_degree(self, api, env):
        """PRD §3.4: "This closes the cycle
        `VERIFIED_QUALIFIED → EXCEPTION_FLAGGED → REMEDIATION_IN_PROGRESS → VERIFIED_QUALIFIED`."

        Design: Difficulty/non_linear_state_machine/assignment_walks_qualified_flagged_remediation_flagged_qualified_cycle
        """
        state = _cycle_state(env)

        _repudiate(api, state["sacrificial_id"], "Institution withdrew the certificate")
        open_remediation(
            state["assignment_id"], env.prog_df_id, "CREDENTIAL_UPDATE_PENDING"
        )
        replacement = file_credential(
            state["faculty_id"],
            "NON_DEGREE_GRADUATE",
            env.pr_id,
            "Northern Extension",
            graduate_credit_hours_in_discipline=6,
        )
        reverify_assignment(state["assignment_id"])
        advance_transcript(replacement["id"], "OFFICIAL_RECEIVED")
        decide_verification(replacement["id"], "VERIFY")
        open_remediation(
            state["assignment_id"], env.prog_df_id, "CREDENTIAL_UPDATE_PENDING"
        )

        closed = validate_success(
            api.reverify_assignment(state["assignment_id"], {}, TEST_USERS["analyst"])
        )

        assert_fields(
            closed,
            status="VERIFIED_QUALIFIED",
            qualification_basis="TERMINAL_DEGREE",
            exception_code=None,
            remediation_action=None,
        )
        faculty = read_faculty(state["faculty_id"])
        assert_fields(faculty, appointment_status="CREDENTIALED_ELIGIBLE")
        assert faculty["assigned_credit_hours"] == 3, (
            "the assignment never left the ledger set during the cycle, got "
            f"{faculty['assigned_credit_hours']}"
        )


def _contracted_state(env):
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
    contract = make_contract(
        morgan["id"], env.term_id, "FULL_TIME", 9, env.prog_cw_id
    )
    countersign_contract(contract["id"], morgan["id"])
    return {
        "faculty_id": morgan["id"],
        "sacrificial_id": sacrificial["id"],
        "contract_id": contract["id"],
        "faculty_version": read_faculty(morgan["id"])["version"],
    }


class TestFacultyDimensionsAreIndependent:
    def test_repudiation_does_not_demote_a_contracted_appointment(self, api, env):
        """PRD §3.2: "A dossier going bad never demotes an appointment — an
        already `CONTRACTED` instructor whose credential is later repudiated stays
        `CONTRACTED`, and that pairing of a contracted appointment with a deficient
        dossier is precisely the exception the accreditor reads."

        Design: Difficulty/non_linear_state_machine/faculty_dossier_and_appointment_dimensions_move_independently
        """
        state = _contracted_state(env)

        _repudiate(api, state["sacrificial_id"], "Institution withdrew the certificate")

        faculty = read_faculty(state["faculty_id"])
        assert_fields(
            faculty,
            dossier_status="DEFICIENT",
            appointment_status="CONTRACTED",
        )
        assert_ordered_codes(
            faculty["deficiency_codes"], ["CREDENTIAL_REPUDIATED"], "deficiency_codes"
        )
        assert faculty["version"] > state["faculty_version"], (
            "the repudiation recompute must advance the faculty member's version"
        )

    def test_contract_snapshots_are_frozen_at_issuance(self, api, env):
        """PRD §2.5: "`FacultyContract.dossier_snapshot_status` pins that faculty
        member's `dossier_status` at issuance (always `VERIFIED`, since issuance
        requires it). Neither is ever rewritten, so an auditor can see at a glance
        that the credential evidence moved after the contract was cut."

        Design: Difficulty/non_linear_state_machine/faculty_dossier_and_appointment_dimensions_move_independently
        """
        state = _contracted_state(env)

        _repudiate(api, state["sacrificial_id"], "Institution withdrew the certificate")

        contract = validate_success(
            api.get_contract(state["contract_id"], TEST_USERS["registrar"])
        )
        assert_fields(
            contract, status="COUNTERSIGNED", dossier_snapshot_status="VERIFIED"
        )
        assert_fields(
            read_faculty(state["faculty_id"]), highest_verified_degree_level="MASTERS"
        )
