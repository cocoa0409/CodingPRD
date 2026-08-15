"""Data quality audits and findings: open conflicts, close preconditions,
and the pinned dq_score evaluation order on resolution."""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_data_steward_headers,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    create_active_program,
    create_cycle,
    enroll_participant,
    grant_consent,
    open_audit_for_cycle,
    record_finding,
    setup_cycle_under_review,
    setup_observation_world,
    setup_program_with_approved_model,
    setup_participant_with_consent,
    setup_active_cycle,
    record_and_validate,
)
from test_helpers.test_users import DIRECTOR, STEWARD


class TestAuditOpenConflict:
    def test_audit_already_open_conflict(self, api):
        """PRD section 3.7: "at most one audit per cycle may be `OPEN` at a
        time: a second open attempt is rejected with `ERR_AUDIT_ALREADY_OPEN`
        (HTTP 409)."

        Design: Corner/validations/audit_already_open_conflict
        """
        program = create_active_program(name="DoubleAudit", code="DAU")
        cycle = create_cycle(program["id"])
        get_success_data(api.open_enrollment(cycle["id"], DIRECTOR))
        # Drive to DATA_CLOSED without any participants.
        # Need ACTIVE first -- cycle must be ENROLLING to activate, which
        # requires an APPROVED model. Use the helper.
        base = setup_program_with_approved_model(program_name="DAU-base",
                                                 program_code="DAB")
        cycle2 = setup_active_cycle(base["program"])
        get_success_data(api.close_data(cycle2["id"], DIRECTOR))

        first = open_audit_for_cycle(cycle2["id"])
        assert first["status"] == "OPEN"

        second_resp = api.open_audit(cycle2["id"], make_data_steward_headers("steward-1"))
        validate_error(second_resp, ApiErrorId.ERR_AUDIT_ALREADY_OPEN)


class TestAuditClosePrecondition:
    def test_audit_close_blocked_by_open_findings(self, api):
        """PRD section 3.7: "Closing an audit (`OPEN → CLOSED`) requires
        every finding to be resolved: with any finding still `OPEN`
        (`open_finding_count` above zero), the close is rejected with
        `ERR_INVALID_STATE`. Closing stamps `closed_at`, recomputes `dq_score`
        one final time, and copies it to the cycle's `latest_dq_score`."

        Design: Corner/state_machines/audit_close_blocked_by_open_findings
        """
        program = create_active_program(name="Audit", code="AUD")
        base = setup_program_with_approved_model(program_name="AuditBase",
                                                 program_code="ADB")
        cycle = setup_active_cycle(base["program"])
        pc = setup_participant_with_consent(cycle["id"])
        get_success_data(api.close_data(cycle["id"], DIRECTOR))

        audit = open_audit_for_cycle(cycle["id"])
        finding = record_finding(audit["id"], pc["participant"]["id"],
                                 finding_type="MISSING_DATA",
                                 description="no data at all")

        blocked = api.close_audit(audit["id"], make_data_steward_headers("steward-1"))
        validate_error(blocked, ApiErrorId.ERR_INVALID_STATE)

        get_success_data(api.waive_finding(
            finding["id"], {"reason": "documented exemption"},
            make_data_steward_headers("steward-1")))

        closed = get_success_data(
            api.close_audit(audit["id"], make_data_steward_headers("steward-1")))
        assert closed["status"] == "CLOSED"
        assert closed["closed_at"] is not None


class TestDqEvaluationOrder:
    def test_waive_removes_penalty_in_same_recompute(self, api):
        """PRD section 3.7: "First, the mutation that triggered the recompute
        - audit open, a finding recorded, a finding resolved, an observation
        validated or excluded, or audit close - is applied. ... Third, **F**
        counts the findings in `OPEN` status belonging to any audit of this
        cycle, regardless of those audits' own status. Fourth, the raw score
        is one-half of C, plus three-tenths of V, plus one-fifth of K, minus
        4.00 for each open finding."
        PRD section 3.7: "Each resolution recomputes `open_finding_count` and
        the quality fields - the penalty lifts as findings leave `OPEN`."

        Design: Difficulty/combinatorial_formula/dq_evaluation_order_on_finding_waive
        """
        base = setup_program_with_approved_model(
            program_name="Meals", program_code="MLS",
            indicator_specs=[{
                "code": "I1", "level": "OUTPUT", "unit": "COUNT",
                "direction": "HIGHER_IS_BETTER", "baseline_value": 0,
                "target_value": 100, "weight": 1.0,
                "measurement_frequency": "END_OF_CYCLE",
            }])
        cycle = setup_active_cycle(base["program"])
        pc = setup_participant_with_consent(cycle["id"])
        from test_helpers.fixtures import (
            create_certification, create_instrument, publish_instrument,
        )
        instr = create_instrument(base["program"]["id"], code="SURV", title="Survey")
        publish_instrument(instr["id"])
        create_certification(instr["id"], staff_user_id="collector-1")

        record_and_validate(pc["participant"]["id"],
                            base["indicators"]["I1"]["id"],
                            instr["id"], value=10)

        get_success_data(api.close_data(cycle["id"], DIRECTOR))
        audit = open_audit_for_cycle(cycle["id"])
        assert audit["dq_score"] == 100.00, (
            "C=100, V=100, K=100, F=0 -> dq_score 100.00"
        )

        finding = record_finding(audit["id"], pc["participant"]["id"],
                                 finding_type="MISSING_DATA",
                                 description="one indicator lacking mid-cycle data")
        audit_with_finding = get_success_data(
            api.get_audit(audit["id"], make_data_steward_headers("steward-1")))
        assert audit_with_finding["open_finding_count"] == 1
        assert audit_with_finding["dq_score"] == 96.00, (
            "the OPEN finding drags the score down by the 4.00 penalty"
        )

        get_success_data(api.waive_finding(
            finding["id"], {"reason": "acceptable coverage gap"},
            make_data_steward_headers("steward-1")))

        audit_after = get_success_data(
            api.get_audit(audit["id"], make_data_steward_headers("steward-1")))
        assert audit_after["open_finding_count"] == 0
        assert audit_after["dq_score"] == 100.00, (
            "the waived finding does not penalize the recompute its own waive triggered"
        )

        cycle_after = get_success_data(
            api.get_cycle(cycle["id"], make_data_steward_headers("steward-1")))
        assert cycle_after["latest_dq_score"] == 100.00

    def test_finding_record_lowers_dq_score(self, api):
        """PRD section 3.7: "Recording a finding recomputes the audit's
        `open_finding_count` and its `dq_score` - each new open finding drags
        the score down by the per-finding penalty - and the cycle's
        `latest_dq_score` follows."

        Design: Difficulty/combinatorial_formula/dq_evaluation_order_on_finding_waive
        """
        base = setup_program_with_approved_model(
            program_name="Meals2", program_code="ML2",
            indicator_specs=[{
                "code": "I1", "level": "OUTPUT", "unit": "COUNT",
                "direction": "HIGHER_IS_BETTER", "baseline_value": 0,
                "target_value": 100, "weight": 1.0,
                "measurement_frequency": "END_OF_CYCLE",
            }])
        cycle = setup_active_cycle(base["program"])
        pc = setup_participant_with_consent(cycle["id"])
        from test_helpers.fixtures import (
            create_certification, create_instrument, publish_instrument,
        )
        instr = create_instrument(base["program"]["id"], code="SURV", title="Survey")
        publish_instrument(instr["id"])
        create_certification(instr["id"], staff_user_id="collector-1")
        record_and_validate(pc["participant"]["id"],
                            base["indicators"]["I1"]["id"],
                            instr["id"], value=10)
        get_success_data(api.close_data(cycle["id"], DIRECTOR))
        audit = open_audit_for_cycle(cycle["id"])
        assert audit["dq_score"] == 100.00

        record_finding(audit["id"], pc["participant"]["id"],
                       finding_type="MISSING_DATA", description="one gap")
        audit_mid = get_success_data(
            api.get_audit(audit["id"], make_data_steward_headers("steward-1")))
        assert audit_mid["dq_score"] == 96.00
        cycle_mid = get_success_data(
            api.get_cycle(cycle["id"], make_data_steward_headers("steward-1")))
        assert cycle_mid["latest_dq_score"] == 96.00, (
            "cycle.latest_dq_score follows the audit recompute"
        )
