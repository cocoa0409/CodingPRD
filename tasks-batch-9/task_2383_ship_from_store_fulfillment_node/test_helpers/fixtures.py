"""Composite setup helpers.

Every test starts against an empty database, so each helper here builds its
preconditions from scratch using only endpoints the PRD declares. The single-
call wrappers at the top exist so the composite builders below (and the tests)
never repeat header plumbing or version look-ups.

All setup calls use ``get_success_data`` so a broken precondition surfaces as a
setup failure rather than as a confusing assertion further down.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import PACKAGE_CLASS_TO_TYPE
from .factories import (
    create_carrier_pickup_payload,
    create_order_line_payload,
    create_order_payload,
    create_packaging_supply_payload,
    create_routing_run_payload,
    create_sku_payload,
    create_store_inventory_payload,
    create_store_payload,
    inventory_adjustment_payload,
    line_pick,
    pick_payload,
    ship_payload,
)
from .test_users import (
    CARE,
    CARRIER,
    PLANNER,
    make_store_associate_headers,
)

DEFAULT_CLOCK = "2026-08-03T09:00:00Z"


# ======================================================================
# Single-call wrappers
# ======================================================================


def set_clock(to_iso8601: str) -> dict:
    """Move the logical clock forward."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, PLANNER))


def register_node(preset: str = "S1", **overrides) -> dict:
    """Register one fulfillment node from a preset."""
    return get_success_data(
        api_client.create_store(create_store_payload(preset, **overrides), PLANNER)
    )


def register_nodes(*presets: str) -> list:
    """Register several nodes in the given order (creation order matters for
    tie-breaks and for the ops-run's ordering)."""
    return [register_node(preset) for preset in presets]


def register_sku(preset: str = "SKU-A", **overrides) -> dict:
    return get_success_data(
        api_client.create_sku(create_sku_payload(preset, **overrides), PLANNER)
    )


def stock_inventory(
    store_id: str, sku_id: str, on_hand_units: int = 12, safety_stock_units: int = 2
) -> dict:
    return get_success_data(
        api_client.create_store_inventory(
            create_store_inventory_payload(
                store_id, sku_id, on_hand_units, safety_stock_units
            ),
            PLANNER,
        )
    )


def stock_packaging(
    store_id: str,
    package_type: str = "MEDIUM_BOX",
    on_hand_units: int = 20,
    reorder_point_units: int = 2,
) -> dict:
    return get_success_data(
        api_client.create_packaging_supply(
            create_packaging_supply_payload(
                store_id, package_type, on_hand_units, reorder_point_units
            ),
            PLANNER,
        )
    )


def schedule_pickup(store_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_carrier_pickup(
            store_id, create_carrier_pickup_payload(**overrides), headers or CARRIER
        )
    )


def intake_order(**overrides) -> dict:
    return get_success_data(
        api_client.create_order(create_order_payload(**overrides), CARE)
    )


def add_order_line(
    order_id: str, sku_id: str, quantity: int = 2, unit_price_cents: int = 4500
) -> dict:
    return get_success_data(
        api_client.create_order_line(
            order_id,
            create_order_line_payload(sku_id, quantity, unit_price_cents),
            CARE,
        )
    )


def read_store(store_id: str) -> dict:
    return get_success_data(api_client.get_store(store_id, PLANNER))


def read_sku(sku_id: str) -> dict:
    return get_success_data(api_client.get_sku(sku_id, PLANNER))


def read_inventory(inventory_id: str) -> dict:
    return get_success_data(api_client.get_store_inventory(inventory_id, PLANNER))


def read_packaging(supply_id: str) -> dict:
    return get_success_data(api_client.get_packaging_supply(supply_id, PLANNER))


def read_pickup(pickup_id: str) -> dict:
    return get_success_data(api_client.get_carrier_pickup(pickup_id, PLANNER))


def read_order(order_id: str) -> dict:
    return get_success_data(api_client.get_order(order_id, PLANNER))


def read_order_line(order_line_id: str) -> dict:
    return get_success_data(api_client.get_order_line(order_line_id, PLANNER))


def read_assignment(assignment_id: str) -> dict:
    return get_success_data(api_client.get_assignment(assignment_id, PLANNER))


def read_assignment_line(assignment_line_id: str) -> dict:
    return get_success_data(api_client.get_assignment_line(assignment_line_id, PLANNER))


def read_routing_run(routing_run_id: str) -> dict:
    return get_success_data(api_client.get_routing_run(routing_run_id, PLANNER))


def read_window(window_id: str) -> dict:
    return get_success_data(api_client.get_performance_window(window_id, PLANNER))


def read_notification(notification_id: str) -> dict:
    return get_success_data(api_client.get_notification(notification_id, CARE))


def cost_comparison(order_id: str) -> dict:
    return get_success_data(api_client.get_cost_comparison(order_id, PLANNER))


def order_version(order_id: str) -> int:
    return read_order(order_id)["version"]


def inventory_version(inventory_id: str) -> int:
    return read_inventory(inventory_id)["version"]


def pickup_version(pickup_id: str) -> int:
    return read_pickup(pickup_id)["version"]


# ------------------------------------------------------------- list reads


def find_assignments(**params) -> list:
    return get_success_data(api_client.list_assignments(PLANNER, params=params or None))


def find_assignment(index: int = 0, **params) -> dict:
    rows = find_assignments(**params)
    assert len(rows) > index, (
        f"expected at least {index + 1} assignment(s) for {params}, got {len(rows)}"
    )
    return rows[index]


def find_assignment_lines(assignment_id: str) -> list:
    return get_success_data(
        api_client.list_assignment_lines(PLANNER, params={"assignment_id": assignment_id})
    )


def find_routing_runs(**params) -> list:
    return get_success_data(
        api_client.list_routing_runs(PLANNER, params=params or None)
    )


def find_routing_candidates(**params) -> list:
    return get_success_data(
        api_client.list_routing_candidates(PLANNER, params=params or None)
    )


def find_windows(**params) -> list:
    return get_success_data(
        api_client.list_performance_windows(PLANNER, params=params or None)
    )


def find_notifications(**params) -> list:
    return get_success_data(api_client.list_notifications(CARE, params=params or None))


def find_order_lines(**params) -> list:
    return get_success_data(api_client.list_order_lines(PLANNER, params=params or None))


def find_inventories(**params) -> list:
    return get_success_data(
        api_client.list_store_inventories(PLANNER, params=params or None)
    )


# ------------------------------------------------------------- write steps


def run_routing(order_id: str, mode: str = "COMMIT", expected_order_version=None, **extra) -> dict:
    """Start a routing run, reading the order's live version when not pinned."""
    if expected_order_version is None:
        expected_order_version = order_version(order_id)
    return get_success_data(
        api_client.create_routing_run(
            order_id,
            create_routing_run_payload(expected_order_version, mode, **extra),
            PLANNER,
        )
    )


def commit_routing(order_id: str, expected_order_version=None, **extra) -> dict:
    return run_routing(order_id, "COMMIT", expected_order_version, **extra)


def provisional_routing(order_id: str, expected_order_version=None, **extra) -> dict:
    return run_routing(order_id, "PROVISIONAL", expected_order_version, **extra)


def accept(assignment_id: str, store_id: str) -> dict:
    return get_success_data(
        api_client.accept_assignment(
            assignment_id, make_store_associate_headers(store_id)
        )
    )


def reject(
    assignment_id: str, store_id: str, reject_reason_code: str = "LABOR_UNAVAILABLE"
) -> dict:
    return get_success_data(
        api_client.reject_assignment(
            assignment_id,
            {"reject_reason_code": reject_reason_code},
            make_store_associate_headers(store_id),
        )
    )


def pick_full(assignment_id: str, store_id: str) -> dict:
    """Pick every unit on every line of the assignment."""
    lines = find_assignment_lines(assignment_id)
    picks = [line_pick(row["id"], row["units_assigned"]) for row in lines]
    total = sum(row["units_assigned"] for row in lines)
    return get_success_data(
        api_client.pick_assignment(
            assignment_id,
            pick_payload(total, picks),
            make_store_associate_headers(store_id),
        )
    )


def pick_units(assignment_id: str, store_id: str, units_by_line_index: dict) -> dict:
    """Short pick: ``units_by_line_index`` maps the assignment line's position
    (0-based, in list order) to the units actually picked. Lines that are not
    mentioned are reported as fully picked."""
    lines = find_assignment_lines(assignment_id)
    picks = []
    total = 0
    for index, row in enumerate(lines):
        units = units_by_line_index.get(index, row["units_assigned"])
        picks.append(line_pick(row["id"], units))
        total += units
    return get_success_data(
        api_client.pick_assignment(
            assignment_id,
            pick_payload(total, picks),
            make_store_associate_headers(store_id),
        )
    )


def pack(assignment_id: str, store_id: str, package_type: str = None) -> dict:
    """Pack the assignment; defaults to the assignment's derived_package_type."""
    if package_type is None:
        package_type = read_assignment(assignment_id)["derived_package_type"]
    return get_success_data(
        api_client.pack_assignment(
            assignment_id,
            {"package_type": package_type},
            make_store_associate_headers(store_id),
        )
    )


def ship(
    assignment_id: str,
    store_id: str,
    carrier_pickup_id: str,
    expected_pickup_version=None,
) -> dict:
    if expected_pickup_version is None:
        expected_pickup_version = pickup_version(carrier_pickup_id)
    return get_success_data(
        api_client.ship_assignment(
            assignment_id,
            ship_payload(carrier_pickup_id, expected_pickup_version),
            make_store_associate_headers(store_id),
        )
    )


def cancel_assignment(
    assignment_id: str, cancel_reason_code: str = "CUSTOMER_REQUEST", reroute: bool = False
) -> dict:
    return get_success_data(
        api_client.cancel_assignment(
            assignment_id,
            {"cancel_reason_code": cancel_reason_code, "reroute": reroute},
            CARE,
        )
    )


def cancel_order(order_id: str, cancel_reason_code: str = "CUSTOMER_REQUEST") -> dict:
    return get_success_data(
        api_client.cancel_order(order_id, {"cancel_reason_code": cancel_reason_code}, CARE)
    )


def adjust_inventory(
    inventory_id: str,
    counted_on_hand_units: int,
    reason: str = "CYCLE_COUNT",
    expected_inventory_version=None,
    headers=None,
    **extra,
) -> dict:
    if expected_inventory_version is None:
        expected_inventory_version = inventory_version(inventory_id)
    return get_success_data(
        api_client.adjust_store_inventory(
            inventory_id,
            inventory_adjustment_payload(
                expected_inventory_version, counted_on_hand_units, reason, **extra
            ),
            headers or PLANNER,
        )
    )


def restock_packaging(supply_id: str, added_units: int, headers=None) -> dict:
    return get_success_data(
        api_client.restock_packaging_supply(
            supply_id, {"added_units": added_units}, headers or PLANNER
        )
    )


def close_pickup(pickup_id: str) -> dict:
    return get_success_data(api_client.close_carrier_pickup(pickup_id, CARRIER))


def depart_pickup(pickup_id: str) -> dict:
    return get_success_data(api_client.depart_carrier_pickup(pickup_id, CARRIER))


def cancel_pickup(pickup_id: str) -> dict:
    return get_success_data(api_client.cancel_carrier_pickup(pickup_id, CARRIER))


def close_windows() -> list:
    """Run the ops-run: close every OPEN window and re-posture the nodes."""
    return get_success_data(api_client.close_performance_windows(PLANNER))


# ======================================================================
# Tier 2 — composite network builders
# ======================================================================


def setup_network(
    node_presets=("S1",),
    sku_presets=("SKU-A",),
    clock: str = DEFAULT_CLOCK,
    stock=None,
    packaging=None,
) -> dict:
    """Clock + nodes + SKUs + optional inventory and packaging rows.

    ``stock`` is a list of ``(node_preset, sku_preset, on_hand, safety)`` tuples.
    ``packaging`` is a list of ``(node_preset, package_type, on_hand, reorder_point)``
    tuples. Both default to nothing so callers opt in explicitly.

    Returns ``{"stores": {preset: Store}, "skus": {preset: Sku},
    "inventories": {(node, sku): StoreInventory},
    "supplies": {(node, package_type): PackagingSupply}}``.
    """
    if clock:
        set_clock(clock)

    stores = {preset: register_node(preset) for preset in node_presets}
    skus = {preset: register_sku(preset) for preset in sku_presets}

    inventories = {}
    for node_preset, sku_preset, on_hand, safety in stock or []:
        inventories[(node_preset, sku_preset)] = stock_inventory(
            stores[node_preset]["id"], skus[sku_preset]["id"], on_hand, safety
        )

    supplies = {}
    for node_preset, package_type, on_hand, reorder_point in packaging or []:
        supplies[(node_preset, package_type)] = stock_packaging(
            stores[node_preset]["id"], package_type, on_hand, reorder_point
        )

    return {
        "stores": stores,
        "skus": skus,
        "inventories": inventories,
        "supplies": supplies,
    }


def setup_order_with_lines(
    lines,
    order_code: str = "O-1001",
    customer_ref: str = "C-1",
    destination_zone: int = 4,
    service_level: str = "GROUND",
    promised_ship_by_utc: str = "2026-08-03T16:00:00Z",
) -> dict:
    """Intake an order and add one demand line per ``(sku_id, quantity,
    unit_price_cents)`` tuple. Returns ``{"order": ..., "lines": [...]}``."""
    order = intake_order(
        order_code=order_code,
        customer_ref=customer_ref,
        destination_zone=destination_zone,
        service_level=service_level,
        promised_ship_by_utc=promised_ship_by_utc,
    )
    created = [
        add_order_line(order["id"], sku_id, quantity, unit_price_cents)
        for sku_id, quantity, unit_price_cents in lines
    ]
    return {"order": read_order(order["id"]), "lines": created}


# ======================================================================
# Tier 3 — assignment lifecycle shortcuts
# ======================================================================


def setup_committed_assignment(
    node_preset: str = "S1",
    sku_preset: str = "SKU-A",
    on_hand_units: int = 12,
    safety_stock_units: int = 2,
    quantity: int = 2,
    destination_zone: int = 4,
    service_level: str = "GROUND",
    order_code: str = "O-1001",
    customer_ref: str = "C-1",
    promised_ship_by_utc: str = "2026-08-03T16:00:00Z",
    clock: str = DEFAULT_CLOCK,
    with_packaging: bool = True,
    package_type: str = None,
    packaging_on_hand: int = 20,
    with_pickup: bool = True,
    pickup_start: str = "2026-08-03T09:00:00Z",
    pickup_end: str = "2026-08-03T12:00:00Z",
    parcel_capacity: int = 5,
) -> dict:
    """One node, one SKU, one single-line order committed to that node.

    Returns a dict with ``store``, ``sku``, ``inventory``, ``supply``,
    ``pickup``, ``order``, ``line``, ``run``, ``assignment`` and
    ``assignment_lines``.
    """
    net = setup_network(
        node_presets=(node_preset,),
        sku_presets=(sku_preset,),
        clock=clock,
        stock=[(node_preset, sku_preset, on_hand_units, safety_stock_units)],
    )
    store = net["stores"][node_preset]
    sku = net["skus"][sku_preset]
    inventory = net["inventories"][(node_preset, sku_preset)]

    supply = None
    if with_packaging:
        resolved_type = package_type or PACKAGE_CLASS_TO_TYPE[sku["package_class"]]
        supply = stock_packaging(store["id"], resolved_type, packaging_on_hand, 2)

    pickup = None
    if with_pickup:
        pickup = schedule_pickup(
            store["id"],
            window_start_utc=pickup_start,
            window_end_utc=pickup_end,
            parcel_capacity=parcel_capacity,
        )

    built = setup_order_with_lines(
        [(sku["id"], quantity, sku["unit_price_cents"])],
        order_code=order_code,
        customer_ref=customer_ref,
        destination_zone=destination_zone,
        service_level=service_level,
        promised_ship_by_utc=promised_ship_by_utc,
    )
    order, line = built["order"], built["lines"][0]

    run = commit_routing(order["id"])
    assignment = find_assignment(order_id=order["id"], store_id=store["id"])

    return {
        "store": store,
        "sku": sku,
        "inventory": inventory,
        "supply": supply,
        "pickup": pickup,
        "order": read_order(order["id"]),
        "line": read_order_line(line["id"]),
        "run": run,
        "assignment": assignment,
        "assignment_lines": find_assignment_lines(assignment["id"]),
    }


def setup_accepted_assignment(accept_at: str = "2026-08-03T09:05:00Z", **kwargs) -> dict:
    """Committed assignment, then accepted at ``accept_at``."""
    ctx = setup_committed_assignment(**kwargs)
    if accept_at:
        set_clock(accept_at)
    accept(ctx["assignment"]["id"], ctx["store"]["id"])
    ctx["assignment"] = read_assignment(ctx["assignment"]["id"])
    return ctx


def setup_picked_assignment(
    accept_at: str = "2026-08-03T09:05:00Z", pick_at: str = None, **kwargs
) -> dict:
    """Committed → accepted → fully picked."""
    ctx = setup_accepted_assignment(accept_at=accept_at, **kwargs)
    if pick_at:
        set_clock(pick_at)
    pick_full(ctx["assignment"]["id"], ctx["store"]["id"])
    ctx["assignment"] = read_assignment(ctx["assignment"]["id"])
    ctx["assignment_lines"] = find_assignment_lines(ctx["assignment"]["id"])
    return ctx


def setup_packed_assignment(
    accept_at: str = "2026-08-03T09:05:00Z",
    pick_at: str = None,
    pack_at: str = "2026-08-03T09:25:00Z",
    package_type_on_pack: str = None,
    **kwargs,
) -> dict:
    """Committed → accepted → picked → packed."""
    ctx = setup_picked_assignment(accept_at=accept_at, pick_at=pick_at, **kwargs)
    if pack_at:
        set_clock(pack_at)
    pack(ctx["assignment"]["id"], ctx["store"]["id"], package_type_on_pack)
    ctx["assignment"] = read_assignment(ctx["assignment"]["id"])
    return ctx


def setup_shipped_assignment(
    accept_at: str = "2026-08-03T09:05:00Z",
    pick_at: str = None,
    pack_at: str = "2026-08-03T09:25:00Z",
    ship_at: str = None,
    package_type_on_pack: str = None,
    **kwargs,
) -> dict:
    """Committed → accepted → picked → packed → shipped into the node's pickup."""
    ctx = setup_packed_assignment(
        accept_at=accept_at,
        pick_at=pick_at,
        pack_at=pack_at,
        package_type_on_pack=package_type_on_pack,
        **kwargs,
    )
    if ship_at:
        set_clock(ship_at)
    ship(ctx["assignment"]["id"], ctx["store"]["id"], ctx["pickup"]["id"])
    ctx["assignment"] = read_assignment(ctx["assignment"]["id"])
    ctx["order"] = read_order(ctx["order"]["id"])
    ctx["pickup"] = read_pickup(ctx["pickup"]["id"])
    ctx["inventory"] = read_inventory(ctx["inventory"]["id"])
    ctx["line"] = read_order_line(ctx["line"]["id"])
    ctx["store"] = read_store(ctx["store"]["id"])
    return ctx


# ======================================================================
# Tier 4 — multi-node / split targeting
# ======================================================================


def setup_multi_node_order(
    node_stock,
    sku_preset: str = "SKU-A",
    quantity: int = 6,
    destination_zone: int = 4,
    service_level: str = "GROUND",
    order_code: str = "O-2001",
    customer_ref: str = "C-2",
    promised_ship_by_utc: str = "2026-08-03T15:00:00Z",
    clock: str = DEFAULT_CLOCK,
    packaging=None,
    pickups=None,
    commit: bool = True,
) -> dict:
    """Several nodes, one SKU, one single-line order that needs a split.

    ``node_stock`` is an ordered list of ``(node_preset, on_hand, safety)``
    tuples — creation order is preserved because it decides tie-breaks.
    ``packaging`` is a list of ``(node_preset, package_type, on_hand)``.
    ``pickups`` is a list of ``(node_preset, start, end, capacity)``.

    Returns ``stores`` (keyed by preset), ``sku``, ``inventories``,
    ``supplies``, ``pickups``, ``order``, ``line``, ``run`` and
    ``assignments`` (keyed by node preset, only the ones created).
    """
    if clock:
        set_clock(clock)

    stores = {}
    for node_preset, _on_hand, _safety in node_stock:
        stores[node_preset] = register_node(node_preset)
    sku = register_sku(sku_preset)

    inventories = {}
    for node_preset, on_hand, safety in node_stock:
        inventories[node_preset] = stock_inventory(
            stores[node_preset]["id"], sku["id"], on_hand, safety
        )

    supplies = {}
    for node_preset, package_type, on_hand in packaging or []:
        supplies[(node_preset, package_type)] = stock_packaging(
            stores[node_preset]["id"], package_type, on_hand, 2
        )

    created_pickups = {}
    for node_preset, start, end, capacity in pickups or []:
        created_pickups[node_preset] = schedule_pickup(
            stores[node_preset]["id"],
            window_start_utc=start,
            window_end_utc=end,
            parcel_capacity=capacity,
        )

    built = setup_order_with_lines(
        [(sku["id"], quantity, sku["unit_price_cents"])],
        order_code=order_code,
        customer_ref=customer_ref,
        destination_zone=destination_zone,
        service_level=service_level,
        promised_ship_by_utc=promised_ship_by_utc,
    )
    order, line = built["order"], built["lines"][0]

    run = None
    assignments = {}
    if commit:
        run = commit_routing(order["id"])
        for node_preset, store in stores.items():
            rows = find_assignments(order_id=order["id"], store_id=store["id"])
            if rows:
                assignments[node_preset] = rows[0]

    return {
        "stores": stores,
        "sku": sku,
        "inventories": inventories,
        "supplies": supplies,
        "pickups": created_pickups,
        "order": read_order(order["id"]),
        "line": read_order_line(line["id"]),
        "run": run,
        "assignments": assignments,
    }


# ======================================================================
# Tier 5 — node posture / epoch targeting
# ======================================================================


def setup_node_with_one_breached_window(
    node_preset: str = "S1",
    sku_preset: str = "SKU-A",
    on_hand_units: int = 12,
    safety_stock_units: int = 2,
    quantity: int = 2,
    order_code: str = "O-3001",
    customer_ref: str = "C-5",
    clock: str = "2026-08-03T09:00:00Z",
    reject_at: str = "2026-08-03T09:05:00Z",
    close_at: str = "2026-08-03T09:30:00Z",
) -> dict:
    """One node whose only epoch-1 assignment was rejected, then the ops-run
    closes the epoch. The node lands on PROBATION with one breach window and
    the retried order is re-committed into epoch 2.

    Returns ``store``, ``sku``, ``inventory``, ``order``, ``line``,
    ``assignment_epoch_1``, ``windows_closed`` and ``assignment_epoch_2``
    (None when the retry created nothing).
    """
    ctx = setup_committed_assignment(
        node_preset=node_preset,
        sku_preset=sku_preset,
        on_hand_units=on_hand_units,
        safety_stock_units=safety_stock_units,
        quantity=quantity,
        order_code=order_code,
        customer_ref=customer_ref,
        clock=clock,
        with_packaging=False,
        with_pickup=False,
    )

    set_clock(reject_at)
    reject(ctx["assignment"]["id"], ctx["store"]["id"])

    set_clock(close_at)
    windows = close_windows()

    epoch_2 = find_assignments(order_id=ctx["order"]["id"], epoch=2)

    return {
        "store": read_store(ctx["store"]["id"]),
        "sku": ctx["sku"],
        "inventory": read_inventory(ctx["inventory"]["id"]),
        "order": read_order(ctx["order"]["id"]),
        "line": read_order_line(ctx["line"]["id"]),
        "assignment_epoch_1": read_assignment(ctx["assignment"]["id"]),
        "windows_closed": windows,
        "assignment_epoch_2": epoch_2[0] if epoch_2 else None,
    }


def setup_deactivated_node(
    node_preset: str = "S1",
    sku_preset: str = "SKU-A",
    clock: str = "2026-08-03T09:00:00Z",
    reject_at: str = "2026-08-03T09:05:00Z",
    first_close_at: str = "2026-08-03T09:30:00Z",
    cancel_at: str = "2026-08-03T09:35:00Z",
    second_close_at: str = "2026-08-03T09:40:00Z",
) -> dict:
    """Drive a node through ELIGIBLE → PROBATION → DEACTIVATED using two
    consecutive cancellation-rate breaches.

    Returns ``store`` (DEACTIVATED), ``order``, ``line``, ``inventory``,
    ``window_epoch_1``, ``window_epoch_2``, ``assignment_epoch_1`` and
    ``assignment_epoch_2``.
    """
    probation = setup_node_with_one_breached_window(
        node_preset=node_preset,
        sku_preset=sku_preset,
        clock=clock,
        reject_at=reject_at,
        close_at=first_close_at,
    )

    epoch_2_assignment = probation["assignment_epoch_2"]
    assert epoch_2_assignment is not None, (
        "setup expected the ops-run retry to recreate an assignment in epoch 2"
    )

    set_clock(cancel_at)
    cancel_assignment(epoch_2_assignment["id"], "CUSTOMER_REQUEST", reroute=False)

    set_clock(second_close_at)
    second_windows = close_windows()

    windows = find_windows(store_id=probation["store"]["id"])
    by_epoch = {row["epoch"]: row for row in windows}

    return {
        "store": read_store(probation["store"]["id"]),
        "sku": probation["sku"],
        "inventory": read_inventory(probation["inventory"]["id"]),
        "order": read_order(probation["order"]["id"]),
        "line": read_order_line(probation["line"]["id"]),
        "assignment_epoch_1": probation["assignment_epoch_1"],
        "assignment_epoch_2": read_assignment(epoch_2_assignment["id"]),
        "window_epoch_1": by_epoch.get(1),
        "window_epoch_2": by_epoch.get(2),
        "windows_closed": second_windows,
    }
