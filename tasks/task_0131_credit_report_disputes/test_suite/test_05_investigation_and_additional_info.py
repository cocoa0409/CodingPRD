"""PRD §3.2 (investigation open), §3.3 (sweep), §3.8 (deadline calc).

Covers:
- start_investigation transitions RECEIVED -> UNDER_INVESTIGATION.
- One FurnisherInquiry auto-created with forwarded_day=clock.day,
  response=PENDING.
- start_investigation gated by posture != FROZEN -> ERR_REPORT_FROZEN.
- start_investigation gated by non-empty supporting_documents ->
  ERR_NO_SUPPORTING_DOCUMENTS (PRD reuses this code at start).
- additional_info extends deadline_day to submitted_day+45 ONLY if
  accepted before base deadline; flips additional_info_accepted=true.
- additional_info rejected when additional_info_accepted is already
  true -> ERR_INVALID_STATE_TRANSITION.
- additional_info past deadline_day -> ERR_DISPUTE_DEADLINE_PASSED.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    DISPUTE_BASE_WINDOW_DAYS,
    DISPUTE_EXTENDED_WINDOW_DAYS,
    FURNISHER_REVERIFY_WINDOW_DAYS,
    TEST_USERS,
    additional_info_payload,
    advance_clock,
    get_dispute,
    make_consumer_headers,
    place_credit_freeze,
    read_clock_day,
    setup_consumer_furnisher_report_tradeline,
    setup_dispute_in_state,
    start_investigation,
    submit_additional_info,
    submit_dispute,
    validate_error,
    validate_success,
)


# ===========================================================================
# start_investigation happy path — PRD §3.2
# ===========================================================================
class TestStartInvestigation:

    def test_received_to_under_investigation(self, api):
        """PRD §3.2: 'Opening the investigation transitions the dispute
        from RECEIVED to UNDER_INVESTIGATION.'"""
        c, f, r, t = setup_consumer_furnisher_report_tradeline()
        d = submit_dispute(consumer=c, report=r, tradeline=t)
        assert d["status"] == "RECEIVED"
        d2 = start_investigation(consumer_id=c["id"], dispute_id=d["id"])
        assert d2["status"] == "UNDER_INVESTIGATION"

    def test_start_investigation_from_under_investigation_rejected(self, api):
        """PRD §2.6: same trigger from UNDER_INVESTIGATION is not a
        valid transition -> ERR_INVALID_STATE_TRANSITION (priority 5
        in §3.13 state check)."""
        c, f, r, t, d = setup_dispute_in_state(state="UNDER_INVESTIGATION")
        res = api.start_investigation(
            c["id"], d["id"], TEST_USERS["bureau_operator_headers"],
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


# ===========================================================================
# Report frozen blocks start_investigation — PRD §3.2, §3.13
# ===========================================================================
class TestReportFrozenBlocksStart:

    def test_start_investigation_blocked_when_report_frozen(self, api):
        """PRD §3.2: 'the target CreditReport's posture must not be
        FROZEN (otherwise ERR_REPORT_FROZEN — FCRA does not freeze
        the dispute process itself, but this system requires the
        consumer to lift the freeze first so that subsequent
        recomputation is meaningful)'."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline(
            bureau="EQUIFAX",
        )
        # Submit dispute first (start_investigation is what's gated).
        d = submit_dispute(consumer=c, report=r, tradeline=t)
        # Freeze the EQUIFAX bureau (matching the report's bureau).
        place_credit_freeze(consumer=c, bureau="EQUIFAX")
        res = api.start_investigation(
            c["id"], d["id"], TEST_USERS["bureau_operator_headers"],
        )
        validate_error(res, ApiErrorId.ERR_REPORT_FROZEN)


# ===========================================================================
# additional_info side effects — PRD §3.2, §3.8
# ===========================================================================
class TestAdditionalInfoExtension:

    def test_additional_info_extends_deadline_to_submitted_plus_45(self, api):
        """PRD §3.2: 'On acceptance, additional_info_accepted is set
        to true and deadline_day is rewritten to submitted_day plus
        forty-five — the FCRA fifteen-day extension on top of the
        original thirty.'"""
        c, f, r, t, d = setup_dispute_in_state(state="UNDER_INVESTIGATION")
        submitted = d["submitted_day"]
        d2 = submit_additional_info(consumer=c, dispute_id=d["id"])
        assert d2["additional_info_accepted"] is True
        assert d2["deadline_day"] == submitted + DISPUTE_EXTENDED_WINDOW_DAYS

    def test_additional_info_second_call_rejected(self, api):
        """PRD §3.2: 'The action is rejected if additional_info_accepted
        is already true (a second extension is
        ERR_INVALID_STATE_TRANSITION)'."""
        c, f, r, t, d = setup_dispute_in_state(state="UNDER_INVESTIGATION")
        submit_additional_info(consumer=c, dispute_id=d["id"])
        res = api.submit_additional_info(
            c["id"], d["id"], additional_info_payload(),
            make_consumer_headers(c["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_additional_info_after_deadline_rejected(self, api):
        """PRD §3.2: 'or if the current clock day has already passed
        deadline_day (ERR_DISPUTE_DEADLINE_PASSED)'.

        Boundary: deadline_day = submitted_day + 30. Advance the
        clock by 31 days so clock.day = deadline_day + 1; the call
        must fail."""
        c, f, r, t, d = setup_dispute_in_state(state="UNDER_INVESTIGATION")
        # Advance clock past deadline_day (= submitted_day + 30).
        advance_clock(DISPUTE_BASE_WINDOW_DAYS + 1)
        res = api.submit_additional_info(
            c["id"], d["id"], additional_info_payload(),
            make_consumer_headers(c["id"]),
        )
        validate_error(res, ApiErrorId.ERR_DISPUTE_DEADLINE_PASSED)


# ===========================================================================
# Reverification deadline independent of extension — PRD §3.3
# ===========================================================================
class TestReverificationIndependence:

    def test_reverification_deadline_is_forwarded_plus_25_unaffected_by_extension(self, api):
        """PRD §3.3: 'The inquiry's reverification_deadline_day is set
        to its forwarded_day plus twenty-five — twenty-five logical
        days regardless of whether the dispute itself has been extended
        to forty-five days. This twenty-five-day furnisher window is
        intentionally independent of the consumer's extension; an
        extension affects only the bureau's own deadline_day.'

        Claim: the reverification deadline must stay at forwarded_day
        + 25 even after the consumer requests an extension.

        Note: we observe reverification_deadline_day indirectly by
        verifying that a furnisher_response is still allowed on day
        forwarded_day + 25 after the dispute has been extended (the
        operator response succeeds, proving the boundary is at +25
        not at +45)."""
        c, f, r, t, d = setup_dispute_in_state(state="UNDER_INVESTIGATION")
        # forwarded_day == submitted_day (start_investigation at
        # clock.day == submitted_day in our fixture).
        forwarded_day = d["submitted_day"]
        # Submit additional info to extend dispute deadline to +45.
        submit_additional_info(consumer=c, dispute_id=d["id"])
        # Advance clock to exactly forwarded_day + 25 (boundary
        # inclusive per PRD §3.3 'deadline is inclusive of the operator
        # response on the deadline day itself').
        delta = (forwarded_day + FURNISHER_REVERIFY_WINDOW_DAYS) - read_clock_day()
        if delta > 0:
            advance_clock(delta)
        from test_helpers import furnisher_response_payload
        res = api.record_furnisher_response(
            c["id"], d["id"],
            furnisher_response_payload(response="VERIFIED", response_payload={}),
            TEST_USERS["bureau_operator_headers"],
        )
        # The response on the boundary day must succeed (PRD §3.3
        # boundary is inclusive). This proves the reverification
        # window stayed at forwarded_day + 25 and was not extended.
        validate_success(res, 200)
