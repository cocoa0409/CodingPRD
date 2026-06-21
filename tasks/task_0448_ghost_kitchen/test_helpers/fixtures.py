"""Composite setup helpers for multi-step test prerequisites (Ghost Kitchen Platform).

Each helper builds its preconditions from scratch using only PRD-declared endpoints
(the per-test server starts against an empty DB). Uses get_success_data() so a broken
setup surfaces as a clear "Setup step failed" error rather than a confusing assertion.

Identity threading (PRD §2.1): StallOperator's X-User-ID must equal the acting Stall.id
and BrandOwner's X-User-ID must equal the acting VirtualBrand.id. Every ownership-gated
call below uses make_stall_operator_headers(stall["id"]) / make_brand_owner_headers(
brand["id"]) with the real entity id — never the shared fallback constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_stall_payload,
    create_brand_payload,
    create_lease_payload,
    create_equipment_payload,
    create_booking_payload,
    create_menu_item_payload,
    create_recipe_component_payload,
    create_ingredient_lot_payload,
    create_order_payload,
)
from .test_users import (
    TEST_USERS,
    make_stall_operator_headers,
    make_brand_owner_headers,
)
from .constants import ROUTING_CLOCK_UTC

OPS = TEST_USERS["platform_ops_headers"]
GATEWAY = TEST_USERS["aggregator_gateway_headers"]


# ─── Logical clock ───────────────────────────────────────────────────────────

def set_clock(to_iso8601: str = ROUTING_CLOCK_UTC):
    """Advance the server logical clock (PlatformOps only)."""
    return get_success_data(api_client.set_clock(to_iso8601, OPS))


# ─── Tier 1: base entities ───────────────────────────────────────────────────

def create_stall(**overrides) -> dict:
    """Create a stall (status OPEN, equipment_count 0, version 1). Returns the stall."""
    return get_success_data(api_client.create_stall(create_stall_payload(**overrides), OPS))


def create_brand(**overrides) -> dict:
    """Create a brand (status ONBOARDING, availability PAUSED, ledger 0). Returns the brand."""
    return get_success_data(api_client.create_brand(create_brand_payload(**overrides), OPS))


def create_lease(stall_id: str, brand_id: str, **overrides) -> dict:
    """Create a lease (status PENDING). Returns the lease."""
    return get_success_data(
        api_client.create_lease(create_lease_payload(stall_id, brand_id, **overrides), OPS)
    )


def create_equipment(stall_id: str, **overrides) -> dict:
    """Add an equipment unit to a stall (StallOperator owns the stall). Returns the unit."""
    return get_success_data(
        api_client.create_equipment(
            create_equipment_payload(stall_id, **overrides),
            make_stall_operator_headers(stall_id),
        )
    )


def create_ingredient_lot(stall_id: str, **overrides) -> dict:
    """Receive an ingredient lot at a stall (StallOperator owns the stall). Returns the lot."""
    return get_success_data(
        api_client.create_ingredient_lot(
            create_ingredient_lot_payload(stall_id, **overrides),
            make_stall_operator_headers(stall_id),
        )
    )


def create_menu_item(brand_id: str, **overrides) -> dict:
    """Create a menu item under a brand (BrandOwner owns the brand). Returns the item."""
    return get_success_data(
        api_client.create_menu_item(
            create_menu_item_payload(brand_id, **overrides),
            make_brand_owner_headers(brand_id),
        )
    )


def add_recipe_component(brand_id: str, menu_item_id: str, **overrides) -> dict:
    """Add a recipe line to a menu item (BrandOwner owns the brand). Returns the line."""
    return get_success_data(
        api_client.create_recipe_component(
            menu_item_id, create_recipe_component_payload(**overrides),
            make_brand_owner_headers(brand_id),
        )
    )


def create_booking(stall_id: str, equipment_id: str, start_minute: int, end_minute: int, **overrides) -> dict:
    """Create a manual maintenance hold (StallOperator owns the stall). Returns the booking."""
    return get_success_data(
        api_client.create_booking(
            create_booking_payload(equipment_id, start_minute, end_minute, **overrides),
            make_stall_operator_headers(stall_id),
        )
    )


# ─── Tier 2: state-progression shortcuts ─────────────────────────────────────

def activate_lease(stall_id: str, lease_id: str) -> dict:
    """Activate a PENDING lease (StallOperator owns the stall). May cascade brand ACTIVE."""
    return get_success_data(
        api_client.activate_lease(lease_id, make_stall_operator_headers(stall_id))
    )


def list_brand(brand_id: str) -> dict:
    """Set brand availability LISTED (BrandOwner owns the brand). Returns the brand."""
    return get_success_data(
        api_client.list_brand_availability(brand_id, make_brand_owner_headers(brand_id))
    )


def create_active_listed_brand_on_stall(commission_rate_bps: int = 1000,
                                        stall_overrides=None, brand_overrides=None):
    """Stall OPEN + Brand ACTIVE+LISTED bound by an ACTIVE rank-1 lease.

    Returns (stall, brand, lease). The lease activation cascades the brand
    ONBOARDING->ACTIVE; the brand is then LISTED by its owner.
    """
    stall = create_stall(**(stall_overrides or {}))
    brand = create_brand(commission_rate_bps=commission_rate_bps, **(brand_overrides or {}))
    lease = create_lease(stall["id"], brand["id"], priority_rank=1)
    lease = activate_lease(stall["id"], lease["id"])
    brand = list_brand(brand["id"])
    return stall, brand, lease


def create_active_brand_on_stall(commission_rate_bps: int = 1000,
                                 stall_overrides=None, brand_overrides=None):
    """Stall OPEN + Brand ACTIVE (but still PAUSED, NOT listed), bound by an ACTIVE lease.

    Returns (stall, brand, lease).
    """
    stall = create_stall(**(stall_overrides or {}))
    brand = create_brand(commission_rate_bps=commission_rate_bps, **(brand_overrides or {}))
    lease = create_lease(stall["id"], brand["id"], priority_rank=1)
    lease = activate_lease(stall["id"], lease["id"])
    brand = get_success_data(api_client.get_brand(brand["id"], OPS))
    return stall, brand, lease


# ─── Tier 3: routable single-item scenario ───────────────────────────────────

def setup_routable_scenario(menu_item_overrides=None, recipe_overrides=None,
                            lot_overrides=None, commission_rate_bps=1000,
                            equipment_overrides=None, clock_at=ROUTING_CLOCK_UTC,
                            stall_overrides=None):
    """Full preconditions for routing a single-line order, INGESTED but not yet routed.

    Builds: stall OPEN -> brand ACTIVE+LISTED via ACTIVE lease -> one menu item with one
    recipe component -> one equipment unit of the item's required type -> one ingredient
    lot -> clock advanced -> one ingested order (1x item).

    Returns dict with keys: stall, brand, lease, menu_item, recipe, equipment, lot, order.
    """
    stall, brand, lease = create_active_listed_brand_on_stall(
        commission_rate_bps=commission_rate_bps, stall_overrides=stall_overrides,
    )
    menu_item = create_menu_item(brand["id"], **(menu_item_overrides or {}))
    recipe = add_recipe_component(brand["id"], menu_item["id"], **(recipe_overrides or {}))
    equipment = create_equipment(stall["id"], **(equipment_overrides or {
        "equipment_type": menu_item["required_equipment_type"]}))
    lot = create_ingredient_lot(stall["id"], **(lot_overrides or {}))
    set_clock(clock_at)
    order = get_success_data(
        api_client.create_order(
            create_order_payload(
                brand["id"], [{"menu_item_id": menu_item["id"], "qty": 1}],
                external_ref="DD-ROUTABLE",
            ),
            GATEWAY,
        )
    )
    return {
        "stall": stall, "brand": brand, "lease": lease, "menu_item": menu_item,
        "recipe": recipe, "equipment": equipment, "lot": lot, "order": order,
    }


def route_order(order_id: str) -> dict:
    """Route an INGESTED order (PlatformOps). Returns the routed order."""
    return get_success_data(api_client.route_order(order_id, OPS))


def start_prep(stall_id: str, order_id: str) -> dict:
    """Begin prep (StallOperator owns routed_stall). Returns the order in PREPARING."""
    return get_success_data(
        api_client.start_prep_order(order_id, make_stall_operator_headers(stall_id))
    )


def fulfill(stall_id: str, order_id: str) -> dict:
    """Fulfill a PREPARING order (StallOperator owns routed_stall). Returns FULFILLED order."""
    return get_success_data(
        api_client.fulfill_order(order_id, make_stall_operator_headers(stall_id))
    )


# ─── Tier 4: equipment-only (maintenance hold) scenario ──────────────────────

def stall_with_buffered_equipment(turnaround_buffer_minutes: int,
                                  equipment_type: str = "FRYER"):
    """Stall OPEN + one equipment unit with the given turnaround buffer.

    Returns (stall, equipment).
    """
    stall = create_stall()
    equipment = create_equipment(
        stall["id"], equipment_type=equipment_type,
        turnaround_buffer_minutes=turnaround_buffer_minutes,
    )
    return stall, equipment


def stall_with_held_booking(turnaround_buffer_minutes: int = 0,
                            start_minute: int = 100, end_minute: int = 150,
                            equipment_type: str = "FRYER"):
    """Stall OPEN + one equipment unit holding a HELD maintenance booking [start,end).

    Returns (stall, equipment, booking).
    """
    stall, equipment = stall_with_buffered_equipment(
        turnaround_buffer_minutes, equipment_type=equipment_type,
    )
    booking = create_booking(stall["id"], equipment["id"], start_minute, end_minute)
    return stall, equipment, booking
