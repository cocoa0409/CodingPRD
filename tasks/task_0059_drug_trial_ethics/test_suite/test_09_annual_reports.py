"""Annual reports, safety alert flag, continuing-review.

PRD §3.7.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    SEC,
    api_client,
    assert_annual_report,
    create_annual_report,
    create_annual_report_payload,
    get_application,
    list_annual_reports,
    make_applicant_headers,
    setup_application_pending_review,
    setup_resolved_initial_review,
    validate_error,
    validate_success,
)


# ===========================================================================
# AnnualReport creation requires APPROVED parent (PRD §3.7)
# ===========================================================================
class TestAnnualReportParentState:
    """PRD §3.7: 'Each report carries an application_id (which must
    reference an application in one of those two states)' — referring to
    APPROVED or APPROVED_WITH_MOD."""

    def test_cannot_create_annual_report_on_pending_review_app(self, api):
        """PRD §3.7: 'Each report carries an application_id (which must
        reference an application in one of those two states)' —
        APPROVED or APPROVED_WITH_MOD. A PENDING_REVIEW application is
        not in those states."""
        app, _ = setup_application_pending_review()
        res = api.create_annual_report(
            app["id"],
            create_annual_report_payload(),
            make_applicant_headers(app["applicant_id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_can_create_annual_report_on_approved_app(self, api):
        """PRD §3.7: 'Once an application is in APPROVED or
        APPROVED_WITH_MOD, the Applicant must periodically file an
        AnnualReport'."""
        bundle = setup_resolved_initial_review(
            vote_split={"APPROVE": 5, "APPROVE_WITH_MODIFICATION": 2},
            member_count=9,
        )
        app = bundle["application"]
        report = create_annual_report(
            app,
            serious_adverse_event_count=0,
            total_adverse_event_count=0,
            enrollment_count=10,
        )
        assert_annual_report(report)
        assert report["status"] == "SUBMITTED", (
            f"PRD §3.7: 'The new report enters SUBMITTED status'; got "
            f"{report['status']!r}"
        )


# ===========================================================================
# Field invariants (PRD §3.7)
# ===========================================================================
class TestAnnualReportFieldInvariants:
    """PRD §3.7: 'a serious_adverse_event_count that must be
    non-negative, a total_adverse_event_count that must be greater than
    or equal to the serious count, and an enrollment_count of subjects
    enrolled in the period (must be non-negative). Violations of these
    integer invariants — a negative count, a count that exceeds its own
    total, or a malformed datetime — are rejected with
    ERR_FIELD_VALIDATION.'"""

    def test_negative_sae_rejected(self, api):
        """PRD §3.7: 'serious_adverse_event_count that must be
        non-negative ... a negative count ... rejected with
        ERR_FIELD_VALIDATION.'"""
        bundle = setup_resolved_initial_review(
            vote_split={"APPROVE": 5, "APPROVE_WITH_MODIFICATION": 2},
            member_count=9,
        )
        app = bundle["application"]
        res = api.create_annual_report(
            app["id"],
            create_annual_report_payload(
                serious_adverse_event_count=-1,
            ),
            make_applicant_headers(app["applicant_id"]),
        )
        validate_error(res, ApiErrorId.ERR_FIELD_VALIDATION.value)

    def test_sae_exceeds_total_rejected(self, api):
        """PRD §3.7: 'total_adverse_event_count that must be greater
        than or equal to the serious count ... a count that exceeds its
        own total ... rejected with ERR_FIELD_VALIDATION.'"""
        bundle = setup_resolved_initial_review(
            vote_split={"APPROVE": 5, "APPROVE_WITH_MODIFICATION": 2},
            member_count=9,
        )
        app = bundle["application"]
        res = api.create_annual_report(
            app["id"],
            create_annual_report_payload(
                serious_adverse_event_count=5,
                total_adverse_event_count=4,
            ),
            make_applicant_headers(app["applicant_id"]),
        )
        validate_error(res, ApiErrorId.ERR_FIELD_VALIDATION.value)

    def test_negative_enrollment_rejected(self, api):
        """PRD §3.7: 'enrollment_count ... must be non-negative.'"""
        bundle = setup_resolved_initial_review(
            vote_split={"APPROVE": 5, "APPROVE_WITH_MODIFICATION": 2},
            member_count=9,
        )
        app = bundle["application"]
        res = api.create_annual_report(
            app["id"],
            create_annual_report_payload(
                enrollment_count=-1,
            ),
            make_applicant_headers(app["applicant_id"]),
        )
        validate_error(res, ApiErrorId.ERR_FIELD_VALIDATION.value)


# ===========================================================================
# Safety alert flag (PRD §3.7)
# ===========================================================================
class TestSafetyAlertFlag:
    """PRD §3.7: 'The safety_alert_flag is set true when either of two
    threshold conditions holds. The first condition is that the
    serious_adverse_event_count is at least 3 serious events in the
    period; the boundary is inclusive, so exactly 3 SAEs is enough to
    raise the flag. The second condition is computed only when
    enrollment_count is strictly greater than zero: the observed
    adverse-event rate, defined as total_adverse_event_count divided by
    enrollment_count, is at or above 0.20 (twenty percent).'"""

    def test_safety_alert_true_at_exactly_3_serious(self, api):
        """PRD §3.7: 'serious_adverse_event_count is at least 3 serious
        events in the period; the boundary is inclusive, so exactly 3
        SAEs is enough to raise the flag.'"""
        bundle = setup_resolved_initial_review(
            vote_split={"APPROVE": 5, "APPROVE_WITH_MODIFICATION": 2},
            member_count=9,
        )
        app = bundle["application"]
        report = create_annual_report(
            app,
            serious_adverse_event_count=3,
            total_adverse_event_count=3,
            enrollment_count=10,
        )
        assert report["safety_alert_flag"] is True, (
            f"PRD §3.7: exactly 3 SAEs raises the flag; got "
            f"{report.get('safety_alert_flag')!r}"
        )

    def test_safety_alert_false_at_2_serious_and_low_rate(self, api):
        """PRD §3.7: 'serious_adverse_event_count is at least 3' (the
        boundary is 3, not 2)."""
        bundle = setup_resolved_initial_review(
            vote_split={"APPROVE": 5, "APPROVE_WITH_MODIFICATION": 2},
            member_count=9,
        )
        app = bundle["application"]
        report = create_annual_report(
            app,
            serious_adverse_event_count=2,
            total_adverse_event_count=2,
            enrollment_count=20,
        )
        assert report["safety_alert_flag"] is False, (
            f"PRD §3.7: 2 SAEs and rate 0.10 → False; got "
            f"{report.get('safety_alert_flag')!r}"
        )

    def test_safety_alert_true_at_exactly_20_percent_rate(self, api):
        """PRD §3.7: 'the observed adverse-event rate ... is at or above
        0.20 (twenty percent) ... a rate of exactly 0.20 raises the
        flag.'"""
        bundle = setup_resolved_initial_review(
            vote_split={"APPROVE": 5, "APPROVE_WITH_MODIFICATION": 2},
            member_count=9,
        )
        app = bundle["application"]
        # 2 SAEs (below 3), but 4/20 = 0.20 rate → flag true.
        report = create_annual_report(
            app,
            serious_adverse_event_count=2,
            total_adverse_event_count=4,
            enrollment_count=20,
        )
        assert report["safety_alert_flag"] is True, (
            f"PRD §3.7: 'a rate of exactly 0.20 raises the flag'; got "
            f"{report.get('safety_alert_flag')!r}"
        )

    def test_safety_alert_false_when_enrollment_zero_and_few_sae(self, api):
        """PRD §3.7: 'The second condition is computed only when
        enrollment_count is strictly greater than zero'."""
        bundle = setup_resolved_initial_review(
            vote_split={"APPROVE": 5, "APPROVE_WITH_MODIFICATION": 2},
            member_count=9,
        )
        app = bundle["application"]
        report = create_annual_report(
            app,
            serious_adverse_event_count=0,
            total_adverse_event_count=0,
            enrollment_count=0,
        )
        assert report["safety_alert_flag"] is False, (
            f"PRD §3.7: with enrollment 0 and SAE 0, no condition "
            f"holds; got {report.get('safety_alert_flag')!r}"
        )
