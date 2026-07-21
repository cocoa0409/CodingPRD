"""Subscription boxes: shipment gating, keep-decision guards, OCC on curation,
version bumps, reservation on curation, and shared-role curation.

Queue A (Difficulty): ship_blocked_by_nonactive_subscription.
Queue B (Corner): keep-before-ship, keep-not-subset, OCC stale version,
version increment, curation reserves inventory, FitSpecialist may curate.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    make_customer_headers, make_fit_specialist_headers,
    register_customer, create_specialist, create_product, create_variant,
    create_subscription, set_subscription_status,
    setup_curated_box,
    curate_shipment_payload,
)

SM = TEST_USERS["store_manager_headers"]


# ---------------------------------------------------------------------------
# ship_blocked_by_nonactive_subscription (Queue A)
# ---------------------------------------------------------------------------
def test_ship_rejected_when_subscription_paused(api):
    """PRD §3.6: "Shipping the box, performed by a store manager, moves `CURATED` to
    `SHIPPED`; it requires that the shipment currently be `CURATED` and that the
    parent subscription still be `ACTIVE`, else `ERR_SUBSCRIPTION_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/ship_blocked_by_nonactive_subscription
    """
    box = setup_curated_box(api, plan_tier="SIGNATURE", variant_overrides={"inventory_on_hand": 20})
    set_subscription_status(api, box["subscription"]["id"], box["customer"]["id"], "PAUSED")
    resp = api.ship_shipment(box["shipment"]["id"], SM)
    validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE.value)


def test_ship_blocked_by_pause_leaves_box_curated(api):
    """PRD §3.6: "Shipping the box, performed by a store manager, moves `CURATED` to
    `SHIPPED`; it requires that the shipment currently be `CURATED` and that the
    parent subscription still be `ACTIVE`, else `ERR_SUBSCRIPTION_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/ship_blocked_by_nonactive_subscription
    """
    box = setup_curated_box(api, plan_tier="SIGNATURE", variant_overrides={"inventory_on_hand": 20})
    set_subscription_status(api, box["subscription"]["id"], box["customer"]["id"], "PAUSED")
    api.ship_shipment(box["shipment"]["id"], SM)
    shipment = validate_success(api.get_shipment(box["shipment"]["id"], SM))
    assert shipment["status"] == "CURATED"


# ---------------------------------------------------------------------------
# Corner instances
# ---------------------------------------------------------------------------
def test_keep_decisions_before_ship_returns_invalid_state(api):
    """PRD §3.6: "A box transition requested from a disallowed state is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/box_keep_decisions_before_ship_returns_invalid_state
    """
    box = setup_curated_box(api, plan_tier="ESSENTIALS", variant_overrides={"inventory_on_hand": 20})
    resp = api.keep_decisions(
        box["shipment"]["id"], {"kept_variant_ids": [box["variants"][0]["id"]]},
        make_customer_headers(box["customer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    shipment = validate_success(api.get_shipment(box["shipment"]["id"], SM))
    assert shipment["status"] == "CURATED"


def test_keep_decisions_with_foreign_variant_returns_invalid_keep_selection(api):
    """PRD §3.6: "the submitted `kept_variant_ids` must be a subset of the box's item
    variant ids, else `ERR_INVALID_KEEP_SELECTION`, and the selection is stored on
    the shipment."

    Design: Corner/validations/keep_selection_not_subset_returns_error
    """
    box = setup_curated_box(api, plan_tier="ESSENTIALS", variant_overrides={"inventory_on_hand": 20})
    foreign = create_variant(api, box["product"]["id"], size_code=26, color="Navy",
                             inventory_on_hand=20)
    validate_success(api.ship_shipment(box["shipment"]["id"], SM))
    resp = api.keep_decisions(
        box["shipment"]["id"], {"kept_variant_ids": [foreign["id"]]},
        make_customer_headers(box["customer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_KEEP_SELECTION.value)


def test_curate_with_stale_subscription_version_returns_stale(api):
    """PRD §2.5: "If that value does not equal the subscription's current `version`,
    the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting/occ_stale_subscription_version_on_curate_returns_412
    """
    customer = register_customer(api)
    product = create_product(api)
    variant = create_variant(api, product["id"], size_code=22, inventory_on_hand=20)
    subscription = create_subscription(api, customer["id"], "SIGNATURE")
    observed_version = subscription["version"]
    # Pausing advances the version, making observed_version stale.
    set_subscription_status(api, subscription["id"], customer["id"], "PAUSED")
    resp = api.create_shipment(
        subscription["id"],
        curate_shipment_payload(observed_version, [variant["id"]]),
        SM,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)


def test_subscription_status_change_increments_version(api):
    """PRD §3.6: "Every one of these status changes increments the subscription's
    `version` by 1."

    Design: Corner/cross_cutting/subscription_status_change_increments_version
    """
    customer = register_customer(api)
    subscription = create_subscription(api, customer["id"], "ESSENTIALS")
    assert subscription["version"] == 1
    updated = set_subscription_status(api, subscription["id"], customer["id"], "PAUSED")
    assert updated["version"] == 2
    assert updated["status"] == "PAUSED"


def test_curation_reserves_one_unit_per_item(api):
    """PRD §3.6: "The shipment is created in `CURATED` status, each item's variant has
    its `inventory_reserved` raised by 1 (one unit reserved per item), and the parent
    subscription's `version` is incremented by 1."

    Design: Corner/cross_cutting/box_curation_reserves_inventory
    """
    box = setup_curated_box(api, plan_tier="ESSENTIALS", variant_overrides={"inventory_on_hand": 20})
    variant = validate_success(api.get_variant(box["variants"][0]["id"], SM))
    assert variant["inventory_reserved"] == 1
    assert variant["inventory_available"] == 19


def test_fit_specialist_can_curate_box_shipment(api):
    """PRD §3.6: "A fit specialist or store manager curates a box against a
    subscription by supplying `expected_subscription_version` — subject to the
    optimistic-concurrency rule of §2.5 — and `item_variant_ids`, the SKUs selected
    for this cycle."

    Design: Corner/rbac/fitspecialist_can_curate_box_shipment
    """
    customer = register_customer(api)
    specialist = create_specialist(api, specialties=["ADAPTIVE"])
    product = create_product(api)
    variant = create_variant(api, product["id"], size_code=24, inventory_on_hand=20)
    subscription = create_subscription(api, customer["id"], "SIGNATURE")
    resp = api.create_shipment(
        subscription["id"],
        curate_shipment_payload(subscription["version"], [variant["id"]]),
        make_fit_specialist_headers(specialist["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "CURATED"
