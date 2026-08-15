"""Booking gates: cross-entity state, utilization boundary, safety rails.

Covers difficulty instances loan_booking_requires_borrower_active,
utilization_exactly_9000bps_blocked_8999_allowed,
state_error_beats_fiscal_error_on_confirm, plus related corner instances.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_borrow_request,
    create_loan_proposal,
    create_owner,
    create_position,
    create_security,
    create_borrower,
    get_borrower,
    get_loan,
    get_position,
    make_borrower_rep_headers,
    make_owner_rep_headers,
    setup_booked_loan,
    setup_desk,
    validate_error,
    validate_success,
)

TRADER = TEST_USERS["desk_trader_headers"]
RISK = TEST_USERS["risk_officer_headers"]
ADMIN = TEST_USERS["desk_admin_headers"]


def _booking_setup(symbol="XDP1", credit_limit_cents=100_000_000,
                   quantity=4000):
    security, owner, borrower, position = setup_desk(
        security_symbol=symbol, credit_limit_cents=credit_limit_cents)
    loan = create_loan_proposal(owner, borrower, security, position,
                                quantity=quantity, rate_bps=25)
    return security, owner, borrower, position, loan


class TestLoanBookingRequiresBorrowerActive:
    def test_suspended_borrower_blocks_accept_and_resume_unblocks(self, api):
        """PRD §3.4: "Both paths enforce the same battery of preconditions,
        evaluated in this order: the borrower must be `ACTIVE`
        (`ERR_BORROWER_SUSPENDED`)"
        PRD §3.8: "Suspending a borrower — `ACTIVE` to `SUSPENDED` — cancels
        every `SUBMITTED` borrow request of that borrower; resuming restores
        `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/loan_booking_requires_borrower_active
        """
        _, _, borrower, _, loan = _booking_setup()
        validate_success(api.suspend_borrower(borrower["id"], RISK))
        resp = api.accept_loan(
            loan["id"], make_borrower_rep_headers(borrower["id"]))
        validate_error(resp, ApiErrorId.ERR_BORROWER_SUSPENDED)
        validate_success(api.resume_borrower(borrower["id"], RISK))
        booked = validate_success(api.accept_loan(
            loan["id"], make_borrower_rep_headers(borrower["id"])))
        assert booked["status"] == "BOOKED"
        assert booked["original_price_cents"] == 1000

    def test_proposal_survives_suspension_window(self, api):
        """PRD §3.4: "Both paths enforce the same battery of preconditions,
        evaluated in this order: the borrower must be `ACTIVE`
        (`ERR_BORROWER_SUSPENDED`)"

        The proposal is not consumed by the rejection: after resume the same
        loan id books successfully with the price captured at booking.

        Design: Difficulty/cross_entity_state_dependency/loan_booking_requires_borrower_active
        """
        _, _, borrower, position, loan = _booking_setup()
        validate_success(api.suspend_borrower(borrower["id"], RISK))
        first = api.accept_loan(
            loan["id"], make_borrower_rep_headers(borrower["id"]))
        validate_error(first, ApiErrorId.ERR_BORROWER_SUSPENDED)
        assert get_loan(loan["id"])["status"] == "PROPOSED"
        validate_success(api.resume_borrower(borrower["id"], RISK))
        booked = validate_success(api.accept_loan(
            loan["id"], make_borrower_rep_headers(borrower["id"])))
        assert booked["status"] == "BOOKED"
        pos = get_position(position["id"])
        assert pos["quantity_on_loan"] == 4000


class TestUtilizationBoundary:
    def _setup(self, api):
        security, owner, borrower, position = setup_desk(
            security_symbol="UTL1", credit_limit_cents=100_000_000,
            quantity_total=1_000_000)
        headers = make_borrower_rep_headers(borrower["id"])
        return security, owner, borrower, position, headers

    def test_exactly_9000bps_blocked_and_8999_allowed(self, api):
        """PRD §2.9: "a booking that would push the borrower's prospective
        utilization to 9000 basis points or more of the effective limit —
        ninety percent — is refused with `ERR_CREDIT_LIMIT_EXCEEDED`. The
        gate is inclusive: a prospective utilization of exactly 9000 basis
        points is blocked."
        PRD §2.9: "The `utilization_bps` is `utilization_cents` multiplied by
        10000 and divided by `effective_limit_cents`, computed with integer
        floor division."

        Design: Difficulty/boundary_precision_check/utilization_exactly_9000bps_blocked_8999_allowed
        """
        security, owner, borrower, position, headers = self._setup(api)
        loan_a = create_loan_proposal(owner, borrower, security, position,
                                      quantity=50000, rate_bps=25)
        validate_success(api.accept_loan(loan_a["id"], headers))
        loan_b = create_loan_proposal(owner, borrower, security, position,
                                      quantity=40000, rate_bps=25)
        loan_c = create_loan_proposal(owner, borrower, security, position,
                                      quantity=39999, rate_bps=25)

        # B would land at exactly 9000bps: 50,000,000 + 40,000,000 = 90,000,000c
        # on a 100,000,000c limit -> floor(90000000*10000/100000000) = 9000.
        resp_b = api.accept_loan(loan_b["id"], headers)
        validate_error(resp_b, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
        assert get_loan(loan_b["id"])["status"] == "PROPOSED"

        # C lands at floor(89999000*10000/100000000) = 8999bps: allowed.
        booked_c = validate_success(api.accept_loan(loan_c["id"], headers))
        assert booked_c["status"] == "BOOKED"

        b = get_borrower(borrower["id"])
        assert b["utilization_cents"] == 89999000
        assert b["utilization_bps"] == 8999

    def test_utilization_counts_only_booked_loans(self, api):
        """PRD §2.9: "A borrower's `utilization_cents` is the sum of
        `market_value_cents` — outstanding quantity times the security's
        current marked price — across exactly that borrower's loans in
        `BOOKED` or `RECALLED` status; proposals still in negotiation do not
        count until they book."

        Design: Corner/calculations/utilization_ignores_proposed_loans
        """
        security, owner, borrower, position, _ = self._setup(api)
        create_loan_proposal(owner, borrower, security, position,
                             quantity=50000, rate_bps=25)
        b = get_borrower(borrower["id"])
        assert b["utilization_cents"] == 0
        assert b["utilization_bps"] == 0

    def test_utilization_gate_is_on_effective_limit_with_floor(self, api):
        """PRD §2.9: "The `utilization_bps` is `utilization_cents` multiplied
        by 10000 and divided by `effective_limit_cents`, computed with
        integer floor division."
        PRD §2.9: "a booking that would push the borrower's prospective
        utilization to 9000 basis points or more of the effective limit —
        ninety percent — is refused with `ERR_CREDIT_LIMIT_EXCEEDED`."

        Floor-division probe: 50,000,000c + 39,999,999c = 89,999,999c ->
        floor(89999999 x 10000 / 100000000) = 8999 (just below the gate), so
        the booking succeeds; the borrowed market value then drives
        utilization_cents to 89,999,999.

        Design: Difficulty/boundary_precision_check/utilization_exactly_9000bps_blocked_8999_allowed
        """
        security, owner, borrower, position = setup_desk(
            security_symbol="UTL2", credit_limit_cents=100_000_000,
            quantity_total=1_000_000)
        headers = make_borrower_rep_headers(borrower["id"])
        loan_a = create_loan_proposal(owner, borrower, security, position,
                                      quantity=50000, rate_bps=25)
        validate_success(api.accept_loan(loan_a["id"], headers))
        # 39,999.999 shares is not expressible; approximate the floor probe
        # with 39,999 shares (89,999,000c) and confirm utilization fields.
        loan_c = create_loan_proposal(owner, borrower, security, position,
                                      quantity=39999, rate_bps=25)
        validate_success(api.accept_loan(loan_c["id"], headers))
        b = get_borrower(borrower["id"])
        assert b["utilization_cents"] == 89999000
        assert b["utilization_bps"] == 8999


class TestPriorityPairs:
    def test_state_error_beats_fiscal_error_on_confirm(self, api):
        """PRD §2.7: "When several checks could fail on the same request, the
        server evaluates them in a fixed priority order and reports the first
        failure, so that an early failure is never masked by a later one."
        PRD §2.7: "6. **State** — the target entity is in a state from which
        the requested transition exists; otherwise `ERR_INVALID_STATE`."
        PRD §3.4: "the borrower's prospective utilization including this
        loan's market value must stay strictly below 9000 basis points of the
        effective limit, with exactly 9000 blocked
        (`ERR_CREDIT_LIMIT_EXCEEDED`)."

        Design: Difficulty/priority_pair_validation_conflict/state_error_beats_fiscal_error_on_confirm
        """
        security, owner, borrower, position = setup_desk(
            security_symbol="PRI1", credit_limit_cents=1_000_000,
            quantity_total=1_000_000)
        loan = create_loan_proposal(owner, borrower, security, position,
                                    quantity=1000, rate_bps=25)
        # 1000 sh x 1000c = 1,000,000c = 10000bps of the tiny limit —
        # the fiscal check would fail if reached. Cancel first so the
        # state check (priority 6) fires ahead of the fiscal one (10).
        validate_success(api.cancel_loan(loan["id"], TRADER))
        resp = api.confirm_loan(loan["id"], TRADER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_loan(loan["id"])["status"] == "CANCELLED"
        entries = api.list_ledger_entries(
            RISK, params={"loan_id": loan["id"]})
        from test_helpers import get_success_data
        assert get_success_data(entries) == []

    def test_fiscal_error_fires_when_state_is_valid(self, api):
        """PRD §2.7: "the server evaluates them in a fixed priority order and
        reports the first failure"
        PRD §3.4: "the borrower's prospective utilization including this
        loan's market value must stay strictly below 9000 basis points of the
        effective limit, with exactly 9000 blocked
        (`ERR_CREDIT_LIMIT_EXCEEDED`)."

        With the loan still in a valid state for booking (PROPOSED), the
        fiscal rule is the first failure reached and reports
        `ERR_CREDIT_LIMIT_EXCEEDED` — confirming the priority pair isolates
        the fiscal branch when the state branch does not fire.

        Design: Difficulty/priority_pair_validation_conflict/state_error_beats_fiscal_error_on_confirm
        """
        security, owner, borrower, position = setup_desk(
            security_symbol="PRI1B", credit_limit_cents=1_000_000,
            quantity_total=1_000_000)
        loan = create_loan_proposal(owner, borrower, security, position,
                                    quantity=1000, rate_bps=25)
        # 1000 sh x 1000c = 100% of the limit: prospective 10000bps >= 9000.
        resp = api.accept_loan(
            loan["id"], make_borrower_rep_headers(borrower["id"]))
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
        assert get_loan(loan["id"])["status"] == "PROPOSED"


class TestSafetyGates:
    def test_halted_security_blocks_create_and_collateral_pledge(self, api):
        """PRD §3.1: "While a security is `HALTED`, four operations are
        refused with `ERR_SECURITY_HALTED`: creating a direct loan proposal
        in it, matching a borrow request for it, booking a loan in it, and
        pledging it as collateral."

        Design: Corner/state_machines/halted_security_blocks_create_and_collateral_pledge
        """
        s1 = create_security(symbol="SMC1", asset_class="EQUITY",
                             price_cents=1000)
        s2 = create_security(symbol="SMC2", asset_class="GOV_BOND",
                             price_cents=10000)
        owner = create_owner(display_name="Owner Smc")
        borrower = create_borrower(display_name="Borrower Smc")
        pos = create_position(owner, s1, quantity_total=10000)
        cpos = create_position(owner, s2, quantity_total=10000)
        loan = create_loan_proposal(owner, borrower, s1, pos, quantity=1000)
        booked = validate_success(api.accept_loan(
            loan["id"], make_borrower_rep_headers(borrower["id"])))
        validate_success(api.halt_security(s2["id"], ADMIN))

        resp_create = api.create_loan(
            {"owner_id": owner["id"], "borrower_id": borrower["id"],
             "security_id": s2["id"], "position_id": cpos["id"],
             "quantity": 100, "collateral_type": "SECURITIES",
             "rate_bps": 25}, TRADER)
        validate_error(resp_create, ApiErrorId.ERR_SECURITY_HALTED)

        resp_pledge = api.create_pledge(
            booked["id"],
            {"pledge_type": "SECURITY", "pledge_security_id": s2["id"],
             "quantity": 117},
            make_borrower_rep_headers(borrower["id"]))
        validate_error(resp_pledge, ApiErrorId.ERR_SECURITY_HALTED)
        assert get_loan(booked["id"])["status"] == "BOOKED"

    def test_suspended_position_rejected_at_match(self, api):
        """PRD §3.2: "A `SUSPENDED` position cannot be matched or booked —
        attempts fail with `ERR_POSITION_SUSPENDED`"

        Design: Corner/state_machines/suspended_position_rejected_at_match
        """
        security, owner, borrower, position = setup_desk(
            security_symbol="SMD", quantity_total=10000)
        request = create_borrow_request(borrower, security, quantity=1000)
        validate_success(api.suspend_lendable_position(
            position["id"], make_owner_rep_headers(owner["id"])))
        resp = api.match_borrow_request(
            request["id"], {"position_id": position["id"]}, TRADER)
        validate_error(resp, ApiErrorId.ERR_POSITION_SUSPENDED)
