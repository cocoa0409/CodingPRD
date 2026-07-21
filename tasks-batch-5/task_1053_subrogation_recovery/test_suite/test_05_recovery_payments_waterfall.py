"""Recovery payments and the allocation waterfall: the clear cascade to RECOVERED and
the created reimbursement, the deductible-only zero-carrier split, bucket conservation,
the reverse/claw-back that conserves the deductible pool, the settled-claim precondition,
the fiscal ceiling, and clear idempotency."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_recovery_payment_payload, assert_allocation_conserved,
    setup_demand_issued_claim, setup_settled_claim, setup_cleared_payment,
    setup_recovered_with_disbursed_reimbursement, record_payment,
)
from test_helpers import TEST_USERS

FINANCE = TEST_USERS["finance_headers"]
READER = TEST_USERS["reader_headers"]

# paid_loss 0, deductible 500k, total 1M -> waterfall deductible bucket exactly fills.
DEDUCTIBLE_ONLY_CLAIM = {"paid_loss_cents": 0, "deductible_cents": 500_000, "total_damages_cents": 1_000_000}


def test_clear_recovers_claim(api):
    """PRD §3.6: "The claim's `final_recovered_cents` is increased by the payment's
    gross `amount_cents`".
    PRD §3.6: "if the claim's `final_recovered_cents` now reaches or exceeds its
    `settled_amount_cents`, the claim is promoted from `SETTLED` to `RECOVERED`."

    Design: Difficulty/transitive_cascade/payment_clear_recovers_claim_and_creates_reimbursement
    """
    ctx = setup_cleared_payment(api, settled_amount_cents=3_000_000)
    assert ctx["payment"]["status"] == "CLEARED"
    assert ctx["claim"]["final_recovered_cents"] == 3_000_000
    assert ctx["claim"]["status"] == "RECOVERED"


def test_clear_creates_pending_deductible_reimbursement(api):
    """PRD §3.6: "if this payment's `alloc_deductible_cents` is greater than zero, the
    system creates a `DeductibleReimbursement` in `status` `PENDING` whose `amount_cents`
    equals that `alloc_deductible_cents`".

    Design: Difficulty/transitive_cascade/payment_clear_recovers_claim_and_creates_reimbursement
    """
    ctx = setup_cleared_payment(api, settled_amount_cents=3_000_000)
    data, meta = validate_paginated(
        api.list_deductible_reimbursements(READER, params={"claim_id": ctx["claim"]["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["status"] == "PENDING"
    assert data[0]["amount_cents"] == 500_000


def test_waterfall_deductible_only_fills_first_bucket(api):
    """PRD §3.6: "`alloc_deductible_cents` (bucket one) is the smaller of the payment's
    `amount_cents` and that outstanding deductible."

    Design: Difficulty/boundary_precision_check/waterfall_payment_equals_deductible_zero_carrier
    """
    ctx = setup_cleared_payment(api, settled_amount_cents=500_000, liability_pct=100,
                                claim_overrides=dict(DEDUCTIBLE_ONLY_CLAIM))
    assert ctx["payment"]["alloc_deductible_cents"] == 500_000


def test_waterfall_deductible_only_leaves_zero_commission_and_carrier(api):
    """PRD §3.6: "The remainder after the deductible bucket is `amount_cents` minus
    `alloc_deductible_cents`. From that remainder, `alloc_commission_cents` (bucket two)
    is the carrier's `commission_rate_bps` divided by 10000, multiplied by the
    remainder, rounded half up to whole cents. `alloc_carrier_cents` (bucket three) is
    the remainder minus `alloc_commission_cents`."

    Design: Difficulty/boundary_precision_check/waterfall_payment_equals_deductible_zero_carrier
    """
    ctx = setup_cleared_payment(api, settled_amount_cents=500_000, liability_pct=100,
                                claim_overrides=dict(DEDUCTIBLE_ONLY_CLAIM))
    assert ctx["payment"]["alloc_commission_cents"] == 0
    assert ctx["payment"]["alloc_carrier_cents"] == 0


def test_waterfall_split_full_amounts(api):
    """PRD §3.6: "From that remainder, `alloc_commission_cents` (bucket two) is the
    carrier's `commission_rate_bps` divided by 10000, multiplied by the remainder,
    rounded half up to whole cents. `alloc_carrier_cents` (bucket three) is the
    remainder minus `alloc_commission_cents`."

    Design: Difficulty/compensating_invariant/payment_allocation_sum_conserved
    """
    ctx = setup_cleared_payment(api, settled_amount_cents=3_000_000)  # NET 2500bps, deductible 500k
    payment = ctx["payment"]
    assert payment["alloc_deductible_cents"] == 500_000
    assert payment["alloc_commission_cents"] == 625_000
    assert payment["alloc_carrier_cents"] == 1_875_000


def test_waterfall_buckets_sum_to_gross_amount(api):
    """PRD §3.6: "By construction the three buckets sum exactly to the gross
    `amount_cents`."

    Design: Difficulty/compensating_invariant/payment_allocation_sum_conserved
    """
    ctx = setup_cleared_payment(api, settled_amount_cents=3_000_000)
    payment = ctx["payment"]
    assert_allocation_conserved(payment)
    assert (payment["alloc_deductible_cents"] + payment["alloc_commission_cents"]
            + payment["alloc_carrier_cents"]) == 3_000_000


def test_reverse_restores_deductible_pool_and_demotes_claim(api):
    """PRD §3.6: "If the claim was `RECOVERED` and, after this compensation, its
    `final_recovered_cents` falls below its `settled_amount_cents`, the claim is demoted
    from `RECOVERED` back to `SETTLED`."
    PRD §3.6: "if it had already been `DISBURSED`, the claim's
    `deductible_reimbursed_cents` is decreased by that reimbursement's `amount_cents`."

    Design: Difficulty/compensating_invariant/deductible_pool_conserved_under_reverse
    """
    ctx = setup_recovered_with_disbursed_reimbursement(api, settled_amount_cents=3_000_000)
    assert ctx["claim"]["deductible_reimbursed_cents"] == 500_000  # disbursed first
    validate_success(api.reverse_payment(ctx["payment"]["id"], FINANCE))
    claim = validate_success(api.get_claim(ctx["claim"]["id"], READER))
    assert claim["deductible_reimbursed_cents"] == 0
    assert claim["status"] == "SETTLED"


def test_reverse_claws_back_disbursed_reimbursement(api):
    """PRD §3.6: "And the `DeductibleReimbursement` funded by this payment is clawed
    back: whether it was `PENDING` or `DISBURSED`, it moves to `CLAWED_BACK`".

    Design: Difficulty/compensating_invariant/deductible_pool_conserved_under_reverse
    """
    ctx = setup_recovered_with_disbursed_reimbursement(api, settled_amount_cents=3_000_000)
    api.reverse_payment(ctx["payment"]["id"], FINANCE)
    reimb = validate_success(api.get_deductible_reimbursement(ctx["reimbursement"]["id"], READER))
    assert reimb["status"] == "CLAWED_BACK"


def test_record_payment_on_unsettled_claim_rejected(api):
    """PRD §3.6: "Money recovered from the adverse party is booked as recovery payments
    against a settled claim, and this is `FinanceOfficer` territory."
    PRD §2.11: "(7) that the target resource is in a state permitting the requested
    transition (`ERR_INVALID_STATE`)".

    Design: Difficulty/cross_entity_state_dependency/recovery_payment_requires_claim_settled
    """
    ctx = setup_demand_issued_claim(api)  # never settled
    resp = api.create_recovery_payment(ctx["claim"]["id"], create_recovery_payment_payload(100_000), FINANCE)
    validate_error(resp, "ERR_INVALID_STATE", 409)


def test_rejected_payment_not_recorded_on_unsettled_claim(api):
    """PRD §3.6: "Money recovered from the adverse party is booked as recovery payments
    against a settled claim, and this is `FinanceOfficer` territory."

    Design: Difficulty/cross_entity_state_dependency/recovery_payment_requires_claim_settled
    """
    ctx = setup_demand_issued_claim(api)
    api.create_recovery_payment(ctx["claim"]["id"], create_recovery_payment_payload(100_000), FINANCE)
    data, meta = validate_paginated(
        api.list_recovery_payments(READER, params={"claim_id": ctx["claim"]["id"]}))
    assert meta["total_count"] == 0, "a rejected recording must not persist a payment"


def test_recovery_payment_over_settlement_rejected(api):
    """PRD §3.6: "the cumulative total of already-cleared payments plus this new amount
    must not exceed the claim's `settled_amount_cents`, or the request is rejected with
    `ERR_PAYMENT_EXCEEDS_SETTLEMENT` at HTTP 422."

    Design: Corner/errors/recovery_payment_over_settlement_returns_422
    """
    ctx = setup_settled_claim(api, settled_amount_cents=1_000_000)
    resp = api.create_recovery_payment(ctx["claim"]["id"], create_recovery_payment_payload(2_000_000), FINANCE)
    validate_error(resp, "ERR_PAYMENT_EXCEEDS_SETTLEMENT", 422)


def test_clear_already_cleared_payment_rejected(api):
    """PRD §3.6: "Clearing moves the payment from `RECEIVED` to `CLEARED` and runs the
    recovery waterfall".
    PRD §2.11: "(7) that the target resource is in a state permitting the requested
    transition (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/clear_already_cleared_payment_returns_invalid_state
    """
    ctx = setup_cleared_payment(api, settled_amount_cents=3_000_000)
    resp = api.clear_payment(ctx["payment"]["id"], FINANCE)
    validate_error(resp, "ERR_INVALID_STATE", 409)
