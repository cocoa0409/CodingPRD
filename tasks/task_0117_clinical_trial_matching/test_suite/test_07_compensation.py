"""Compensation — provisional accrual, finalization, reversal, and the
re-consent bonus.

PRD §3.8 (Payment kinds and amounts), §2.9 (window semantics for the
late-day penalty), §3.7 (REVERSAL on withdrawal cascade).
"""
from __future__ import annotations

from typing import Dict, List

import pytest

from test_helpers import (
    BASE_VISIT_CENTS,
    LATE_PENALTY_CENTS,
    ON_TIME_BONUS_CENTS,
    RE_CONSENT_BONUS_CENTS,
    TEST_USERS,
    advance_clock_to,
    assert_payment,
    complete_participant,
    complete_visit,
    iso_anchor_offset,
    list_payments,
    schedule_visit,
    setup_enrolled_participant,
    setup_enrolled_with_one_completed_visit,
    setup_participant_with_three_on_time_visits_after_reconsent,
    validate_error,
    validate_success,
    withdraw_participant,
)


# ===========================================================================
# §3.8 per-visit tiers — d == 0 / 1..2 / 3..window.
# ===========================================================================
class TestProvisionalCompensationTiers:
    """PRD §3.8 tiered per-visit bonus."""

    def test_grace_period_d_equals_1_yields_base_only(self, api):
        """PRD §3.8: "When d is 1 or 2 — within a two-day grace period
        — the bonus is zero."

        Claim: a draw one day late yields compensation_cents ==
        BASE_VISIT_CENTS (5000) with no bonus.
        """
        trial, p, _arms = setup_enrolled_participant(
            blood_draw_window_days=7,
        )
        v = schedule_visit(
            p["id"], sequence_no=1,
            target_date=iso_anchor_offset(days=10),
        )
        # d = 1: draw on day 11.
        advance_clock_to(iso_anchor_offset(days=11, hours=12))
        completed = complete_visit(
            v["id"],
            actual_draw_at=iso_anchor_offset(days=11, hours=12),
        )
        assert completed["compensation_cents"] == BASE_VISIT_CENTS

    def test_late_d_equals_3_subtracts_one_day_penalty(self, api):
        """PRD §3.8: "When d is at least 3 and at most
        blood_draw_window_days — late but still within the window —
        the bonus is negative: the late-day penalty of 750 cents is
        multiplied by the number of days past the grace period,
        computed as (d - 2). So a draw 3 days off target carries a
        750-cent penalty".

        Claim: a draw 3 days off yields compensation = 5000 - 750 =
        4250.
        """
        trial, p, _arms = setup_enrolled_participant(
            blood_draw_window_days=7,
        )
        v = schedule_visit(
            p["id"], sequence_no=1,
            target_date=iso_anchor_offset(days=10),
        )
        advance_clock_to(iso_anchor_offset(days=13, hours=12))
        completed = complete_visit(
            v["id"],
            actual_draw_at=iso_anchor_offset(days=13, hours=12),
        )
        assert completed["compensation_cents"] == (
            BASE_VISIT_CENTS - LATE_PENALTY_CENTS
        )

    def test_late_d_equals_window_uses_full_penalty(self, api):
        """PRD §3.8: "4 days off carries a 1500-cent penalty, and so
        on, scaling linearly with each additional day past day 2."

        Claim: d=7 with window=7 yields 5000 + (-750 * 5) = 1250.
        """
        trial, p, _arms = setup_enrolled_participant(
            blood_draw_window_days=7,
        )
        v = schedule_visit(
            p["id"], sequence_no=1,
            target_date=iso_anchor_offset(days=10),
        )
        advance_clock_to(iso_anchor_offset(days=17, hours=12))
        completed = complete_visit(
            v["id"],
            actual_draw_at=iso_anchor_offset(days=17, hours=12),
        )
        expected = BASE_VISIT_CENTS + (-LATE_PENALTY_CENTS * (7 - 2))
        assert completed["compensation_cents"] == expected
        assert completed["compensation_cents"] == 1250

    def test_provisional_payment_row_matches_compensation_cents(
        self, api,
    ):
        """PRD §3.6: "Visit.compensation_cents := <computed by
        participant_compensation, provisional variant>; Create Payment
        row with kind=PROVISIONAL, amount_cents=Visit.compensation_cents".
        PRD §3.8: "the PROVISIONAL Payment row written with paid_at of
        null".

        Claim: after a visit-complete, exactly one PROVISIONAL Payment
        row exists with amount_cents == visit.compensation_cents and
        paid_at null.
        """
        trial, p, v, pmt = setup_enrolled_with_one_completed_visit(
            blood_draw_window_days=7,
        )
        assert_payment(pmt)
        assert pmt["kind"] == "PROVISIONAL"
        assert pmt["amount_cents"] == v["compensation_cents"]
        assert pmt.get("paid_at") is None


# ===========================================================================
# §3.8 finalization — FINAL rows and the re-consent bonus.
# ===========================================================================
class TestFinalization:
    """PRD §3.8 final-variant compensation."""

    def test_complete_participant_writes_final_rows_and_re_consent_bonus(
        self, api,
    ):
        """PRD §3.8: "for each visit whose status is COMPLETED and
        which still holds a PROVISIONAL payment row, the server writes
        a new FINAL Payment row whose amount_cents equals the
        provisional amount unchanged, and stamps paid_at with the
        current logical clock instant."

        PRD §3.8: "a re-consent bonus of 2500 cents is allocated to
        the last chronological COMPLETED visit, where 'last' is
        determined by the visit's sequence_no, taking the maximum
        sequence_no".

        Claim: a participant with three on-time COMPLETED visits and a
        v1->v2 re-consent has exactly 3 FINAL rows, of which the one
        for the largest-sequence_no visit carries the +2500 bonus,
        and the sum of FINAL rows equals 6000*3 + 2500 = 20500.
        """
        trial, p, visits = (
            setup_participant_with_three_on_time_visits_after_reconsent()
        )
        complete_participant(p["id"])

        finals = list_payments(p["id"], kind="FINAL")
        assert len(finals) == 3, (
            f"expected 3 FINAL rows; got {len(finals)}"
        )

        # Map visit_id -> sequence_no for the three visits.
        seq_by_visit: Dict[str, int] = {
            v["id"]: v["sequence_no"] for v in visits
        }
        last_seq_visit_id = max(
            seq_by_visit, key=lambda vid: seq_by_visit[vid],
        )

        bonus_rows = [f for f in finals if f["amount_cents"] == 8500]
        normal_rows = [f for f in finals if f["amount_cents"] == 6000]
        assert len(bonus_rows) == 1, (
            f"expected exactly 1 FINAL with +2500 bonus (amount 8500); "
            f"got {len(bonus_rows)}"
        )
        assert len(normal_rows) == 2, (
            f"expected 2 FINAL rows at 6000 each; "
            f"got {len(normal_rows)}"
        )
        assert bonus_rows[0]["visit_id"] == last_seq_visit_id, (
            "the +2500 bonus must land on the visit with the largest "
            "sequence_no per PRD §3.8."
        )
        assert sum(f["amount_cents"] for f in finals) == 20500
        for f in finals:
            assert f.get("paid_at") is not None, (
                "PRD §3.8: every FINAL row sets paid_at on commit."
            )

    def test_provisional_rows_remain_after_finalization(self, api):
        """PRD §3.8: "The earlier PROVISIONAL rows remain as audit
        history; the sum of PROVISIONAL rows is not what gets paid,
        only the sum of FINAL rows is."

        Claim: after participant-complete, the three PROVISIONAL rows
        still exist alongside the three FINAL rows; sum(PROVISIONAL)
        is 6000 * 3 = 18000.
        """
        trial, p, _visits = (
            setup_participant_with_three_on_time_visits_after_reconsent()
        )
        complete_participant(p["id"])
        all_pmts = list_payments(p["id"])
        provisionals = [r for r in all_pmts if r["kind"] == "PROVISIONAL"]
        finals = [r for r in all_pmts if r["kind"] == "FINAL"]
        assert len(provisionals) == 3
        assert len(finals) == 3
        assert sum(r["amount_cents"] for r in provisionals) == 18000


# ===========================================================================
# §3.7 withdrawal — REVERSAL rows for cancelled visits holding
# PROVISIONAL payments.
# ===========================================================================
class TestReversalOnWithdrawal:
    """PRD §3.7 / §3.8 REVERSAL emission."""

    def test_withdraw_does_not_emit_reversal_for_uncompleted_visit(
        self, api,
    ):
        """PRD §3.7: "For each visit cascaded to CANCELLED that holds
        a PROVISIONAL payment, the server writes a REVERSAL Payment
        row with a negated amount_cents."

        Claim: when a SCHEDULED visit (no PROVISIONAL row yet) is
        cascaded to CANCELLED on withdraw, no REVERSAL row is written.
        """
        trial, p, _arms = setup_enrolled_participant(
            blood_draw_window_days=7,
        )
        schedule_visit(
            p["id"], sequence_no=1,
            target_date=iso_anchor_offset(days=10),
        )
        withdraw_participant(p["id"])
        pmts = list_payments(p["id"])
        assert all(r["kind"] != "REVERSAL" for r in pmts), (
            "no PROVISIONAL existed, so no REVERSAL must exist either"
        )
