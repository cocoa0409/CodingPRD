"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (the server is restarted before every test, so each test starts
against an empty database and the logical clock at 2026-08-01T00:00:00Z).
Setup calls use the lenient get_success_data() validator so failures surface
as clear "Setup failed" errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_credit_claim_payload,
    create_location_payload,
    create_operator_payload,
    create_order_payload,
    create_planogram_payload,
    create_product_payload,
    create_promotion_payload,
    create_route_payload,
    create_service_ticket_payload,
    create_telemetry_event_payload,
)
from .test_users import TEST_USERS, make_operator_manager_headers

__all__ = [
    "ADMIN",
    "PLANNER",
    "WAREHOUSE",
    "ADJUSTER",
    "TELEMETRY",
    "create_operator",
    "create_route",
    "create_product",
    "create_location",
    "create_draft_planogram",
    "activate_planogram",
    "setup_selling_location",
    "create_order",
    "submit_order",
    "confirm_order",
    "deliver_order",
    "walk_order_to_delivered",
    "settle_order_with_event",
    "ingest_telemetry",
    "create_claim",
    "create_promotion",
    "create_service_ticket",
    "set_logical_clock",
    "get_location",
    "get_order",
    "get_operator",
    "get_planogram",
    "get_credit_claim",
]

# Shared role headers for the opaque roles (PRD §2.1: their X-User-ID is never
# compared to any entity id).
ADMIN = TEST_USERS["wholesale_admin_headers"]
PLANNER = TEST_USERS["route_planner_headers"]
WAREHOUSE = TEST_USERS["warehouse_ops_headers"]
ADJUSTER = TEST_USERS["credit_adjuster_headers"]
TELEMETRY = TEST_USERS["telemetry_gateway_headers"]


# ---------------------------------------------------------------------------
# Primitive creators
# ---------------------------------------------------------------------------

def create_operator(name="Op", default_tender=None):
    resp = api_client.create_operator(create_operator_payload(name, default_tender), ADMIN)
    return get_success_data(resp)


def create_route(route_code="R-1", delivery_weekdays=("MON",),
                 daily_case_capacity=100, min_order_cents=0):
    resp = api_client.create_route(
        create_route_payload(route_code, delivery_weekdays,
                             daily_case_capacity, min_order_cents),
        ADMIN,
    )
    return get_success_data(resp)


def create_product(sku, **overrides):
    resp = api_client.create_product(create_product_payload(sku=sku, **overrides), ADMIN)
    return get_success_data(resp)


def create_location(operator_id, route_id, name="Loc", location_type="OFFICE",
                    headers=None):
    """Default creator is WholesaleAdmin (may create for any operator, PRD §3.3)."""
    resp = api_client.create_location(
        create_location_payload(operator_id, route_id, name, location_type),
        headers or ADMIN,
    )
    return get_success_data(resp)


def create_draft_planogram(location_id, slots, operator_id, name="PG"):
    resp = api_client.create_planogram(
        create_planogram_payload(location_id, slots, name),
        make_operator_manager_headers(operator_id),
    )
    return get_success_data(resp)


def activate_planogram(planogram_id, location_id, operator_id):
    """Read the location's live version, then activate with it (PRD §2.7 OCC)."""
    loc = get_success_data(api_client.get_location(location_id, ADMIN))
    resp = api_client.activate_planogram(
        planogram_id,
        {"expected_location_version": loc["version"]},
        make_operator_manager_headers(operator_id),
    )
    return get_success_data(resp)


def create_promotion(product_id, discount_type, discount_value, starts_at, ends_at,
                     stacking_class, operator_id=None):
    resp = api_client.create_promotion(
        create_promotion_payload(product_id, discount_type, discount_value,
                                 starts_at, ends_at, stacking_class, operator_id),
        ADMIN,
    )
    return get_success_data(resp)


def create_service_ticket(location_id, operator_id, equipment_model="VENDO-540",
                          issue_type="REPAIR", parts=None):
    resp = api_client.create_service_ticket(
        create_service_ticket_payload(location_id, equipment_model, issue_type, parts),
        make_operator_manager_headers(operator_id),
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Composite: operator + route + products + location + ACTIVE planogram
# ---------------------------------------------------------------------------

def setup_selling_location(products_spec=None, slots_spec=None,
                           route_weekdays=("MON",), daily_case_capacity=100,
                           min_order_cents=0, location_type="OFFICE",
                           operator_name="Op", route_code="R-1",
                           location_name="Loc", planogram_name="PG",
                           activate=True):
    """Operator + route + products + location + planogram (+ activation).

    products_spec: list of create_product kwargs (default: one OFFICE-eligible
        product, pack 10, base 1000).
    slots_spec: list of {"slot_code", "product_index", "par_level_units",
        "vend_price_cents"} rows (default: one slot over product 0).

    Returns a world dict with operator, route, location, products (list),
    planogram, and om_headers (OperatorManager headers bound to the operator).
    """
    operator = create_operator(operator_name)
    route = create_route(route_code, route_weekdays, daily_case_capacity,
                         min_order_cents)
    if products_spec is None:
        products_spec = [{"sku": "SKU-1"}]
    products = [create_product(**spec) for spec in products_spec]
    location = create_location(operator["id"], route["id"], location_name,
                               location_type)
    if slots_spec is None:
        slots_spec = [{"slot_code": "A1", "product_index": 0,
                       "par_level_units": 10, "vend_price_cents": 150}]
    slots = [{
        "slot_code": spec["slot_code"],
        "product_id": products[spec.get("product_index", 0)]["id"],
        "par_level_units": spec.get("par_level_units", 10),
        "vend_price_cents": spec.get("vend_price_cents", 150),
    } for spec in slots_spec]
    planogram = create_draft_planogram(location["id"], slots, operator["id"],
                                       planogram_name)
    if activate:
        planogram = activate_planogram(planogram["id"], location["id"],
                                       operator["id"])
    return {
        "operator": operator,
        "route": route,
        "location": location,
        "products": products,
        "planogram": planogram,
        "om_headers": make_operator_manager_headers(operator["id"]),
    }


# ---------------------------------------------------------------------------
# Order lifecycle helpers (PRD §3.5, §3.6)
# ---------------------------------------------------------------------------

def create_order(world, lines, delivery_date="2026-08-03", location=None):
    loc_id = (location or world["location"])["id"]
    resp = api_client.create_order(
        create_order_payload(loc_id, delivery_date, lines),
        world["om_headers"],
    )
    return get_success_data(resp)


def submit_order(world, order_id):
    return get_success_data(api_client.submit_order(order_id, world["om_headers"]))


def confirm_order(order_id):
    return get_success_data(api_client.confirm_order(order_id, PLANNER))


def deliver_order(order_id):
    return get_success_data(api_client.mark_order_delivered(order_id, WAREHOUSE))


def walk_order_to_delivered(world, lines, delivery_date="2026-08-03", location=None):
    """Create -> submit -> confirm -> mark-delivered. Returns the DELIVERED order."""
    order = create_order(world, lines, delivery_date, location)
    submit_order(world, order["id"])
    confirm_order(order["id"])
    return deliver_order(order["id"])


def ingest_telemetry(location_id, recorded_at, items,
                     cash_collected_cents=0, cashless_sales_cents=0):
    resp = api_client.create_telemetry_event(
        create_telemetry_event_payload(location_id, recorded_at, items,
                                       cash_collected_cents, cashless_sales_cents),
        TELEMETRY,
    )
    return get_success_data(resp)


def settle_order_with_event(world, order, tender="CASH",
                            recorded_at="2026-08-04T09:00:00Z",
                            items=None, cash=0, cashless=0):
    """Ingest a DEX event for the order's location, then settle against it."""
    event = ingest_telemetry(world["location"]["id"], recorded_at,
                             items if items is not None else [],
                             cash, cashless)
    resp = api_client.settle_order(
        order["id"],
        {"tender_type": tender, "telemetry_event_id": event["id"]},
        ADMIN,
    )
    return get_success_data(resp)


def create_claim(world, order_id, lines):
    resp = api_client.create_credit_claim(
        create_credit_claim_payload(order_id, lines),
        world["om_headers"],
    )
    return get_success_data(resp)


def set_logical_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Read-back helpers
# ---------------------------------------------------------------------------

def get_location(location_id):
    return get_success_data(api_client.get_location(location_id, ADMIN))


def get_order(order_id):
    return get_success_data(api_client.get_order(order_id, ADMIN))


def get_operator(operator_id):
    return get_success_data(api_client.get_operator(operator_id, ADMIN))


def get_planogram(planogram_id):
    return get_success_data(api_client.get_planogram(planogram_id, ADMIN))


def get_credit_claim(claim_id):
    return get_success_data(api_client.get_credit_claim(claim_id, ADMIN))
