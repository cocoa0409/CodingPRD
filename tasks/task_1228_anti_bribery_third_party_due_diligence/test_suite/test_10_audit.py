"""Audit rights: notice window, half-open overlap, findings cascade, close gate."""
import pytest

from test_helpers import (
    ApiErrorId,
    FINANCE_1_ID,
    audit_headers,
    create_audit,
    create_payment,
    get_third_party,
    officer_headers,
    set_clock,
    setup_active_contract,
    setup_audit_in_fieldwork,
    setup_third_party_in_state,
    validate_error,
    validate_success,
)
from test_helpers.test_users import SPONSOR_1_ID


class TestFieldworkWindowOverlap:
    def _setup_party_with_audit_a(self, api):
        ctx = setup_third_party_in_state("APPROVED", "CH", 80)
        tp_id = ctx["third_party"]["id"]
        aud_a = create_audit(tp_id, "2026-05-15", "2026-05-30")
        return tp_id, aud_a

    def test_adjacent_window_allowed(self, api, audit_headers):
        """PRD §3.9: "Fieldwork windows are half-open, including their start date
        and excluding their end date, and a new window conflicts with an existing
        `NOTICED` or `IN_FIELDWORK` window for the same party when the proposed
        start falls before the existing window's end and the existing window's
        start falls before the proposed end — windows that merely touch, where
        the proposed start equals an existing end, do not conflict. A conflicting
        create fails with `ERR_AUDIT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/audit_fieldwork_half_open_overlap_and_adjacency
        """
        tp_id, _ = self._setup_party_with_audit_a(api)
        # [2026-05-30, 2026-06-10) touches [2026-05-15, 2026-05-30) at one endpoint.
        resp = api.create_audit_exercise(
            tp_id, {"fieldwork_start_date": "2026-05-30",
                    "fieldwork_end_date": "2026-06-10"}, audit_headers)
        data = validate_success(resp, 201)
        assert data["audit_status"] == "NOTICED"

    def test_overlapping_window_rejected(self, api, audit_headers):
        """PRD §3.9: "Fieldwork windows are half-open, including their start date
        and excluding their end date, and a new window conflicts with an existing
        `NOTICED` or `IN_FIELDWORK` window for the same party when the proposed
        start falls before the existing window's end and the existing window's
        start falls before the proposed end — windows that merely touch, where
        the proposed start equals an existing end, do not conflict. A conflicting
        create fails with `ERR_AUDIT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/audit_fieldwork_half_open_overlap_and_adjacency
        """
        tp_id, _ = self._setup_party_with_audit_a(api)
        # [2026-05-29, 2026-06-05) intersects [2026-05-15, 2026-05-30).
        resp = api.create_audit_exercise(
            tp_id, {"fieldwork_start_date": "2026-05-29",
                    "fieldwork_end_date": "2026-06-05"}, audit_headers)
        validate_error(resp, ApiErrorId.ERR_AUDIT_WINDOW_OVERLAP)


class TestNoticeWindowBoundary:
    def test_audit_notice_window_ten_day_boundary(self, api, audit_headers, admin_headers):
        """PRD §3.9: "The start date must be at least ten calendar days after the
        notice date — the boundary is inclusive, so exactly ten days later is
        legal — or the create fails with `ERR_AUDIT_NOTICE_TOO_SHORT`; the end
        date must be strictly later than the start date or the payload is
        `ERR_VALIDATION`."
        PRD §3.9: "Beginning fieldwork moves the exercise to `IN_FIELDWORK` and
        is gated on the same ten-day notice measured against the logical clock:
        the current date must be at least `notice_date` plus ten days, inclusive,
        else `ERR_AUDIT_NOTICE_TOO_SHORT`."

        Design: Corner/calculations/audit_notice_window_ten_day_boundary
        """
        ctx = setup_third_party_in_state("APPROVED", "CH", 80)
        tp_id = ctx["third_party"]["id"]

        # notice_date = current date 2026-05-01; notice + 10 days = 2026-05-11.
        too_short = api.create_audit_exercise(
            tp_id, {"fieldwork_start_date": "2026-05-10",
                    "fieldwork_end_date": "2026-05-20"}, audit_headers)
        validate_error(too_short, ApiErrorId.ERR_AUDIT_NOTICE_TOO_SHORT)

        ok = validate_success(
            api.create_audit_exercise(
                tp_id, {"fieldwork_start_date": "2026-05-11",
                        "fieldwork_end_date": "2026-05-20"}, audit_headers), 201)
        assert ok["audit_status"] == "NOTICED", "exactly notice+10 is legal (inclusive)"

        set_clock("2026-05-10T00:00:00Z")
        early = api.begin_fieldwork(ok["id"], audit_headers)
        validate_error(early, ApiErrorId.ERR_AUDIT_NOTICE_TOO_SHORT)

        set_clock("2026-05-11T00:00:00Z")
        begun = validate_success(api.begin_fieldwork(ok["id"], audit_headers), 200)
        assert begun["audit_status"] == "IN_FIELDWORK", "notice+10 inclusive at begin"


class TestFindingsCascadeToTermination:
    def _setup_findings_issued(self, api):
        """APPROVED party + ACTIVE contract + one SUBMITTED payment; audit in
        fieldwork; findings issued with 1 substantiated critical."""
        ctx = setup_third_party_in_state("APPROVED", "CH", 80)
        tp_id = ctx["third_party"]["id"]
        contract = setup_active_contract(tp_id, SPONSOR_1_ID, value_cents=500000)
        pay = create_payment(contract["id"], amount_cents=50000)  # ratio 10.00
        audit = setup_audit_in_fieldwork(tp_id, "2026-05-15", "2026-05-30", "2026-05-15")
        issued = validate_success(
            api.issue_findings(audit["id"],
                               {"findings_total": 3, "findings_substantiated_critical": 1},
                               audit_headers()), 200)
        return ctx, tp_id, contract, pay, audit, issued

    def test_issue_findings_fires_cascade(self, api, officer_headers):
        """PRD §3.9: "When `findings_substantiated_critical` is at least one, the
        familiar cascade fires: a `CRITICAL` red flag is created with
        `source_type` `AUDIT` and `source_ref_id` pointing at the exercise, the
        flag auto-escalates to `UNDER_ENHANCED_REVIEW` with an `ENHANCED_DD` case
        whose `escalated_by_user_id` is null, and the party drops from `APPROVED`
        to `SUSPENDED` or from `SCREENING` or `DD_REVIEW` to `ENHANCED_REVIEW`."

        Design: Difficulty/transitive_cascade/audit_findings_to_termination_cascade
        """
        _, tp_id, _, _, audit, issued = self._setup_findings_issued(api)
        assert issued["audit_status"] == "FINDINGS_ISSUED"

        assert get_third_party(tp_id)["onboarding_status"] == "SUSPENDED"

        flags = validate_success(api.list_red_flags(tp_id, officer_headers), 200)
        assert flags[0]["source_type"] == "AUDIT"
        assert flags[0]["source_ref_id"] == audit["id"]
        assert flags[0]["flag_status"] == "UNDER_ENHANCED_REVIEW"

        cases = validate_success(api.list_escalation_cases(tp_id, officer_headers), 200)
        assert cases[0]["case_status"] == "ENHANCED_DD"
        assert cases[0]["escalated_by_user_id"] is None, (
            "auto-escalation: any officer may decide"
        )

    def test_decide_terminate_runs_full_cascade(self, api, officer_headers, finance_headers):
        """PRD §3.5: "`TERMINATE` substantiates the linked flags and moves the
        party to `TERMINATED` with the full termination cascade described below."
        PRD §3.5: "Termination, from `APPROVED` or `SUSPENDED` — whether by
        officer action with an optional `reason`, by an escalation decision of
        `TERMINATE`, or by a re-diligence completion of `TERMINATE` — fires the
        full cascade: every contract of the party in `DRAFT`, `PENDING_CLAUSES`,
        or `ACTIVE` moves to `TERMINATED`; every payment request still
        `SUBMITTED` on those contracts moves to `BLOCKED`; every gift entry still
        `PENDING_APPROVAL` moves to `REJECTED`; and the party's `version`
        increments by one."

        Design: Difficulty/transitive_cascade/audit_findings_to_termination_cascade
        """
        _, tp_id, contract, pay, _, _ = self._setup_findings_issued(api)
        cases = validate_success(api.list_escalation_cases(tp_id, officer_headers), 200)
        case_id = cases[0]["id"]

        decided = validate_success(
            api.decide_escalation_case(case_id, {"outcome": "TERMINATE"},
                                       officer_headers), 200)
        assert decided["case_status"] == "DECIDED"

        assert get_third_party(tp_id)["onboarding_status"] == "TERMINATED"
        after = validate_success(api.get_contract(contract["id"], officer_headers), 200)
        assert after["contract_status"] == "TERMINATED"

        payments = validate_success(api.list_payment_requests(contract["id"],
                                                              finance_headers), 200)
        by_id = {p["id"]: p for p in payments}
        assert by_id[pay["id"]]["payment_status"] == "BLOCKED"

        flags = validate_success(api.list_red_flags(tp_id, officer_headers), 200)
        assert flags[0]["flag_status"] == "SUBSTANTIATED"


class TestCloseGate:
    def test_audit_close_with_pending_flags_rejected(self, api, audit_headers,
                                                     officer_headers):
        """PRD §3.9: "Closing the exercise requires every red flag spawned by it
        to have reached `CLEARED` or `SUBSTANTIATED`; while any remains `OPEN` or
        `UNDER_ENHANCED_REVIEW`, the close fails with `ERR_FINDINGS_PENDING`."
        PRD §3.5: "`APPROVE_WITH_CONDITIONS` clears the linked flags to `CLEARED`
        and restores the third party — from `ENHANCED_REVIEW` back to `DD_REVIEW`,
        or from `SUSPENDED` back to `APPROVED`."

        Design: Corner/validations/audit_close_with_pending_flags_rejected
        """
        ctx = setup_third_party_in_state("APPROVED", "CH", 80)
        tp_id = ctx["third_party"]["id"]
        audit = setup_audit_in_fieldwork(tp_id, "2026-05-15", "2026-05-30", "2026-05-15")
        validate_success(
            api.issue_findings(audit["id"],
                               {"findings_total": 2, "findings_substantiated_critical": 1},
                               audit_headers), 200)

        blocked = api.close_audit(audit["id"], audit_headers)
        validate_error(blocked, ApiErrorId.ERR_FINDINGS_PENDING)

        cases = validate_success(api.list_escalation_cases(tp_id, officer_headers), 200)
        validate_success(
            api.decide_escalation_case(
                cases[0]["id"],
                {"outcome": "APPROVE_WITH_CONDITIONS",
                 "conditions_note": "remediation plan on file"},
                officer_headers), 200)

        closed = validate_success(api.close_audit(audit["id"], audit_headers), 200)
        assert closed["audit_status"] == "CLOSED"
        assert get_third_party(tp_id)["onboarding_status"] == "APPROVED"
