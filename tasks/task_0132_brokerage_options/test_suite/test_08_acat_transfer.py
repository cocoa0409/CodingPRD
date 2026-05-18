"""ACAT transfer lifecycle: initiate -> validate -> in-transit ->
completed; cancel / reject branches; six-business-day ETA; outbound
lock cascade.

Coverage targets (PRD §3.5):
- Initiation initial state: INITIATED, initiated_at set,
  business_days_elapsed = 0.
- Minimum requested_value_cents = 100 -> ERR_VALIDATION on below.
- Outbound uniqueness: second non-terminal OUTBOUND ->
  ERR_TRANSFER_ALREADY_PENDING.
- Validate computes expected_completion_at by business-day walk to
  17:00:00 UTC on the 6th business day.
- Validate OUTBOUND with open orders -> ERR_OPEN_ORDERS_BLOCK_TRANSFER.
- Validate OUTBOUND -> posture := TRANSFER_LOCKED; non-terminal Orders
  -> CANCELLED.
- Clock-driven transitions VALIDATED -> IN_TRANSIT -> COMPLETED.
- INBOUND completion credits cash & equity.
- OUTBOUND completion debits cash & equity and reverts posture to OPEN.
- Cancel from INITIATED / VALIDATED, with TRANSFER_LOCKED revert when
  cancelling VALIDATED OUTBOUND.
- Cancel from IN_TRANSIT -> ERR_INVALID_STATE.
"""
from __future__ import annotations

from test_helpers import (
    ACAT_MIN_VALUE_CENTS,
    ApiErrorId,
    TEST_USERS,
    advance_clock,
    assert_acat_transfer,
    create_acat_transfer_payload,
    make_customer_headers,
    reject_acat_transfer_payload,
    setup_account_with_outbound_acat_initiated,
    setup_account_with_outbound_acat_validated,
    setup_account_with_working_limit_order,
    setup_approved_customer_and_account,
    setup_for_acat_completion_two_hop_cascade,
    setup_funded_account,
    validate_error,
    validate_success,
)


# ===========================================================================
# Initiation — PRD §3.5
# ===========================================================================
class TestAcatInitiation:
    """PRD §3.5: 'The new row is created with status set to INITIATED,
    initiated_at set to the current now(), expected_completion_at and
    completed_at null until later, and business_days_elapsed at 0.'"""

    def test_inbound_initiation_initial_state(self, api):
        """PRD §3.5: "The new row is created with status set to
        INITIATED, initiated_at set to the current now(),
        expected_completion_at and completed_at null until later, and
        business_days_elapsed at 0."

        Claim: a newly-initiated INBOUND transfer has status=INITIATED,
        initiated_at populated, expected_completion_at and completed_at
        null, business_days_elapsed=0.
        """
        customer, account = setup_approved_customer_and_account()
        resp = api.create_acat_transfer(
            create_acat_transfer_payload(
                account_id=account["id"], direction="INBOUND",
                requested_value_cents=100_000,
            ),
            make_customer_headers(customer["id"]),
        )
        transfer = validate_success(resp, expected_status=201)
        assert_acat_transfer(transfer)
        assert transfer["status"] == "INITIATED"
        assert transfer["initiated_at"]
        assert transfer["expected_completion_at"] is None
        assert transfer["completed_at"] is None
        assert transfer["business_days_elapsed"] == 0

    def test_value_below_minimum_rejected(self, api):
        """PRD §3.5: "the transfer value is in US cents, and a minimum
        of 100 cents (one dollar) is enforced — anything below is
        rejected with ERR_VALIDATION."

        Claim: requested_value_cents=99 -> ERR_VALIDATION / 422.
        """
        customer, account = setup_approved_customer_and_account()
        resp = api.create_acat_transfer(
            create_acat_transfer_payload(
                account_id=account["id"], direction="INBOUND",
                requested_value_cents=ACAT_MIN_VALUE_CENTS - 1,
            ),
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ===========================================================================
# Outbound uniqueness — PRD §3.5
# ===========================================================================
class TestOutboundUniqueness:
    """PRD §3.5: 'At most one OUTBOUND transfer per account may sit in
    a non-terminal status (INITIATED, VALIDATED, or IN_TRANSIT); a
    second outbound submission against the same account is rejected
    with ERR_TRANSFER_ALREADY_PENDING at HTTP 409.'"""

    def test_second_outbound_blocked(self, api):
        """PRD §3.5: "At most one OUTBOUND transfer per account may sit
        in a non-terminal status (INITIATED, VALIDATED, or IN_TRANSIT);
        a second outbound submission against the same account is
        rejected with ERR_TRANSFER_ALREADY_PENDING at HTTP 409."

        Claim: while first OUTBOUND is INITIATED, a second OUTBOUND for
        the same account -> ERR_TRANSFER_ALREADY_PENDING / 409.
        """
        customer, account, first = (
            setup_account_with_outbound_acat_initiated()
        )
        # Second OUTBOUND for the same account.
        resp = api.create_acat_transfer(
            create_acat_transfer_payload(
                account_id=account["id"], direction="OUTBOUND",
                requested_value_cents=200_000,
            ),
            make_customer_headers(customer["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_TRANSFER_ALREADY_PENDING.value,
        )

    def test_after_cancel_second_outbound_succeeds(self, api):
        """PRD §3.5: "At most one OUTBOUND transfer per account may sit
        in a non-terminal status (INITIATED, VALIDATED, or IN_TRANSIT);
        a second outbound submission against the same account is
        rejected with ERR_TRANSFER_ALREADY_PENDING at HTTP 409."

        Claim: after the first OUTBOUND is cancelled (terminal), a
        second OUTBOUND for the same account is accepted.
        """
        customer, account, first = (
            setup_account_with_outbound_acat_initiated()
        )
        # Cancel the first.
        cancel_resp = api.cancel_acat_transfer(
            first["id"], make_customer_headers(customer["id"]),
        )
        cancelled = validate_success(cancel_resp)
        assert cancelled["status"] == "CANCELLED"

        # Submit second.
        resp = api.create_acat_transfer(
            create_acat_transfer_payload(
                account_id=account["id"], direction="OUTBOUND",
                requested_value_cents=200_000,
            ),
            make_customer_headers(customer["id"]),
        )
        second = validate_success(resp, expected_status=201)
        assert second["status"] == "INITIATED"


# ===========================================================================
# Outbound validate gated by open orders — PRD §3.5
# ===========================================================================
class TestOutboundValidateOpenOrders:
    """PRD §3.5: 'when direction is OUTBOUND — no Order whose status is
    in ACCEPTED or WORKING; an outbound validate attempted with open
    orders is rejected with ERR_OPEN_ORDERS_BLOCK_TRANSFER at HTTP
    409.'"""

    def test_outbound_validate_blocked_by_working_order(self, api):
        """PRD §3.5: "when direction is OUTBOUND — no Order whose
        status is in ACCEPTED or WORKING; an outbound validate
        attempted with open orders is rejected with
        ERR_OPEN_ORDERS_BLOCK_TRANSFER at HTTP 409."

        Claim: OUTBOUND validate while a WORKING Order exists ->
        ERR_OPEN_ORDERS_BLOCK_TRANSFER / 409.
        """
        customer, account, order = (
            setup_account_with_working_limit_order(
                account_type="CASH", cash_amount_cents=10_000_000,
            )
        )
        # Now initiate an OUTBOUND.
        resp = api.create_acat_transfer(
            create_acat_transfer_payload(
                account_id=account["id"], direction="OUTBOUND",
                requested_value_cents=500_000,
            ),
            make_customer_headers(customer["id"]),
        )
        transfer = validate_success(resp, expected_status=201)
        # Validate while the working order is still open.
        v_resp = api.validate_acat_transfer(
            transfer["id"], TEST_USERS["compliance_headers"],
        )
        validate_error(
            v_resp, ApiErrorId.ERR_OPEN_ORDERS_BLOCK_TRANSFER.value,
        )


# ===========================================================================
# Validate succeeds + outbound posture lock — PRD §3.5
# ===========================================================================
class TestValidateSideEffects:
    """PRD §3.5: 'When direction is OUTBOUND, validation also flips
    Account.trading_posture from OPEN to TRANSFER_LOCKED as a cascade
    and cancels every Order on the account whose status is in ACCEPTED
    or WORKING'."""

    def test_outbound_validate_locks_posture(self, api):
        """PRD §3.5: "When direction is OUTBOUND, validation also flips
        Account.trading_posture from OPEN to TRANSFER_LOCKED as a
        cascade".

        Claim: after OUTBOUND validate, Account.trading_posture ==
        TRANSFER_LOCKED.
        """
        customer, account, transfer = (
            setup_account_with_outbound_acat_validated()
        )
        assert transfer["status"] == "VALIDATED"
        assert account["trading_posture"] == "TRANSFER_LOCKED"

    def test_inbound_validate_does_not_lock_posture(self, api):
        """PRD §3.5: "When direction is OUTBOUND, validation also
        flips Account.trading_posture from OPEN to TRANSFER_LOCKED as
        a cascade".

        Claim: an INBOUND validate does NOT flip posture (the lock is
        OUTBOUND-only).
        """
        customer, account = setup_approved_customer_and_account()
        resp = api.create_acat_transfer(
            create_acat_transfer_payload(
                account_id=account["id"], direction="INBOUND",
                requested_value_cents=100_000,
            ),
            make_customer_headers(customer["id"]),
        )
        transfer = validate_success(resp, expected_status=201)
        v_resp = api.validate_acat_transfer(
            transfer["id"], TEST_USERS["compliance_headers"],
        )
        validate_success(v_resp)
        fresh = validate_success(api.get_account(
            account["id"], make_customer_headers(customer["id"]),
        ))
        assert fresh["trading_posture"] == "OPEN"


# ===========================================================================
# Inbound completion side-effects — PRD §3.5
# ===========================================================================
class TestInboundCompletion:
    """PRD §3.5: 'An INBOUND completion adds requested_value_cents to
    both Account.cash_balance_cents and Account.equity_value_cents.'"""

    def test_inbound_completion_credits_cash_and_equity(self, api):
        """PRD §3.5: "An INBOUND completion adds requested_value_cents
        to both Account.cash_balance_cents and
        Account.equity_value_cents."

        Claim: after the clock crosses expected_completion_at on an
        INBOUND transfer, cash_balance_cents and equity_value_cents
        are each increased by requested_value_cents.
        """
        customer, account = setup_approved_customer_and_account()
        before_cash = account["cash_balance_cents"]
        before_equity = account["equity_value_cents"]
        amount = 1_000_000  # $10k
        resp = api.create_acat_transfer(
            create_acat_transfer_payload(
                account_id=account["id"], direction="INBOUND",
                requested_value_cents=amount,
            ),
            make_customer_headers(customer["id"]),
        )
        transfer = validate_success(resp, expected_status=201)
        api.validate_acat_transfer(
            transfer["id"], TEST_USERS["compliance_headers"],
        )
        # Push past 6 business days at 17:00 UTC.
        advance_clock(9 * 24 * 60 * 60)
        fresh = validate_success(api.get_account(
            account["id"], make_customer_headers(customer["id"]),
        ))
        assert (
            fresh["cash_balance_cents"] == before_cash + amount
        ), (
            "INBOUND completion must credit cash by "
            "requested_value_cents (PRD §3.5)"
        )
        assert (
            fresh["equity_value_cents"] == before_equity + amount
        ), (
            "INBOUND completion must credit equity by "
            "requested_value_cents (PRD §3.5)"
        )
        # Transfer reached COMPLETED.
        t_after = validate_success(api.get_acat_transfer(
            transfer["id"], make_customer_headers(customer["id"]),
        ))
        assert t_after["status"] == "COMPLETED"
        assert t_after["completed_at"]


# ===========================================================================
# Outbound completion cash debit + posture revert — PRD §3.5
# ===========================================================================
class TestOutboundCompletion:
    """PRD §3.5: 'An OUTBOUND completion subtracts requested_value_cents
    from both Account.cash_balance_cents and Account.equity_value_cents,
    and additionally — if the account is still in TRANSFER_LOCKED —
    reverts Account.trading_posture to OPEN'."""

    def test_outbound_completion_debits_and_reverts_posture(self, api):
        """PRD §3.5: "An OUTBOUND completion subtracts
        requested_value_cents from both Account.cash_balance_cents
        and Account.equity_value_cents, and additionally — if the
        account is still in TRANSFER_LOCKED — reverts
        Account.trading_posture to OPEN, since the outbound pipeline
        has now settled."

        Claim: after clock crosses expected_completion_at on an
        OUTBOUND transfer, cash and equity are each debited by
        requested_value_cents AND trading_posture reverts from
        TRANSFER_LOCKED to OPEN.
        """
        customer, account, transfer = (
            setup_for_acat_completion_two_hop_cascade(
                cash_amount_cents=10_000_000,
                transfer_value_cents=500_000,
            )
        )
        cash_before = account["cash_balance_cents"]
        equity_before = account["equity_value_cents"]
        assert account["trading_posture"] == "TRANSFER_LOCKED"
        advance_clock(9 * 24 * 60 * 60)  # past 6 BD + buffer.
        fresh = validate_success(api.get_account(
            account["id"], make_customer_headers(customer["id"]),
        ))
        assert fresh["cash_balance_cents"] == cash_before - 500_000
        assert fresh["equity_value_cents"] == equity_before - 500_000
        assert fresh["trading_posture"] == "OPEN"
        t_after = validate_success(api.get_acat_transfer(
            transfer["id"], make_customer_headers(customer["id"]),
        ))
        assert t_after["status"] == "COMPLETED"


# ===========================================================================
# Cancel transitions — PRD §3.5
# ===========================================================================
class TestAcatCancel:
    """PRD §3.5 cancel branches."""

    def test_cancel_validated_outbound_reverts_posture(self, api):
        """PRD §3.5: "The customer can cancel a transfer that is still
        in INITIATED or VALIDATED; cancellation moves the row to
        terminal CANCELLED, and — if the cancellation occurs on a
        VALIDATED OUTBOUND transfer — the trading posture reverts from
        TRANSFER_LOCKED back to OPEN."

        Claim: DELETE on a VALIDATED OUTBOUND transfer ->
        status=CANCELLED AND trading_posture=OPEN.
        """
        customer, account, transfer = (
            setup_account_with_outbound_acat_validated()
        )
        assert account["trading_posture"] == "TRANSFER_LOCKED"
        resp = api.cancel_acat_transfer(
            transfer["id"], make_customer_headers(customer["id"]),
        )
        cancelled = validate_success(resp)
        assert cancelled["status"] == "CANCELLED"
        fresh = validate_success(api.get_account(
            account["id"], make_customer_headers(customer["id"]),
        ))
        assert fresh["trading_posture"] == "OPEN"

    def test_cancel_in_transit_rejected(self, api):
        """PRD §3.5: "Once a transfer has advanced to IN_TRANSIT,
        customer cancellation is no longer possible: an attempt is
        rejected with ERR_INVALID_STATE."

        Claim: DELETE on an IN_TRANSIT transfer -> ERR_INVALID_STATE.
        """
        customer, account, transfer = (
            setup_account_with_outbound_acat_validated(
                cash_amount_cents=10_000_000,
                transfer_value_cents=500_000,
            )
        )
        # Advance one business day to land at IN_TRANSIT.
        advance_clock(2 * 24 * 60 * 60)
        # Re-read transfer.
        t = validate_success(api.get_acat_transfer(
            transfer["id"], make_customer_headers(customer["id"]),
        ))
        # PRD §3.5 says VALIDATED auto-advances to IN_TRANSIT after >=1
        # business day; tolerate either VALIDATED or IN_TRANSIT only if
        # the implementation interprets 'crosses' strictly. The test
        # contracts the IN_TRANSIT case — assert that the implementation
        # has advanced (PRD says it auto-advances on clock advance).
        assert t["status"] == "IN_TRANSIT", (
            f"PRD §3.5: 'When the clock crosses initiated_at plus one "
            f"business day, business_days_elapsed becomes greater than "
            f"or equal to 1 and the transfer auto-advances from "
            f"VALIDATED to IN_TRANSIT.' Got status={t['status']!r}."
        )
        resp = api.cancel_acat_transfer(
            transfer["id"], make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Reject — PRD §3.5
# ===========================================================================
class TestAcatReject:
    """PRD §3.5: 'Compliance can also reject a still-INITIATED transfer
    outright, carrying a reason in the body; this moves the row
    directly to terminal REJECTED.'"""

    def test_reject_initiated_transfer(self, api):
        """PRD §3.5: "Compliance can also reject a still-INITIATED
        transfer outright, carrying a reason in the body; this moves
        the row directly to terminal REJECTED."

        Claim: POST /acat-transfers/{id}/reject on INITIATED ->
        status=REJECTED.
        """
        customer, account, transfer = (
            setup_account_with_outbound_acat_initiated()
        )
        resp = api.reject_acat_transfer(
            transfer["id"],
            reject_acat_transfer_payload(reason="counterparty unknown"),
            TEST_USERS["compliance_headers"],
        )
        rejected = validate_success(resp)
        assert rejected["status"] == "REJECTED"
