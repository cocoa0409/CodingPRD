"""Payments, fund allocation and its refund reversal, the account-receivable
conservation on refund, overpayment/segregation guards, and the delinquency
grace-day boundary."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_payment_payload,
    make_billing_clerk_headers,
    setup_issued_bill, setup_paid_bill,
    find_ledger_entry,
)

ASSESSOR = TEST_USERS["assessor_headers"]
BILLING_CLERK = TEST_USERS["billing_clerk_headers"]


def test_fund_allocation_capital_round_then_subtract_5c(api):
    """PRD §2.5: "When an applied payment is split between the two municipal
    funds, the capital share is rounded and the operating share is then taken as
    the applied amount minus the rounded capital share, so the two shares always
    add back to exactly the amount applied."
    PRD §3.6: "The capital share is 30 percent of the applied amount, rounded to
    whole cents; the operating share is the applied amount minus that rounded
    capital share, so the two always sum to exactly the amount applied."

    Design: Difficulty/combinatorial_formula/fund_allocation_capital_round_then_subtract_mode_b
    """
    base = setup_issued_bill(api, measured_sqft=6000, land_use="RESIDENTIAL_MF")
    pay = validate_success(
        api.create_payment(
            create_payment_payload(base["bill"]["id"], base["account"]["id"], 5),
            BILLING_CLERK),
        expected_status=201)
    entries = validate_success(
        api.list_fund_ledger(BILLING_CLERK, params={"source_payment_id": pay["id"]}))
    assert find_ledger_entry(entries, "CAPITAL", "ALLOCATION")["amount_cents"] == 2
    assert find_ledger_entry(entries, "OPERATING", "ALLOCATION")["amount_cents"] == 3
    bill = validate_success(api.get_bill(base["bill"]["id"], BILLING_CLERK))
    assert bill["status"] == "PARTIALLY_PAID"


def test_fund_allocation_capital_round_then_subtract_15c(api):
    """PRD §3.6: "The capital share is 30 percent of the applied amount, rounded
    to whole cents; the operating share is the applied amount minus that rounded
    capital share, so the two always sum to exactly the amount applied."

    Design: Difficulty/combinatorial_formula/fund_allocation_capital_round_then_subtract_mode_b
    """
    # 0.30*15 = 4.5 -> round half up = 5 capital; operating = 15 - 5 = 10.
    base = setup_issued_bill(api, measured_sqft=6000, land_use="RESIDENTIAL_MF")
    pay = validate_success(
        api.create_payment(
            create_payment_payload(base["bill"]["id"], base["account"]["id"], 15),
            BILLING_CLERK),
        expected_status=201)
    entries = validate_success(
        api.list_fund_ledger(BILLING_CLERK, params={"source_payment_id": pay["id"]}))
    assert find_ledger_entry(entries, "CAPITAL", "ALLOCATION")["amount_cents"] == 5
    assert find_ledger_entry(entries, "OPERATING", "ALLOCATION")["amount_cents"] == 10


def test_fund_allocation_thirty_percent_split(api):
    """PRD §3.6: "Every applied payment is split between two municipal funds and
    recorded as two `FundLedgerEntry` rows. The capital share is 30 percent of
    the applied amount, rounded to whole cents; the operating share is the
    applied amount minus that rounded capital share."

    Design: Corner/calculations/fund_allocation_thirty_percent_split
    """
    base = setup_issued_bill(api, measured_sqft=18000, land_use="COMMERCIAL")
    pay = validate_success(
        api.create_payment(
            create_payment_payload(base["bill"]["id"], base["account"]["id"], 10000),
            BILLING_CLERK),
        expected_status=201)
    entries = validate_success(
        api.list_fund_ledger(BILLING_CLERK, params={"source_payment_id": pay["id"]}))
    assert find_ledger_entry(entries, "CAPITAL", "ALLOCATION")["amount_cents"] == 3000
    assert find_ledger_entry(entries, "OPERATING", "ALLOCATION")["amount_cents"] == 7000


def test_payment_settles_bill_and_account_eru6(api):
    """PRD §3.6: "a bill moves from `ISSUED` or `DELINQUENT` to `PARTIALLY_PAID`
    when the cumulative amount paid is greater than 0 but still less than
    `net_fee_cents`, and to `PAID` when the cumulative amount paid equals
    `net_fee_cents`."
    PRD §2.6: "On an account, `outstanding_balance_cents` is the sum, over that
    account's non-`VOID` bills, of each bill's `net_fee_cents` minus its
    `amount_paid_cents`."
    PRD §3.8: "An account is `CURRENT` when none of its bills is past its
    `due_date`."

    Design: Difficulty/transitive_cascade/payment_settles_bill_and_account_depth2
    """
    base = setup_issued_bill(api, measured_sqft=18000, land_use="COMMERCIAL")
    acct = validate_success(api.get_account(base["account"]["id"], BILLING_CLERK))
    assert acct["outstanding_balance_cents"] == 21500
    validate_success(
        api.create_payment(
            create_payment_payload(base["bill"]["id"], base["account"]["id"], 21500,
                                   method="CARD"), BILLING_CLERK),
        expected_status=201)
    bill = validate_success(api.get_bill(base["bill"]["id"], BILLING_CLERK))
    assert bill["status"] == "PAID"
    acct = validate_success(api.get_account(base["account"]["id"], BILLING_CLERK))
    assert acct["outstanding_balance_cents"] == 0
    assert acct["delinquency_status"] == "CURRENT"


def test_payment_settles_bill_and_account_eru3(api):
    """PRD §3.6: "and to `PAID` when the cumulative amount paid equals
    `net_fee_cents`."
    PRD §3.6: "Each payment recomputes the charged account's
    `outstanding_balance_cents` and its `delinquency_status`."

    Design: Difficulty/transitive_cascade/payment_settles_bill_and_account_depth2
    """
    # ERU 3.0 -> assessed 11500; paying it in full settles the bill and account.
    base = setup_issued_bill(api, measured_sqft=9000, land_use="COMMERCIAL")
    validate_success(
        api.create_payment(
            create_payment_payload(base["bill"]["id"], base["account"]["id"], 11500),
            BILLING_CLERK),
        expected_status=201)
    bill = validate_success(api.get_bill(base["bill"]["id"], BILLING_CLERK))
    assert bill["status"] == "PAID"
    acct = validate_success(api.get_account(base["account"]["id"], BILLING_CLERK))
    assert acct["outstanding_balance_cents"] == 0


def test_refund_conserves_total_fund_balance_21500(api):
    """PRD §3.6: "Finally, the refund writes two `FundLedgerEntry` rows of
    `entry_type` `REVERSAL`, one against the `CAPITAL` fund and one against the
    `OPERATING` fund, equal and opposite to the original allocation entries."

    Design: Difficulty/compensating_invariant/refund_conserves_total_fund_balance
    """
    base = setup_paid_bill(api, measured_sqft=18000, amount_cents=21500,
                           creator_user_id="clerk-a")
    pay_id = base["payment"]["id"]
    validate_success(api.refund_payment(pay_id, make_billing_clerk_headers("clerk-b")))
    entries = validate_success(
        api.list_fund_ledger(BILLING_CLERK, params={"source_payment_id": pay_id}))
    alloc_cap = find_ledger_entry(entries, "CAPITAL", "ALLOCATION")["amount_cents"]
    alloc_op = find_ledger_entry(entries, "OPERATING", "ALLOCATION")["amount_cents"]
    rev_cap = find_ledger_entry(entries, "CAPITAL", "REVERSAL")["amount_cents"]
    rev_op = find_ledger_entry(entries, "OPERATING", "REVERSAL")["amount_cents"]
    assert alloc_cap == 6450 and alloc_op == 15050
    assert rev_cap == 6450 and rev_op == 15050
    assert alloc_cap - rev_cap == 0 and alloc_op - rev_op == 0


def test_refund_conserves_total_fund_balance_8000(api):
    """PRD §3.6: "Finally, the refund writes two `FundLedgerEntry` rows of
    `entry_type` `REVERSAL`, one against the `CAPITAL` fund and one against the
    `OPERATING` fund, equal and opposite to the original allocation entries."

    Design: Difficulty/compensating_invariant/refund_conserves_total_fund_balance
    """
    # ERU 2.0 -> assessed 8000; capital 2400 / operating 5600; refund reverses both.
    base = setup_paid_bill(api, measured_sqft=6000, amount_cents=8000,
                           creator_user_id="clerk-a")
    pay_id = base["payment"]["id"]
    validate_success(api.refund_payment(pay_id, make_billing_clerk_headers("clerk-b")))
    entries = validate_success(
        api.list_fund_ledger(BILLING_CLERK, params={"source_payment_id": pay_id}))
    alloc_cap = find_ledger_entry(entries, "CAPITAL", "ALLOCATION")["amount_cents"]
    alloc_op = find_ledger_entry(entries, "OPERATING", "ALLOCATION")["amount_cents"]
    rev_cap = find_ledger_entry(entries, "CAPITAL", "REVERSAL")["amount_cents"]
    rev_op = find_ledger_entry(entries, "OPERATING", "REVERSAL")["amount_cents"]
    assert alloc_cap == 2400 and alloc_op == 5600
    assert rev_cap == 2400 and rev_op == 5600


def test_refund_conserves_account_receivable_full(api):
    """PRD §3.6: "Refunding moves the payment from `APPLIED` to `REFUNDED`,
    subtracts the applied amount back out of the bill's `amount_paid_cents`, and
    recomputes the bill's status — a bill that had reached `PAID` or
    `PARTIALLY_PAID` falls back toward `ISSUED` as its paid total drops. The
    charged account's `outstanding_balance_cents` and `delinquency_status` are
    recomputed."

    Design: Difficulty/compensating_invariant/refund_conserves_account_receivable
    """
    base = setup_paid_bill(api, measured_sqft=18000, amount_cents=21500,
                           creator_user_id="clerk-a")
    acct = validate_success(api.get_account(base["account"]["id"], BILLING_CLERK))
    assert acct["outstanding_balance_cents"] == 0
    assert base["bill"]["status"] == "PAID"
    payment = validate_success(
        api.refund_payment(base["payment"]["id"], make_billing_clerk_headers("clerk-b")))
    assert payment["status"] == "REFUNDED"
    bill = validate_success(api.get_bill(base["bill"]["id"], BILLING_CLERK))
    assert bill["amount_paid_cents"] == 0
    assert bill["status"] == "ISSUED"
    acct = validate_success(api.get_account(base["account"]["id"], BILLING_CLERK))
    assert acct["outstanding_balance_cents"] == 21500


def test_refund_conserves_account_receivable_partial(api):
    """PRD §3.6: "Refunding moves the payment from `APPLIED` to `REFUNDED`,
    subtracts the applied amount back out of the bill's `amount_paid_cents`, and
    recomputes the bill's status — a bill that had reached `PAID` or
    `PARTIALLY_PAID` falls back toward `ISSUED` as its paid total drops."

    Design: Difficulty/compensating_invariant/refund_conserves_account_receivable
    """
    # Partial payment path: pay 10000 of an 21500 bill, then refund it.
    base = setup_paid_bill(api, measured_sqft=18000, amount_cents=10000,
                           creator_user_id="clerk-a")
    assert base["bill"]["status"] == "PARTIALLY_PAID"
    validate_success(
        api.refund_payment(base["payment"]["id"], make_billing_clerk_headers("clerk-b")))
    bill = validate_success(api.get_bill(base["bill"]["id"], BILLING_CLERK))
    assert bill["amount_paid_cents"] == 0
    assert bill["status"] == "ISSUED"
    acct = validate_success(api.get_account(base["account"]["id"], BILLING_CLERK))
    assert acct["outstanding_balance_cents"] == 21500


def test_overpayment_on_payable_bill_rejected(api):
    """PRD §3.6: "the `amount_cents` may not exceed the bill's current
    outstanding, defined as `net_fee_cents` minus `amount_paid_cents`, and an
    amount that exceeds it is rejected with `ERR_OVERPAYMENT`."

    Design: Corner/validations/overpayment_on_payable_bill_rejected
    """
    base = setup_issued_bill(api, measured_sqft=18000, land_use="COMMERCIAL")
    resp = api.create_payment(
        create_payment_payload(base["bill"]["id"], base["account"]["id"], 30000),
        BILLING_CLERK)
    validate_error(resp, ApiErrorId.ERR_OVERPAYMENT.value)


def test_segregation_of_duties_refund_by_creator_rejected(api):
    """PRD §3.6: "Segregation of duties is strict: the principal refunding a
    payment must not be the one who created it, so a refund whose `X-User-ID`
    equals the payment's `created_by_user_id` is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/cross_cutting_complexity_layers/segregation_of_duties_refund_by_creator_rejected
    """
    base = setup_paid_bill(api, measured_sqft=18000, amount_cents=21500,
                           creator_user_id="clerk-a")
    resp = api.refund_payment(base["payment"]["id"], make_billing_clerk_headers("clerk-a"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    payment = validate_success(api.get_payment(base["payment"]["id"], BILLING_CLERK))
    assert payment["status"] == "APPLIED"


def test_delinquency_grace_day_boundary_inclusive(api):
    """PRD §3.8: "The grace period is 30 days: a bill is past the boundary when
    the logical clock has reached its `due_date` plus 30 days, and the boundary
    is inclusive — the clock reading exactly the due date plus 30 days is already
    past due."
    PRD §3.8: "The delinquency penalty is 10 percent of the unpaid principal,
    where the unpaid principal is the bill's `assessed_fee_cents` minus its
    `amount_paid_cents`: the penalty is that product rounded to whole cents,
    written to `penalty_cents`, and the bill's `net_fee_cents` becomes the
    assessed fee plus the penalty."

    Design: Difficulty/boundary_precision_check/delinquency_grace_day_boundary_inclusive
    """
    base = setup_issued_bill(api, measured_sqft=18000, land_use="COMMERCIAL",
                             due_date="2026-04-01T00:00:00Z")
    validate_success(api.set_clock("2026-05-01T00:00:00Z", BILLING_CLERK))
    validate_success(api.run_billing_cycle(BILLING_CLERK))
    bill = validate_success(api.get_bill(base["bill"]["id"], BILLING_CLERK))
    assert bill["status"] == "DELINQUENT"
    assert bill["penalty_cents"] == 2150
    assert bill["net_fee_cents"] == 23650


def test_delinquency_one_day_before_boundary_not_delinquent(api):
    """PRD §3.8: "The grace period is 30 days: a bill is past the boundary when
    the logical clock has reached its `due_date` plus 30 days, and the boundary
    is inclusive — the clock reading exactly the due date plus 30 days is already
    past due."

    Design: Difficulty/boundary_precision_check/delinquency_grace_day_boundary_inclusive
    """
    # Clock at due_date + 29 days (2026-04-30) is BEFORE the inclusive boundary.
    base = setup_issued_bill(api, measured_sqft=18000, land_use="COMMERCIAL",
                             due_date="2026-04-01T00:00:00Z")
    validate_success(api.set_clock("2026-04-30T00:00:00Z", BILLING_CLERK))
    result = validate_success(api.run_billing_cycle(BILLING_CLERK))
    assert result["bills_marked_delinquent"] == 0
    bill = validate_success(api.get_bill(base["bill"]["id"], BILLING_CLERK))
    assert bill["status"] == "ISSUED"
    assert bill["penalty_cents"] == 0
