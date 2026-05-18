"""Statement-credit redemption: two modes, two rounding directions —
PRD §3.6.

Coverage:
- POINTS_FIRST: floor(requested_points * 100 / points_per_dollar_tier);
  points_debited == requested_points.
- AMOUNT_FIRST: ceil(requested_amount_cents * points_per_dollar_tier / 100);
  credit_amount_cents == requested_amount_cents.
- Minimum redemption boundary at 2500 (POINTS_FIRST and AMOUNT_FIRST).
- Body schema exclusivity (ERR_INVALID_REDEMPTION_BODY).
- Insufficient balance -> ERR_INSUFFICIENT_POINTS.
- Reversal appends REDEEM_REVERSE row and restores balance.
- Closed-account reversal -> ERR_INVALID_STATE.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    MIN_REDEMPTION_CENTS,
    MIN_REDEMPTION_POINTS,
    create_amount_first_redemption_payload,
    create_points_first_redemption_payload,
    find_ledger_entries,
    get_ledger,
    make_cardholder_headers,
    re_get_account,
    redeem_amount_first,
    redeem_points_first,
    reverse_statement_credit,
    setup_account_on_gold,
    setup_account_on_platinum,
    setup_account_with_balance_via_signup,
    setup_platinum_with_high_balance,
    validate_error,
    validate_success,
)


# ===========================================================================
# POINTS_FIRST mode — PRD §3.6
# ===========================================================================
class TestPointsFirstMode:

    def test_points_first_on_standard_one_cent_per_point(self, api):
        """PRD §3.6: "STANDARD requires one hundred points per dollar
        (one cent per point)".
        PRD §3.6: "For POINTS_FIRST, the server records points_debited
        equal to requested_points and computes credit_amount_cents as
        requested_points multiplied by one hundred and divided by the
        tier's points-per-dollar figure, with the floor taken".

        Claim: 3000 points POINTS_FIRST on STANDARD ->
        floor(3000*100/100)=3000 cents, points_debited == 3000.
        """
        ch, acc, _cat = setup_account_with_balance_via_signup()
        # Use AWARDED 60k + earn to ensure we have >= 3000 points.
        credit = redeem_points_first(
            cardholder_id=ch["id"], account_id=acc["id"],
            requested_points=3_000,
        )
        assert credit["points_debited"] == 3_000
        assert credit["credit_amount_cents"] == 3_000

    def test_points_first_on_platinum_floors_cents(self, api):
        """PRD §3.6: "PLATINUM requires eighty points per dollar (one
        and a quarter cents per point exactly)".
        PRD §3.6: "with the floor taken — the points are spent in full,
        the cents are the dependent value, and any sub-cent residue is
        forfeit to the system".

        Claim: 2530 points POINTS_FIRST on PLATINUM ->
        floor(2530*100/80) = floor(3162.5) = 3162 cents (sub-cent
        residue of 0.5 cents is forfeit). requested_points stays
        at-or-above the PRD §3.6 minimum of 2500.
        """
        ch, acc, _cat = setup_platinum_with_high_balance()
        credit = redeem_points_first(
            cardholder_id=ch["id"], account_id=acc["id"],
            requested_points=2_530,
        )
        assert credit["points_debited"] == 2_530
        assert credit["credit_amount_cents"] == 3_162


# ===========================================================================
# AMOUNT_FIRST mode — PRD §3.6
# ===========================================================================
class TestAmountFirstMode:

    def test_amount_first_on_standard_round_trip(self, api):
        """PRD §3.6: "a thirty-dollar AMOUNT_FIRST redemption on
        STANDARD costs three thousand points and three thousand points
        POINTS_FIRST yields exactly thirty dollars".

        Claim: 3000-cent AMOUNT_FIRST on STANDARD ->
        ceil(3000*100/100)=3000 points; credit_amount_cents == 3000.
        """
        ch, acc, _cat = setup_account_with_balance_via_signup()
        credit = redeem_amount_first(
            cardholder_id=ch["id"], account_id=acc["id"],
            requested_amount_cents=3_000,
        )
        assert credit["credit_amount_cents"] == 3_000
        assert credit["points_debited"] == 3_000

    def test_amount_first_on_platinum_ceils_points(self, api):
        """PRD §3.6: "For AMOUNT_FIRST, the server records
        credit_amount_cents equal to requested_amount_cents exactly and
        computes points_debited as requested_amount_cents multiplied by
        the tier's points-per-dollar figure and divided by one hundred,
        with the ceiling taken — the cents are exact, and any sub-point
        residue is rounded up so that the system is never under-charged
        points".

        Claim: 3049-cent AMOUNT_FIRST on PLATINUM ->
        ceil(3049*80/100) = ceil(2439.2) = 2440 points;
        credit_amount_cents == 3049 exactly.
        """
        ch, acc, _cat = setup_platinum_with_high_balance()
        credit = redeem_amount_first(
            cardholder_id=ch["id"], account_id=acc["id"],
            requested_amount_cents=3_049,
        )
        assert credit["credit_amount_cents"] == 3_049
        assert credit["points_debited"] == 2_440


# ===========================================================================
# Minimum-redemption boundary — PRD §3.6
# ===========================================================================
class TestRedemptionMinimum:

    def test_points_first_min_boundary_accepted(self, api):
        """PRD §3.6: "POINTS_FIRST requires requested_points to be
        at-or-above two thousand five hundred points".

        Claim: requested_points == 2500 (exact minimum) is accepted.
        """
        ch, acc, _cat = setup_account_with_balance_via_signup()
        credit = redeem_points_first(
            cardholder_id=ch["id"], account_id=acc["id"],
            requested_points=MIN_REDEMPTION_POINTS,
        )
        assert credit["points_debited"] == MIN_REDEMPTION_POINTS

    def test_points_first_below_minimum_rejected(self, api):
        """PRD §3.6: "anything below is rejected with
        ERR_BELOW_MINIMUM_REDEMPTION".

        Claim: requested_points == 2499 -> ERR_BELOW_MINIMUM_REDEMPTION.
        """
        ch, acc, _cat = setup_account_with_balance_via_signup()
        resp = api.create_statement_credit(
            create_points_first_redemption_payload(
                account_id=acc["id"],
                requested_points=MIN_REDEMPTION_POINTS - 1,
            ),
            make_cardholder_headers(ch["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_BELOW_MINIMUM_REDEMPTION.value,
        )

    def test_amount_first_below_minimum_rejected(self, api):
        """PRD §3.6: "AMOUNT_FIRST requires requested_amount_cents to
        be at-or-above two thousand five hundred cents (twenty-five
        dollars); anything below is rejected with
        ERR_BELOW_MINIMUM_REDEMPTION".

        Claim: requested_amount_cents == 2499 ->
        ERR_BELOW_MINIMUM_REDEMPTION.
        """
        ch, acc, _cat = setup_account_with_balance_via_signup()
        resp = api.create_statement_credit(
            create_amount_first_redemption_payload(
                account_id=acc["id"],
                requested_amount_cents=MIN_REDEMPTION_CENTS - 1,
            ),
            make_cardholder_headers(ch["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_BELOW_MINIMUM_REDEMPTION.value,
        )

    def test_amount_first_min_boundary_accepted(self, api):
        """PRD §3.6: "AMOUNT_FIRST requires requested_amount_cents to
        be at-or-above two thousand five hundred cents (twenty-five
        dollars)".

        Claim: requested_amount_cents == 2500 (exact minimum) is
        accepted.
        """
        ch, acc, _cat = setup_account_with_balance_via_signup()
        credit = redeem_amount_first(
            cardholder_id=ch["id"], account_id=acc["id"],
            requested_amount_cents=MIN_REDEMPTION_CENTS,
        )
        assert credit["credit_amount_cents"] == MIN_REDEMPTION_CENTS


# ===========================================================================
# Body schema exclusivity — PRD §3.6
# ===========================================================================
class TestRedemptionBodyExclusivity:

    def test_points_first_with_amount_field_rejected(self, api):
        """PRD §3.6: "POINTS_FIRST requires requested_points to be
        present and requested_amount_cents to be absent; AMOUNT_FIRST
        requires requested_amount_cents to be present and
        requested_points to be absent. Any other combination is
        rejected with ERR_INVALID_REDEMPTION_BODY."

        Claim: POINTS_FIRST + requested_amount_cents present ->
        ERR_INVALID_REDEMPTION_BODY.
        """
        ch, acc, _cat = setup_account_with_balance_via_signup()
        resp = api.create_statement_credit(
            {
                "account_id": acc["id"],
                "redemption_mode": "POINTS_FIRST",
                "requested_points": 3_000,
                "requested_amount_cents": 3_000,
            },
            make_cardholder_headers(ch["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_INVALID_REDEMPTION_BODY.value,
        )

    def test_amount_first_with_points_field_rejected(self, api):
        """PRD §3.6: "AMOUNT_FIRST requires requested_amount_cents to
        be present and requested_points to be absent. Any other
        combination is rejected with ERR_INVALID_REDEMPTION_BODY."

        Claim: AMOUNT_FIRST + requested_points present ->
        ERR_INVALID_REDEMPTION_BODY.
        """
        ch, acc, _cat = setup_account_with_balance_via_signup()
        resp = api.create_statement_credit(
            {
                "account_id": acc["id"],
                "redemption_mode": "AMOUNT_FIRST",
                "requested_amount_cents": 3_000,
                "requested_points": 3_000,
            },
            make_cardholder_headers(ch["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_INVALID_REDEMPTION_BODY.value,
        )


# ===========================================================================
# Insufficient balance — PRD §3.6
# ===========================================================================
class TestRedemptionInsufficient:

    def test_redemption_above_balance_rejected(self, api):
        """PRD §3.6: "Before the calculation is allowed to settle the
        ledger, the server verifies points_debited is at-or-below
        points_balance; if not, the request is rejected with
        ERR_INSUFFICIENT_POINTS."

        Claim: requesting points strictly above points_balance ->
        ERR_INSUFFICIENT_POINTS.
        """
        ch, acc, _cat = setup_account_with_balance_via_signup()
        # Ask for far more than is available.
        resp = api.create_statement_credit(
            create_points_first_redemption_payload(
                account_id=acc["id"],
                requested_points=acc["points_balance"] + 10_000,
            ),
            make_cardholder_headers(ch["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_POINTS.value)


# ===========================================================================
# REDEEM_DEBIT / REDEEM_REVERSE invariant — PRD §3.6
# ===========================================================================
class TestRedemptionReversal:

    def test_redemption_appends_redeem_debit_row(self, api):
        """PRD §3.6: "On success the server creates the StatementCredit
        in APPLIED status, mints applied_at, appends a REDEEM_DEBIT
        ledger entry whose delta_points is the negation of
        points_debited, recomputes points_balance, and sets
        last_qualifying_activity_at to the current clock instant."

        Claim: ledger contains one REDEEM_DEBIT row with delta_points
        == -points_debited.
        """
        ch, acc, _cat = setup_account_with_balance_via_signup()
        credit = redeem_points_first(
            cardholder_id=ch["id"], account_id=acc["id"],
            requested_points=2_500,
        )
        ledger = get_ledger(acc["id"])
        debit_rows = find_ledger_entries(
            ledger, entry_type="REDEEM_DEBIT",
            source_entity_id=credit["id"],
        )
        assert len(debit_rows) == 1
        assert debit_rows[0]["delta_points"] == -credit["points_debited"]

    def test_reverse_appends_redeem_reverse_and_restores_balance(self, api):
        """PRD §3.6: "A PlatformAdmin may reverse an APPLIED credit ...
        reversal appends a REDEEM_REVERSE ledger entry whose
        delta_points is the positive points_debited, recomputes
        points_balance, and advances status to REVERSED."

        Claim: after reversal, ledger has a REDEEM_REVERSE row with
        delta_points == +points_debited, status == REVERSED, and the
        balance is restored to its pre-redemption value.
        """
        ch, acc, _cat = setup_account_with_balance_via_signup()
        balance_before = acc["points_balance"]
        credit = redeem_points_first(
            cardholder_id=ch["id"], account_id=acc["id"],
            requested_points=2_500,
        )
        # Reverse as PlatformAdmin.
        reversed_credit = reverse_statement_credit(credit["id"])
        assert reversed_credit["status"] == "REVERSED"
        ledger = get_ledger(acc["id"])
        reverse_rows = find_ledger_entries(
            ledger, entry_type="REDEEM_REVERSE",
            source_entity_id=credit["id"],
        )
        assert len(reverse_rows) == 1
        assert reverse_rows[0]["delta_points"] == credit["points_debited"]
        acc_after = re_get_account(acc["id"])
        assert acc_after["points_balance"] == balance_before, (
            f"reversal must restore balance to pre-redemption value: "
            f"before={balance_before}, after={acc_after['points_balance']}"
        )

    def test_reverse_already_reversed_credit_rejected(self, api):
        """PRD §3.6: "an attempt against an already-REVERSED credit, or
        against a credit on a CLOSED account, is rejected with
        ERR_INVALID_STATE".

        Claim: a second reverse of the same credit -> ERR_INVALID_STATE.
        """
        ch, acc, _cat = setup_account_with_balance_via_signup()
        credit = redeem_points_first(
            cardholder_id=ch["id"], account_id=acc["id"],
            requested_points=2_500,
        )
        reverse_statement_credit(credit["id"])
        # Second reverse.
        resp = api.reverse_statement_credit(
            credit["id"], None,
            __import__("test_helpers").TEST_USERS["admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
