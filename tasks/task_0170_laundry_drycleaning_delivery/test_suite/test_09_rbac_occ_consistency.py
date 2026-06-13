"""RBAC, optimistic concurrency, version increment, and consistency corners."""
import test_helpers as th


# --------------------------------------------------------------------------
# rbac
# --------------------------------------------------------------------------
def test_customer_cannot_pickup_order(api):
    """PRD §2.1: "When a well-identified caller attempts an operation their role
    is not permitted to perform, the request is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS`."
    PRD §4: pickup is authorized for DispatchAgent only.

    Design: Corner/rbac/customer_cannot_pickup_order
    """
    customer, pickup, delivery, order, _ = th.create_order_with_garments(
        garments=[{"service_type": "WASH_FOLD", "declared_weight_grams": 2000}])
    th.schedule_order(order, customer)
    resp = api.pickup_order(order["id"], th.make_customer_headers(customer["id"]))
    th.validate_error(resp, "ERR_INSUFFICIENT_PERMISSIONS", 403)


def test_customer_cannot_act_on_other_customers_order(api):
    """PRD §2.1: "An attempt by a `Customer` to act on a resource they do not own
    is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Customer B schedules Customer A's order.

    Design: Corner/rbac/customer_cannot_act_on_other_customers_order
    """
    cust_a = th.create_customer(zone_code="Z1")
    cust_b = th.create_customer(zone_code="Z1")
    pickup = th.create_pickup_window(zone_code="Z1", stop_capacity=5)
    delivery = th.create_delivery_window(zone_code="Z1", stop_capacity=5)
    _, _, _, order, _ = th.create_order_with_garments(
        customer=cust_a, pickup=pickup, delivery=delivery,
        garments=[{"service_type": "WASH_FOLD", "declared_weight_grams": 2000}])
    resp = api.schedule_order(order["id"], th.make_customer_headers(cust_b["id"]))
    th.validate_error(resp, "ERR_NOT_RESOURCE_OWNER", 403)


def test_missing_auth_header_rejected(api):
    """PRD §2.1: "When either header is missing or malformed, the request is
    rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    A request with no user-context headers at all.

    Design: Corner/rbac/missing_auth_header_rejected
    """
    resp = api._request("GET", "/subscription-plans", headers={})
    th.validate_error(resp, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400)


# --------------------------------------------------------------------------
# cross_cutting_complexity_layers (OCC + versioning)
# --------------------------------------------------------------------------
def test_occ_stale_order_version_on_claim_create(api):
    """PRD §2.6: "When `expected_order_version` does not equal the order's current
    `version`, the create is rejected with `ERR_STALE_ORDER_VERSION` at HTTP 412."

    Read the order version, then a mark-lost bumps it; a claim carrying the stale
    pre-bump version is rejected.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_order_version_on_claim_create
    """
    customer, pickup, delivery, order, garments = th.order_in_processing(
        garments=[{"service_type": "DRY_CLEAN", "declared_piece_count": 1}],
        actuals=[{"actual_piece_count": 1}],
    )
    stale_version = th.get_order(order["id"], customer["id"])["version"]
    th.mark_lost(order, garments[0])  # advances Order.version
    payload = th.create_claim_payload(
        order["id"], "GARMENT", 5000, stale_version, garment_id=garments[0]["id"])
    resp = api.create_claim(payload, th.make_customer_headers(customer["id"]))
    th.validate_error(resp, "ERR_STALE_ORDER_VERSION", 412)


def test_occ_stale_subscription_version_on_change_plan(api):
    """PRD §2.6: "When `expected_subscription_version` does not equal the
    subscription's current `version`, the plan change is rejected with
    `ERR_STALE_SUBSCRIPTION_VERSION` at HTTP 412."

    A first change-plan bumps the version; a second change-plan carrying the stale
    pre-bump version is rejected.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_subscription_version_on_change_plan
    """
    plan_a = th.create_plan(tier="LITE", monthly_fee_cents=3000, included_wash_fold_grams=2000,
                            overage_rate_cents_per_kg=350, dryclean_discount_pct=0.10)
    plan_b = th.create_plan(tier="PLUS", monthly_fee_cents=6000, included_wash_fold_grams=5000,
                            overage_rate_cents_per_kg=300, dryclean_discount_pct=0.25)
    plan_c = th.create_plan(tier="PREMIUM", monthly_fee_cents=9000, included_wash_fold_grams=8000,
                            overage_rate_cents_per_kg=250, dryclean_discount_pct=0.40)
    customer = th.create_customer(zone_code="Z1")
    sub = th.create_subscription(customer["id"], plan_a["id"])
    stale_version = sub["version"]
    th.validate_success(api.change_subscription_plan(
        sub["id"], {"plan_id": plan_b["id"], "expected_subscription_version": stale_version},
        th.make_customer_headers(customer["id"])))
    resp = api.change_subscription_plan(
        sub["id"], {"plan_id": plan_c["id"], "expected_subscription_version": stale_version},
        th.make_customer_headers(customer["id"]))
    th.validate_error(resp, "ERR_STALE_SUBSCRIPTION_VERSION", 412)


def test_version_increments_on_mutation(api):
    """PRD §2.4: "a `version`, an integer that begins at its initial value on
    creation and increments by one with every modification."

    Order.version increments by one after the schedule mutation.

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_mutation
    """
    customer, pickup, delivery, order, _ = th.create_order_with_garments(
        garments=[{"service_type": "WASH_FOLD", "declared_weight_grams": 2000}])
    create_version = order["version"]
    scheduled = th.validate_success(
        api.schedule_order(order["id"], th.make_customer_headers(customer["id"])))
    assert scheduled["version"] == create_version + 1, \
        f"version increments by one on mutation: {create_version}->{scheduled['version']}"


# --------------------------------------------------------------------------
# consistency_model
# --------------------------------------------------------------------------
def test_schedule_estimate_visible_in_same_response(api):
    """PRD §3.3: "the order's `estimate_total_cents` is set to the sum of the
    estimate line prices of all garments on the order"
    PRD §3.3: "For a `DRY_CLEAN` garment, the base is the piece count times 900
    cents per piece."

    The schedule response immediately reflects estimate_total_cents (2 DRY_CLEAN
    pieces -> 1800), no read-after-write lag.

    Design: Corner/consistency_model/schedule_estimate_visible_same_response
    """
    customer, pickup, delivery, order, _ = th.create_order_with_garments(
        garments=[{"service_type": "DRY_CLEAN", "declared_piece_count": 2}])
    scheduled = th.validate_success(
        api.schedule_order(order["id"], th.make_customer_headers(customer["id"])))
    assert scheduled["estimate_total_cents"] == 1800, \
        f"schedule response shows estimate 1800, got {scheduled['estimate_total_cents']}"
