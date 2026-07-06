"""Subscription lifecycle: pause, resume, change with OCC, past-due fiscal block, and
parallel-axis independence.

Covers difficulty rule `non_linear_state_machine.subscription_parallel_lifecycle_and_billing_axes`
and multiple corner state-machine / validation / cross-cutting instances.
"""
from test_helpers import (
    api_client,
    make_customer_headers,
    setup_plan_customer_subscription,
    get_subscription,
    get_subscription_charges,
    capture_current_charge,
    capture_payment_fail,
    pause,
    validate_error,
    validate_success,
    TEST_USERS,
    ApiErrorId,
)
from test_helpers.factories import change_subscription_payload


# =====================================================================
# Difficulty §1.8: non_linear_state_machine.subscription_parallel_lifecycle_and_billing_axes
# =====================================================================


def test_pause_moves_lifecycle_axis_only_leaving_billing_axis_untouched():
    """PRD §2.7: "A `Subscription` tracks two independent status axes on the same record. Its `lifecycle_status` (one of `ACTIVE`, `PAUSED`, `CANCELLED`, `EXPIRED`) governs the customer-facing lifecycle, while its `billing_status` (one of `CURRENT`, `PAST_DUE`) governs its financial standing. The two evolve independently: a subscription can be `ACTIVE` while `PAST_DUE`, or `PAUSED` while `CURRENT`."
    PRD §3.3: "A subscriber can pause an `ACTIVE` subscription, moving its `lifecycle_status` from `ACTIVE` to `PAUSED`".

    Pause flips lifecycle to PAUSED without touching billing.

    Design: Difficulty/non_linear_state_machine/subscription_parallel_lifecycle_and_billing_axes
    """
    _plan, customer, subscription = setup_plan_customer_subscription()
    pause_res = api_client.pause_subscription(
        subscription["id"], {}, make_customer_headers(customer["id"])
    )
    paused = validate_success(pause_res)
    assert paused["lifecycle_status"] == "PAUSED"
    assert paused["billing_status"] == "CURRENT"


def test_pause_then_payment_fail_holds_both_axes_independently():
    """PRD §2.7: "The two evolve independently: a subscription can be `ACTIVE` while `PAST_DUE`, or `PAUSED` while `CURRENT`."
    PRD §3.7: "A `FAILED` outcome moves the charge to `FAILED` and cascades on the billing axis: the subscription's `billing_status` flips to `PAST_DUE`".

    Pause sets lifecycle=PAUSED; failed payment sets billing=PAST_DUE; the two axes co-exist.

    Design: Difficulty/non_linear_state_machine/subscription_parallel_lifecycle_and_billing_axes
    """
    _plan, customer, subscription = setup_plan_customer_subscription()
    pause(subscription["id"], customer["id"])
    charge = capture_current_charge(subscription["id"])
    capture_payment_fail(charge["id"])
    sub = get_subscription(subscription["id"])
    assert sub["lifecycle_status"] == "PAUSED"
    assert sub["billing_status"] == "PAST_DUE"


# =====================================================================
# Corner: state machine invalid transitions
# =====================================================================


def test_pause_from_paused_returns_invalid_state():
    """PRD §2.9: "The target resource must be in a state from which the requested transition is legal, including cross-entity state preconditions; failures surface as `ERR_INVALID_STATE`, `ERR_SHIPMENT_NOT_SKIPPABLE`, `ERR_OFFER_NOT_REDEEMABLE`, `ERR_SUBSCRIPTION_NOT_ACTIVE`, or `ERR_LOT_EXPIRED` (all 409)."
    PRD §3.3: "A subscriber can pause an `ACTIVE` subscription, moving its `lifecycle_status` from `ACTIVE` to `PAUSED`".

    Pause is legal only from ACTIVE, so pausing a PAUSED subscription is an invalid state.

    Design: Corner/state_machines/corner_pause_from_paused_invalid
    """
    _plan, customer, subscription = setup_plan_customer_subscription()
    pause(subscription["id"], customer["id"])
    res = api_client.pause_subscription(
        subscription["id"], {}, make_customer_headers(customer["id"])
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_resume_from_active_returns_invalid_state():
    """PRD §3.3: "Resuming reverses this: a `PAUSED` subscription returns to `ACTIVE`, `paused_until` is cleared, and the `version` increments again. Both actions require that the acting customer own the subscription, and each is legal only from its respective source state."

    Resume from ACTIVE is not from PAUSED, so it violates the state precondition.

    Design: Corner/state_machines/corner_resume_from_active_invalid
    """
    _plan, customer, subscription = setup_plan_customer_subscription()
    res = api_client.resume_subscription(
        subscription["id"], {}, make_customer_headers(customer["id"])
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# =====================================================================
# Corner: fiscal block on change
# =====================================================================


def test_change_rejected_while_billing_past_due():
    """PRD §3.3: "A change is refused while the subscription is `PAST_DUE`: the fiscal gate rejects it with `ERR_BILLING_PAST_DUE`."

    Design: Corner/validations/corner_billing_past_due_blocks_change
    """
    _plan, customer, subscription = setup_plan_customer_subscription()
    charge = capture_current_charge(subscription["id"])
    capture_payment_fail(charge["id"])
    # Refresh version after the billing cascade.
    sub_after = get_subscription(subscription["id"])
    assert sub_after["billing_status"] == "PAST_DUE"
    payload = change_subscription_payload(
        expected_subscription_version=sub_after["version"], size="DELUXE"
    )
    res = api_client.change_subscription(
        subscription["id"], payload, make_customer_headers(customer["id"])
    )
    validate_error(res, ApiErrorId.ERR_BILLING_PAST_DUE.value)


# =====================================================================
# Corner: OCC
# =====================================================================


def test_change_with_stale_version_rejected():
    """PRD §2.8: "Before applying the change, the server compares `expected_subscription_version` to the subscription's current `version`. If they do not match — because a prior change, a renewal, or a billing cascade advanced the subscription's `version` since the client last read it — the request is rejected with `ERR_STALE_VERSION` and HTTP status 412".

    First change bumps version; a second change carrying the pre-change version is stale.

    Design: Corner/cross_cutting/corner_occ_stale_version_change_rejected
    """
    _plan, customer, subscription = setup_plan_customer_subscription()
    initial_version = subscription["version"]
    # First change succeeds and bumps version.
    first_payload = change_subscription_payload(
        expected_subscription_version=initial_version, size="DELUXE"
    )
    first_res = api_client.change_subscription(
        subscription["id"], first_payload, make_customer_headers(customer["id"])
    )
    validate_success(first_res)
    # Second change reuses the stale version.
    second_payload = change_subscription_payload(
        expected_subscription_version=initial_version, size="GRAND"
    )
    second_res = api_client.change_subscription(
        subscription["id"], second_payload, make_customer_headers(customer["id"])
    )
    validate_error(second_res, ApiErrorId.ERR_STALE_VERSION.value)


def test_change_with_current_version_succeeds_bumps_version_and_recomputes_price():
    """PRD §3.3: "A successful change recomputes `renewal_price_cents` (using the same gross/discount/cap/floor rule as at creation, so the new configuration prices the next renewal) and increments the subscription's `version`."

    Design: Corner/cross_cutting/corner_occ_correct_version_change_succeeds
    """
    plan, customer, subscription = setup_plan_customer_subscription(base_fee_cents=6000)
    v0 = subscription["version"]
    payload = change_subscription_payload(
        expected_subscription_version=v0, size="DELUXE"
    )
    res = api_client.change_subscription(
        subscription["id"], payload, make_customer_headers(customer["id"])
    )
    changed = validate_success(res)
    assert changed["version"] == v0 + 1, (
        f"version must increment by 1; was {v0}, now {changed['version']}"
    )
    # 6000 + DELUXE 1500 + no vase = 7500 (§3.2 pricing rule)
    assert changed["renewal_price_cents"] == 7500


# =====================================================================
# Corner: ownership on change
# =====================================================================


def test_change_by_non_owner_returns_not_owner():
    """PRD §2.1: "A `Customer` is a subscriber acting on their own subscriptions, shipments, wallet, and win-back offers. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity. Ownership checks compare the targeted resource back to that identity: a subscription's `customer_id`, a shipment's owning subscription's `customer_id`, and a win-back offer's `customer_id` must all equal `X-User-ID`. When a customer targets a resource they do not own, the request is rejected with `ERR_NOT_OWNER`".

    A distinct customer acting on someone else's subscription is not the owner.

    Design: Corner/validations/corner_not_owner_change
    """
    from test_helpers.fixtures import create_customer, create_plan, create_subscription_for

    plan = create_plan()
    c1 = create_customer()
    c2 = create_customer()  # distinct actor
    subscription = create_subscription_for(c1, plan)
    payload = change_subscription_payload(
        expected_subscription_version=subscription["version"], size="DELUXE"
    )
    res = api_client.change_subscription(
        subscription["id"], payload, make_customer_headers(c2["id"])
    )
    validate_error(res, ApiErrorId.ERR_NOT_OWNER.value)
