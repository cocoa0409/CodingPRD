"""Clock advance and time-triggered sweeps — PRD §3.10.

Coverage:
- Advance clock returns {now, expired_rfes, auto_denied_cases}.
- RFE expiry: clock crosses deadline_at -> RFE.status=EXPIRED, parent
  Case.status=DENIED with denial_reason=RFE_TIMEOUT, decision_at set.
- Cascade hop 3 for I-130 RFE expiry: dependent I-485 also DENIED with
  denial_reason=INELIGIBLE; SCHEDULED Biometrics/Interview on the
  dependent set to CANCELLED.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    advance_clock_to,
    api_client,
    iso_utc,
    issue_rfe,
    parse_iso,
    re_get_case,
    setup_biometrics_completed,
    setup_filed_case,
    setup_i130_in_rfe_issued,
    setup_i130_in_rfe_issued_with_dependent_i485_filed,
    validate_success,
)


class TestClockAdvanceBasics:

    def test_advance_returns_now_field(self, api, supervisor_headers):
        """PRD §3.10: "Advancing the clock runs every time-triggered
        sweep against the new server time and returns an object whose
        fields are now (the new server clock value), expired_rfes (the
        count of RFEs swept to EXPIRED), and auto_denied_cases (the
        count of cases auto-denied as a result)."

        Claim: POST /_clock/advance returns object with now,
        expired_rfes, auto_denied_cases.
        """
        resp = api_client.advance_clock(
            {"to": "2030-01-01T00:00:00.000Z"},
            supervisor_headers,
        )
        data = validate_success(resp)
        assert "now" in data
        assert "expired_rfes" in data
        assert "auto_denied_cases" in data
        assert isinstance(data["expired_rfes"], int)
        assert isinstance(data["auto_denied_cases"], int)


class TestRFEExpirySweep:

    def test_clock_past_deadline_expires_rfe_and_denies_case(self, api):
        """PRD §3.10: "The RFE expiry sweep iterates every RFE whose
        status is OUTSTANDING and whose deadline_at has been strictly
        exceeded by the new server time. Each such RFE has its status
        set to EXPIRED, and its parent case transitions to DENIED with
        denial_reason set to RFE_TIMEOUT and decision_at set to the
        moment of expiry".

        Claim: advancing the clock past an OUTSTANDING RFE's
        deadline_at sets the RFE to EXPIRED and the parent Case to
        DENIED/RFE_TIMEOUT with decision_at non-null.
        """
        bundle = setup_i130_in_rfe_issued()
        case = bundle["case"]
        rfe = bundle["rfe"]
        deadline = parse_iso(rfe["deadline_at"])
        # Advance 1 second past the deadline (strictly later).
        advance_clock_to(iso_utc(deadline + timedelta(seconds=1)))
        # Re-read.
        from test_helpers import api_client as _ac
        rfe_resp = _ac.get_rfe(
            rfe["id"],
            {"X-User-ID": "officer-x", "X-User-Role": "Officer",
             "Content-Type": "application/json"},
        )
        rfe_after = validate_success(rfe_resp)
        assert rfe_after["status"] == "EXPIRED"
        case_after = re_get_case(case["id"])
        assert case_after["status"] == "DENIED"
        assert case_after["denial_reason"] == "RFE_TIMEOUT"
        assert case_after.get("decision_at") is not None

    def test_clock_at_exact_deadline_does_not_expire(self, api):
        """PRD §2.8: "comparisons against it use strict greater-than
        semantics, so the exact instant equal to deadline_at is still
        in-window and only a strictly later instant marks the RFE as
        past due."

        Claim: advancing the clock TO exactly deadline_at (no later)
        does NOT expire the RFE — its status remains OUTSTANDING.
        """
        bundle = setup_i130_in_rfe_issued()
        case = bundle["case"]
        rfe = bundle["rfe"]
        deadline = parse_iso(rfe["deadline_at"])
        advance_clock_to(iso_utc(deadline))
        from test_helpers import api_client as _ac
        rfe_resp = _ac.get_rfe(
            rfe["id"],
            {"X-User-ID": "officer-x", "X-User-Role": "Officer",
             "Content-Type": "application/json"},
        )
        rfe_after = validate_success(rfe_resp)
        assert rfe_after["status"] == "OUTSTANDING", (
            f"At now() == deadline_at exactly the RFE is still "
            f"in-window per PRD §2.8 strict greater-than; got "
            f"status={rfe_after['status']!r}"
        )
        case_after = re_get_case(case["id"])
        assert case_after["status"] == "RFE_ISSUED"
