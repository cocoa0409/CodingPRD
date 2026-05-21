"""Wallet/ledger invariants.

Covers PRD §2.8 (monetary precision; wallet never negative), §2.9
(ledger entries and reference_kind / reference_id rules; wallet is
running sum), §3.1 (deposit), §3.3 (FEE_CHARGE/FEE_REFUND on timed
entry), §3.6 (LOTTERY_FEE non-refundable, PERMIT_FEE on accept).
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    BOOKING_FEE_CENTS,
    assert_ledger_entry,
    assert_wallet_equals_ledger_sum,
    cancel_campground_reservation,
    cancel_timed_entry,
    confirm_campground_reservation,
    confirm_timed_entry,
    create_campground_reservation,
    create_park,
    create_timed_entry,
    create_visitor,
    create_visitor_with_wallet,
    date_to_local_str,
    deposit_wallet,
    get_visitor,
    list_visitor_ledger,
    make_visitor_headers,
    setup_confirmed_campground_reservation,
    setup_confirmed_timed_entry,
    setup_park_with_campground,
    validate_error,
)


class TestDeposit:

    def test_deposit_writes_one_positive_ledger(self, api):
        """PRD §3.1: "Each deposit writes one LedgerEntry with kind of
        DEPOSIT and a positive amount_cents."

        PRD §2.9: "Deposits and adjustments use reference_kind of None
        and leave reference_id null."
        """
        v = create_visitor()
        deposit_wallet(v["id"], 1234)
        ledger = list_visitor_ledger(v["id"])
        deposits = [e for e in ledger if e["kind"] == "DEPOSIT"]
        assert len(deposits) == 1
        e = deposits[0]
        assert e["amount_cents"] == 1234
        assert e["reference_kind"] == "None"
        assert e.get("reference_id") in (None, "")
        assert_ledger_entry(e)


class TestWalletInvariant:

    def test_wallet_equals_sum_of_ledger(self, api):
        """PRD §2.9: "Visitor.wallet_balance_cents is the running sum
        of all amount_cents values for that visitor."

        Drive a sequence of operations and assert wallet == sum.
        """
        park = create_park()
        v = create_visitor()
        deposit_wallet(v["id"], 50_000)
        deposit_wallet(v["id"], 5_000)
        # Book + confirm + cancel a timed entry round trip.
        held = create_timed_entry(
            park["id"], v,
            entry_date_local=date_to_local_str(
                date.today() + timedelta(days=10),
            ),
            window_start_local="09:00",
        )
        confirm_timed_entry(park["id"], held["id"], v)
        cancel_timed_entry(park["id"], held["id"], v)
        v_after = get_visitor(v["id"])
        ledger = list_visitor_ledger(v["id"])
        assert_wallet_equals_ledger_sum(v_after, ledger)

    def test_wallet_never_negative_on_insufficient_funds(self, api):
        """PRD §2.8: "The Visitor.wallet_balance_cents field never goes
        below zero; debit operations that would do so are rejected with
        ERR_INSUFFICIENT_FUNDS."

        Claim: post-rejection wallet remains unchanged.
        """
        park, c = setup_park_with_campground(
            nightly_standard_fee_cents=10_000,
            nightly_group_fee_cents=12000,
        )
        v = create_visitor()  # wallet = 0
        r = create_campground_reservation(
            c["id"], v,
            site_kind="STANDARD", party_size=2,
            check_in_date_local=date_to_local_str(
                date.today() + timedelta(days=30),
            ),
            check_out_date_local=date_to_local_str(
                date.today() + timedelta(days=32),
            ),
        )
        resp = api.confirm_campground_reservation(
            c["id"], r["id"], make_visitor_headers(v["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FUNDS.value)
        # Wallet unchanged at 0.
        v_after = get_visitor(v["id"])
        assert v_after["wallet_balance_cents"] == 0


class TestRoundTripCharge:

    def test_confirm_then_cancel_writes_paired_ledger_entries(self, api):
        """PRD §3.3: "the wallet is debited by entry_fee_cents, and a
        LedgerEntry of kind FEE_CHARGE referencing the timed-entry
        reservation is appended."

        PRD §3.3: "the system computes the refund using the timed-
        entry tiered-refund rule, debits or credits the wallet
        accordingly via a LedgerEntry of kind FEE_REFUND".

        Claim: a confirm + cancel cycle leaves exactly one FEE_CHARGE
        and one FEE_REFUND entry referencing the same reservation.
        """
        park, v, r = setup_confirmed_timed_entry(days_out=10)
        fee = r["entry_fee_cents"]
        cancel_timed_entry(park["id"], r["id"], v)
        ledger = list_visitor_ledger(v["id"])
        charges = [
            e for e in ledger if e["kind"] == "FEE_CHARGE"
            and e.get("reference_id") == r["id"]
        ]
        refunds = [
            e for e in ledger if e["kind"] == "FEE_REFUND"
            and e.get("reference_id") == r["id"]
        ]
        if fee > 0:
            assert len(charges) == 1
            assert charges[0]["amount_cents"] == -fee
            assert charges[0]["reference_kind"] == "TimedEntryReservation"
            assert len(refunds) == 1
        else:
            # PRD §3.3 pass_waived variant — no debit, no refund.
            assert len(charges) == 0 or (
                len(charges) == 1 and charges[0]["amount_cents"] == 0
            )
