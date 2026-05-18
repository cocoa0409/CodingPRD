"""Signup bonus qualification and the 90-day window — PRD §3.1.

Coverage:
- A purchase totalling exactly $3000 (300,000 cents) inside the window
  qualifies and awards the 60,000-point bonus.
- $2999.99 (299,999 cents) does NOT qualify; signup_bonus_state stays
  PENDING.
- A purchase posted at exactly signup_bonus_deadline_at (half-open
  upper bound) does NOT count toward qualifying spend.
- A purchase posted at 1 ms before the deadline DOES count.
- Refunds inside the window deduct from qualifying spend (and can
  unwind a near-miss).
- Sweep after the deadline transitions PENDING -> EXPIRED without a
  ledger entry.
- AWARDED bonus emits a SIGNUP_BONUS ledger row with delta_points
  == +60000.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    SIGNUP_BONUS_POINTS,
    SIGNUP_MIN_SPEND_CENTS,
    advance_clock_to,
    create_cardholder_and_account,
    find_ledger_entries,
    get_ledger,
    iso_instant_utc,
    post_purchase,
    re_get_account,
    register_fixed_bonus_category,
    run_sweep,
    setup_clock_at,
)


# ===========================================================================
# Exact-boundary qualification — PRD §3.1
# ===========================================================================
class TestSignupBonusBoundary:
    """PRD §3.1 SIGNUP_MIN_SPEND_CENTS at-or-greater-than threshold."""

    def test_exact_minimum_qualifies(self, api):
        """PRD §3.1: "When signup_bonus_state is PENDING and the
        qualifying total is at least three thousand dollars (three
        hundred thousand cents) — the comparison is at-or-greater-than,
        so exactly three thousand dollars triggers but two thousand
        nine hundred ninety-nine dollars and ninety-nine cents does not
        — the bonus is awarded immediately as described."

        Claim: a single 300,000-cent PURCHASE inside the signup window
        transitions signup_bonus_state to AWARDED.
        """
        setup_clock_at(2026, 1, 2)
        ch, acc = create_cardholder_and_account()
        cat = register_fixed_bonus_category(base_rate_bps=500)
        post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"],
            amount_cents=SIGNUP_MIN_SPEND_CENTS,
        )
        acc_after = re_get_account(acc["id"])
        assert acc_after["signup_bonus_state"] == "AWARDED", (
            f"expected signup_bonus_state==AWARDED at exactly "
            f"{SIGNUP_MIN_SPEND_CENTS} cents, got "
            f"{acc_after['signup_bonus_state']}"
        )

    def test_one_cent_below_minimum_does_not_qualify(self, api):
        """PRD §3.1: "exactly three thousand dollars triggers but two
        thousand nine hundred ninety-nine dollars and ninety-nine cents
        does not".

        Claim: a 299,999-cent PURCHASE inside the window leaves
        signup_bonus_state at PENDING (no bonus booked).
        """
        setup_clock_at(2026, 1, 2)
        ch, acc = create_cardholder_and_account()
        cat = register_fixed_bonus_category(base_rate_bps=500)
        post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"],
            amount_cents=SIGNUP_MIN_SPEND_CENTS - 1,
        )
        acc_after = re_get_account(acc["id"])
        assert acc_after["signup_bonus_state"] == "PENDING", (
            f"expected signup_bonus_state==PENDING at "
            f"{SIGNUP_MIN_SPEND_CENTS - 1} cents (one under), got "
            f"{acc_after['signup_bonus_state']}"
        )

    def test_awarded_emits_signup_bonus_ledger_row(self, api):
        """PRD §3.1: "Awarding deposits sixty thousand points to the
        ledger as a single SIGNUP_BONUS entry whose delta_points is
        positive sixty thousand, and the Account's points_balance
        recomputes accordingly."

        Claim: after qualification, exactly one SIGNUP_BONUS ledger row
        exists with delta_points == +60000.
        """
        setup_clock_at(2026, 1, 2)
        ch, acc = create_cardholder_and_account()
        cat = register_fixed_bonus_category(base_rate_bps=500)
        post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"],
            amount_cents=SIGNUP_MIN_SPEND_CENTS,
        )
        ledger = get_ledger(acc["id"])
        bonus_rows = find_ledger_entries(
            ledger, entry_type="SIGNUP_BONUS",
        )
        assert len(bonus_rows) == 1, (
            f"expected exactly 1 SIGNUP_BONUS row, got {len(bonus_rows)}"
        )
        assert bonus_rows[0]["delta_points"] == SIGNUP_BONUS_POINTS


# ===========================================================================
# Window half-open semantics — PRD §3.1 / §2.12
# ===========================================================================
class TestSignupWindowHalfOpen:
    """PRD §3.1 [opened_at, signup_bonus_deadline_at) half-open."""

    def test_post_at_deadline_excluded(self, api):
        """PRD §3.1: "whose posted_at is at or after opened_at and
        strictly before signup_bonus_deadline_at".
        PRD §2.12: "The signup window of an Account is the half-open
        interval beginning at opened_at (inclusive) and ending at
        signup_bonus_deadline_at (exclusive), where
        signup_bonus_deadline_at is precisely 90 days after opened_at."

        Claim: a PURCHASE posted at posted_at == signup_bonus_deadline_at
        does NOT count toward signup_bonus_qualifying_spend_cents.
        """
        setup_clock_at(2026, 1, 1)
        ch, acc = create_cardholder_and_account()
        cat = register_fixed_bonus_category(base_rate_bps=500)
        # 90 days after 2026-01-01T00:00:00Z is 2026-04-01T00:00:00Z.
        advance_clock_to("2026-04-01T00:00:00.000Z")
        post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"],
            amount_cents=SIGNUP_MIN_SPEND_CENTS,
        )
        acc_after = re_get_account(acc["id"])
        # The purchase at exactly the deadline is excluded — the
        # qualifying total remains 0.
        assert (
            acc_after["signup_bonus_qualifying_spend_cents"] == 0
        ), (
            f"a PURCHASE at posted_at==signup_bonus_deadline_at must be "
            f"excluded; got qualifying_spend = "
            f"{acc_after['signup_bonus_qualifying_spend_cents']}"
        )

    def test_post_one_ms_before_deadline_qualifies(self, api):
        """PRD §3.1: "whose posted_at is at or after opened_at and
        strictly before signup_bonus_deadline_at" + PRD §3.1's
        at-or-greater-than threshold.

        Claim: a PURCHASE posted one millisecond before
        signup_bonus_deadline_at DOES count, and at exactly the minimum
        triggers AWARDED.
        """
        setup_clock_at(2026, 1, 1)
        ch, acc = create_cardholder_and_account()
        cat = register_fixed_bonus_category(base_rate_bps=500)
        # One millisecond before 2026-04-01T00:00:00Z.
        advance_clock_to("2026-03-31T23:59:59.999Z")
        post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"],
            amount_cents=SIGNUP_MIN_SPEND_CENTS,
        )
        acc_after = re_get_account(acc["id"])
        assert acc_after["signup_bonus_state"] == "AWARDED", (
            f"a PURCHASE one ms before the deadline must qualify; got "
            f"{acc_after['signup_bonus_state']}"
        )


# ===========================================================================
# Refund interaction — PRD §3.1
# ===========================================================================
# NOTE: The test that previously lived here
# (test_refund_inside_window_deducts_qualifying_spend) was DELETED because PRD
# §3.1 does not uniquely determine the post-refund signup_bonus_qualifying_
# spend_cents in the unwind-a-near-miss scenario:
#
#   * Reading A — PRD §3.1's formula, literal: qualifying = sum(amount over
#     PURCHASE rows whose status is POSTED in window) - sum(REFUND amount in
#     window). PRD §3.4 flips the original purchase to REVERSED on refund, so
#     the refunded purchase drops out of the first sum AND the refund row is
#     added to the second sum, producing 200,000 - 99,000 = 101,000.
#   * Reading B — PRD §3.1's prose intent ("unwind a near-miss"): the refund
#     net-deducts once from the gross purchase total, producing
#     299,000 - 99,000 = 200,000.
#
# A faithful PRD-only implementer can produce either reading. STEP 1b
# unique-derivability therefore fails and the test was removed per the
# PRD-First contract.


# ===========================================================================
# Sweep-driven expiration — PRD §3.1 / §3.8
# ===========================================================================
class TestSignupSweepExpiration:

    def test_sweep_after_deadline_transitions_to_expired(self, api):
        """PRD §3.1: "When signup_bonus_state is PENDING and the
        current logical clock is at or beyond signup_bonus_deadline_at
        without the qualifying total having crossed three thousand
        dollars, the state advances to EXPIRED and no bonus is booked."
        PRD §3.8: "every Account whose signup_bonus_state is PENDING
        and whose current clock is at-or-beyond signup_bonus_deadline_at
        transitions to EXPIRED for that bonus position, with no ledger
        entry written (no points were ever deposited)."

        Claim: an account with PENDING bonus, qualifying spend below
        the threshold, and clock past signup_bonus_deadline_at moves to
        EXPIRED after /_sweep/run, with no SIGNUP_BONUS ledger row.
        """
        setup_clock_at(2026, 1, 1)
        ch, acc = create_cardholder_and_account()
        cat = register_fixed_bonus_category(base_rate_bps=500)
        # Small purchase well under the 300,000 threshold.
        post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], amount_cents=50_000,
        )
        # Advance past the 90-day deadline and run sweep.
        advance_clock_to("2026-04-02T00:00:00.000Z")
        run_sweep()
        acc_after = re_get_account(acc["id"])
        assert acc_after["signup_bonus_state"] == "EXPIRED"
        ledger = get_ledger(acc["id"])
        bonus_rows = find_ledger_entries(
            ledger, entry_type="SIGNUP_BONUS",
        )
        assert len(bonus_rows) == 0, (
            f"no SIGNUP_BONUS ledger row may be written on expiry; got "
            f"{len(bonus_rows)}"
        )
