"""Payments: waterfall allocation, escrow files, amount validation, paid-bill lockout."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    assert_payment,
    create_tax_year, create_parcel, create_escrow_agent, issue_bill,
    setup_year_parcel_bill, installments_by_bill, get_bill, post_payment,
    create_payment_payload,
    TEST_USERS,
)

CASHIER = TEST_USERS["cashier_headers"]


# ---- Corner: calculations/payment_partial_allocation_waterfall ----
def test_payment_partial_allocation_waterfall(api):
    """PRD 3.4: "An installment moves from `PENDING` to `PARTIALLY_PAID` when its allocated
    principal is positive but less than its `principal_due_cents`, and to
    `PAID` when its balance reaches zero"
    PRD 3.4: "Any amount still remaining after every installment is satisfied becomes
    `overpayment_applied_cents` on the payment and is retained as the
    bill's overpayment"

    Design: Corner/calculations/payment_partial_allocation_waterfall
    """
    ty, parcel, bill = setup_year_parcel_bill(api, assessed_value_cents=20000000)
    pay = post_payment(api, bill["id"], 250000)
    insts = installments_by_bill(api, bill["id"])
    assert insts[1]["status"] == "PAID"
    assert insts[2]["paid_cents"] == 50000
    assert insts[2]["balance_cents"] == 150000
    assert get_bill(api, bill["id"])["collection_status"] == "PARTIALLY_PAID"
    assert pay["overpayment_applied_cents"] == 0


# ---- Corner: calculations/escrow_payment_records_agent_and_source ----
def test_escrow_payment_records_agent_and_source(api):
    """PRD 3.4: "When `source` is `ESCROW`, an `escrow_agent_id` identifying the paying
    servicer is required and its omission is rejected with
    `ERR_ESCROW_AGENT_REQUIRED`"
    PRD 3.4: "a payment that clears the balance to zero with all installments paid
    yields `PAID`."

    Design: Corner/calculations/escrow_payment_records_agent_and_source
    """
    agent = create_escrow_agent(api, servicer_code="BBS", name="BigBank Servicing")
    ty = create_tax_year(api)
    parcel = create_parcel(api, parcel_number="APN-C12", assessed_value_cents=20000000,
                           escrow_agent_id=agent["id"])
    bill = issue_bill(api, parcel["id"], ty["id"])
    pay = post_payment(api, bill["id"], 400000, tender_type="ACH",
                       source="ESCROW", escrow_agent_id=agent["id"])
    assert_payment(pay)
    assert pay["source"] == "ESCROW"
    assert pay["escrow_agent_id"] == agent["id"]
    assert get_bill(api, bill["id"])["collection_status"] == "PAID"


# ---- Corner: validations/zero_amount_payment_rejected ----
def test_zero_amount_payment_rejected(api):
    """PRD 3.4: "A zero or negative `amount_cents` is rejected with `ERR_ZERO_AMOUNT`."

    Design: Corner/validations/zero_amount_payment_rejected
    """
    ty, parcel, bill = setup_year_parcel_bill(api, assessed_value_cents=20000000)
    resp = api.create_payment(create_payment_payload(bill["id"], 0, tender_type="CASH",
                                                     source="COUNTER"), CASHIER)
    validate_error(resp, ApiErrorId.ERR_ZERO_AMOUNT.value)


# ---- Corner: validations/escrow_source_without_agent_rejected ----
def test_escrow_source_without_agent_rejected(api):
    """PRD 3.4: "When `source` is `ESCROW`, an `escrow_agent_id` identifying the paying
    servicer is required and its omission is rejected with
    `ERR_ESCROW_AGENT_REQUIRED`"

    Design: Corner/validations/escrow_source_without_agent_rejected
    """
    ty, parcel, bill = setup_year_parcel_bill(api, assessed_value_cents=20000000)
    resp = api.create_payment(create_payment_payload(bill["id"], 100000, tender_type="ACH",
                                                     source="ESCROW"), CASHIER)
    validate_error(resp, ApiErrorId.ERR_ESCROW_AGENT_REQUIRED.value)


# ---- Difficulty: payment_rejected_when_bill_paid (test 1 of 2) ----
def test_payment_on_fully_paid_bill_rejected(api):
    """PRD 3.4: "A payment against a bill whose `collection_status` is already `PAID` is
    rejected with `ERR_BILL_ALREADY_PAID`."

    Design: Difficulty/cross_entity_state_dependency/payment_rejected_when_bill_paid
    """
    ty, parcel, bill = setup_year_parcel_bill(api, assessed_value_cents=20000000)
    post_payment(api, bill["id"], 400000, tender_type="ACH")
    assert get_bill(api, bill["id"])["collection_status"] == "PAID"
    resp = api.create_payment(create_payment_payload(bill["id"], 100, tender_type="CASH",
                                                     source="COUNTER"), CASHIER)
    validate_error(resp, ApiErrorId.ERR_BILL_ALREADY_PAID.value)


# ---- Difficulty: payment_rejected_when_bill_paid (test 2 of 2) ----
def test_paid_bill_rejects_further_payment_balance_unchanged(api):
    """PRD 3.4: "A payment against a bill whose `collection_status` is already `PAID` is
    rejected with `ERR_BILL_ALREADY_PAID`."

    Design: Difficulty/cross_entity_state_dependency/payment_rejected_when_bill_paid
    """
    ty, parcel, bill = setup_year_parcel_bill(api, assessed_value_cents=20000000)
    post_payment(api, bill["id"], 400000, tender_type="ACH")
    resp = api.create_payment(create_payment_payload(bill["id"], 5000, tender_type="CHECK",
                                                     source="COUNTER"), CASHIER)
    validate_error(resp, ApiErrorId.ERR_BILL_ALREADY_PAID.value)
    after = get_bill(api, bill["id"])
    assert after["collection_status"] == "PAID"
    assert after["balance_cents"] == 0
