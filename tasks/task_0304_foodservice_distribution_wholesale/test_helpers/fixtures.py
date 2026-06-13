"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures produce clear
"Setup failed" errors rather than confusing assertion failures.

The dominant preamble in this domain is:
  distributor -> (set clock) -> warehouse -> route -> product (+ price tiers)
  -> inventory lot -> customer -> order -> order line(s) -> submit
  -> approve-credit -> start-pick -> load shipment -> capture POD.

These helpers expose every value tests need to control via keyword arguments while
defaulting everything else. All roles use opaque identity (see test_users.py), so
shared role headers are used throughout.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_distributor_payload, set_current_utc_payload,
    create_warehouse_payload, create_route_payload, create_product_payload,
    create_price_tier_payload, create_inventory_lot_payload, create_customer_payload,
    create_order_guide_payload, create_order_guide_item_payload,
    create_order_payload, create_order_line_payload, approve_credit_payload,
    pod_payload, create_return_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["distributor_admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
WAREHOUSE = TEST_USERS["warehouse_op_headers"]
CREDIT = TEST_USERS["credit_manager_headers"]

# A clock comfortably before the standard cutoff for the 2026-06-17 (Wed) delivery.
DEFAULT_CLOCK = "2026-06-15T12:00:00Z"
DEFAULT_DELIVERY = "2026-06-17T00:00:00Z"


# ─── Catalog building blocks ───────────────────────────────────────────────

def create_distributor(name="FreshCo"):
    """Create a distributor. Returns the distributor dict."""
    return get_success_data(api_client.create_distributor(
        create_distributor_payload(name=name), ADMIN))


def set_clock(distributor_id, to_iso8601):
    """Advance a distributor's server clock (also runs the AR sweep). Returns distributor."""
    return get_success_data(api_client.set_current_utc(
        set_current_utc_payload(distributor_id, to_iso8601), ADMIN))


def create_warehouse(distributor_id, code="WH1", name="Main"):
    return get_success_data(api_client.create_warehouse(
        create_warehouse_payload(distributor_id, code=code, name=name), ADMIN))


def create_route(distributor_id, warehouse_id, code="R1", delivery_dow=2,
                 cutoff_lead_hours=24, min_delivery_gap_days=None):
    payload = create_route_payload(
        distributor_id, warehouse_id, code=code,
        delivery_dow=delivery_dow, cutoff_lead_hours=cutoff_lead_hours)
    if min_delivery_gap_days is not None:
        payload["min_delivery_gap_days"] = min_delivery_gap_days
    return get_success_data(api_client.create_route(payload, ADMIN))


def create_product(distributor_id, sku="P-1", name="Cheddar", category="DAIRY",
                   splits_per_case=12, split_allowed=None, perishable=None,
                   substitute_product_id=None, case_cost_cents=1000):
    payload = create_product_payload(
        distributor_id, sku=sku, name=name, category=category,
        splits_per_case=splits_per_case, case_cost_cents=case_cost_cents)
    if split_allowed is not None:
        payload["split_allowed"] = split_allowed
    if perishable is not None:
        payload["perishable"] = perishable
    if substitute_product_id is not None:
        payload["substitute_product_id"] = substitute_product_id
    return get_success_data(api_client.create_product(payload, ADMIN))


def add_price_tier(product_id, min_cases, case_price_cents):
    return get_success_data(api_client.create_price_tier(
        create_price_tier_payload(product_id, min_cases, case_price_cents), ADMIN))


def add_price_tiers(product_id, tiers):
    """tiers: list of (min_cases, case_price_cents). Returns list of created tiers."""
    return [add_price_tier(product_id, mc, cp) for (mc, cp) in tiers]


def receive_lot(product_id, warehouse_id, on_hand_splits, lot_code="L1", expires_on=None):
    payload = create_inventory_lot_payload(
        product_id, warehouse_id, on_hand_splits, lot_code=lot_code)
    if expires_on is not None:
        payload["expires_on"] = expires_on
    return get_success_data(api_client.create_inventory_lot(payload, WAREHOUSE))


def create_customer(distributor_id, route_id, name="Diner A",
                    credit_limit_cents=100000, split_fee_cents=None):
    payload = create_customer_payload(
        distributor_id, route_id, name=name, credit_limit_cents=credit_limit_cents)
    if split_fee_cents is not None:
        payload["split_fee_cents"] = split_fee_cents
    return get_success_data(api_client.create_customer(payload, SALES))


# ─── Common base scenarios ─────────────────────────────────────────────────

def setup_base(distributor_name="FreshCo", clock=DEFAULT_CLOCK,
               delivery_dow=2, cutoff_lead_hours=24, min_delivery_gap_days=None):
    """Distributor + clock + warehouse + route.

    Returns dict: {distributor, warehouse, route}.
    """
    dist = create_distributor(distributor_name)
    if clock is not None:
        set_clock(dist["id"], clock)
    wh = create_warehouse(dist["id"])
    route = create_route(dist["id"], wh["id"], delivery_dow=delivery_dow,
                         cutoff_lead_hours=cutoff_lead_hours,
                         min_delivery_gap_days=min_delivery_gap_days)
    return {"distributor": dist, "warehouse": wh, "route": route}


def setup_catalog(splits_per_case=12, split_allowed=None, perishable=None,
                  case_cost_cents=1000, tiers=((1, 2400),), on_hand_splits=12,
                  lot_expires_on=None, credit_limit_cents=100000, split_fee_cents=None,
                  clock=DEFAULT_CLOCK, delivery_dow=2, cutoff_lead_hours=24,
                  min_delivery_gap_days=None, stock=True):
    """Full catalog through a customer: distributor, warehouse, route, one product
    with `tiers`, optionally one inventory lot, and one customer.

    Returns dict: {distributor, warehouse, route, product, tiers, lot, customer}.
    `lot` is None when stock is False.
    """
    base = setup_base(clock=clock, delivery_dow=delivery_dow,
                      cutoff_lead_hours=cutoff_lead_hours,
                      min_delivery_gap_days=min_delivery_gap_days)
    prod = create_product(base["distributor"]["id"], splits_per_case=splits_per_case,
                          split_allowed=split_allowed, perishable=perishable,
                          case_cost_cents=case_cost_cents)
    created_tiers = add_price_tiers(prod["id"], list(tiers)) if tiers else []
    lot = None
    if stock:
        lot = receive_lot(prod["id"], base["warehouse"]["id"], on_hand_splits,
                          expires_on=lot_expires_on)
    cust = create_customer(base["distributor"]["id"], base["route"]["id"],
                           credit_limit_cents=credit_limit_cents,
                           split_fee_cents=split_fee_cents)
    return {
        "distributor": base["distributor"],
        "warehouse": base["warehouse"],
        "route": base["route"],
        "product": prod,
        "tiers": created_tiers,
        "lot": lot,
        "customer": cust,
    }


# ─── Order lifecycle ───────────────────────────────────────────────────────

def create_order(customer_id, delivery_date=DEFAULT_DELIVERY):
    return get_success_data(api_client.create_order(
        create_order_payload(customer_id, requested_delivery_date=delivery_date), SALES))


def add_line(order_id, product_id, uom, ordered_qty):
    return get_success_data(api_client.add_order_line(
        order_id, create_order_line_payload(product_id, uom, ordered_qty), SALES))


def submit_order(order_id):
    return get_success_data(api_client.submit_order(order_id, SALES))


def approve_order(order_id, expected_customer_version):
    return get_success_data(api_client.approve_credit(
        order_id, approve_credit_payload(expected_customer_version), CREDIT))


def get_customer_version(customer_id):
    cust = get_success_data(api_client.get_customer(customer_id, SALES))
    return cust["version"]


def create_draft_order_with_line(customer_id, product_id, uom="CASE", ordered_qty=1,
                                 delivery_date=DEFAULT_DELIVERY):
    """Draft order with one line (not submitted). Returns (order, line)."""
    order = create_order(customer_id, delivery_date)
    line = add_line(order["id"], product_id, uom, ordered_qty)
    return order, line


def create_submitted_order(customer_id, product_id, lines=None, uom="CASE", ordered_qty=1,
                           delivery_date=DEFAULT_DELIVERY):
    """Draft order + lines + submit. `lines` is a list of (product_id, uom, ordered_qty);
    when None a single line (product_id, uom, ordered_qty) is added.

    Returns (order, [lines]).
    """
    order = create_order(customer_id, delivery_date)
    created = []
    if lines is None:
        lines = [(product_id, uom, ordered_qty)]
    for (pid, u, qty) in lines:
        created.append(add_line(order["id"], pid, u, qty))
    submit_order(order["id"])
    order = get_success_data(api_client.get_order(order["id"], SALES))
    return order, created


def create_approved_order(customer_id, product_id, lines=None, uom="CASE", ordered_qty=1,
                          delivery_date=DEFAULT_DELIVERY, expected_customer_version=None):
    """Submitted order then credit-approved. Returns (order, [lines]).

    If expected_customer_version is omitted, the customer's current version is read
    just before approval (so the OCC guard passes).
    """
    order, created = create_submitted_order(
        customer_id, product_id, lines=lines, uom=uom, ordered_qty=ordered_qty,
        delivery_date=delivery_date)
    if expected_customer_version is None:
        expected_customer_version = get_customer_version(customer_id)
    approve_order(order["id"], expected_customer_version)
    order = get_success_data(api_client.get_order(order["id"], SALES))
    return order, created


def shipment_for_order(order_id):
    """Return the (first) shipment created for an order."""
    data, _ = _list(api_client.list_shipments(WAREHOUSE, params={"order_id": order_id}))
    return data[0]


def create_delivered_order(customer_id, product_id, lines=None, uom="CASE", ordered_qty=1,
                           delivery_date=DEFAULT_DELIVERY, expected_customer_version=None,
                           pod_signature="J. Receiver"):
    """Full lifecycle through DELIVERED: approve -> start-pick -> load -> pod.

    Returns (order, [lines], shipment).
    """
    order, created = create_approved_order(
        customer_id, product_id, lines=lines, uom=uom, ordered_qty=ordered_qty,
        delivery_date=delivery_date, expected_customer_version=expected_customer_version)
    get_success_data(api_client.start_pick(order["id"], WAREHOUSE))
    ship = shipment_for_order(order["id"])
    get_success_data(api_client.load_shipment(ship["id"], WAREHOUSE))
    get_success_data(api_client.pod_shipment(ship["id"], pod_payload(pod_signature), WAREHOUSE))
    order = get_success_data(api_client.get_order(order["id"], SALES))
    ship = get_success_data(api_client.get_shipment(ship["id"], WAREHOUSE))
    return order, created, ship


def _list(response):
    """Internal: parse a paginated list response leniently into (data, meta)."""
    body = response.json()
    data = body.get("data", [])
    meta = body.get("meta", {})
    return data, meta


# ─── Returns ───────────────────────────────────────────────────────────────

def request_return(customer_id, order_id, order_line_id, reason, return_splits, headers=None):
    return get_success_data(api_client.create_return(
        create_return_payload(customer_id, order_id, order_line_id, reason, return_splits),
        headers or SALES))


def setup_delivered_line_for_return(splits_per_case=12, tiers=((1, 2400),),
                                    on_hand_splits=14, uom="SPLIT", ordered_qty=14,
                                    credit_limit_cents=100000):
    """A delivered order with a single line, ready for return requests.

    Returns dict: {customer, order, line, product, shipment}.
    """
    cat = setup_catalog(splits_per_case=splits_per_case, split_allowed=True,
                        tiers=tiers, on_hand_splits=on_hand_splits,
                        credit_limit_cents=credit_limit_cents)
    order, lines, ship = create_delivered_order(
        cat["customer"]["id"], cat["product"]["id"],
        lines=[(cat["product"]["id"], uom, ordered_qty)])
    return {
        "customer": cat["customer"],
        "order": order,
        "line": lines[0],
        "product": cat["product"],
        "shipment": ship,
    }
