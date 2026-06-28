"""Composite setup helpers for multi-step test prerequisites.

The server database is reset before every test, so each fixture builds its preconditions
from scratch using only PRD-declared endpoints. Fixtures use ``get_success_data`` (the lenient
2xx validator) so a setup misstep surfaces as a clear "setup failed" rather than a confusing
downstream assertion error.

Identity threading: PetParent is entity-backed on Account, so every ownership-gated call uses
``make_pet_parent_headers(account_id)`` with the actual account id — never the shared constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    register_account_payload,
    create_recipe_payload,
    create_pet_payload,
    create_weight_log_payload,
    create_subscription_payload,
    generate_order_payload,
    settle_charge_payload,
)
from .test_users import TEST_USERS, make_pet_parent_headers
from .constants import DEFAULT_CLOCK

# Convenient operator-header aliases.
VET = TEST_USERS["nutrition_vet_headers"]
BILLING = TEST_USERS["billing_admin_headers"]
OPS = TEST_USERS["fulfillment_ops_headers"]
ANON = TEST_USERS["anonymous_headers"]


# --------------------------------------------------------------------------- #
# Clock                                                                        #
# --------------------------------------------------------------------------- #
def set_clock(instant=DEFAULT_CLOCK, headers=BILLING):
    """Set the logical clock to an absolute UTC instant. Any authenticated role may do this."""
    return get_success_data(api_client.set_clock(instant, headers))


# --------------------------------------------------------------------------- #
# Tier 1: primitives                                                           #
# --------------------------------------------------------------------------- #
def register_account(email, country_code="US", referral_code=None, full_name="Holder"):
    """Register an account (Anonymous). Returns the Account dict."""
    extra = {"country_code": country_code}
    if referral_code is not None:
        extra["referral_code"] = referral_code
    return get_success_data(
        api_client.register_account(
            register_account_payload(email, full_name=full_name, **extra), ANON
        )
    )


def create_pet(account_id, **overrides):
    """Create a pet under account_id (ownership-gated -> account-id headers)."""
    headers = make_pet_parent_headers(account_id)
    return get_success_data(
        api_client.create_pet(create_pet_payload(account_id, **overrides), headers)
    )


def create_published_recipe(**overrides):
    """Create a recipe then publish it. Returns the published Recipe dict.

    Recipes default to shipping to both US and CA so the activation region gate
    (PRD §3.5: the account's country_code must appear in availability_regions) is
    satisfied for the suite's default US/CA accounts; callers override to test the gate.
    """
    overrides.setdefault("availability_regions", ["US", "CA"])
    rec = get_success_data(api_client.create_recipe(create_recipe_payload(**overrides), VET))
    return get_success_data(api_client.publish_recipe(rec["id"], VET))


def create_draft_recipe(**overrides):
    """Create a recipe in DRAFT (not published)."""
    overrides.setdefault("availability_regions", ["US", "CA"])
    return get_success_data(api_client.create_recipe(create_recipe_payload(**overrides), VET))


def create_subscription(account_id, pet_id, recipe_id, **overrides):
    """Create a DRAFT subscription (ownership-gated)."""
    headers = make_pet_parent_headers(account_id)
    return get_success_data(
        api_client.create_subscription(
            create_subscription_payload(account_id, pet_id, recipe_id, **overrides), headers
        )
    )


def record_weight(account_id, pet_id, weight_kg, effective_date=None):
    """Record a weight log (ownership-gated). Returns the WeightLog dict."""
    headers = make_pet_parent_headers(account_id)
    extra = {}
    if effective_date is not None:
        extra["effective_date"] = effective_date
    return get_success_data(
        api_client.create_weight_log(
            create_weight_log_payload(pet_id, weight_kg, **extra), headers
        )
    )


# --------------------------------------------------------------------------- #
# Tier 2: account + pet + published recipe                                     #
# --------------------------------------------------------------------------- #
def setup_account_pet_recipe(
    email,
    country_code="US",
    pet_overrides=None,
    recipe_overrides=None,
    clock=DEFAULT_CLOCK,
):
    """Clock + account + pet + published recipe. Returns (account, pet, recipe)."""
    set_clock(clock)
    account = register_account(email, country_code=country_code)
    pet = create_pet(account["id"], **(pet_overrides or {}))
    recipe = create_published_recipe(**(recipe_overrides or {}))
    return account, pet, recipe


# --------------------------------------------------------------------------- #
# Tier 3: active subscription                                                  #
# --------------------------------------------------------------------------- #
def setup_active_subscription(
    email,
    country_code="US",
    pet_overrides=None,
    recipe_overrides=None,
    sub_overrides=None,
    clock=DEFAULT_CLOCK,
):
    """Clock + account + pet + published recipe + DRAFT subscription -> ACTIVE.

    Returns (account, pet, recipe, subscription) with the subscription freshly ACTIVE
    (version reflects the activation bump).
    """
    account, pet, recipe = setup_account_pet_recipe(
        email,
        country_code=country_code,
        pet_overrides=pet_overrides,
        recipe_overrides=recipe_overrides,
        clock=clock,
    )
    headers = make_pet_parent_headers(account["id"])
    sub = create_subscription(account["id"], pet["id"], recipe["id"], **(sub_overrides or {}))
    sub = get_success_data(api_client.activate_subscription(sub["id"], headers))
    return account, pet, recipe, sub


def generate_order(subscription_id, expected_version, headers=BILLING):
    """Generate the next cycle order. Returns the Order dict."""
    return get_success_data(
        api_client.generate_order(
            subscription_id, generate_order_payload(expected_version), headers
        )
    )


def setup_active_subscription_with_order(
    email,
    country_code="US",
    pet_overrides=None,
    recipe_overrides=None,
    sub_overrides=None,
    clock=DEFAULT_CLOCK,
):
    """Active subscription + one freshly generated SCHEDULED order.

    Returns (account, pet, recipe, subscription, order).
    """
    account, pet, recipe, sub = setup_active_subscription(
        email,
        country_code=country_code,
        pet_overrides=pet_overrides,
        recipe_overrides=recipe_overrides,
        sub_overrides=sub_overrides,
        clock=clock,
    )
    order = generate_order(sub["id"], sub["version"])
    return account, pet, recipe, sub, order


# --------------------------------------------------------------------------- #
# Tier 4: charge / settle lifecycle                                           #
# --------------------------------------------------------------------------- #
def charge_order(order_id, headers=BILLING):
    """SCHEDULED -> CHARGING. Returns the Order dict with finalized billing fields."""
    return get_success_data(api_client.charge_order(order_id, headers))


def settle_order(order_id, outcome, headers=BILLING):
    """Settle a CHARGING order. outcome in {SUCCEEDED, DECLINED}. Returns the Order dict."""
    return get_success_data(
        api_client.settle_charge(order_id, settle_charge_payload(outcome), headers)
    )


def setup_paid_order(
    email,
    country_code="US",
    pet_overrides=None,
    recipe_overrides=None,
    sub_overrides=None,
    clock=DEFAULT_CLOCK,
):
    """Active subscription -> generate order -> charge -> settle SUCCEEDED (PAID).

    Returns (account, pet, recipe, subscription, order_paid). A PENDING Shipment now exists.
    """
    account, pet, recipe, sub, order = setup_active_subscription_with_order(
        email,
        country_code=country_code,
        pet_overrides=pet_overrides,
        recipe_overrides=recipe_overrides,
        sub_overrides=sub_overrides,
        clock=clock,
    )
    charge_order(order["id"])
    paid = settle_order(order["id"], "SUCCEEDED")
    return account, pet, recipe, sub, paid


def get_shipment_for_order(order_id, headers=OPS):
    """Return the single PENDING Shipment created when the order was PAID."""
    data, _meta = _list(api_client.list_shipments(headers, params={"order_id": order_id}))
    assert data, f"expected a shipment for order {order_id}"
    return data[0]


def setup_dispatched_shipment(
    email,
    transit_days=None,
    clock=DEFAULT_CLOCK,
):
    """Paid order -> its PENDING shipment -> (optional transit patch) -> DISPATCHED.

    Returns (account, subscription, order_paid, shipment_dispatched). The clock is left at
    ``clock`` so delivery-window tests can advance from there.
    """
    account, pet, recipe, sub, paid = setup_paid_order(
        email, recipe_overrides={"availability_regions": ["US"]}, clock=clock
    )
    shipment = get_shipment_for_order(paid["id"])
    if transit_days is not None:
        from .factories import update_shipment_payload

        shipment = get_success_data(
            api_client.update_shipment(
                shipment["id"], update_shipment_payload(transit_days), OPS
            )
        )
    shipment = get_success_data(api_client.dispatch_shipment(shipment["id"], OPS))
    return account, sub, paid, shipment


# --------------------------------------------------------------------------- #
# Referral pairs                                                              #
# --------------------------------------------------------------------------- #
def setup_referral_pair(referrer_email, referred_email, clock=DEFAULT_CLOCK):
    """Referrer R (organic) + referred F registered with R's code.

    Returns (referrer, referred). Two PENDING SIGNUP referral-credit rows now exist.
    """
    set_clock(clock)
    referrer = register_account(referrer_email, full_name="R")
    referred = register_account(
        referred_email, full_name="F", referral_code=referrer["referral_code"]
    )
    return referrer, referred


def setup_referred_with_active_subscription(referrer_email, referred_email, clock=DEFAULT_CLOCK):
    """Referral pair + referred F has an ACTIVE subscription (no PAID order yet).

    Returns (referrer, referred, pet, recipe, subscription).
    """
    referrer, referred = setup_referral_pair(referrer_email, referred_email, clock=clock)
    pet = create_pet(referred["id"])
    recipe = create_published_recipe()
    headers = make_pet_parent_headers(referred["id"])
    sub = create_subscription(referred["id"], pet["id"], recipe["id"])
    sub = get_success_data(api_client.activate_subscription(sub["id"], headers))
    return referrer, referred, pet, recipe, sub


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #
def _list(response):
    """Extract (data_list, meta) from a list response without enforcing a strict envelope."""
    body = response.json()
    return body.get("data", []), body.get("meta", {})


def get_subscription_version(subscription_id, headers=BILLING):
    """Read the subscription's current version."""
    sub = get_success_data(api_client.get_subscription(subscription_id, headers))
    return sub["version"]
