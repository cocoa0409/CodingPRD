"""Regulatory volume reports: auto-creation by cascades, computed counts,
and the finalization window.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_regulatory_report,
    cancel_policy_effective,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx

OFFICER = TEST_USERS["compliance_officer_headers"]
UNDERWRITER = TEST_USERS["underwriter_headers"]


class TestComputedReportCounts:
    def test_computed_read_report_counts(self, api):
        """PRD §2.10: "The `cancellation_count` counts cancellation cases that
        reached `EFFECTIVE` against policies pinned to that profile whose
        `scheduled_effective_date` falls within the period. The
        `rescinded_count` counts cancellation and nonrenewal cases whose
        rescission falls within the period." and "The first cascade that
        touches a profile-and-month pair auto-creates the row in `OPEN`
        status and increments the appropriate counter; later cascades
        increment the same row."

        Design: Corner/endpoints/computed_read_report_counts
        """
        bundle = cancel_policy_effective(
            "PA",
            request_clock="2026-08-01T00:00:00Z",
            scheduled_effective_date="2026-08-20",
            mailed_on_date="2026-08-01",
            policy_number="P-PA-1",
        )
        report = fx.find_report(bundle["profile"]["id"], "2026-08")
        assert_regulatory_report(report)
        assert report["status"] == "OPEN"
        assert report["cancellation_count"] == 1
        assert report["nonrenewal_count"] == 0
        assert report["rescinded_count"] == 0

        data, _meta = validate_paginated(
            api.list_regulatory_reports(
                OFFICER, params={"state_profile_id": bundle["profile"]["id"], "report_period": "2026-07"}
            )
        )
        assert data == [], "no cascade touched July, so no July row exists"


class TestFinalizeWindow:
    def test_finalize_report_before_period_close_rejected(self, api):
        """PRD §2.10: "A `ComplianceOfficer` finalizes an `OPEN` report only
        after its period has fully closed — the current clock month must be
        later than the `report_period`, and a finalize attempted while the
        clock is still within the period is rejected with
        `ERR_REPORT_PERIOD_STILL_OPEN`. `FINALIZED` is terminal."

        Design: Corner/endpoints/finalize_report_before_period_close_rejected
        """
        bundle = cancel_policy_effective(
            "DC",
            request_clock="2026-08-01T00:00:00Z",
            scheduled_effective_date="2026-08-20",
            mailed_on_date="2026-08-01",
            policy_number="P-DC-1",
        )
        fx.set_clock("2026-08-25T00:00:00Z")  # still inside the 2026-08 period
        report = fx.find_report(bundle["profile"]["id"], "2026-08")

        early = api.finalize_regulatory_report(report["id"], OFFICER)
        validate_error(early, ApiErrorId.ERR_REPORT_PERIOD_STILL_OPEN)

        fx.set_clock("2026-09-01T00:00:00Z")  # period fully closed
        finalized = validate_success(api.finalize_regulatory_report(report["id"], OFFICER))
        assert finalized["status"] == "FINALIZED"
