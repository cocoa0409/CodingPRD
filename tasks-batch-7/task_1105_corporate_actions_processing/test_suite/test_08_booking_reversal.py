"""Compensating invariants (PRD §3.7): booking reversal restores conserved
quantities exactly — shares + basis for a split, cash for a dividend.
"""
from test_helpers import (
    validate_success, get_success_data,
    make_security, make_account, make_lot, set_clock,
    make_confirmed_event, split_terms, cash_dividend_terms,
)
from test_helpers.fixtures import OPS
from test_helpers import api_client


def _split_booked_two_lots():
    sec = make_security(ticker="ACME")
    acct = make_account(account_number="A-1", holder_name="One",
                        opening_cash_cents=50000)
    l1 = make_lot(acct["id"], sec["id"], quantity=1000,
                  acquisition_date="2026-04-01", cost_basis_total_cents=10000000)
    l2 = make_lot(acct["id"], sec["id"], quantity=250,
                  acquisition_date="2026-04-02", cost_basis_total_cents=2500000)
    event, _, _ = make_confirmed_event(sec["id"], "SPLIT", split_terms())
    set_clock("2026-05-15T00:00:00Z")
    get_success_data(api_client.capture_record_position(event["id"], OPS))
    booking = get_success_data(api_client.book_event(event["id"], OPS))
    return sec, acct, l1, l2, event, booking


class TestSplitBookingReversalRestoresSharesAndBasis:
    def test_forward_booking_doubles_shares(self, api):
        """PRD §3.6: "For each lot in order: the exact entitlement is the lot's quantity multiplied by the ratio (`ratio_num` divided by `ratio_den`); the whole-share part is that exact value rounded down" and "the entitlement's `booked_whole_shares` is the sum of the per-lot whole-share floors".

        Design: Difficulty/compensating_invariant/split_booking_reversal_restores_shares_and_basis
        """
        _, acct, l1, _, _, booking = _split_booked_two_lots()
        assert booking["total_whole_shares_credited"] == 2500  # 1250 x 2
        l1_after = get_success_data(api.get_position_lot(l1["id"], OPS))
        assert l1_after["quantity"] == 2000

    def test_reversal_restores_conserved_quantities_exactly(self, api):
        """PRD §3.7: "On success the booking moves `POSTED` → `REVERSED`, and every one of its lines is inverted using the recorded `prior_quantity` and `prior_basis_cents` — an exact restore, never a recompute." and "Every affected account's cash, cost basis, and pending count is recomputed, and the event itself returns from `BOOKED` to `CONFIRMED` with its `version` incremented".

        Design: Difficulty/compensating_invariant/split_booking_reversal_restores_shares_and_basis
        """
        _, acct, l1, l2, event, booking = _split_booked_two_lots()
        reversed_booking = validate_success(api.reverse_booking(booking["id"], OPS))
        assert reversed_booking["status"] == "REVERSED"
        l1_after = get_success_data(api.get_position_lot(l1["id"], OPS))
        l2_after = get_success_data(api.get_position_lot(l2["id"], OPS))
        assert l1_after["quantity"] == 1000
        assert l1_after["cost_basis_total_cents"] == 10000000
        assert l2_after["quantity"] == 250
        assert l2_after["cost_basis_total_cents"] == 2500000
        # INVARIANT: totals identical to pre-booking values.
        assert (l1_after["quantity"] + l2_after["quantity"]) == 1250
        assert (l1_after["cost_basis_total_cents"]
                + l2_after["cost_basis_total_cents"]) == 12500000
        acct_after = get_success_data(api.get_account(acct["id"], OPS))
        assert acct_after["cash_balance_cents"] == 50000
        event_after = get_success_data(api.get_event(event["id"], OPS))
        assert event_after["status"] == "CONFIRMED"


def _dividend_booked():
    sec = make_security(ticker="ACME")
    acct = make_account(account_number="A-1", holder_name="One",
                        opening_cash_cents=50000)
    make_lot(acct["id"], sec["id"], quantity=1000,
             acquisition_date="2026-04-01", cost_basis_total_cents=10000000)
    event, _, _ = make_confirmed_event(
        sec["id"], "CASH_DIVIDEND", cash_dividend_terms(cash_per_share_cents=250))
    set_clock("2026-05-15T00:00:00Z")
    get_success_data(api_client.capture_record_position(event["id"], OPS))
    booking = get_success_data(api_client.book_event(event["id"], OPS))
    return sec, acct, event, booking


class TestDividendBookingReversalRestoresCash:
    def test_forward_booking_credits_dividend_cash(self, api):
        """PRD §3.6: "A `CASH_DIVIDEND` booking mutates no lots: each settled entitlement simply credits its `cash_amount_cents` to the account as a cash-credit line." and "`total_cash_credited_cents` is the sum of every cash credit — dividends and merger cash legs — with rights debits excluded".

        Design: Difficulty/compensating_invariant/dividend_booking_reversal_restores_cash
        """
        _, acct, _, booking = _dividend_booked()
        assert booking["total_cash_credited_cents"] == 250000  # 1000 x 250
        acct_after = get_success_data(api.get_account(acct["id"], OPS))
        assert acct_after["cash_balance_cents"] == 300000  # 50000 + 250000

    def test_reversal_returns_cash_to_opening_zero_drift(self, api):
        """PRD §3.7: "On success the booking moves `POSTED` → `REVERSED`, and every one of its lines is inverted using the recorded `prior_quantity` and `prior_basis_cents` — an exact restore, never a recompute." and
        "entitlements the booking settled return from `SETTLED` to `FIRM` with `booked_whole_shares` and `booked_cash_in_lieu_cents` reset to null".
        PRD §2.9: "An account's `cash_balance_cents` is its `opening_cash_cents` plus the sum of every cash delta ever applied to it: booking line credits and debits, rights-exercise debits, claim payments, and the inverse lines posted by a booking reversal."

        Design: Difficulty/compensating_invariant/dividend_booking_reversal_restores_cash
        """
        _, acct, event, booking = _dividend_booked()
        validate_success(api.reverse_booking(booking["id"], OPS))
        acct_after = get_success_data(api.get_account(acct["id"], OPS))
        # INVARIANT: net cash drift == 0 across book + reverse.
        assert acct_after["cash_balance_cents"] == 50000
        ent = api_client.list_entitlements(
            OPS, params={"event_id": event["id"], "account_id": acct["id"]}
        ).json()["data"][0]
        assert ent["status"] == "FIRM"
        event_after = get_success_data(api.get_event(event["id"], OPS))
        assert event_after["status"] == "CONFIRMED"
        booking_after = get_success_data(api.get_booking(booking["id"], OPS))
        assert booking_after["status"] == "REVERSED"
