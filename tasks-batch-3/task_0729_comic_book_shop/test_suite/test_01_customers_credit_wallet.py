"""Customers, credit transactions, and store-credit wallet conservation."""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_customer,
    assert_credit_transaction,
    create_customer_payload,
    create_credit_adjustment_payload,
    create_customer,
    customer_with_store_credit,
    TEST_USERS,
)

CLERK = TEST_USERS["clerk_headers"]
MANAGER = TEST_USERS["manager_headers"]


# ---------------------------------------------------------------------------
# Queue B — entities
# ---------------------------------------------------------------------------
def test_create_customer_returns_defaults(api, clerk_headers):
    """PRD §3.8: "A customer is created with an email (unique per customer) and a
    full_name, and opens with loyalty_tier at BRONZE, store_credit_cents at 0,
    loyalty_points_balance at 0, lifetime_spend_cents at 0, and status at ACTIVE."

    Design: Corner/entities/create_customer_returns_defaults
    """
    res = api.create_customer(create_customer_payload(full_name="New Cust"), clerk_headers)
    cust = validate_success(res, 201)
    assert_customer(cust)
    assert cust["loyalty_tier"] == "BRONZE"
    assert cust["store_credit_cents"] == 0
    assert cust["loyalty_points_balance"] == 0
    assert cust["lifetime_spend_cents"] == 0
    assert cust["status"] == "ACTIVE"


def test_create_customer_missing_full_name_returns_validation(api, clerk_headers):
    """PRD §2.8: "Well-formedness — required fields present, enums valid, numbers
    in range, ends_at strictly after starts_at, and commission_pct at least 0 and
    strictly below 1, else ERR_VALIDATION (400)."

    Design: Corner/entities/create_customer_missing_full_name_returns_validation
    """
    res = api.create_customer({"email": "x@x.com"}, clerk_headers)
    validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=400)


def test_get_customer_nonexistent_returns_not_found(api, clerk_headers):
    """PRD §2.8: "Existence — every path id and every foreign-key id in the body
    resolves to an existing resource, checked left to right, else ERR_NOT_FOUND
    (404)."

    Design: Corner/entities/get_customer_nonexistent_returns_not_found
    """
    res = api.get_customer(NON_EXISTENT_UUID, clerk_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_credit_transaction_immutable_no_version(api, manager_headers):
    """PRD §2.4: "A `CreditTransaction` is an append-only ledger event: it carries only `id` and `created_at`. It has neither `updated_at` nor `version`, because it is never modified after it is written."

    Design: Corner/entities/credit_transaction_immutable_no_version
    """
    cust = create_customer()
    txn = validate_success(
        api.create_credit_adjustment(
            cust["id"], create_credit_adjustment_payload(1000, "ADJUSTMENT"), manager_headers
        ),
        201,
    )
    read = validate_success(api.get_credit_transaction(txn["id"], manager_headers), 200)
    assert_credit_transaction(read)
    assert read["amount_cents"] == 1000
    assert read["balance_after_cents"] == 1000
    assert "version" not in read, "CreditTransaction must not carry a version field"
    assert "updated_at" not in read, "CreditTransaction must not carry an updated_at field"


# ---------------------------------------------------------------------------
# Queue B — rbac
# ---------------------------------------------------------------------------
def test_clerk_cannot_adjust_store_credit(api, clerk_headers):
    """PRD §2.1: "plus three fiscal-authority operations reserved exclusively to
    managers: manual store-credit adjustments, customer bans, and consignment
    payouts."

    Design: Corner/rbac/clerk_cannot_adjust_store_credit
    """
    cust = create_customer()
    res = api.create_credit_adjustment(
        cust["id"], create_credit_adjustment_payload(1000, "ADJUSTMENT"), clerk_headers
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


# ---------------------------------------------------------------------------
# Queue A — compensating_invariant: store-credit wallet conservation
# ---------------------------------------------------------------------------
def test_store_credit_reverses_to_zero_with_zero_balance_after(api, manager_headers):
    """PRD §3.8: "A manager may also make a manual store-credit adjustment, which writes a credit transaction carrying a signed `amount_cents` (positive to credit, negative to debit) and a `reason`, raises the customer's `store_credit_cents` by that `amount_cents`, records the resulting `balance_after_cents` on the transaction, and recomputes the customer's loyalty tier."

    Design: Difficulty/compensating_invariant/store_credit_conservation_across_adjust_and_reverse
    """
    cust, _txn1 = customer_with_store_credit(5000)
    assert cust["store_credit_cents"] == 5000
    txn2 = validate_success(
        api.create_credit_adjustment(
            cust["id"], create_credit_adjustment_payload(-5000, "ADJUSTMENT"), manager_headers
        ),
        201,
    )
    assert txn2["balance_after_cents"] == 0
    after = validate_success(api.get_customer(cust["id"], manager_headers), 200)
    assert after["store_credit_cents"] == 0


def test_store_credit_ledger_records_running_balance_no_drift(api, manager_headers):
    """PRD §3.8: "Every credit transaction records the affected `customer_id`, its signed `amount_cents`, its `reason` — one of `CONSIGNMENT_PAYOUT`, `REFUND`, `ADJUSTMENT`, or `REDEMPTION` — and the `balance_after_cents`, the wallet balance immediately after the transaction was applied."

    Design: Difficulty/compensating_invariant/store_credit_conservation_across_adjust_and_reverse
    """
    cust, txn1 = customer_with_store_credit(5000)
    assert txn1["balance_after_cents"] == 5000
    txn2 = validate_success(
        api.create_credit_adjustment(
            cust["id"], create_credit_adjustment_payload(-5000, "ADJUSTMENT"), manager_headers
        ),
        201,
    )
    assert txn2["amount_cents"] == -5000
    assert txn2["balance_after_cents"] == 0
    after = validate_success(api.get_customer(cust["id"], manager_headers), 200)
    assert after["store_credit_cents"] == 0
