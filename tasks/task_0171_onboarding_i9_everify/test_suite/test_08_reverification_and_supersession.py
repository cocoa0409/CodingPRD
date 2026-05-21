"""ReverificationEvent lifecycle, Section 3 supersession, STEM extension.

Covers PRD §3.4 (reverification due, STEM extension, OPT_TO_OPT_STEM
reverification reason), PRD §3.3 (supersession via successor Section
2 sign).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    advance_clock_to,
    api_client,
    assert_audit_action_present,
    assert_reverification_event,
    create_employee,
    get_employee,
    list_audit_events,
    list_reverification_events,
    register_ead_document,
    setup_ead_employee_with_open_reverification,
    setup_employee_for_section3_supersession,
    setup_supersession_with_ead_scenario,
    supersede_with_reverification_form,
    TEST_USERS,
    update_employee_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# WORK_AUTH_EXPIRY reverification creation at Section 2 sign — PRD §3.4
# ===========================================================================
class TestReverificationEventCreation:

    def test_ead_section2_sign_opens_work_auth_expiry_event(self, api):
        """PRD §3.4: "When `reverification_due` is non-null, the system
        creates a `ReverificationEvent` for the employee with
        `triggering_form_id` equal to the newly signed form, `reason`
        `WORK_AUTH_EXPIRY`, and a `resolution_deadline` computed by the
        reverification deadline rule below."

        Claim: F1_OPT employee with EAD I-766 expiring 2026-08-01 →
        one open ReverificationEvent with reason=WORK_AUTH_EXPIRY.
        """
        emp, form, ead, rever = (
            setup_ead_employee_with_open_reverification(
                ead_expiration_date="2026-08-01",
            )
        )
        assert_reverification_event(rever)
        assert rever["reason"] == "WORK_AUTH_EXPIRY"
        assert rever["triggering_form_id"] == form["id"]
        assert rever["new_form_id"] is None, (
            "Brand-new event must not yet have new_form_id"
        )
        assert rever["resolved_at"] is None
        # resolution_deadline = EAD expiry at 23:59:59.999Z.
        assert str(rever["resolution_deadline"]).startswith("2026-08-01"), (
            f"PRD §3.4: WORK_AUTH_EXPIRY resolution_deadline is the "
            f"triggering form's reverification_due itself; got "
            f"{rever['resolution_deadline']!r}"
        )


# ===========================================================================
# Section 3 supersession — PRD §3.3 / §3.4
# ===========================================================================
class TestSupersession:

    def test_successor_section2_supersedes_predecessor_and_resolves_event(
            self, api):
        """PRD §3.3: "If this newly-signed form has a
        `supersedes_form_id`, that predecessor form simultaneously
        transitions to state `SUPERSEDED` with its own `AuditEvent` of
        action `FORM_SUPERSEDED`, and any open `ReverificationEvent`
        whose `triggering_form_id` was the predecessor is resolved by
        setting its `resolved_at` to the new `section2_completed_at`
        and its `new_form_id` to the successor's `id`."."""
        ctx = setup_employee_for_section3_supersession()
        emp = ctx["employee"]
        initial_form_id = ctx["initial_form"]["id"]
        new_form = ctx["new_form"]
        # The supersession cascade flips the initial form's status.
        from test_helpers import list_i9_forms
        forms = list_i9_forms(emp["id"])
        initial = next(f for f in forms if f["id"] == initial_form_id)
        successor = next(f for f in forms if f["id"] == new_form["id"])
        assert initial["form_status"] == "SUPERSEDED"
        assert successor["form_status"] == "SECTION_2_DONE"
        assert successor["supersedes_form_id"] == initial_form_id
        # ReverificationEvent resolved.
        events = list_reverification_events(emp["id"])
        triggered = [
            e for e in events if e["triggering_form_id"] == initial_form_id
        ]
        assert len(triggered) == 1, (
            f"Expected exactly one ReverificationEvent triggered by the "
            f"initial form, got {len(triggered)}"
        )
        re = triggered[0]
        assert re["resolved_at"] is not None
        assert re["new_form_id"] == new_form["id"]
        # Audit trail.
        audits = list_audit_events(emp["id"])
        assert_audit_action_present(audits, "FORM_SUPERSEDED")
        assert_audit_action_present(audits, "REVERIFY_RESOLVED")


# ===========================================================================
# F1_OPT -> F1_OPT_STEM extension — PRD §3.4
# ===========================================================================
class TestStemExtension:

    def test_stem_extension_before_ead_expiry_extends_deadline_180_days(
            self, api, hr_staff_headers):
        """PRD §3.4: "When `HRStaff` updates an employee whose existing
        `visa_class` is `F1_OPT` and the new `visa_class` is
        `F1_OPT_STEM`, the system performs two actions. First, the
        existing form's `reverification_due` is recomputed: instead of
        the original EAD `expiration_date`, the system uses that
        original date plus 180 calendar days, so no new I-9 form is
        required until the extended date. Second, a `ReverificationEvent`
        is opened with `reason` `OPT_TO_OPT_STEM_EXTENSION` and
        `resolution_deadline` set per the rule above."

        Claim: PATCH visa_class F1_OPT -> F1_OPT_STEM while
        current_time <= EAD expiration_date opens a
        OPT_TO_OPT_STEM_EXTENSION event with resolution_deadline = EAD
        expiration_date + 180 calendar days.
        """
        emp, form, ead, original_rever = (
            setup_ead_employee_with_open_reverification(
                ead_expiration_date="2026-08-01",
            )
        )
        # Before EAD expiry.
        advance_clock_to("2026-07-15T08:00:00.000Z")
        re_emp = get_employee(emp["id"])
        resp = api.update_employee(
            emp["id"],
            update_employee_payload(
                version=re_emp["version"],
                visa_class="F1_OPT_STEM",
            ),
            hr_staff_headers,
        )
        validate_success(resp, expected_status=200)
        # Look for the new OPT_TO_OPT_STEM_EXTENSION event.
        events = list_reverification_events(emp["id"])
        stem_events = [
            e for e in events
            if e.get("reason") == "OPT_TO_OPT_STEM_EXTENSION"
        ]
        assert len(stem_events) >= 1, (
            f"Expected at least one OPT_TO_OPT_STEM_EXTENSION event, "
            f"got events: {events!r}"
        )
        # resolution_deadline = 2026-08-01 + 180 days = 2027-01-28T23:59:59.999Z.
        # (Aug 1 + 180 calendar days: Aug has 30 days after Aug 1 -> Aug 31;
        # then Sep 30, Oct 31, Nov 30, Dec 31 = +5 months → 2027-01-28.)
        rd = str(stem_events[0]["resolution_deadline"])
        assert rd.startswith("2027-01-28"), (
            f"PRD §3.4: STEM resolution_deadline = EAD expiry + 180 "
            f"calendar days = 2027-01-28T23:59:59.999Z; got {rd!r}"
        )

    def test_stem_extension_after_ead_expiry_returns_err_stem_extension_late(
            self, api, hr_staff_headers):
        """PRD §3.4: "This update is only allowed while
        `SystemClock.current_time` is on or before the underlying EAD's
        `expiration_date`; an attempt to STEM-extend an already-lapsed
        authorization is rejected with `ERR_STEM_EXTENSION_LATE`."

        Claim: clock past 2026-08-01 → PATCH visa_class to F1_OPT_STEM
        returns ERR_STEM_EXTENSION_LATE.
        """
        emp, form, ead, _rever = (
            setup_ead_employee_with_open_reverification(
                ead_expiration_date="2026-08-01",
            )
        )
        # Advance strictly past the EAD expiration_date.
        advance_clock_to("2026-08-02T00:00:00.000Z")
        re_emp = get_employee(emp["id"])
        resp = api.update_employee(
            emp["id"],
            update_employee_payload(
                version=re_emp["version"],
                visa_class="F1_OPT_STEM",
            ),
            hr_staff_headers,
        )
        validate_error(resp, "ERR_STEM_EXTENSION_LATE")


# ===========================================================================
# Reverification sweep expiry — PRD §3.4, §2.11
# ===========================================================================
class TestReverificationExpiry:

    def test_sweep_expires_overdue_reverification_and_terminates_employee(
            self, api):
        """PRD §3.4: "It transitions to `EXPIRED` when, during a sweep,
        `resolved_at` is still null and the current time has passed
        `resolution_deadline`. Expiry appends an `AuditEvent` with
        action `REVERIFY_EXPIRED`, cascades into the employee-termination
        subroutine (`is_terminated` becomes true, an `AuditEvent` with
        action `TERMINATE` is appended), and moves `onboarding_status`
        to `NOT_AUTHORIZED`."."""
        from test_helpers import run_sweep
        emp, form, ead, _rever = (
            setup_ead_employee_with_open_reverification(
                ead_expiration_date="2026-08-01",
            )
        )
        # Past the resolution_deadline.
        advance_clock_to("2026-08-02T00:00:01.000Z")
        run_sweep()
        re_emp = get_employee(emp["id"])
        assert re_emp["is_terminated"] is True
        # PRD §3.7: is_terminated=true → onboarding_status=TERMINATED.
        assert re_emp["onboarding_status"] == "TERMINATED"
        audits = list_audit_events(emp["id"])
        assert_audit_action_present(audits, "REVERIFY_EXPIRED")
        assert_audit_action_present(audits, "TERMINATE")
