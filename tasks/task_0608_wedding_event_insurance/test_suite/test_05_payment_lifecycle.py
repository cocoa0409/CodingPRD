"""Paying, activating, and the parallel billing/lifecycle dimensions.

Queue A: non_linear_state_machine / policy_parallel_billing_advances_independently_of_lifecycle
         priority_pair_validation_conflict / pay_on_unbound_policy_state_beats_amount_mismatch
Queue B: payment-amount mismatch, activate-before-payment.
"""
from test_helpers import (
    validate_success, validate_error, make_policyholder_headers, TEST_USERS,
)
from test_helpers import fixtures as FX

_admin = TEST_USERS["admin_headers"]
_uw = TEST_USERS["underwriter_headers"]
_ph = make_policyholder_headers("ph-1")


def test_policy_parallel_billing_advances_independently_of_lifecycle(api):
    """PRD §2.8: "paying the premium advances `billing_status` from `UNPAID` to `PAID`
    while `lifecycle_status` remains `BOUND`, and only a subsequent action that requires
    the premium to be `PAID` advances the lifecycle to `IN_FORCE`."

    Design: Difficulty/non_linear_state_machine/policy_parallel_billing_advances_independently_of_lifecycle
    """
    ctx = FX.setup_bound_policy_canc_only()  # total_premium_cents == 65000
    res = api.pay_policy(ctx["policy"]["id"], {"amount_cents": 65000}, _ph)
    paid = validate_success(res, 200)
    assert paid["billing_status"] == "PAID"
    assert paid["lifecycle_status"] == "BOUND"


def test_payment_moves_only_billing_dimension(api):
    """PRD §3.5: "A successful payment increments the policy's `version`. Note that
    payment moves only the billing dimension — the lifecycle remains `BOUND`."

    Design: Difficulty/non_linear_state_machine/policy_parallel_billing_advances_independently_of_lifecycle
    """
    ctx = FX.setup_bound_policy_canc_only()
    before = validate_success(api.get_policy(ctx["policy"]["id"], _uw), 200)
    paid = validate_success(
        api.pay_policy(ctx["policy"]["id"], {"amount_cents": 65000}, _ph), 200)
    assert paid["lifecycle_status"] == "BOUND"
    assert paid["billing_status"] == "PAID"
    assert paid["version"] == before["version"] + 1


def test_pay_on_unbound_policy_state_beats_amount_mismatch(api):
    """PRD §3.5: "the policy's `lifecycle_status` must be `BOUND`, or the request is
    rejected with `ERR_POLICY_NOT_BOUND`; the policy's `billing_status` must be `UNPAID`,
    or it is rejected with `ERR_PREMIUM_ALREADY_PAID`; and the submitted `amount_cents`
    must exactly equal the policy's `total_premium_cents`, or it is rejected with
    `ERR_PAYMENT_AMOUNT_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/pay_on_unbound_policy_state_beats_amount_mismatch
    """
    policy = FX.create_quoted_policy()  # QUOTED, total_premium_cents == 0
    res = api.pay_policy(policy["id"], {"amount_cents": 99999}, _ph)
    validate_error(res, "ERR_POLICY_NOT_BOUND", 409)


def test_pay_on_quoted_policy_not_amount_mismatch_even_with_zero_premium(api):
    """PRD §3.5: "the policy's `lifecycle_status` must be `BOUND`, or the request is
    rejected with `ERR_POLICY_NOT_BOUND`; the policy's `billing_status` must be `UNPAID`,
    or it is rejected with `ERR_PREMIUM_ALREADY_PAID`; and the submitted `amount_cents`
    must exactly equal the policy's `total_premium_cents`, or it is rejected with
    `ERR_PAYMENT_AMOUNT_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/pay_on_unbound_policy_state_beats_amount_mismatch
    """
    # A QUOTED policy has total_premium_cents==0; paying 0 would match the amount but the
    # lifecycle precondition (checked first per §3.5) still fires ERR_POLICY_NOT_BOUND.
    policy = FX.create_quoted_policy()
    res = api.pay_policy(policy["id"], {"amount_cents": 0}, _ph)
    validate_error(res, "ERR_POLICY_NOT_BOUND", 409)


def test_payment_amount_mismatch_rejected(api):
    """PRD §3.5: "the submitted `amount_cents` must exactly equal the policy's
    `total_premium_cents`, or it is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH`."

    Design: Corner/validations/payment_amount_mismatch_rejected
    """
    ctx = FX.setup_bound_policy_canc_only()  # total_premium_cents == 65000
    res = api.pay_policy(ctx["policy"]["id"], {"amount_cents": 60000}, _ph)
    validate_error(res, "ERR_PAYMENT_AMOUNT_MISMATCH", 422)
    refreshed = validate_success(api.get_policy(ctx["policy"]["id"], _uw), 200)
    assert refreshed["billing_status"] == "UNPAID"


def test_activate_coverage_before_payment_rejected(api):
    """PRD §3.5: "This step is gated on the billing dimension: the policy must be `BOUND`,
    or `ERR_POLICY_NOT_BOUND` is returned, and its `billing_status` must be `PAID`, or
    `ERR_PREMIUM_UNPAID` is returned."

    Design: Corner/state_machines/activate_coverage_before_payment_rejected
    """
    ctx = FX.setup_bound_policy_canc_only()  # BOUND but UNPAID
    res = api.activate_coverage(ctx["policy"]["id"], _uw)
    validate_error(res, "ERR_PREMIUM_UNPAID", 409)
    refreshed = validate_success(api.get_policy(ctx["policy"]["id"], _uw), 200)
    assert refreshed["lifecycle_status"] == "BOUND"
