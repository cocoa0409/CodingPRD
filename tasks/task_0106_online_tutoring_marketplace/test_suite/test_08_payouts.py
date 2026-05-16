"""Payout batch lifecycle, segregation of duties, stale balance.

Covers PRD §3.6: settlement and payout batch creation, mark-paid by a
different admin, reverse, ERR_PAYOUT_STALE on balance drift.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    advance_clock_to,
    assert_payout_batch,
    create_payout,
    iso_utc,
    make_admin_headers,
    make_tutor_headers,
    mark_payout_paid,
    parse_iso,
    server_now_dt,
    setup_settled_session,
    setup_completed_session,
    validate_error,
    validate_success,
)


# ===========================================================================
# PayoutBatch creation
# ===========================================================================
class TestCreatePayout:
    def test_create_payout_snapshots_balance_and_sessions(self, api,
                                                          admin_headers):
        """PRD §3.6: "At creation, the server snapshots the tutor's
        current payout_balance_cents into the batch's amount_cents
        and snapshots into session_ids the ids of every SETTLED
        Session for that tutor whose tutor_payout_cents contributes
        to the snapshot".

        Claim: with one SETTLED session, the batch's amount_cents
        equals the tutor's current payout_balance_cents and
        session_ids includes the session.
        """
        tutor, student, settled = setup_settled_session(
            hourly_rate_cents=6000, duration_minutes=60,
            adjusted_minutes=60,
        )
        # Re-fetch tutor.
        tutor_after = validate_success(
            api.get_tutor(tutor["id"], TEST_USERS["admin_headers"]),
        )
        expected_balance = tutor_after["payout_balance_cents"]
        assert expected_balance > 0
        batch = create_payout(tutor=tutor_after)
        assert_payout_batch(batch)
        assert batch["status"] == "REQUESTED"
        assert batch["amount_cents"] == expected_balance
        assert settled["id"] in batch["session_ids"]
        assert batch["requested_by"] == TEST_USERS["admin_headers"][
            "X-User-ID"
        ]


# ===========================================================================
# Mark-paid segregation of duties
# ===========================================================================
class TestMarkPaidSegregation:
    def test_same_admin_cannot_mark_paid(self, api, admin_headers):
        """PRD §3.6: "A different PlatformAdmin (whose X-User-ID
        differs from requested_by — ERR_SEGREGATION_VIOLATION
        otherwise) marks the batch paid".

        Claim: mark-paid by the same admin who requested returns
        ERR_SEGREGATION_VIOLATION.
        """
        tutor, _student, _settled = setup_settled_session()
        tutor_after = validate_success(
            api.get_tutor(tutor["id"], admin_headers),
        )
        batch = create_payout(tutor=tutor_after)
        res = api.mark_payout_paid(batch["id"], admin_headers)
        validate_error(res, "ERR_SEGREGATION_VIOLATION")

    def test_different_admin_can_mark_paid(self, api, admin_headers,
                                           admin_headers_alt):
        """PRD §3.6: "marks the batch paid, which transitions it
        REQUESTED → PAID and decrements the tutor's
        payout_balance_cents by amount_cents."

        Claim: mark-paid by a distinct admin yields status=PAID and
        decrements tutor's payout_balance_cents.
        """
        tutor, _student, _settled = setup_settled_session()
        tutor_after = validate_success(
            api.get_tutor(tutor["id"], admin_headers),
        )
        original_balance = tutor_after["payout_balance_cents"]
        batch = create_payout(tutor=tutor_after)
        paid = mark_payout_paid(payout=batch, payer_headers=admin_headers_alt)
        assert paid["status"] == "PAID"
        # Re-fetch tutor.
        tutor_post = validate_success(
            api.get_tutor(tutor["id"], admin_headers),
        )
        assert (
            tutor_post["payout_balance_cents"]
            == original_balance - batch["amount_cents"]
        )


# ===========================================================================
# Reverse
# ===========================================================================
class TestReverse:
    def test_reverse_requested_batch_no_balance_change(self, api,
                                                      admin_headers):
        """PRD §3.6: "any PlatformAdmin may reverse a REQUESTED batch,
        which transitions it REQUESTED → REVERSED with no balance
        change (the balance was never decremented at REQUESTED in the
        first place)."

        Claim: reverse a REQUESTED batch yields status=REVERSED and
        tutor balance is unchanged.
        """
        tutor, _student, _settled = setup_settled_session()
        tutor_after = validate_success(
            api.get_tutor(tutor["id"], admin_headers),
        )
        original_balance = tutor_after["payout_balance_cents"]
        batch = create_payout(tutor=tutor_after)
        reversed_resp = validate_success(
            api.reverse_payout(batch["id"], admin_headers),
        )
        assert reversed_resp["status"] == "REVERSED"
        tutor_post = validate_success(
            api.get_tutor(tutor["id"], admin_headers),
        )
        assert tutor_post["payout_balance_cents"] == original_balance


# ===========================================================================
# Stale balance — PRD §3.6
# ===========================================================================
class TestPayoutStale:
    def test_mark_paid_after_balance_drift_returns_stale(
        self, api, admin_headers, admin_headers_alt,
    ):
        """PRD §3.6: "The marked-paid step is rejected with
        ERR_PAYOUT_STALE if the tutor's current payout_balance_cents
        no longer equals what the batch was sized against (this
        happens when a refund landed between request and mark-paid,
        changing the balance)."

        Claim: a payout is created; a fresh SETTLED session lands
        before mark-paid (raising tutor balance); mark-paid then
        returns ERR_PAYOUT_STALE.
        """
        # Build a tutor with one SETTLED session and create the batch.
        tutor, student, settled1 = setup_settled_session(
            hourly_rate_cents=6000, duration_minutes=60,
            adjusted_minutes=60,
        )
        tutor_after = validate_success(
            api.get_tutor(tutor["id"], admin_headers),
        )
        batch = create_payout(tutor=tutor_after)
        # Now produce another SETTLED session for the same tutor to
        # raise payout_balance_cents above batch.amount_cents.
        from test_helpers import (
            advance_clock_by,
            book_session,
            complete_session,
            confirm_session,
            create_adult_student,
            parse_iso as _parse,
        )
        other_student = create_adult_student()
        # Book + confirm + complete + advance for settlement.
        s2 = book_session(
            tutor=tutor_after, student=other_student, duration_minutes=60,
            start_offset_hours=12.0,
        )
        confirm_session(session=s2, tutor=tutor_after)
        from test_helpers import advance_clock_past_session_end
        advance_clock_past_session_end(s2)
        complete_session(session=s2, tutor=tutor_after, adjusted_minutes=60)
        # Advance >=72h past s2.end_at to settle s2.
        end_dt = _parse(s2["end_at"])
        advance_clock_to(iso_utc(end_dt + timedelta(hours=73)))
        # Now mark-paid the original batch — balance has drifted upward.
        res = api.mark_payout_paid(batch["id"], admin_headers_alt)
        validate_error(res, "ERR_PAYOUT_STALE")


# ===========================================================================
# Settlement hold (PRD §3.6) — sweep behavior verified
# ===========================================================================
class TestSettlementHold:
    def test_completed_session_stays_completed_inside_72h_hold(self, api):
        """PRD §3.6: "A COMPLETED session enters its hold window: it
        cannot pay out to the tutor until 72 hours of wall-clock time
        have elapsed since end_at and no RefundDispute is in any
        non-terminal state for that session."

        Claim: advancing the clock by 71h after end_at does NOT move
        the session to SETTLED.
        """
        tutor, student, completed = setup_completed_session()
        end_dt = parse_iso(completed["end_at"])
        # advance to end+71h
        advance_clock_to(iso_utc(end_dt + timedelta(hours=71)))
        from test_helpers import make_student_headers
        refreshed = validate_success(
            api.get_session(
                completed["id"], make_student_headers(student["id"]),
            ),
        )
        assert refreshed["status"] == "COMPLETED"
