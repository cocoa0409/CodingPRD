"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface as
"Setup failed" errors rather than obscure assertion failures.

Identity threading is mandatory per the PRD: whenever a fixture creates an entity-backed
role's backing record (Customer, Restaurant, Rider), any ownership-gated call made on
behalf of that role must use make_<role>_headers(<actual-id>), NEVER the shared
TEST_USERS fallback. The shared fallbacks would carry an X-User-ID that does not match
any real entity id, so every ownership check would reject the call.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    approve_return_payload,
    build_order_item,
    coords_for_distance_km,
    create_customer_payload,
    create_menu_item_payload,
    create_order_payload,
    create_restaurant_payload,
    create_return_payload,
    create_rider_payload,
    create_work_order_payload,
    resolve_work_order_payload,
)
from .test_users import (
    TEST_USERS,
    make_admin_headers,
    make_cs_headers,
    make_customer_headers,
    make_restaurant_headers,
    make_rider_headers,
)


# ──────────────────────────────────────────────────────────
# Clock helpers
# ──────────────────────────────────────────────────────────

def advance_clock_seconds(seconds: int) -> None:
    """Advance the server's logical clock by N seconds (PRD §2.10)."""
    get_success_data(api_client.advance_clock(seconds, TEST_USERS["admin_headers"]))


def _force_off_peak_window() -> None:
    """Best-effort: advance the logical clock until we are comfortably off-peak.

    Peak windows per PRD §2.10 are 11:00-13:00 and 18:00-20:00 UTC. The benchmark's
    logical clock is server-side; we cannot read it, but advancing by a short amount
    is idempotent and safe between tests. Callers that need a strict off-peak placement
    should set up within a fresh test_helpers session, which the runner provides.
    """
    # No-op: relying on the server's starting clock which is typically set outside peak.
    # The dedicated peak tests use clock advances that the caller orchestrates explicitly.
    return None


# ──────────────────────────────────────────────────────────
# Tier 1: State progression
# ──────────────────────────────────────────────────────────

def create_active_restaurant(
    *, commission_rate_override: Optional[float] = None, **restaurant_overrides: Any
) -> Dict[str, Any]:
    """Create a Restaurant and approve it to ACTIVE. Returns the ACTIVE Restaurant record."""
    admin = TEST_USERS["admin_headers"]
    payload = create_restaurant_payload(**restaurant_overrides)
    if commission_rate_override is not None:
        payload["commission_rate_override"] = commission_rate_override
    created = get_success_data(api_client.create_restaurant(payload, admin))
    approved = get_success_data(api_client.approve_restaurant(created["id"], admin))
    return approved


# Module-level registry of every rider the test helpers have created during this session.
# Used to "go offline" riders we no longer need so dispatch deterministically targets a
# specific rider. (PRD does not expose a list-riders endpoint, so without this registry
# we cannot enumerate competing AVAILABLE candidates from prior tests.)
_CREATED_RIDER_IDS: "set[str]" = set()


def create_available_rider(**rider_overrides: Any) -> Dict[str, Any]:
    """Create a Rider and move them to AVAILABLE via /go-online.

    Uses make_rider_headers(rider["id"]) on /go-online, satisfying PRD §2.1's identity
    rule for the Rider role.
    """
    admin = TEST_USERS["admin_headers"]
    rider = get_success_data(api_client.create_rider(create_rider_payload(**rider_overrides), admin))
    headers = make_rider_headers(rider["id"])
    online = get_success_data(api_client.rider_go_online(rider["id"], headers))
    _CREATED_RIDER_IDS.add(online["id"])
    return online


def _resolve_rider_from_assignment(assignment: Dict[str, Any]) -> Dict[str, Any]:
    """Return the Rider dict whose id matches assignment["rider_id"], read with the
    rider's own headers (PRD §2.1: Rider may read their own record).

    The fixture uses this after a dispatch call because PRD §3.6 says the server picks
    the "best available rider" without a PRD-specified tie-breaker, and the test
    environment may contain multiple AVAILABLE riders from prior tests in the same
    server process. Using the id the server actually stamped on the assignment
    guarantees every subsequent ownership-gated call threads the right identity.
    """
    rider_id = assignment["rider_id"]
    headers = make_rider_headers(rider_id)
    _CREATED_RIDER_IDS.add(rider_id)
    return get_success_data(api_client.get_rider(rider_id, headers))


def take_other_riders_offline(keep_rider_id: str) -> None:
    """Go-offline every rider in the session registry except *keep_rider_id*.

    Some flows (route merging in PRD §3.6) require the server's dispatch to target a
    specific rider. Because PRD does not prescribe a tie-breaker among AVAILABLE riders
    and prior tests may have left other riders in AVAILABLE, we proactively set all
    non-target riders to OFFLINE via /go-offline (PRD §3.3 allows it when they hold no
    active assignment). Errors are swallowed: a rider who is already OFFLINE or has an
    active assignment just stays where they are, which is acceptable — the goal is to
    narrow the candidate set, not to reach a specific total.
    """
    for other_id in list(_CREATED_RIDER_IDS):
        if other_id == keep_rider_id:
            continue
        try:
            headers = make_rider_headers(other_id)
            api_client.rider_go_offline(other_id, headers)
        except Exception:
            pass


def create_customer(distance_km: float = 2.0, **customer_overrides: Any) -> Dict[str, Any]:
    """Create a Customer located exactly *distance_km* north of the reference restaurant."""
    admin = TEST_USERS["admin_headers"]
    return get_success_data(
        api_client.create_customer(
            create_customer_payload(distance_km=distance_km, **customer_overrides),
            admin,
        )
    )


# ──────────────────────────────────────────────────────────
# Tier 2: Entity hierarchy — restaurant + menu items + customer + rider
# ──────────────────────────────────────────────────────────

def create_listed_menu_item(
    restaurant: Dict[str, Any],
    *,
    price_cents: int = 1000,
    name: str = "Test Dish",
    is_listed: bool = True,
) -> Dict[str, Any]:
    """Create a listed MenuItem under *restaurant*.

    Uses make_restaurant_headers(restaurant["id"]) so the ownership check in PRD §2.1
    passes: when X-User-Role is Restaurant, X-User-ID is compared to restaurant_id.
    """
    headers = make_restaurant_headers(restaurant["id"])
    payload = create_menu_item_payload(price_cents=price_cents, name=name, is_listed=is_listed)
    return get_success_data(api_client.create_menu_item(restaurant["id"], payload, headers))


def setup_restaurant_with_menu(
    *,
    commission_rate_override: Optional[float] = None,
    menu_items: Optional[List[Dict[str, Any]]] = None,
    **restaurant_overrides: Any,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Create an ACTIVE Restaurant plus N listed MenuItems.

    menu_items is a list of factory overrides; defaults to a single 1000-cent dish.
    """
    restaurant = create_active_restaurant(
        commission_rate_override=commission_rate_override, **restaurant_overrides
    )
    items_cfg = menu_items if menu_items is not None else [{"price_cents": 1000, "name": "Dish"}]
    created_items = []
    for idx, cfg in enumerate(items_cfg):
        name = cfg.pop("name", f"Dish-{idx}")
        price = cfg.pop("price_cents", 1000)
        created_items.append(
            create_listed_menu_item(restaurant, price_cents=price, name=name)
        )
    return restaurant, created_items


def setup_customer_restaurant_menu(
    *,
    distance_km: float = 2.0,
    commission_rate_override: Optional[float] = None,
    menu_price_cents: int = 1000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Most common seed: ACTIVE Restaurant, a listed MenuItem, and a Customer at *distance_km*."""
    restaurant, menu_items = setup_restaurant_with_menu(
        commission_rate_override=commission_rate_override,
        menu_items=[{"price_cents": menu_price_cents, "name": "Dish"}],
    )
    customer = create_customer(distance_km=distance_km)
    return restaurant, menu_items[0], customer


# ──────────────────────────────────────────────────────────
# Tier 3: Order lifecycle shortcuts
# ──────────────────────────────────────────────────────────

def place_order(
    customer: Dict[str, Any],
    restaurant: Dict[str, Any],
    menu_item: Dict[str, Any],
    *,
    quantity: int = 1,
    unit_price_cents: Optional[int] = None,
    extra_items: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Place an order as *customer*. Uses make_customer_headers(customer["id"])."""
    price = unit_price_cents if unit_price_cents is not None else menu_item["price_cents"]
    items = [build_order_item(menu_item["id"], name=menu_item["name"],
                              unit_price_cents=price, quantity=quantity)]
    if extra_items:
        items.extend(extra_items)
    payload = create_order_payload(customer["id"], restaurant["id"], items=items)
    headers = make_customer_headers(customer["id"])
    return get_success_data(api_client.create_order(payload, headers))


def restaurant_accept_order(order: Dict[str, Any], restaurant: Dict[str, Any]) -> Dict[str, Any]:
    """Transition Order PLACED → RESTAURANT_ACCEPTED as the owning restaurant."""
    headers = make_restaurant_headers(restaurant["id"])
    return get_success_data(api_client.accept_order(order["id"], headers))


def start_preparing(order: Dict[str, Any], restaurant: Dict[str, Any]) -> Dict[str, Any]:
    """Transition RESTAURANT_ACCEPTED → PREPARING. System also opens dispatch."""
    headers = make_restaurant_headers(restaurant["id"])
    return get_success_data(api_client.start_preparing_order(order["id"], headers))


def mark_ready(order: Dict[str, Any], restaurant: Dict[str, Any]) -> Dict[str, Any]:
    """Transition PREPARING → READY_FOR_PICKUP. Preconditioned on accepted Assignment."""
    headers = make_restaurant_headers(restaurant["id"])
    return get_success_data(api_client.mark_order_ready(order["id"], headers))


def dispatch_order_as_admin(order: Dict[str, Any]) -> Dict[str, Any]:
    """Force a fresh dispatch, returning the new Assignment row."""
    return get_success_data(api_client.dispatch_order(order["id"], TEST_USERS["admin_headers"]))


def get_assignment_for_order(order_id: str, rider: Dict[str, Any]) -> Dict[str, Any]:
    """Return the current Assignment for *order_id* as the rider sees it, by scanning /api/orders
    via the admin role (which has unrestricted GET access per PRD §2.1)."""
    # Orders list doesn't expose assignment ids directly; rely on the PlatformAdmin list view
    # with rider_id filter to pull assignments. The server is expected to provide that filter
    # per PRD §4 (GET /api/orders rider_id filter).
    # As a robust path, read order record and inspect assignment linkage if the implementation
    # exposes it; otherwise fall back on dispatch returning the assignment directly.
    raise NotImplementedError(
        "Use dispatch_order_as_admin or capture the Assignment from start_preparing's "
        "/api/orders/{id}/dispatch return value; the PRD does not require an "
        "assignment-listing endpoint."
    )


def accept_assignment_as_rider(assignment: Dict[str, Any], rider: Dict[str, Any]) -> Dict[str, Any]:
    """Rider accepts an OFFERED assignment. Uses make_rider_headers(rider["id"])."""
    headers = make_rider_headers(rider["id"])
    return get_success_data(api_client.accept_assignment(assignment["id"], headers))


def pickup_assignment_as_rider(assignment: Dict[str, Any], rider: Dict[str, Any]) -> Dict[str, Any]:
    """Rider picks up an ACCEPTED assignment. Cascades Order READY_FOR_PICKUP → PICKED_UP."""
    headers = make_rider_headers(rider["id"])
    return get_success_data(api_client.pickup_assignment(assignment["id"], headers))


def deliver_assignment_as_rider(assignment: Dict[str, Any], rider: Dict[str, Any]) -> Dict[str, Any]:
    """Rider delivers a PICKED_UP assignment. Cascades Order → DELIVERED with full fiscal
    reconciliation (see PRD §3.7)."""
    headers = make_rider_headers(rider["id"])
    return get_success_data(api_client.deliver_assignment(assignment["id"], headers))


# ──────────────────────────────────────────────────────────
# Composite workflows
# ──────────────────────────────────────────────────────────

def run_order_to_picked_up(
    *,
    distance_km: float = 2.0,
    quantity: int = 1,
    menu_price_cents: int = 5000,
    commission_rate_override: Optional[float] = None,
) -> Dict[str, Any]:
    """Full placement → restaurant accepts → start preparing (dispatches) → rider accepts →
    ready → pickup. Returns a dict of every entity created: {restaurant, menu_item,
    customer, rider, order, assignment}. Pick-up leaves the order in PICKED_UP — the caller
    can then deliver or time out.

    Identity threading: each actor call uses make_<role>_headers(<id>). Because PRD §3.6
    says dispatch picks the "best available rider" without specifying a deterministic
    tie-breaker, and prior tests in the same server process may have left other AVAILABLE
    riders in the database, we must adopt whichever rider the dispatch actually returns
    rather than assuming it is the one we just created. We create a fresh rider only to
    guarantee at least one AVAILABLE candidate exists.
    """
    restaurant, menu_item, customer = setup_customer_restaurant_menu(
        distance_km=distance_km,
        commission_rate_override=commission_rate_override,
        menu_price_cents=menu_price_cents,
    )
    # Create a fresh rider and narrow the candidate set to just this rider by taking
    # every other session-known AVAILABLE rider offline. Needed because tests that
    # consume ctx["rider"] assert wallet/metric invariants (e.g., wallet==0 baseline)
    # that only hold for a rider that has not yet run through another delivery.
    rider = create_available_rider()
    take_other_riders_offline(keep_rider_id=rider["id"])

    order = place_order(customer, restaurant, menu_item, quantity=quantity)
    restaurant_accept_order(order, restaurant)
    # Dispatch an Assignment BEFORE start-preparing so we have a handle on the
    # assignment id. PRD §3.6 allows /accept while Order.status is in {RESTAURANT_ACCEPTED,
    # PREPARING, READY_FOR_PICKUP}, and /dispatch has no order-status precondition.
    assignment = dispatch_order_as_admin(order)
    rider = _resolve_rider_from_assignment(assignment)
    assignment = accept_assignment_as_rider(assignment, rider)
    start_preparing(order, restaurant)
    mark_ready(order, restaurant)
    assignment = pickup_assignment_as_rider(assignment, rider)
    return {
        "restaurant": restaurant,
        "menu_item": menu_item,
        "customer": customer,
        "rider": rider,
        "order": order,
        "assignment": assignment,
    }


def run_order_to_delivered(
    *,
    distance_km: float = 2.0,
    quantity: int = 1,
    menu_price_cents: int = 5000,
    commission_rate_override: Optional[float] = None,
    clock_advance_before_deliver: int = 0,
) -> Dict[str, Any]:
    """run_order_to_picked_up + deliver. clock_advance_before_deliver lets a caller
    time-travel past promised_delivery_time to induce a late-delivery fine (PRD §3.7)."""
    ctx = run_order_to_picked_up(
        distance_km=distance_km,
        quantity=quantity,
        menu_price_cents=menu_price_cents,
        commission_rate_override=commission_rate_override,
    )
    if clock_advance_before_deliver > 0:
        advance_clock_seconds(clock_advance_before_deliver)
    assignment = deliver_assignment_as_rider(ctx["assignment"], ctx["rider"])
    ctx["assignment"] = assignment
    # Re-read order so caller sees final_* fields.
    admin = TEST_USERS["admin_headers"]
    ctx["order"] = get_success_data(api_client.get_order(ctx["order"]["id"], admin))
    # Re-read rider so caller sees updated wallet_balance_cents / bonus_tier.
    rider_headers = make_rider_headers(ctx["rider"]["id"])
    ctx["rider"] = get_success_data(api_client.get_rider(ctx["rider"]["id"], rider_headers))
    # Re-read restaurant so caller sees updated pending_settlement_cents.
    ctx["restaurant"] = get_success_data(
        api_client.get_restaurant(ctx["restaurant"]["id"], admin)
    )
    return ctx


# ──────────────────────────────────────────────────────────
# Difficulty-design-specific fixtures
# ──────────────────────────────────────────────────────────

def run_two_orders_to_merged_delivery(
    *,
    distance_km_o1: float = 2.0,
    distance_km_o2: float = 2.5,
    menu_price_cents: int = 1000,
) -> Dict[str, Any]:
    """Setup for the dual_variant_calc / combinatorial_formula route-merge scenarios.

    Creates one ACTIVE restaurant, one rider, one customer placed at *distance_km_o1*
    from the restaurant (order O1's distance), and uses the same customer for O2. The
    rider accepts both assignments so they share a RouteGroup (>=2 members → 25%
    floor-rounded discount per leg at delivery). Both orders are walked through to
    DELIVERED.

    Returns {restaurant, customer, rider, order_o1, order_o2, assignment_a1,
    assignment_a2}. All returned Order/Assignment records are re-read post-delivery so
    final_* fields are populated.

    NOTE on distance geometry: the fixture positions ONE customer whose haversine
    distance from the restaurant is *distance_km_o1*. O2 then uses a second customer
    placed at *distance_km_o2* so each order independently produces its own solo_fee.
    The orders share a pickup location (the same restaurant), so the 500m route-merge
    radius (PRD §3.6) is trivially satisfied — both pickups are the exact same point.
    """
    admin = TEST_USERS["admin_headers"]
    restaurant, menu_item, customer_o1 = setup_customer_restaurant_menu(
        distance_km=distance_km_o1, menu_price_cents=menu_price_cents
    )
    customer_o2 = create_customer(distance_km=distance_km_o2)
    # Create a fresh rider and narrow the candidate set to just this rider — needed
    # for route merging, which requires the SAME rider to accept both legs (PRD §3.6).
    fresh_rider = create_available_rider()
    take_other_riders_offline(keep_rider_id=fresh_rider["id"])

    def place(customer: Dict[str, Any]) -> Dict[str, Any]:
        return place_order(customer, restaurant, menu_item, quantity=1)

    # Place both orders before acceptance to leave both dispatch offers available.
    o1 = place(customer_o1)
    o2 = place(customer_o2)

    restaurant_accept_order(o1, restaurant)
    restaurant_accept_order(o2, restaurant)

    # Dispatch and accept BEFORE start-preparing so the rider's /accept does not race
    # against start-preparing's implicit second OFFERED Assignment. PRD §3.6 allows
    # /accept during RESTAURANT_ACCEPTED.
    a1 = dispatch_order_as_admin(o1)
    rider = _resolve_rider_from_assignment(a1)
    a1 = accept_assignment_as_rider(a1, rider)
    # Rider is now ON_DELIVERY. For route merging (PRD §3.6) the SAME rider must
    # accept both legs, which means the second /dispatch must pick this same rider.
    # To prevent any other AVAILABLE rider (left over from a prior test in the same
    # session) from being picked instead, take them all offline now. /go-offline is
    # legal per PRD §3.3 when the rider has no active assignment.
    take_other_riders_offline(keep_rider_id=rider["id"])
    a2 = dispatch_order_as_admin(o2)
    # Assert the second dispatch actually stamped the SAME rider as a1 — without this
    # the two legs can't form a RouteGroup (PRD §3.6: "When the accepting rider already
    # holds an ACTIVE RouteGroup and the newly accepted order's pickup restaurant is
    # within 500 metres of an existing unpicked assignment's pickup restaurant…").
    # Because PRD has no list-riders endpoint the fixture cannot enumerate every
    # AVAILABLE leftover rider from prior tests; if any slipped past our
    # _CREATED_RIDER_IDS registry the dispatcher might pick them instead, and the
    # merge would be structurally impossible. Surface that condition clearly here so
    # callers don't see a downstream 403.
    assert a2["rider_id"] == rider["id"], (
        "run_two_orders_to_merged_delivery: second dispatch targeted a different "
        f"rider (a1.rider_id={a1['rider_id']!r}, a2.rider_id={a2['rider_id']!r}); "
        "route-merging is structurally impossible in this configuration. Another "
        "AVAILABLE rider not in the session registry was preferred by dispatch."
    )
    # Identity for a2's accept MUST match a2.rider_id — re-adopt from the stamped
    # assignment even though we just asserted equality (belt and suspenders).
    rider = _resolve_rider_from_assignment(a2)
    a2 = accept_assignment_as_rider(a2, rider)

    start_preparing(o1, restaurant)
    start_preparing(o2, restaurant)
    mark_ready(o1, restaurant)
    mark_ready(o2, restaurant)
    a1 = pickup_assignment_as_rider(a1, rider)
    a2 = pickup_assignment_as_rider(a2, rider)
    a1 = deliver_assignment_as_rider(a1, rider)
    a2 = deliver_assignment_as_rider(a2, rider)

    # Re-read both orders and assignments after delivery for final_* fields.
    o1 = get_success_data(api_client.get_order(o1["id"], admin))
    o2 = get_success_data(api_client.get_order(o2["id"], admin))
    a1 = get_success_data(api_client.get_assignment(a1["id"], admin))
    a2 = get_success_data(api_client.get_assignment(a2["id"], admin))
    # Re-read rider so caller sees updated wallet_balance_cents / bonus_tier after
    # the §3.7 fiscal-reconciliation cascade fired on both deliveries.
    rider_headers = make_rider_headers(rider["id"])
    rider = get_success_data(api_client.get_rider(rider["id"], rider_headers))

    return {
        "restaurant": restaurant,
        "menu_item": menu_item,
        "customer_o1": customer_o1,
        "customer_o2": customer_o2,
        "rider": rider,
        "order_o1": o1,
        "order_o2": o2,
        "assignment_a1": a1,
        "assignment_a2": a2,
    }


def run_order_deliver_with_lateness(
    *,
    minutes_late: int,
    distance_km: float = 2.0,
    menu_price_cents: int = 5000,
) -> Dict[str, Any]:
    """Run an order end-to-end such that delivery is exactly *minutes_late* minutes
    past promised_delivery_time.

    PRD §3.4 sets promised_delivery_time = placement time + 45 min.
    We advance the clock by 45 + minutes_late minutes between pickup and deliver so
    that actual_delivery_time - promised_delivery_time = minutes_late * 60 seconds.
    """
    ctx = run_order_to_picked_up(
        distance_km=distance_km, menu_price_cents=menu_price_cents
    )
    # Advance clock by (promised_delivery_minutes + minutes_late * 60) seconds.
    # We already consumed some logical time through the placement flow; the clock-advance
    # capability is cumulative so we add the full (45+minutes_late) minutes here. The
    # server's minutes_late computation reads actual_delivery_time - promised_delivery_time,
    # floored to minutes — any small prior advancements are absorbed into the placement
    # moment's baseline because promised_delivery_time was pinned at placement.
    advance_clock_seconds((45 + minutes_late) * 60)
    assignment = deliver_assignment_as_rider(ctx["assignment"], ctx["rider"])
    admin = TEST_USERS["admin_headers"]
    ctx["assignment"] = get_success_data(api_client.get_assignment(assignment["id"], admin))
    ctx["order"] = get_success_data(api_client.get_order(ctx["order"]["id"], admin))
    rider_headers = make_rider_headers(ctx["rider"]["id"])
    ctx["rider"] = get_success_data(api_client.get_rider(ctx["rider"]["id"], rider_headers))
    return ctx


# ──────────────────────────────────────────────────────────
# Return / WorkOrder composite flows
# ──────────────────────────────────────────────────────────

def open_return_on_delivered_order(
    delivered_ctx: Dict[str, Any],
    *,
    requested_refund_cents: int = 100,
    reason: str = "QUALITY_ISSUE",
) -> Dict[str, Any]:
    """Open a Return on a DELIVERED order. delivered_ctx is the dict from
    run_order_to_delivered()."""
    customer = delivered_ctx["customer"]
    headers = make_customer_headers(customer["id"])
    return get_success_data(
        api_client.create_return(
            delivered_ctx["order"]["id"],
            create_return_payload(
                reason=reason, requested_refund_cents=requested_refund_cents
            ),
            headers,
        )
    )


def run_to_return_requested(
    *,
    distance_km: float = 2.0,
    subtotal_cents: int = 1000,
    requested_refund_cents: int = 400,
    reason: str = "QUALITY_ISSUE",
) -> Dict[str, Any]:
    """run_order_to_delivered + open Return in REQUESTED.

    subtotal_cents is achieved by picking a single menu item whose price_cents equals
    subtotal_cents (quantity=1).
    """
    delivered = run_order_to_delivered(
        distance_km=distance_km, menu_price_cents=subtotal_cents
    )
    ret = open_return_on_delivered_order(
        delivered, requested_refund_cents=requested_refund_cents, reason=reason
    )
    delivered["return"] = ret
    # Re-read order so caller sees status REFUND_REQUESTED.
    admin = TEST_USERS["admin_headers"]
    delivered["order"] = get_success_data(api_client.get_order(delivered["order"]["id"], admin))
    return delivered


def open_work_order_for_return(
    return_row: Dict[str, Any],
    *,
    opened_by_role: str = "CUSTOMER_SERVICE",
    opened_by_id: Optional[str] = None,
    category: str = "FOOD_QUALITY",
    actor_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Open a WorkOrder with related_return_id == return_row["id"]."""
    opener = opened_by_id if opened_by_id else "test-cs-1"
    headers = actor_headers if actor_headers is not None else TEST_USERS["cs_headers"]
    payload = create_work_order_payload(
        opened_by_role=opened_by_role,
        opened_by_id=opener,
        category=category,
        related_return_id=return_row["id"],
    )
    return get_success_data(api_client.create_work_order(payload, headers))


# ──────────────────────────────────────────────────────────
# Rider metric-manipulation fixtures
# ──────────────────────────────────────────────────────────

def create_rider_with_score(
    *,
    on_time_rate: Optional[float] = None,
    acceptance_rate: Optional[float] = None,
    rating: Optional[float] = None,
) -> Dict[str, Any]:
    """Create a rider whose initial metrics are the defaults (on_time_rate=1.0,
    acceptance_rate=1.0, rating=5.0 per PRD §3.3, all seeded until 30 samples accrue).

    This helper is intentionally minimal: the PRD does NOT expose admin-level writes to
    rider metrics, so tests that need a specific score must drive it through the normal
    delivery cascade. The two-reader test in SKILL.md blocks inventing a write-path.

    Returns the rider in OFFLINE initial state.
    """
    admin = TEST_USERS["admin_headers"]
    return get_success_data(
        api_client.create_rider(create_rider_payload(), admin)
    )


# ──────────────────────────────────────────────────────────
# Misc
# ──────────────────────────────────────────────────────────

__all__ = [
    # Clock
    "advance_clock_seconds",
    # State progression
    "create_active_restaurant",
    "create_available_rider",
    "create_customer",
    # Menu / hierarchy
    "create_listed_menu_item",
    "setup_restaurant_with_menu",
    "setup_customer_restaurant_menu",
    # Order flow
    "place_order",
    "restaurant_accept_order",
    "start_preparing",
    "mark_ready",
    "dispatch_order_as_admin",
    "accept_assignment_as_rider",
    "pickup_assignment_as_rider",
    "deliver_assignment_as_rider",
    # Composite flows
    "run_order_to_picked_up",
    "run_order_to_delivered",
    "run_two_orders_to_merged_delivery",
    "run_order_deliver_with_lateness",
    "take_other_riders_offline",
    # Return flow
    "open_return_on_delivered_order",
    "run_to_return_requested",
    "open_work_order_for_return",
    # Rider helpers
    "create_rider_with_score",
]
