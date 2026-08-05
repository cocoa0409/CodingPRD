"""Recovery transactions: interest accrual, waterfall allocation, void conservation,
precedence, and posting guards."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    setup_overpayment_in_recovery,
    setup_demanded_overpayment,
    advance_clock,
    create_transaction_payload,
    void_transaction_payload,
    assert_recovery_transaction,
)

RECOVERY = TEST_USERS["recovery_officer_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]


# --------------------------------------------------------------------------- #
# Interest accrual — round per month then sum
# --------------------------------------------------------------------------- #
def test_interest_three_full_months(api):
    """PRD 3.4: "the per-month interest charge is `final_amount_cents` multiplied by the
    monthly rate of 0.01 (one percent), rounded half up to whole cents; and
    `accrued_interest_cents` is that per-month charge summed over the N months. The rounding
    order is fixed — round each month to whole cents, then sum — and this deliberately
    differs from multiplying the unrounded product by N."

    Design: Difficulty/combinatorial_formula/interest_accrual_rounding_order_mode_b
    """
    ctx = setup_demanded_overpayment(api, claim_type="IHE")  # final 45050, demanded 2026-05-01
    advance_clock(api, "2026-08-01T00:00:00Z")  # 3 full months
    op = validate_success(api.get_overpayment(ctx["overpayment"]["id"], RECOVERY))
    # round_half_up(45050*0.01)=451 per month * 3 = 1353 (not the 1352 of sum-then-round).
    assert op["accrued_interest_cents"] == 1353, (
        f"expected 1353, got {op['accrued_interest_cents']}"
    )
    assert op["status"] == "DEMANDED", f"expected DEMANDED, got {op['status']}"


def test_interest_ignores_partial_final_month(api):
    """PRD 3.4: "let N be the number of full elapsed months between `demand_date` and the
    current logical clock, counting only whole monthly anniversaries and ignoring any
    partial final month; the per-month interest charge is `final_amount_cents` multiplied
    by the monthly rate of 0.01 (one percent), rounded half up to whole cents; and
    `accrued_interest_cents` is that per-month charge summed over the N months."

    Design: Difficulty/combinatorial_formula/interest_accrual_rounding_order_mode_b
    """
    ctx = setup_demanded_overpayment(api, claim_type="IHE")  # demanded 2026-05-01
    advance_clock(api, "2026-07-15T00:00:00Z")  # 2 full anniversaries (06-01, 07-01), partial ignored
    op = validate_success(api.get_overpayment(ctx["overpayment"]["id"], RECOVERY))
    assert op["accrued_interest_cents"] == 902, (
        f"expected 902 (2*451), got {op['accrued_interest_cents']}"
    )


# --------------------------------------------------------------------------- #
# Waterfall allocation (interest first)
# --------------------------------------------------------------------------- #
def test_payment_allocation_interest_first(api):
    """PRD 3.7: "`applied_to_interest_cents` is the smaller of `amount_cents` and the
    overpayment's `outstanding_interest_cents` at the moment of posting, and
    `applied_to_principal_cents` is whatever of `amount_cents` remains after interest —
    that is, `amount_cents` minus `applied_to_interest_cents`."

    Design: Corner/calculations/payment_allocation_interest_first
    """
    ctx = setup_overpayment_in_recovery(api, claim_type="IHE")
    advance_clock(api, "2026-08-01T00:00:00Z")  # interest 1353
    txn = validate_success(
        api.create_transaction(
            create_transaction_payload(ctx["recovery_plan"]["id"], 5000,
                                       transaction_date="2026-08-01", method="PAYMENT"),
            RECOVERY,
        ),
        expected_status=201,
    )
    assert_recovery_transaction(txn)
    assert txn["applied_to_interest_cents"] == 1353, (
        f"expected 1353 to interest, got {txn['applied_to_interest_cents']}"
    )
    assert txn["applied_to_principal_cents"] == 3647, (
        f"expected 3647 to principal, got {txn['applied_to_principal_cents']}"
    )


# --------------------------------------------------------------------------- #
# Void conservation
# --------------------------------------------------------------------------- #
def test_void_restores_outstanding_principal(api):
    """PRD 3.7: "a void is a compensating reversal that removes the transaction's
    `applied_to_principal_cents` and `applied_to_interest_cents` from the overpayment's
    ledger sums, restoring `outstanding_principal_cents` and `outstanding_interest_cents`."

    Design: Difficulty/compensating_invariant/void_restores_outstanding_principal
    """
    ctx = setup_overpayment_in_recovery(api, claim_type="IHE")  # final 45050, zero interest
    txn = validate_success(
        api.create_transaction(
            create_transaction_payload(ctx["recovery_plan"]["id"], 5000,
                                       transaction_date="2026-05-01", method="PAYMENT"),
            RECOVERY,
        ),
        expected_status=201,
    )
    voided = validate_success(api.void_transaction(txn["id"], void_transaction_payload(), RECOVERY))
    assert voided["status"] == "VOIDED", f"expected VOIDED, got {voided['status']}"
    op = validate_success(api.get_overpayment(ctx["overpayment"]["id"], SUPERVISOR))
    assert op["outstanding_principal_cents"] == 45050, (
        f"expected principal restored to 45050, got {op['outstanding_principal_cents']}"
    )
    assert op["status"] == "IN_RECOVERY", f"expected IN_RECOVERY, got {op['status']}"


def test_void_restores_outstanding_interest(api):
    """PRD 3.7: "a void is a compensating reversal that removes the transaction's
    `applied_to_principal_cents` and `applied_to_interest_cents` from the overpayment's
    ledger sums, restoring `outstanding_principal_cents` and `outstanding_interest_cents`."

    Design: Difficulty/compensating_invariant/void_restores_outstanding_principal
    """
    ctx = setup_overpayment_in_recovery(api, claim_type="IHE")
    advance_clock(api, "2026-08-01T00:00:00Z")  # interest 1353
    txn = validate_success(
        api.create_transaction(
            create_transaction_payload(ctx["recovery_plan"]["id"], 5000,
                                       transaction_date="2026-08-01", method="PAYMENT"),
            RECOVERY,
        ),
        expected_status=201,
    )
    validate_success(api.void_transaction(txn["id"], void_transaction_payload(), RECOVERY))
    op = validate_success(api.get_overpayment(ctx["overpayment"]["id"], SUPERVISOR))
    assert op["outstanding_interest_cents"] == 1353, (
        f"expected interest restored to 1353, got {op['outstanding_interest_cents']}"
    )
    assert op["outstanding_principal_cents"] == 45050, (
        f"expected principal restored to 45050, got {op['outstanding_principal_cents']}"
    )


# --------------------------------------------------------------------------- #
# Precedence: temporal beats fiscal
# --------------------------------------------------------------------------- #
def test_before_start_beats_amount_exceeds(api):
    """PRD 2.9: "In short: authentication before authorization before existence before
    shape before enum/format before pagination before state before cross-entity
    preconditions before segregation of duties before domain constraints before temporal
    before fiscal before concurrency."
    PRD 3.7: "The `transaction_date` must be on or after the plan's `start_date`; an
    earlier date is rejected with `ERR_TRANSACTION_BEFORE_PLAN_START` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fiscal_on_transaction
    """
    ctx = setup_overpayment_in_recovery(
        api, claim_type="IHE",
        plan_overrides={"start_date": "2026-06-01", "end_date": "2027-06-01"},
    )
    # Date before start (temporal) AND amount 999999 > 45050 balance (fiscal).
    resp = api.create_transaction(
        create_transaction_payload(ctx["recovery_plan"]["id"], 999999,
                                   transaction_date="2026-05-15", method="PAYMENT"),
        RECOVERY,
    )
    validate_error(resp, ApiErrorId.ERR_TRANSACTION_BEFORE_PLAN_START.value)


def test_amount_exceeds_fires_when_date_valid(api):
    """PRD 2.9: "In short: authentication before authorization before existence before
    shape before enum/format before pagination before state before cross-entity
    preconditions before segregation of duties before domain constraints before temporal
    before fiscal before concurrency."
    PRD 3.7: "The `amount_cents` may not exceed the overpayment's total outstanding balance
    (outstanding interest plus outstanding principal); an amount that exceeds it is rejected
    with `ERR_AMOUNT_EXCEEDS_BALANCE` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fiscal_on_transaction
    """
    ctx = setup_overpayment_in_recovery(
        api, claim_type="IHE",
        plan_overrides={"start_date": "2026-06-01", "end_date": "2027-06-01"},
    )
    # Temporal check passes (date after start); only the fiscal cap now fails.
    resp = api.create_transaction(
        create_transaction_payload(ctx["recovery_plan"]["id"], 999999,
                                   transaction_date="2026-06-02", method="PAYMENT"),
        RECOVERY,
    )
    validate_error(resp, ApiErrorId.ERR_AMOUNT_EXCEEDS_BALANCE.value)


# --------------------------------------------------------------------------- #
# Corner: amount-exceeds and double-void guards
# --------------------------------------------------------------------------- #
def test_amount_exceeds_balance_rejected(api):
    """PRD 3.7: "The `amount_cents` may not exceed the overpayment's total outstanding
    balance (outstanding interest plus outstanding principal); an amount that exceeds it is
    rejected with `ERR_AMOUNT_EXCEEDS_BALANCE` (HTTP 422)."

    Design: Corner/validations/amount_exceeds_balance
    """
    ctx = setup_overpayment_in_recovery(api, claim_type="IHE")  # balance 45050, zero interest
    resp = api.create_transaction(
        create_transaction_payload(ctx["recovery_plan"]["id"], 60000,
                                   transaction_date="2026-05-02", method="PAYMENT"),
        RECOVERY,
    )
    validate_error(resp, ApiErrorId.ERR_AMOUNT_EXCEEDS_BALANCE.value)


def test_double_void_rejected(api):
    """PRD 3.7: "Voiding a transaction that is already `VOIDED` is rejected with
    `ERR_ALREADY_VOIDED` (HTTP 409)."

    Design: Corner/validations/already_voided_transaction
    """
    ctx = setup_overpayment_in_recovery(api, claim_type="IHE")
    txn = validate_success(
        api.create_transaction(
            create_transaction_payload(ctx["recovery_plan"]["id"], 5000,
                                       transaction_date="2026-05-01", method="PAYMENT"),
            RECOVERY,
        ),
        expected_status=201,
    )
    validate_success(api.void_transaction(txn["id"], void_transaction_payload(), RECOVERY))
    resp = api.void_transaction(txn["id"], void_transaction_payload(), RECOVERY)
    validate_error(resp, ApiErrorId.ERR_ALREADY_VOIDED.value)
