"""Composite setup helpers for Pool & Spa Maintenance tests.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, because the test harness restarts the server (empty DB) before each
test. Helpers use get_success_data() (lenient) internally so setup failures
surface as clear "Setup failed" errors.

Identity threading: when an ownership-gated Customer call is needed (work-order
hold / resolve), the helper threads the owning Customer.id through
make_customer_headers(customer_id) — never the shared TEST_USERS constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_customer_headers
from . import factories as F


AM = TEST_USERS["account_manager_headers"]
RM = TEST_USERS["route_manager_headers"]
FT = TEST_USERS["field_technician_headers"]


# ---------------------------------------------------------------------------
# Tier 0: atomic creators
# ---------------------------------------------------------------------------
def create_customer(**overrides) -> dict:
    resp = api_client.create_customer(F.create_customer_payload(**overrides), AM)
    return get_success_data(resp)


def create_pool(customer_id=None, **overrides) -> dict:
    if customer_id is None:
        customer_id = create_customer()["id"]
    resp = api_client.create_pool(F.create_pool_payload(customer_id, **overrides), AM)
    return get_success_data(resp)


def create_plan(pool_id, **overrides) -> dict:
    resp = api_client.create_service_plan(F.create_service_plan_payload(pool_id, **overrides), AM)
    return get_success_data(resp)


def create_active_plan(pool_id, **overrides) -> dict:
    plan = create_plan(pool_id, **overrides)
    get_success_data(api_client.activate_service_plan(plan["id"], AM))
    return get_success_data(api_client.get_service_plan(plan["id"], AM))


def create_route(**overrides) -> dict:
    resp = api_client.create_route(F.create_route_payload(**overrides), RM)
    return get_success_data(resp)


def create_visit(pool_id, plan_id, route_id, **overrides) -> dict:
    resp = api_client.create_visit(F.create_visit_payload(pool_id, plan_id, route_id, **overrides), RM)
    return get_success_data(resp)


def open_pool(pool_id, effective_date="2026-06-10") -> dict:
    """Drive a CLOSED pool to OPEN via a seasonal OPEN event + apply."""
    se = get_success_data(
        api_client.create_seasonal_event(pool_id, F.create_seasonal_event_payload("OPEN", effective_date=effective_date), RM)
    )
    get_success_data(api_client.apply_seasonal_event(se["id"], RM))
    return get_success_data(api_client.get_pool(pool_id, AM))


# ---------------------------------------------------------------------------
# Tier 1/2: hierarchy reaching a DISPATCHED route + OPEN pool + SCHEDULED visit
# ---------------------------------------------------------------------------
def setup_open_pool_dispatched_visit(
    water_type="CHLORINE",
    volume_gallons=20000,
    plan_type="ONE_TIME",
    frequency="NONE",
    per_visit_rate_cents=8000,
    prepaid_visit_count=None,
    slot_start_minute=540,
    slot_end_minute=600,
    capacity_visits=5,
):
    """Customer + pool(OPEN) + ACTIVE plan + DISPATCHED route + one SCHEDULED visit.

    Returns dict with keys: customer, pool, plan, route, visit.
    The route is dispatched (requires >=1 SCHEDULED visit) AFTER the visit and
    AFTER the pool is opened, matching the design-index call order.
    """
    customer = create_customer()
    pool = create_pool(customer["id"], water_type=water_type, volume_gallons=volume_gallons)
    plan_overrides = dict(plan_type=plan_type, frequency=frequency, per_visit_rate_cents=per_visit_rate_cents)
    if prepaid_visit_count is not None:
        plan_overrides["prepaid_visit_count"] = prepaid_visit_count
    plan = create_active_plan(pool["id"], **plan_overrides)
    route = create_route(capacity_visits=capacity_visits)
    visit = create_visit(pool["id"], plan["id"], route["id"],
                         slot_start_minute=slot_start_minute, slot_end_minute=slot_end_minute)
    open_pool(pool["id"])
    get_success_data(api_client.dispatch_route(route["id"], RM))
    return {
        "customer": customer,
        "pool": get_success_data(api_client.get_pool(pool["id"], AM)),
        "plan": get_success_data(api_client.get_service_plan(plan["id"], AM)),
        "route": get_success_data(api_client.get_route(route["id"], RM)),
        "visit": get_success_data(api_client.get_visit(visit["id"], RM)),
    }


def setup_scheduled_visit_planned_route(
    plan_type="RECURRING",
    frequency="WEEKLY",
    per_visit_rate_cents=6000,
    capacity_visits=5,
    slot_start_minute=540,
    slot_end_minute=600,
):
    """Customer + pool(still CLOSED) + ACTIVE plan + PLANNED route + one SCHEDULED
    visit (no dispatch, no open). For skip / cancel / interval / capacity tests
    that don't require an OPEN pool. Returns dict: customer, pool, plan, route, visit."""
    customer = create_customer()
    pool = create_pool(customer["id"])
    plan = create_active_plan(pool["id"], plan_type=plan_type, frequency=frequency,
                              per_visit_rate_cents=per_visit_rate_cents)
    route = create_route(capacity_visits=capacity_visits)
    visit = create_visit(pool["id"], plan["id"], route["id"],
                         slot_start_minute=slot_start_minute, slot_end_minute=slot_end_minute)
    return {"customer": customer, "pool": pool, "plan": plan, "route": route, "visit": visit}


# ---------------------------------------------------------------------------
# Tier 3: green-recovery state (pool in GREEN_RECOVERY with auto recovery visit)
# ---------------------------------------------------------------------------
def setup_green_recovery_pool(
    volume_gallons=20000,
    plan_type="RECURRING",
    frequency="WEEKLY",
    per_visit_rate_cents=6000,
):
    """Complete a green-pool initial visit so the pool flips OPEN -> GREEN_RECOVERY
    and an auto RECOVERY_SCHEDULED follow-up visit is created.

    Returns dict: customer, pool, plan, route, initial_visit, recovery_visit.
    The recovery visit is located via GET /routes/{id}/visits (index [1]).
    """
    base = setup_open_pool_dispatched_visit(
        volume_gallons=volume_gallons, plan_type=plan_type, frequency=frequency,
        per_visit_rate_cents=per_visit_rate_cents,
    )
    get_success_data(api_client.complete_visit(base["visit"]["id"], F.complete_payload(green_pool=True), FT))
    visits, _ = _list_route_visits(base["route"]["id"])
    recovery = next(v for v in visits if v["status"] == "RECOVERY_SCHEDULED")
    return {
        "customer": base["customer"],
        "pool": get_success_data(api_client.get_pool(base["pool"]["id"], AM)),
        "plan": base["plan"],
        "route": base["route"],
        "initial_visit": get_success_data(api_client.get_visit(base["visit"]["id"], RM)),
        "recovery_visit": recovery,
    }


def _list_route_visits(route_id):
    resp = api_client.list_route_visits(route_id, RM, params={"limit": 100})
    body = resp.json()
    return body["data"], body["meta"]


# ---------------------------------------------------------------------------
# Tier 3: work-order lifecycle
# ---------------------------------------------------------------------------
def setup_work_order_awaiting_approval(
    severity="MAJOR",
    component="PUMP",
    quoted_parts_cents=5000,
    labor_minutes=90,
):
    """Customer-owned pool + work order driven OPEN -> DIAGNOSED -> AWAITING_APPROVAL.

    Returns dict: customer, pool, work_order. The customer owns the pool, so
    customer_headers (built from customer id) authorize hold/resolve.
    """
    customer = create_customer()
    pool = create_pool(customer["id"])
    wo = get_success_data(api_client.create_work_order(
        F.create_work_order_payload(pool["id"], component=component, severity=severity), FT))
    get_success_data(api_client.diagnose_work_order(
        wo["id"], F.diagnose_payload(quoted_parts_cents=quoted_parts_cents, labor_minutes=labor_minutes), FT))
    get_success_data(api_client.submit_work_order_for_approval(wo["id"], FT))
    return {
        "customer": customer,
        "pool": pool,
        "work_order": get_success_data(api_client.get_work_order(wo["id"], FT)),
        "customer_headers": make_customer_headers(customer["id"]),
    }


def setup_resolved_work_order(
    severity="MINOR",
    component="FILTER",
    quoted_parts_cents=0,
    labor_minutes=30,
):
    """Work order driven all the way to RESOLVED (customer approves).
    Returns dict: customer, pool, work_order, customer_headers."""
    ctx = setup_work_order_awaiting_approval(
        severity=severity, component=component,
        quoted_parts_cents=quoted_parts_cents, labor_minutes=labor_minutes)
    get_success_data(api_client.resolve_work_order(ctx["work_order"]["id"], ctx["customer_headers"]))
    ctx["work_order"] = get_success_data(api_client.get_work_order(ctx["work_order"]["id"], FT))
    return ctx


# ---------------------------------------------------------------------------
# Tier 3/4: completed visit + draft invoice (billing chains)
# ---------------------------------------------------------------------------
def setup_completed_visit(green_pool=False, volume_gallons=20000, per_visit_rate_cents=8000,
                          plan_type="ONE_TIME", frequency="NONE", prepaid_visit_count=None):
    """Customer + OPEN pool + DISPATCHED route + a COMPLETED visit.
    Returns dict: customer, pool, plan, route, visit (the completed visit)."""
    base = setup_open_pool_dispatched_visit(
        volume_gallons=volume_gallons, per_visit_rate_cents=per_visit_rate_cents,
        plan_type=plan_type, frequency=frequency, prepaid_visit_count=prepaid_visit_count)
    get_success_data(api_client.complete_visit(base["visit"]["id"], F.complete_payload(green_pool=green_pool), FT))
    base["visit"] = get_success_data(api_client.get_visit(base["visit"]["id"], RM))
    return base


def setup_draft_invoice_for_visit(green_pool=True, volume_gallons=20000, per_visit_rate_cents=8000):
    """Completed visit (green initial by default => billed 26000 at vol 20000) +
    a DRAFT invoice referencing it. Returns dict: customer, pool, plan, route,
    visit, invoice."""
    ctx = setup_completed_visit(green_pool=green_pool, volume_gallons=volume_gallons,
                                per_visit_rate_cents=per_visit_rate_cents)
    inv = get_success_data(api_client.create_invoice(
        F.create_invoice_payload(ctx["pool"]["id"], visit_id=ctx["visit"]["id"]), AM))
    ctx["invoice"] = inv
    return ctx


def setup_issued_invoice_for_visit(green_pool=True, volume_gallons=20000, per_visit_rate_cents=8000):
    """As setup_draft_invoice_for_visit but the invoice is ISSUED.
    Returns dict: customer, pool, plan, route, visit, invoice."""
    ctx = setup_draft_invoice_for_visit(green_pool=green_pool, volume_gallons=volume_gallons,
                                        per_visit_rate_cents=per_visit_rate_cents)
    get_success_data(api_client.issue_invoice(ctx["invoice"]["id"], AM))
    ctx["invoice"] = get_success_data(api_client.get_invoice(ctx["invoice"]["id"], AM))
    return ctx
