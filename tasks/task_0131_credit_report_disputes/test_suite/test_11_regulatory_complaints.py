"""PRD §3.10 — RegulatoryComplaint CFPB escalation lifecycle.

Covers:
- Filing requires dispute in {CLOSED_VERIFIED, CLOSED_DISMISSED} ->
  ERR_NOT_ESCALATABLE otherwise.
- Filing transitions dispute to ESCALATED.
- One open complaint per dispute -> ERR_COMPLAINT_ALREADY_OPEN.
- Refile only via parent_complaint_id after parent REJECTED.
- Accept: complaint FILED -> UNDER_REVIEW; dispute ESCALATED ->
  UNDER_INVESTIGATION (fresh deadline = clock.day + 30, new
  FurnisherInquiry).
- Reject: complaint FILED -> REJECTED; no dispute side effects.
- Resolve: complaint UNDER_REVIEW -> RESOLVED only when dispute is
  again in CLOSED_* -> ERR_DISPUTE_NOT_RECLOSED otherwise.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    CFPB_REOPEN_WINDOW_DAYS,
    TEST_USERS,
    accept_complaint,
    assert_regulatory_complaint,
    close_dispute_verified,
    create_regulatory_complaint_payload,
    file_regulatory_complaint,
    get_dispute,
    issue_result_notice,
    make_consumer_headers,
    read_clock_day,
    record_furnisher_response,
    reject_complaint,
    resolve_complaint,
    setup_consumer_furnisher_report_tradeline,
    setup_dispute_in_state,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# Escalation eligibility — PRD §3.10
# ===========================================================================
class TestEscalationEligibility:

    def test_escalate_from_closed_verified(self, api):
        """PRD §3.10: 'The dispute must currently be in CLOSED_VERIFIED
        or CLOSED_DISMISSED; if it is in any other state, the
        escalation is rejected with ERR_NOT_ESCALATABLE.'

        CLOSED_VERIFIED is one of the permitted preconditions."""
        c, f, r, t, d = setup_dispute_in_state(state="CLOSED_VERIFIED")
        k = file_regulatory_complaint(
            consumer=c, dispute_id=d["id"],
            narrative="Bureau verification was insufficient.",
        )
        assert_regulatory_complaint(k)
        assert k["status"] == "FILED"

    def test_escalate_from_closed_updated_rejected(self, api):
        """PRD §3.10: only CLOSED_VERIFIED or CLOSED_DISMISSED are
        escalatable. CLOSED_UPDATED is a closed state too, but PRD
        explicitly excludes it -> ERR_NOT_ESCALATABLE."""
        c, f, r, t, d = setup_dispute_in_state(state="CLOSED_UPDATED")
        res = api.create_regulatory_complaint(
            c["id"],
            create_regulatory_complaint_payload(
                dispute_id=d["id"],
                narrative="Updated outcome was not in my favor.",
            ),
            make_consumer_headers(c["id"]),
        )
        validate_error(res, ApiErrorId.ERR_NOT_ESCALATABLE)

    def test_escalate_from_under_investigation_rejected(self, api):
        """PRD §3.10: any non-CLOSED_* state -> ERR_NOT_ESCALATABLE."""
        c, f, r, t, d = setup_dispute_in_state(state="UNDER_INVESTIGATION")
        res = api.create_regulatory_complaint(
            c["id"],
            create_regulatory_complaint_payload(
                dispute_id=d["id"], narrative="Still under investigation.",
            ),
            make_consumer_headers(c["id"]),
        )
        validate_error(res, ApiErrorId.ERR_NOT_ESCALATABLE)


# ===========================================================================
# Filing side effects — PRD §3.10
# ===========================================================================
class TestFilingSideEffects:

    def test_filing_transitions_dispute_to_escalated(self, api):
        """PRD §3.10: 'As a side effect of the filing, the underlying
        dispute transitions to ESCALATED (from CLOSED_VERIFIED or
        CLOSED_DISMISSED).'"""
        c, f, r, t, d = setup_dispute_in_state(state="CLOSED_VERIFIED")
        file_regulatory_complaint(
            consumer=c, dispute_id=d["id"],
            narrative="Need CFPB review.",
        )
        d_after = get_dispute(consumer_id=c["id"], dispute_id=d["id"])
        assert d_after["status"] == "ESCALATED"

    def test_filed_day_is_clock_day(self, api):
        """PRD §3.10: 'A RegulatoryComplaint is created with status
        of FILED, filed_day stamped from the current clock day'."""
        from test_helpers import advance_clock
        c, f, r, t, d = setup_dispute_in_state(state="CLOSED_VERIFIED")
        advance_clock(13)
        now = read_clock_day()
        k = file_regulatory_complaint(
            consumer=c, dispute_id=d["id"], narrative="Escalating.",
        )
        assert k["filed_day"] == now


# ===========================================================================
# One open complaint per dispute — PRD §3.10
# ===========================================================================
class TestOneOpenComplaintPerDispute:

    def test_second_filing_while_first_filed_rejected(self, api):
        """PRD §3.10: 'At most one open regulatory complaint may exist
        per dispute — "open" meaning the complaint's status is either
        FILED or UNDER_REVIEW. A second open complaint is rejected
        with ERR_COMPLAINT_ALREADY_OPEN'.

        After the first filing, the underlying dispute also transitions
        to ESCALATED (PRD §3.10). The second sequential filing therefore
        triggers BOTH the eligibility check (priority 16,
        ERR_NOT_ESCALATABLE per PRD §3.13 boundary case) and the
        uniqueness check (priority 17, ERR_COMPLAINT_ALREADY_OPEN).
        PRD §3.13 explicitly names ERR_NOT_ESCALATABLE as the winner of
        that exact precedence pair, while PRD §3.10 names
        ERR_COMPLAINT_ALREADY_OPEN as 'the' rejection reason; both
        readings are PRD-supported, so we accept either."""
        c, f, r, t, d = setup_dispute_in_state(state="CLOSED_VERIFIED")
        file_regulatory_complaint(
            consumer=c, dispute_id=d["id"], narrative="First filing.",
        )
        res = api.create_regulatory_complaint(
            c["id"],
            create_regulatory_complaint_payload(
                dispute_id=d["id"], narrative="Second filing.",
            ),
            make_consumer_headers(c["id"]),
        )
        validate_error_is_one_of(
            res,
            [
                ApiErrorId.ERR_COMPLAINT_ALREADY_OPEN.value,
                ApiErrorId.ERR_NOT_ESCALATABLE.value,
            ],
        )

    def test_refile_after_reject_with_parent_complaint_id_succeeds(self, api):
        """PRD §3.10: 'A refile is permitted only via
        parent_complaint_id after the parent has been moved to
        REJECTED.'"""
        c, f, r, t, d = setup_dispute_in_state(state="CLOSED_VERIFIED")
        k1 = file_regulatory_complaint(
            consumer=c, dispute_id=d["id"], narrative="v1",
        )
        # CFPB rejects.
        reject_complaint(complaint_id=k1["id"])
        # Note: the original dispute transitioned to ESCALATED on
        # filing per PRD §3.10. After reject, the dispute remains
        # ESCALATED (PRD says reject 'produces no side effects on the
        # dispute'); PRD §3.10 'must currently be in CLOSED_VERIFIED
        # or CLOSED_DISMISSED' would block a refile.
        #
        # Two PRD-only readers could legitimately disagree: one
        # treats the parent_complaint_id refile path as a special
        # path that bypasses the CLOSED_* gate (the only way to
        # exercise PRD §3.10's refile clause meaningfully); another
        # treats the gate as universal. We test the strictly
        # supported invariant (k2.parent_complaint_id == k1.id when
        # refile succeeds) and accept either of {201, 409
        # ERR_NOT_ESCALATABLE}.
        k2_resp = api.create_regulatory_complaint(
            c["id"],
            create_regulatory_complaint_payload(
                dispute_id=d["id"],
                parent_complaint_id=k1["id"],
                narrative="v2 refile",
            ),
            make_consumer_headers(c["id"]),
        )
        assert k2_resp.status_code in (201, 409), (
            f"Refile response must be 201 (PRD §3.10 refile path) or "
            f"409 ERR_NOT_ESCALATABLE (dispute ESCALATED gate), got "
            f"HTTP {k2_resp.status_code}"
        )
        if k2_resp.status_code == 201:
            k2 = k2_resp.json()["data"]
            assert k2["parent_complaint_id"] == k1["id"], (
                "PRD §3.10: refile must reference parent_complaint_id"
            )
            assert k2["status"] == "FILED"


# ===========================================================================
# CFPB accept arm — PRD §3.10
# ===========================================================================
class TestCfpbAccept:

    def test_accept_transitions_complaint_to_under_review(self, api):
        """PRD §3.10: 'The accept action transitions the complaint
        from FILED to UNDER_REVIEW'."""
        c, f, r, t, d = setup_dispute_in_state(state="CLOSED_VERIFIED")
        k = file_regulatory_complaint(
            consumer=c, dispute_id=d["id"], narrative="Please review.",
        )
        k2 = accept_complaint(complaint_id=k["id"])
        assert k2["status"] == "UNDER_REVIEW"

    def test_accept_reopens_dispute_with_fresh_deadline(self, api):
        """PRD §3.10: 'and triggers the dispute-reopen cascade: the
        underlying dispute transitions from ESCALATED back to
        UNDER_INVESTIGATION; a fresh FurnisherInquiry is auto-created
        (with its own forwarded_day of the current clock day and
        response of PENDING); the dispute's deadline_day is reset to
        the current clock day plus thirty; and additional_info_accepted
        is reset to false.'"""
        from test_helpers import advance_clock
        c, f, r, t, d = setup_dispute_in_state(state="CLOSED_VERIFIED")
        k = file_regulatory_complaint(
            consumer=c, dispute_id=d["id"], narrative="Reopen please.",
        )
        # Advance clock to make the fresh-deadline assertion meaningful.
        advance_clock(50)
        now_before_accept = read_clock_day()
        accept_complaint(complaint_id=k["id"])
        d_after = get_dispute(consumer_id=c["id"], dispute_id=d["id"])
        assert d_after["status"] == "UNDER_INVESTIGATION"
        assert d_after["deadline_day"] == now_before_accept + CFPB_REOPEN_WINDOW_DAYS
        assert d_after["additional_info_accepted"] is False


# ===========================================================================
# CFPB reject arm — PRD §3.10
# ===========================================================================
class TestCfpbReject:

    def test_reject_transitions_to_rejected_no_dispute_side_effects(self, api):
        """PRD §3.10: 'The reject action transitions the complaint
        from FILED directly to REJECTED and produces no side effects
        on the dispute.'"""
        c, f, r, t, d = setup_dispute_in_state(state="CLOSED_VERIFIED")
        k = file_regulatory_complaint(
            consumer=c, dispute_id=d["id"], narrative="Filed.",
        )
        d_before = get_dispute(consumer_id=c["id"], dispute_id=d["id"])
        # Status is ESCALATED after filing.
        assert d_before["status"] == "ESCALATED"
        reject_complaint(complaint_id=k["id"])
        d_after = get_dispute(consumer_id=c["id"], dispute_id=d["id"])
        # PRD §3.10: reject 'produces no side effects on the dispute'
        # — therefore the dispute stays in ESCALATED.
        assert d_after["status"] == d_before["status"]


# ===========================================================================
# CFPB resolve arm — PRD §3.10
# ===========================================================================
class TestCfpbResolve:

    def test_resolve_blocked_when_dispute_under_investigation(self, api):
        """PRD §3.10: 'The resolve action transitions the complaint
        from UNDER_REVIEW to RESOLVED, but only when the underlying
        dispute is once again in one of the four terminal CLOSED_*
        states (so that the reopened investigation has actually been
        closed out); otherwise the resolve attempt is rejected with
        ERR_DISPUTE_NOT_RECLOSED.'"""
        c, f, r, t, d = setup_dispute_in_state(state="CLOSED_VERIFIED")
        k = file_regulatory_complaint(
            consumer=c, dispute_id=d["id"], narrative="Filed.",
        )
        accept_complaint(complaint_id=k["id"])
        # Dispute is now UNDER_INVESTIGATION (per accept cascade).
        d_mid = get_dispute(consumer_id=c["id"], dispute_id=d["id"])
        assert d_mid["status"] == "UNDER_INVESTIGATION"
        res = api.resolve_complaint(
            k["id"], TEST_USERS["cfpb_operator_headers"],
        )
        validate_error(res, ApiErrorId.ERR_DISPUTE_NOT_RECLOSED)

    def test_resolve_succeeds_when_dispute_reclosed(self, api):
        """PRD §3.10: 'only when the underlying dispute is once again
        in one of the four terminal CLOSED_* states'. Reclose VERIFIED,
        then resolve."""
        c, f, r, t, d = setup_dispute_in_state(state="CLOSED_VERIFIED")
        k = file_regulatory_complaint(
            consumer=c, dispute_id=d["id"], narrative="Filed.",
        )
        accept_complaint(complaint_id=k["id"])
        # Drive dispute back through to CLOSED_VERIFIED.
        record_furnisher_response(
            consumer_id=c["id"], dispute_id=d["id"],
            response="VERIFIED", response_payload={},
        )
        issue_result_notice(consumer_id=c["id"], dispute_id=d["id"])
        d_reclosed = get_dispute(consumer_id=c["id"], dispute_id=d["id"])
        assert d_reclosed["status"] == "CLOSED_VERIFIED"
        k_resolved = resolve_complaint(complaint_id=k["id"])
        assert k_resolved["status"] == "RESOLVED"
