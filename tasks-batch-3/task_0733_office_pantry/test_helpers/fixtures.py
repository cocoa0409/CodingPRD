"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures produce clear
"Setup failed" errors, not confusing assertion failures.

Identity threading: every fixture that creates a Client or Location threads
its id through make_client_admin_headers(client_id) / make_location_manager_headers(location_id)
so ownership-gated downstream calls succeed.
"""
import uuid
from typing import Optional, List, Dict, Any, Tuple

from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_plan_payload,
    create_client_payload,
    create_location_payload,
    create_product_payload,
    create_preference_payload,
    create_par_level_payload,
    create_subscription_payload,
    create_delivery_payload,
    create_dispute_payload,
    create_feedback_payload,
    create_headcount_patch_payload,
    create_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_client_admin_headers,
    make_location_manager_headers,
)


# ─────────────────────────────────────────────────────────────
# Tier 1 — Primitive helpers (one API call per, with identity threading)
# ─────────────────────────────────────────────────────────────

def _admin():
    return TEST_USERS["platform_admin_headers"]


def set_clock(iso: str) -> None:
    """Set the server logical clock to `iso` (as PlatformAdmin)."""
    res = api_client.set_clock(create_clock_payload(iso), _admin())
    get_success_data(res)


def create_plan(**overrides) -> dict:
    """Create a Plan. Defaults to a FLAT plan with flat_fee_cents=1000, threshold=50."""
    # Unique tier so we can re-run in the same test process (though harness restarts DB per test).
    if "tier" not in overrides:
        overrides["tier"] = f"T-{uuid.uuid4().hex[:8]}"
    res = api_client.create_plan(create_plan_payload(**overrides), _admin())
    return get_success_data(res)


def create_client(**overrides) -> dict:
    """Create a Client. Returns the Client dict (contains version, credit_balance_cents, etc.)."""
    if "name" not in overrides:
        overrides["name"] = f"Client-{uuid.uuid4().hex[:8]}"
    res = api_client.create_client(create_client_payload(**overrides), _admin())
    return get_success_data(res)


def create_location(client_id: str, **overrides) -> dict:
    """Create a Location on the given client. Uses ClientAdmin identity threaded to client_id."""
    if "name" not in overrides:
        overrides["name"] = f"Loc-{uuid.uuid4().hex[:6]}"
    res = api_client.create_location(
        client_id,
        create_location_payload(**overrides),
        make_client_admin_headers(client_id),
    )
    return get_success_data(res)


def create_product(**overrides) -> dict:
    """Create a Product."""
    if "sku" not in overrides:
        overrides["sku"] = f"SKU-{uuid.uuid4().hex[:8]}"
    res = api_client.create_product(create_product_payload(**overrides), _admin())
    return get_success_data(res)


def create_preference(client_id: str, dietary_flag: str) -> dict:
    """Create a dietary Preference on a client."""
    res = api_client.create_preference(
        client_id,
        create_preference_payload(dietary_flag=dietary_flag),
        make_client_admin_headers(client_id),
    )
    return get_success_data(res)


def create_par_level(location_id: str, product_id: str, par_units: int) -> dict:
    """Create a ParLevel at a Location."""
    res = api_client.create_par_level(
        location_id,
        create_par_level_payload(product_id=product_id, par_units=par_units),
        make_location_manager_headers(location_id),
    )
    return get_success_data(res)


def create_subscription(client_id: str, plan_id: str, expected_client_version: int) -> dict:
    """Create a Subscription (DRAFT)."""
    res = api_client.create_subscription(
        client_id,
        create_subscription_payload(plan_id, expected_client_version),
        make_client_admin_headers(client_id),
    )
    return get_success_data(res)


def activate_subscription(subscription_id: str) -> dict:
    res = api_client.activate_subscription(subscription_id, _admin())
    return get_success_data(res)


def get_first_rotation_cycle(subscription_id: str) -> dict:
    res = api_client.list_subscription_rotation_cycles(subscription_id, _admin())
    data = get_success_data(res)
    # data is the payload; the framework's list envelope returns a list under data
    if isinstance(data, list):
        return data[0]
    return data


def create_delivery(rotation_cycle_id: str, location_id: str, scheduled_at: str) -> dict:
    res = api_client.create_delivery(
        rotation_cycle_id,
        create_delivery_payload(location_id, scheduled_at),
        _admin(),
    )
    return get_success_data(res)


def dispatch_delivery(delivery_id: str) -> dict:
    res = api_client.dispatch_delivery(delivery_id, _admin())
    return get_success_data(res)


def confirm_delivery(delivery_id: str, location_id: str) -> dict:
    res = api_client.confirm_delivery(delivery_id, make_location_manager_headers(location_id))
    return get_success_data(res)


def dispute_delivery(delivery_id: str, location_id: str, reason: str = "shortship") -> dict:
    res = api_client.dispute_delivery(
        delivery_id, create_dispute_payload(reason), make_location_manager_headers(location_id)
    )
    return get_success_data(res)


def resolve_delivery_dispute(delivery_id: str) -> dict:
    res = api_client.resolve_delivery_dispute(delivery_id, _admin())
    return get_success_data(res)


def finalize_delivery(delivery_id: str) -> dict:
    res = api_client.finalize_delivery(delivery_id, _admin())
    return get_success_data(res)


def patch_delivery_line_actual(delivery_line_id: str, location_id: str, actual_units: int) -> dict:
    res = api_client.patch_delivery_line_actual(
        delivery_line_id,
        {"actual_units": actual_units},
        make_location_manager_headers(location_id),
    )
    return get_success_data(res)


def list_delivery_lines(delivery_id: str) -> list:
    res = api_client.list_delivery_lines_for_delivery(delivery_id, _admin())
    data = get_success_data(res)
    if isinstance(data, list):
        return data
    return data


def close_rotation_cycle(rotation_cycle_id: str) -> dict:
    res = api_client.close_rotation_cycle(rotation_cycle_id, _admin())
    return get_success_data(res)


def pause_subscription(subscription_id: str, client_id: str) -> dict:
    res = api_client.pause_subscription(subscription_id, make_client_admin_headers(client_id))
    return get_success_data(res)


def resume_subscription(subscription_id: str, client_id: str) -> dict:
    res = api_client.resume_subscription(subscription_id, make_client_admin_headers(client_id))
    return get_success_data(res)


def cancel_subscription(subscription_id: str, client_id: str) -> dict:
    res = api_client.cancel_subscription(subscription_id, make_client_admin_headers(client_id))
    return get_success_data(res)


def pay_invoice(invoice_id: str, client_id: str) -> dict:
    res = api_client.pay_invoice(invoice_id, make_client_admin_headers(client_id))
    return get_success_data(res)


# ─────────────────────────────────────────────────────────────
# Tier 2 — Composite setups
# ─────────────────────────────────────────────────────────────

def setup_active_subscription(
    clock: str = "2026-06-01T00:00:00Z",
    plan_overrides: Optional[Dict[str, Any]] = None,
    client_overrides: Optional[Dict[str, Any]] = None,
    location_overrides: Optional[Dict[str, Any]] = None,
    product_overrides: Optional[Dict[str, Any]] = None,
    par_units: int = 1,
) -> Dict[str, Any]:
    """The canonical composite: clock -> plan -> client -> location -> product ->
    par-level -> subscription -> activate. Returns a dict with all handles.

    Fields:
      plan, client, location, product, par_level, subscription, rotation_cycle
    """
    set_clock(clock)
    plan = create_plan(**(plan_overrides or {}))
    client = create_client(**(client_overrides or {}))
    location = create_location(client["id"], **(location_overrides or {}))
    product = create_product(**(product_overrides or {}))
    par_level = create_par_level(location["id"], product["id"], par_units)
    sub = create_subscription(client["id"], plan["id"], client["version"])
    sub_active = activate_subscription(sub["id"])
    rc = get_first_rotation_cycle(sub["id"])
    return {
        "plan": plan,
        "client": client,
        "location": location,
        "product": product,
        "par_level": par_level,
        "subscription": sub_active,
        "rotation_cycle": rc,
    }


def setup_draft_subscription(
    clock: str = "2026-06-01T00:00:00Z",
    plan_overrides: Optional[Dict[str, Any]] = None,
    client_overrides: Optional[Dict[str, Any]] = None,
    location_overrides: Optional[Dict[str, Any]] = None,
    product_overrides: Optional[Dict[str, Any]] = None,
    par_units: int = 1,
) -> Dict[str, Any]:
    """Same as setup_active_subscription but stops at DRAFT (no activate).
    Useful for testing activation preconditions."""
    set_clock(clock)
    plan = create_plan(**(plan_overrides or {}))
    client = create_client(**(client_overrides or {}))
    location = create_location(client["id"], **(location_overrides or {}))
    product = create_product(**(product_overrides or {}))
    par_level = create_par_level(location["id"], product["id"], par_units)
    sub = create_subscription(client["id"], plan["id"], client["version"])
    return {
        "plan": plan,
        "client": client,
        "location": location,
        "product": product,
        "par_level": par_level,
        "subscription": sub,
    }


def setup_scheduled_delivery(
    clock: str = "2026-06-01T00:00:00Z",
    scheduled_at: str = "2026-06-01T12:00:00Z",
    location_overrides: Optional[Dict[str, Any]] = None,
    product_overrides: Optional[Dict[str, Any]] = None,
    par_units: int = 10,
    plan_overrides: Optional[Dict[str, Any]] = None,
    client_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Composite through delivery creation: ACTIVE sub + OPEN RC + one SCHEDULED Delivery.
    Returns state dict with additional 'delivery' key."""
    state = setup_active_subscription(
        clock=clock,
        plan_overrides=plan_overrides,
        client_overrides=client_overrides,
        location_overrides=location_overrides,
        product_overrides=product_overrides,
        par_units=par_units,
    )
    delv = create_delivery(state["rotation_cycle"]["id"], state["location"]["id"], scheduled_at)
    state["delivery"] = delv
    return state


def setup_en_route_delivery(
    clock: str = "2026-06-01T00:00:00Z",
    scheduled_at: str = "2026-06-01T12:00:00Z",
    **kwargs,
) -> Dict[str, Any]:
    """SCHEDULED delivery + dispatch. Returns state with EN_ROUTE delivery and provisional_cents."""
    state = setup_scheduled_delivery(clock=clock, scheduled_at=scheduled_at, **kwargs)
    dispatched = dispatch_delivery(state["delivery"]["id"])
    state["delivery"] = dispatched
    return state


def setup_delivered_delivery(
    clock: str = "2026-06-01T00:00:00Z",
    scheduled_at: str = "2026-06-01T12:00:00Z",
    **kwargs,
) -> Dict[str, Any]:
    """EN_ROUTE + confirm -> DELIVERED."""
    state = setup_en_route_delivery(clock=clock, scheduled_at=scheduled_at, **kwargs)
    delivered = confirm_delivery(state["delivery"]["id"], state["location"]["id"])
    state["delivery"] = delivered
    return state


def setup_disputed_delivery(
    clock: str = "2026-06-01T00:00:00Z",
    scheduled_at: str = "2026-06-01T12:00:00Z",
    dispute_reason: str = "short-shipped",
    **kwargs,
) -> Dict[str, Any]:
    """DELIVERED + dispute -> DISPUTED."""
    state = setup_delivered_delivery(clock=clock, scheduled_at=scheduled_at, **kwargs)
    disputed = dispute_delivery(state["delivery"]["id"], state["location"]["id"], dispute_reason)
    state["delivery"] = disputed
    return state


def report_all_actuals_and_resolve(state: dict, actuals: List[int]) -> Dict[str, Any]:
    """Given state with a DISPUTED delivery, set actual_units on all lines
    (in order of GET /deliveries/{id}/lines) to values from `actuals`, then resolve.
    Mutates and returns state with the FINALIZED delivery."""
    lines = list_delivery_lines(state["delivery"]["id"])
    assert len(lines) == len(actuals), (
        f"actuals list has {len(actuals)} entries but delivery has {len(lines)} lines"
    )
    for line, actual in zip(lines, actuals):
        patch_delivery_line_actual(line["id"], state["location"]["id"], actual)
    resolved = resolve_delivery_dispute(state["delivery"]["id"])
    state["delivery"] = resolved
    return state


def close_and_get_invoice(state: dict, close_clock: str = "2026-07-05T00:00:00Z") -> Dict[str, Any]:
    """Advance clock past the RC window then close the rotation. Returns state with 'invoice'."""
    set_clock(close_clock)
    invoice = close_rotation_cycle(state["rotation_cycle"]["id"])
    state["invoice"] = invoice
    return state
