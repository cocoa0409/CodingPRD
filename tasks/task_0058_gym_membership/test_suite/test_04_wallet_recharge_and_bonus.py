"""Wallet recharges, tiered bonuses, FIFO consumption, and balance
projection.

PRD §3.3, §3.4.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    create_funded_member,
    create_member,
    create_monthly_card_type,
    find_wallet_txn,
    get_member,
    issue_card,
    list_wallet_transactions,
    make_member_headers,
    recharge_member,
    validate_error,
)


# ===========================================================================
# Recharge amount validation (PRD §3.3)
# ===========================================================================
class TestRechargeAmountValidation:

    def test_zero_amount_rejected(self, api):
        """PRD §3.3: 'The value must be strictly greater than zero and
        no more than 1,000,000 cents; otherwise the request is rejected
        with ERR_RECHARGE_AMOUNT_INVALID.'"""
        m = create_member()
        res = api.recharge_wallet(
            m["id"], {"amount_cents": 0},
            make_member_headers(m["id"]),
        )
        validate_error(res, ApiErrorId.ERR_RECHARGE_AMOUNT_INVALID.value)

    def test_negative_amount_rejected(self, api):
        """PRD §3.3: 'strictly greater than zero ... otherwise the
        request is rejected with ERR_RECHARGE_AMOUNT_INVALID.'"""
        m = create_member()
        res = api.recharge_wallet(
            m["id"], {"amount_cents": -500},
            make_member_headers(m["id"]),
        )
        validate_error(res, ApiErrorId.ERR_RECHARGE_AMOUNT_INVALID.value)

    def test_above_cap_rejected(self, api):
        """PRD §3.3: 'no more than 1,000,000 cents; otherwise the
        request is rejected with ERR_RECHARGE_AMOUNT_INVALID.'"""
        m = create_member()
        res = api.recharge_wallet(
            m["id"], {"amount_cents": 1_000_001},
            make_member_headers(m["id"]),
        )
        validate_error(res, ApiErrorId.ERR_RECHARGE_AMOUNT_INVALID.value)


# ===========================================================================
# Recharge bonus tiers (PRD §3.3)
# ===========================================================================
class TestRechargeBonusTiers:

    def test_below_20k_no_bonus(self, api):
        """PRD §3.3: 'amounts below 20,000 cents earn no bonus.'"""
        m = create_member()
        recharge_member(m["id"], 19_999)
        member = get_member(m["id"])
        assert member["bonus_balance_cents"] == 0
        assert member["wallet_balance_cents"] == 19_999

    def test_20k_tier_yields_5_percent_truncated(self, api):
        """PRD §3.3: 'amounts of at least 20,000 cents earn a 5% bonus.'
        and 'with the result truncated toward zero — recharge bonuses do
        not round up.'"""
        m = create_member()
        recharge_member(m["id"], 20_000)
        member = get_member(m["id"])
        # 20_000 * 500 / 10000 = 1000 cents.
        assert member["bonus_balance_cents"] == 1_000

    def test_50k_tier_yields_10_percent(self, api):
        """PRD §3.3: 'amounts of at least 50,000 cents earn a 10%
        bonus.'"""
        m = create_member()
        recharge_member(m["id"], 50_000)
        member = get_member(m["id"])
        # 50_000 * 1000 / 10000 = 5000.
        assert member["bonus_balance_cents"] == 5_000

    def test_100k_tier_yields_20_percent(self, api):
        """PRD §3.3: 'amounts of at least 100,000 cents earn a 20%
        bonus.'"""
        m = create_member()
        recharge_member(m["id"], 100_000)
        member = get_member(m["id"])
        # 100_000 * 2000 / 10000 = 20000.
        assert member["bonus_balance_cents"] == 20_000

    def test_25k_recharge_yields_1250_bonus(self, api):
        """PRD §3.3: 'amounts of at least 20,000 cents earn a 5% bonus
        ... with the result truncated toward zero.'

        25_000 * 0.05 = 1250 exactly; tests the lower-end of tier 1.
        """
        m = create_member()
        recharge_member(m["id"], 25_000)
        member = get_member(m["id"])
        assert member["bonus_balance_cents"] == 1_250
        assert member["wallet_balance_cents"] == 25_000 + 1_250

    def test_bonus_truncates_not_rounds(self, api):
        """PRD §3.3: 'with the result truncated toward zero — recharge
        bonuses do not round up.'

        Pick an amount whose 5% has a fractional remainder: 21_345 →
        21_345 * 500 / 10000 = 1067.25 → truncates to 1067.
        """
        m = create_member()
        recharge_member(m["id"], 21_345)
        member = get_member(m["id"])
        assert member["bonus_balance_cents"] == 1_067, (
            "PRD §3.3: bonus is truncated toward zero, not rounded."
        )


# ===========================================================================
# Bonus-grant ledger row shape (PRD §3.3)
# ===========================================================================
class TestBonusGrantLedgerRow:

    def test_bonus_grant_row_in_bonus_bucket(self, api):
        """PRD §3.3: 'a BONUS_GRANT row is appended with bucket=BONUS,
        the truncated bonus value as amount_cents, and expires_at set
        to 365 days after the current instant anchored at end-of-day
        UTC.'"""
        m = create_member()
        recharge_member(m["id"], 50_000)
        rows = list_wallet_transactions(
            m["id"], headers=make_member_headers(m["id"]),
        )
        grants = find_wallet_txn(rows, kind="BONUS_GRANT", bucket="BONUS")
        assert len(grants) == 1
        assert grants[0]["amount_cents"] == 5_000
        assert grants[0]["expires_at"] is not None, (
            "PRD §3.3: 'expires_at set to 365 days after the current "
            "instant anchored at end-of-day UTC.'"
        )

    def test_recharge_row_principal_bucket(self, api):
        """PRD §3.3: 'Each successful recharge appends a RECHARGE row
        to the ledger with bucket=PRINCIPAL and amount_cents set to the
        requested amount.'"""
        m = create_member()
        recharge_member(m["id"], 30_000)
        rows = list_wallet_transactions(
            m["id"], headers=make_member_headers(m["id"]),
        )
        recharges = find_wallet_txn(
            rows, kind="RECHARGE", bucket="PRINCIPAL",
        )
        assert len(recharges) == 1
        assert recharges[0]["amount_cents"] == 30_000


# ===========================================================================
# Wallet debit: FIFO bonus consumption (PRD §3.4)
# ===========================================================================
class TestWalletDebitFifoConsumption:

    def test_card_issuance_drains_bonus_first(self, api):
        """PRD §3.4: 'The debit amount is satisfied first from
        outstanding BONUS_GRANT rows in FIFO order.'

        After 50k recharge, bonus = 5_000. Issuing a 4_000-cent card
        should be fully covered by bonus, leaving principal untouched.
        """
        m = create_funded_member(wallet_balance_cents=0)
        recharge_member(m["id"], 50_000)
        # Before issuance: principal=50_000, bonus=5_000.
        member_before = get_member(m["id"])
        assert member_before["bonus_balance_cents"] == 5_000

        ct = create_monthly_card_type(price_cents=4_000)
        card = issue_card(ct["id"], m["id"])
        # PRD §3.4: bonus consumed first; the 4_000 debit fully fits
        # in the 5_000 bonus.
        member_after = get_member(m["id"])
        assert member_after["bonus_balance_cents"] == 1_000, (
            "PRD §3.4: bonus is drained before principal for any debit."
        )
        # Principal untouched.
        assert member_after["wallet_balance_cents"] == \
            50_000 + 1_000, (
            "PRD §3.4: principal must remain at recharge level when "
            "bonus fully covers the debit."
        )

    def test_card_issuance_insufficient_total_balance_aborts(self, api):
        """PRD §3.4: 'if principal_balance_cents is less than the
        remainder, the entire debit aborts with
        ERR_INSUFFICIENT_BALANCE and no rows are appended.'"""
        m = create_member()
        recharge_member(m["id"], 20_000)        # principal=20_000, bonus=1_000
        ct = create_monthly_card_type(price_cents=30_000)
        before_rows = list_wallet_transactions(
            m["id"], headers=make_member_headers(m["id"]),
        )
        before_count = len(before_rows)
        res = api.issue_card(
            {"card_type_id": ct["id"], "holder_member_id": m["id"]},
            __import__("test_helpers").SO,
        )
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_BALANCE.value)
        # No rows should have been appended.
        after_rows = list_wallet_transactions(
            m["id"], headers=make_member_headers(m["id"]),
        )
        assert len(after_rows) == before_count, (
            "PRD §3.4: 'the entire debit aborts ... no rows are appended.'"
        )


# ===========================================================================
# Refunds always credit PRINCIPAL (PRD §3.4)
# ===========================================================================
class TestRefundsAlwaysCreditPrincipal:

    def test_refund_credits_principal_not_bonus(self, api):
        """PRD §3.4: 'Refunds and class-cancel refunds always credit
        PRINCIPAL regardless of which bucket originally paid — bonus
        credits are never returned to the bonus bucket.'

        Pay a deduction with a bonus-paid group class booking, then
        cancel the class.  The refund row's bucket must be PRINCIPAL.
        """
        # Setup: trainer + class with deduction=5_000. Recharge member
        # so they have 5_000 bonus + 0 principal beyond the original
        # recharge; the deduction will draw 5_000 bonus first.
        from test_helpers import (
            create_trainer, create_group_class, create_group_booking,
            iso_z, parse_iso, advance_clock, reset_clock_to,
        )
        from datetime import timedelta

        reset_clock_to("2026-01-01T00:00:00.000Z")
        trainer = create_trainer(specialties=["STRENGTH"])
        s = parse_iso("2026-01-05T10:00:00.000Z")
        e = s + timedelta(hours=1)
        klass = create_group_class(
            instructor_trainer_id=trainer["id"],
            starts_at=iso_z(s), ends_at=iso_z(e),
            capacity=5, deduction_cents=5_000,
        )
        member = create_member()
        # 100_000 recharge → bonus 20_000, principal 100_000.
        recharge_member(member["id"], 100_000)
        booking = create_group_booking(class_id=klass["id"], member=member)
        # Check bonus is partially drawn (5_000 from bonus = 15_000 left).
        m2 = get_member(member["id"])
        # The 5_000 group-class deduction was satisfied entirely from
        # bonus (since bonus had 20_000).
        assert m2["bonus_balance_cents"] == 15_000

        # Cancel the class — this triggers refund per PRD §3.9.
        from test_helpers import PA
        cancel_resp = api.cancel_group_class(klass["id"], PA)
        from prd_bench_local_runner.testing import get_success_data
        get_success_data(cancel_resp)

        # Now the refund row should have bucket=PRINCIPAL (not BONUS).
        rows = list_wallet_transactions(
            member["id"], headers=make_member_headers(member["id"]),
        )
        refund_rows = find_wallet_txn(rows, kind="REFUND")
        assert len(refund_rows) >= 1, "refund row should be appended"
        for r in refund_rows:
            assert r["bucket"] == "PRINCIPAL", (
                "PRD §3.4: 'Refunds and class-cancel refunds always "
                "credit PRINCIPAL regardless of which bucket originally "
                "paid.'"
            )
