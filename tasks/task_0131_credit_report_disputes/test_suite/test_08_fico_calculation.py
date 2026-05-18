"""PRD §3.5 — FICO calculation (final vs provisional).

Covers:
- Initial fico_score = 300 on a freshly created report (already in
  test_02 — here we exercise the recompute path).
- DELETED tradelines are excluded; empty T -> payment-history 100,
  utilization 100.
- Single-item portfolio: mix component = 50.
- DELETED -> fico_score recomputes (CLOSED_DELETED branch).
- /projected_fico vs /credit_reports/{id}:
    * provisional: assumes in-flight dispute resolves in consumer's
      favor (DELETE_ITEM -> treat as DELETED).
    * final: stored score on CLOSED_VERIFIED reflects no change.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    FICO_MAX,
    FICO_MIN,
    TEST_USERS,
    advance_clock,
    assert_fico_score,
    close_dispute_deleted,
    close_dispute_verified,
    get_credit_report,
    make_consumer_headers,
    setup_consumer_furnisher_report_tradeline,
    setup_dispute_in_state,
    start_investigation,
    submit_dispute,
    validate_success,
)


# ===========================================================================
# Score range — PRD §3.5
# ===========================================================================
class TestScoreRange:

    def test_score_clamped_within_300_to_850(self, api):
        """PRD §3.5: 'the result is clamped to the inclusive range
        from 300 to 850.'

        With any combination of tradelines, the stored fico_score
        must lie in [300, 850]."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline(
            balance_cents=1_000_000_000, payment_status="LATE_90",
        )
        r_after = get_credit_report(c["id"], r["id"])
        assert_fico_score(r_after["fico_score"])

    def test_empty_tradeline_set_after_delete_yields_max_score(self, api):
        """PRD §3.5: 'If T is empty after the deletion exclusion, the
        payment-history component is defined to be 100 rather than
        undefined.' and 'If T is empty, the utilization score is
        defined to be 100.' and 'The mix component is 50 when T
        contains exactly one item — penalizing single-item portfolios
        for lack of mix — and 100 otherwise.'

        Empty T -> all components evaluate to their defined values:
        payment_history=100, utilization=100, age=100, mix=100
        (per 'and 100 otherwise'), inquiries=100. raw = 0.35*100 +
        0.30*100 + 0.15*100 + 0.10*100 + 0.10*100 = 100.
        fico_score = round_half_up(300 + 5.5*100) = round_half_up(850)
        = 850.

        We reach empty T by creating exactly ONE tradeline then closing
        the dispute as DELETED — the lone tradeline is excluded from T
        (its payment_status becomes DELETED per §3.4)."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline()
        close_dispute_deleted(consumer=c, report=r, tradeline=t)
        r_after = get_credit_report(c["id"], r["id"])
        assert r_after["fico_score"] == FICO_MAX


# ===========================================================================
# Single-item mix penalty — PRD §3.5
# ===========================================================================
class TestMixComponent:

    def test_single_tradeline_recomputes_below_max(self, api):
        """PRD §3.5: 'The mix component is 50 when T contains exactly
        one item — penalizing single-item portfolios for lack of mix
        — and 100 otherwise.'

        A LATE_90 single tradeline at balance 500_000 cents:
          - payment_history = 0.35 * 20 = 7
          - utilization: total_balance=500_000; denom=1*1_000_000=
            1_000_000; util_pct=50; util_score=50; weighted=15
          - age = 0.15 * 100 = 15
          - mix = 0.10 * 50 = 5
          - inquiries = 0.10 * 100 = 10
          raw = 7 + 15 + 15 + 5 + 10 = 52
          fico = round_half_up(300 + 5.5 * 52) = round_half_up(586) = 586"""
        c, f, r, t = setup_consumer_furnisher_report_tradeline(
            balance_cents=500_000, payment_status="LATE_90",
        )
        r_after = get_credit_report(c["id"], r["id"])
        assert r_after["fico_score"] == 586


# ===========================================================================
# Provisional vs final — PRD §3.5
# ===========================================================================
class TestProvisionalVsFinal:

    def test_projected_fico_assumes_delete_for_delete_item(self, api):
        """PRD §3.5: 'The provisional variant is what a consumer sees
        when invoking the projected-FICO retrieval against a report
        that currently has at least one dispute in a non-terminal
        status: the calculation simulates the in-flight dispute
        resolving in the consumer's favor by ... when the
        requested_action is DELETE_ITEM — by treating the targeted
        tradeline as if its payment_status were DELETED. The
        provisional variant always includes the in-flight dispute's
        projected outcome, even when no FurnisherInquiry response yet
        exists.'

        Setup: one LATE_90 tradeline. Submit DELETE_ITEM dispute.
        Provisional FICO treats T as empty -> 850 (per
        empty-T-yields-max above)."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline(
            balance_cents=500_000, payment_status="LATE_90",
        )
        d = submit_dispute(
            consumer=c, report=r, tradeline=t,
            requested_action="DELETE_ITEM",
            requested_payload={},
        )
        # start_investigation creates the FurnisherInquiry but the
        # provisional variant applies even before any response.
        start_investigation(consumer_id=c["id"], dispute_id=d["id"])
        res = api.get_projected_fico(
            c["id"], r["id"], make_consumer_headers(c["id"]),
        )
        body = validate_success(res, 200)
        assert body["fico_score"] == FICO_MAX

    def test_final_fico_on_closed_verified_reflects_no_change(self, api):
        """PRD §3.5: 'The final variant is what is persisted to
        CreditReport.fico_score on every CLOSED_* dispute transition;
        it uses only post-transition (committed) tradeline state with
        the actual furnisher response applied. If the in-flight
        dispute closed VERIFIED, the targeted tradeline is unchanged'.

        After CLOSED_VERIFIED the stored fico_score reflects the
        unchanged single LATE_90 tradeline -> 586 (per single-item
        calculation above)."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline(
            balance_cents=500_000, payment_status="LATE_90",
        )
        close_dispute_verified(consumer=c, report=r, tradeline=t)
        r_after = get_credit_report(c["id"], r["id"])
        assert r_after["fico_score"] == 586

    def test_provisional_and_final_differ_for_delete_item_then_verified(self, api):
        """PRD §3.5: 'For identical inputs ... provisional fico_score
        = 850 and final fico_score = 586 — same data, two algorithms,
        different numbers.' (paraphrased; the distinguishing-aspect
        is named in PRD §3.5 prose: '... different combination of
        side effects ... same data, two algorithms'.)

        Concretely: in-flight DELETE_ITEM -> projected=850; then
        furnisher VERIFIED -> CLOSED_VERIFIED final=586."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline(
            balance_cents=500_000, payment_status="LATE_90",
        )
        d = submit_dispute(
            consumer=c, report=r, tradeline=t,
            requested_action="DELETE_ITEM",
            requested_payload={},
        )
        start_investigation(consumer_id=c["id"], dispute_id=d["id"])
        # Provisional FICO before closure.
        res = api.get_projected_fico(
            c["id"], r["id"], make_consumer_headers(c["id"]),
        )
        provisional = validate_success(res, 200)["fico_score"]
        # Close VERIFIED (no change to tradeline).
        from test_helpers import (
            issue_result_notice,
            record_furnisher_response,
            get_dispute,
        )
        record_furnisher_response(
            consumer_id=c["id"], dispute_id=d["id"],
            response="VERIFIED", response_payload={},
        )
        issue_result_notice(consumer_id=c["id"], dispute_id=d["id"])
        r_after = get_credit_report(c["id"], r["id"])
        final = r_after["fico_score"]
        # Provisional treats T as empty -> 850; final keeps LATE_90 -> 586.
        assert provisional == 850
        assert final == 586
        assert provisional != final


# ===========================================================================
# Recompute on CLOSED_DELETED — PRD §3.4 (fico recompute) + §3.5
# ===========================================================================
class TestFicoRecomputeOnClose:

    def test_fico_recomputes_on_closed_deleted(self, api):
        """PRD §3.4 deleted branch: 'the owning report's fico_score is
        then recomputed per §3.5.'

        Pre: 586 (one LATE_90). Post DELETED close: 850 (empty T)."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline(
            balance_cents=500_000, payment_status="LATE_90",
        )
        before = get_credit_report(c["id"], r["id"])
        assert before["fico_score"] == 586
        close_dispute_deleted(consumer=c, report=r, tradeline=t)
        after = get_credit_report(c["id"], r["id"])
        assert after["fico_score"] == FICO_MAX
