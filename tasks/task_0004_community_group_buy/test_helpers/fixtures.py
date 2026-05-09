"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures produce clear
'Setup failed' errors rather than confusing assertion failures.

Identity threading: every entity_backed role uses make_*_headers(entity_id) so
ownership-gated checks see the actual owner id, not a shared placeholder.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_community_payload, create_group_leader_payload, create_customer_payload,
    create_supplier_payload, create_warehouse_payload, create_pickup_point_payload,
    create_flash_campaign_payload, create_group_buy_campaign_payload,
    create_join_payload, create_flash_purchase_payload,
    create_after_sales_payload, create_resolve_payload,
    create_plan_shipments_payload,
    create_payout_payload,
)
from .test_users import (
    TEST_USERS,
    make_group_leader_headers, make_customer_headers, make_supplier_headers,
    make_platform_admin_headers, make_pickup_operator_headers,
    make_customer_service_headers,
)


ADMIN = TEST_USERS["platform_admin_headers"]
PICKUP_OP = TEST_USERS["pickup_operator_headers"]
CS_AGENT = TEST_USERS["customer_service_headers"]


# ─── Tier 1: State Progression ────────────────────────

def create_community(**overrides):
    res = api_client.create_community(create_community_payload(**overrides), ADMIN)
    return get_success_data(res)


def create_supplier(**overrides):
    res = api_client.create_supplier(create_supplier_payload(**overrides), ADMIN)
    return get_success_data(res)


def create_customer(community_id, **overrides):
    res = api_client.create_customer(create_customer_payload(community_id, **overrides), ADMIN)
    return get_success_data(res)


def create_warehouse(supplier_id, **overrides):
    res = api_client.create_warehouse(supplier_id, create_warehouse_payload(**overrides), ADMIN)
    return get_success_data(res)


def create_pickup_point(community_id, **overrides):
    res = api_client.create_pickup_point(community_id, create_pickup_point_payload(**overrides), ADMIN)
    return get_success_data(res)


def create_active_leader(community_id, parent_leader_id=None, **overrides):
    """Create a GroupLeader and approve to ACTIVE."""
    payload = create_group_leader_payload(**overrides)
    if parent_leader_id is not None:
        payload["parent_leader_id"] = parent_leader_id
    leader = get_success_data(api_client.create_group_leader(community_id, payload, ADMIN))
    leader = get_success_data(api_client.approve_leader(leader["id"], ADMIN))
    return leader


def create_pending_leader(community_id, parent_leader_id=None, **overrides):
    """Create a GroupLeader; do NOT approve. Status remains PENDING_REVIEW."""
    payload = create_group_leader_payload(**overrides)
    if parent_leader_id is not None:
        payload["parent_leader_id"] = parent_leader_id
    return get_success_data(api_client.create_group_leader(community_id, payload, ADMIN))


# ─── Tier 2: Common scenario combos ───────────────────

def setup_basic_scaffold(region_code="RC1"):
    """Build a minimal scaffold: community + customer + supplier + warehouse + leader + pickup point.
    Returns dict with C, Cust, S, W, L (active), P keys."""
    community = create_community(region_code=region_code)
    cust = create_customer(community["id"], display_name="Cust1")
    supplier = create_supplier(name="S1")
    warehouse = create_warehouse(supplier["id"], region_code=region_code, cold_chain_capable=False)
    leader = create_active_leader(community["id"], display_name="L1")
    pickup = create_pickup_point(community["id"], capacity_packages=5, cold_storage_capable=True)
    return {
        "community": community,
        "customer": cust,
        "supplier": supplier,
        "warehouse": warehouse,
        "leader": leader,
        "pickup_point": pickup,
    }


def create_group_buy_campaign(leader_id, supplier_id, **overrides):
    res = api_client.create_group_buy_campaign(
        leader_id,
        create_group_buy_campaign_payload(supplier_id, **overrides),
        make_group_leader_headers(leader_id),
    )
    return get_success_data(res)


def join_campaign(campaign_id, customer_id, **overrides):
    res = api_client.join_group_buy(
        campaign_id,
        create_join_payload(customer_id, **overrides),
        make_customer_headers(customer_id),
    )
    return get_success_data(res)


def pay_order(order_id, customer_id):
    res = api_client.pay_order(order_id, make_customer_headers(customer_id))
    return get_success_data(res)


def close_campaign(campaign_id, leader_id):
    res = api_client.close_campaign(campaign_id, make_group_leader_headers(leader_id))
    return get_success_data(res)


# ─── Tier 3: Full lifecycle helpers ───────────────────

def setup_paid_succeeded_order(unit_price_cents=100, quantity=1, line_items=None,
                                discount_tiers=None, region_code="RC1"):
    """
    Build a SUCCEEDED group-buy campaign with one PAID order from one customer.
    Returns dict: scaffold + campaign + order (after close, payment_status=SETTLED).
    """
    sc = setup_basic_scaffold(region_code=region_code)
    if discount_tiers is None:
        discount_tiers = [{"min_participants": 1, "discount_basis_points": 0}]
    campaign = create_group_buy_campaign(
        sc["leader"]["id"], sc["supplier"]["id"],
        sku="SKUA", unit_price_cents=unit_price_cents,
        discount_tiers=discount_tiers,
        opens_at_period=0, deadline_period=100,
    )
    if line_items is None:
        line_items = [{"sku": "SKUA", "unit_price_cents": unit_price_cents, "quantity": quantity}]
    order = join_campaign(campaign["id"], sc["customer"]["id"], line_items=line_items)
    order = pay_order(order["id"], sc["customer"]["id"])
    campaign = close_campaign(campaign["id"], sc["leader"]["id"])
    # Re-fetch order so caller sees SETTLED
    order = get_success_data(api_client.get_order(order["id"], ADMIN))
    sc["campaign"] = campaign
    sc["order"] = order
    return sc


def plan_shipments_for_order(order_id, supplier_id, pickup_point_id, line_units):
    res = api_client.plan_shipments(
        order_id,
        create_plan_shipments_payload(pickup_point_id, line_units),
        make_supplier_headers(supplier_id),
    )
    return get_success_data(res)


def dispatch_shipment(shipment_id, supplier_id):
    res = api_client.dispatch_shipment(shipment_id, make_supplier_headers(supplier_id))
    return get_success_data(res)


def arrive_shipment(shipment_id, supplier_id):
    res = api_client.arrive_at_pickup(shipment_id, make_supplier_headers(supplier_id))
    return get_success_data(res)


def pickup_confirm(order_id, customer_id):
    res = api_client.pickup_confirm(order_id, make_customer_headers(customer_id))
    return get_success_data(res)


def progress_order_to_picked_up(scaffold, line_units=None):
    """Take a SETTLED group-buy order through plan -> dispatch -> arrive -> pickup-confirm.
    `scaffold` must contain: order, supplier, pickup_point, customer."""
    order = scaffold["order"]
    if line_units is None:
        line_units = [{"sku": li["sku"], "quantity": li["quantity"]} for li in order["line_items"]]
    shipments = plan_shipments_for_order(
        order["id"], scaffold["supplier"]["id"], scaffold["pickup_point"]["id"], line_units
    )
    for sh in shipments:
        dispatch_shipment(sh["id"], scaffold["supplier"]["id"])
    for sh in shipments:
        arrive_shipment(sh["id"], scaffold["supplier"]["id"])
    pickup_confirm(order["id"], scaffold["customer"]["id"])
    scaffold["shipments"] = shipments
    scaffold["order"] = get_success_data(api_client.get_order(order["id"], ADMIN))
    return scaffold


def setup_picked_up_order(unit_price_cents=100, quantity=1, line_items=None,
                          discount_tiers=None, region_code="RC1"):
    """End-to-end: SUCCEEDED campaign + paid order + picked up. Order.fulfillment_status=PICKED_UP."""
    sc = setup_paid_succeeded_order(
        unit_price_cents=unit_price_cents, quantity=quantity,
        line_items=line_items, discount_tiers=discount_tiers, region_code=region_code,
    )
    return progress_order_to_picked_up(sc)


# ─── Tier 4: Flash campaigns ──────────────────────────

def setup_flash_scenario(total_stock=10, tier_caps=None, unit_price_cents=100,
                         cold_chain_required=False, opens_at_period=0, closes_at_period=100):
    """Community + customer + supplier (with warehouse) + open flash campaign."""
    community = create_community(region_code="RC1")
    cust = create_customer(community["id"], display_name="Cust1")
    supplier = create_supplier(name="S1")
    create_warehouse(supplier["id"], region_code="RC1",
                     cold_chain_capable=cold_chain_required)
    if tier_caps is None:
        tier_caps = [{"tier": 0, "max_units": 5}]
    fc = get_success_data(api_client.create_flash_campaign(
        supplier["id"],
        create_flash_campaign_payload(
            sku="FLASHA", cold_chain_required=cold_chain_required,
            unit_price_cents=unit_price_cents, tier_caps=tier_caps,
            total_stock=total_stock,
            opens_at_period=opens_at_period, closes_at_period=closes_at_period,
        ),
        ADMIN,
    ))
    return {
        "community": community,
        "customer": cust,
        "supplier": supplier,
        "flash_campaign": fc,
    }


# ─── Tier 5: After-sales / payouts / risk ─────────────

def file_after_sales(order_id, customer_id, case_type, requested_amount_cents):
    res = api_client.file_after_sales(
        order_id,
        create_after_sales_payload(case_type, requested_amount_cents),
        make_customer_headers(customer_id),
    )
    return get_success_data(res)


def start_review(case_id):
    res = api_client.start_review(case_id, CS_AGENT)
    return get_success_data(res)


def resolve_case(case_id, outcome, by_admin=False):
    headers = ADMIN if by_admin else CS_AGENT
    res = api_client.resolve_case(case_id, create_resolve_payload(outcome), headers)
    return get_success_data(res)


def assemble_payout(leader_id, target_period_index):
    res = api_client.create_payout(
        leader_id, create_payout_payload(target_period_index), ADMIN
    )
    return get_success_data(res)


def advance_clock(by_periods):
    res = api_client.advance_clock(by_periods, ADMIN)
    return get_success_data(res)


def run_payouts_sweep():
    res = api_client.run_payouts_sweep(ADMIN)
    return get_success_data(res)


def recompute_risk():
    res = api_client.recompute_risk_sweep(ADMIN)
    return get_success_data(res)


# ─── Tier 6: Multi-customer helpers ───────────────────

def setup_multi_customer_paid(num_customers=5, unit_price_cents=100, discount_tiers=None,
                                deadline_period=100):
    """Build a campaign with N customers each placing+paying one order. Returns scaffold + customers list + campaign + orders list (still PAID — not closed)."""
    if discount_tiers is None:
        discount_tiers = [{"min_participants": 1, "discount_basis_points": 0}]
    community = create_community(region_code="RC1")
    supplier = create_supplier(name="S1")
    create_warehouse(supplier["id"], region_code="RC1")
    leader = create_active_leader(community["id"], display_name="L1")
    pickup = create_pickup_point(community["id"], capacity_packages=10, cold_storage_capable=True)
    customers = [create_customer(community["id"], display_name=f"Cust{i}") for i in range(num_customers)]
    campaign = create_group_buy_campaign(
        leader["id"], supplier["id"],
        sku="SKUA", unit_price_cents=unit_price_cents,
        discount_tiers=discount_tiers,
        opens_at_period=0, deadline_period=deadline_period,
    )
    orders = []
    for cust in customers:
        order = join_campaign(campaign["id"], cust["id"],
                              line_items=[{"sku": "SKUA", "unit_price_cents": unit_price_cents, "quantity": 1}])
        order = pay_order(order["id"], cust["id"])
        orders.append(order)
    return {
        "community": community,
        "supplier": supplier,
        "leader": leader,
        "pickup_point": pickup,
        "customers": customers,
        "campaign": campaign,
        "orders": orders,
    }


def find_commission_entry(leader_id, order_id):
    """Locate a CommissionEntry for (leader_id, order_id). Returns entry dict or None."""
    res = api_client.list_commission_entries(leader_id, ADMIN)
    data = get_success_data(res)
    if isinstance(data, dict) and "items" in data:
        entries = data["items"]
    elif isinstance(data, list):
        entries = data
    else:
        entries = data
    for e in entries:
        if e.get("order_id") == order_id and e.get("leader_id") == leader_id:
            return e
    return None


def list_commission_entries(leader_id):
    res = api_client.list_commission_entries(leader_id, ADMIN)
    data = get_success_data(res)
    if isinstance(data, dict) and "items" in data:
        return data["items"]
    elif isinstance(data, list):
        return data
    return data
