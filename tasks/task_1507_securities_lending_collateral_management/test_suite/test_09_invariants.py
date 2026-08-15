"""Compensating invariants: position share-bucket conservation across
propose/book/return, and collateral-cash conservation across invest/unwind.

Covers difficulty instances lendable_quantity_bucket_conservation and
cash_collateral_invest_unwind_conservation (>=2 tests each).
"""
import pytest

from test_helpers import (
    TEST_USERS,
    create_and_book_loan,
    create_loan_proposal,
    create_tranche,
    get_loan,
    get_position,
    list_ledger_entries,
    make_borrower_rep_headers,
    post_cash_pledge,
    return_shares,
    setup_booked_loan,
    setup_cash_loan_with_pledge,
    setup_desk,
    validate_success,
)

TRADER = TEST_USERS["desk_trader_headers"]
OPS = TEST_USERS["ops_settler_headers"]


def _buckets(position_id):
    pos = get_position(position_id)
    return (pos["quantity_reserved"], pos["quantity_on_loan"],
            pos["quantity_available"], pos["quantity_total"])


class TestLendableQuantityBucketConservation:
    def test_propose_book_full_return_restores_buckets(self, api):
        """PRD §3.2: "`quantity_reserved` sums the quantities of loans in
        `PROPOSED` or `COUNTERED` matched from the position,
        `quantity_on_loan` sums the outstanding quantities of loans in
        `BOOKED` or `RECALLED` matched from it, and `quantity_available` is
        what remains — `quantity_total` minus `quantity_reserved` minus
        `quantity_on_loan`."
        PRD §3.4: "the position's `quantity_reserved` decreases by the loan
        quantity while its `quantity_on_loan` increases by the same amount"
        PRD §3.4: "the settlement cascade: the position's `quantity_on_loan`
        is decremented"

        Design: Difficulty/compensating_invariant/lendable_quantity_bucket_conservation
        """
        security, owner, borrower, position = setup_desk(
            security_symbol="INV1", quantity_total=10000)
        assert _buckets(position["id"]) == (0, 0, 10000, 10000)

        loan = create_loan_proposal(owner, borrower, security, position,
                                    quantity=4000, rate_bps=25)
        r, o, a, total = _buckets(position["id"])
        assert (r, o, a) == (4000, 0, 6000)
        assert r + o + a == total

        booked = validate_success(api.accept_loan(
            loan["id"], make_borrower_rep_headers(borrower["id"])))
        r, o, a, total = _buckets(position["id"])
        assert (r, o, a) == (0, 4000, 6000)
        assert r + o + a == total

        settled = return_shares(booked, borrower, 4000)
        assert settled["status"] == "SETTLED"
        r, o, a, total = _buckets(position["id"])
        assert (r, o, a) == (0, 0, 10000)
        assert r + o + a == total

    def test_conservation_holds_at_each_hop_of_two_concurrent_loans(self, api):
        """PRD §3.2: "`quantity_reserved` sums the quantities of loans in
        `PROPOSED` or `COUNTERED` matched from the position,
        `quantity_on_loan` sums the outstanding quantities of loans in
        `BOOKED` or `RECALLED` matched from it, and `quantity_available` is
        what remains — `quantity_total` minus `quantity_reserved` minus
        `quantity_on_loan`."

        Design: Difficulty/compensating_invariant/lendable_quantity_bucket_conservation
        """
        security, owner, borrower, position = setup_desk(
            security_symbol="INV1B", quantity_total=10000)
        loan_a = create_loan_proposal(owner, borrower, security, position,
                                      quantity=2000, rate_bps=25)
        loan_b = create_loan_proposal(owner, borrower, security, position,
                                      quantity=3000, rate_bps=25)
        r, o, a, total = _buckets(position["id"])
        assert (r, o, a) == (5000, 0, 5000)
        assert r + o + a == total

        booked_a = validate_success(api.accept_loan(
            loan_a["id"], make_borrower_rep_headers(borrower["id"])))
        r, o, a, total = _buckets(position["id"])
        assert (r, o, a) == (3000, 2000, 5000)
        assert r + o + a == total

        # Partial return: 500 of 2000 shares back; loan stays BOOKED.
        return_shares(booked_a, borrower, 500)
        r, o, a, total = _buckets(position["id"])
        assert (r, o, a) == (3000, 1500, 5500)
        assert r + o + a == total


class TestCashCollateralConservation:
    def test_invest_unwind_restores_uninvested_cash(self, api):
        """PRD §3.4: "its `cash_uninvested_cents` is the total of its
        `ACTIVE` cash pledges minus the principal of its `INVESTED`
        reinvestment tranches."
        PRD §3.6: "Unwinding returns the principal to the loan's
        `cash_uninvested_cents`; gains and losses go to revenue, never to the
        borrower's collateral principal."

        Design: Difficulty/compensating_invariant/cash_collateral_invest_unwind_conservation
        """
        ctx = setup_cash_loan_with_pledge(
            pledge_amount_cents=1_020_000, security_symbol="INV2",
            loan_quantity=1000, rate_bps=0)
        loan = ctx["loan"]

        assert get_loan(loan["id"])["cash_uninvested_cents"] == 1020000

        tranche = create_tranche(loan, principal_cents=600_000,
                                 instrument_type="TIME_DEPOSIT",
                                 stated_yield_bps=360)
        # 1,020,000 pledged == 420,000 uninvested + 600,000 invested principal
        assert get_loan(loan["id"])["cash_uninvested_cents"] == 420000

        validate_success(api.mark_reinvestment(
            tranche["id"], {"current_nav_cents": 615000}, OPS))
        unwound = validate_success(api.unwind_reinvestment(
            tranche["id"], TRADER))
        assert unwound["realized_income_cents"] == 15000  # 615,000 - 600,000

        after = get_loan(loan["id"])
        assert after["cash_uninvested_cents"] == 1020000
        assert after["posted_collateral_cents"] == 1020000

    def test_nav_gain_lands_on_ledger_only_not_collateral(self, api):
        """PRD §3.6: "at unwind, the tranche realizes `current_nav_cents`
        minus `principal_cents` as its `realized_income_cents` — a figure
        that may be negative when the mark has fallen — and a
        `REINVEST_INCOME_FINAL` entry carries that signed amount."
        PRD §3.6: "gains and losses go to revenue, never to the borrower's
        collateral principal."

        Design: Difficulty/compensating_invariant/cash_collateral_invest_unwind_conservation
        """
        ctx = setup_cash_loan_with_pledge(
            pledge_amount_cents=1_020_000, security_symbol="INV2B",
            loan_quantity=1000, rate_bps=0)
        loan = ctx["loan"]
        tranche = create_tranche(loan, principal_cents=600_000,
                                 instrument_type="TIME_DEPOSIT")
        validate_success(api.mark_reinvestment(
            tranche["id"], {"current_nav_cents": 615000}, OPS))
        validate_success(api.unwind_reinvestment(tranche["id"], TRADER))

        finals = list_ledger_entries(OPS, loan_id=loan["id"],
                                     entry_type="REINVEST_INCOME_FINAL")
        assert len(finals) == 1
        assert finals[0]["amount_cents"] == 15000

        after = get_loan(loan["id"])
        # The 15,000c gain never inflates collateral-side buckets.
        assert after["cash_uninvested_cents"] == 1020000
        assert after["posted_collateral_cents"] == 1020000
