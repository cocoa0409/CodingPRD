"""Charge lifecycle: double-capture idempotency and refund limits.

Covers corner state_machines and validations instances.
"""
from test_helpers import (
    api_client,
    TEST_USERS,
    validate_error,
    validate_success,
    ApiErrorId,
    setup_captured_charge_subscription,
    capture_current_charge,
    capture_payment_succeed,
)
from test_helpers.factories import simulate_payment_payload, refund_payload


# =====================================================================
# Corner: charge_double_capture_idempotency
# =====================================================================


def test_second_success_on_captured_charge_returns_invalid_state():
    """PRD §3.7: "A `SUCCEEDED` outcome captures the charge, moving it to `CAPTURED`".
    PRD §3.7: "A `BillingAdmin` simulates a payment attempt on a `PENDING` charge by supplying an `outcome`."
    PRD §2.9: "The target resource must be in a state from which the requested transition is legal, including cross-entity state preconditions; failures surface as `ERR_INVALID_STATE`, `ERR_SHIPMENT_NOT_SKIPPABLE`, `ERR_OFFER_NOT_REDEEMABLE`, `ERR_SUBSCRIPTION_NOT_ACTIVE`, or `ERR_LOT_EXPIRED` (all 409)."

    simulate-payment expects a PENDING charge. A charge already CAPTURED fails the state check.

    Design: Corner/state_machines/corner_charge_double_capture_idempotency
    """
    _plan, _customer, _subscription, charge = setup_captured_charge_subscription()
    assert charge["status"] == "CAPTURED"
    res = api_client.simulate_payment(
        charge["id"], simulate_payment_payload("SUCCEEDED"), TEST_USERS["billing_admin_headers"]
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# =====================================================================
# Corner: refund_exceeds_captured
# =====================================================================


def test_refund_exceeding_captured_amount_rejected():
    """PRD §3.7: "The refund is refused with `ERR_REFUND_EXCEEDS_CAPTURED` if the already-refunded amount plus the requested amount would exceed the charge's `amount_cents`."

    DELUXE+vase = 8700 CAPTURED; refund 9000 > 8700.

    Design: Corner/validations/corner_refund_exceeds_captured
    """
    _plan, _customer, _subscription, charge = setup_captured_charge_subscription(
        size="DELUXE", vase_addon=True
    )
    res = api_client.refund_charge(
        charge["id"], refund_payload(9000), TEST_USERS["billing_admin_headers"]
    )
    validate_error(res, ApiErrorId.ERR_REFUND_EXCEEDS_CAPTURED.value)
