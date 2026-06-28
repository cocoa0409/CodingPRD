"""Policy billing dimension: payment thresholds, the parallel coverage/billing axes, and
payment reversal. Also the appraisal-threshold bind boundary.

Design queue A: non_linear_state_machine (parallel dimensions), boundary_precision_check.
Design queue B: validations (underpaid, not billable).
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    set_clock,
    create_risk_zone,
    create_policyholder,
    create_policy,
    create_scheduled_item,
    bind_policy,
    pay_premium,
    setup_quoted_policy_with_item,
    setup_bound_policy_with_item,
    setup_active_policy_with_item,
    make_policyholder_headers,
)

_UW = TEST_USERS["underwriter_headers"]


# ─────────────────────────────────────────────────────────────────────────
# Queue A: non_linear_state_machine — parallel coverage x billing dimensions
# ─────────────────────────────────────────────────────────────────────────

def test_payment_reversal_flips_billing_but_not_coverage(api):
    """PRD §3.6: "An Underwriter may reverse a previously received payment; reversal requires
    the payment to be in status RECEIVED (otherwise ERR_INVALID_STATE), sets that payment's
    status to REVERSED, drives billing_status from PAID to PAST_DUE, and stamps past_due_since
    with the current clock."
    PRD §3.6: "A policy carries two status dimensions that evolve independently:
    coverage_status, the coverage lifecycle, and billing_status, the premium-payment
    dimension."

    Design: Difficulty/non_linear_state_machine/policy_parallel_coverage_billing_dimensions
    """
    ctx = setup_active_policy_with_item()
    pol, payment = ctx["policy"], ctx["payment"]
    assert pol["coverage_status"] == "ACTIVE"
    assert pol["billing_status"] == "PAID"

    reversed_payment = validate_success(
        api.reverse_payment(pol["id"], payment["id"], _UW), 200)
    assert reversed_payment["status"] == "REVERSED"

    after = validate_success(api.get_policy(pol["id"], _UW), 200)
    assert after["coverage_status"] == "ACTIVE"
    assert after["billing_status"] == "PAST_DUE"


def test_bound_policy_bubbles_to_active_on_paid(api):
    """PRD §3.6: "a policy that is BOUND automatically advances its coverage_status to ACTIVE
    the moment billing_status becomes PAID, since active coverage requires a paid premium."
    PRD §3.6: "A sufficient payment drives billing_status from UNBILLED to PAID and increments
    the policy's version."

    Design: Difficulty/non_linear_state_machine/policy_parallel_coverage_billing_dimensions
    """
    ctx = setup_bound_policy_with_item()
    assert ctx["policy"]["coverage_status"] == "BOUND"
    assert ctx["policy"]["billing_status"] == "UNBILLED"

    pay_premium(ctx["policy"]["id"], ctx["policyholder"]["id"])
    after = validate_success(api.get_policy(ctx["policy"]["id"], _UW), 200)
    assert after["coverage_status"] == "ACTIVE"
    assert after["billing_status"] == "PAID"


# ─────────────────────────────────────────────────────────────────────────
# Queue A: boundary_precision_check
# ─────────────────────────────────────────────────────────────────────────

def test_item_exactly_at_appraisal_threshold_binds_without_appraisal(api):
    """PRD §3.3: "every scheduled item whose scheduled_value_cents exceeds ten thousand
    dollars must carry a non-null appraisal_id pointing to a currently valid appraisal, or
    the bind is rejected with ERR_APPRAISAL_REQUIRED. This appraisal threshold is strict: an
    item valued at exactly ten thousand dollars needs no appraisal, while an item valued at
    ten thousand dollars and one cent does."

    Design: Difficulty/boundary_precision_check/appraisal_threshold_strict_greater_than
    """
    ctx = setup_quoted_policy_with_item(
        item_overrides={"scheduled_value_cents": 1000000})  # exactly $10,000
    bound = validate_success(api.bind_policy(ctx["policy"]["id"], _UW), 200)
    assert bound["coverage_status"] == "BOUND"

    item = validate_success(api.get_scheduled_item(ctx["item"]["id"], _UW), 200)
    assert item["item_status"] == "ACTIVE"


def test_premium_payment_exact_amount_accepted(api):
    """PRD §3.6: "the tendered amount_cents must be at least the policy's annual_premium_cents,
    or it is rejected with ERR_PREMIUM_UNDERPAID."
    PRD §3.6: "A sufficient payment drives billing_status from UNBILLED to PAID and increments
    the policy's version."
    PRD §3.6: "a policy that is BOUND automatically advances its coverage_status to ACTIVE the
    moment billing_status becomes PAID"

    Design: Difficulty/boundary_precision_check/premium_payment_exact_amount_accepted
    """
    ctx = setup_bound_policy_with_item()
    # RING cv 1,000,000, zone rate 300, ALL_RISK, STANDARD -> annual_premium_cents 3947.
    assert ctx["policy"]["annual_premium_cents"] == 3947
    ph_headers = make_policyholder_headers(ctx["policyholder"]["id"])

    validate_success(
        api.create_payment(ctx["policy"]["id"], {"amount_cents": 3947}, ph_headers), 201)
    after = validate_success(api.get_policy(ctx["policy"]["id"], _UW), 200)
    assert after["billing_status"] == "PAID"
    assert after["coverage_status"] == "ACTIVE"


def test_item_one_cent_above_appraisal_threshold_requires_appraisal(api):
    """PRD §3.3: "every scheduled item whose scheduled_value_cents exceeds ten thousand
    dollars must carry a non-null appraisal_id pointing to a currently valid appraisal, or the
    bind is rejected with ERR_APPRAISAL_REQUIRED. This appraisal threshold is strict: an item
    valued at exactly ten thousand dollars needs no appraisal, while an item valued at ten
    thousand dollars and one cent does."

    Design: Difficulty/boundary_precision_check/appraisal_threshold_strict_greater_than
    """
    ctx = setup_quoted_policy_with_item(
        item_overrides={"scheduled_value_cents": 1000001})  # $10,000.01, no appraisal_id
    res = api.bind_policy(ctx["policy"]["id"], _UW)
    validate_error(res, ApiErrorId.ERR_APPRAISAL_REQUIRED, 409)


def test_premium_payment_one_cent_above_premium_accepted(api):
    """PRD §3.6: "the tendered amount_cents must be at least the policy's annual_premium_cents,
    or it is rejected with ERR_PREMIUM_UNDERPAID."
    PRD §3.6: "A Policyholder (or an Underwriter acting for them) records a PremiumPayment
    against the policy, supplying an amount_cents; the payment is created in status RECEIVED
    with its policy_id set from the path policy."

    Design: Difficulty/boundary_precision_check/premium_payment_exact_amount_accepted
    """
    ctx = setup_bound_policy_with_item()
    assert ctx["policy"]["annual_premium_cents"] == 3947
    ph_headers = make_policyholder_headers(ctx["policyholder"]["id"])
    # One cent above the threshold is also accepted (boundary '>=').
    payment = validate_success(
        api.create_payment(ctx["policy"]["id"], {"amount_cents": 3948}, ph_headers), 201)
    assert payment["status"] == "RECEIVED"
    after = validate_success(api.get_policy(ctx["policy"]["id"], _UW), 200)
    assert after["billing_status"] == "PAID"


# ─────────────────────────────────────────────────────────────────────────
# Queue B: validations — billing rejections
# ─────────────────────────────────────────────────────────────────────────

def test_payment_one_cent_below_premium_rejected(api):
    """PRD §3.6: "the tendered amount_cents must be at least the policy's annual_premium_cents,
    or it is rejected with ERR_PREMIUM_UNDERPAID."

    Design: Corner/validations/premium_payment_underpaid_rejected
    """
    ctx = setup_bound_policy_with_item()
    assert ctx["policy"]["annual_premium_cents"] == 3947
    ph_headers = make_policyholder_headers(ctx["policyholder"]["id"])
    res = api.create_payment(ctx["policy"]["id"], {"amount_cents": 3946}, ph_headers)
    validate_error(res, ApiErrorId.ERR_PREMIUM_UNDERPAID, 409)


def test_payment_on_quoted_policy_rejected(api):
    """PRD §3.6: "the policy's coverage_status must be one of BOUND, ACTIVE, or LAPSED, or
    the payment is rejected with ERR_POLICY_NOT_BILLABLE"

    Design: Corner/validations/policy_not_billable_before_bind
    """
    ctx = setup_quoted_policy_with_item()  # never bound -> QUOTED
    ph_headers = make_policyholder_headers(ctx["policyholder"]["id"])
    res = api.create_payment(ctx["policy"]["id"], {"amount_cents": 5000000}, ph_headers)
    validate_error(res, ApiErrorId.ERR_POLICY_NOT_BILLABLE, 409)
