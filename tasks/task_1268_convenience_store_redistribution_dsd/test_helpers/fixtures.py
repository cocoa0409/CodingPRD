"""Composite setup helpers (multi-step fixtures).

Every test starts against an empty DB (the runner restarts the server before
each test), so fixtures build their full preconditions from scratch using
only PRD-declared endpoints.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_delivery_manifest_payload,
    create_fuel_surcharge_rate_payload,
    create_order_guide_payload,
    create_product_payload,
    create_promo_event_payload,
    create_purchase_order_payload,
    create_retailer_payload,
    create_tax_stamp_supply_payload,
    order_line,
)
from .test_users import TEST_USERS, make_store_manager_headers

ADMIN = TEST_USERS["admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
DRIVER = TEST_USERS["route_driver_headers"]
CREDIT = TEST_USERS["credit_manager_headers"]


# ---------------------------------------------------------------------------
# Tier 1: retailer + product + guide building blocks
# ---------------------------------------------------------------------------


def setup_retailer(**overrides):
    """Create a retailer; returns (retailer, store_manager_headers)."""
    retailer = get_success_data(api_client.create_retailer(create_retailer_payload(**overrides), ADMIN))
    return retailer, make_store_manager_headers(retailer["id"])


def setup_product(sku="P1", **overrides):
    """Create a product; returns product dict."""
    return get_success_data(api_client.create_product(create_product_payload(sku=sku, **overrides), ADMIN))


def setup_guide(retailer_id, lines, delivery_day="MON", cutoff_hours_before=24):
    """Create an ACTIVE order guide for the retailer; returns guide dict."""
    payload = create_order_guide_payload(
        retailer_id=retailer_id,
        delivery_day=delivery_day,
        cutoff_hours_before=cutoff_hours_before,
        lines=lines,
    )
    return get_success_data(api_client.create_order_guide(payload, SALES))


def setup_retailer_with_guide(product_skus=("P1",), retailer_overrides=None, guide_overrides=None):
    """Retailer + one product per sku + a guide listing them.

    Returns dict with retailer, store_manager headers, products {sku: product},
    and guide."""
    ro = retailer_overrides or {}
    retailer, sm_headers = setup_retailer(**ro)
    products = {}
    for sku in product_skus:
        products[sku] = setup_product(sku=sku)
    lines = [{"product_id": p["id"], "par_cases": 0} for p in products.values()]
    go = {"retailer_id": retailer["id"], "lines": lines}
    go.update(guide_overrides or {})
    guide = setup_guide(**go)
    return {
        "retailer": retailer,
        "sm_headers": sm_headers,
        "products": products,
        "guide": guide,
    }


# ---------------------------------------------------------------------------
# Tier 2: draft order helpers
# ---------------------------------------------------------------------------


def setup_draft_order(product_specs, retailer_overrides=None, promo=None, clock_to="2026-05-20T00:00:00Z"):
    """Build retailer + products + guide + draft order.

    product_specs: list of dicts {sku, cases_qty, split_units_qty, **product_overrides}.
    promo: optional dict {product_sku, promo_type, discount_pct_bps, start_date, end_date}.
    Returns dict with retailer, sm_headers, products, guide, order, order_version.
    """
    product_skus = [s["sku"] for s in product_specs]
    base = setup_retailer_with_guide(product_skus=tuple(product_skus), retailer_overrides=retailer_overrides)
    # Apply product overrides per sku
    products = base["products"]
    for spec in product_specs:
        sku = spec["sku"]
        extra = {k: v for k, v in spec.items() if k not in ("sku", "cases_qty", "split_units_qty")}
        if extra:
            products[sku] = setup_product(sku=f"{sku}-{extra.get('case_pack_units', 'x')}", **extra)
            # Rebuild guide to point at the new product id
            base["guide"] = setup_guide(
                retailer_id=base["retailer"]["id"],
                lines=[{"product_id": products[s["sku"]]["id"], "par_cases": 0} for s in product_specs],
            )
    if promo:
        target = products[promo.get("product_sku", product_specs[0]["sku"])]
        get_success_data(api_client.create_promo_event(create_promo_event_payload(
            product_id=target["id"],
            promo_type=promo.get("promo_type", "OFF_INVOICE"),
            discount_pct_bps=promo.get("discount_pct_bps", 1000),
            start_date=promo.get("start_date", "2026-05-01"),
            end_date=promo.get("end_date", "2026-05-31"),
        ), SALES))
    if clock_to is not None:
        get_success_data(api_client.set_clock({"to_iso8601": clock_to}, ADMIN))
    lines = [order_line(products[s["sku"]]["id"], cases_qty=s.get("cases_qty", 0),
                        split_units_qty=s.get("split_units_qty", 0)) for s in product_specs]
    order = get_success_data(api_client.create_purchase_order(
        create_purchase_order_payload(
            retailer_id=base["retailer"]["id"],
            order_guide_id=base["guide"]["id"],
            lines=lines,
        ),
        base["sm_headers"],
    ))
    base["order"] = order
    base["order_version"] = order["version"]
    return base


def setup_submitted_order(product_specs, **kwargs):
    """Draft order that has been submitted. Returns base dict with updated order."""
    base = setup_draft_order(product_specs, **kwargs)
    submitted = get_success_data(api_client.submit_order(
        base["order"]["id"],
        {"expected_order_version": base["order_version"]},
        base["sm_headers"],
    ))
    base["order"] = submitted
    base["order_version"] = submitted["version"]
    return base


# ---------------------------------------------------------------------------
# Tier 3: manifest pipeline (assign, begin-loading, close, confirm-delivery)
# ---------------------------------------------------------------------------


def setup_manifest(delivery_date="2026-05-25", capacity_lbs=100_000, route_code="R-1"):
    """Create a SCHEDULED manifest; returns manifest dict."""
    return get_success_data(api_client.create_delivery_manifest(
        create_delivery_manifest_payload(
            route_code=route_code, delivery_date=delivery_date, capacity_lbs=capacity_lbs,
        ),
        ADMIN,
    ))


def publish_fuel_rate(week_start_date="2026-05-25", doe_index_usd=3.00):
    return get_success_data(api_client.create_fuel_surcharge_rate(
        create_fuel_surcharge_rate_payload(week_start_date=week_start_date, doe_index_usd=doe_index_usd),
        ADMIN,
    ))


def assign_order_to_manifest(manifest, order):
    """Assign a SUBMITTED order; returns updated manifest dict."""
    updated = get_success_data(api_client.assign_order(
        manifest["id"],
        {"order_id": order["id"], "expected_manifest_version": manifest["version"]},
        ADMIN,
    ))
    return get_success_data(api_client.get_delivery_manifest(manifest["id"], ADMIN))


def begin_loading(manifest):
    """SCHEDULED -> LOADING; returns updated manifest."""
    return get_success_data(api_client.begin_loading(manifest["id"], ADMIN))


def close_manifest(manifest):
    """LOADING -> CLOSED; returns updated manifest."""
    return get_success_data(api_client.close_manifest(
        manifest["id"],
        {"expected_manifest_version": manifest["version"]},
        ADMIN,
    ))


def setup_closed_order(product_specs, fuel_doe=3.00, **kwargs):
    """Order taken through submit + assign + close. Returns dict with order, manifest, etc."""
    base = setup_submitted_order(product_specs, **kwargs)
    manifest = setup_manifest()
    publish_fuel_rate(doe_index_usd=fuel_doe)
    manifest = assign_order_to_manifest(manifest, base["order"])
    manifest = begin_loading(manifest)
    manifest = close_manifest(manifest)
    base["manifest"] = manifest
    # Refresh order (version bumped by assign + close)
    base["order"] = get_success_data(api_client.get_purchase_order(base["order"]["id"], ADMIN))
    return base


def setup_invoiced_order(product_specs, fuel_doe=3.00, **kwargs):
    """Order taken through confirm-delivery; invoice created. Returns dict with invoice."""
    base = setup_closed_order(product_specs, fuel_doe=fuel_doe, **kwargs)
    invoice = get_success_data(api_client.confirm_delivery(base["order"]["id"], DRIVER))
    base["invoice"] = invoice
    return base


# ---------------------------------------------------------------------------
# Tier 4: tobacco / stamp supply helpers
# ---------------------------------------------------------------------------


def setup_stamp_supply(jurisdiction="CA_NORTH", **overrides):
    return get_success_data(api_client.create_tax_stamp_supply(
        create_tax_stamp_supply_payload(jurisdiction_code=jurisdiction, **overrides),
        ADMIN,
    ))


# ---------------------------------------------------------------------------
# Tier 5: canonical scenarios used by many tests
# ---------------------------------------------------------------------------


def setup_canonical_submitted_promoted_order():
    """The 50 cases P1 (case 1200) + 20 split Q1 (unit 150) order with 1000bps
    OFF_INVOICE promo on P1 covering 2026-05-25, submitted at clock 2026-05-20.
    Provisional total: 58500. Returns base dict."""
    retailer, sm_headers = setup_retailer()
    p1 = setup_product(sku="P1", case_pack_units=12, case_cost_cents=1200,
                       unit_cost_cents=110, split_case_allowed=True,
                       weight_lbs_per_case=10)
    q1 = setup_product(sku="Q1", case_pack_units=24, case_cost_cents=2400,
                       unit_cost_cents=150, split_case_allowed=True,
                       weight_lbs_per_case=8)
    guide = setup_guide(
        retailer_id=retailer["id"],
        lines=[{"product_id": p1["id"], "par_cases": 0},
               {"product_id": q1["id"], "par_cases": 0}],
    )
    base = {
        "retailer": retailer,
        "sm_headers": sm_headers,
        "products": {"P1": p1, "Q1": q1},
        "guide": guide,
    }
    get_success_data(api_client.create_promo_event(create_promo_event_payload(
        product_id=base["products"]["P1"]["id"],
        promo_type="OFF_INVOICE",
        discount_pct_bps=1000,
        start_date="2026-05-01",
        end_date="2026-05-31",
    ), SALES))
    get_success_data(api_client.set_clock({"to_iso8601": "2026-05-20T00:00:00Z"}, ADMIN))
    order = get_success_data(api_client.create_purchase_order(
        create_purchase_order_payload(
            retailer_id=base["retailer"]["id"],
            order_guide_id=base["guide"]["id"],
            lines=[
                order_line(base["products"]["P1"]["id"], cases_qty=50, split_units_qty=0),
                order_line(base["products"]["Q1"]["id"], cases_qty=0, split_units_qty=20),
            ],
        ),
        base["sm_headers"],
    ))
    base["order"] = order
    base["order_version"] = order["version"]
    submitted = get_success_data(api_client.submit_order(
        order["id"], {"expected_order_version": base["order_version"]}, base["sm_headers"],
    ))
    base["order"] = submitted
    base["order_version"] = submitted["version"]
    return base


def setup_canonical_invoiced_60600():
    """Order of 50 cases P1 (no promo), 0% fuel tier, taken through confirm-delivery.
    Invoice total: 60600 (60000 merch + 600 pick, no min-drop). Returns base dict."""
    return setup_invoiced_order(
        [{"sku": "P1", "cases_qty": 50, "split_units_qty": 0}],
        fuel_doe=3.00,
    )


def get_order_line_id_for_product(order_id, product_id, headers=ADMIN):
    """Return the first line id of the given order for the given product."""
    resp = api_client.list_order_lines_filtered(headers, params={"order_id": order_id, "product_id": product_id})
    data = get_success_data(resp)
    return data[0]["id"]
