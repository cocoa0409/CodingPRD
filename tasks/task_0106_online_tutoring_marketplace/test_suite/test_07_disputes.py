"""Refund dispute lifecycle.

Covers PRD §3.7: open, respond, counter, accept, reopen, escalate,
arbitrate (REFUND / DENY), withdraw; segregation of duties;
DISPUTED → REFUNDED money recomputation (FINAL_AFTER_REFUND commission).
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    accept_dispute,
    advance_clock_to,
    arbitrate_dispute,
    assert_money_conservation_invariant,
    assert_refund_dispute,
    counter_dispute,
    escalate_dispute,
    iso_utc,
    make_arbiter_headers,
    make_student_headers,
    make_tutor_headers,
    open_dispute,
    open_dispute_payload,
    parse_iso,
    respond_dispute,
    setup_completed_session,
    setup_settled_session,
    validate_error,
    validate_success,
    withdraw_dispute,
)


# ===========================================================================
# Dispute creation
# ===========================================================================
class TestOpenDispute:
    def test_open_dispute_on_completed_session(self, api):
        """PRD §3.7: "Once a session is in COMPLETED or SETTLED, the
        booking student ... may open a RefundDispute against it." And:
        "When the underlying session is currently COMPLETED, opening
        the dispute cascades it COMPLETED → DISPUTED".

        Claim: opening a dispute on a COMPLETED session yields
        dispute.status=OPEN, dispute.round_count=0, and the underlying
        session moves to DISPUTED.
        """
        tutor, student, completed = setup_completed_session()
        d = open_dispute(
            session=completed,
            opener_headers=make_student_headers(student["id"]),
            requested_amount_cents=1000,
        )
        assert_refund_dispute(d)
        assert d["status"] == "OPEN"
        assert d["round_count"] == 0
        # Re-fetch session.
        refreshed_session = validate_success(
            api.get_session(
                completed["id"], make_student_headers(student["id"]),
            ),
        )
        assert refreshed_session["status"] == "DISPUTED"

    def test_open_dispute_on_settled_session_does_not_change_session(self, api):
        """PRD §3.7: "when the session is already SETTLED, the session
        remains in SETTLED and the dispute is simply attached."

        Claim: opening a dispute on a SETTLED session leaves the
        session in SETTLED.
        """
        tutor, student, settled = setup_settled_session()
        assert settled["status"] == "SETTLED"
        open_dispute(
            session=settled,
            opener_headers=make_student_headers(student["id"]),
            requested_amount_cents=1000,
        )
        refreshed = validate_success(
            api.get_session(
                settled["id"], make_student_headers(student["id"]),
            ),
        )
        assert refreshed["status"] == "SETTLED"

    def test_dispute_window_closed_for_non_completed_session(self, api):
        """PRD §3.7: "The dispute must be opened ... against a session
        in COMPLETED or SETTLED; otherwise ERR_DISPUTE_WINDOW_CLOSED."

        Claim: opening a dispute on a CONFIRMED session returns
        ERR_DISPUTE_WINDOW_CLOSED.
        """
        from test_helpers import setup_confirmed_session
        tutor, student, confirmed = setup_confirmed_session()
        res = api.open_dispute(
            open_dispute_payload(
                session_id=confirmed["id"],
                requested_amount_cents=1000,
            ),
            make_student_headers(student["id"]),
        )
        validate_error(res, "ERR_DISPUTE_WINDOW_CLOSED")

    def test_requested_amount_above_charged_rejected(self, api):
        """PRD §3.7: "The requested amount must be strictly greater
        than zero and no greater than the session's
        charged_amount_cents; otherwise ERR_AMOUNT_OUT_OF_RANGE."

        Claim: requested_amount_cents > session.charged_amount_cents
        returns ERR_AMOUNT_OUT_OF_RANGE.
        """
        tutor, student, completed = setup_completed_session(
            hourly_rate_cents=6000, duration_minutes=60,
        )
        # charged_amount_cents == 6000; request 6001.
        res = api.open_dispute(
            open_dispute_payload(
                session_id=completed["id"],
                requested_amount_cents=6001,
            ),
            make_student_headers(student["id"]),
        )
        validate_error(res, "ERR_AMOUNT_OUT_OF_RANGE")

    def test_requested_amount_zero_rejected(self, api):
        """PRD §3.7: "The requested amount must be strictly greater
        than zero".

        Claim: requested_amount_cents=0 returns ERR_AMOUNT_OUT_OF_RANGE.
        """
        tutor, student, completed = setup_completed_session()
        res = api.open_dispute(
            open_dispute_payload(
                session_id=completed["id"],
                requested_amount_cents=0,
            ),
            make_student_headers(student["id"]),
        )
        validate_error(res, "ERR_AMOUNT_OUT_OF_RANGE")

    def test_second_dispute_rejected_while_first_open(self, api):
        """PRD §3.7: "At most one non-terminal dispute may exist per
        session at any time; a second attempt is rejected with
        ERR_DISPUTE_ALREADY_OPEN."

        Claim: a second dispute on the same session while the first
        is OPEN returns ERR_DISPUTE_ALREADY_OPEN.
        """
        tutor, student, completed = setup_completed_session()
        open_dispute(
            session=completed,
            opener_headers=make_student_headers(student["id"]),
            requested_amount_cents=1000,
        )
        res = api.open_dispute(
            open_dispute_payload(
                session_id=completed["id"],
                requested_amount_cents=500,
            ),
            make_student_headers(student["id"]),
        )
        validate_error(res, "ERR_DISPUTE_ALREADY_OPEN")


# ===========================================================================
# Cyclic respond / counter / reopen
# ===========================================================================
class TestDisputeCycle:
    def test_respond_moves_to_tutor_responded(self, api):
        """PRD §3.7: "The owning tutor responds via the respond action,
        which moves the dispute OPEN → TUTOR_RESPONDED".

        Claim: tutor /respond on OPEN dispute yields
        status=TUTOR_RESPONDED.
        """
        tutor, student, completed = setup_completed_session()
        d = open_dispute(
            session=completed,
            opener_headers=make_student_headers(student["id"]),
            requested_amount_cents=1000,
        )
        responded = respond_dispute(dispute=d, tutor=tutor)
        assert responded["status"] == "TUTOR_RESPONDED"

    def test_counter_increments_round_count(self, api):
        """PRD §3.7: "From TUTOR_RESPONDED, the tutor may submit a
        counter offer ... which moves the dispute TUTOR_RESPONDED →
        COUNTER_PROPOSED and increments round_count by 1."

        Claim: after counter, status=COUNTER_PROPOSED and
        round_count=1.

        # difficulty: non_linear_state_machine/refund_dispute_cyclic_open_counter_loop
        """
        tutor, student, completed = setup_completed_session()
        d = open_dispute(
            session=completed,
            opener_headers=make_student_headers(student["id"]),
            requested_amount_cents=1000,
        )
        respond_dispute(dispute=d, tutor=tutor)
        counter = counter_dispute(
            dispute=d, tutor=tutor, counter_amount_cents=500,
        )
        assert counter["status"] == "COUNTER_PROPOSED"
        assert counter["round_count"] == 1

    def test_counter_offer_above_requested_rejected(self, api):
        """PRD §3.7: "the offer must lie in the range 0 through
        requested_amount_cents inclusive — ERR_AMOUNT_OUT_OF_RANGE
        otherwise".

        Claim: counter_amount > requested_amount returns
        ERR_AMOUNT_OUT_OF_RANGE.
        """
        from test_helpers import counter_dispute_payload
        tutor, student, completed = setup_completed_session()
        d = open_dispute(
            session=completed,
            opener_headers=make_student_headers(student["id"]),
            requested_amount_cents=1000,
        )
        respond_dispute(dispute=d, tutor=tutor)
        res = api.counter_dispute(
            d["id"],
            counter_dispute_payload(counter_amount_cents=2000),
            make_tutor_headers(tutor["id"]),
        )
        validate_error(res, "ERR_AMOUNT_OUT_OF_RANGE")

    def test_reopen_returns_dispute_to_open(self, api):
        """PRD §3.7: "Reopening (the opener rejects the counter)
        transitions the dispute COUNTER_PROPOSED → OPEN".

        Claim: opener /reopen on COUNTER_PROPOSED yields status=OPEN.

        # difficulty: non_linear_state_machine/refund_dispute_cyclic_open_counter_loop
        """
        from test_helpers import reopen_dispute
        tutor, student, completed = setup_completed_session()
        d = open_dispute(
            session=completed,
            opener_headers=make_student_headers(student["id"]),
            requested_amount_cents=1000,
        )
        respond_dispute(dispute=d, tutor=tutor)
        counter_dispute(
            dispute=d, tutor=tutor, counter_amount_cents=500,
        )
        reopened = reopen_dispute(
            dispute=d, opener_headers=make_student_headers(student["id"]),
        )
        assert reopened["status"] == "OPEN"
        assert reopened["round_count"] == 1  # round count not reset


# ===========================================================================
# Accept counter (cascade DISPUTED → REFUNDED)
# ===========================================================================
class TestAcceptCounter:
    def test_accept_counter_pins_refund_and_cascades_refunded(self, api):
        """PRD §3.7: "Accepting transitions the dispute COUNTER_PROPOSED
        → RESOLVED_REFUND, pins resolved_refund_cents to the latest
        counter offer (which has already been bounded into the range
        0 through requested_amount_cents), and cascades the underlying
        session DISPUTED → REFUNDED."

        Claim: accept on COUNTER_PROPOSED yields dispute
        status=RESOLVED_REFUND, resolved_refund_cents=500, and the
        session moves to REFUNDED.
        """
        tutor, student, completed = setup_completed_session(
            hourly_rate_cents=6000, duration_minutes=60,
            adjusted_minutes=60,
        )
        d = open_dispute(
            session=completed,
            opener_headers=make_student_headers(student["id"]),
            requested_amount_cents=1000,
        )
        respond_dispute(dispute=d, tutor=tutor)
        counter_dispute(
            dispute=d, tutor=tutor, counter_amount_cents=500,
        )
        accepted = accept_dispute(
            dispute=d, opener_headers=make_student_headers(student["id"]),
        )
        assert accepted["status"] == "RESOLVED_REFUND"
        assert accepted["resolved_refund_cents"] == 500
        # Re-fetch session.
        refreshed = validate_success(
            api.get_session(
                completed["id"], make_student_headers(student["id"]),
            ),
        )
        assert refreshed["status"] == "REFUNDED"
        assert refreshed["arbitration_refund_cents"] == 500


# ===========================================================================
# Escalation
# ===========================================================================
class TestEscalation:
    def test_escalate_before_round_3_and_before_14d_rejected(self, api):
        """PRD §3.7: "The action is only permitted when round_count is
        at least 3 or the elapsed time since the dispute's created_at
        is at least 14 days. Any earlier escalation is rejected with
        ERR_ESCALATION_NOT_ALLOWED."

        Claim: escalating on OPEN with round_count=0 and age<14d
        returns ERR_ESCALATION_NOT_ALLOWED.
        """
        tutor, student, completed = setup_completed_session()
        d = open_dispute(
            session=completed,
            opener_headers=make_student_headers(student["id"]),
            requested_amount_cents=1000,
        )
        res = api.escalate_dispute(
            d["id"], make_student_headers(student["id"]),
        )
        validate_error(res, "ERR_ESCALATION_NOT_ALLOWED")


# ===========================================================================
# Arbitration — DENY
# ===========================================================================
class TestArbitrationDeny:
    def test_arbitrate_deny_cascades_session_to_settled(self, api):
        """PRD §3.7: "A DENY decision transitions the dispute
        ARBITRATION → RESOLVED_DENY, writes arbitrated_by, pins
        resolved_refund_cents to 0, and cascades the underlying
        session DISPUTED → SETTLED."

        Claim: arbiter DENY yields dispute=RESOLVED_DENY,
        resolved_refund_cents=0, session=SETTLED.
        """
        tutor, student, completed = setup_completed_session()
        d = open_dispute(
            session=completed,
            opener_headers=make_student_headers(student["id"]),
            requested_amount_cents=1000,
        )
        # Reach ARBITRATION via clock-driven 14-day timer.
        created_dt = parse_iso(d["created_at"])
        advance_clock_to(
            iso_utc(created_dt + timedelta(days=14, hours=1)),
        )
        # Re-fetch dispute.
        d_after = validate_success(
            api.get_dispute(d["id"], make_student_headers(student["id"])),
        )
        assert d_after["status"] == "ARBITRATION"
        resolved = arbitrate_dispute(
            dispute=d_after, decision="DENY",
        )
        assert resolved["status"] == "RESOLVED_DENY"
        assert resolved["resolved_refund_cents"] == 0
        refreshed_session = validate_success(
            api.get_session(
                completed["id"], make_student_headers(student["id"]),
            ),
        )
        assert refreshed_session["status"] == "SETTLED"

    def test_arbiter_cannot_be_session_tutor(self, api):
        """PRD §3.7: "The arbiter's X-User-ID must not equal the
        session's tutor_id ... any of these violations yields
        ERR_SEGREGATION_VIOLATION."

        Claim: arbiter id == session.tutor_id returns
        ERR_SEGREGATION_VIOLATION.
        """
        from test_helpers import arbitrate_dispute_payload
        tutor, student, completed = setup_completed_session()
        d = open_dispute(
            session=completed,
            opener_headers=make_student_headers(student["id"]),
            requested_amount_cents=1000,
        )
        # Drive to ARBITRATION.
        created_dt = parse_iso(d["created_at"])
        advance_clock_to(
            iso_utc(created_dt + timedelta(days=14, hours=1)),
        )
        res = api.arbitrate_dispute(
            d["id"],
            arbitrate_dispute_payload(decision="DENY"),
            make_arbiter_headers(tutor["id"]),
        )
        validate_error(res, "ERR_SEGREGATION_VIOLATION")


# ===========================================================================
# Arbitration — REFUND with FINAL_AFTER_REFUND recompute
# ===========================================================================
class TestArbitrationRefund:
    def test_arbitrate_refund_recomputes_payout_and_commission(self, api):
        """PRD §3.7: "arbitration_refund_cents is set to the dispute's
        resolved_refund_cents ... a service-revenue-retained quantity
        equal to the maximum of zero and actual_gross_cents minus
        arbitration_refund_cents is computed; final_commission_cents
        is recomputed using the commission rule with the
        FINAL_AFTER_REFUND variant, billing commission only on this
        retained portion ... tutor_payout_cents is re-pinned to
        service-revenue-retained minus this new final_commission_cents,
        clamped to zero or greater."

        Claim: with actual_gross=6000, lifetime tier 0 (20%), arbitrate
        REFUND amount=2000 yields refund_to_student total=2000,
        service_revenue_retained=4000, final_commission=800,
        tutor_payout=3200. Money invariant holds.

        # difficulty: compensating_invariant/per_session_money_conservation_on_refund_cascade
        """
        # Use 60-min/60-min completion so actual_gross == gross == 6000.
        tutor, student, completed = setup_completed_session(
            hourly_rate_cents=6000, duration_minutes=60,
            adjusted_minutes=60,
        )
        assert completed["actual_gross_cents"] == 6000
        d = open_dispute(
            session=completed,
            opener_headers=make_student_headers(student["id"]),
            requested_amount_cents=2000,
        )
        created_dt = parse_iso(d["created_at"])
        advance_clock_to(
            iso_utc(created_dt + timedelta(days=14, hours=1)),
        )
        # Confirm reached ARBITRATION.
        d_after = validate_success(
            api.get_dispute(d["id"], make_student_headers(student["id"])),
        )
        assert d_after["status"] == "ARBITRATION"
        arbitrate_dispute(
            dispute=d_after, decision="REFUND",
            refund_amount_cents=2000,
        )
        refreshed_session = validate_success(
            api.get_session(
                completed["id"], make_student_headers(student["id"]),
            ),
        )
        assert refreshed_session["status"] == "REFUNDED"
        assert refreshed_session["arbitration_refund_cents"] == 2000
        # refund_to_student total includes arbitration refund (and any
        # short-delivery refund from COMPLETED; here that's 0).
        assert refreshed_session["refund_to_student_cents"] == 2000
        # service_revenue_retained = 6000 - 2000 = 4000
        # final_commission = round(4000 * 0.20) = 800
        assert refreshed_session["final_commission_cents"] == 800
        # tutor_payout = 4000 - 800 = 3200
        assert refreshed_session["tutor_payout_cents"] == 3200
        assert_money_conservation_invariant(refreshed_session)


# ===========================================================================
# Withdraw
# ===========================================================================
class TestWithdraw:
    def test_withdraw_from_open_within_hold_window_returns_to_completed(
        self, api,
    ):
        """PRD §3.7: "on withdraw, the cascaded session goes
        DISPUTED → SETTLED if the 72-hour hold window has already
        elapsed since end_at, or DISPUTED → COMPLETED if the session
        is still inside the hold window."

        Claim: withdraw on dispute inside hold window cascades session
        back to COMPLETED (not SETTLED).
        """
        tutor, student, completed = setup_completed_session()
        # We are at end_at + 1min — well within 72h.
        d = open_dispute(
            session=completed,
            opener_headers=make_student_headers(student["id"]),
            requested_amount_cents=1000,
        )
        withdrawn = withdraw_dispute(
            dispute=d, opener_headers=make_student_headers(student["id"]),
        )
        assert withdrawn["status"] == "WITHDRAWN"
        refreshed_session = validate_success(
            api.get_session(
                completed["id"], make_student_headers(student["id"]),
            ),
        )
        assert refreshed_session["status"] == "COMPLETED"
