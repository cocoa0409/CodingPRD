"""Section 1 attestation and Section 2 signing — state transitions,
segregation of duties, and the deadline-enforcement flag.

Covers PRD §3.3 (Section 1 / Section 2 lifecycle), §2.1 (segregation
of duties), and the deadline flag.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    advance_clock_to,
    api_client,
    assert_audit_action_present,
    assert_i9_form,
    attest_section1,
    create_employee,
    create_i9_form,
    list_audit_events,
    make_employee_headers,
    make_employer_rep_headers,
    register_list_a_document,
    section1_payload,
    section2_payload,
    setup_employee_with_section2_done,
    TEST_USERS,
    EMPLOYER_REP_SHARED_ID,
    validate_error,
    validate_success,
)


# ===========================================================================
# Section 1 — PRD §3.3
# ===========================================================================
class TestSection1Attestation:

    def test_section1_attest_transitions_draft_to_section1_done(
            self, api):
        """PRD §3.3: "On success the form transitions from `DRAFT` to
        `SECTION_1_DONE`: `section1_completed_at` is stamped with
        `SystemClock.current_time`, `section1_attested_by_user_id` is
        set to `X-User-ID`"."""
        emp = create_employee()
        form = create_i9_form(employee_id=emp["id"], form_kind="INITIAL")
        resp = api.attest_section1(
            emp["id"], form["id"],
            section1_payload(version=form["version"]),
            make_employee_headers(emp["id"]),
        )
        signed = validate_success(resp, expected_status=200)
        assert_i9_form(signed)
        assert signed["form_status"] == "SECTION_1_DONE"
        assert signed["section1_attested_by_user_id"] == emp["id"]
        assert signed["section1_completed_at"] is not None

    def test_section1_attest_by_non_owner_employee_returns_forbidden(
            self, api):
        """PRD §3.3: "This step is exclusive to the `Employee` role,
        and `X-User-ID` must equal the `Employee.id` — a non-owner
        Employee attempt is rejected with `ERR_FORBIDDEN`"."""
        emp = create_employee()
        other_emp = create_employee()
        form = create_i9_form(employee_id=emp["id"], form_kind="INITIAL")
        # Use another Employee's id as X-User-ID — fails ownership check.
        resp = api.attest_section1(
            emp["id"], form["id"],
            section1_payload(version=form["version"]),
            make_employee_headers(other_emp["id"]),
        )
        validate_error(resp, "ERR_FORBIDDEN")

    def test_section1_attest_emits_audit_event(self, api):
        """PRD §2.8: "Every state transition and every business-
        significant mutation produces an `AuditEvent`."

        Claim: SECTION_1_ATTEST AuditEvent is present after attestation.
        """
        emp = create_employee()
        form = create_i9_form(employee_id=emp["id"], form_kind="INITIAL")
        attest_section1(employee_id=emp["id"], form_id=form["id"])
        events = list_audit_events(emp["id"])
        assert_audit_action_present(events, "SECTION_1_ATTEST")


# ===========================================================================
# Section 2 — PRD §3.3
# ===========================================================================
class TestSection2Signing:

    def test_section2_with_list_a_passport_succeeds(self, api,
                                                    employer_rep_headers):
        """PRD §3.3: "On a successful transition the system stamps
        `section2_completed_at` with the current time, records
        `section2_completed_by_user_id` from `X-User-ID`, computes
        `reverification_due`, appends an `AuditEvent` whose `action` is
        `SECTION_2_SIGN`, and moves `onboarding_status` to
        `EVERIFY_PENDING`"."""
        advance_clock_to("2026-05-30T08:00:00.000Z")
        emp = create_employee(start_date="2026-06-01")
        form = create_i9_form(employee_id=emp["id"], form_kind="INITIAL")
        form = attest_section1(employee_id=emp["id"], form_id=form["id"])
        doc = register_list_a_document(employee_id=emp["id"])
        advance_clock_to("2026-06-02T08:00:00.000Z")
        resp = api.sign_section2(
            emp["id"], form["id"],
            section2_payload(
                version=form["version"],
                list_a_document_id=doc["id"],
            ),
            employer_rep_headers,
        )
        signed = validate_success(resp, expected_status=200)
        assert signed["form_status"] == "SECTION_2_DONE"
        assert signed["section2_completed_at"] is not None
        assert signed["section2_completed_by_user_id"] == EMPLOYER_REP_SHARED_ID
        # PRD §3.7: status moves to EVERIFY_PENDING.
        events = list_audit_events(emp["id"])
        assert_audit_action_present(events, "SECTION_2_SIGN")

    def test_section2_by_section1_attester_returns_err_segregation_of_duties(
            self, api):
        """PRD §2.1: "an `EmployerRep` who signs Section 2 with the
        same `X-User-ID` as the `Employee` who attested Section 1 is
        rejected with `ERR_SEGREGATION_OF_DUTIES`"."""
        advance_clock_to("2026-05-30T08:00:00.000Z")
        emp = create_employee(start_date="2026-06-01")
        form = create_i9_form(employee_id=emp["id"], form_kind="INITIAL")
        form = attest_section1(employee_id=emp["id"], form_id=form["id"])
        doc = register_list_a_document(employee_id=emp["id"])
        advance_clock_to("2026-06-02T08:00:00.000Z")
        # Pass the employee's id as the EmployerRep operator id.
        resp = api.sign_section2(
            emp["id"], form["id"],
            section2_payload(
                version=form["version"],
                list_a_document_id=doc["id"],
            ),
            make_employer_rep_headers(emp["id"]),
        )
        validate_error(resp, "ERR_SEGREGATION_OF_DUTIES")

    def test_section2_late_without_enforce_succeeds_with_audit_flag(
            self, api, employer_rep_headers):
        """PRD §3.3: "When the flag is omitted or false, late Section 2
        sign is permitted: the transition still executes, the form
        moves to `SECTION_2_DONE`, and an `AuditEvent` with action
        `SECTION_2_LATE` is appended alongside the regular Section 2
        audit row to flag the lateness."

        Claim: SECTION_2_LATE audit is recorded when current_time >
        section2_deadline and enforce_deadline is omitted.
        """
        advance_clock_to("2026-05-30T08:00:00.000Z")
        emp = create_employee(start_date="2026-06-01")
        # section2_deadline = 2026-06-04T23:59:59.999Z
        form = create_i9_form(employee_id=emp["id"], form_kind="INITIAL")
        form = attest_section1(employee_id=emp["id"], form_id=form["id"])
        doc = register_list_a_document(employee_id=emp["id"])
        # Advance past the deadline.
        advance_clock_to("2026-06-08T08:00:00.000Z")
        resp = api.sign_section2(
            emp["id"], form["id"],
            section2_payload(
                version=form["version"],
                list_a_document_id=doc["id"],
            ),
            employer_rep_headers,
        )
        signed = validate_success(resp, expected_status=200)
        assert signed["form_status"] == "SECTION_2_DONE"
        events = list_audit_events(emp["id"])
        assert_audit_action_present(events, "SECTION_2_LATE")
        assert_audit_action_present(events, "SECTION_2_SIGN")

    def test_section2_late_with_enforce_returns_err_section2_deadline_missed(
            self, api, employer_rep_headers):
        """PRD §3.3: "When `enforce_deadline` is true and
        `SystemClock.current_time` is strictly later than the employee's
        `section2_deadline`, the request is rejected with
        `ERR_SECTION2_DEADLINE_MISSED`"."""
        advance_clock_to("2026-05-30T08:00:00.000Z")
        emp = create_employee(start_date="2026-06-01")
        form = create_i9_form(employee_id=emp["id"], form_kind="INITIAL")
        form = attest_section1(employee_id=emp["id"], form_id=form["id"])
        doc = register_list_a_document(employee_id=emp["id"])
        # Advance strictly past deadline 2026-06-04T23:59:59.999Z.
        advance_clock_to("2026-06-05T00:00:00.000Z")
        resp = api.sign_section2(
            emp["id"], form["id"],
            section2_payload(
                version=form["version"],
                list_a_document_id=doc["id"],
                enforce_deadline=True,
            ),
            employer_rep_headers,
        )
        validate_error(resp, "ERR_SECTION2_DEADLINE_MISSED")

    def test_section2_with_no_list_documents_returns_list_rule(
            self, api, employer_rep_headers):
        """PRD §3.3: "Any other combination ... is rejected with
        `ERR_DOCUMENT_LIST_RULE`"; empty document set is not one of
        the two valid combinations.

        Difficulty: boundary_precision_check / empty_document_set_on_section2.
        """
        advance_clock_to("2026-05-30T08:00:00.000Z")
        emp = create_employee(start_date="2026-06-01")
        form = create_i9_form(employee_id=emp["id"], form_kind="INITIAL")
        form = attest_section1(employee_id=emp["id"], form_id=form["id"])
        advance_clock_to("2026-06-02T08:00:00.000Z")
        # Body omits all list ids entirely.
        resp = api.sign_section2(
            emp["id"], form["id"],
            section2_payload(version=form["version"]),
            employer_rep_headers,
        )
        validate_error(resp, "ERR_DOCUMENT_LIST_RULE")


# ===========================================================================
# Re-signing Section 2 → invalid state — PRD §2.9 priority order
# ===========================================================================
class TestSection2InvalidState:

    def test_second_section2_sign_on_already_signed_form_returns_invalid_state(
            self, api, employer_rep_secondary_headers):
        """PRD §2.9: "fifth, the target resource must be in a state
        from which the requested transition is permitted
        (`ERR_INVALID_STATE`)".

        Claim: re-signing a SECTION_2_DONE form → ERR_INVALID_STATE.
        """
        emp, form, doc = setup_employee_with_section2_done()
        # Use a different EmployerRep operator (not the attester) so
        # segregation of duties cannot fire — the state check should
        # win regardless via PRD §2.9 priority (state P5 < SoD P6).
        resp = api.sign_section2(
            emp["id"], form["id"],
            section2_payload(
                version=form["version"],
                list_a_document_id=doc["id"],
            ),
            employer_rep_secondary_headers,
        )
        validate_error(resp, "ERR_INVALID_STATE")
