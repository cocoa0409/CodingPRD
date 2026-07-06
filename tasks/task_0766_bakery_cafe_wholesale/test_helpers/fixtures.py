"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted, empty server). Helpers use
get_success_data() so a broken setup surfaces as a clear "Setup failed" error
rather than a confusing downstream assertion.
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import TEST_USERS
from . import factories as f

MANAGER = TEST_USERS["manager_headers"]


# ------------------------------------------------------------------ primitives
def set_clock(api, iso, headers=MANAGER):
    return get_success_data(api.set_clock(iso, headers))


def make_product(api, headers=MANAGER, **overrides):
    return get_success_data(api.create_product(f.create_product_payload(**overrides), headers))


def make_oven(api, headers=MANAGER, **overrides):
    return get_success_data(api.create_oven(f.create_oven_payload(**overrides), headers))


def make_account(api, headers=MANAGER, **overrides):
    return get_success_data(
        api.create_wholesale_account(f.create_wholesale_account_payload(**overrides), headers))


def make_bake_plan(api, headers=MANAGER, **overrides):
    return get_success_data(api.create_bake_plan(f.create_bake_plan_payload(**overrides), headers))


def add_line(api, plan_id, product_id, par_qty, headers=MANAGER):
    payload = f.create_bake_plan_line_payload(product_id=product_id, par_qty=par_qty)
    return get_success_data(api.add_bake_plan_line(plan_id, payload, headers))


def commit_plan(api, plan_id, headers=MANAGER):
    return get_success_data(api.commit_bake_plan(plan_id, headers))


def make_bake_lot(api, line_id, oven_id, headers=MANAGER, **overrides):
    payload = f.create_bake_lot_payload(bake_plan_line_id=line_id, oven_id=oven_id, **overrides)
    return get_success_data(api.create_bake_lot(payload, headers))


def make_retail_sale(api, lot_id, qty, headers=MANAGER):
    payload = f.create_retail_sale_payload(bake_lot_id=lot_id, qty=qty)
    return get_success_data(api.create_retail_sale(payload, headers))


def make_standing_order(api, account_id, product_id, headers=MANAGER, **overrides):
    payload = f.create_standing_order_payload(
        wholesale_account_id=account_id, product_id=product_id, **overrides)
    return get_success_data(api.create_standing_order(payload, headers))


def make_delivery_order(api, account_id, product_id, line_id, headers=MANAGER, **overrides):
    payload = f.create_delivery_order_payload(
        wholesale_account_id=account_id, product_id=product_id,
        bake_plan_line_id=line_id, **overrides)
    return get_success_data(api.create_delivery_order(payload, headers))


def make_route(api, headers=MANAGER, **overrides):
    return get_success_data(api.create_delivery_route(f.create_delivery_route_payload(**overrides), headers))


def add_stop(api, route_id, order_id, headers=MANAGER, **overrides):
    payload = f.create_route_stop_payload(delivery_order_id=order_id, **overrides)
    return get_success_data(api.add_route_stop(route_id, payload, headers))


# ------------------------------------------------------- composite state builders
def setup_committed_line(api, base_price_cents=400, par_qty=20, shelf_life_hours=12,
                         production_date="2026-06-02T00:00:00Z", allergens=None,
                         category="BREAD", is_custom=False, headers=MANAGER):
    """Active product + DRAFT->COMMITTED bake plan holding one par line.

    Returns dict: {product, plan, line}. The plan is COMMITTED (par pool frozen).
    """
    prod_kwargs = dict(base_price_cents=base_price_cents, shelf_life_hours=shelf_life_hours,
                       category=category, is_custom=is_custom)
    if allergens is not None:
        prod_kwargs["allergens"] = allergens
    product = make_product(api, headers=headers, **prod_kwargs)
    plan = make_bake_plan(api, headers=headers, production_date=production_date)
    line = add_line(api, plan["id"], product["id"], par_qty, headers=headers)
    commit_plan(api, plan["id"], headers=headers)
    return {"product": product, "plan": plan, "line": line}


def setup_committed_line_with_account(api, base_price_cents=400, par_qty=20,
                                      shelf_life_hours=12, contract_tier="STANDARD",
                                      credit_limit_cents=1_000_000, allergen_restrictions=None,
                                      production_date="2026-06-02T00:00:00Z",
                                      allergens=None, headers=MANAGER):
    """setup_committed_line plus one ACTIVE wholesale account. Returns
    {product, plan, line, account}."""
    ctx = setup_committed_line(api, base_price_cents=base_price_cents, par_qty=par_qty,
                               shelf_life_hours=shelf_life_hours, allergens=allergens,
                               production_date=production_date, headers=headers)
    acct_kwargs = dict(contract_tier=contract_tier, credit_limit_cents=credit_limit_cents)
    if allergen_restrictions is not None:
        acct_kwargs["allergen_restrictions"] = allergen_restrictions
    ctx["account"] = make_account(api, headers=headers, **acct_kwargs)
    return ctx


def setup_lot(api, base_price_cents=400, par_qty=20, shelf_life_hours=12, baked_qty=10,
              produced_at="2026-06-02T06:00:00Z", slot_start="2026-06-02T02:00:00Z",
              slot_end="2026-06-02T03:00:00Z", production_date="2026-06-02T00:00:00Z",
              category="BREAD", headers=MANAGER):
    """Committed line + one oven + one FRESH BakeLot. Returns
    {product, plan, line, oven, lot}."""
    ctx = setup_committed_line(api, base_price_cents=base_price_cents, par_qty=par_qty,
                               shelf_life_hours=shelf_life_hours, category=category,
                               production_date=production_date, headers=headers)
    ctx["oven"] = make_oven(api, headers=headers)
    ctx["lot"] = make_bake_lot(api, ctx["line"]["id"], ctx["oven"]["id"], headers=headers,
                               baked_qty=baked_qty, produced_at=produced_at,
                               slot_start=slot_start, slot_end=slot_end)
    return ctx


def deliver_order(api, account_id, product_id, line_id, qty=1,
                  delivery_date="2026-06-02T10:00:00Z", headers=MANAGER):
    """Create -> pack -> deliver an order (counter delivery). Returns the delivered order."""
    order = make_delivery_order(api, account_id, product_id, line_id, headers=headers,
                                qty=qty, delivery_date=delivery_date)
    get_success_data(api.pack_delivery_order(order["id"], headers))
    return get_success_data(api.deliver_delivery_order(order["id"], headers))


def get_line(api, line_id, headers=MANAGER):
    return get_success_data(api.get_bake_plan_line(line_id, headers))


def get_lot(api, lot_id, headers=MANAGER):
    return get_success_data(api.get_bake_lot(lot_id, headers))


def get_order(api, order_id, headers=MANAGER):
    return get_success_data(api.get_delivery_order(order_id, headers))


def get_account(api, account_id, headers=MANAGER):
    return get_success_data(api.get_wholesale_account(account_id, headers))


def get_route(api, route_id, headers=MANAGER):
    return get_success_data(api.get_delivery_route(route_id, headers))


def get_stop(api, stop_id, headers=MANAGER):
    return get_success_data(api.get_route_stop(stop_id, headers))


def get_standing_order(api, so_id, headers=MANAGER):
    return get_success_data(api.get_standing_order(so_id, headers))


def get_plan(api, plan_id, headers=MANAGER):
    return get_success_data(api.get_bake_plan(plan_id, headers))
