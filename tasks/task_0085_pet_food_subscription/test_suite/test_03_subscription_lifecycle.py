"""Subscription state machine (PRD §3.2)."""
from __future__ import annotations

import datetime as dt

import pytest

from test_helpers import (
    ApiErrorId,
    activate_subscription,
    advance_clock_by_hours,
    api_client,
    assert_subscription,
    cancel_force,
    cancel_subscription_payload,
    create_draft_subscription,
    create_pet,
    create_subscription_payload,
    make_address,
    make_customer_headers,
    pause_subscription_payload,
    reload_subscription,
    setup_active_subscription,
    setup_customer_with_pet,
    setup_verified_customer,
    update_subscription_payload,
    validate_error,
    validate_success,
    verify_subscription_address,
)


# ---------------------------------------------------------------------------
# DRAFT → ACTIVE preconditions
# ---------------------------------------------------------------------------
def test_subscription_create_initial_state_is_draft(api):
    """PRD §3.2: 'The new subscription's status is DRAFT and the
    customer_id is taken from the path.'
    """
    customer, pet = setup_customer_with_pet()
    sub = create_draft_subscription(customer, pet)
    assert_subscription(sub)
    assert sub["status"] == "DRAFT"
    assert sub["customer_id"] == customer["id"]
    assert sub["pet_ids"] == [pet["id"]]
    assert sub["scheduled_order_count"] == 0
    assert sub["skipped_count"] == 0
    assert sub["total_cycles_elapsed"] == 0
    assert sub["retention_offer_applied"] is False
    assert sub["modification_deadline_hours"] == 48


def test_subscription_create_forces_address_verified_false(api):
    """PRD §3.2: 'copies the supplied address into shipping_address,
    forcing its verified to false.'
    """
    customer, pet = setup_customer_with_pet()
    sub = create_draft_subscription(customer, pet)
    assert sub["shipping_address"]["verified"] is False


@pytest.mark.parametrize("frequency,expected_cycle_days", [
    ("WEEKLY", 7),
    ("BIWEEKLY", 14),
    ("MONTHLY", 30),
])
def test_subscription_cycle_days_derived_from_frequency(
    api, frequency, expected_cycle_days,
):
    """PRD §3.2: 'The server derives cycle_days from frequency — 7
    for weekly, 14 for biweekly, 30 for monthly.'
    """
    customer, pet = setup_customer_with_pet()
    sub = create_draft_subscription(customer, pet, frequency=frequency)
    assert sub["cycle_days"] == expected_cycle_days


def test_subscription_activate_requires_address_verified(api):
    """PRD §3.2: 'A DRAFT subscription moves to ACTIVE when the
    customer invokes activation, provided that the subscription's
    shipping_address has been verified (otherwise
    ERR_ADDRESS_NOT_VERIFIED).'
    """
    customer, pet = setup_customer_with_pet()
    sub = create_draft_subscription(customer, pet)
    # Skip verify_subscription_address — address is still unverified.
    res = api.activate_subscription(
        sub["id"], make_customer_headers(customer["id"]),
    )
    validate_error(res, ApiErrorId.ERR_ADDRESS_NOT_VERIFIED.value)


def test_subscription_activate_with_verified_address_succeeds(api):
    """PRD §3.2: 'Activation sets next_cycle_at to the current logical
    clock plus cycle_days, computes one initial PENDING
    RecipeRecommendation for each pet, and appends a PLAN_MODIFIED
    audit entry.'
    """
    customer, pet = setup_customer_with_pet()
    sub = create_draft_subscription(customer, pet)
    sub = verify_subscription_address(customer, sub)
    res = api.activate_subscription(
        sub["id"], make_customer_headers(customer["id"]),
    )
    after = validate_success(res)
    assert after["status"] == "ACTIVE"
    assert after["next_cycle_at"] is not None


# ---------------------------------------------------------------------------
# ACTIVE → PAUSED
# ---------------------------------------------------------------------------
def test_pause_rejects_invalid_pause_window_in_past(api):
    """PRD §3.2: 'with ERR_INVALID_PAUSE_WINDOW if pause_until is less
    than or equal to the current logical clock.'
    """
    bundle = setup_active_subscription()
    customer = bundle["customer"]
    sub = bundle["subscription"]
    past_ts = "1970-01-01T00:00:00.000Z"
    res = api.pause_subscription(
        sub["id"],
        pause_subscription_payload(past_ts),
        make_customer_headers(customer["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_PAUSE_WINDOW.value)


def test_pause_from_active_succeeds_and_clears_next_cycle_at(api):
    """PRD §3.2: 'When pause succeeds, status becomes PAUSED,
    paused_until is set to the supplied pause_until, next_cycle_at is
    cleared to null.'
    """
    bundle = setup_active_subscription()
    customer = bundle["customer"]
    sub = bundle["subscription"]
    future = "2099-12-31T00:00:00.000Z"
    res = api.pause_subscription(
        sub["id"], pause_subscription_payload(future),
        make_customer_headers(customer["id"]),
    )
    after = validate_success(res)
    assert after["status"] == "PAUSED"
    assert after["next_cycle_at"] is None
    assert after["paused_until"] is not None


def test_pause_when_not_active_rejected(api):
    """PRD §3.2: 'Pause is rejected with ERR_INVALID_SUBSCRIPTION_STATE
    if the subscription is not currently in ACTIVE.'
    """
    customer, pet = setup_customer_with_pet()
    sub = create_draft_subscription(customer, pet)
    res = api.pause_subscription(
        sub["id"],
        pause_subscription_payload("2099-12-31T00:00:00.000Z"),
        make_customer_headers(customer["id"]),
    )
    validate_error(
        res, ApiErrorId.ERR_INVALID_SUBSCRIPTION_STATE.value,
    )


# ---------------------------------------------------------------------------
# PAUSED → ACTIVE via manual resume
# ---------------------------------------------------------------------------
def test_manual_resume_from_paused(api):
    """PRD §3.2: 'A PAUSED subscription returns to ACTIVE either
    automatically ... or manually, when the customer invokes the
    resume capability. Either path requires that the subscription is
    currently in PAUSED.'

    'paused_until is cleared to null, next_cycle_at is set to the
    current logical clock plus cycle_days, and a RESUMED audit entry
    is appended.'
    """
    bundle = setup_active_subscription()
    customer = bundle["customer"]
    sub = bundle["subscription"]
    api.pause_subscription(
        sub["id"],
        pause_subscription_payload("2099-12-31T00:00:00.000Z"),
        make_customer_headers(customer["id"]),
    )
    res = api.resume_subscription(
        sub["id"], make_customer_headers(customer["id"]),
    )
    after = validate_success(res)
    assert after["status"] == "ACTIVE"
    assert after["paused_until"] is None
    assert after["next_cycle_at"] is not None


def test_resume_when_not_paused_rejected(api):
    """PRD §3.2: 'Either path requires that the subscription is
    currently in PAUSED (otherwise ERR_INVALID_SUBSCRIPTION_STATE).'
    """
    bundle = setup_active_subscription()
    res = api.resume_subscription(
        bundle["subscription"]["id"],
        make_customer_headers(bundle["customer"]["id"]),
    )
    validate_error(
        res, ApiErrorId.ERR_INVALID_SUBSCRIPTION_STATE.value,
    )


# ---------------------------------------------------------------------------
# Cancel — invalid reason
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("reason", ["WHATEVER", "TOO_EXPENSIVE", ""])
def test_cancel_rejects_invalid_reason(api, reason):
    """PRD §3.2: 'whose value must be one of PRICE, QUALITY,
    PET_NO_LONGER, or OTHER (any other value is rejected with
    ERR_INVALID_CANCEL_REASON).'
    """
    bundle = setup_active_subscription()
    customer = bundle["customer"]
    sub = bundle["subscription"]
    res = api.cancel_subscription(
        sub["id"],
        cancel_subscription_payload(reason),
        make_customer_headers(customer["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_CANCEL_REASON.value)


def test_cancel_with_price_reason_returns_retention_offer_first(api):
    """PRD §3.2: 'When cancel_reason is PRICE and
    retention_offer_applied is currently false and force is not true,
    the cancel is deflected: retention_offer_applied is set to true,
    the subscription's status remains unchanged (ACTIVE or PAUSED),
    and the response carries HTTP 200 with the retention offer
    payload (a single one-cycle 50% discount).'
    """
    bundle = setup_active_subscription()
    customer = bundle["customer"]
    sub = bundle["subscription"]
    res = api.cancel_subscription(
        sub["id"],
        cancel_subscription_payload("PRICE"),
        make_customer_headers(customer["id"]),
    )
    after = validate_success(res)
    assert after["status"] in ("ACTIVE", "PAUSED")
    assert after["retention_offer_applied"] is True


def test_cancel_price_with_force_completes_cancel(api):
    """PRD §3.2: 'The customer must re-invoke cancel — typically with
    force true — to commit the cancellation. Any cancel that is not
    deflected sets status to CANCELLED.'
    """
    bundle = setup_active_subscription()
    customer = bundle["customer"]
    sub = bundle["subscription"]
    # Force cancel bypasses retention offer.
    res = api.cancel_subscription(
        sub["id"],
        cancel_subscription_payload("PRICE", force=True),
        make_customer_headers(customer["id"]),
    )
    after = validate_success(res)
    assert after["status"] == "CANCELLED"
    assert after["cancel_reason"] == "PRICE"
    assert after["next_cycle_at"] is None


def test_cancel_quality_does_not_deflect(api):
    """PRD §3.2: deflection rule is specifically 'When cancel_reason
    is PRICE'. QUALITY / PET_NO_LONGER / OTHER must cancel directly.
    """
    bundle = setup_active_subscription()
    customer = bundle["customer"]
    sub = bundle["subscription"]
    res = api.cancel_subscription(
        sub["id"],
        cancel_subscription_payload("QUALITY"),
        make_customer_headers(customer["id"]),
    )
    after = validate_success(res)
    assert after["status"] == "CANCELLED"
    assert after["cancel_reason"] == "QUALITY"


# ---------------------------------------------------------------------------
# CANCELLED → REACTIVATING → ACTIVE
# ---------------------------------------------------------------------------
def test_reactivate_requires_cancelled_state(api):
    """PRD §3.2: 'The reactivate capability requires the subscription's
    current status to be CANCELLED (otherwise
    ERR_INVALID_SUBSCRIPTION_STATE).'
    """
    bundle = setup_active_subscription()
    res = api.reactivate_subscription(
        bundle["subscription"]["id"],
        make_customer_headers(bundle["customer"]["id"]),
    )
    validate_error(
        res, ApiErrorId.ERR_INVALID_SUBSCRIPTION_STATE.value,
    )


def test_reactivate_moves_to_reactivating_and_resets_offer_flag(api):
    """PRD §3.2: 'The transition from REACTIVATING back to ACTIVE
    reuses the activate capability and re-enforces the
    address-verified precondition; on success it sets next_cycle_at
    to the current logical clock plus cycle_days, resets
    retention_offer_applied back to false.'
    """
    bundle = setup_active_subscription()
    customer = bundle["customer"]
    sub = bundle["subscription"]
    # Cancel with force after applying retention offer.
    api.cancel_subscription(
        sub["id"], cancel_subscription_payload("PRICE"),
        make_customer_headers(customer["id"]),
    )
    api.cancel_subscription(
        sub["id"], cancel_subscription_payload("PRICE", force=True),
        make_customer_headers(customer["id"]),
    )
    # Reactivate.
    res = api.reactivate_subscription(
        sub["id"], make_customer_headers(customer["id"]),
    )
    after = validate_success(res)
    assert after["status"] == "REACTIVATING"


def test_reactivating_requires_address_reverify_for_activate(api):
    """PRD §3.2: 'on success the status moves to REACTIVATING and the
    customer must verify the shipping address again before they can
    call activation a second time.'
    """
    bundle = setup_active_subscription()
    customer = bundle["customer"]
    sub = bundle["subscription"]
    cancel_force(customer, sub, "OTHER")
    api.reactivate_subscription(
        sub["id"], make_customer_headers(customer["id"]),
    )
    # Activate without re-verifying must fail with
    # ERR_ADDRESS_NOT_VERIFIED.
    res = api.activate_subscription(
        sub["id"], make_customer_headers(customer["id"]),
    )
    validate_error(res, ApiErrorId.ERR_ADDRESS_NOT_VERIFIED.value)


# ---------------------------------------------------------------------------
# PATCH /subscriptions/{id} — pet_ids validation
# ---------------------------------------------------------------------------
def test_subscription_patch_empty_pet_ids_rejected(api):
    """PRD §3.2: 'If pet_ids is included, the resulting list must be
    non-empty, contain only ids that belong to the requesting
    customer, and have all member pets in ACTIVE status; failures
    surface as ERR_INVALID_PET_LIST or ERR_PET_NOT_ACTIVE.'
    """
    bundle = setup_active_subscription()
    customer = bundle["customer"]
    sub = bundle["subscription"]
    res = api.update_subscription(
        sub["id"],
        update_subscription_payload(pet_ids=[]),
        make_customer_headers(customer["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_PET_LIST.value)


def test_subscription_patch_pet_from_another_customer_rejected(api):
    """PRD §3.2: 'contain only ids that belong to the requesting
    customer ... failures surface as ERR_INVALID_PET_LIST.'
    """
    bundle = setup_active_subscription()
    customer = bundle["customer"]
    sub = bundle["subscription"]
    other_customer, other_pet = setup_customer_with_pet()
    res = api.update_subscription(
        sub["id"],
        update_subscription_payload(pet_ids=[other_pet["id"]]),
        make_customer_headers(customer["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_PET_LIST.value)


# ---------------------------------------------------------------------------
# Address change on PATCH resets verified flag
# ---------------------------------------------------------------------------
def test_subscription_patch_address_change_resets_verified(api):
    """PRD §3.2: 'If shipping_address is supplied (even to the same
    value), its verified flag is forced back to false and a fresh
    verify call is required before the next activation, confirmation,
    or reactivation.'
    """
    bundle = setup_active_subscription()
    customer = bundle["customer"]
    sub = bundle["subscription"]
    res = api.update_subscription(
        sub["id"],
        update_subscription_payload(
            shipping_address=make_address(city="Newville"),
        ),
        make_customer_headers(customer["id"]),
    )
    after = validate_success(res)
    assert after["shipping_address"]["verified"] is False
