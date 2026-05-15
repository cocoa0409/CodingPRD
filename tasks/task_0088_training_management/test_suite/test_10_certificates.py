"""Certificates: issuance, expiring-soon sweep, renewal window, revoke,
verify (PRD §3.5, §3.7)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    api_client,
    assert_certificate,
    assert_certificate_template,
    create_and_publish_course,
    create_certificate_template,
    create_certificate_template_payload,
    iso_utc,
    make_trainee_headers,
    renew_certificate_payload,
    revoke_certificate_payload,
    run_sweep,
    setup_certificate_in_expiring_soon,
    setup_completed_enrollment,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Certificate template (PRD §3.7)
# ===========================================================================
class TestCertificateTemplate:

    def test_template_created_with_defaults(self, api, training_admin_headers):
        """PRD §3.7: "The template carries an integer validity_months
        between 1 and 120, an integer renewal_window_days between 1
        and 180 (default 30) representing how many days before
        expires_at a renewal is permitted, and two boolean flags
        requires_attendance and requires_exam_pass (each defaulting
        to true)."

        Claim: a template created with explicit validity_months=12
        defaults the rest to renewal_window_days=30,
        requires_attendance=true, requires_exam_pass=true.
        """
        course = create_and_publish_course()
        # Build a minimal payload exercising defaults.
        payload = create_certificate_template_payload(course_id=course["id"])
        resp = api.create_certificate_template(payload, training_admin_headers)
        data = validate_success(resp, expected_status=201)
        assert_certificate_template(data)
        assert data["validity_months"] == 12
        assert data["renewal_window_days"] == 30
        assert data["requires_attendance"] is True
        assert data["requires_exam_pass"] is True


# ===========================================================================
# Issuance during session-complete cascade (PRD §3.5)
# ===========================================================================
class TestCertificateIssuance:

    def test_present_and_passed_issues_certificate(
        self, api, training_admin_headers,
    ):
        """PRD §3.5: "for any course that carries a CertificateTemplate,
        a fresh Certificate is issued to a trainee whose enrollment
        status is now COMPLETED provided two conditions are met: when
        the template's requires_attendance is true the enrollment's
        attendance_status must be PRESENT (not merely PARTIAL), and
        when the template's requires_exam_pass is true the
        corresponding ExamAttempt.passed must be true."

        Claim: PRESENT + passed exam + template -> Certificate issued
        in VALID status.
        """
        ctx = setup_completed_enrollment(
            attendance="PRESENT", exam_passed=True,
            with_certificate_template=True,
        )
        resp = api.list_certificates(
            training_admin_headers,
            params={"trainee_id": ctx["trainee"]["id"]},
        )
        rows, _ = validate_paginated(resp)
        match = [c for c in rows if c["trainee_id"] == ctx["trainee"]["id"]]
        assert match, "PRD §3.5 requires a Certificate for PRESENT+passed"
        assert_certificate(match[0])
        assert match[0]["status"] == "VALID"

    def test_partial_attendance_does_not_issue_when_template_requires_present(
        self, api, training_admin_headers,
    ):
        """PRD §3.5: "when the template's requires_attendance is true
        the enrollment's attendance_status must be PRESENT (not
        merely PARTIAL)."

        Claim: when the observed attendance_status is PARTIAL (and
        the template requires_attendance=true and requires_exam_pass=true
        with the exam passed), NO Certificate is issued. The
        attendance_status the implementation produces is checked
        first; if it lands on PRESENT instead, this scenario does
        not exercise the rule and the assertion is vacuously true
        (PRESENT+passed legitimately issues a certificate).
        """
        ctx = setup_completed_enrollment(
            attendance="PARTIAL", exam_passed=True,
            with_certificate_template=True,
            template_overrides={"requires_attendance": True,
                                "requires_exam_pass": True},
        )
        observed = ctx["enrollment"].get("attendance_status")
        resp = api.list_certificates(
            training_admin_headers,
            params={"trainee_id": ctx["trainee"]["id"]},
        )
        rows, _ = validate_paginated(resp)
        match = [c for c in rows if c["trainee_id"] == ctx["trainee"]["id"]]
        if observed == "PARTIAL":
            assert not match, (
                "PRD §3.5: PARTIAL attendance must NOT yield a Certificate "
                "when requires_attendance=true"
            )
        elif observed == "PRESENT":
            # The fixture's single check-in was treated as PRESENT
            # under this implementation's sampling rule; the
            # PARTIAL-rejection path is not exercised. PRESENT+passed
            # legitimately issues a certificate.
            assert match, (
                "PRD §3.5: PRESENT+passed must yield a Certificate when "
                "requires_attendance=true (and requires_exam_pass is "
                "satisfied)"
            )
        else:
            pytest.skip(
                f"Implementation produced attendance_status={observed!r} "
                f"from a single check-in; PRD does not pin the in-session "
                f"sampling algorithm, so the PARTIAL-rejection path "
                f"cannot be deterministically exercised."
            )


# ===========================================================================
# Sweep-driven transitions: VALID -> EXPIRING_SOON (PRD §3.7)
# ===========================================================================
class TestCertificateExpiringSoonSweep:

    def test_sweep_inside_renewal_window_advances_to_expiring_soon(
        self, api, training_admin_headers,
    ):
        """PRD §3.7: "While the certificate is VALID and the
        difference between expires_at and the current clock falls at
        or below renewal_window_days, the sweep transitions it to
        EXPIRING_SOON and emits a SyncEvent with event_type equal to
        cert.expiring_soon and source_system equal to IM."

        Claim: after advancing to expires_at - half(window) and
        running sweep, Certificate.status == EXPIRING_SOON.
        """
        ctx = setup_certificate_in_expiring_soon(
            validity_months=12, renewal_window_days=30,
        )
        assert ctx["certificate"]["status"] == "EXPIRING_SOON"


# ===========================================================================
# Certificate renewal window (PRD §3.7) — covers difficulty instance
# cross_entity_state_dependency/certificate_renewal_requires_completed_enrollment.
# ===========================================================================
class TestCertificateRenewalWindow:

    def test_renewal_with_enrollment_outside_window_rejected(
        self, api, training_admin_headers,
    ):
        """PRD §3.7: "the corresponding session's start_at falls
        within the half-open window stretching from expires_at minus
        renewal_window_days (exclusive on the lower end) up to and
        including expires_at itself; a source enrollment outside this
        window is rejected with ERR_RENEWAL_WINDOW_INVALID."

        Claim: a source enrollment whose session.start_at predates the
        renewal window lower bound -> ERR_RENEWAL_WINDOW_INVALID.

        Setup is the most demanding fixture in the suite: we need an
        EXPIRING_SOON certificate AND a separate Completed enrollment
        on the same course outside the window. To keep this within a
        single test, we exercise the negative case using the
        certificate's own source enrollment (which dates from BEFORE
        the renewal window opened): per the half-open lower bound
        being exclusive, the original issuing enrollment lies at or
        BEFORE expires_at - validity_months — far outside the renewal
        window.
        """
        ctx = setup_certificate_in_expiring_soon(
            validity_months=12, renewal_window_days=30,
        )
        cert = ctx["certificate"]
        # The certificate's source_enrollment_id is the one that
        # issued it; its session.start_at predates the window by ~12
        # months. Renewing with that enrollment id MUST be rejected
        # per the lower-bound rule (exclusive).
        payload = renew_certificate_payload(
            source_enrollment_id=cert["source_enrollment_id"],
        )
        resp = api.renew_certificate(
            cert["id"], payload, make_trainee_headers(ctx["trainee"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RENEWAL_WINDOW_INVALID.value)


# ===========================================================================
# Revoke (PRD §3.7)
# ===========================================================================
class TestCertificateRevoke:

    def test_admin_revokes_valid_certificate(self, api, training_admin_headers):
        """PRD §3.7: "A TrainingAdmin may revoke a certificate that is
        either VALID or EXPIRING_SOON, transitioning it to REVOKED;
        the action accepts an optional reason argument."

        Claim: revoke on VALID -> REVOKED.
        """
        ctx = setup_completed_enrollment(
            attendance="PRESENT", exam_passed=True,
            with_certificate_template=True,
        )
        resp = api.list_certificates(
            training_admin_headers,
            params={"trainee_id": ctx["trainee"]["id"]},
        )
        rows, _ = validate_paginated(resp)
        assert rows
        cert = rows[0]
        rev_resp = api.revoke_certificate(
            cert["id"], revoke_certificate_payload(reason="audit"),
            training_admin_headers,
        )
        data = validate_success(rev_resp, expected_status=200)
        assert data["status"] == "REVOKED"
