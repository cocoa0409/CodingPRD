"""Refunds and reversals: ledger/cash conservation, four-eyes SoD, overpayment, OCC."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    assert_ledger_balance_conservation,
    setup_year_parcel_bill, setup_overpaid_bill,
    post_payment, reverse_payment, file_refund, decide_refund,
    bill_version, get_bill, ledger_entries, installment_seq,
    create_refund_payload, decide_payload,
    make_treasurer_headers,
    TEST_USERS,
)

CASHIER = TEST_USERS["cashier_headers"]


# ---- Difficulty: ledger_balance_conservation_on_reverse (test 1 of 2) ----
def test_reverse_restores_bill_balance_with_zero_drift(api):
    """PRD 3.6: "for each `PAYMENT` ledger entry the payment produced, the system posts an
    equal and opposite `REVERSAL` ledger entry, so the reversed cash is
    restored to the bill's balance."
    PRD 2.11: "a bill's `balance_cents` is exactly the sum of every one of its
    `LedgerEntry` amounts, with none excluded."

    Design: Difficulty/compensating_invariant/ledger_balance_conservation_on_reverse
    """
    ty, parcel, bill = setup_year_parcel_bill(api, assessed_value_cents=20000000)
    pay = post_payment(api, bill["id"], 200000)
    reverse_payment(api, pay["id"], user_id="tr-1")
    refreshed = get_bill(api, bill["id"])
    assert refreshed["balance_cents"] == 400000
    assert_ledger_balance_conservation(refreshed, ledger_entries(api, bill["id"]))


# ---- Difficulty: ledger_balance_conservation_on_reverse (test 2 of 2) ----
def test_reverse_marks_payment_reversed_and_reopens_installment(api):
    """PRD 3.6: "The reversal increments the bill's `version` by one, records
    `reversed_by_user_id`, and moves the payment to `REVERSED`."
    PRD 3.6: "a `PAID` installment whose balance reopens returns to `PENDING` when the
    current clock date is on or before its `due_date`"

    Design: Difficulty/compensating_invariant/ledger_balance_conservation_on_reverse
    """
    ty, parcel, bill = setup_year_parcel_bill(api, assessed_value_cents=20000000)
    pay = post_payment(api, bill["id"], 200000)
    reversed_pay = reverse_payment(api, pay["id"], user_id="tr-1")
    assert reversed_pay["status"] == "REVERSED"
    assert installment_seq(api, bill["id"], 1)["status"] == "PENDING"


# ---- Difficulty: cash_conservation_on_refund (test 1 of 2) ----
def test_refund_approved_amount_and_overpayment_cleared(api):
    """PRD 3.7: "The `approved_amount_cents` is the lesser of the requested `amount_cents`
    and that available amount, and it may not exceed the bill's available
    overpayment"
    PRD 3.2: "`overpayment_cents`, the greater of zero and the negative of
    `balance_cents`"

    Design: Difficulty/compensating_invariant/cash_conservation_on_refund
    """
    ty, parcel, bill = setup_overpaid_bill(api, assessed_value_cents=20000000, payment_cents=500000)
    refund = file_refund(api, bill["id"], 100000, requester_user_id="tr-1")
    decided = decide_refund(api, refund["id"], "APPROVE", decider_user_id="tr-2")
    assert decided["approved_amount_cents"] == 100000
    assert get_bill(api, bill["id"])["overpayment_cents"] == 0


# ---- Difficulty: cash_conservation_on_refund (test 2 of 2) ----
def test_refund_preserves_cash_conservation(api):
    """PRD 2.11: "the cash the county actually retains on a bill, exposed as
    `total_applied_cents`, equals `total_paid_cents` minus the sum of
    `approved_amount_cents` across that bill's `APPROVED` refunds."

    Design: Difficulty/compensating_invariant/cash_conservation_on_refund
    """
    ty, parcel, bill = setup_overpaid_bill(api, assessed_value_cents=20000000, payment_cents=500000)
    refund = file_refund(api, bill["id"], 100000, requester_user_id="tr-1")
    decide_refund(api, refund["id"], "APPROVE", decider_user_id="tr-2")
    refreshed = get_bill(api, bill["id"])
    assert refreshed["total_applied_cents"] == 400000
    assert refreshed["balance_cents"] == 0


# ---- Difficulty: sod_beats_refund_already_decided (test 1 of 2) ----
def test_requester_redeciding_own_refund_hits_sod(api):
    """PRD 3.7: "the acting `X-User-ID` must differ from `requested_by_user_id`, and a
    match is rejected with `ERR_SEGREGATION_OF_DUTIES` before any other
    decision check."

    Design: Difficulty/priority_pair_validation_conflict/sod_beats_refund_already_decided
    """
    ty, parcel, bill = setup_overpaid_bill(api, assessed_value_cents=20000000, payment_cents=500000)
    refund = file_refund(api, bill["id"], 100000, requester_user_id="tr-1")
    decide_refund(api, refund["id"], "APPROVE", decider_user_id="tr-2")
    resp = api.decide_refund(refund["id"], decide_payload("APPROVE"), make_treasurer_headers("tr-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


# ---- Difficulty: sod_beats_refund_already_decided (test 2 of 2) ----
def test_sod_precedes_already_decided_check(api):
    """PRD 2.9: "A violation of either equality is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (403), and this check precedes the
    operation's own business checks (overpayment availability for a
    refund, redemption expiry for a sale)."

    Design: Difficulty/priority_pair_validation_conflict/sod_beats_refund_already_decided
    """
    # tr-1 (the original requester) re-decides an already-APPROVED refund: BOTH SoD and
    # already-decided apply; SoD must win.
    ty, parcel, bill = setup_overpaid_bill(api, assessed_value_cents=20000000, payment_cents=500000)
    refund = file_refund(api, bill["id"], 100000, requester_user_id="tr-1")
    decide_refund(api, refund["id"], "APPROVE", decider_user_id="tr-2")
    resp = api.decide_refund(refund["id"], decide_payload("APPROVE"), make_treasurer_headers("tr-1"))
    err = validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    assert err["error_id"] != "ERR_REFUND_ALREADY_DECIDED"


# ---- Corner: validations/refund_exceeds_available_overpayment_rejected ----
def test_refund_exceeds_available_overpayment_rejected(api):
    """PRD 3.7: "it may not exceed the bill's available overpayment — an approval that
    would exceed it is rejected with `ERR_OVERPAYMENT_UNAVAILABLE`."

    Design: Corner/validations/refund_exceeds_available_overpayment_rejected
    """
    ty, parcel, bill = setup_overpaid_bill(api, assessed_value_cents=20000000, payment_cents=450000)
    refund = file_refund(api, bill["id"], 100000, requester_user_id="tr-1")
    resp = api.decide_refund(refund["id"], decide_payload("APPROVE"), make_treasurer_headers("tr-2"))
    validate_error(resp, ApiErrorId.ERR_OVERPAYMENT_UNAVAILABLE.value)


# ---- Corner: validations/reverse_already_reversed_payment_rejected ----
def test_reverse_already_reversed_payment_rejected(api):
    """PRD 3.6: "Only a `Treasurer` may reverse a payment, and only a payment currently
    in `POSTED` status; reversing a payment that is already `REVERSED` is rejected with
    `ERR_PAYMENT_ALREADY_REVERSED`."

    Design: Corner/validations/reverse_already_reversed_payment_rejected
    """
    ty, parcel, bill = setup_year_parcel_bill(api, assessed_value_cents=20000000)
    pay = post_payment(api, bill["id"], 200000)
    reverse_payment(api, pay["id"], user_id="tr-1")
    resp = api.reverse_payment(pay["id"], make_treasurer_headers("tr-1"))
    validate_error(resp, ApiErrorId.ERR_PAYMENT_ALREADY_REVERSED.value)


# ---- Corner: cross_cutting_complexity_layers/refund_create_stale_bill_version_rejected ----
def test_refund_create_stale_bill_version_rejected(api):
    """PRD 2.7: "A create-refund request must include `expected_bill_version` equal to the
    target bill's current `version`. If another payment or reversal has
    advanced the bill's `version` since the client last read it, the
    refund is rejected with `ERR_STALE_VERSION` (HTTP 412), so the refund
    is never computed from an outdated overpayment figure."

    Design: Corner/cross_cutting_complexity_layers/refund_create_stale_bill_version_rejected
    """
    ty, parcel, bill = setup_year_parcel_bill(api, assessed_value_cents=20000000)
    post_payment(api, bill["id"], 200000)          # bill now PARTIALLY_PAID, version advanced
    stale_ver = bill_version(api, bill["id"])
    post_payment(api, bill["id"], 150000)          # a further payment advances version again
    resp = api.create_refund(create_refund_payload(bill["id"], 50000, stale_ver),
                             make_treasurer_headers("tr-1"))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
