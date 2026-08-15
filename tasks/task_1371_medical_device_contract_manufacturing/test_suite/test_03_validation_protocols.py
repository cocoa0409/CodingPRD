"""Validation protocols: reject loop, revalidation cycle, segregation, line buffer."""
from test_helpers import (
    QE_CAROL,
    ApiErrorId,
    QE_ALICE,
    assert_instant_equal,
    create_approved_dmr,
    create_line,
    create_protocol,
    create_validated_stack,
    qe,
    qm,
    set_clock,
    sqe,
    validate_error,
    validate_success,
    walk_protocol_to_validated,
    api_client,
)


class TestProtocolRejectLoopAndRevalidationCycle:
    def test_reject_returns_to_execution_and_clears_executor(self, api):
        """PRD section 3.3: "Rejection instead returns the phase to its execution
        state and clears that phase's executor identifier, so rework may be
        performed by any quality engineer."

        Design: Difficulty/non_linear_state_machine/validation_protocol_reject_loop_and_revalidation_cycle
        """
        line = create_line("L-V")
        dmr = create_approved_dmr(device_code="DEV-V")
        protocol = create_protocol("VP-V", dmr["id"], line["id"])
        validate_success(api.execute_phase(protocol["id"], qe(QE_ALICE)))
        validate_success(api.submit_phase_review(protocol["id"], qe(QE_ALICE)))

        rejected = validate_success(api.reject_phase(protocol["id"], qm()))
        assert rejected["status"] == "IQ_EXECUTION"
        assert rejected["iq_executor_user_id"] is None, (
            "reject must clear the phase executor so another engineer can rework"
        )

        resubmitted = validate_success(api.submit_phase_review(protocol["id"], qe(QE_CAROL)))
        assert resubmitted["iq_executor_user_id"] == QE_CAROL

    def test_validated_then_time_expiry_revalidation_starts_new_generation(self, api):
        """PRD section 3.3: "the protocol becomes `VALIDATED`, `validated_at` is
        stamped from the logical clock, `revalidation_due_at` is set to thirty-six
        months (three years) after `validated_at`" and PRD section 2.5: "Every
        validation protocol in `VALIDATED` whose `revalidation_due_at` has been
        reached or passed transitions to `REVALIDATION_REQUIRED` with
        `revalidation_reason` `TIME_EXPIRY`" and PRD section 3.3: "When execution
        begins from `REVALIDATION_REQUIRED`, a new validation cycle starts:
        `generation` increments by one".

        Design: Difficulty/non_linear_state_machine/validation_protocol_reject_loop_and_revalidation_cycle
        """
        line = create_line("L-V")
        dmr = create_approved_dmr(device_code="DEV-V")
        protocol = create_protocol("VP-V", dmr["id"], line["id"])
        validated = walk_protocol_to_validated(protocol["id"])
        assert validated["status"] == "VALIDATED"
        assert_instant_equal(validated["validated_at"], "2026-08-01T00:00:00Z", "validated_at")
        assert_instant_equal(
            validated["revalidation_due_at"], "2029-08-01T00:00:00Z", "revalidation_due_at"
        )

        set_clock("2029-08-01T00:00:00Z")
        swept = validate_success(api.get_protocol(protocol["id"], qm()))
        assert swept["status"] == "REVALIDATION_REQUIRED"
        assert swept["revalidation_reason"] == "TIME_EXPIRY"

        reexecuted = validate_success(api.execute_phase(protocol["id"], qe()))
        assert reexecuted["status"] == "IQ_EXECUTION"
        assert reexecuted["generation"] == 2


class TestProtocolGuards:
    def test_execute_phase_from_review_rejected(self, api):
        """PRD section 3.3: "Beginning execution moves a protocol from `DRAFT` —
        or, in a later cycle, from `REVALIDATION_REQUIRED` — to `IQ_EXECUTION`" —
        from `IQ_REVIEW` no such transition is declared, and PRD section 2.10
        step 7 rejects it with `ERR_INVALID_STATE_TRANSITION`.

        Design: Corner/state_machines/protocol_execute_from_review_rejected
        """
        line = create_line("L-IV")
        dmr = create_approved_dmr(device_code="DEV-IV")
        protocol = create_protocol("VP-IV", dmr["id"], line["id"])
        validate_success(api.execute_phase(protocol["id"], qe()))
        validate_success(api.submit_phase_review(protocol["id"], qe()))

        resp = api.execute_phase(protocol["id"], qe())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        current = validate_success(api.get_protocol(protocol["id"], qm()))
        assert current["status"] == "IQ_REVIEW"

    def test_approve_phase_segregation_of_duties(self, api):
        """PRD section 3.3: "Approval is forbidden to the phase's executor
        (`ERR_SEGREGATION_OF_DUTIES`)" and PRD section 2.6: "The operator
        approving a validation phase must not be that phase's recorded executor".

        Design: Corner/state_machines/protocol_approve_phase_segregation
        """
        line = create_line("L-SD")
        dmr = create_approved_dmr(device_code="DEV-SD")
        protocol = create_protocol("VP-SD", dmr["id"], line["id"])
        validate_success(api.execute_phase(protocol["id"], qe(QE_ALICE)))
        validate_success(api.submit_phase_review(protocol["id"], qe(QE_ALICE)))

        from test_helpers import make_quality_manager_headers

        resp = api.approve_phase(protocol["id"], make_quality_manager_headers(QE_ALICE))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        current = validate_success(api.get_protocol(protocol["id"], qm()))
        assert current["status"] == "IQ_REVIEW"

        approved = validate_success(api.approve_phase(protocol["id"], qm()))
        assert approved["status"] == "OQ_EXECUTION"

    def test_protocol_create_on_draft_dmr_rejected(self, api):
        """PRD section 3.3: "the `dmr_id` of the pinned revision under validation
        (which must be `APPROVED`, else `ERR_DMR_NOT_APPROVED`)".

        Design: Corner/endpoints/protocol_create_on_draft_dmr_rejected
        """
        from test_helpers import create_dmr_draft, create_protocol_payload

        line = create_line("L-PD")
        dmr = create_dmr_draft(device_code="DEV-PD")
        resp = api.create_protocol(
            create_protocol_payload(dmr["id"], line["id"], protocol_code="VP-PD"), qe()
        )
        validate_error(resp, ApiErrorId.ERR_DMR_NOT_APPROVED)


class TestLineWindowChangeoverBuffer:
    def test_gap_exactly_equal_to_buffer_is_accepted(self, api):
        """PRD section 3.3: "a new protocol is rejected with
        `ERR_LINE_WINDOW_CONFLICT` when the gap between its window and any
        occupying protocol's window — measured from the earlier window's
        `planned_end` to the later window's `planned_start`, in either direction
        — is strictly less than the line's `changeover_buffer_hours`. A gap of
        exactly the buffer, or more, is acceptable."

        Design: Difficulty/resource_temporal_overlap/line_window_changeover_buffer
        """
        line = create_line("L-BF", changeover_buffer_hours=24)
        dmr = create_approved_dmr(device_code="DEV-BF")
        create_protocol("VP-BF1", dmr["id"], line["id"],
                        planned_start="2026-09-01T00:00:00Z", planned_end="2026-09-05T00:00:00Z")
        second = create_protocol("VP-BF2", dmr["id"], line["id"],
                                 planned_start="2026-09-06T00:00:00Z", planned_end="2026-09-08T00:00:00Z")
        assert second["status"] == "DRAFT", (
            "a gap of exactly 24h (the buffer) must be acceptable"
        )

    def test_gap_below_buffer_is_rejected(self, api):
        """PRD section 3.3: "a new protocol is rejected with
        `ERR_LINE_WINDOW_CONFLICT` when the gap between its window and any
        occupying protocol's window — measured from the earlier window's
        `planned_end` to the later window's `planned_start`, in either direction —
        is strictly less than the line's `changeover_buffer_hours`."

        Design: Difficulty/resource_temporal_overlap/line_window_changeover_buffer
        """
        from test_helpers import create_protocol_payload

        line = create_line("L-BF", changeover_buffer_hours=24)
        dmr = create_approved_dmr(device_code="DEV-BF")
        create_protocol("VP-BF1", dmr["id"], line["id"],
                        planned_start="2026-09-01T00:00:00Z", planned_end="2026-09-05T00:00:00Z")
        resp = api.create_protocol(
            create_protocol_payload(
                dmr["id"], line["id"], protocol_code="VP-BF3",
                planned_start="2026-09-05T12:00:00Z", planned_end="2026-09-07T00:00:00Z",
            ),
            qe(),
        )
        validate_error(resp, ApiErrorId.ERR_LINE_WINDOW_CONFLICT)
