"""Loan negotiation loop, booking gates, and proposal lifecycle.

Covers the difficulty instance loan_negotiation_counter_cycle (>=2 tests)
plus corner instances on invalid transitions and request-linked counters.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_and_book_loan,
    create_borrow_request,
    create_loan_proposal,
    get_borrow_request,
    get_loan,
    get_position,
    make_borrower_rep_headers,
    setup_booked_loan,
    setup_desk,
    validate_error,
    validate_success,
)

TRADER = TEST_USERS["desk_trader_headers"]
OPS = TEST_USERS["ops_settler_headers"]


def _negotiation_setup():
    """Desk with a 4000-share PROPOSED direct loan at 25bps."""
    security, owner, borrower, position = setup_desk(
        security_symbol="NEG1", quantity_total=100000)
    loan = create_loan_proposal(owner, borrower, security, position,
                                quantity=4000, collateral_type="SECURITIES",
                                rate_bps=25)
    return security, owner, borrower, position, loan


class TestNegotiationCounterCycle:
    def test_full_counter_cycle_lands_booked_at_last_counter(self, api):
        """PRD §3.4: "Rate negotiation is a cycle, not a line. From
        `PROPOSED`, the borrower's side may counter — the `BorrowerRep`
        caller's `X-User-ID` must equal the loan's `borrower_id` — supplying
        a new `rate_bps` and flipping the loan to `COUNTERED`"
        PRD §3.4: "From `COUNTERED`, the `DeskTrader` may counter back,
        restoring `PROPOSED` with a new `rate_bps`. Each counter writes the
        supplied `rate_bps` onto the loan and increments its `version` by
        one"
        PRD §3.4: "Booking happens from either side of the loop: the
        `BorrowerRep` accepts a desk proposal out of `PROPOSED`, or the
        `DeskTrader` confirms a borrower counter out of `COUNTERED`."

        Design: Difficulty/non_linear_state_machine/loan_negotiation_counter_cycle
        """
        _, owner, borrower, position, loan = _negotiation_setup()
        assert loan["version"] == 1

        s1 = validate_success(api.counter_loan(
            loan["id"], {"rate_bps": 20},
            make_borrower_rep_headers(borrower["id"])))
        assert s1["status"] == "COUNTERED" and s1["version"] == 2

        s2 = validate_success(api.counter_loan(
            loan["id"], {"rate_bps": 22}, TRADER))
        assert s2["status"] == "PROPOSED" and s2["version"] == 3

        s3 = validate_success(api.counter_loan(
            loan["id"], {"rate_bps": 21},
            make_borrower_rep_headers(borrower["id"])))
        assert s3["status"] == "COUNTERED" and s3["version"] == 4

        s4 = validate_success(api.confirm_loan(loan["id"], TRADER))
        assert s4["status"] == "BOOKED" and s4["version"] == 5
        assert s4["rate_bps"] == 21

        pos = get_position(position["id"])
        assert pos["quantity_on_loan"] == 4000
        assert pos["quantity_reserved"] == 0
        assert s4["original_price_cents"] == 1000

    def test_counter_writes_rate_and_bumps_version_each_hop(self, api):
        """PRD §3.4: "Each counter writes the supplied `rate_bps` onto the
        loan and increments its `version` by one, and the loop may repeat
        indefinitely until someone books, or someone cancels."

        Design: Difficulty/non_linear_state_machine/loan_negotiation_counter_cycle
        """
        _, _, borrower, _, loan = _negotiation_setup()
        for hop, rate in enumerate((20, 22, 21), start=2):
            if hop % 2 == 0:  # borrower counters from PROPOSED
                data = validate_success(api.counter_loan(
                    loan["id"], {"rate_bps": rate},
                    make_borrower_rep_headers(borrower["id"])))
                assert data["status"] == "COUNTERED"
            else:  # desk counters from COUNTERED
                data = validate_success(api.counter_loan(
                    loan["id"], {"rate_bps": rate}, TRADER))
                assert data["status"] == "PROPOSED"
            assert data["rate_bps"] == rate
            assert data["version"] == hop

    def test_booking_captures_original_price_and_moves_buckets(self, api):
        """PRD §3.4: "Booking's side effects mirror the reservation: the
        position's `quantity_reserved` decreases by the loan quantity while
        its `quantity_on_loan` increases by the same amount; the loan
        captures the security's current `price_cents` as its
        `original_price_cents`"

        Design: Difficulty/non_linear_state_machine/loan_negotiation_counter_cycle
        """
        _, _, borrower, position, loan = _negotiation_setup()
        validate_success(api.counter_loan(
            loan["id"], {"rate_bps": 20},
            make_borrower_rep_headers(borrower["id"])))
        booked = validate_success(api.confirm_loan(loan["id"], TRADER))
        assert booked["status"] == "BOOKED"
        assert booked["original_price_cents"] == 1000
        pos = get_position(position["id"])
        assert pos["quantity_reserved"] == 0
        assert pos["quantity_on_loan"] == 4000


class TestNegotiationInvalidTransitions:
    def test_borrower_accept_on_countered_proposal_rejected(self, api):
        """PRD §3.4: "the `BorrowerRep` accepts a desk proposal out of
        `PROPOSED`, or the `DeskTrader` confirms a borrower counter out of
        `COUNTERED`."
        PRD §2.7: "the target entity is in a state from which the
        requested transition exists; otherwise `ERR_INVALID_STATE`."

        Design: Corner/state_machines/borrower_accept_on_countered_proposal_returns_invalid_state
        """
        security, owner, borrower, position = setup_desk(
            security_symbol="SM1")
        loan = create_loan_proposal(owner, borrower, security, position,
                                    quantity=1000)
        validate_success(api.counter_loan(
            loan["id"], {"rate_bps": 20},
            make_borrower_rep_headers(borrower["id"])))
        resp = api.accept_loan(
            loan["id"], make_borrower_rep_headers(borrower["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_loan(loan["id"])["status"] == "COUNTERED"

    def test_desk_confirm_on_proposed_rejected(self, api):
        """PRD §3.4: "the `DeskTrader` confirms a borrower counter out of
        `COUNTERED`."
        PRD §2.7: "the target entity is in a state from which the
        requested transition exists; otherwise `ERR_INVALID_STATE`."

        Design: Corner/state_machines/desk_confirm_on_proposed_returns_invalid_state
        """
        security, owner, borrower, position = setup_desk(
            security_symbol="SM2")
        loan = create_loan_proposal(owner, borrower, security, position,
                                    quantity=1000)
        resp = api.confirm_loan(loan["id"], TRADER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_settled_loan_rejects_amendment_terminal_lockdown(self, api):
        """PRD §3.4: "A `DeskTrader` may amend a `BOOKED` loan's `rate_bps`,
        its `term_days`, or both"
        PRD §2.7: "the target entity is in a state from which the
        requested transition exists; otherwise `ERR_INVALID_STATE`."

        Design: Corner/state_machines/settled_loan_rejects_amendment_terminal_lockdown
        """
        ctx = setup_booked_loan(security_symbol="SM3", loan_quantity=500)
        loan, borrower = ctx["loan"], ctx["borrower"]
        validate_success(api.return_loan(
            loan["id"], {"quantity": 500},
            make_borrower_rep_headers(borrower["id"])))
        settled = get_loan(loan["id"])
        assert settled["status"] == "SETTLED"
        resp = api.amend_loan(
            loan["id"], {"expected_loan_version": settled["version"],
                         "rate_bps": 30}, TRADER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestCounterRateCeiling:
    def test_counter_above_request_max_rate_rejected_boundary_inclusive(
            self, api):
        """PRD §3.4: "when the loan descends from a borrow request, the
        countered rate may not exceed that request's `max_rate_bps`, or the
        counter is rejected with `ERR_RATE_ABOVE_MAX`."

        Design: Corner/errors/counter_above_request_max_rate_rejected
        """
        security, owner, borrower, position = setup_desk(
            security_symbol="RTE1", quantity_total=10000, min_fee_bps=25)
        request = create_borrow_request(borrower, security, quantity=1000,
                                        max_rate_bps=40)
        loan = validate_success(api.match_borrow_request(
            request["id"], {"position_id": position["id"]}, TRADER),
            expected_status=201)
        headers = make_borrower_rep_headers(borrower["id"])
        resp = api.counter_loan(loan["id"], {"rate_bps": 41}, headers)
        validate_error(resp, ApiErrorId.ERR_RATE_ABOVE_MAX)
        ok = validate_success(api.counter_loan(
            loan["id"], {"rate_bps": 40}, headers))
        assert ok["status"] == "COUNTERED"
        assert ok["rate_bps"] == 40

    def test_counter_at_max_rate_boundary_of_thirty_nine_and_forty(self, api):
        """PRD §3.4: "the countered rate may not exceed that request's
        `max_rate_bps`, or the counter is rejected with `ERR_RATE_ABOVE_MAX`."

        Boundary precision: max-1 (39) and max (40) are both accepted;
        only exceeding values fail (see the paired 41 test above).

        Design: Corner/errors/counter_above_request_max_rate_rejected
        """
        security, owner, borrower, position = setup_desk(
            security_symbol="RTE2", quantity_total=10000, min_fee_bps=25)
        request = create_borrow_request(borrower, security, quantity=1000,
                                        max_rate_bps=40)
        loan = validate_success(api.match_borrow_request(
            request["id"], {"position_id": position["id"]}, TRADER),
            expected_status=201)
        headers = make_borrower_rep_headers(borrower["id"])
        at_39 = validate_success(api.counter_loan(
            loan["id"], {"rate_bps": 39}, headers))
        assert at_39["rate_bps"] == 39
        # Desk counters back so the borrower may counter again.
        validate_success(api.counter_loan(loan["id"], {"rate_bps": 38},
                                          TRADER))
        at_40 = validate_success(api.counter_loan(
            loan["id"], {"rate_bps": 40}, headers))
        assert at_40["rate_bps"] == 40
        assert at_40["status"] == "COUNTERED"


class TestMatchedRequestExpiry:
    def test_matched_request_expiry_cancels_proposal_and_releases_reservation(
            self, api):
        """PRD §3.3: "Finally, the daily run expires demand: a request whose
        `needed_by_date` has fallen behind the current date moves from
        `SUBMITTED` to `EXPIRED` outright, or from `MATCHED` to `EXPIRED`
        with the same proposal-cancelling, reservation-releasing cascade."

        Design: Corner/state_machines/matched_request_expiry_cancels_proposal
        """
        security, owner, borrower, position = setup_desk(
            security_symbol="SM9", quantity_total=10000)
        request = create_borrow_request(borrower, security, quantity=3000,
                                        needed_by_date="2026-08-02")
        loan = validate_success(api.match_borrow_request(
            request["id"], {"position_id": position["id"]}, TRADER),
            expected_status=201)
        assert get_position(position["id"])["quantity_reserved"] == 3000

        from test_helpers import run_mtm, set_clock
        set_clock("2026-08-03T00:00:00Z")
        summary = run_mtm()
        assert summary["requests_expired"] == 1
        assert get_borrow_request(request["id"], OPS)["status"] == "EXPIRED"
        assert get_loan(loan["id"], OPS)["status"] == "CANCELLED"
        assert get_position(position["id"], OPS)["quantity_reserved"] == 0
