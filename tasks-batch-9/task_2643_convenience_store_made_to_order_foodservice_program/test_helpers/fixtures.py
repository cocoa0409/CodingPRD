"""Composite setup builders.

The database is empty at the start of every test, so each builder creates all
of the state it returns. Builders take the api client as their first argument
and return the created entity dicts (already unwrapped from the envelope) so a
test can read ids, versions and computed values without a second round trip.

Two sequencing rules are baked in here because getting them wrong breaks every
downstream call:

* Creating a labor plan bumps the store's ``version``, so the store must be
  re-read immediately before each plan create to obtain a fresh
  ``expected_store_version``.
* A par-baked batch only holds stock after it has been planned, baked and
  pulled, so :func:`create_holding_batch` walks all three steps.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from . import factories as F
from .test_users import (
    CHAIN_ADMIN_HEADERS,
    FOOD_SAFETY_LEAD_HEADERS,
    KITCHEN_ASSOCIATE_HEADERS,
    SHIFT_LEAD_HEADERS,
    STORE_MANAGER_HEADERS,
    STORE_TERMINAL_HEADERS,
    make_customer_headers,
)

Json = Dict[str, Any]


# ─── Clock ────────────────────────────────────────────────────────────
def set_clock(api, to_iso8601: str) -> Json:
    """Advance the logical clock and return the reported clock state."""
    return get_success_data(api.set_clock(F.clock_payload(to_iso8601), CHAIN_ADMIN_HEADERS))


# ─── Store ────────────────────────────────────────────────────────────
def create_store(api, **overrides: Any) -> Json:
    return get_success_data(api.create_store(F.store_payload(**overrides), CHAIN_ADMIN_HEADERS), 201)


def read_store(api, store_id: str) -> Json:
    return get_success_data(api.get_store(store_id, STORE_MANAGER_HEADERS))


def transition_daypart(api, store_id: str, to_daypart: str) -> Json:
    return get_success_data(
        api.create_daypart_transition(
            store_id, F.daypart_transition_payload(to_daypart), STORE_MANAGER_HEADERS
        )
    )


# ─── Holding units ────────────────────────────────────────────────────
def create_bakery_case(api, store_id: str, **overrides: Any) -> Json:
    return get_success_data(
        api.create_holding_unit(store_id, F.holding_unit_payload(**overrides), STORE_MANAGER_HEADERS),
        201,
    )


def read_holding_unit(api, unit_id: str) -> Json:
    return get_success_data(api.get_holding_unit(unit_id, STORE_MANAGER_HEADERS))


def log_temperature(api, unit_id: str, reading_f: int, headers: Optional[Json] = None) -> Json:
    return get_success_data(
        api.create_temperature_log(
            unit_id, F.temperature_log_payload(reading_f), headers or KITCHEN_ASSOCIATE_HEADERS
        ),
        201,
    )


def impair_unit(api, unit_id: str, reading_f: int = 120) -> Json:
    """Record one out-of-range reading, taking the unit out of service."""
    return log_temperature(api, unit_id, reading_f)


def open_corrective_action(
    api, temperature_log_id: str, headers: Optional[Json] = None, **overrides: Any
) -> Json:
    return get_success_data(
        api.create_corrective_action(
            F.corrective_action_payload(temperature_log_id, **overrides),
            headers or SHIFT_LEAD_HEADERS,
        ),
        201,
    )


def verify_corrective_action(api, action_id: str, headers: Optional[Json] = None) -> Json:
    return get_success_data(
        api.verify_corrective_action(action_id, {}, headers or FOOD_SAFETY_LEAD_HEADERS)
    )


def restore_unit_to_service(api, unit_id: str, temperature_log_id: str) -> Json:
    """Open a corrective action and have a different lead verify it."""
    action = open_corrective_action(api, temperature_log_id, KITCHEN_ASSOCIATE_HEADERS)
    return verify_corrective_action(api, action["id"], FOOD_SAFETY_LEAD_HEADERS)


def read_readiness(api, store_id: str) -> Json:
    return get_success_data(api.get_store_readiness(store_id, STORE_MANAGER_HEADERS))


# ─── Menu items ───────────────────────────────────────────────────────
def create_menu_item(api, **overrides: Any) -> Json:
    return get_success_data(
        api.create_menu_item(F.menu_item_payload(**overrides), CHAIN_ADMIN_HEADERS), 201
    )


def create_hoagie(api, **overrides: Any) -> Json:
    return get_success_data(
        api.create_menu_item(F.hoagie_payload(**overrides), CHAIN_ADMIN_HEADERS), 201
    )


def create_coffee(api, **overrides: Any) -> Json:
    return get_success_data(
        api.create_menu_item(F.coffee_payload(**overrides), CHAIN_ADMIN_HEADERS), 201
    )


def create_wrap(api, **overrides: Any) -> Json:
    return get_success_data(
        api.create_menu_item(F.wrap_payload(**overrides), CHAIN_ADMIN_HEADERS), 201
    )


def create_pretzel(api, **overrides: Any) -> Json:
    return get_success_data(
        api.create_menu_item(F.pretzel_payload(**overrides), CHAIN_ADMIN_HEADERS), 201
    )


def create_modifier_option(api, menu_item_id: str, **overrides: Any) -> Json:
    return get_success_data(
        api.create_modifier_option(
            menu_item_id, F.modifier_option_payload(**overrides), CHAIN_ADMIN_HEADERS
        ),
        201,
    )


# ─── Promotions ───────────────────────────────────────────────────────
def create_promotion_rule(api, **overrides: Any) -> Json:
    return get_success_data(
        api.create_promotion_rule(F.promotion_rule_payload(**overrides), CHAIN_ADMIN_HEADERS), 201
    )


# ─── Loyalty ──────────────────────────────────────────────────────────
def create_loyalty_account(api, **overrides: Any) -> Json:
    return get_success_data(
        api.create_loyalty_account(F.loyalty_account_payload(**overrides), CHAIN_ADMIN_HEADERS), 201
    )


def seed_points(api, account_id: str, delta_points: int, reason: str) -> Json:
    """Grant an opening point balance through a customer-care adjustment."""
    return get_success_data(
        api.create_points_adjustment(
            account_id, F.points_adjustment_payload(delta_points, reason), CHAIN_ADMIN_HEADERS
        ),
        200,
    )


def read_loyalty_account(api, account_id: str) -> Json:
    return get_success_data(api.get_loyalty_account(account_id, CHAIN_ADMIN_HEADERS))


def record_fuel(api, account_id: str, **overrides: Any) -> Json:
    return get_success_data(
        api.create_fuel_transaction(
            account_id, F.fuel_transaction_payload(**overrides), STORE_TERMINAL_HEADERS
        ),
        201,
    )


# ─── Staffing plans ───────────────────────────────────────────────────
def create_staffing_plan(api, store_id: str, **overrides: Any) -> Json:
    """Create a labor plan, re-reading the store version immediately first."""
    store = read_store(api, store_id)
    payload = F.staffing_plan_payload(store["version"], **overrides)
    return get_success_data(api.create_staffing_plan(store_id, payload, STORE_MANAGER_HEADERS), 201)


def publish_staffing_plan(api, plan_id: str) -> Json:
    return get_success_data(api.publish_staffing_plan(plan_id, {}, STORE_MANAGER_HEADERS))


def create_published_plan(api, store_id: str, **overrides: Any) -> Json:
    plan = create_staffing_plan(api, store_id, **overrides)
    return publish_staffing_plan(api, plan["id"])


# ─── Production batches ───────────────────────────────────────────────
def create_planned_batch(
    api, store_id: str, menu_item_id: str, holding_unit_id: str, **overrides: Any
) -> Json:
    return get_success_data(
        api.create_production_batch(
            F.production_batch_payload(store_id, menu_item_id, holding_unit_id, **overrides),
            KITCHEN_ASSOCIATE_HEADERS,
        ),
        201,
    )


def bake_batch(api, batch_id: str, additional_qty: Optional[int] = None) -> Json:
    return get_success_data(
        api.bake_production_batch(
            batch_id, F.bake_payload(additional_qty), KITCHEN_ASSOCIATE_HEADERS
        )
    )


def pull_batch(api, batch_id: str) -> Json:
    return get_success_data(api.pull_production_batch(batch_id, {}, KITCHEN_ASSOCIATE_HEADERS))


def create_holding_batch(
    api, store_id: str, menu_item_id: str, holding_unit_id: str, **overrides: Any
) -> Json:
    """Plan, bake and pull a batch so its stock is available for reservation."""
    batch = create_planned_batch(api, store_id, menu_item_id, holding_unit_id, **overrides)
    bake_batch(api, batch["id"])
    return pull_batch(api, batch["id"])


def read_batch(api, batch_id: str) -> Json:
    return get_success_data(api.get_production_batch(batch_id, KITCHEN_ASSOCIATE_HEADERS))


def discard_batch_units(
    api, batch_id: str, qty: int, reason: str, headers: Optional[Json] = None
) -> Json:
    """Write off units, supplying the batch's current version for the check."""
    batch = read_batch(api, batch_id)
    return get_success_data(
        api.discard_production_batch(
            batch_id,
            F.discard_payload(qty, reason, batch["version"]),
            headers or SHIFT_LEAD_HEADERS,
        )
    )


# ─── Orders ───────────────────────────────────────────────────────────
def create_draft_order(api, store_id: str, headers: Optional[Json] = None, **overrides: Any) -> Json:
    return get_success_data(
        api.create_order(F.order_payload(store_id, **overrides), headers or STORE_TERMINAL_HEADERS),
        201,
    )


def create_draft_preorder(
    api,
    store_id: str,
    pickup_window_start: str,
    pickup_window_end: str,
    headers: Optional[Json] = None,
    **overrides: Any,
) -> Json:
    return get_success_data(
        api.create_order(
            F.preorder_payload(store_id, pickup_window_start, pickup_window_end, **overrides),
            headers or STORE_TERMINAL_HEADERS,
        ),
        201,
    )


def create_draft_catering_order(
    api,
    store_id: str,
    pickup_window_start: str,
    pickup_window_end: str,
    headers: Optional[Json] = None,
    **overrides: Any,
) -> Json:
    return get_success_data(
        api.create_order(
            F.catering_order_payload(store_id, pickup_window_start, pickup_window_end, **overrides),
            headers or STORE_TERMINAL_HEADERS,
        ),
        201,
    )


def add_order_line(
    api,
    order_id: str,
    menu_item_id: str,
    qty: int = 1,
    modifiers: Optional[List[Json]] = None,
    headers: Optional[Json] = None,
    **overrides: Any,
) -> Json:
    return get_success_data(
        api.create_order_line(
            order_id,
            F.order_line_payload(menu_item_id, qty, modifiers, **overrides),
            headers or STORE_TERMINAL_HEADERS,
        ),
        201,
    )


def place_order(api, order_id: str, headers: Optional[Json] = None) -> Json:
    return get_success_data(api.place_order(order_id, {}, headers or STORE_TERMINAL_HEADERS))


def authorize_order(api, order_id: str, tender_type: str = "CARD",
                    headers: Optional[Json] = None) -> Json:
    return get_success_data(
        api.authorize_order(
            order_id, F.authorize_payload(tender_type), headers or STORE_TERMINAL_HEADERS
        )
    )


def settle_order(api, order_id: str, headers: Optional[Json] = None) -> Json:
    return get_success_data(api.settle_order(order_id, {}, headers or STORE_TERMINAL_HEADERS))


def read_order(api, order_id: str, headers: Optional[Json] = None) -> Json:
    return get_success_data(api.get_order(order_id, headers or STORE_MANAGER_HEADERS))


def read_order_line(api, line_id: str, headers: Optional[Json] = None) -> Json:
    return get_success_data(api.get_order_line(line_id, headers or STORE_MANAGER_HEADERS))


# ─── Kitchen tickets ──────────────────────────────────────────────────
def list_order_tickets(api, order_id: str) -> List[Json]:
    body = get_success_data(api.list_order_kitchen_tickets(order_id, KITCHEN_ASSOCIATE_HEADERS))
    return body


def find_ticket(api, order_id: str, station: str) -> Json:
    """Return the order's ticket for one station."""
    tickets = list_order_tickets(api, order_id)
    matches = [t for t in tickets if t["station"] == station]
    assert matches, f"order {order_id} has no {station} ticket (stations: " \
                    f"{[t['station'] for t in tickets]})"
    return matches[0]


def start_ticket(api, ticket_id: str, headers: Optional[Json] = None) -> Json:
    return get_success_data(
        api.start_kitchen_ticket(ticket_id, {}, headers or KITCHEN_ASSOCIATE_HEADERS)
    )


def complete_ticket(api, ticket_id: str, headers: Optional[Json] = None) -> Json:
    return get_success_data(
        api.complete_kitchen_ticket(ticket_id, {}, headers or KITCHEN_ASSOCIATE_HEADERS)
    )


def work_ticket_to_done(api, ticket_id: str, headers: Optional[Json] = None) -> Json:
    """Claim a queued ticket and finish it."""
    start_ticket(api, ticket_id, headers)
    return complete_ticket(api, ticket_id, headers)


def reopen_ticket(api, ticket_id: str, reason: str = "Wrong bread used",
                  headers: Optional[Json] = None) -> Json:
    return get_success_data(
        api.reopen_kitchen_ticket(ticket_id, F.reopen_payload(reason), headers or SHIFT_LEAD_HEADERS)
    )


# ─── Composite trading-floor scenarios ────────────────────────────────
def setup_store_open_for_lunch(api, clock: str = C.CLOCK_LUNCH, **store_overrides: Any) -> Json:
    """A fuel-site store flipped to LUNCH with a published LUNCH labor plan.

    This is the minimum state in which an order can be placed: the store's
    operational daypart matches the clock, and the daypart it will be placed
    in has an authorised labor plan.
    """
    set_clock(api, clock)
    store = create_store(api, **store_overrides)
    transition_daypart(api, store["id"], "LUNCH")
    create_published_plan(api, store["id"], daypart="LUNCH")
    return read_store(api, store["id"])


def setup_lunch_trade_with_sandwich(
    api, clock: str = C.CLOCK_LUNCH
) -> Tuple[Json, Json]:
    """Store open for lunch plus the made-to-order sandwich on the menu."""
    store = setup_store_open_for_lunch(api, clock)
    hoagie = create_hoagie(api)
    return store, hoagie


def setup_lunch_trade_with_par_baked_stock(
    api, clock: str = C.CLOCK_LUNCH, planned_qty: int = 40
) -> Tuple[Json, Json, Json, Json]:
    """Store open for lunch, a bakery case, and a pretzel batch on hold.

    Returns ``(store, unit, pretzel, batch)``. The batch is planned before the
    clock reaches lunch so that the bake and pull both land in the past.
    """
    set_clock(api, C.CLOCK_BREAKFAST)
    store = create_store(api)
    unit = create_bakery_case(api, store["id"])
    pretzel = create_pretzel(api)
    batch = create_holding_batch(
        api, store["id"], pretzel["id"], unit["id"], planned_qty=planned_qty
    )
    set_clock(api, clock)
    transition_daypart(api, store["id"], "LUNCH")
    create_published_plan(api, store["id"], daypart="LUNCH")
    return read_store(api, store["id"]), read_holding_unit(api, unit["id"]), pretzel, batch


def setup_placed_order_with_tickets(
    api, clock: str = C.CLOCK_LUNCH
) -> Tuple[Json, Json, Json, Json]:
    """A placed two-station order that has kitchen tickets waiting.

    Returns ``(store, hoagie, coffee, order)``.
    """
    store = setup_store_open_for_lunch(api, clock)
    hoagie = create_hoagie(api)
    coffee = create_coffee(api)
    order = create_draft_order(api, store["id"])
    add_order_line(api, order["id"], hoagie["id"], 1)
    add_order_line(api, order["id"], coffee["id"], 1)
    placed = place_order(api, order["id"])
    return store, hoagie, coffee, placed


def setup_authorized_order_with_tickets(
    api, clock: str = C.CLOCK_LUNCH
) -> Tuple[Json, Json, Json, Json]:
    """The same order, with tender authorised so tickets may be started."""
    store, hoagie, coffee, order = setup_placed_order_with_tickets(api, clock)
    authorized = authorize_order(api, order["id"])
    return store, hoagie, coffee, authorized


def setup_member_with_order(
    api, clock: str = C.CLOCK_LUNCH
) -> Tuple[Json, Json, Json, Json]:
    """A loyalty member with a draft order carrying one sandwich.

    Returns ``(store, hoagie, account, order)``. The order is opened by the
    member themselves, so the customer headers are the account's own id.
    """
    store = setup_store_open_for_lunch(api, clock)
    hoagie = create_hoagie(api)
    account = create_loyalty_account(api)
    customer = make_customer_headers(account["id"])
    order = create_draft_order(
        api, store["id"], headers=customer, loyalty_account_id=account["id"]
    )
    add_order_line(api, order["id"], hoagie["id"], 1, headers=customer)
    return store, hoagie, account, order
