"""Payment waterfall allocation, over-payment rejection, reversal, and the
independent payment/collection axes on a bill."""
from test_helpers import (
    validate_success, validate_error,
    TEST_USERS,
    setup_account_with_two_bills, setup_account_with_water_bill,
    setup_paid_bill, setup_delinquent_account, make_payment,
)

BS = TEST_USERS["billing_specialist_headers"]


# ---------------------------------------------------------------------------
# calculations / payment_waterfall_allocates_oldest_bill_first (corner)
# ---------------------------------------------------------------------------
def test_payment_waterfall_pays_oldest_bill_first(api):
    """PRD §3.5: "The candidate bills are the account's bills whose `payment_status` is
    `UNPAID` or `PARTIAL` and whose `collection_status` is not `IN_LIEN`, ordered by
    `period_end` ascending and breaking ties by `created_at` ascending — never by `id`."
    PRD §3.5: "the amount taken is the smaller of the remaining payment and that bill's
    outstanding balance".

    Design: Corner/calculations/payment_waterfall_allocates_oldest_bill_first
    """
    ctx = setup_account_with_two_bills(api)  # Jan 2890, Feb 4640
    make_payment(api, ctx["account"]["id"], 5000, "ACH")
    jan = validate_success(api.get_bill(ctx["bill1"]["id"], BS))
    feb = validate_success(api.get_bill(ctx["bill2"]["id"], BS))
    assert jan["payment_status"] == "PAID"
    assert jan["amount_paid_cents"] == 2890
    assert feb["payment_status"] == "PARTIAL"
    assert feb["amount_paid_cents"] == 2110


# ---------------------------------------------------------------------------
# validations / payment_exceeds_balance_returns_422 (corner)
# ---------------------------------------------------------------------------
def test_payment_exceeding_open_balance_rejected(api):
    """PRD §3.5: "If any amount remains after every candidate has been filled, the whole
    payment is rejected with `ERR_PAYMENT_EXCEEDS_BALANCE`."

    Design: Corner/validations/payment_exceeds_balance_returns_422
    """
    ctx = setup_account_with_water_bill(api, reading_value=9500)  # single bill 4640
    resp = api.create_payment(ctx["account"]["id"], {"amount_cents": 10000, "method": "CASH"}, BS)
    validate_error(resp, "ERR_PAYMENT_EXCEEDS_BALANCE")


# ---------------------------------------------------------------------------
# compensating_invariant / payment_reversal_restores_account_receivable
# ---------------------------------------------------------------------------
def test_reversal_restores_account_receivable(api):
    """PRD §3.5: "Reversal moves the payment `POSTED → REVERSED`, and each allocation it
    made is unwound: the reversed `applied_cents` is subtracted from each affected bill's
    `amount_paid_cents`, that bill's `payment_status` is recomputed, and the account's
    receivable is restored to its pre-payment value."

    Design: Difficulty/compensating_invariant/payment_reversal_restores_account_receivable
    """
    ctx = setup_paid_bill(api, reading_value=9500, amount_cents=4640)
    before = validate_success(api.get_account(ctx["account"]["id"], BS))
    paid_bill = validate_success(api.get_bill(ctx["bill"]["id"], BS))
    assert paid_bill["payment_status"] == "PAID"
    assert before["current_balance_cents"] == 0

    reversed_payment = validate_success(api.reverse_payment(ctx["payment"]["id"], BS))
    assert reversed_payment["status"] == "REVERSED"
    after = validate_success(api.get_account(ctx["account"]["id"], BS))
    assert after["current_balance_cents"] == 4640


def test_reversal_unwinds_bill_amount_paid_to_zero(api):
    """PRD §3.5: "each allocation it made is unwound: the reversed `applied_cents` is
    subtracted from each affected bill's `amount_paid_cents`".

    Design: Difficulty/compensating_invariant/payment_reversal_restores_account_receivable
    """
    ctx = setup_paid_bill(api, reading_value=9500, amount_cents=4640)
    validate_success(api.reverse_payment(ctx["payment"]["id"], BS))
    bill = validate_success(api.get_bill(ctx["bill"]["id"], BS))
    assert bill["amount_paid_cents"] == 0


# ---------------------------------------------------------------------------
# state_machines / reverse_already_reversed_payment_returns_invalid_state (corner)
# ---------------------------------------------------------------------------
def test_reversing_already_reversed_payment_rejected(api):
    """PRD §3.5: "Only a payment currently in `POSTED` status may be reversed."
    PRD §2.11: "a transition attempted from an invalid current state yields
    `ERR_INVALID_STATE` (409)".

    Design: Corner/state_machines/reverse_already_reversed_payment_returns_invalid_state
    """
    ctx = setup_paid_bill(api, reading_value=9500, amount_cents=4640)
    validate_success(api.reverse_payment(ctx["payment"]["id"], BS))
    validate_error(api.reverse_payment(ctx["payment"]["id"], BS), "ERR_INVALID_STATE")


# ---------------------------------------------------------------------------
# non_linear_state_machine / bill_parallel_payment_and_collection_axes
# ---------------------------------------------------------------------------
def test_partial_payment_advances_payment_status_only(api):
    """PRD §3.5: "a bill goes `UNPAID → PARTIAL` when it receives a positive amount short of
    its full balance".

    Design: Difficulty/non_linear_state_machine/bill_parallel_payment_and_collection_axes
    """
    ctx = setup_delinquent_account(api, reading_value=9500, clock_at="2026-06-11T00:00:00Z")
    make_payment(api, ctx["account"]["id"], 2000, "CASH")
    bill = validate_success(api.get_bill(ctx["bill"]["id"], BS))
    assert bill["payment_status"] == "PARTIAL"
    assert bill["amount_paid_cents"] == 2000


def test_partial_payment_leaves_collection_status_delinquent(api):
    """PRD §3.6: "the payment axis (`UNPAID`, `PARTIAL`, `PAID`) and the collections axis
    (`CURRENT`, `DELINQUENT`, `IN_LIEN`) evolve on separate tracks."

    Design: Difficulty/non_linear_state_machine/bill_parallel_payment_and_collection_axes
    """
    ctx = setup_delinquent_account(api, reading_value=9500, clock_at="2026-06-11T00:00:00Z")
    make_payment(api, ctx["account"]["id"], 2000, "CASH")
    bill = validate_success(api.get_bill(ctx["bill"]["id"], BS))
    assert bill["collection_status"] == "DELINQUENT", "partial payment must not clear delinquency"
    assert bill["payment_status"] == "PARTIAL"
