"""Final coding, DRG mismatch reconciliation, denial targets, and OCC."""
import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    close_review,
    create_and_activate_review,
    create_case,
    create_denial_risk_target_payload,
    create_program,
    create_provider,
    create_query,
    finalize_case,
    get_case,
    setup_agreed_case,
    setup_basic_scenario,
    setup_mismatched_finalize,
    validate_error,
    validate_success,
)


class TestFinalizePreconditions:
    def test_finalize_blocked_while_review_open(self, api, him_coder_headers):
        """PRD §3.7: "no review of the case may be in `DRAFT`, `ACTIVE`, or
        `ON_HOLD` (`ERR_OPEN_REVIEW_EXISTS`)"

        Design: Corner/state_machines/patient_case_finalize_blocked_while_review_open
        """
        scenario = setup_basic_scenario(discharge_period=1)
        create_and_activate_review(scenario["case"]["id"])
        advance_clock(scenario["program"]["id"], 2)
        current = get_case(scenario["case"]["id"])
        resp = api.finalize_coding(
            scenario["case"]["id"],
            {
                "coder_drg_code": current["working_drg_code"],
                "coder_drg_weight": current["working_drg_weight"],
                "expected_case_version": current["version"],
            },
            him_coder_headers,
        )
        validate_error(resp, ApiErrorId.ERR_OPEN_REVIEW_EXISTS)

    def test_finalize_before_discharge_returns_case_not_discharged(self, api, him_coder_headers):
        """PRD §3.7: "the program's `current_period_index` must be at least the
        case's `discharge_period` (`ERR_CASE_NOT_DISCHARGED`)"

        Design: Corner/state_machines/patient_case_finalize_before_discharge_returns_case_not_discharged
        """
        program = create_program()
        provider = create_provider(program["id"])
        case = create_case(program["id"], provider["id"], discharge_period=10)
        resp = api.finalize_coding(
            case["id"],
            {
                "coder_drg_code": case["working_drg_code"],
                "coder_drg_weight": case["working_drg_weight"],
                "expected_case_version": case["version"],
            },
            him_coder_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_DISCHARGED)


class TestDrgMismatchReconciliation:
    def test_mismatch_creates_event_and_rejects(self, api):
        """PRD §3.7: "If `coder_drg_code` differs from `working_drg_code`, or
        `coder_drg_weight` differs from `working_drg_weight`, finalization is
        blocked: a `ReconciliationEvent` is created in `OPEN` status capturing the
        coder's `coder_drg_code` and `coder_drg_weight` as inputs and snapshotting
        the case's current working values as `cdi_drg_code` and `cdi_drg_weight`"

        Design: Difficulty/compensating_invariant/agree_then_coder_prevails_reconciliation_preserves_drift
        """
        scenario = setup_mismatched_finalize()
        validate_error(scenario["mismatch_error"], ApiErrorId.ERR_DRG_MISMATCH)
        event = scenario["reconciliation"]
        assert event is not None
        assert event["status"] == "OPEN"
        assert event["coder_drg_code"] == "DRG-A"
        assert event["coder_drg_weight"] == pytest.approx(1.0, abs=1e-9)
        # Snapshot of the case's working values at event creation (post-AGREE).
        assert event["cdi_drg_code"] == "DRG-B"
        assert event["cdi_drg_weight"] == pytest.approx(2.0, abs=1e-9)
        case = get_case(scenario["case"]["id"])
        assert case["reconciliation_status"] == "PENDING"
        assert case["status"] == "UNDER_REVIEW"

    def test_coder_prevails_restores_original_weight(self, api, cdi_manager_headers,
                                                     cdi_specialist_headers):
        """PRD §3.7: "When the coder prevails, the event moves to
        `RESOLVED_CODER_PREVAILS`, the case's `reconciliation_status` becomes
        `RESOLVED_CODER_PREVAILS`, its `working_drg_code` and `working_drg_weight`
        are overwritten with the coder's values, and its `priority_score` is
        recomputed."
        PRD §3.6: "These deltas are cumulative realizations: they are not
        recomputed downward when a later `AGREE` overwrites an earlier one"

        Design: Difficulty/compensating_invariant/agree_then_coder_prevails_reconciliation_preserves_drift
        """
        scenario = setup_mismatched_finalize()
        event = scenario["reconciliation"]
        resolved = validate_success(
            api.resolve_reconciliation_event(
                event["id"],
                {"outcome": "CODER_PREVAILS", "resolution_note": "coder correct"},
                cdi_manager_headers,
            )
        )
        assert resolved["status"] == "RESOLVED_CODER_PREVAILS"
        case = get_case(scenario["case"]["id"])
        assert case["working_drg_code"] == "DRG-A"
        assert case["working_drg_weight"] == pytest.approx(1.0, abs=1e-9)
        assert case["reconciliation_status"] == "RESOLVED_CODER_PREVAILS"
        assert case["status"] == "RECONCILED"
        # Review deltas are cumulative realizations and are not rolled back.
        review = validate_success(
            api.get_cdi_review(scenario["review"]["id"], cdi_specialist_headers)
        )
        assert review["opportunity_weight_delta"] == pytest.approx(1.0, abs=1e-9)


class TestDenialTargetWindow:
    def test_finalize_before_window_not_subject_to_target(self, api, cdi_manager_headers,
                                                          him_coder_headers):
        """PRD §3.7: "For every `DenialRiskTarget` whose `drg_code` equals the
        case's `working_drg_code` and whose active window — from
        `active_from_period` through `active_to_period`, both inclusive —
        contains the program's `current_period_index`, two requirements must
        hold."

        Design: Difficulty/resource_temporal_overlap/denial_target_active_window_inclusive_boundaries
        """
        program = create_program()
        provider = create_provider(program["id"])
        validate_success(
            api.create_denial_risk_target(
                create_denial_risk_target_payload(
                    program["id"], drg_code="A",
                    required_evidence_tags=["NEEDED_TAG"], severity_floor=1,
                    active_from_period=5, active_to_period=7,
                ),
                cdi_manager_headers,
            ),
            expected_status=201,
        )
        case = create_case(
            program["id"], provider["id"],
            admission_period=0, discharge_period=3,
            initial_drg_code="A", initial_drg_weight=1.0,
        )
        # Finalize at period 4 < active_from 5: target window does not apply.
        advance_clock(program["id"], 4)
        finalized = finalize_case(case["id"])
        assert finalized["status"] == "FINAL_CODED"

    def test_finalize_at_window_start_is_subject_to_target(self, api, cdi_manager_headers,
                                                           him_coder_headers):
        """PRD §3.7: "Every tag in the target's `required_evidence_tags` must
        appear in the union of `clinical_indicators` across the case's queries
        that are `RESPONDED` with a response type of `AGREE`, and the case's
        `working_soi` must be at least the target's `severity_floor`. Any
        shortfall is rejected with `ERR_DENIAL_TARGET_UNMET`."

        Design: Difficulty/resource_temporal_overlap/denial_target_active_window_inclusive_boundaries
        """
        program = create_program()
        provider = create_provider(program["id"])
        validate_success(
            api.create_denial_risk_target(
                create_denial_risk_target_payload(
                    program["id"], drg_code="A",
                    required_evidence_tags=["NEEDED_TAG"], severity_floor=1,
                    active_from_period=5, active_to_period=7,
                ),
                cdi_manager_headers,
            ),
            expected_status=201,
        )
        case = create_case(
            program["id"], provider["id"],
            admission_period=0, discharge_period=5,
            initial_drg_code="A", initial_drg_weight=1.0,
        )
        # Finalize at period 5 == active_from (inclusive): target applies; the
        # case has no AGREED queries, so NEEDED_TAG is missing.
        advance_clock(program["id"], 5)
        current = get_case(case["id"])
        resp = api.finalize_coding(
            case["id"],
            {
                "coder_drg_code": "A",
                "coder_drg_weight": 1.0,
                "expected_case_version": current["version"],
            },
            him_coder_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DENIAL_TARGET_UNMET)


class TestOptimisticConcurrency:
    def test_finalize_with_stale_case_version_rejected(self, api, him_coder_headers):
        """PRD §2.8: "Finalizing a case's coding requires `expected_case_version`;
        a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), because a
        prior `AGREE` response or a reconciliation resolution may have updated the
        case's working DRG fields"

        Design: Corner/cross_cutting_complexity_layers/occ_finalize_coding_stale_version
        """
        scenario = setup_agreed_case(
            proposed_drg_weight=2.0, proposed_soi=2, proposed_rom=2,
            proposed_drg_code="DRG-B", initial_drg_weight=1.0, initial_drg_code="DRG-A",
            discharge_period=1, response_due_periods=10, escalation_stage_periods=10,
        )
        close_review(scenario["review"]["id"])
        advance_clock(scenario["program"]["id"], 2)
        # v_obs is the creation version; AGREE + cascades have since bumped it.
        v_obs = scenario["case"]["version"]
        resp = api.finalize_coding(
            scenario["case"]["id"],
            {
                "coder_drg_code": "DRG-B",
                "coder_drg_weight": 2.0,
                "expected_case_version": v_obs,
            },
            him_coder_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_query_send_stale_version_after_edit(self, api, cdi_specialist_headers):
        """PRD §2.8: "Sending a query requires `expected_query_version`; a
        mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), because edits to
        the query's text or indicators after the caller's last read invalidate the
        lint assumptions under which the send was prepared."

        Design: Corner/cross_cutting_complexity_layers/occ_query_send_stale_version_after_edit
        """
        scenario = setup_basic_scenario(
            discharge_period=10, response_due_periods=5, escalation_stage_periods=5,
        )
        review = create_and_activate_review(scenario["case"]["id"])
        query = create_query(
            review["id"], scenario["provider"]["id"], scenario["policy"]["id"]
        )
        stale_version = query["version"]
        validate_success(
            api.update_cdi_query(query["id"], {"query_text": "edited"}, cdi_specialist_headers)
        )
        resp = api.send_cdi_query(
            query["id"], {"expected_query_version": stale_version}, cdi_specialist_headers
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_review_close_stale_version_rejected(self, api, cdi_specialist_headers):
        """PRD §2.8: "Closing a review requires `expected_review_version`; if the
        value does not match the review's current `version`, the request is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_finalize_coding_stale_version
        """
        scenario = setup_basic_scenario(discharge_period=10)
        review = create_and_activate_review(scenario["case"]["id"])
        # review["version"] at creation was 1; activation bumped it to 2.
        resp = api.close_cdi_review(
            review["id"],
            {"closed_reason": "NO_OPPORTUNITY", "expected_review_version": 1},
            cdi_specialist_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
