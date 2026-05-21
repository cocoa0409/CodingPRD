"""Audit trail completeness + the derived onboarding_status projection.

Covers PRD §2.8 (audit append-only contract, ordering, fields),
PRD §3.7 (derive_onboarding_status projection).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    advance_clock_to,
    api_client,
    assert_audit_action_present,
    assert_audit_event,
    create_employee,
    create_i9_form,
    deliver_result,
    find_audit_actions,
    get_employee,
    list_audit_events,
    setup_employee_with_employment_authorized_case,
    setup_employee_with_pending_case,
    setup_employee_with_section2_done,
    setup_employee_with_tnc_case,
    TEST_USERS,
    validate_error,
    validate_paginated,
)


# ===========================================================================
# Audit-row shape — PRD §2.8
# ===========================================================================
class TestAuditEventShape:

    def test_audit_event_carries_required_fields(self, api,
                                                hr_staff_headers):
        """PRD §2.8: "Each row records `subject_employee_id` (the
        employee the event ultimately concerns, denormalized for query),
        `subject_entity` (one of `EMPLOYEE`, `I9_FORM`, `I9_DOCUMENT`,
        `EVERIFY_CASE`, or `REVERIFICATION_EVENT`), `subject_entity_id`,
        an `action` verb code ... the `actor_role` ... the
        `actor_user_id` ... and `occurred_at`"."""
        emp = create_employee()
        events = list_audit_events(emp["id"])
        assert events, "Employee creation must produce at least 1 audit event"
        for e in events:
            assert_audit_event(e)

    def test_audit_list_is_ordered_ascending_by_occurred_at(self, api):
        """PRD §2.8: "audit reads are ordered by `occurred_at`
        ascending"."""
        emp, form, _doc = setup_employee_with_section2_done()
        events = list_audit_events(emp["id"])
        assert len(events) >= 2
        occurred = [e["occurred_at"] for e in events]
        assert occurred == sorted(occurred), (
            f"Audit events must be ordered ascending by occurred_at; "
            f"got {occurred!r}"
        )


# ===========================================================================
# Audit action coverage on Section 2 sign — PRD §3.3
# ===========================================================================
class TestAuditOnSection2:

    def test_section2_sign_emits_section2_sign_audit(self, api):
        """PRD §3.3: "appends an `AuditEvent` whose `action` is
        `SECTION_2_SIGN`"."""
        emp, form, _doc = setup_employee_with_section2_done()
        events = list_audit_events(emp["id"])
        assert_audit_action_present(events, "SECTION_2_SIGN")


# ===========================================================================
# derive_onboarding_status — PRD §3.7
# ===========================================================================
class TestOnboardingStatusDerivation:

    def test_status_pending_section_1_before_form_creation(self, api):
        """PRD §3.7: "If no such latest form exists, or the latest
        form's `form_status` is `DRAFT`, the status is
        `PENDING_SECTION_1`."."""
        emp = create_employee()
        re = get_employee(emp["id"])
        assert re["onboarding_status"] == "PENDING_SECTION_1"

    def test_status_pending_section_2_after_section1_done(self, api):
        """PRD §3.7: "If the latest form's `form_status` is
        `SECTION_1_DONE`, the status is `PENDING_SECTION_2`."."""
        from test_helpers import attest_section1
        emp = create_employee()
        form = create_i9_form(employee_id=emp["id"], form_kind="INITIAL")
        attest_section1(employee_id=emp["id"], form_id=form["id"])
        re = get_employee(emp["id"])
        assert re["onboarding_status"] == "PENDING_SECTION_2"

    def test_status_everify_pending_after_section2_done_no_case(self, api):
        """PRD §3.7: "Otherwise if no latest non-closed case exists,
        the status is `EVERIFY_PENDING` — Section 2 is done but no
        case is open yet."."""
        emp, form, _doc = setup_employee_with_section2_done()
        re = get_employee(emp["id"])
        assert re["onboarding_status"] == "EVERIFY_PENDING"

    def test_status_tnc_open_when_non_closed_case_in_tnc(self, api):
        """PRD §3.7: "If a non-closed case exists and its `case_status`
        is `TNC`, the status is `TNC_OPEN`."."""
        emp, form, case = setup_employee_with_tnc_case(
            tnc_kind="SSA",
            tnc_opened_at="2026-06-15T09:00:00.000Z",
        )
        re = get_employee(emp["id"])
        assert re["onboarding_status"] == "TNC_OPEN"

    def test_status_authorized_after_closed_authorized_case(self, api,
                                                            employer_rep_headers):
        """PRD §3.7: "the system ... reports `AUTHORIZED` when its
        `final_disposition` is `AUTHORIZED`"."""
        emp, form, case = setup_employee_with_employment_authorized_case()
        api.close_everify_case(case["id"], None, employer_rep_headers)
        re = get_employee(emp["id"])
        assert re["onboarding_status"] == "AUTHORIZED"
