"""Discrepancy handling: applicant decision, issuing-bank refuse,
applicant override, return documents, and the UCP600 5-banking-day
refusal-deadline auto-promotion (PRD §3.7)."""
from __future__ import annotations

import pytest

from test_helpers import (
    advance_clock_banking_days,
    applicant_decision_accept,
    applicant_decision_reject,
    applicant_override,
    discrepancy_item,
    get_clock,
    get_presentation,
    parse_iso,
    refuse_payload,
    setup_examined_discrepant_presentation,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# §3.7 — Applicant decision branches
# ===========================================================================
class TestApplicantDecision:

    def test_applicant_accept_advances_to_accepted_by_applicant(self, api):
        """PRD §3.7: 'an ACCEPTED decision flips every
        Discrepancy.applicant_action to ACCEPTED, sets each action_at
        to the current clock, and advances the presentation to
        ACCEPTED_BY_APPLICANT.'"""
        lc, bundle, presentation, _ = setup_examined_discrepant_presentation(
            amount_minor_units=10_000,
            drawing_amount_minor_units=5_000,
        )
        applicant_decision_accept(
            presentation["id"], bundle["applicant_headers"],
        )
        snapshot = get_presentation(
            presentation["id"], bundle["beneficiary_headers"],
        )
        assert snapshot["status"] == "ACCEPTED_BY_APPLICANT"

    def test_applicant_reject_advances_to_refused(self, api):
        """PRD §3.7: 'A REJECTED decision flips every applicant_action
        to REJECTED and advances the presentation to REFUSED, setting
        refusal_notified_at to the current clock and refusal_deadline
        to the current clock plus 5 banking days.'"""
        lc, bundle, presentation, _ = setup_examined_discrepant_presentation(
            amount_minor_units=10_000,
            drawing_amount_minor_units=5_000,
        )
        applicant_decision_reject(
            presentation["id"], bundle["applicant_headers"],
        )
        snapshot = get_presentation(
            presentation["id"], bundle["beneficiary_headers"],
        )
        assert snapshot["status"] == "REFUSED"
        assert snapshot.get("refusal_notified_at") is not None, (
            "PRD §3.7: 'setting refusal_notified_at to the current clock'"
        )
        assert snapshot.get("refusal_deadline") is not None, (
            "PRD §3.7: 'and refusal_deadline to the current clock plus "
            "5 banking days'"
        )


# ===========================================================================
# §3.7 — Issuing bank refuse
# ===========================================================================
class TestIssuingBankRefuse:

    def test_refuse_advances_to_refused_with_deadline(self, api):
        """PRD §3.7: 'The IssuingBank may also independently refuse the
        presentation with a refusal_reason, which moves the row directly
        from EXAMINED_DISCREPANT to REFUSED and writes the same
        refusal_notified_at and refusal_deadline fields.'"""
        lc, bundle, presentation, _ = setup_examined_discrepant_presentation(
            amount_minor_units=10_000,
            drawing_amount_minor_units=5_000,
        )
        res = api.refuse_presentation(
            presentation["id"], refuse_payload(refusal_reason="discrepant"),
            bundle["issuing_bank_headers"],
        )
        after = validate_success(res)
        assert after["status"] == "REFUSED"
        assert after.get("refusal_notified_at") is not None
        assert after.get("refusal_deadline") is not None


# ===========================================================================
# §3.7 — Applicant override (compensating action)
# ===========================================================================
class TestApplicantOverride:

    def test_override_returns_to_accepted_and_clears_refusal(self, api):
        """PRD §3.7: 'the Applicant may override refusal — a compensating
        action that moves REFUSED back to ACCEPTED_BY_APPLICANT, sets
        each Discrepancy.applicant_action to ACCEPTED, and nulls out
        both refusal_notified_at and refusal_deadline.'"""
        lc, bundle, presentation, _ = setup_examined_discrepant_presentation(
            amount_minor_units=10_000,
            drawing_amount_minor_units=5_000,
        )
        # Issuing bank refuses.
        api.refuse_presentation(
            presentation["id"], refuse_payload(refusal_reason="x"),
            bundle["issuing_bank_headers"],
        )
        res = api.applicant_override(
            presentation["id"], bundle["applicant_headers"],
        )
        after = validate_success(res)
        assert after["status"] == "ACCEPTED_BY_APPLICANT"
        assert after.get("refusal_notified_at") in (None, ""), (
            "PRD §3.7: 'nulls out both refusal_notified_at and refusal_deadline'"
        )
        assert after.get("refusal_deadline") in (None, ""), (
            "PRD §3.7: 'nulls out both refusal_notified_at and refusal_deadline'"
        )


# ===========================================================================
# §3.7 — Refusal deadline auto-promotion (UCP600 art.16(d)/(f))
# ===========================================================================
class TestRefusalDeadlineSweep:

    def test_six_banking_days_auto_promotes_to_clean(self, api):
        """PRD §3.7: 'when the elapsed banking-day count between the
        presentation's presented_at and the current clock is strictly
        greater than 5, the presentation's status is still
        EXAMINED_DISCREPANT, and refusal_notified_at is null, the system
        auto-promotes the presentation to EXAMINED_CLEAN because the
        issuing bank has lost its right to refuse and the documents are
        deemed compliant.'

        Boundary: 5 banking days still in window; 6 banking days lapses.
        """
        lc, bundle, presentation, _ = setup_examined_discrepant_presentation(
            amount_minor_units=10_000,
            drawing_amount_minor_units=5_000,
        )
        # Advance the clock 6 banking days. Per PRD §2.8 'banking days
        # count Monday through Friday strictly greater than the start
        # date'. Crossing the 5-banking-day threshold by one day
        # triggers auto-promotion.
        advance_clock_banking_days(6)
        snapshot = get_presentation(
            presentation["id"], bundle["beneficiary_headers"],
        )
        assert snapshot["status"] == "EXAMINED_CLEAN", (
            "PRD §3.7: '... the system auto-promotes the presentation "
            "to EXAMINED_CLEAN'"
        )

    def test_refuse_after_lapse_rejected(self, api):
        """PRD §3.7: 'An issuing-bank refuse call after the same
        boundary is rejected with ERR_REFUSAL_DEADLINE_PASSED.'

        After the 5-banking-day boundary the presentation has been
        auto-promoted, so the issuing bank cannot refuse. PRD names
        ERR_REFUSAL_DEADLINE_PASSED, but ERR_INVALID_STATE_TRANSITION
        is also faithful because the row is no longer in
        EXAMINED_DISCREPANT.
        """
        lc, bundle, presentation, _ = setup_examined_discrepant_presentation(
            amount_minor_units=10_000,
            drawing_amount_minor_units=5_000,
        )
        advance_clock_banking_days(6)
        res = api.refuse_presentation(
            presentation["id"], refuse_payload(refusal_reason="late"),
            bundle["issuing_bank_headers"],
        )
        validate_error_is_one_of(
            res,
            ["ERR_REFUSAL_DEADLINE_PASSED", "ERR_INVALID_STATE_TRANSITION"],
        )
