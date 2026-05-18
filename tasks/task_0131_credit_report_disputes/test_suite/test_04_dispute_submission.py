"""PRD §3.2 — Dispute submission and submission-time validations.

Covers:
- Successful submission seeds status=RECEIVED, submitted_day,
  deadline_day=submitted_day+30, additional_info_accepted=false,
  investigation_outcome=PENDING.
- Empty supporting_documents -> ERR_NO_SUPPORTING_DOCUMENTS.
- Frivolous threshold: 4th submission on same tradeline within 365
  days -> ERR_FRIVOLOUS_DISPUTE.
- Duplicate active dispute on same tradeline -> ERR_DUPLICATE_ACTIVE_DISPUTE.
- New dispute on same tradeline AFTER prior close is permitted (no buffer).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    DISPUTE_BASE_WINDOW_DAYS,
    advance_clock,
    assert_dispute,
    close_dispute_verified,
    create_dispute_payload,
    make_consumer_headers,
    read_clock_day,
    setup_consumer_furnisher_report_tradeline,
    submit_dispute,
    submit_n_closed_disputes_on_tradeline,
    supporting_doc,
    validate_error,
    validate_success,
)


# ===========================================================================
# Successful submission semantics — PRD §3.2
# ===========================================================================
class TestSubmissionSeedFields:

    def test_status_received_on_submission(self, api):
        """PRD §3.2: 'On successful submission, the new Dispute is
        created with status of RECEIVED'."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline()
        d = submit_dispute(consumer=c, report=r, tradeline=t)
        assert_dispute(d)
        assert d["status"] == "RECEIVED"

    def test_submitted_day_is_clock_day(self, api):
        """PRD §3.2: 'submitted_day set to the current clock day'."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline()
        clock_day = read_clock_day()
        d = submit_dispute(consumer=c, report=r, tradeline=t)
        assert d["submitted_day"] == clock_day

    def test_deadline_day_is_submitted_plus_thirty(self, api):
        """PRD §3.2: 'The investigation clock is set by computing
        deadline_day as submitted_day plus thirty — the FCRA base
        window.'"""
        c, f, r, t = setup_consumer_furnisher_report_tradeline()
        d = submit_dispute(consumer=c, report=r, tradeline=t)
        assert d["deadline_day"] == d["submitted_day"] + DISPUTE_BASE_WINDOW_DAYS

    def test_additional_info_accepted_starts_false(self, api):
        """PRD §3.2: 'additional_info_accepted initialized to false'."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline()
        d = submit_dispute(consumer=c, report=r, tradeline=t)
        assert d["additional_info_accepted"] is False

    def test_investigation_outcome_starts_pending(self, api):
        """PRD §3.2: 'investigation_outcome initialized to PENDING'."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline()
        d = submit_dispute(consumer=c, report=r, tradeline=t)
        assert d["investigation_outcome"] == "PENDING"

    def test_result_notice_id_starts_null(self, api):
        """PRD §3.2: 'and a null result_notice_id.'"""
        c, f, r, t = setup_consumer_furnisher_report_tradeline()
        d = submit_dispute(consumer=c, report=r, tradeline=t)
        assert d["result_notice_id"] is None


# ===========================================================================
# Supporting documents — PRD §3.2
# ===========================================================================
class TestSupportingDocuments:

    def test_empty_supporting_documents_rejected_at_submission(self, api):
        """PRD §3.2: 'The supporting-documents array must be non-empty
        at submission; an empty or missing array is rejected with
        ERR_NO_SUPPORTING_DOCUMENTS'."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline()
        payload = create_dispute_payload(
            credit_report_id=r["id"],
            tradeline_item_id=t["id"],
            supporting_documents=[],
        )
        res = api.create_dispute(
            c["id"], payload, make_consumer_headers(c["id"]),
        )
        validate_error(res, ApiErrorId.ERR_NO_SUPPORTING_DOCUMENTS)

    def test_one_supporting_document_succeeds(self, api):
        """PRD §3.2 boundary: array length == 1 -> 201. Pairs with
        the empty-array boundary above."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline()
        payload = create_dispute_payload(
            credit_report_id=r["id"],
            tradeline_item_id=t["id"],
            supporting_documents=[supporting_doc("RECEIPT")],
        )
        res = api.create_dispute(
            c["id"], payload, make_consumer_headers(c["id"]),
        )
        validate_success(res, 201)


# ===========================================================================
# Frivolous threshold — PRD §3.2
# ===========================================================================
class TestFrivolousThreshold:

    def test_fourth_submission_in_365_days_is_frivolous(self, api):
        """PRD §3.2: 'if the consumer has already submitted more than
        three disputes against the same tradeline_item_id in the
        trailing 365 logical days, the submission is rejected with
        ERR_FRIVOLOUS_DISPUTE.'

        Three priors close VERIFIED; the 4th submission on the same
        tradeline must fail with ERR_FRIVOLOUS_DISPUTE."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline()
        # 3 priors, all closed VERIFIED.
        submit_n_closed_disputes_on_tradeline(
            consumer=c, report=r, tradeline=t, n=3, close_as="VERIFIED",
        )
        # 4th submission on the SAME tradeline.
        payload = create_dispute_payload(
            credit_report_id=r["id"], tradeline_item_id=t["id"],
        )
        res = api.create_dispute(
            c["id"], payload, make_consumer_headers(c["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FRIVOLOUS_DISPUTE)

    def test_third_submission_in_365_days_is_not_frivolous(self, api):
        """PRD §3.2 boundary: 'more than three' means N>3, so the
        third submission (counting the new one => total 3 in 365
        days) is still allowed. Two priors closed; the third
        submission succeeds."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline()
        submit_n_closed_disputes_on_tradeline(
            consumer=c, report=r, tradeline=t, n=2, close_as="VERIFIED",
        )
        d3 = submit_dispute(consumer=c, report=r, tradeline=t)
        assert d3["status"] == "RECEIVED"


# ===========================================================================
# Duplicate active dispute — PRD §3.2
# ===========================================================================
class TestDuplicateActiveDispute:

    def test_second_active_dispute_on_same_tradeline_rejected(self, api):
        """PRD §3.2: 'at most one Dispute may be in a non-terminal
        status (anything other than CLOSED_VERIFIED, CLOSED_UPDATED,
        CLOSED_DELETED, or CLOSED_DISMISSED) per TradelineItem — a
        second attempt is rejected with ERR_DUPLICATE_ACTIVE_DISPUTE.'"""
        c, f, r, t = setup_consumer_furnisher_report_tradeline()
        submit_dispute(consumer=c, report=r, tradeline=t)
        payload = create_dispute_payload(
            credit_report_id=r["id"], tradeline_item_id=t["id"],
        )
        res = api.create_dispute(
            c["id"], payload, make_consumer_headers(c["id"]),
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_ACTIVE_DISPUTE)

    def test_new_dispute_after_prior_closes_succeeds(self, api):
        """PRD §3.2 derives an open-interval semantics for active
        disputes: 'at most one Dispute may be in a non-terminal
        status ... per TradelineItem'. Once the first dispute is in
        a CLOSED_* state, a second submission on the same tradeline
        must succeed (no buffer)."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline()
        # Close first dispute VERIFIED.
        close_dispute_verified(consumer=c, report=r, tradeline=t)
        # New submission on same tradeline.
        d2 = submit_dispute(consumer=c, report=r, tradeline=t)
        assert d2["status"] == "RECEIVED"


# ===========================================================================
# Channel immutability — PRD §3.2
# ===========================================================================
class TestChannelImmutability:

    def test_channel_persisted_as_submitted(self, api):
        """PRD §3.2: 'the channel of submission as channel (either
        ONLINE or MAIL, immutable after submission)'."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline()
        d_online = submit_dispute(
            consumer=c, report=r, tradeline=t, channel="ONLINE",
        )
        assert d_online["channel"] == "ONLINE"

    def test_mail_channel_persisted_as_mail(self, api):
        """PRD §3.2 channel enum: MAIL is the other accepted value."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline()
        # Need a separate tradeline because the first dispute is active.
        from test_helpers import add_extra_tradeline
        t2 = add_extra_tradeline(consumer=c, furnisher=f, report=r)
        d_mail = submit_dispute(
            consumer=c, report=r, tradeline=t2, channel="MAIL",
        )
        assert d_mail["channel"] == "MAIL"
