"""Loan servicing: scheduled payments, the CURRENT<->DELINQUENT cure cycle,
the actuarial balance recomputation, and late-fee assessment on cure.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_active_rate_card, create_customer, create_vehicle,
    create_loan_payload, record_payment_payload,
    setup_loan, setup_delinquent_loan,
    TEST_USERS, make_borrower_headers,
    assert_payment,
)

FM = TEST_USERS["finance_manager_headers"]


def test_scheduled_payment_increments_count_and_reduces_balance(api):
    """PRD §3.3: "When a scheduled payment posts against a `CURRENT` loan, the system writes a
    `Payment` whose `status` is `POSTED`, whose `kind` is `SCHEDULED`, and whose `late_fee_cents`
    is 0; it then increments `payments_made_count` by one and recomputes `principal_balance_cents`
    on the actuarial schedule."

    Design: Corner/state_machines/payment_increments_count_and_reduces_balance
    """
    customer, vehicle, loan = setup_loan(fico_score=760)
    borrower = make_borrower_headers(customer["id"])
    validate_success(api.record_payment(
        loan["id"], record_payment_payload(46030, "SCHEDULED"), borrower), 201)
    loan_after = validate_success(api.get_loan(loan["id"], borrower), 200)
    assert loan_after["payments_made_count"] == 1
    assert loan_after["principal_balance_cents"] == 2462283


def test_scheduled_payment_writes_posted_payment(api):
    """PRD §3.3: "When a scheduled payment posts against a `CURRENT` loan, the system writes a
    `Payment` whose `status` is `POSTED`, whose `kind` is `SCHEDULED`, and whose `late_fee_cents`
    is 0; it then increments `payments_made_count` by one and recomputes `principal_balance_cents`
    on the actuarial schedule."

    Design: Corner/state_machines/payment_increments_count_and_reduces_balance
    """
    customer, vehicle, loan = setup_loan(fico_score=760)
    borrower = make_borrower_headers(customer["id"])
    payment = validate_success(api.record_payment(
        loan["id"], record_payment_payload(46030, "SCHEDULED"), borrower), 201)
    assert_payment(payment)
    assert payment["status"] == "POSTED"
    assert payment["kind"] == "SCHEDULED"
    assert payment["late_fee_cents"] == 0


def test_cure_returns_loan_to_current_and_resets_missed_count(api):
    """PRD §3.3: "When the same kind of scheduled payment posts against a `DELINQUENT` loan, it
    acts as a **cure**: the loan returns to `CURRENT`, `missed_payment_count` is reset to 0,
    `payments_made_count` increments by one, and `principal_balance_cents` is recomputed."

    Design: Difficulty/non_linear_state_machine/loan_current_delinquent_cure_cycle
    """
    customer, vehicle, loan = setup_delinquent_loan(num_missed=1, fico_score=760)
    borrower = make_borrower_headers(customer["id"])
    validate_success(api.record_payment(
        loan["id"], record_payment_payload(46030, "SCHEDULED"), borrower), 201)
    loan_after = validate_success(api.get_loan(loan["id"], borrower), 200)
    assert loan_after["status"] == "CURRENT"
    assert loan_after["missed_payment_count"] == 0


def test_cure_assesses_floor_late_fee(api):
    """PRD §3.3: "The late fee is the larger of a fixed floor of 2500 cents and five percent of
    the monthly payment rounded half-up to whole cents (that is, the loan's `monthly_payment_cents`
    multiplied by 0.05, rounded half-up)."

    Design: Difficulty/non_linear_state_machine/loan_current_delinquent_cure_cycle
    """
    # TIER_1 monthly 46030: 5% = 2301.5 -> 2302 < floor 2500, so floor applies.
    customer, vehicle, loan = setup_delinquent_loan(num_missed=1, fico_score=760)
    borrower = make_borrower_headers(customer["id"])
    payment = validate_success(api.record_payment(
        loan["id"], record_payment_payload(46030, "SCHEDULED"), borrower), 201)
    assert payment["late_fee_cents"] == 2500


def test_cure_late_fee_percentage_exceeds_floor(api):
    """PRD §3.3: "The late fee is the larger of a fixed floor of 2500 cents and five percent of
    the monthly payment rounded half-up to whole cents (that is, the loan's `monthly_payment_cents`
    multiplied by 0.05, rounded half-up)."

    Design: Corner/calculations/late_fee_percentage_exceeds_floor
    """
    # TIER_3 monthly 56034: 5% = 2801.7 -> 2802 > floor 2500, so percentage applies.
    customer, vehicle, loan = setup_delinquent_loan(
        num_missed=1, fico_score=650,
        loan_overrides={"down_payment_cents": 300_000})
    assert loan["monthly_payment_cents"] == 56034
    borrower = make_borrower_headers(customer["id"])
    payment = validate_success(api.record_payment(
        loan["id"], record_payment_payload(56034, "SCHEDULED"), borrower), 201)
    assert payment["late_fee_cents"] == 2802


def test_miss_payment_moves_current_to_delinquent(api):
    """PRD §3.3: "From `CURRENT` this moves the loan to `DELINQUENT`; from `DELINQUENT` it leaves
    the loan `DELINQUENT`. Either way the system writes a `Payment` whose `status` is `MISSED`,
    whose `kind` is `SCHEDULED`, and whose `late_fee_cents` is 0, and increments
    `missed_payment_count` by one."

    Design: Difficulty/non_linear_state_machine/loan_current_delinquent_cure_cycle
    """
    customer, vehicle, loan = setup_loan(fico_score=760)
    payment = validate_success(api.miss_payment(loan["id"], FM), 201)
    assert payment["status"] == "MISSED"
    assert payment["kind"] == "SCHEDULED"
    loan_after = validate_success(api.get_loan(loan["id"], FM), 200)
    assert loan_after["status"] == "DELINQUENT"
    assert loan_after["missed_payment_count"] == 1


def test_payment_immutable_no_version_field(api):
    """PRD §2.4: "A payment is an append-only event record rather than a mutable resource, so it
    carries only `id` and `created_at`; it has no `updated_at` and no `version`, and the API
    never modifies a payment after it is written."

    Design: Corner/entities/payment_immutable_no_version_field
    """
    customer, vehicle, loan = setup_loan(fico_score=760)
    borrower = make_borrower_headers(customer["id"])
    payment = validate_success(api.record_payment(
        loan["id"], record_payment_payload(46030, "SCHEDULED"), borrower), 201)
    assert "id" in payment and "created_at" in payment
    assert "version" not in payment
    assert "updated_at" not in payment


def test_scheduled_payment_wrong_amount_returns_mismatch(api):
    """PRD §3.3: "The submitted `amount_cents` must equal the loan's `monthly_payment_cents`
    exactly, or the payment is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH`."

    Design: Corner/validations/scheduled_payment_wrong_amount_returns_mismatch
    """
    customer, vehicle, loan = setup_loan(fico_score=760)
    borrower = make_borrower_headers(customer["id"])
    res = api.record_payment(loan["id"], record_payment_payload(40000, "SCHEDULED"), borrower)
    validate_error(res, "ERR_PAYMENT_AMOUNT_MISMATCH")
