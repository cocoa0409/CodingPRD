"""341 creditors' meeting — scheduling and conducting.

PRD §3.5. Tests cover ERR_MEETING_TOO_EARLY boundary, the inclusive
21-day boundary, ERR_MEETING_DATE_NOT_REACHED, and the claim-allowance
cascade on conduct_341.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    MEETING_341_MIN_GAP_DAYS,
    TEST_USERS,
    advance_clock_to,
    conduct_341,
    create_creditor,
    file_claim,
    iso_offset,
    iso_utc,
    parse_iso,
    re_get_case,
    re_get_claim,
    schedule_341_payload,
    schedule_341,
    setup_filed_case,
    setup_meeting_scheduled_case,
    validate_error,
    validate_success,
)


# ===========================================================================
# ERR_MEETING_TOO_EARLY boundary — PRD §3.5
# ===========================================================================
class TestMeetingDateGap:
    """PRD §3.5: 'The proposed meeting_date must be at least 21 days
    after filing_date — that is, the meeting date is no earlier than
    the filing date plus 21 days. A meeting scheduled too early is
    rejected with ERR_MEETING_TOO_EARLY (HTTP 422).'"""

    def test_meeting_20_days_after_filing_rejected(self, api):
        """PRD §3.5: "The proposed meeting_date must be at least 21
        days after filing_date — that is, the meeting date is no
        earlier than the filing date plus 21 days. A meeting scheduled
        too early is rejected with ERR_MEETING_TOO_EARLY (HTTP 422)."

        Claim: 20 days after filing -> ERR_MEETING_TOO_EARLY.
        # difficulty: resource_temporal_overlap/meeting_341_minimum_gap_after_filing
        """
        debtor, case, _mtr = setup_filed_case()
        filing_date = parse_iso(case["filing_date"])
        too_early = iso_offset(days=20, base=filing_date)
        resp = api.schedule_341(
            case["id"], schedule_341_payload(meeting_date=too_early),
            TEST_USERS["trustee_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_MEETING_TOO_EARLY.value)

    def test_meeting_exactly_21_days_after_filing_accepted(self, api):
        """PRD §3.5: "The proposed meeting_date must be at least 21
        days after filing_date — that is, the meeting date is no
        earlier than the filing date plus 21 days."

        Claim: exactly 21 days after filing -> case transitions to
        MEETING_SCHEDULED (boundary inclusive).
        # difficulty: resource_temporal_overlap/meeting_341_minimum_gap_after_filing
        """
        debtor, case, _mtr = setup_filed_case()
        filing_date = parse_iso(case["filing_date"])
        at_boundary = iso_offset(days=MEETING_341_MIN_GAP_DAYS,
                                 base=filing_date)
        result = schedule_341(
            case=case, meeting_date_iso=at_boundary,
        )
        assert result["status"] == "MEETING_SCHEDULED"
        # PRD §3.5: 'the server records it on the case as meeting_341_date'.
        assert result.get("meeting_341_date") is not None


# ===========================================================================
# ERR_MEETING_DATE_NOT_REACHED — PRD §3.5
# ===========================================================================
class TestConductMeetingClockGate:
    """PRD §3.5: 'The system's logical clock must already have reached
    the scheduled meeting_341_date; attempting to conduct the meeting
    while the clock is still earlier than that date is rejected with
    ERR_MEETING_DATE_NOT_REACHED.'"""

    def test_conduct_341_before_clock_reaches_date_rejected(self, api):
        """PRD §3.5: "The system's logical clock must already have
        reached the scheduled meeting_341_date; attempting to conduct
        the meeting while the clock is still earlier than that date
        is rejected with ERR_MEETING_DATE_NOT_REACHED."

        Claim: conduct_341 before clock reaches meeting date ->
        ERR_MEETING_DATE_NOT_REACHED.
        """
        # Schedule meeting far in the future relative to "now".
        debtor, case, _mtr, _md = setup_meeting_scheduled_case(
            days_after_filing=365,
        )
        # Do NOT advance the clock; conduct now.
        resp = api.conduct_341(
            case["id"], None, TEST_USERS["trustee_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_MEETING_DATE_NOT_REACHED.value,
        )

    def test_conduct_341_succeeds_after_clock_reaches_meeting_date(self, api):
        """PRD §3.5: "The meeting may then be conducted, transitioning
        the case from MEETING_SCHEDULED to MEETING_HELD."

        Claim: after clock advances past meeting_341_date, conduct_341
        succeeds and case -> MEETING_HELD.
        """
        debtor, case, _mtr, meeting_date_iso = setup_meeting_scheduled_case(
            days_after_filing=21,
        )
        advance_clock_to(meeting_date_iso)
        case_after = conduct_341(case=case)
        assert case_after["status"] == "MEETING_HELD"


# ===========================================================================
# Claim-review cascade on conduct_341 — PRD §3.5 / §2.10
# ===========================================================================
class TestConductMeetingCascade:
    """PRD §3.5: 'Conducting the meeting also fires the claim-review
    cascade. Every Claim for this case still in FILED status
    auto-transitions to ALLOWED in the same transaction.'"""

    def test_conduct_341_transitions_filed_claims_to_allowed(self, api):
        """PRD §3.5: "Conducting the meeting also fires the
        claim-review cascade. Every Claim for this case still in FILED
        status auto-transitions to ALLOWED in the same transaction."

        Claim: after conduct_341, claims that were FILED are now
        ALLOWED.
        """
        debtor, case, _mtr, _md = setup_meeting_scheduled_case()
        creditor = create_creditor(creditor_type="GENERAL_UNSECURED")
        claim = file_claim(
            case=case, creditor=creditor, amount_cents=50_000,
            is_dischargeable=True,
        )
        assert claim["status"] == "FILED"
        # Advance clock + conduct.
        advance_clock_to(case["meeting_341_date"])
        conduct_341(case=case)
        # Reread claim.
        claim_after = re_get_claim(case["id"], claim["id"])
        assert claim_after["status"] == "ALLOWED"

    def test_conduct_341_cascade_recomputes_total_unsecured_pool(self, api):
        """PRD §2.12: "For every case, the server-maintained
        total_unsecured_pool_cents aggregate is the sum of
        amount_cents across every Claim on this case whose claim_class
        is GENERAL_UNSECURED and whose status is ALLOWED. The pool
        recomputes whenever a claim transitions into or out of
        ALLOWED."

        Claim: after conduct_341 transitions GU claims to ALLOWED,
        Case.total_unsecured_pool_cents equals the sum.
        """
        debtor, case, _mtr, _md = setup_meeting_scheduled_case()
        c1 = create_creditor(creditor_type="GENERAL_UNSECURED")
        c2 = create_creditor(creditor_type="GENERAL_UNSECURED")
        cl1 = file_claim(case=case, creditor=c1, amount_cents=100_000)
        cl2 = file_claim(case=case, creditor=c2, amount_cents=300_000)
        advance_clock_to(case["meeting_341_date"])
        conduct_341(case=case)
        case_after = re_get_case(case["id"])
        assert case_after["total_unsecured_pool_cents"] == 100_000 + 300_000


# ===========================================================================
# Wrong-state schedule/conduct — PRD §2.6
# ===========================================================================
class TestMeetingWrongState:
    """PRD §2.6: 'State-machine eligibility is checked fourth: a
    target resource in a state from which the requested transition is
    undefined yields ERR_INVALID_STATE.'"""

    def test_schedule_341_from_draft_rejected(self, api):
        """PRD §2.6: "a target resource in a state from which the
        requested transition is undefined yields ERR_INVALID_STATE".

        Claim: schedule_341 on a DRAFT case (not yet FILED) ->
        ERR_INVALID_STATE.
        """
        from test_helpers import create_case, create_debtor
        debtor = create_debtor()
        case = create_case(debtor=debtor)
        # Submit a payload that is far enough in the future.
        future_iso = iso_offset(days=30)
        resp = api.schedule_341(
            case["id"], schedule_341_payload(meeting_date=future_iso),
            TEST_USERS["trustee_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_conduct_341_from_filed_rejected(self, api):
        """PRD §2.6: "a target resource in a state from which the
        requested transition is undefined yields ERR_INVALID_STATE".

        Claim: conduct_341 on a FILED case (still need scheduling) ->
        ERR_INVALID_STATE.
        """
        debtor, case, _mtr = setup_filed_case()
        resp = api.conduct_341(
            case["id"], None, TEST_USERS["trustee_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
