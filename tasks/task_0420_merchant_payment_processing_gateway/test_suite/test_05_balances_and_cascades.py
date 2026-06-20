"""Refund settlement cascade into available balance and payout headroom; payout
request-then-return conservation; refund guards.

Covers difficulty queue (transitive_cascade refund-settle depth2, compensating_invariant
payout conservation, priority_pair referential-vs-fiscal refund) and corner refund/error
instances.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    set_clock,
    create_flat_plan, create_approved_merchant, create_captured_charge,
    open_and_settle_batch,
    setup_funded_merchant, create_pending_refund,
    make_merchant_user_headers,
    TEST_USERS,
)

OPERATOR = TEST_USERS["platform_operator_headers"]


def test_refund_settle_lowers_available_balance(api):
    """PRD §3.5: "Settling the refund drives its `refund_status` from `PENDING` to `SETTLED`:
    it posts a `REFUND` ledger entry against the `AVAILABLE` account for the negative of the
    refund's `amount_cents` (a debit) with `source_type` `REFUND`, then recomputes the
    merchant's `available_balance_cents`."

    Design: Difficulty/transitive_cascade/refund_settle_cascade_balance_then_payout_headroom_depth2
    """
    base = setup_funded_merchant(assigned_risk_band="LOW", auth_amount_cents=10000)
    headers = make_merchant_user_headers(base["merchant_id"])
    refund = validate_success(api.create_refund(base["charge"]["id"], {"amount_cents": 4000}, headers), expected_status=201)
    validate_success(api.settle_refund(refund["id"], {}, OPERATOR))
    merchant = validate_success(api.get_merchant(base["merchant_id"], OPERATOR))
    # 9680 - 4000 = 5680
    assert merchant["available_balance_cents"] == 5680, (
        f"expected 5680, got {merchant['available_balance_cents']}"
    )


def test_payout_over_reduced_headroom_after_refund_rejected(api):
    """PRD §3.10: "the requested amount must not exceed the merchant's
    `available_balance_cents`; a request for more than the available balance is rejected with
    `ERR_INSUFFICIENT_BALANCE` (HTTP 422)".

    Design: Difficulty/transitive_cascade/refund_settle_cascade_balance_then_payout_headroom_depth2
    """
    base = setup_funded_merchant(assigned_risk_band="LOW", auth_amount_cents=10000)
    headers = make_merchant_user_headers(base["merchant_id"])
    refund = validate_success(api.create_refund(base["charge"]["id"], {"amount_cents": 4000}, headers), expected_status=201)
    validate_success(api.settle_refund(refund["id"], {}, OPERATOR))
    # available now 5680; payout of 5681 is 1 over the headroom.
    resp = api.create_payout(base["merchant_id"], {"amount_cents": 5681, "scheduled_for": "2026-01-10"}, headers)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_BALANCE)


def test_payout_request_debits_available_balance(api):
    """PRD §3.10: "Requesting a payout debits the money immediately: it sets the payout's
    `payout_status` to `REQUESTED`, posts a `PAYOUT` ledger entry on the `AVAILABLE` account
    for the negative of the payout `amount_cents` with `source_type` `PAYOUT`, and recomputes
    the merchant's `available_balance_cents`."

    Design: Difficulty/compensating_invariant/payout_request_then_return_conserves_available_balance
    """
    base = setup_funded_merchant(assigned_risk_band="LOW", auth_amount_cents=10000)
    headers = make_merchant_user_headers(base["merchant_id"])
    validate_success(api.create_payout(base["merchant_id"], {"amount_cents": 5000, "scheduled_for": "2026-01-05"}, headers), expected_status=201)
    merchant = validate_success(api.get_merchant(base["merchant_id"], OPERATOR))
    # 9680 - 5000 = 4680
    assert merchant["available_balance_cents"] == 4680


def test_payout_return_restores_available_balance_exactly(api):
    """PRD §3.10: "Returning the payout — used when the bank rejects it — drives
    `payout_status` from `REQUESTED` to the terminal `RETURNED`; it is permitted only while the
    payout is `REQUESTED`, posts a compensating `PAYOUT_RETURN` ledger entry on the `AVAILABLE`
    account for the positive of the payout `amount_cents` with `source_type` `PAYOUT`, and
    recomputes the merchant's `available_balance_cents`, restoring the debited funds."

    Design: Difficulty/compensating_invariant/payout_request_then_return_conserves_available_balance
    """
    base = setup_funded_merchant(assigned_risk_band="LOW", auth_amount_cents=10000)
    headers = make_merchant_user_headers(base["merchant_id"])
    payout = validate_success(api.create_payout(base["merchant_id"], {"amount_cents": 5000, "scheduled_for": "2026-01-05"}, headers), expected_status=201)
    after_request = validate_success(api.get_merchant(base["merchant_id"], OPERATOR))
    assert after_request["available_balance_cents"] == 4680
    validate_success(api.return_payout(payout["id"], {}, OPERATOR))
    after_return = validate_success(api.get_merchant(base["merchant_id"], OPERATOR))
    assert after_return["available_balance_cents"] == 9680, "return must restore the balance exactly"


def test_refund_blocked_by_dispute_wins_over_exceeds_captured(api):
    """PRD §3.5: "a refund may not be created while the charge has a live dispute: if a
    `Dispute` in any non-terminal status (`OPEN`, `UNDER_REVIEW`, or `REPRESENTED`) exists on
    the charge, the refund is rejected with `ERR_REFUND_BLOCKED_BY_DISPUTE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/referential_vs_fiscal_refund_blocked_by_dispute_over_captured
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = create_flat_plan()
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="LOW")
    version = merchant["version"]
    charge = create_captured_charge(merchant["id"], auth_amount_cents=10000)
    headers = make_merchant_user_headers(merchant["id"])
    # partial refund of 3000 first (uses 3000 of headroom), then settle batch, then dispute net 7000.
    validate_success(api.create_refund(charge["id"], {"amount_cents": 3000}, headers), expected_status=201)
    open_and_settle_batch(merchant["id"], version, business_date="2026-01-01")
    validate_success(api.create_dispute(charge["id"], {"disputed_amount_cents": 7000}, headers), expected_status=201)
    # refund of 9000 both exceeds remaining headroom AND is blocked by the OPEN dispute; referential wins.
    resp = api.create_refund(charge["id"], {"amount_cents": 9000}, headers)
    validate_error(resp, ApiErrorId.ERR_REFUND_BLOCKED_BY_DISPUTE)


def test_refund_blocked_by_dispute_isolated(api):
    """PRD §3.5: "if a `Dispute` in any non-terminal status (`OPEN`, `UNDER_REVIEW`, or
    `REPRESENTED`) exists on the charge, the refund is rejected with
    `ERR_REFUND_BLOCKED_BY_DISPUTE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/referential_vs_fiscal_refund_blocked_by_dispute_over_captured
    """
    # In-headroom refund attempt while an OPEN dispute exists -> only the referential guard can fire.
    set_clock("2026-01-01T00:00:00Z")
    plan = create_flat_plan()
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="LOW")
    version = merchant["version"]
    charge = create_captured_charge(merchant["id"], auth_amount_cents=10000)
    headers = make_merchant_user_headers(merchant["id"])
    open_and_settle_batch(merchant["id"], version, business_date="2026-01-01")
    validate_success(api.create_dispute(charge["id"], {"disputed_amount_cents": 10000}, headers), expected_status=201)
    resp = api.create_refund(charge["id"], {"amount_cents": 1000}, headers)
    validate_error(resp, ApiErrorId.ERR_REFUND_BLOCKED_BY_DISPUTE)


# --- Corner: refund and error instances ---

def test_refund_in_headroom_succeeds_and_reserves_headroom(api):
    """PRD §3.5: "A successful creation produces a refund in `PENDING` status and immediately
    increments the charge's `refunded_amount_cents` by the refund amount, reserving that
    headroom."

    Design: Corner/Validations/corner_refund_satisfaction_passes
    """
    plan = create_flat_plan()
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="LOW")
    charge = create_captured_charge(merchant["id"], auth_amount_cents=10000)
    headers = make_merchant_user_headers(merchant["id"])
    refund = validate_success(api.create_refund(charge["id"], {"amount_cents": 4000}, headers), expected_status=201)
    assert refund["refund_status"] == "PENDING"
    fetched = validate_success(api.get_charge(charge["id"], headers))
    assert fetched["refunded_amount_cents"] == 4000


def test_refund_settle_action_posts_debit_and_recomputes(api):
    """PRD §3.5: "it posts a `REFUND` ledger entry against the `AVAILABLE` account for the
    negative of the refund's `amount_cents` (a debit) with `source_type` `REFUND`, then
    recomputes the merchant's `available_balance_cents`."

    Design: Corner/Endpoints/corner_refund_settle_action_posts_ledger_debit
    """
    base = setup_funded_merchant(assigned_risk_band="LOW", auth_amount_cents=10000)
    headers = make_merchant_user_headers(base["merchant_id"])
    refund = create_pending_refund(base["merchant_id"], base["charge"]["id"], 4000)
    settled = validate_success(api.settle_refund(refund["id"], {}, OPERATOR))
    assert settled["refund_status"] == "SETTLED"
    merchant = validate_success(api.get_merchant(base["merchant_id"], OPERATOR))
    assert merchant["available_balance_cents"] == 5680


def test_refund_fail_restores_headroom(api):
    """PRD §3.5: "Failing the refund instead drives its `refund_status` from `PENDING` to
    `FAILED`: it posts no ledger entry and compensates by decrementing the charge's
    `refunded_amount_cents` by the refund's `amount_cents`, which restores the refundable
    headroom that was reserved at creation."

    Design: Corner/Endpoints/corner_refund_fail_compensation_restores_headroom
    """
    plan = create_flat_plan()
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="LOW")
    charge = create_captured_charge(merchant["id"], auth_amount_cents=10000)
    headers = make_merchant_user_headers(merchant["id"])
    refund = validate_success(api.create_refund(charge["id"], {"amount_cents": 4000}, headers), expected_status=201)
    failed = validate_success(api.fail_refund(refund["id"], {}, OPERATOR))
    assert failed["refund_status"] == "FAILED"
    fetched = validate_success(api.get_charge(charge["id"], headers))
    assert fetched["refunded_amount_cents"] == 0, "fail compensation must restore headroom"


def test_refund_exceeds_captured_rejected(api):
    """PRD §3.5: "a refund that would push the cumulative refunded total above the captured
    amount is rejected with `ERR_REFUND_EXCEEDS_CAPTURED` (HTTP 422)."

    Design: Corner/Errors/corner_err_refund_exceeds_captured
    """
    plan = create_flat_plan()
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="LOW")
    charge = create_captured_charge(merchant["id"], auth_amount_cents=10000)
    headers = make_merchant_user_headers(merchant["id"])
    resp = api.create_refund(charge["id"], {"amount_cents": 11000}, headers)
    validate_error(resp, ApiErrorId.ERR_REFUND_EXCEEDS_CAPTURED)


def test_payout_over_available_rejected(api):
    """PRD §3.10: "the requested amount must not exceed the merchant's
    `available_balance_cents`; a request for more than the available balance is rejected with
    `ERR_INSUFFICIENT_BALANCE` (HTTP 422)".

    Design: Corner/Errors/corner_err_insufficient_balance_payout_over_available
    """
    base = setup_funded_merchant(assigned_risk_band="LOW", auth_amount_cents=10000)
    headers = make_merchant_user_headers(base["merchant_id"])
    # available is 9680; request 10000.
    resp = api.create_payout(base["merchant_id"], {"amount_cents": 10000, "scheduled_for": "2026-01-10"}, headers)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_BALANCE)
