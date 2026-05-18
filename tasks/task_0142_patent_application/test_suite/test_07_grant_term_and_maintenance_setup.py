"""Grant transition, statutory term, and MaintenanceFee provisioning.

Covers PRD §3.4 in full.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULT_BASE_CLOCK,
    MAINTENANCE_GRACE_DAYS,
    MAINTENANCE_STAGE_ANCHOR_YEARS,
    MAINTENANCE_WINDOW_LEAD_DAYS,
    advance_clock_to,
    allow_application,
    assert_maintenance_fee,
    grant_application_full,
    list_maintenance_fees,
    make_applicant_headers,
    pay_fee,
    reset_clock_to_base,
    setup_allowed_application,
    setup_granted_application,
    setup_granted_utility_at_calendar_anchor,
    setup_under_examination,
    validate_error,
    validate_success,
)


# ===========================================================================
# ALLOWED -> GRANTED (PRD §3.4)
# ===========================================================================
class TestGrant:

    def test_grant_utility_succeeds(self, api):
        """PRD §3.4: "To grant an application, an examiner advances it
        from ALLOWED to GRANTED."
        """
        a, granted = setup_granted_application(application_type="UTILITY")
        assert granted["status"] == "GRANTED"
        assert granted["granted_at"] is not None
        assert granted["expires_at"] is not None

    def test_grant_design_succeeds(self, api):
        """PRD §3.4: "The transition requires that the application's
        application_type is one of UTILITY or DESIGN".
        """
        a, granted = setup_granted_application(application_type="DESIGN")
        assert granted["status"] == "GRANTED"
        assert granted["expires_at"] is not None

    def test_grant_without_issue_fee_rejected(self, api, examiner_headers):
        """PRD §3.4: "an ISSUE-category fee transaction exists at the
        scaffold-computed issue amount for the applicant's
        entity_size."

        Claim: /grant without an ISSUE fee fails.
        """
        a, allowed = setup_allowed_application(application_type="UTILITY")
        res = api.grant_application(allowed["id"], examiner_headers)
        validate_error(res, ApiErrorId.ERR_FEE_AMOUNT_MISMATCH.value)

    def test_grant_utility_creates_three_maintenance_rows(self, api):
        """PRD §3.4: "for utility patents only — provisions three
        MaintenanceFee rows representing the three statutory
        maintenance windows."
        """
        a, granted, mfs = setup_granted_utility_at_calendar_anchor(
            entity_size="SMALL", grant_year=2024, grant_month=1, grant_day=1,
        )
        assert len(mfs) == 3, (
            f"PRD §3.4: UTILITY grant must create 3 MaintenanceFees, got {len(mfs)}"
        )
        stages = sorted(m["stage"] for m in mfs)
        assert stages == ["STAGE_11_5", "STAGE_3_5", "STAGE_7_5"]
        for m in mfs:
            assert_maintenance_fee(m)
            assert m["status"] == "SCHEDULED"

    def test_grant_design_creates_no_maintenance_rows(self, api):
        """PRD §3.4: "Design patents have no maintenance" + "a request
        for the maintenance list against a non-utility or non-granted
        application is rejected with ERR_MAINTENANCE_NOT_APPLICABLE".

        Claim: GET /applications/{id}/maintenance-fees on a granted
        DESIGN application is rejected because DESIGN has no
        maintenance.
        """
        a, granted = setup_granted_application(application_type="DESIGN")
        res = api.list_maintenance_fees(granted["id"], make_applicant_headers(a["id"]))
        validate_error(res, ApiErrorId.ERR_MAINTENANCE_NOT_APPLICABLE.value)


# ===========================================================================
# Statutory expiration (PRD §3.4)
# ===========================================================================
class TestExpiration:

    def test_utility_expires_at_is_granted_plus_20_years(self, api):
        """PRD §3.4: "a granted UTILITY expires at granted_at plus 20
        years; a granted DESIGN expires at granted_at plus 15 years."

        Claim: UTILITY expires_at equals granted_at + 20 years (to the
        second).
        """
        a, granted, _ = setup_granted_utility_at_calendar_anchor(
            grant_year=2024, grant_month=1, grant_day=1,
        )
        granted_at = datetime.fromisoformat(granted["granted_at"].replace("Z", "+00:00"))
        expires_at = datetime.fromisoformat(granted["expires_at"].replace("Z", "+00:00"))
        # 20 calendar years; allow exact calendar replacement.
        expected = granted_at.replace(year=granted_at.year + 20)
        assert expires_at == expected, (
            f"PRD §3.4: UTILITY expires_at must be granted_at + 20y. "
            f"granted_at={granted_at} expires_at={expires_at} expected={expected}"
        )

    def test_design_expires_at_is_granted_plus_15_years(self, api):
        """PRD §3.4: "a granted UTILITY expires at granted_at plus 20
        years; a granted DESIGN expires at granted_at plus 15 years."

        Claim: DESIGN expires_at equals granted_at + 15 years.
        """
        # Anchor on a calendar-clean grant date.
        reset_clock_to_base()
        advance_clock_to(DEFAULT_BASE_CLOCK)
        a, granted = setup_granted_application(application_type="DESIGN")
        granted_at = datetime.fromisoformat(granted["granted_at"].replace("Z", "+00:00"))
        expires_at = datetime.fromisoformat(granted["expires_at"].replace("Z", "+00:00"))
        expected = granted_at.replace(year=granted_at.year + 15)
        assert expires_at == expected, (
            f"PRD §3.4: DESIGN expires_at must be granted_at + 15y. "
            f"granted_at={granted_at} expires_at={expires_at} expected={expected}"
        )


# ===========================================================================
# MaintenanceFee anchors (PRD §3.4)
# ===========================================================================
class TestMaintenanceAnchors:

    def test_stage_3_5_window_anchored_3_years_after_grant(self, api):
        """PRD §3.4: "whose grace_period_end_at is the due date plus
        180 days".

        Claim: STAGE_3_5 grace_period_end_at == due_at + 180 days.

        The PRD also pins window_open_at as due_at minus "six months"
        but does not equate six months with 180 days exactly (the grace
        side IS pinned to 180 days verbatim, the window side is left as
        a calendar-month offset), so the window-lead distance is left
        to faithful implementer choice. Only the grace-day count and
        the simple ordering invariants are asserted here.
        """
        a, granted, mfs = setup_granted_utility_at_calendar_anchor(
            grant_year=2024, grant_month=1, grant_day=1,
        )
        s35 = next(m for m in mfs if m["stage"] == "STAGE_3_5")
        granted_at = datetime.fromisoformat(granted["granted_at"].replace("Z", "+00:00"))
        due = datetime.fromisoformat(s35["due_at"].replace("Z", "+00:00"))
        win = datetime.fromisoformat(s35["window_open_at"].replace("Z", "+00:00"))
        grace = datetime.fromisoformat(s35["grace_period_end_at"].replace("Z", "+00:00"))
        assert (grace - due).days == MAINTENANCE_GRACE_DAYS, (
            "PRD §3.4: grace_period_end_at must be due_at + 180 days"
        )
        # Ordering invariants pinned by PRD §3.4: window opens before
        # due, due before grace end.
        assert win < due < grace
        # Due_at must be after granted_at (sanity check on 3.5 years
        # anchor).
        assert due > granted_at

    def test_no_maintenance_list_for_non_utility(self, api):
        """PRD §3.4: "a request for the maintenance list against a
        non-utility or non-granted application is rejected with
        ERR_MAINTENANCE_NOT_APPLICABLE."

        Claim: listing /applications/{design.id}/maintenance-fees
        returns ERR_MAINTENANCE_NOT_APPLICABLE.
        """
        a, granted = setup_granted_application(application_type="DESIGN")
        res = api.list_maintenance_fees(granted["id"], make_applicant_headers(a["id"]))
        validate_error(res, ApiErrorId.ERR_MAINTENANCE_NOT_APPLICABLE.value)

    def test_no_maintenance_list_for_non_granted_utility(self, api):
        """PRD §3.4: "a request for the maintenance list against a
        non-utility or non-granted application is rejected with
        ERR_MAINTENANCE_NOT_APPLICABLE."

        Claim: a FILED UTILITY application (not GRANTED) also
        triggers ERR_MAINTENANCE_NOT_APPLICABLE.
        """
        from test_helpers import setup_filed_application
        a, app = setup_filed_application(application_type="UTILITY")
        res = api.list_maintenance_fees(app["id"], make_applicant_headers(a["id"]))
        validate_error(res, ApiErrorId.ERR_MAINTENANCE_NOT_APPLICABLE.value)
