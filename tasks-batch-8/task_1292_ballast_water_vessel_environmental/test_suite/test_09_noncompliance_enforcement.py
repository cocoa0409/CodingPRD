"""Noncompliance response deadlines, severity derivation, clock-driven
escalation cascades, and enforcement case closure."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_enforcement_case,
    assert_timestamp_equals,
    create_voyage,
    depart_voyage,
    evaluate_inspection_ok,
    find_noncompliance,
    get_single_case,
    get_vessel,
    list_enforcement_cases,
    list_noncompliance,
    record_inspection,
    set_clock,
    setup_vessel_with_approved_plan,
    setup_voyage_in_progress,
    validate_error,
    validate_success,
)
from test_helpers import api_client


class TestSeverityDerivation:
    def test_severity_sampling_exceedance_hits_major_threshold_exactly(self, api):
        """PRD section 3.10: "A sampling exceedance contributes 40 points, a PSC
        deficiency 30, a noncompliant determination 25, an overdue report 10, and a
        missing method 15."
        PRD section 3.10: "A score of at least 70 yields `CRITICAL`; at least 40
        yields `MAJOR`; otherwise `MINOR`. The response deadline is 30 days from
        `detected_at` for `MINOR`, 14 days for `MAJOR`, and 72 hours for `CRITICAL`."

        Design: Corner/calculations/severity_sampling_exceedance_hits_major_threshold_exactly
        """
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9100034", vessel_name="MV Curlew", voyage_number="V9403"
        )
        inspection = record_inspection(
            vessel["id"], voyage["id"], inspection_kind="FLAG_STATE", organism=15.0,
            tss=10.0, findings=["BWMS-07"], recorder_user_id="fs-rec-6",
        )
        evaluate_inspection_ok(vessel["id"], voyage["id"], inspection["id"],
                               evaluator_user_id="fs-eval-6")

        record = find_noncompliance(vessel["id"], voyage["id"],
                                    source_type="SAMPLING_EXCEEDANCE")
        # Score exactly 40 (sampling exceedance, posture OPEN, no prior escalations):
        # 40 meets the MAJOR band's inclusive lower bound.
        assert record["severity"] == "MAJOR"
        # detected at the logical clock 2026-08-01T00:00:00Z; MAJOR deadline +14 days.
        assert_timestamp_equals(record["detected_at"], "2026-08-01T00:00:00Z",
                                label="detected_at")
        assert_timestamp_equals(record["response_due_at"], "2026-08-15T00:00:00Z",
                                label="MAJOR response_due_at")


class TestSeveritySamplesPosture:
    def _setup_restricted_then_noncompliant_voyage(self):
        """Vessel held RESTRICTED by an OPEN P1 deficiency on voyage A; voyage B
        arrives with a method-less discharge stream."""
        from test_helpers import post_discharge, post_uptake, setup_psc_exceeded_deficiency

        vessel, plan = setup_vessel_with_approved_plan(
            imo_number="9000005", vessel_name="MV Eider"
        )
        voyage_a = create_voyage(vessel["id"], voyage_number="V3001")
        depart_voyage(vessel["id"], voyage_a["id"])
        setup_psc_exceeded_deficiency(vessel["id"], voyage_a["id"], organism=12.0,
                                      recorder_user_id="psc-1", evaluator_user_id="fs-1")
        posture_mid = get_vessel(vessel["id"])["compliance_posture"]

        voyage_b = create_voyage(vessel["id"], voyage_number="V3002",
                                 arrived_at="2026-08-10T00:00:00Z")
        depart_voyage(vessel["id"], voyage_b["id"])
        post_uptake(vessel["id"], voyage_b["id"], tank_id="T1", volume_m3=400, salinity_ppt=32.0)
        post_discharge(vessel["id"], voyage_b["id"], tank_id="T1", volume_m3=400,
                       occurred_at="2026-07-29T06:00:00Z")
        return vessel, voyage_b, posture_mid

    def test_posture_restricted_from_open_p1_deficiency(self, api, vessel_master_headers):
        """PRD section 2.8: "Otherwise it is `RESTRICTED` when at least one
        priority-one port state control deficiency is in `OPEN`, `RECTIFYING`,
        `RECTIFIED`, or `REOPENED` status, or when a `CRITICAL` noncompliance record
        detected within the last 180 days is not yet `CLOSED`."
        PRD section 3.3: "If the basis is `NONCOMPLIANT_MIXED` or
        `NONCOMPLIANT_NO_METHOD`, or any `OPEN` noncompliance record for the voyage
        has severity `MAJOR` or `CRITICAL`, the voyage transitions to `NONCOMPLIANT`"

        Design: Difficulty/combinatorial_formula/severity_derivation_samples_posture_before_self_reference
        """
        vessel, voyage_b, posture_mid = self._setup_restricted_then_noncompliant_voyage()
        assert posture_mid == "RESTRICTED", "P1 deficiency OPEN after evaluate"

        resp = api.arrive_voyage(vessel["id"], voyage_b["id"],
                                 {"arrived_at": "2026-08-10T00:00:00Z"}, vessel_master_headers)
        arrived = validate_success(resp, 200)
        # Basis NONCOMPLIANT_NO_METHOD (attributed discharge, no method).
        assert arrived["compliance_status"] == "NONCOMPLIANT"

    def test_arrival_noncompliant_under_restricted_posture_yields_major(
            self, api, vessel_master_headers):
        """PRD section 3.10: "a noncompliant determination 25"
        PRD section 3.10: "if the vessel's posture was `RESTRICTED` at detection time,
        15 more."
        PRD section 3.10: "A score of at least 70 yields `CRITICAL`; at least 40
        yields `MAJOR`; otherwise `MINOR`. The response deadline is 30 days from
        `detected_at` for `MINOR`, 14 days for `MAJOR`, and 72 hours for `CRITICAL`."
        PRD section 3.3: "a noncompliance record with `source_type`
        `DETERMINATION_NONCOMPLIANT` is created if one is not already present"

        Design: Difficulty/combinatorial_formula/severity_derivation_samples_posture_before_self_reference
        """
        vessel, voyage_b, posture_mid = self._setup_restricted_then_noncompliant_voyage()
        assert posture_mid == "RESTRICTED"

        resp = api.arrive_voyage(vessel["id"], voyage_b["id"],
                                 {"arrived_at": "2026-08-10T00:00:00Z"}, vessel_master_headers)
        validate_success(resp, 200)

        record = find_noncompliance(vessel["id"], voyage_b["id"],
                                    source_type="DETERMINATION_NONCOMPLIANT")
        # Score 25 + 15 (RESTRICTED at detection) = 40, exactly the MAJOR threshold.
        assert record["severity"] == "MAJOR"
        # detected at the logical clock 2026-08-01T00:00:00Z; MAJOR deadline +14 days.
        assert_timestamp_equals(record["response_due_at"], "2026-08-15T00:00:00Z",
                                label="MAJOR response_due_at")


class TestRespondDeadline:
    def test_noncompliance_respond_after_deadline_returns_409(self, api, shore_officer_headers):
        """PRD section 3.10: "Response by a `ShoreComplianceOfficer` moves the record
        from `OPEN` to `RESPONDED`, provided the response arrives by
        `response_due_at`; the vessel's `version` increments."
        PRD section 3.10: "an `OPEN` record escalates when more than 7 days have
        passed since `response_due_at`"
        PRD section 2.5: "An attempt to invoke a state transition that the target
        entity's current state does not permit is rejected with `ERR_INVALID_STATE`
        (HTTP 409)"

        Design: Corner/state_machines/noncompliance_respond_after_deadline_returns_409
        """
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9100024", vessel_name="MV Oystercatcher", voyage_number="V9304",
            arrived_at="2026-08-10T00:00:00Z",
        )
        # due_at 2026-08-09T00:00:00Z; overdue record detected 2026-08-09T00:00:01Z,
        # response_due_at 2026-09-08T00:00:01Z.
        set_clock("2026-08-09T00:00:01Z")
        # One second past the response deadline, but not yet past due+7d (so the
        # record is still OPEN, not escalated).
        set_clock("2026-09-08T00:00:02Z")

        record = find_noncompliance(vessel["id"], voyage["id"], source_type="REPORT_OVERDUE")
        assert record["response_status"] == "OPEN"

        resp = api.respond_noncompliance(vessel["id"], voyage["id"], record["id"],
                                         shore_officer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestOverdueEscalationCascade:
    def _setup_escalated(self):
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9000009", vessel_name="MV Ibis", voyage_number="V5001",
            arrived_at="2026-08-10T00:00:00Z",
        )
        # Report left DRAFT; due 2026-08-09T00:00:00Z.
        set_clock("2026-08-09T00:00:01Z")  # OVERDUE; MINOR record, due +30d
        # Past response_due_at (2026-09-08T00:00:01Z) + 7 days = 2026-09-15T00:00:01Z.
        set_clock("2026-09-15T00:00:02Z")
        return vessel, voyage

    def test_overdue_record_escalates_and_creates_active_case(self, api, shore_officer_headers):
        """PRD section 3.10: "Escalation is system-driven: an `OPEN` record escalates
        when more than 7 days have passed since `response_due_at`, or when a
        `CRITICAL` record has gone 24 hours without response. Escalation creates an
        enforcement case if none is active (otherwise attaching to the existing active
        case), sets the record's `escalated_to_case_id`, sets the vessel's
        `active_enforcement_case_id`, and flips the vessel's posture to `FROZEN` if
        the case's `hold_flag` is true, otherwise `RESTRICTED`."
        PRD section 3.10: "The response deadline is 30 days from `detected_at` for
        `MINOR`, 14 days for `MAJOR`, and 72 hours for `CRITICAL`."

        Design: Difficulty/transitive_cascade/overdue_escalation_cascade_record_to_case_to_vessel
        """
        vessel, voyage = self._setup_escalated()
        record = find_noncompliance(vessel["id"], voyage["id"], source_type="REPORT_OVERDUE")
        # MINOR: detected 2026-08-09T00:00:01Z + 30 days.
        assert_timestamp_equals(record["response_due_at"], "2026-09-08T00:00:01Z",
                                label="MINOR response_due_at")
        assert record["response_status"] == "ESCALATED"

        case = get_single_case(vessel["id"])
        assert_enforcement_case(case)
        assert case["status"] == "ACTIVE"
        assert record["escalated_to_case_id"] == case["id"], (
            "escalation must link the record to the case it created"
        )

    def test_escalation_stamps_vessel_case_link_and_restricted_posture(
            self, api, shore_officer_headers):
        """PRD section 3.10: "Escalation creates an enforcement case if none is active
        (otherwise attaching to the existing active case), sets the record's
        `escalated_to_case_id`, sets the vessel's `active_enforcement_case_id`, and
        flips the vessel's posture to `FROZEN` if the case's `hold_flag` is true,
        otherwise `RESTRICTED`."

        Design: Difficulty/transitive_cascade/overdue_escalation_cascade_record_to_case_to_vessel
        """
        vessel, voyage = self._setup_escalated()
        case = get_single_case(vessel["id"])

        refreshed = get_vessel(vessel["id"])
        assert refreshed["active_enforcement_case_id"] == case["id"]
        # The escalated case carries no hold, so the posture lands on RESTRICTED.
        assert refreshed["compliance_posture"] == "RESTRICTED"


class TestEnforcementCloseBranchGate:
    def _setup_under_review_case_with_escalated_record(self):
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9000021", vessel_name="MV Uria", voyage_number="V8003",
            arrived_at="2026-08-10T00:00:00Z",
        )
        set_clock("2026-08-09T00:00:01Z")
        set_clock("2026-09-15T00:00:02Z")
        case = get_single_case(vessel["id"])
        resp = api_client.submit_case_response(vessel["id"], case["id"],
                                               TEST_USERS["shore_officer_headers"])
        validate_success(resp, 200)
        return vessel, case

    def test_close_compliant_blocked_by_escalated_linked_record(self, api,
                                                                flag_surveyor_headers):
        """PRD section 3.11: "Closing as `CLOSED_COMPLIANT` requires every linked
        noncompliance record to be `CLOSED`."
        PRD section 2.5: "An attempt to invoke a state transition that the target
        entity's current state does not permit is rejected with `ERR_INVALID_STATE`
        (HTTP 409)"

        Design: Difficulty/cross_entity_state_dependency/enforcement_close_compliant_blocked_by_open_records
        """
        vessel, case = self._setup_under_review_case_with_escalated_record()
        # The linked record is ESCALATED (terminal), never CLOSED.
        resp = api.close_case(vessel["id"], case["id"], {"penalty_assessed": False},
                              flag_surveyor_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_close_with_penalty_succeeds_and_clears_vessel_case(self, api,
                                                                flag_surveyor_headers,
                                                                shore_officer_headers):
        """PRD section 3.11: "Closure by a `FlagSurveyor` moves the case from
        `UNDER_REVIEW` to `CLOSED_COMPLIANT` — or to `CLOSED_PENALTY` when the closure
        request carries `penalty_assessed` true."
        PRD section 3.11: "Either closure stamps `closed_at`, clears the vessel's
        `active_enforcement_case_id`, and recomputes the vessel's posture."
        PRD section 2.8: "Otherwise the vessel is `OPEN`."

        Design: Difficulty/cross_entity_state_dependency/enforcement_close_compliant_blocked_by_open_records
        """
        vessel, case = self._setup_under_review_case_with_escalated_record()

        blocked = api.close_case(vessel["id"], case["id"], {"penalty_assessed": False},
                                 flag_surveyor_headers)
        validate_error(blocked, ApiErrorId.ERR_INVALID_STATE)

        resp = api.close_case(vessel["id"], case["id"], {"penalty_assessed": True},
                              flag_surveyor_headers)
        closed = validate_success(resp, 200)
        assert closed["status"] == "CLOSED_PENALTY"

        refreshed = get_vessel(vessel["id"])
        assert refreshed["active_enforcement_case_id"] is None
        # The ESCALATED record is MINOR: neither priority-one-deficiency nor recent
        # CRITICAL holds, so the rollup lands back on OPEN.
        assert refreshed["compliance_posture"] == "OPEN"


class TestWithdrawLegality:
    def test_enforcement_withdraw_from_under_review_returns_409(self, api,
                                                                flag_surveyor_headers):
        """PRD section 3.11: "Withdrawal by a `FlagSurveyor` moves an `ACTIVE` case to
        `WITHDRAWN`, likewise stamping `closed_at`, clearing
        `active_enforcement_case_id`, and recomputing posture."
        PRD section 2.5: "An attempt to invoke a state transition that the target
        entity's current state does not permit is rejected with `ERR_INVALID_STATE`
        (HTTP 409)"

        Design: Corner/state_machines/enforcement_withdraw_from_under_review_returns_409
        """
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9100028", vessel_name="MV Sandpiper", voyage_number="V9307",
            arrived_at="2026-08-10T00:00:00Z",
        )
        set_clock("2026-08-09T00:00:01Z")
        set_clock("2026-09-15T00:00:02Z")
        case = get_single_case(vessel["id"])
        resp = api.submit_case_response(vessel["id"], case["id"],
                                        TEST_USERS["shore_officer_headers"])
        validate_success(resp, 200)

        resp = api.withdraw_case(vessel["id"], case["id"], flag_surveyor_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        current = get_single_case(vessel["id"])
        assert current["status"] == "UNDER_REVIEW", (
            "rejected withdraw must leave the case UNDER_REVIEW"
        )


class TestCriticalEscalationBoundary:
    def _setup_critical_record(self):
        """Voyage A escalates a MINOR overdue record (creates the ACTIVE case);
        voyage B escalates its own MINOR record into the same case, then a sampling
        exceedance on B is detected while a prior record on B is ESCALATED and the
        vessel is RESTRICTED: score 40 + 25 + 15 = 80 -> CRITICAL."""
        vessel, plan = setup_vessel_with_approved_plan(
            imo_number="9100068", vessel_name="MV Stint"
        )
        voyage_a = create_voyage(vessel["id"], voyage_number="V9801",
                                 arrived_at="2026-08-10T00:00:00Z")
        depart_voyage(vessel["id"], voyage_a["id"])
        voyage_b = create_voyage(vessel["id"], voyage_number="V9802",
                                 arrived_at="2026-08-03T00:00:00Z")

        set_clock("2026-08-09T00:00:01Z")  # A's report overdue (due 2026-08-09)
        set_clock("2026-09-15T00:00:02Z")  # A's record escalates; case ACTIVE
        depart_voyage(vessel["id"], voyage_b["id"])
        set_clock("2026-09-15T00:00:03Z")  # B's report overdue (due 2026-08-02)
        set_clock("2026-10-22T00:00:04Z")  # B's record escalates into the same case

        inspection = record_inspection(
            vessel["id"], voyage_b["id"], inspection_kind="FLAG_STATE", organism=20.0,
            tss=10.0, sampled_at="2026-10-20T00:00:00Z", findings=["BWMS-14"],
            recorder_user_id="fs-rec-8",
        )
        evaluate_inspection_ok(vessel["id"], voyage_b["id"], inspection["id"],
                               evaluator_user_id="fs-eval-8")
        return vessel, voyage_b

    def test_critical_record_derives_score_80_and_72h_deadline(self, api):
        """PRD section 3.10: "A sampling exceedance contributes 40 points, a PSC
        deficiency 30, a noncompliant determination 25, an overdue report 10, and a
        missing method 15. If the voyage already has a prior noncompliance record that
        escalated, 25 more points are added; if the vessel's posture was `RESTRICTED`
        at detection time, 15 more. A score of at least 70 yields `CRITICAL`; at least
        40 yields `MAJOR`; otherwise `MINOR`. The response deadline is 30 days from
        `detected_at` for `MINOR`, 14 days for `MAJOR`, and 72 hours for `CRITICAL`."

        Design: Corner/cross_cutting_layers/critical_record_escalates_after_24h_boundary
        """
        vessel, voyage_b = self._setup_critical_record()
        record = find_noncompliance(vessel["id"], voyage_b["id"],
                                    source_type="SAMPLING_EXCEEDANCE")
        # Score 40 + 25 (prior ESCALATED on the voyage) + 15 (RESTRICTED) = 80 >= 70.
        assert record["severity"] == "CRITICAL"
        assert record["response_status"] == "OPEN"
        # detected 2026-10-22T00:00:04Z + 72 hours.
        assert_timestamp_equals(record["response_due_at"], "2026-10-25T00:00:04Z",
                                label="CRITICAL response_due_at")

    def test_critical_record_escalates_just_after_24h_without_response(self, api):
        """PRD section 3.10: "Escalation is system-driven: an `OPEN` record escalates
        when more than 7 days have passed since `response_due_at`, or when a
        `CRITICAL` record has gone 24 hours without response. Escalation creates an
        enforcement case if none is active (otherwise attaching to the existing active
        case), sets the record's `escalated_to_case_id`, sets the vessel's
        `active_enforcement_case_id`, and flips the vessel's posture to `FROZEN` if
        the case's `hold_flag` is true, otherwise `RESTRICTED`."

        Design: Corner/cross_cutting_layers/critical_record_escalates_after_24h_boundary
        """
        vessel, voyage_b = self._setup_critical_record()
        case = get_single_case(vessel["id"])

        # One second short of 24 hours without response: not yet "gone 24 hours".
        set_clock("2026-10-23T00:00:03Z")
        record = find_noncompliance(vessel["id"], voyage_b["id"],
                                    source_type="SAMPLING_EXCEEDANCE")
        assert record["response_status"] == "OPEN"

        # One second past the 24-hour mark: escalated, attached to the existing case.
        set_clock("2026-10-23T00:00:05Z")
        record = find_noncompliance(vessel["id"], voyage_b["id"],
                                    source_type="SAMPLING_EXCEEDANCE")
        assert record["response_status"] == "ESCALATED"
        assert record["escalated_to_case_id"] == case["id"]

        current_case = get_single_case(vessel["id"])
        assert current_case["id"] == case["id"]
        assert current_case["status"] == "ACTIVE"


class TestClearanceConservation:
    def _setup_escalated_case(self):
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9000028", vessel_name="MV Bufflehead", voyage_number="V9103",
            arrived_at="2026-08-10T00:00:00Z",
        )
        set_clock("2026-08-09T00:00:01Z")
        set_clock("2026-09-15T00:00:02Z")
        return vessel, voyage

    def test_escalation_disturbs_vessel_clearance(self, api, shore_officer_headers):
        """PRD section 3.10: "Escalation creates an enforcement case if none is active
        (otherwise attaching to the existing active case), sets the record's
        `escalated_to_case_id`, sets the vessel's `active_enforcement_case_id`, and
        flips the vessel's posture to `FROZEN` if the case's `hold_flag` is true,
        otherwise `RESTRICTED`."
        PRD section 3.1: "A newly registered vessel starts with `version` 1 and
        `compliance_posture` `OPEN`."

        Design: Difficulty/compensating_invariant/escalation_close_conserves_vessel_clearance
        """
        vessel, voyage = self._setup_escalated_case()
        refreshed = get_vessel(vessel["id"])
        assert refreshed["active_enforcement_case_id"] is not None
        assert refreshed["compliance_posture"] == "RESTRICTED", (
            "the forward escalation action disturbs the OPEN clearance baseline"
        )

    def test_penalty_closure_restores_vessel_clearance(self, api, shore_officer_headers,
                                                       flag_surveyor_headers):
        """PRD section 3.11: "Either closure stamps `closed_at`, clears the vessel's
        `active_enforcement_case_id`, and recomputes the vessel's posture."
        PRD section 3.12: "The server runs on a logical clock that starts at
        2026-08-01T00:00:00Z and never falls back to wall-clock time."
        PRD section 2.8: "Otherwise the vessel is `OPEN`."

        Design: Difficulty/compensating_invariant/escalation_close_conserves_vessel_clearance
        """
        vessel, voyage = self._setup_escalated_case()
        case = get_single_case(vessel["id"])

        resp = api.submit_case_response(vessel["id"], case["id"], shore_officer_headers)
        validate_success(resp, 200)
        resp = api.close_case(vessel["id"], case["id"], {"penalty_assessed": True},
                              flag_surveyor_headers)
        closed = validate_success(resp, 200)
        assert closed["status"] == "CLOSED_PENALTY"
        assert_timestamp_equals(closed["closed_at"], "2026-09-15T00:00:02Z",
                                label="closed_at")

        refreshed = get_vessel(vessel["id"])
        assert refreshed["active_enforcement_case_id"] is None
        assert refreshed["compliance_posture"] == "OPEN", (
            "the compensating close-out must conserve vessel clearance"
        )
