"""State-machine guards on the event lifecycle (PRD §3.3-§3.7) and on claims,
bookings, breaks, and accounts.
"""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of, get_success_data,
    ApiErrorId,
    make_security, make_account, make_lot, set_clock,
    make_scrubbed_event, make_confirmed_event,
    make_merger_event_confirmed, make_missed_entitlement_context,
    make_open_position_break, file_claim,
    make_account_holder_headers, make_examiner_headers,
    split_terms, get_event_version,
)
from test_helpers.fixtures import OPS, ANALYST_1, ANALYST_2
from test_helpers import api_client


class TestEventCreatedInDraft:
    def test_draft_initial_state_and_pool_initialization(self, api):
        """PRD §3.3: "A successfully scrubbed event is born `DRAFT`. The server records the scrubbing analyst as `scrubbed_by_user_id` and initializes `compensation_pool_remaining_cents` to the full `compensation_pool_cents`."
        PRD §3.3: "On success, every referenced notification moves to `MATCHED`."

        Design: Corner/state_machines/event_created_in_draft_initial_state
        """
        sec = make_security(ticker="ACME", cusip="CUSPB00001")
        event, n1, n2 = make_scrubbed_event(
            sec["id"], "SPLIT", split_terms(), compensation_pool_cents=100000)
        assert event["status"] == "DRAFT"
        assert event["compensation_pool_remaining_cents"] == 100000
        assert event["scrubbed_by_user_id"] == "analyst-1"
        n1_after = get_success_data(api.get_source_notification(n1["id"], OPS))
        n2_after = get_success_data(api.get_source_notification(n2["id"], OPS))
        assert n1_after["status"] == "MATCHED"
        assert n2_after["status"] == "MATCHED"


class TestInvalidEventTransitions:
    def test_book_from_draft_rejected(self, api):
        """PRD §3.6: "Like capture, it requires a `CONFIRMED` event — an attempt against an event in any other state is rejected with `ERR_EVENT_NOT_CONFIRMED`".

        Design: Corner/state_machines/book_from_draft_rejected
        """
        sec = make_security(ticker="ACME", cusip="CUSPB00002")
        event, _, _ = make_scrubbed_event(sec["id"], "SPLIT", split_terms())
        resp = api.book_event(event["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_CONFIRMED)
        bookings, meta = __import__("test_helpers").validate_paginated(
            api.list_event_bookings(event["id"], OPS))
        assert meta["total_count"] == 0

    def test_amend_draft_event_rejected(self, api):
        """PRD §3.4: "Amendment requires the event to be `CONFIRMED`; against any other state the request fails the state check, with `ERR_EVENT_NOT_AMENDABLE` (HTTP 409) when the event is not in the amendable state."

        Design: Corner/state_machines/amend_draft_event_rejected
        """
        sec = make_security(ticker="ACME", cusip="CUSPB00003")
        event, _, _ = make_scrubbed_event(sec["id"], "SPLIT", split_terms())
        resp = api.amend_event(
            event["id"],
            {"amended_terms": split_terms(ratio_num=3), "reason": "early",
             "expected_event_version": event["version"]},
            ANALYST_1)
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_AMENDABLE)
        after = get_success_data(api.get_event(event["id"], OPS))
        assert after["status"] == "DRAFT"
        assert after["version"] == event["version"]

    def test_confirm_cancelled_event_rejected(self, api):
        """PRD §3.4: "Once an event is `COMPLETED` or `CANCELLED` it is terminal: any further lifecycle operation against it is rejected with `ERR_EVENT_ALREADY_TERMINAL` (HTTP 409)."

        Design: Corner/state_machines/confirm_cancelled_event_rejected
        """
        sec = make_security(ticker="ACME", cusip="CUSPB00004")
        event, _, _ = make_scrubbed_event(sec["id"], "SPLIT", split_terms())
        cancelled = validate_success(api.cancel_event(event["id"], ANALYST_1))
        assert cancelled["status"] == "CANCELLED"
        resp = api.confirm_event(event["id"], ANALYST_2)
        validate_error(resp, ApiErrorId.ERR_EVENT_ALREADY_TERMINAL)

    def test_complete_from_confirmed_rejected(self, api):
        """PRD §3.7: "The `OperationsManager` completes a `BOOKED` event — completion against any other state fails the state check, with `ERR_EVENT_NOT_BOOKED` (HTTP 409) when the event is not booked".

        Design: Corner/state_machines/complete_from_confirmed_rejected
        """
        sec = make_security(ticker="ACME", cusip="CUSPB00005")
        event, _, _ = make_confirmed_event(sec["id"], "SPLIT", split_terms())
        resp = api.complete_event(event["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_BOOKED)
        after = get_success_data(api.get_event(event["id"], OPS))
        assert after["status"] == "CONFIRMED"


class TestElectionVoidLockdown:
    def test_withdraw_void_election_rejected(self, api):
        """PRD §3.5: "both `SUBMITTED` and `WITHDRAWN` elections are voided when the event is cancelled" and "Withdrawal requires a `SUBMITTED` election and resubmission a `WITHDRAWN` one; attempting either against the wrong state is rejected with `ERR_ELECTION_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/withdraw_void_election_rejected
        """
        ctx = make_merger_event_confirmed(account_shares=10)
        event, acct = ctx["event"], ctx["account"]
        election = validate_success(api.submit_election(
            event["id"],
            {"account_id": acct["id"], "option_code": "CASH",
             "expected_event_version": get_event_version(event["id"])},
            make_account_holder_headers(acct["id"])), 201)
        validate_success(api.cancel_event(event["id"], ANALYST_1))
        after = get_success_data(api.get_election(election["id"], OPS))
        assert after["status"] == "VOID"
        resp = api.withdraw_election(
            election["id"], make_account_holder_headers(acct["id"]))
        # PRD §3.5 covers ERR_ELECTION_INVALID_STATE for wrong-state withdraw.
        # PRD §3.4 also declares a terminal event rejects "any further lifecycle
        # operation" with ERR_EVENT_ALREADY_TERMINAL — and PRD does not state
        # which check wins when both hold (the event is CANCELLED, hence
        # terminal, AND the election is VOID, hence not SUBMITTED). Either
        # error is PRD-consistent here.
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_ELECTION_INVALID_STATE,
            ApiErrorId.ERR_EVENT_ALREADY_TERMINAL,
        ])


class TestClaimStateGuards:
    def test_decide_twice_rejected(self, api):
        """PRD §3.8: "The checks run in order: the claim must still be `FILED`, else `ERR_CLAIM_NOT_FILED` (HTTP 409)".

        Design: Corner/state_machines/decide_twice_rejected
        """
        ctx = make_missed_entitlement_context(price_per_share_cents=5000,
                                              compensation_pool_cents=100000)
        claim = file_claim(ctx["event"]["id"], ctx["entitlement"]["id"],
                           ctx["account"]["id"], claimed_amount_cents=50000)
        decided = validate_success(api.decide_claim(
            claim["id"], {"decision": "APPROVED"},
            make_examiner_headers("examiner-1")))
        assert decided["review_status"] == "APPROVED"
        resp = api.decide_claim(claim["id"], {"decision": "DENIED"},
                                make_examiner_headers("examiner-1"))
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_FILED)
        after = get_success_data(api.get_claim(claim["id"], OPS))
        assert after["review_status"] == "APPROVED"

    def test_pay_unapproved_claim_rejected(self, api):
        """PRD §3.8: "It requires the claim to be `APPROVED` and still `UNPAID`; anything else is rejected with `ERR_CLAIM_NOT_PAYABLE` (HTTP 409)."

        Design: Corner/state_machines/pay_unapproved_claim_rejected
        """
        ctx = make_missed_entitlement_context(price_per_share_cents=5000,
                                              compensation_pool_cents=100000)
        claim = file_claim(ctx["event"]["id"], ctx["entitlement"]["id"],
                           ctx["account"]["id"], claimed_amount_cents=50000)
        resp = api.pay_claim(claim["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_PAYABLE)
        acct_after = get_success_data(api.get_account(ctx["account"]["id"], OPS))
        assert acct_after["cash_balance_cents"] == 0
        claim_after = get_success_data(api.get_claim(claim["id"], OPS))
        assert claim_after["payment_status"] == "UNPAID"


class TestBookingReversalLockdown:
    def test_reverse_reversed_booking_rejected(self, api):
        """PRD §3.7: "Reversal, performed by the `OperationsManager`, requires the booking to be `POSTED` and no `PAID` claim to reference any entitlement the booking settled; otherwise the request is rejected with `ERR_BOOKING_NOT_REVERSIBLE` (HTTP 409)."

        Design: Corner/state_machines/reverse_reversed_booking_rejected
        """
        sec = make_security(ticker="ACME", cusip="CUSPB00010")
        acct = make_account(account_number="A-1", holder_name="One")
        make_lot(acct["id"], sec["id"], quantity=1000,
                 acquisition_date="2026-04-01", cost_basis_total_cents=10000000)
        event, _, _ = make_confirmed_event(sec["id"], "SPLIT", split_terms())
        set_clock("2026-05-15T00:00:00Z")
        get_success_data(api_client.capture_record_position(event["id"], OPS))
        booking = get_success_data(api_client.book_event(event["id"], OPS))
        reversed_bk = validate_success(api.reverse_booking(booking["id"], OPS))
        assert reversed_bk["status"] == "REVERSED"
        resp = api.reverse_booking(booking["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_REVERSIBLE)


class TestReconBreakResolutionGuards:
    def test_resolve_resolved_break_rejected(self, api):
        """PRD §3.9: "the break must be `OPEN`, else `ERR_RECON_BREAK_NOT_OPEN` (HTTP 409)" and "A manual resolution stores `resolution` `MANUAL` and moves the break `OPEN` → `RESOLVED".

        Design: Corner/state_machines/resolve_resolved_break_rejected
        """
        _, _, _, _, brk = make_open_position_break(
            account_shares=1000, reported_quantity=900)
        resolved = validate_success(api.resolve_recon_break(
            brk["id"],
            {"resolution": "RESOLVED",
             "resolution_note": "custodian retransmitted corrected file"},
            OPS))
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolution"] == "MANUAL"
        resp = api.resolve_recon_break(
            brk["id"], {"resolution": "WRITTEN_OFF",
                        "resolution_note": "second attempt"}, OPS)
        validate_error(resp, ApiErrorId.ERR_RECON_BREAK_NOT_OPEN)


class TestAccountCloseGuards:
    def test_close_account_with_open_lots_rejected(self, api):
        """PRD §3.1: "Closing is guarded: an account with any `OPEN` position lot whose quantity is greater than zero, or any entitlement still in `PROJECTED` or `FIRM` status, cannot be closed and the attempt is rejected with `ERR_ACCOUNT_NOT_SETTLED`."

        Design: Corner/state_machines/close_account_with_open_lots_rejected
        """
        sec = make_security(ticker="ACME", cusip="CUSPB00012")
        acct = make_account(account_number="A-1", holder_name="One")
        make_lot(acct["id"], sec["id"], quantity=100,
                 acquisition_date="2026-04-01", cost_basis_total_cents=500000)
        resp = api.update_account(acct["id"], {"status": "CLOSED"}, OPS)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_SETTLED)
        after = get_success_data(api.get_account(acct["id"], OPS))
        assert after["status"] == "ACTIVE"
