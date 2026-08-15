"""Payments: immutability, waterfall bucket order, immediate consistency,
dpa_id filtering, and customer self-pay."""
from test_helpers import (
    api_client, validate_success, validate_paginated,
    assert_payment, assert_breakdown_sums_to,
    create_account, charge_arrearage, charge_current, pay, get_account, create_dpa,
    TEST_USERS, make_customer_headers,
)

ADMIN = TEST_USERS["admin_headers"]
CSR = TEST_USERS["csr_headers"]


def test_payment_immutable_event_no_version(api):
    """PRD §2.5: "The Payment resource is the deliberate exception. A payment is
    an immutable posting record: it carries only `id` and `created_at`, with no
    `updated_at` and no `version`."
    PRD §3.5: "The posting stamps `paid_at` with the logical clock."

    Design: Corner/entities/payment_immutable_event_no_version
    """
    account = create_account(service_address="3 Event Way")
    charge_arrearage(account["id"], 3_000)
    payment = pay(account["id"], 3_000, tender_type="CASH")
    fetched = validate_success(api.get_payment(payment["id"], CSR), 200)
    assert_payment(fetched)
    assert str(fetched["paid_at"]).startswith("2026-08-01T00:00:00"), (
        f"paid_at must be stamped with the logical clock, got {fetched['paid_at']!r}")


def test_payment_waterfall_bucket_order(api):
    """PRD §3.5: "`applied_breakdown`, a computed object with seven buckets —
    `reconnection_fee_cents`, `down_payment_cents`, `installment_cents`,
    `dpa_extra_cents`, `arrearage_cents`, `current_charges_cents`, and
    `overpayment_cents` — that together sum to the tendered amount."
    PRD §3.5: "Fifth, the account's open `arrearage_balance_cents`; sixth, its
    `current_charges_balance_cents`; seventh and last, anything left over lands
    in `credit_balance_cents` as overpayment."
    PRD §3.1: "whenever the arrearage balance stands at zero, `arrearage_since`
    is null."

    Design: Corner/calculations/payment_waterfall_bucket_order
    """
    account = create_account(service_address="22 Waterfall Way")
    charge_arrearage(account["id"], 3_000)
    charge_current(account["id"], 4_000)
    payment = pay(account["id"], 5_000, tender_type="CARD")
    assert payment["applied_breakdown"] == {
        "reconnection_fee_cents": 0,
        "down_payment_cents": 0,
        "installment_cents": 0,
        "dpa_extra_cents": 0,
        "arrearage_cents": 3_000,
        "current_charges_cents": 2_000,
        "overpayment_cents": 0,
    }
    assert payment["dpa_id"] is None, "no DPA buckets touched, so dpa_id is null"
    account = get_account(account["id"])
    assert account["arrearage_balance_cents"] == 0
    assert account["arrearage_since"] is None
    assert account["current_charges_balance_cents"] == 2_000
    assert account["credit_balance_cents"] == 0


def test_immediate_consistency_payment_then_read(api):
    """PRD §3.5: "Fifth, the account's open `arrearage_balance_cents`; sixth, its
    `current_charges_balance_cents`; seventh and last, anything left over lands
    in `credit_balance_cents` as overpayment."
    PRD §3.5: "After the waterfall runs, posting recomputes the account's
    `delinquency_tier` and performs the open-order auto-cancel check".
    PRD §3.1: "whenever the arrearage balance stands at zero, `arrearage_since`
    is null."

    Design: Corner/consistency_model/immediate_consistency_payment_then_read
    """
    account = create_account(service_address="90 Immediate Isle")
    charge_arrearage(account["id"], 7_000)
    payment = pay(account["id"], 7_000, tender_type="CASH")
    assert payment["applied_breakdown"]["arrearage_cents"] == 7_000
    reread = get_account(account["id"])
    assert reread["arrearage_balance_cents"] == 0
    assert reread["arrearage_since"] is None


def test_payments_filtered_by_dpa_id(api):
    """PRD §3.5: "The payments listing filters by `account_id` and `dpa_id`."
    PRD §3.5: "Whenever any portion routes through the down-payment, installment,
    or extra buckets, the payment's `dpa_id` is set to that agreement; otherwise
    `dpa_id` is null."

    Design: Corner/endpoints/payments_filtered_by_dpa_id
    """
    acct_a = create_account(service_address="63 Filter Rd A")
    charge_arrearage(acct_a["id"], 120_000)
    dpa = create_dpa(acct_a["id"], installment_count=4)
    pay_a = pay(acct_a["id"], 12_000, tender_type="CASH")
    assert pay_a["dpa_id"] == dpa["id"]

    acct_b = create_account(service_address="64 Filter Rd B")
    pay(acct_b["id"], 5_000, tender_type="CASH")

    rows, meta = validate_paginated(api.list_payments(ADMIN, params={"dpa_id": dpa["id"]}))
    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert rows[0]["id"] == pay_a["id"]


def test_customer_pays_own_account(api):
    """PRD §3.5: "A `Customer` (for their own account) or a `CustomerServiceRep`
    tenders a payment naming the `account_id`, an `amount_cents` strictly greater
    than zero, and a `tender_type` of `CASH`, `CARD`, `CHECK`, or `MONEY_ORDER`."
    PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the
    acting CustomerAccount".

    Design: Corner/rbac/customer_pays_own_account
    """
    account = create_account(service_address="74 Selfpay St")
    charge_arrearage(account["id"], 3_000)
    resp = api.create_payment(
        {"account_id": account["id"], "amount_cents": 3_000, "tender_type": "CARD"},
        make_customer_headers(account["id"]))
    payment = validate_success(resp, 201)
    assert_payment(payment)
    assert payment["applied_breakdown"]["arrearage_cents"] == 3_000
    assert_breakdown_sums_to(payment["applied_breakdown"], 3_000)
