"""Mandate acknowledgement workflow: cyclic return loop, SoD, deadline,
mandate retire cascade, and program rule locking."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_mandate,
    create_mandate_ack,
    create_mcc_block_rule_payload,
    create_program_with_bin_and_publish,
    create_submitted_ack,
    get_success_data,
    make_compliance_officer_headers,
    set_clock,
    validate_error,
    validate_success,
)

CO = TEST_USERS["compliance_officer_headers"]


class TestMandateAckCyclicLoop:
    def test_ack_return_resubmit_verify_cycle_increments_revision(self, api):
        """PRD §3.7: "The acknowledgement starts `DRAFT` with `revision_count`
        zero." and "A returned acknowledgement may be resubmitted (`RETURNED` →
        `SUBMITTED`), which increments `revision_count`, re-locks the program,
        and records the new submitter's identity; the cycle can iterate until
        the acknowledgement is finally disposed".

        Design: Difficulty/non_linear_state_machine/mandate_ack_cyclic_return_loop
        """
        set_clock("2026-08-01T00:00:00Z")
        prog, _bin = create_program_with_bin_and_publish("P-VISA-5", bin_prefix="444444")
        mandate = create_mandate("VI-2026-Q3-001", title="Tokenization mandate")
        ack = create_mandate_ack(mandate["id"], prog["id"], "v1 notes")
        # DRAFT → SUBMITTED (u1) → RETURNED (u2) → SUBMITTED (u3) → VERIFIED (u4)
        get_success_data(
            api.submit_mandate_ack(mandate["id"], ack["id"],
                                   make_compliance_officer_headers("user-cto-1")),
        )
        get_success_data(
            api.return_mandate_ack(mandate["id"], ack["id"],
                                   make_compliance_officer_headers("user-cto-2")),
        )
        resubmitted = get_success_data(
            api.submit_mandate_ack(mandate["id"], ack["id"],
                                   make_compliance_officer_headers("user-cto-3")),
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["revision_count"] == 1, (
            f"Exactly one RETURN→SUBMIT cycle must yield revision_count == 1, got "
            f"{resubmitted['revision_count']}"
        )
        verified = get_success_data(
            api.verify_mandate_ack(mandate["id"], ack["id"],
                                   make_compliance_officer_headers("user-cto-4")),
        )
        assert verified["status"] == "VERIFIED"
        assert verified["revision_count"] == 1
        assert verified.get("verified_by_user_id") == "user-cto-4"

    def test_ack_lock_released_after_verify(self, api):
        """PRD §3.7: "Verification (`SUBMITTED` → `VERIFIED`) additionally
        requires the clock to still be ahead of the mandate's
        `compliance_deadline` — a verification at or past the deadline fails
        with `ERR_MANDATE_DEADLINE_PASSED` — and records `verified_by_user_id`
        while releasing the lock".

        Design: Difficulty/non_linear_state_machine/mandate_ack_cyclic_return_loop
        """
        set_clock("2026-08-01T00:00:00Z")
        prog, _bin = create_program_with_bin_and_publish("P-VISA-5B", bin_prefix="444445")
        mandate = create_mandate("VI-2026-Q3-001B")
        ack = create_submitted_ack(mandate["id"], prog["id"], "user-cto-1")
        prog_mid = get_success_data(api.get_program(prog["id"], CO))
        assert prog_mid["authorization_rules_locked"] is True, (
            "Submission locks the program (authorization_rules_locked=true)"
        )
        get_success_data(
            api.verify_mandate_ack(mandate["id"], ack["id"],
                                   make_compliance_officer_headers("user-cto-4")),
        )
        prog_after = get_success_data(api.get_program(prog["id"], CO))
        assert prog_after["authorization_rules_locked"] is False, (
            "Verification releases the lock (authorization_rules_locked=false)"
        )


class TestMandateAckSod:
    def test_mandate_ack_sod_same_user_rejected(self, api):
        """PRD §3.7: "Returning, verifying, or rejecting a submitted
        acknowledgement must be performed by a different operator than the one
        who submitted it — a matching `X-User-ID` is rejected with
        `ERR_SOD_SAME_USER` — and this segregation check precedes the deadline
        check".

        Design: Corner/state_machines/mandate_ack_sod_same_user_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        prog, _bin = create_program_with_bin_and_publish("P-SOD")
        mandate = create_mandate("M-SOD")
        ack = create_submitted_ack(mandate["id"], prog["id"], "u-1")
        resp = api.verify_mandate_ack(
            mandate["id"], ack["id"], make_compliance_officer_headers("u-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SOD_SAME_USER.value)


class TestMandateDeadline:
    def test_mandate_verify_blocked_by_deadline(self, api):
        """PRD §3.7: "Verification (`SUBMITTED` → `VERIFIED`) additionally
        requires the clock to still be ahead of the mandate's
        `compliance_deadline` — a verification at or past the deadline fails
        with `ERR_MANDATE_DEADLINE_PASSED` — and records `verified_by_user_id`
        while releasing the lock".

        Design: Difficulty/cross_entity_state_dependency/mandate_verify_blocked_by_deadline
        """
        set_clock("2026-08-01T00:00:00Z")
        prog, _bin = create_program_with_bin_and_publish("P-VISA-14", bin_prefix="444400")
        mandate = create_mandate(
            "VI-14",
            effective_at="2026-08-02T00:00:00Z",
            compliance_deadline="2026-08-10T00:00:00Z",
        )
        ack = create_submitted_ack(mandate["id"], prog["id"], "user-cto-1")
        # Advance the clock past the compliance deadline.
        set_clock("2026-08-15T00:00:00Z")
        resp = api.verify_mandate_ack(
            mandate["id"], ack["id"], make_compliance_officer_headers("user-cto-2"),
        )
        validate_error(resp, ApiErrorId.ERR_MANDATE_DEADLINE_PASSED.value)

    def test_mandate_verify_before_deadline_succeeds(self, api):
        """PRD §3.7: "Verification (`SUBMITTED` → `VERIFIED`) additionally
        requires the clock to still be ahead of the mandate's
        `compliance_deadline` — a verification at or past the deadline fails
        with `ERR_MANDATE_DEADLINE_PASSED` — and records `verified_by_user_id`
        while releasing the lock".

        Design: Difficulty/cross_entity_state_dependency/mandate_verify_blocked_by_deadline
        """
        set_clock("2026-08-01T00:00:00Z")
        prog, _bin = create_program_with_bin_and_publish("P-VISA-14B", bin_prefix="444401")
        mandate = create_mandate(
            "VI-14B",
            effective_at="2026-08-02T00:00:00Z",
            compliance_deadline="2026-08-10T00:00:00Z",
        )
        ack = create_submitted_ack(mandate["id"], prog["id"], "user-cto-1")
        # Verify before the deadline (clock still 2026-08-01).
        resp = api.verify_mandate_ack(
            mandate["id"], ack["id"], make_compliance_officer_headers("user-cto-2"),
        )
        data = validate_success(resp)
        assert data["status"] == "VERIFIED"
        assert data.get("verified_by_user_id") == "user-cto-2"


class TestValidationPriority:
    def test_state_check_precedes_sod_on_terminal_ack(self, api):
        """PRD §2.7: "State validity — the target resource must be in a state
        that permits the requested transition (`ERR_INVALID_STATE`)." and
        "Business checks — segregation of duties (`ERR_SOD_SAME_USER`)" appear
        later in the same pinned order, and PRD §3.7 states "`VERIFIED` and
        `REJECTED` are terminal".

        A verify against an already-VERIFIED (terminal) ack by the original
        submitter must surface ERR_INVALID_STATE (state, step 6) rather than
        ERR_SOD_SAME_USER (business, step 7).

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_sod
        """
        set_clock("2026-08-01T00:00:00Z")
        prog, _bin = create_program_with_bin_and_publish("P-VISA-9", bin_prefix="488888")
        mandate = create_mandate("VI-P9")
        ack = create_submitted_ack(mandate["id"], prog["id"], "user-cto-1")
        get_success_data(
            api.verify_mandate_ack(mandate["id"], ack["id"],
                                   make_compliance_officer_headers("user-cto-9")),
        )
        # Ack is now VERIFIED (terminal). A second verify — even by the original
        # submitter (which would be an SoD violation if it could run) — must hit
        # the earlier state-validity check.
        resp = api.verify_mandate_ack(
            mandate["id"], ack["id"], make_compliance_officer_headers("user-cto-1"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_state_check_precedes_sod_on_return_of_verified_ack(self, api):
        """PRD §2.7: "State validity — the target resource must be in a state
        that permits the requested transition (`ERR_INVALID_STATE`)." and
        "Business checks — segregation of duties (`ERR_SOD_SAME_USER`)" appear
        later in the same pinned order, and PRD §3.7 states "`VERIFIED` and
        `REJECTED` are terminal".

        A return against a VERIFIED ack must surface ERR_INVALID_STATE before
        any SoD evaluation.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_sod
        """
        set_clock("2026-08-01T00:00:00Z")
        prog, _bin = create_program_with_bin_and_publish("P-VISA-9B", bin_prefix="488889")
        mandate = create_mandate("VI-P9B")
        ack = create_submitted_ack(mandate["id"], prog["id"], "user-cto-1")
        get_success_data(
            api.verify_mandate_ack(mandate["id"], ack["id"],
                                   make_compliance_officer_headers("user-cto-9")),
        )
        resp = api.return_mandate_ack(
            mandate["id"], ack["id"], make_compliance_officer_headers("user-cto-1"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestMandateRetireCascade:
    def test_mandate_retire_rejects_draft_acks_and_unlocks_program(self, api):
        """PRD §3.7: "from either state, retiring flips all of the mandate's
        `DRAFT` and `RETURNED` acknowledgements to `REJECTED`. Retiring an
        `EFFECTIVE` mandate also recomputes every affected program's lock: a
        program's `authorization_rules_locked` becomes true if any other
        acknowledgement against a still-active mandate is `SUBMITTED` for that
        program, and false otherwise."

        Design: Difficulty/transitive_cascade/mandate_retire_cascade_depth_2
        """
        set_clock("2026-08-01T00:00:00Z")
        prog, _bin = create_program_with_bin_and_publish("P-VISA-8", bin_prefix="477777")
        mandate = create_mandate(
            "VI-2026-Q3-RET",
            effective_at="2026-08-02T00:00:00Z",
            severity="ADVISORY",
        )
        # Push the clock past effective_at and observe the mandate flip to
        # EFFECTIVE on read (lazy transition).
        set_clock("2026-08-03T00:00:00Z")
        mandate_after = get_success_data(api.get_mandate(mandate["id"], CO))
        assert mandate_after["status"] == "EFFECTIVE"
        ack = create_mandate_ack(mandate["id"], prog["id"], "draft notes")
        # Retire the EFFECTIVE mandate.
        retired = get_success_data(api.retire_mandate(mandate["id"], CO))
        assert retired["status"] == "RETIRED"
        ack_after = get_success_data(api.get_mandate_ack(mandate["id"], ack["id"], CO))
        assert ack_after["status"] == "REJECTED", (
            f"DRAFT ack must flip to REJECTED on mandate retire, got "
            f"{ack_after['status']}"
        )
        prog_after = get_success_data(api.get_program(prog["id"], CO))
        assert prog_after["authorization_rules_locked"] is False

    def test_mandate_retire_rejects_returned_ack(self, api):
        """PRD §3.7: "from either state, retiring flips all of the mandate's
        `DRAFT` and `RETURNED` acknowledgements to `REJECTED`."

        Design: Difficulty/transitive_cascade/mandate_retire_cascade_depth_2
        """
        set_clock("2026-08-01T00:00:00Z")
        prog, _bin = create_program_with_bin_and_publish("P-VISA-8B", bin_prefix="477778")
        mandate = create_mandate(
            "VI-2026-Q3-RET-B",
            effective_at="2026-08-02T00:00:00Z",
            severity="ADVISORY",
        )
        set_clock("2026-08-03T00:00:00Z")
        get_success_data(api.get_mandate(mandate["id"], CO))  # force lazy EFFECTIVE
        ack = create_submitted_ack(mandate["id"], prog["id"], "user-cto-1")
        # Return it (SUBMITTED → RETURNED), which also releases the lock.
        get_success_data(
            api.return_mandate_ack(mandate["id"], ack["id"],
                                   make_compliance_officer_headers("user-cto-2")),
        )
        get_success_data(api.retire_mandate(mandate["id"], CO))
        ack_after = get_success_data(api.get_mandate_ack(mandate["id"], ack["id"], CO))
        assert ack_after["status"] == "REJECTED", (
            f"RETURNED ack must flip to REJECTED on mandate retire, got "
            f"{ack_after['status']}"
        )


class TestConditionalFeatureFlag:
    def test_conditional_feature_flag_rules_locked(self, api):
        """PRD §3.5: "for a program-scoped rule the program's
        `authorization_rules_locked` must be false — a locked program rejects
        the activation with `ERR_PROGRAM_RULES_LOCKED`".

        Design: Corner/cross_cutting_complexity_layers/conditional_feature_flag_rules_locked
        """
        set_clock("2026-08-01T00:00:00Z")
        prog, _bin = create_program_with_bin_and_publish("P-LK")
        mandate = create_mandate("M-LK")
        create_submitted_ack(mandate["id"], prog["id"], "u-1")  # locks the program
        rule = get_success_data(
            api.create_authorization_rule(
                create_mcc_block_rule_payload("PROGRAM", prog["id"], mcc_list=["7995"]),
                CO,
            ),
        )
        resp = api.activate_authorization_rule(rule["id"], rule["version"], CO)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_RULES_LOCKED.value)


class TestScheduledMandateTransition:
    def test_scheduled_mandate_transition(self, api):
        """PRD §3.7: "A mandate starts `ANNOUNCED` and flips itself to
        `EFFECTIVE` once the clock reaches `effective_at`".

        Design: Corner/cross_cutting_complexity_layers/scheduled_mandate_transition
        """
        set_clock("2026-08-01T00:00:00Z")
        mandate = create_mandate("M-SCHED", effective_at="2026-09-01T00:00:00Z")
        assert mandate["status"] == "ANNOUNCED"
        set_clock("2026-09-02T00:00:00Z")
        after = get_success_data(api.get_mandate(mandate["id"], CO))
        assert after["status"] == "EFFECTIVE", (
            f"Mandate must flip ANNOUNCED → EFFECTIVE once clock reaches "
            f"effective_at; got {after['status']}"
        )
