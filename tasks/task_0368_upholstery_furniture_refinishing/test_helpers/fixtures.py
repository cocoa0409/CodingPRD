"""Composite setup helpers.

These encapsulate the multi-step API sequences that drive a work order through
its lifecycle (intake -> estimating -> awaiting approval -> approved ->
in production -> ready for fulfillment -> completed), plus catalog and shop-day
setup. Each helper builds its preconditions from scratch using only PRD-declared
endpoints and uses the lenient get_success_data() validator so setup failures
surface as clear "Setup failed" errors.

Identity threading: the Customer role is entity-backed, so any ownership-gated
call (approve / decline / request-revision / file warranty claim) uses
make_customer_headers(customer_id) with the real Customer id.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_customer_headers
from . import factories


CLERK = TEST_USERS["intake_clerk_headers"]
ESTIMATOR = TEST_USERS["estimator_headers"]
MANAGER = TEST_USERS["shop_manager_headers"]


# ---------------------------------------------------------------------------
# Single-entity helpers
# ---------------------------------------------------------------------------
def register_customer(**overrides) -> dict:
    resp = api_client.create_customer(factories.create_customer_payload(**overrides), CLERK)
    return get_success_data(resp)


def register_fabric_sku(**overrides) -> dict:
    resp = api_client.create_fabric_sku(factories.create_fabric_sku_payload(**overrides), MANAGER)
    return get_success_data(resp)


def register_discontinued_fabric_sku(**overrides) -> dict:
    fab = register_fabric_sku(**overrides)
    get_success_data(api_client.discontinue_fabric_sku(fab["id"], MANAGER))
    return get_success_data(api_client.get_fabric_sku(fab["id"], MANAGER))


def register_foam_spec(**overrides) -> dict:
    resp = api_client.create_foam_spec(factories.create_foam_spec_payload(**overrides), MANAGER)
    return get_success_data(resp)


def register_shop_day(work_date, labor_capacity_hours, **overrides) -> dict:
    resp = api_client.create_shop_day(
        factories.create_shop_day_payload(work_date, labor_capacity_hours, **overrides), MANAGER
    )
    return get_success_data(resp)


def get_work_order(work_order_id: str) -> dict:
    return get_success_data(api_client.get_work_order(work_order_id, MANAGER))


def current_version(work_order_id: str) -> int:
    return get_work_order(work_order_id)["version"]


# ---------------------------------------------------------------------------
# Tier 1: state progression on a single work order
# ---------------------------------------------------------------------------
def open_intake_work_order(service_type="REPAIR", rush_requested=False,
                           with_photo=True, customer=None):
    """Customer + WorkOrder at INTAKE (+ one condition photo unless suppressed).
    Returns (customer, work_order)."""
    if customer is None:
        customer = register_customer()
    wo = get_success_data(api_client.create_work_order(
        factories.create_work_order_payload(
            customer["id"], service_type=service_type, rush_requested=rush_requested),
        CLERK,
    ))
    if with_photo:
        get_success_data(api_client.create_condition_photo(
            factories.create_condition_photo_payload(wo["id"]), CLERK))
    return customer, wo


def create_estimating_work_order(service_type="REPAIR", rush_requested=False,
                                 line_items=None, customer=None):
    """Open order + add line items so the first one advances INTAKE -> ESTIMATING.
    `line_items` is a list of line-item payload dicts (label/labor_hours/fabric/etc.).
    Defaults to one simple REPAIR piece (2 labor-hours).
    Returns (customer, work_order, [line_item, ...])."""
    customer, wo = open_intake_work_order(
        service_type=service_type, rush_requested=rush_requested, customer=customer)
    if line_items is None:
        line_items = [factories.create_line_item_payload(piece_label="Piece", labor_hours=2)]
    created = []
    for li in line_items:
        created.append(get_success_data(api_client.create_line_item(wo["id"], li, CLERK)))
    return customer, get_work_order(wo["id"]), created


def author_estimate(work_order_id, supersedes_estimate_id=None):
    """Author an estimate version against the current work-order version.
    Returns the created Estimate."""
    v = current_version(work_order_id)
    payload = factories.create_estimate_payload(v)
    if supersedes_estimate_id is not None:
        payload["supersedes_estimate_id"] = supersedes_estimate_id
    return get_success_data(api_client.create_estimate(work_order_id, payload, ESTIMATOR))


def create_awaiting_approval_order(service_type="REPAIR", rush_requested=False,
                                   line_items=None, customer=None):
    """ESTIMATING order with a v1 estimate authored -> AWAITING_APPROVAL.
    Returns (customer, work_order, estimate, [line_item, ...])."""
    customer, wo, items = create_estimating_work_order(
        service_type=service_type, rush_requested=rush_requested,
        line_items=line_items, customer=customer)
    est = author_estimate(wo["id"])
    return customer, get_work_order(wo["id"]), est, items


def approve_order(customer, work_order_id, deposit_amount_cents):
    """Approve as the owning customer with the given deposit. Returns the WorkOrder."""
    v = current_version(work_order_id)
    headers = make_customer_headers(customer["id"])
    return get_success_data(api_client.approve_work_order(
        work_order_id, factories.approve_payload(v, deposit_amount_cents), headers))


def create_approved_order(service_type="REPAIR", rush_requested=False,
                          line_items=None, deposit_amount_cents=None, customer=None):
    """AWAITING_APPROVAL order approved with a deposit -> APPROVED.
    deposit_amount_cents defaults to the order's estimate_total (always >= floor).
    Returns (customer, work_order, estimate, [line_item, ...])."""
    customer, wo, est, items = create_awaiting_approval_order(
        service_type=service_type, rush_requested=rush_requested,
        line_items=line_items, customer=customer)
    if deposit_amount_cents is None:
        deposit_amount_cents = wo["estimate_total_cents"]
    approve_order(customer, wo["id"], deposit_amount_cents)
    return customer, get_work_order(wo["id"]), est, items


# ---------------------------------------------------------------------------
# Tier 2/3: production lifecycle
# ---------------------------------------------------------------------------
def place_material_order(work_order_id, **overrides):
    """Place a MaterialOrder against an approved order. Returns the MaterialOrder."""
    return get_success_data(api_client.create_material_order(
        factories.create_material_order_payload(work_order_id, **overrides), MANAGER))


def receive_material_order(material_order_id, **prices):
    """Receive a MaterialOrder at the supplied actual prices. Returns the MaterialOrder."""
    return get_success_data(api_client.receive_material_order(material_order_id, prices, MANAGER))


def book_production_leg(work_order_id, shop_day_id):
    """Book the first PRODUCTION leg onto a shop day -> IN_PRODUCTION.
    Returns the FulfillmentLeg."""
    return get_success_data(api_client.create_fulfillment_leg(
        factories.create_fulfillment_leg_payload(
            work_order_id, "PRODUCTION", shop_day_id=shop_day_id), MANAGER))


def complete_production_leg(leg_id):
    """Walk a PRODUCTION leg PLANNED -> DISPATCHED -> COMPLETED."""
    get_success_data(api_client.dispatch_fulfillment_leg(leg_id, MANAGER))
    return get_success_data(api_client.complete_fulfillment_leg(leg_id, MANAGER))


def create_in_production_order(service_type="REPAIR", rush_requested=False,
                               line_items=None, deposit_amount_cents=None,
                               shop_day_date="2026-04-01", shop_capacity=40,
                               material_orders=None, customer=None):
    """APPROVED order -> place & receive any material orders -> book production leg.
    `material_orders` is a list of (create_overrides, receive_prices) tuples.
    Returns (customer, work_order, shop_day, production_leg, [line_item,...])."""
    customer, wo, est, items = create_approved_order(
        service_type=service_type, rush_requested=rush_requested,
        line_items=line_items, deposit_amount_cents=deposit_amount_cents, customer=customer)
    if material_orders:
        for create_overrides, receive_prices in material_orders:
            mo = place_material_order(wo["id"], **create_overrides)
            receive_material_order(mo["id"], **receive_prices)
    day = register_shop_day(shop_day_date, shop_capacity)
    leg = book_production_leg(wo["id"], day["id"])
    return customer, get_work_order(wo["id"]), day, leg, items


def create_ready_for_fulfillment_order(service_type="REPAIR", rush_requested=False,
                                       line_items=None, deposit_amount_cents=None,
                                       shop_day_date="2026-04-01", shop_capacity=40,
                                       material_orders=None, customer=None):
    """IN_PRODUCTION order with production leg COMPLETED -> finish-production
    -> READY_FOR_FULFILLMENT. Returns (customer, work_order, shop_day, prod_leg, [items])."""
    customer, wo, day, leg, items = create_in_production_order(
        service_type=service_type, rush_requested=rush_requested,
        line_items=line_items, deposit_amount_cents=deposit_amount_cents,
        shop_day_date=shop_day_date, shop_capacity=shop_capacity,
        material_orders=material_orders, customer=customer)
    complete_production_leg(leg["id"])
    get_success_data(api_client.finish_production(wo["id"], MANAGER))
    return customer, get_work_order(wo["id"]), day, leg, items


def complete_pickup_or_delivery(work_order_id, kind="PICKUP",
                                window_start="2026-04-05T09:00:00Z",
                                window_end="2026-04-05T11:00:00Z"):
    """Create a PICKUP/DELIVERY leg and walk it to COMPLETED. Returns the leg."""
    leg = get_success_data(api_client.create_fulfillment_leg(
        factories.create_fulfillment_leg_payload(
            work_order_id, kind,
            scheduled_window_start=window_start, scheduled_window_end=window_end), MANAGER))
    complete_production_leg(leg["id"])  # dispatch + complete share the same lifecycle
    return leg


def set_clock(to_iso8601: str):
    """Set the server clock used to stamp completed_at."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, MANAGER))


def settle_and_complete(work_order_id):
    """Read the current balance_due and complete with an exact-match settlement.
    Returns the WorkOrder."""
    bal = get_work_order(work_order_id)["balance_due_cents"]
    return get_success_data(api_client.complete_work_order(
        work_order_id, {"settlement_amount_cents": bal}, MANAGER))


def create_completed_order(service_type="REPAIR", rush_requested=False,
                           line_items=None, deposit_amount_cents=None,
                           shop_day_date="2026-02-20", shop_capacity=40,
                           material_orders=None, fulfillment_kind="PICKUP",
                           fulfillment_window=("2026-02-28T09:00:00Z", "2026-02-28T11:00:00Z"),
                           completed_at="2026-03-01T00:00:00Z", customer=None):
    """Full lifecycle through COMPLETED, with completed_at stamped from the server
    clock set to `completed_at`. Returns (customer, work_order)."""
    customer, wo, day, leg, items = create_ready_for_fulfillment_order(
        service_type=service_type, rush_requested=rush_requested,
        line_items=line_items, deposit_amount_cents=deposit_amount_cents,
        shop_day_date=shop_day_date, shop_capacity=shop_capacity,
        material_orders=material_orders, customer=customer)
    complete_pickup_or_delivery(
        wo["id"], kind=fulfillment_kind,
        window_start=fulfillment_window[0], window_end=fulfillment_window[1])
    set_clock(completed_at)
    settle_and_complete(wo["id"])
    return customer, get_work_order(wo["id"])


# ---------------------------------------------------------------------------
# Reupholstery convenience: a single reupholstery line item
# ---------------------------------------------------------------------------
def reupholstery_line_item(fabric_sku_id, yardage_required, labor_hours,
                           foam_spec_id=None, board_feet_required=0, piece_label="Sofa"):
    li = factories.create_line_item_payload(
        piece_label=piece_label,
        fabric_sku_id=fabric_sku_id,
        yardage_required=yardage_required,
        labor_hours=labor_hours,
    )
    if foam_spec_id is not None:
        li["foam_spec_id"] = foam_spec_id
        li["board_feet_required"] = board_feet_required
    return li
