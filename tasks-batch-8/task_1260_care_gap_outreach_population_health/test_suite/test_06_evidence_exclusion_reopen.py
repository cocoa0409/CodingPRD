"""Closure evidence, exclusion requests, and reconciliation reopen claims
(PRD §3.6, §3.7, §3.8)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId,
    setup_panel_scenario, create_registry, create_member, advance_clock,
    get_care_gap, submit_evidence, approve_evidence, close_gap_via_evidence,
    book_appointment, create_exclusion, start_review_exclusion,
    setup_exclusion_under_review, create_report, get_report,
    create_exclusion_request_payload,
    make_admin_headers, make_panel_manager_headers,
    make_quality_reviewer_headers, make_reconciliation_bot_headers,
)

PM = "pm_1"
QR = "qr_1"


class TestEvidenceWindow:
    def test_evidence_out_of_window_rejected(self, api):
        """PRD §3.6: "Approval is exclusive to `QualityReviewer` and enforces three
        checks in order: the evidence must be `SUBMITTED`; segregation of duties
        forbids the approver's `X-User-ID` from matching the submitter's, failing
        with `ERR_SOD_VIOLATION` (HTTP 403); and the `service_date` must fall inside
        the measure's lookback window — a service date older than
        `current_business_date` minus the measure's `lookback_days` fails with
        `ERR_EVIDENCE_OUT_OF_WINDOW`."

        service_date 2024-01-01 is older than 2026-05-01 minus 365 days.

        Design: Corner/validations/evidence_out_of_window_rejected
        """
        scenario = setup_panel_scenario(num_members=1)
        gap_id = scenario["gaps"][0]["id"]
        evidence = submit_evidence(gap_id, service_date="2024-01-01T00:00:00Z",
                                   submitter_id=PM)
        resp = api.approve_evidence(evidence["id"], {},
                                    make_quality_reviewer_headers(QR))
        validate_error(resp, ApiErrorId.ERR_EVIDENCE_OUT_OF_WINDOW)


class TestReopenCycle:
    def test_care_gap_closed_reopened_cycle(self, api):
        """PRD §3.8: "Only a gap that is `CLOSED` and whose `closure_source` is
        `CLAIMS_FEED` is eligible — reconciliation may not disturb evidence- or
        appointment-derived closures, and an ineligible state fails with
        `ERR_INVALID_STATE`."
        PRD §3.8: "A successful reopen sets the gap to `REOPENED`, clears its
        `closure_source` to null, increments the member's `open_gap_count` by one".

        Design: Difficulty/non_linear_state_machine/care_gap_closed_reopened_cycle
        """
        scenario = setup_panel_scenario(num_members=1, reporting_lag_days=30)
        gap_id = scenario["gaps"][0]["id"]
        close_gap_via_evidence(gap_id, evidence_type="CLAIMS_FEED")
        resp = api.reopen_care_gap(gap_id, {"reason": "claims mismatch"},
                                   make_reconciliation_bot_headers())
        data = validate_success(resp, 200)
        assert data["status"] == "REOPENED", f"Expected REOPENED, got {data['status']}"
        assert data.get("closure_source") is None, (
            f"Reopen must clear closure_source to null, got {data.get('closure_source')!r}")

    def test_reopen_rejected_for_evidence_closed_gap(self, api):
        """PRD §3.8: "Only a gap that is `CLOSED` and whose `closure_source` is
        `CLAIMS_FEED` is eligible — reconciliation may not disturb evidence- or
        appointment-derived closures, and an ineligible state fails with
        `ERR_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/care_gap_closed_reopened_cycle
        """
        scenario = setup_panel_scenario(num_members=1, reporting_lag_days=30)
        gap_id = scenario["gaps"][0]["id"]
        close_gap_via_evidence(gap_id, evidence_type="CHART_REVIEW")
        resp = api.reopen_care_gap(gap_id, {"reason": "not claims"},
                                   make_reconciliation_bot_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_reopen_after_window_rejected(self, api):
        """PRD §3.8: "The reconciliation window must still be open: the clock must
        not have reached the gap's `due_date` plus the measure's `reporting_lag_days`,
        otherwise the reopen fails with `ERR_RECONCILIATION_WINDOW_CLOSED`."

        Design: Corner/endpoints/reopen_after_window_rejected
        """
        scenario = setup_panel_scenario(num_members=1, reporting_lag_days=30)
        gap_id = scenario["gaps"][0]["id"]
        close_gap_via_evidence(gap_id, evidence_type="CLAIMS_FEED")
        # due_date 2026-05-01 + 30 days = 2026-05-31; the clock is well past it.
        advance_clock(scenario["registry"]["id"], "2027-08-01T00:00:00Z")
        resp = api.reopen_care_gap(gap_id, {"reason": "late claim"},
                                   make_reconciliation_bot_headers())
        validate_error(resp, ApiErrorId.ERR_RECONCILIATION_WINDOW_CLOSED)


class TestExclusionCascade:
    def test_exclusion_approve_cascades_to_excluded_gaps(self, api):
        """PRD §3.7: "Approval takes optional `notes`, transitions every care gap for
        the member that matches the measure (or all of the member's gaps when
        `measure_id` is null) and currently sits in `OPEN` or `OUTREACH_IN_PROGRESS`
        to `EXCLUDED`, cancels any appointment in `SCHEDULED` or `CONFIRMED` attached
        to those gaps, decrements the member's `open_gap_count` by the number of gaps
        transitioned, and decrements the `PROVISIONAL` report denominator."

        Design: Corner/state_machines/exclusion_approve_cascades_to_excluded_gaps
        """
        scenario = setup_panel_scenario(num_members=1)
        member = scenario["members"][0]
        gap_id = scenario["gaps"][0]["id"]
        exclusion = setup_exclusion_under_review(member["id"],
                                                 scenario["measure"]["id"],
                                                 submitter_id=PM, reviewer_id=QR)
        resp = api.approve_exclusion(exclusion["id"], {},
                                     make_quality_reviewer_headers("qr_2"))
        validate_success(resp, 200)
        member_after = get_success_data(api.get_member(member["id"], make_admin_headers()))
        assert member_after["open_gap_count"] == 0, (
            f"Expected open_gap_count 0 after exclusion, got {member_after['open_gap_count']}")
        gap_after = get_care_gap(gap_id)
        assert gap_after["status"] == "EXCLUDED", (
            f"Expected EXCLUDED gap, got {gap_after['status']}")

    def test_medical_exclusion_requires_long_justification(self, api):
        """PRD §3.7: "When the kind is `MEDICAL_CONTRAINDICATION`, the justification
        must be at least 20 characters long, failing with
        `ERR_INSUFFICIENT_JUSTIFICATION` (HTTP 400) otherwise."

        Design: Corner/validations/medical_exclusion_requires_long_justification
        """
        registry = create_registry(name="R-J")
        member = create_member(registry["id"])
        resp = api.create_exclusion_request(
            member["id"],
            create_exclusion_request_payload(
                exclusion_kind="MEDICAL_CONTRAINDICATION", justification="short"),
            make_admin_headers())
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_JUSTIFICATION)


class TestExclusionSafetyVersusReferential:
    def _scenario_with_active_appointment_and_exclusion(self, api):
        scenario = setup_panel_scenario(num_members=1)
        pm = scenario["panel_manager_id"]
        member = scenario["members"][0]
        # Book an appointment: the gap moves to AWAITING_APPOINTMENT with a
        # SCHEDULED appointment referencing the gap for this measure.
        book_appointment(scenario["gaps"][0]["id"], panel_manager_id=pm)
        exclusion = create_exclusion(member["id"], measure_id=scenario["measure"]["id"],
                                     submitter_id=pm)
        start_review_exclusion(exclusion["id"], reviewer_id=QR)
        return scenario, member, exclusion

    def test_exclusion_safety_vs_referential(self, api):
        """PRD §3.7: "Approval runs its checks in order: the request must be
        `UNDER_REVIEW`; segregation of duties forbids the approver being the
        submitter, failing with `ERR_SOD_VIOLATION`; and the member must have no
        appointment in `SCHEDULED` or `CONFIRMED` referencing a care gap for the
        measure in question, failing with `ERR_EXCLUSION_BLOCKED_BY_APPOINTMENT` — a
        booked appointment must be resolved before the member can be excluded."

        The approver's X-User-ID equals the submitter's AND an active appointment
        exists; segregation of duties is evaluated first.

        Design: Difficulty/priority_pair_validation_conflict/exclusion_safety_vs_referential
        """
        scenario, member, exclusion = self._scenario_with_active_appointment_and_exclusion(api)
        submitter_id = scenario["panel_manager_id"]  # pm_1 submitted the request
        resp = api.approve_exclusion(
            exclusion["id"], {},
            make_quality_reviewer_headers(submitter_id))
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)

    def test_exclusion_blocked_by_active_appointment(self, api):
        """PRD §3.7: "Approval runs its checks in order: the request must be
        `UNDER_REVIEW`; segregation of duties forbids the approver being the
        submitter, failing with `ERR_SOD_VIOLATION`; and the member must have no
        appointment in `SCHEDULED` or `CONFIRMED` referencing a care gap for the
        measure in question, failing with `ERR_EXCLUSION_BLOCKED_BY_APPOINTMENT` — a
        booked appointment must be resolved before the member can be excluded."

        A different reviewer approves while a SCHEDULED appointment references the
        member's gap for this measure.

        Design: Difficulty/priority_pair_validation_conflict/exclusion_safety_vs_referential
        """
        scenario, member, exclusion = self._scenario_with_active_appointment_and_exclusion(api)
        resp = api.approve_exclusion(
            exclusion["id"], {},
            make_quality_reviewer_headers("qr_2"))
        validate_error(resp, ApiErrorId.ERR_EXCLUSION_BLOCKED_BY_APPOINTMENT)


class TestDenominatorConservation:
    def test_exclusion_approve_revoke_conserves_denominator(self, api):
        """PRD §3.7: "Approval takes optional `notes`, transitions every care gap for
        the member that matches the measure (or all of the member's gaps when
        `measure_id` is null) and currently sits in `OPEN` or `OUTREACH_IN_PROGRESS`
        to `EXCLUDED`, cancels any appointment in `SCHEDULED` or `CONFIRMED` attached
        to those gaps, decrements the member's `open_gap_count` by the number of gaps
        transitioned, and decrements the `PROVISIONAL` report denominator."
        PRD §3.7: "the request moves to `REVOKED`, every gap the original approval
        had excluded reverts from `EXCLUDED` to `OPEN`, the member's `open_gap_count`
        is incremented back, the `PROVISIONAL` denominator is restored, and each
        restored gap's `priority_score` is recomputed."

        Design: Difficulty/compensating_invariant/exclusion_approve_revoke_conserves_denominator
        """
        scenario = setup_panel_scenario(num_members=1)
        member = scenario["members"][0]
        report = create_report(scenario["measure"]["id"], period_key="2026-06")
        denom_pre = report["denominator_count"]
        assert denom_pre == 1, f"Expected denominator 1, got {denom_pre}"
        exclusion = setup_exclusion_under_review(member["id"],
                                                 scenario["measure"]["id"],
                                                 submitter_id=PM, reviewer_id=QR)
        get_success_data(api.approve_exclusion(exclusion["id"], {},
                                               make_quality_reviewer_headers("qr_2")))
        get_success_data(api.revoke_exclusion(exclusion["id"],
                                              {"reason": "member re-engaged"},
                                              make_quality_reviewer_headers("qr_2")))
        report_after = get_report(report["id"])
        assert report_after["denominator_count"] == denom_pre, (
            f"Denominator must be conserved across approve->revoke: "
            f"{denom_pre} -> {report_after['denominator_count']}")

    def test_exclusion_revoke_restores_gap_to_open(self, api):
        """PRD §3.7: "the request moves to `REVOKED`, every gap the original approval
        had excluded reverts from `EXCLUDED` to `OPEN`, the member's `open_gap_count`
        is incremented back, the `PROVISIONAL` denominator is restored, and each
        restored gap's `priority_score` is recomputed."

        Design: Difficulty/compensating_invariant/exclusion_approve_revoke_conserves_denominator
        """
        scenario = setup_panel_scenario(num_members=1)
        member = scenario["members"][0]
        gap_id = scenario["gaps"][0]["id"]
        exclusion = setup_exclusion_under_review(member["id"],
                                                 scenario["measure"]["id"],
                                                 submitter_id=PM, reviewer_id=QR)
        get_success_data(api.approve_exclusion(exclusion["id"], {},
                                               make_quality_reviewer_headers("qr_2")))
        gap_mid = get_care_gap(gap_id)
        assert gap_mid["status"] == "EXCLUDED"
        get_success_data(api.revoke_exclusion(exclusion["id"], {"reason": "re-engaged"},
                                              make_quality_reviewer_headers("qr_2")))
        gap_after = get_care_gap(gap_id)
        assert gap_after["status"] == "OPEN", (
            f"Revoked exclusion must revert the gap to OPEN, got {gap_after['status']}")
        member_after = get_success_data(api.get_member(member["id"], make_admin_headers()))
        assert member_after["open_gap_count"] == 1, (
            f"open_gap_count must be restored to 1, got {member_after['open_gap_count']}")


class TestMemberOpenGapCount:
    def test_derived_field_reconciliation_member_open_gap_count(self, api):
        """PRD §3.3: "The member's denormalized `open_gap_count` tracks how many of
        that member's gaps sit in `OPEN`, `OUTREACH_IN_PROGRESS`,
        `AWAITING_APPOINTMENT`, or `PENDING_EVIDENCE`."
        PRD §3.6: "the member's `open_gap_count` decrements by one" (on closure).
        PRD §3.8: "A successful reopen sets the gap to `REOPENED`, clears its
        `closure_source` to null, increments the member's `open_gap_count` by one".

        Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_member_open_gap_count
        """
        scenario = setup_panel_scenario(num_members=1, reporting_lag_days=30)
        member_id = scenario["members"][0]["id"]
        gap_id = scenario["gaps"][0]["id"]

        def open_count():
            return get_success_data(api.get_member(member_id, make_admin_headers()))[
                "open_gap_count"]

        assert open_count() == 1, "One materialized OPEN gap must count once"
        close_gap_via_evidence(gap_id, evidence_type="CLAIMS_FEED")
        assert open_count() == 0, "Closure must decrement open_gap_count"
        get_success_data(api.reopen_care_gap(gap_id, {"reason": "claims mismatch"},
                                             make_reconciliation_bot_headers()))
        assert open_count() == 1, "Reopen must increment open_gap_count back"
