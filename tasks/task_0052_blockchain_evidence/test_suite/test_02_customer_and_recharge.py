"""Customer bootstrap, wallet recharge, payment events, duplicate ref.

PRD §3.1, §2.11.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    assert_customer,
    assert_recharge,
    create_customer,
    create_customer_payload,
    create_customer_with_balance,
    create_recharge_payload,
    get_customer,
    list_audit_logs,
    make_customer_headers,
    payment_event_payload,
    random_payment_ref,
    recharge_and_pay,
    validate_error,
    validate_success,
)


# ===========================================================================
# Customer bootstrap (PRD §3.1)
# ===========================================================================
class TestCustomerBootstrap:
    """PRD §3.1: 'a PlatformAdmin bootstraps a Customer record carrying
    an email (RFC 5322 syntax, unique across active customers) and a
    display_name that will later be printed on issued certificates. A
    successful bootstrap pairs the newly-minted customer with a
    FeeAccount ledger whose lifetime_recharge_cents and
    lifetime_deduction_cents both start at zero ... The customer's
    wallet_balance_cents likewise starts at zero, the status column
    starts at ACTIVE'."""

    def test_create_customer_defaults(self, api, admin_headers):
        """PRD §3.1: 'wallet_balance_cents likewise starts at zero, the
        status column starts at ACTIVE'."""
        payload = create_customer_payload(
            email="alice@example.com", display_name="Alice",
        )
        customer = validate_success(
            api.create_customer(payload, admin_headers), 201,
        )
        assert_customer(customer)
        assert customer["email"] == "alice@example.com"
        assert customer["display_name"] == "Alice"
        assert customer["wallet_balance_cents"] == 0
        assert customer["status"] == "ACTIVE"
        assert customer["version"] == 1

    def test_get_customer_round_trip(self, api, admin_headers):
        """PRD §4: 'GET /customers/{id}' reads the row."""
        created = create_customer(email="bob@example.com")
        got = validate_success(
            api.get_customer(created["id"], admin_headers), 200,
        )
        assert got["id"] == created["id"]
        assert got["email"] == "bob@example.com"


# ===========================================================================
# Recharge flow (PRD §3.1)
# ===========================================================================
class TestRechargeFlow:
    """PRD §3.1: 'the Customer opens a recharge by providing the target
    customer_id, the amount_cents (at least 100 cents and at most
    10 000 000 cents), and the external_payment_ref ... The recharge is
    created in PENDING. Later, the PlatformAdmin delivers a payment
    event ... when the event payload status is success and its
    external_payment_ref matches a PENDING Recharge, the recharge
    advances to COMPLETED, the customer's wallet_balance_cents is
    credited by amount_cents, the FeeAccount.lifetime_recharge_cents is
    incremented by the same amount'."""

    def test_recharge_starts_in_pending(self, api):
        customer = create_customer()
        headers = make_customer_headers(customer["id"])
        rch = validate_success(api.create_recharge(
            create_recharge_payload(
                customer_id=customer["id"], amount_cents=50_000,
            ),
            headers,
        ), 201)
        assert_recharge(rch)
        assert rch["status"] == "PENDING"
        assert rch["amount_cents"] == 50_000
        # Wallet still 0 — credit happens on the SUCCESS event.
        cust_after = get_customer(customer["id"])
        assert cust_after["wallet_balance_cents"] == 0

    def test_payment_success_credits_wallet(self, api, admin_headers):
        """PRD §3.1: 'when the event payload status is success and its
        external_payment_ref matches a PENDING Recharge, the recharge
        advances to COMPLETED, the customer's wallet_balance_cents is
        credited by amount_cents'."""
        customer = create_customer()
        headers = make_customer_headers(customer["id"])
        ref = random_payment_ref()
        validate_success(api.create_recharge(
            create_recharge_payload(
                customer_id=customer["id"],
                amount_cents=12_345,
                external_payment_ref=ref,
            ),
            headers,
        ), 201)
        validate_success(api.deliver_payment_event(
            payment_event_payload(
                external_payment_ref=ref, status="SUCCESS",
            ),
            admin_headers,
        ), 200)
        cust_after = get_customer(customer["id"])
        assert cust_after["wallet_balance_cents"] == 12_345

    def test_payment_failure_leaves_balance_unchanged(
            self, api, admin_headers):
        """PRD §3.1: 'A payment event whose payload status is failure
        transitions the same recharge to FAILED without crediting
        anything.'"""
        customer = create_customer()
        headers = make_customer_headers(customer["id"])
        ref = random_payment_ref()
        validate_success(api.create_recharge(
            create_recharge_payload(
                customer_id=customer["id"],
                amount_cents=9_999,
                external_payment_ref=ref,
            ),
            headers,
        ), 201)
        validate_success(api.deliver_payment_event(
            payment_event_payload(
                external_payment_ref=ref, status="FAILURE",
            ),
            admin_headers,
        ), 200)
        cust_after = get_customer(customer["id"])
        assert cust_after["wallet_balance_cents"] == 0

    def test_recharge_completed_audit_event(self, api):
        """PRD §3.1: 'an audit row of event_type RECHARGE_COMPLETED is
        appended.'"""
        customer = create_customer()
        recharge_and_pay(customer, amount_cents=7_777)
        rows = list_audit_logs(
            event_type="RECHARGE_COMPLETED",
            target_entity="Recharge",
        )
        # At least one RECHARGE_COMPLETED row for this customer.
        assert len(rows) >= 1


# ===========================================================================
# Duplicate external_payment_ref (PRD §2.11)
# ===========================================================================
class TestDuplicatePaymentRef:
    """PRD §2.11: 'Two payment events arriving with the same
    external_payment_ref are deduplicated by the unique constraint on
    Recharge.external_payment_ref: the wallet is credited at most once,
    and the second event is rejected with ERR_DUPLICATE_PAYMENT_REF.'

    PRD §2.10 priority 21: 'external_payment_ref is globally unique
    across Recharge rows on POST /recharges and the same uniqueness is
    re-enforced on POST /_events/payment.'
    """

    def test_duplicate_recharge_with_same_ref_rejected(self, api):
        """PRD §2.10 priority 21: 'external_payment_ref is globally
        unique across Recharge rows on POST /recharges'."""
        customer = create_customer()
        headers = make_customer_headers(customer["id"])
        ref = random_payment_ref()
        validate_success(api.create_recharge(
            create_recharge_payload(
                customer_id=customer["id"],
                amount_cents=1_000,
                external_payment_ref=ref,
            ),
            headers,
        ), 201)
        res = api.create_recharge(
            create_recharge_payload(
                customer_id=customer["id"],
                amount_cents=1_000,
                external_payment_ref=ref,
            ),
            headers,
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_PAYMENT_REF.value)


# ===========================================================================
# Recharge amount boundary (PRD §3.1)
# ===========================================================================
class TestRechargeAmountBounds:
    """PRD §3.1: 'amount_cents (at least 100 cents and at most
    10 000 000 cents)'."""

    @pytest.mark.parametrize("amount", [99, 0, -1])
    def test_below_minimum_rejected(self, api, amount):
        """PRD §3.1: 'at least 100 cents'. Generic body-shape error per
        PRD §2.10 → ERR_VALIDATION_FAILED."""
        customer = create_customer()
        headers = make_customer_headers(customer["id"])
        res = api.create_recharge(
            create_recharge_payload(
                customer_id=customer["id"], amount_cents=amount,
            ),
            headers,
        )
        validate_error(res, ApiErrorId.ERR_VALIDATION_FAILED.value)

    def test_above_maximum_rejected(self, api):
        """PRD §3.1: 'at most 10 000 000 cents'."""
        customer = create_customer()
        headers = make_customer_headers(customer["id"])
        res = api.create_recharge(
            create_recharge_payload(
                customer_id=customer["id"], amount_cents=10_000_001,
            ),
            headers,
        )
        validate_error(res, ApiErrorId.ERR_VALIDATION_FAILED.value)
