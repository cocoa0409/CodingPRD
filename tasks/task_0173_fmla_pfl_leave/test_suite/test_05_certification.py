"""Medical certification lifecycle — submission, review, cure cycle.

Covers PRD §3.3 (cert_deadline), §3.5 (certification workflow).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    add_days,
    assert_medical_certification,
    create_certification_payload,
    get_leave_case,
    make_employee_headers,
    review_certification,
    setup_pending_certification_case,
    submit_certification,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ===========================================================================
# Submission — PRD §3.5
# ===========================================================================
class TestCertificationSubmission:

    def test_submit_certification_returns_pending_outcome(self, api):
        """PRD §3.5: "A `MedicalCertification` row also records its own
        `review_outcome` which begins at `PENDING`"."""
        _e, _w, employee, case = setup_pending_certification_case(
            reason="OWN_SERIOUS_HEALTH",
        )
        cert = submit_certification(
            leave_case_id=case["id"], employee_id=employee["id"],
            serious_health_condition=True,
        )
        assert_medical_certification(cert)
        assert cert["review_outcome"] == "PENDING"

    def test_submission_flips_parent_certification_status_to_received(
        self, api,
    ):
        """PRD §3.5: "Submitting a certification flips the parent case's
        `certification_status` to `RECEIVED`"."""
        _e, _w, employee, case = setup_pending_certification_case(
            reason="OWN_SERIOUS_HEALTH",
        )
        submit_certification(
            leave_case_id=case["id"], employee_id=employee["id"],
            serious_health_condition=True,
        )
        refreshed = get_leave_case(case["id"])
        assert refreshed["certification_status"] == "RECEIVED", (
            f"PRD §3.5: certification_status flips to RECEIVED on cert "
            f"submission; got {refreshed['certification_status']!r}"
        )


# ===========================================================================
# Review — PRD §3.5
# ===========================================================================
class TestCertificationReview:

    def test_accept_flips_review_outcome_and_parent_status(self, api):
        """PRD §3.5: "An `ACCEPT` decision is allowed only when the
        certification's `serious_health_condition` is true and the
        parent case's `certification_status` is `RECEIVED`; on success
        `review_outcome` becomes `ACCEPTED` and the parent case's
        `certification_status` becomes `COMPLETE`"."""
        _e, _w, employee, case = setup_pending_certification_case(
            reason="OWN_SERIOUS_HEALTH",
        )
        cert = submit_certification(
            leave_case_id=case["id"], employee_id=employee["id"],
            serious_health_condition=True,
        )
        result = review_certification(
            leave_case_id=case["id"], cert_id=cert["id"],
            decision="ACCEPT",
        )
        assert result["review_outcome"] == "ACCEPTED"
        refreshed = get_leave_case(case["id"])
        assert refreshed["certification_status"] == "COMPLETE", (
            f"PRD §3.5: parent certification_status -> COMPLETE on "
            f"ACCEPT; got {refreshed['certification_status']!r}"
        )

    def test_insufficient_flips_outcome_and_parent_status_to_insufficient(
        self, api,
    ):
        """PRD §3.5: "A decision of `INSUFFICIENT` ... on success
        `review_outcome` becomes `INSUFFICIENT`, the parent
        `certification_status` becomes `INSUFFICIENT`"."""
        _e, _w, employee, case = setup_pending_certification_case(
            reason="OWN_SERIOUS_HEALTH",
        )
        cert = submit_certification(
            leave_case_id=case["id"], employee_id=employee["id"],
            serious_health_condition=True,
        )
        result = review_certification(
            leave_case_id=case["id"], cert_id=cert["id"],
            decision="INSUFFICIENT",
        )
        assert result["review_outcome"] == "INSUFFICIENT"
        refreshed = get_leave_case(case["id"])
        assert refreshed["certification_status"] == "INSUFFICIENT"

    def test_reject_flips_outcome_to_rejected_and_parent_to_insufficient(
        self, api,
    ):
        """PRD §3.5: "on a `REJECT`, `review_outcome` becomes `REJECTED`
        and the parent `certification_status` becomes `INSUFFICIENT`"."""
        _e, _w, employee, case = setup_pending_certification_case(
            reason="OWN_SERIOUS_HEALTH",
        )
        # PRD §3.5: REJECT is reserved for serious_health_condition==false.
        cert = submit_certification(
            leave_case_id=case["id"], employee_id=employee["id"],
            serious_health_condition=False,
        )
        result = review_certification(
            leave_case_id=case["id"], cert_id=cert["id"],
            decision="REJECT",
        )
        assert result["review_outcome"] == "REJECTED"
        refreshed = get_leave_case(case["id"])
        assert refreshed["certification_status"] == "INSUFFICIENT"


# ===========================================================================
# Cure cycle — PRD §3.5
# ===========================================================================
class TestCureCycle:

    def test_cure_submission_creates_new_pending_row_preserves_old(self, api):
        """PRD §3.5: "the cure ... creates a new `MedicalCertification`
        row beginning at `PENDING`, with the previous `INSUFFICIENT`
        row preserved"."""
        _e, _w, employee, case = setup_pending_certification_case(
            reason="OWN_SERIOUS_HEALTH",
        )
        cert1 = submit_certification(
            leave_case_id=case["id"], employee_id=employee["id"],
            serious_health_condition=True,
        )
        review_certification(
            leave_case_id=case["id"], cert_id=cert1["id"],
            decision="INSUFFICIENT",
        )
        # Cure: re-submit a new certification.
        cert2 = submit_certification(
            leave_case_id=case["id"], employee_id=employee["id"],
            serious_health_condition=True,
        )
        assert cert2["id"] != cert1["id"], (
            "Cure must create a NEW MedicalCertification row, not "
            "mutate the prior INSUFFICIENT row"
        )
        assert cert2["review_outcome"] == "PENDING"


# ===========================================================================
# cert_deadline pinning — PRD §3.3
# ===========================================================================
class TestCertDeadline:

    def test_cert_deadline_is_creation_plus_15_days(self, api):
        """PRD §3.3: "The `cert_deadline` is set to the case's creation
        timestamp plus 15 calendar days"."""
        _e, _w, _emp, case = setup_pending_certification_case()
        # cert_deadline = created_at + 15 days.
        expected = add_days(case["created_at"], 15)
        assert case["cert_deadline"] == expected, (
            f"cert_deadline must be created_at + 15 days "
            f"({expected!r}); got {case['cert_deadline']!r}"
        )
