"""Chargeback disputes: open debit vs won compensation, the cyclic representment process,
acceptance, and the dispute guards.

Covers difficulty queue (dual_variant_calc chargeback, non_linear_state_machine cyclic
dispute) and corner dispute/validation instances.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    set_clock,
    create_flat_plan, create_approved_merchant, create_captured_charge,
    open_and_settle_batch,
    setup_open_dispute, setup_acknowledged_dispute, setup_represented_dispute,
    make_merchant_user_headers,
    TEST_USERS,
)

OPERATOR = TEST_USERS["platform_operator_headers"]


def test_dispute_open_debits_disputed_amount_plus_fee(api):
    """PRD §3.6: "It also drives two ledger debits on the `AVAILABLE` account, both with
    `source_type` `DISPUTE`: a `CHARGEBACK` entry for the negative of `disputed_amount_cents`,
    and a `FEE` entry for the negative of the chargeback fee."

    Design: Difficulty/dual_variant_calc/chargeback_open_debit_vs_won_compensation_on_dispute
    """
    base = setup_open_dispute(disputed_amount_cents=10000, fund=True)
    merchant = validate_success(api.get_merchant(base["merchant_id"], OPERATOR))
    # funded available was 9680; open debits 10000 + 1500 -> -1820.
    assert merchant["available_balance_cents"] == -1820, (
        f"expected -1820, got {merchant['available_balance_cents']}"
    )


def test_dispute_won_credits_back_only_disputed_amount(api):
    """PRD §3.6: "Resolving `WON` drives the dispute to the terminal `WON` state, posts a
    `CHARGEBACK_REVERSAL` ledger entry on the `AVAILABLE` account for the positive of
    `disputed_amount_cents` (a credit) with `source_type` `DISPUTE`, and — because the
    chargeback fee is retained even on a win — does not reverse the `chargeback_fee_cents`."
    PRD §3.6: "Therefore a full open-then-won cycle leaves the merchant's available balance
    lower by exactly the chargeback fee".

    Design: Difficulty/dual_variant_calc/chargeback_open_debit_vs_won_compensation_on_dispute
    """
    base = setup_represented_dispute(disputed_amount_cents=10000, fund=True)
    before_open_available = 9680  # funded LOW/FLAT 10000 capture
    after_open = validate_success(api.get_merchant(base["merchant_id"], OPERATOR))
    assert after_open["available_balance_cents"] == -1820

    validate_success(api.resolve_dispute(base["dispute"]["id"], {"outcome": "WON"}, OPERATOR))
    after_won = validate_success(api.get_merchant(base["merchant_id"], OPERATOR))
    # -1820 + 10000 = 8180; net drift from before-open 9680 is -1500 (the retained fee).
    assert after_won["available_balance_cents"] == 8180, (
        f"expected 8180, got {after_won['available_balance_cents']}"
    )
    assert before_open_available - after_won["available_balance_cents"] == 1500


def test_dispute_won_restores_charge_settlement_status(api):
    """PRD §3.6: "If the charge's `settlement_status` had been driven to `REVERSED` by the
    open, winning restores it to `SETTLED`."

    Design: Difficulty/dual_variant_calc/chargeback_open_debit_vs_won_compensation_on_dispute
    """
    base = setup_represented_dispute(disputed_amount_cents=10000, fund=True)
    headers = make_merchant_user_headers(base["merchant_id"])
    reversed_charge = validate_success(api.get_charge(base["charge"]["id"], headers))
    assert reversed_charge["settlement_status"] == "REVERSED"
    validate_success(api.resolve_dispute(base["dispute"]["id"], {"outcome": "WON"}, OPERATOR))
    restored = validate_success(api.get_charge(base["charge"]["id"], headers))
    assert restored["settlement_status"] == "SETTLED"


def test_dispute_represent_then_reopen_then_represent_reaches_round_two(api):
    """PRD §3.6: "From `UNDER_REVIEW`, the merchant submits representment evidence, moving the
    dispute to `REPRESENTED` and incrementing `representment_round` by one".
    PRD §3.6: "a `PlatformOperator` reopens the dispute back to `UNDER_REVIEW`, which is
    permitted only while the dispute is `REPRESENTED` and `representment_round` is strictly
    less than two, and which extends `evidence_due_at` by another fourteen days."

    Design: Difficulty/non_linear_state_machine/dispute_cyclic_represent_reopen_rounds
    """
    base = setup_acknowledged_dispute(disputed_amount_cents=10000, fund=False)
    headers = make_merchant_user_headers(base["merchant_id"])
    dispute_id = base["dispute"]["id"]

    first = validate_success(api.represent_dispute(dispute_id, {}, headers))
    assert first["dispute_status"] == "REPRESENTED"
    assert first["representment_round"] == 1

    validate_success(api.reopen_dispute(dispute_id, {}, OPERATOR))
    second = validate_success(api.represent_dispute(dispute_id, {}, headers))
    assert second["dispute_status"] == "REPRESENTED"
    assert second["representment_round"] == 2


def test_dispute_representment_round_increments_each_submission(api):
    """PRD §3.6: "the merchant submits representment evidence, moving the dispute to
    `REPRESENTED` and incrementing `representment_round` by one".

    Design: Difficulty/non_linear_state_machine/dispute_cyclic_represent_reopen_rounds
    """
    base = setup_acknowledged_dispute(disputed_amount_cents=10000, fund=False)
    headers = make_merchant_user_headers(base["merchant_id"])
    dispute_id = base["dispute"]["id"]
    after_first = validate_success(api.represent_dispute(dispute_id, {}, headers))
    assert after_first["representment_round"] == 1
    validate_success(api.reopen_dispute(dispute_id, {}, OPERATOR))
    after_second = validate_success(api.represent_dispute(dispute_id, {}, headers))
    assert after_second["representment_round"] == 2


# --- Corner: dispute side effects and guards ---

def test_dispute_accept_from_open_retains_chargeback_debit(api):
    """PRD §3.6: "The merchant may also concede at any time before resolution by accepting
    liability, which drives the dispute to the terminal `ACCEPTED` state from either `OPEN` or
    `UNDER_REVIEW` with no further ledger postings and the chargeback debit retained."

    Design: Corner/State Machines/corner_dispute_accept_from_open_side_effect_retains_chargeback
    """
    base = setup_open_dispute(disputed_amount_cents=10000, fund=True)
    headers = make_merchant_user_headers(base["merchant_id"])
    accepted = validate_success(api.accept_dispute(base["dispute"]["id"], {}, headers))
    assert accepted["dispute_status"] == "ACCEPTED"
    merchant = validate_success(api.get_merchant(base["merchant_id"], OPERATOR))
    # 9680 - 10000 - 1500 = -1820 (chargeback debit retained on ACCEPTED).
    assert merchant["available_balance_cents"] == -1820


def test_acknowledge_twice_rejected_invalid_state(api):
    """PRD §3.6: "The merchant acknowledges the dispute, moving it from `OPEN` to
    `UNDER_REVIEW`".
    PRD §2.9: "Every action endpoint that drives a state machine first checks that the target
    resource is in a state from which the requested transition is defined; if it is not, the
    request is rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/State Machines/corner_dispute_acknowledge_twice_idempotency_rejected
    """
    base = setup_acknowledged_dispute(disputed_amount_cents=10000, fund=False)
    headers = make_merchant_user_headers(base["merchant_id"])
    resp = api.acknowledge_dispute(base["dispute"]["id"], {}, headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_dispute_amount_not_equal_net_captured_rejected(api):
    """PRD §3.6: "a disputed amount that does not equal net captured is rejected with
    `ERR_DISPUTE_AMOUNT_MISMATCH` (HTTP 422)".

    Design: Corner/Validations/corner_dispute_amount_mismatch_rejected
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = create_flat_plan()
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="LOW")
    version = merchant["version"]
    charge = create_captured_charge(merchant["id"], auth_amount_cents=10000)
    open_and_settle_batch(merchant["id"], version, business_date="2026-01-01")
    headers = make_merchant_user_headers(merchant["id"])
    resp = api.create_dispute(charge["id"], {"disputed_amount_cents": 9999}, headers)
    validate_error(resp, ApiErrorId.ERR_DISPUTE_AMOUNT_MISMATCH)


def test_dispute_open_on_unsettled_charge_rejected_invalid_state(api):
    """PRD §3.6: "A dispute can be opened only on a charge whose `auth_status` is `CAPTURED`
    and whose `settlement_status` is `SETTLED`, and only when no non-terminal dispute already
    exists on that charge."
    PRD §3.6: "an open attempt against a charge whose status does not permit it is rejected
    with `ERR_INVALID_STATE`."

    Design: Corner/Validations/corner_dispute_open_on_unsettled_charge_invalid_state
    """
    plan = create_flat_plan()
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="LOW")
    charge = create_captured_charge(merchant["id"], auth_amount_cents=10000)
    headers = make_merchant_user_headers(merchant["id"])
    resp = api.create_dispute(charge["id"], {"disputed_amount_cents": 10000}, headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_resolve_with_invalid_outcome_rejected(api):
    """PRD §3.6: "A represented dispute is resolved by a `PlatformOperator` with an `outcome`
    of either `WON` or `LOST`; an `outcome` outside that pair is rejected with
    `ERR_RESOLVE_OUTCOME_INVALID` (HTTP 422)".

    Design: Corner/Validations/corner_resolve_outcome_invalid_rejected
    """
    base = setup_represented_dispute(disputed_amount_cents=10000, fund=False)
    resp = api.resolve_dispute(base["dispute"]["id"], {"outcome": "MAYBE"}, OPERATOR)
    validate_error(resp, ApiErrorId.ERR_RESOLVE_OUTCOME_INVALID)
