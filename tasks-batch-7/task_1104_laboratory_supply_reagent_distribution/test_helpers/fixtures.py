"""Composite setup helpers.

Every helper builds its preconditions from scratch through the public API
(the test runner restarts the server before every test, so each test starts
against an empty database). Setup calls use the lenient get_success_data()
validator so failures surface as clear "Setup step failed" errors.

Identity threading: after creating a CustomerAccount, every Customer-role
call uses make_customer_headers(customer["id"]) because ownership checks
compare X-User-ID against the resource's customer_id.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client as _default_api
from .factories import (
    create_agreement_payload,
    create_customer_payload,
    create_job_payload,
    create_kit_payload,
    create_lot_payload,
    create_order_payload,
    create_product_payload,
    create_recall_payload,
    create_shipment_payload,
    create_standing_order_payload,
    create_warehouse_payload,
    create_zone_payload,
    order_line,
)
from .test_users import TEST_USERS, make_customer_headers

OPS = TEST_USERS["ops_admin_headers"]
CATALOG = TEST_USERS["catalog_manager_headers"]
CLERK = TEST_USERS["inventory_clerk_headers"]
QUALITY = TEST_USERS["quality_manager_headers"]
ACCOUNTS = TEST_USERS["account_manager_headers"]


# ---------------------------------------------------------------------------
# Tier 0: single-entity creators (return parsed response data)
# ---------------------------------------------------------------------------

def make_warehouse(api=None, **overrides):
    api = api or _default_api
    resp = api.create_warehouse(create_warehouse_payload(**overrides), OPS)
    return get_success_data(resp)


def make_zone(api=None, warehouse_id=None, **overrides):
    api = api or _default_api
    resp = api.create_zone(
        create_zone_payload(warehouse_id=warehouse_id, **overrides), OPS
    )
    return get_success_data(resp)


def make_product(api=None, **overrides):
    api = api or _default_api
    resp = api.create_product(create_product_payload(**overrides), CATALOG)
    return get_success_data(resp)


def make_customer(api=None, **overrides):
    api = api or _default_api
    resp = api.create_customer(create_customer_payload(**overrides), ACCOUNTS)
    return get_success_data(resp)


def make_lot(api=None, product_id=None, warehouse_id=None, storage_zone_id=None, **overrides):
    api = api or _default_api
    resp = api.create_lot(
        create_lot_payload(
            product_id=product_id,
            warehouse_id=warehouse_id,
            storage_zone_id=storage_zone_id,
            **overrides,
        ),
        CLERK,
    )
    return get_success_data(resp)


def make_order(api=None, customer_id=None, warehouse_id=None, lines=None, **overrides):
    """Create a DRAFT order as its owning customer. Returns the order data."""
    api = api or _default_api
    resp = api.create_order(
        create_order_payload(
            customer_id=customer_id, warehouse_id=warehouse_id, lines=lines or [], **overrides
        ),
        make_customer_headers(customer_id),
    )
    return get_success_data(resp)


def submit_order(api, order_id, customer_id):
    resp = api.submit_order(order_id, make_customer_headers(customer_id))
    return get_success_data(resp)


def make_standing_order(api=None, **overrides):
    api = api or _default_api
    payload = create_standing_order_payload(**overrides)
    resp = api.create_standing_order(payload, make_customer_headers(payload["customer_id"]))
    return get_success_data(resp)


def make_agreement(api=None, **overrides):
    api = api or _default_api
    resp = api.create_agreement(create_agreement_payload(**overrides), ACCOUNTS)
    return get_success_data(resp)


def make_recall(api=None, **overrides):
    api = api or _default_api
    resp = api.create_recall(create_recall_payload(**overrides), QUALITY)
    return get_success_data(resp)


def make_kit(api=None, **overrides):
    api = api or _default_api
    resp = api.create_kit(create_kit_payload(**overrides), CATALOG)
    return get_success_data(resp)


def make_job(api=None, **overrides):
    api = api or _default_api
    resp = api.create_job(create_job_payload(**overrides), CLERK)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: read helpers
# ---------------------------------------------------------------------------

def get_order(api, order_id):
    return get_success_data(api.get_order(order_id, OPS))


def get_order_lines(api, order_id):
    data, _meta = validate_paginated(api.list_order_lines(OPS, params={"order_id": order_id}))
    return data


def get_line_reservations(api, order_line_id):
    data, _meta = validate_paginated(
        api.list_reservations(OPS, params={"order_line_id": order_line_id})
    )
    return data


def get_lot(api, lot_id):
    return get_success_data(api.get_lot(lot_id, OPS))


def get_customer(api, customer_id):
    return get_success_data(api.get_customer(customer_id, ACCOUNTS))


def get_shipment(api, shipment_id):
    return get_success_data(api.get_shipment(shipment_id, OPS))


def get_excursion(api, excursion_id):
    return get_success_data(api.get_excursion(excursion_id, OPS))


# ---------------------------------------------------------------------------
# Tier 2: cold-chain order chain (warehouse -> zone -> product -> customer
# -> lot -> order). The workhorse for shipment/excursion/cascade tests.
# ---------------------------------------------------------------------------

COLD_CHAIN_PRODUCT = {
    "sku": "RG-100",
    "name": "Enzyme Mix",
    "storage_requirement": "REFRIGERATED_2_8",
    "hazard_class": "NON_HAZARDOUS",
    "max_qty_per_shipment": 500,
    "unit_price_cents": 20000,
    "requires_cold_chain": True,
    "shelf_life_days": 60,
    "min_remaining_shelf_life_days": 7,
}

COLD_CHAIN_CUSTOMER = {
    "name": "Lab Alpha",
    "credit_limit_cents": 10000000,
    "hazmat_endorsement": "FULL",
    "cold_chain_certified": True,
}


def setup_cold_chain_order(
    api,
    quantity=2,
    lot_quantity=100,
    shipping_service="EXPRESS",
    requested_ship_date="2026-05-10",
    fulfillment_mode="ANY",
    product_overrides=None,
    customer_overrides=None,
):
    """Warehouse + REFRIGERATED_2_8 FEFO zone + cold-chain product (20000 cents)
    + FULL cold-chain-certified customer + one lot + one submitted order.

    Returns a dict with keys: warehouse, zone, product, customer, lot, order
    (order is the post-submit representation).
    """
    warehouse = make_warehouse(api, name="WH-NE", region_code="US-NE", hazmat_certified=True)
    zone = make_zone(
        api,
        warehouse["id"],
        zone_class="REFRIGERATED_2_8",
        capacity_units=1000,
        rotation_policy="FEFO",
    )
    product = make_product(api, **dict(COLD_CHAIN_PRODUCT, **(product_overrides or {})))
    customer = make_customer(api, **dict(COLD_CHAIN_CUSTOMER, **(customer_overrides or {})))
    lot = make_lot(
        api,
        product["id"],
        warehouse["id"],
        zone["id"],
        quantity_received=lot_quantity,
        manufacture_date="2026-04-01",
    )
    order = make_order(
        api,
        customer["id"],
        warehouse["id"],
        [order_line(product["id"], quantity, fulfillment_mode)],
        shipping_service=shipping_service,
        requested_ship_date=requested_ship_date,
    )
    submitted = submit_order(api, order["id"], customer["id"])
    return {
        "warehouse": warehouse,
        "zone": zone,
        "product": product,
        "customer": customer,
        "lot": lot,
        "order": submitted,
    }


def add_shipment(api, ctx, coolant_type="DRY_ICE", coolant_units=2, declared_weight_grams=3000):
    """Create a shipment for the context's ALLOCATED order. Returns shipment."""
    resp = api.create_shipment(
        create_shipment_payload(
            order_id=ctx["order"]["id"],
            coolant_type=coolant_type,
            coolant_units=coolant_units,
            declared_weight_grams=declared_weight_grams,
        ),
        CLERK,
    )
    return get_success_data(resp)


def pack(ctx, api, shipment_id):
    return get_success_data(api.pack_shipment(shipment_id, CLERK))


def dispatch(ctx, api, shipment_id, actual_weight_grams=3000):
    return get_success_data(
        api.dispatch_shipment(shipment_id, {"actual_weight_grams": actual_weight_grams}, CLERK)
    )


def setup_packed_shipment(api, **chain_kwargs):
    """Cold-chain chain through ALLOCATED order + CREATED shipment + pack."""
    ctx = setup_cold_chain_order(api, **{
        k: v for k, v in chain_kwargs.items()
        if k in ("quantity", "lot_quantity", "shipping_service", "requested_ship_date",
                 "fulfillment_mode", "product_overrides", "customer_overrides")
    })
    ctx["shipment"] = add_shipment(
        api,
        ctx,
        coolant_type=chain_kwargs.get("coolant_type", "DRY_ICE"),
        coolant_units=chain_kwargs.get("coolant_units", 2),
        declared_weight_grams=chain_kwargs.get("declared_weight_grams", 3000),
    )
    pack(ctx, api, ctx["shipment"]["id"])
    return ctx


def setup_in_transit_shipment(api, actual_weight_grams=3000, **chain_kwargs):
    """Cold-chain chain through dispatch: shipment IN_TRANSIT, order SHIPPED,
    invoice posted to the customer's outstanding balance."""
    ctx = setup_packed_shipment(api, **chain_kwargs)
    ctx["shipment"] = dispatch(ctx, api, ctx["shipment"]["id"], actual_weight_grams)
    return ctx


def setup_open_excursion(api, temp_celsius=12.5, duration_minutes=90, actual_weight_grams=3000,
                         **chain_kwargs):
    """Chain through IN_TRANSIT plus one out-of-band reading: excursion OPEN,
    shipment EXCURSION_HOLD. Adds 'excursion_id' and 'reading' keys."""
    ctx = setup_in_transit_shipment(api, actual_weight_grams, **chain_kwargs)
    reading = get_success_data(
        api.record_temperature(
            ctx["shipment"]["id"],
            {"temp_celsius": temp_celsius, "duration_minutes": duration_minutes},
            CLERK,
        )
    )
    ctx["reading"] = reading
    ctx["excursion_id"] = reading["excursion_id"]
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: ambient simple chain (cheap product, no cold chain) for
# allocation / pricing / reservation tests.
# ---------------------------------------------------------------------------

def setup_ambient_order(
    api,
    quantity=8,
    lot_quantity=20,
    unit_price_cents=1000,
    fulfillment_mode="ANY",
    customer_overrides=None,
    product_overrides=None,
    shipping_service="STANDARD",
    requested_ship_date="2026-05-10",
    submit=True,
):
    """Warehouse + AMBIENT FEFO zone + AMBIENT NON_HAZARDOUS product +
    customer + one lot + one order (submitted unless submit=False)."""
    warehouse = make_warehouse(api, name="WH-NE", region_code="US-NE", hazmat_certified=True)
    zone = make_zone(api, warehouse["id"], zone_class="AMBIENT", capacity_units=500)
    product = make_product(
        api,
        **dict(
            {
                "sku": "CH-1000",
                "name": "Assay Vial",
                "storage_requirement": "AMBIENT",
                "hazard_class": "NON_HAZARDOUS",
                "max_qty_per_shipment": 500,
                "unit_price_cents": unit_price_cents,
                "requires_cold_chain": False,
                "shelf_life_days": 365,
                "min_remaining_shelf_life_days": 7,
            },
            **(product_overrides or {}),
        )
    )
    customer = make_customer(api, **dict({"name": "Lab Mu", "credit_limit_cents": 10000000},
                                         **(customer_overrides or {})))
    lot = make_lot(
        api,
        product["id"],
        warehouse["id"],
        zone["id"],
        quantity_received=lot_quantity,
        manufacture_date="2026-01-15",
    )
    order = make_order(
        api,
        customer["id"],
        warehouse["id"],
        [order_line(product["id"], quantity, fulfillment_mode)],
        shipping_service=shipping_service,
        requested_ship_date=requested_ship_date,
    )
    ctx = {
        "warehouse": warehouse,
        "zone": zone,
        "product": product,
        "customer": customer,
        "lot": lot,
        "order": order,
    }
    if submit:
        ctx["order"] = submit_order(api, order["id"], customer["id"])
    return ctx
