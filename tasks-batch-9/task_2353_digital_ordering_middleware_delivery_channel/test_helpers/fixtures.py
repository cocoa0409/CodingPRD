"""Composite setup helpers.

Every test starts against an empty database, so each helper here builds its
preconditions from scratch through the documented endpoints. The chain that
almost every scenario needs is: set the logical clock, register the channels,
author and freeze a brand menu version, register a store, declare its operating
hours, and publish the menu to it — after which listings exist and the store is
sellable.

All helpers use the lenient success validator so a broken precondition surfaces
as a setup failure rather than as a confusing assertion inside a test.
"""
from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .test_users import (
    ANALYST_ONE_USER_ID,
    ANALYST_TWO_USER_ID,
    TEST_USERS,
    make_analyst_headers,
    make_channel_partner_headers,
    make_courier_agent_headers,
    make_store_operator_headers,
)

BASE_CLOCK = "2026-08-03T16:00:00Z"
"""Monday 2026-08-03, 16:00 UTC — 11:00 local for a store at offset -300."""

SETTLEMENT_CLOCK = "2026-08-04T01:00:00Z"
"""A clock past midnight so a statement period covering 2026-08-03 is closed."""

DEFAULT_PERIOD_START = "2026-08-03T00:00:00Z"
DEFAULT_PERIOD_END = "2026-08-04T00:00:00Z"

ADMIN = TEST_USERS["admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
SECOND_ANALYST = TEST_USERS["second_analyst_headers"]


# --------------------------------------------------------------------------- #
# Tier 1 — single-step primitives
# --------------------------------------------------------------------------- #
def set_clock(current_utc: str = BASE_CLOCK) -> dict:
    """Move the logical clock. It is inert: nothing is recomputed."""
    return get_success_data(api_client.set_clock(f.set_clock_payload(current_utc), ADMIN))


def create_channel(**overrides) -> dict:
    """Register the marketplace channel unless overridden."""
    return get_success_data(api_client.create_channel(f.create_channel_payload(**overrides), ADMIN))


def create_aggregator_channel(**overrides) -> dict:
    return get_success_data(
        api_client.create_channel(f.create_aggregator_channel_payload(**overrides), ADMIN)
    )


def create_store(**overrides) -> dict:
    return get_success_data(api_client.create_store(f.create_store_payload(**overrides), ADMIN))


def add_hour_window(store_id: str, day_of_week: int = 0, opens_at_minute: int = 600,
                    closes_at_minute: int = 1320) -> dict:
    payload = f.create_hour_window_payload(
        day_of_week=day_of_week,
        opens_at_minute=opens_at_minute,
        closes_at_minute=closes_at_minute,
    )
    return get_success_data(
        api_client.create_hour_window(store_id, payload, make_store_operator_headers(store_id))
    )


def create_menu_version(**overrides) -> dict:
    return get_success_data(
        api_client.create_menu_version(f.create_menu_version_payload(**overrides), ADMIN)
    )


def add_menu_item(menu_version_id: str, payload: dict) -> dict:
    return get_success_data(api_client.create_menu_item(menu_version_id, payload, ADMIN))


def finalize_menu_version(menu_version_id: str) -> dict:
    return get_success_data(api_client.finalize_menu_version(menu_version_id, ADMIN))


def create_courier_network(**overrides) -> dict:
    return get_success_data(
        api_client.create_courier_network(f.create_courier_network_payload(**overrides), ADMIN)
    )


def default_item_payloads():
    """A two-item catalogue: a taxed burger and taxed fries."""
    return [f.burger_item_payload(), f.fries_item_payload()]


def create_finalized_menu_version(brand_code: str = f.BRAND_CODE,
                                  version_label: str = f.VERSION_LABEL,
                                  item_payloads=None) -> tuple:
    """Author a brand menu version, add its items and freeze it.

    Returns (menu_version, {sku: menu_item}).
    """
    version = create_menu_version(brand_code=brand_code, version_label=version_label)
    items = {}
    for payload in (item_payloads if item_payloads is not None else default_item_payloads()):
        item = add_menu_item(version["id"], payload)
        items[item["sku"]] = item
    version = finalize_menu_version(version["id"])
    return version, items


def publish_menu(store_id: str, menu_version_id: str, expected_store_version: int = None) -> dict:
    """Publish a frozen version to a store, declaring the store version seen."""
    if expected_store_version is None:
        expected_store_version = read_store(store_id)["version"]
    payload = f.publish_menu_payload(menu_version_id, expected_store_version)
    return get_success_data(
        api_client.publish_menu(store_id, payload, make_store_operator_headers(store_id))
    )


# --------------------------------------------------------------------------- #
# Reads used by fixtures and tests alike
# --------------------------------------------------------------------------- #
def read_store(store_id: str) -> dict:
    return get_success_data(api_client.get_store(store_id, ADMIN))


def read_channel(channel_id: str) -> dict:
    return get_success_data(api_client.get_channel(channel_id, ADMIN))


def read_menu_version(menu_version_id: str) -> dict:
    return get_success_data(api_client.get_menu_version(menu_version_id, ADMIN))


def read_order(order_id: str) -> dict:
    return get_success_data(api_client.get_order(order_id, ADMIN))


def read_assignment(assignment_id: str) -> dict:
    return get_success_data(api_client.get_delivery_assignment(assignment_id, ADMIN))


def read_network(network_id: str) -> dict:
    return get_success_data(api_client.get_courier_network(network_id, ADMIN))


def read_adjustment(adjustment_id: str) -> dict:
    return get_success_data(api_client.get_adjustment(adjustment_id, ADMIN))


def read_statement(statement_id: str) -> dict:
    return get_success_data(api_client.get_statement(statement_id, ADMIN))


def list_listings(**params) -> list:
    body = api_client.list_channel_listings(ADMIN, params=params).json()
    return body["data"]


# --------------------------------------------------------------------------- #
# Tier 2 — the published-store scenario every workflow needs
# --------------------------------------------------------------------------- #
def setup_published_store(clock: str = BASE_CLOCK,
                          channel_payloads=None,
                          item_payloads=None,
                          store_overrides=None,
                          hour_windows=((0, 600, 1320),),
                          brand_code: str = f.BRAND_CODE,
                          version_label: str = f.VERSION_LABEL) -> dict:
    """Clock, channels, frozen menu, store, hours and a first publish.

    Returns an environment dict with keys: `store`, `channels` (by code),
    `channel` (the first one registered), `menu_version`, `items` (by sku),
    `hour_windows`, `store_headers`, `partner_headers` (by code).
    """
    set_clock(clock)

    channels = {}
    for payload in (channel_payloads if channel_payloads is not None else [f.create_channel_payload()]):
        channel = get_success_data(api_client.create_channel(payload, ADMIN))
        channels[channel["code"]] = channel
    first_code = next(iter(channels))

    menu_version, items = create_finalized_menu_version(
        brand_code=brand_code, version_label=version_label, item_payloads=item_payloads
    )

    store_payload = dict(brand_code=brand_code)
    store_payload.update(store_overrides or {})
    store = create_store(**store_payload)

    windows = [add_hour_window(store["id"], *window) for window in hour_windows]

    store = publish_menu(store["id"], menu_version["id"], store["version"])

    return {
        "clock": clock,
        "store": store,
        "channels": channels,
        "channel": channels[first_code],
        "menu_version": read_menu_version(menu_version["id"]),
        "items": items,
        "hour_windows": windows,
        "store_headers": make_store_operator_headers(store["id"]),
        "partner_headers": {code: make_channel_partner_headers(ch["id"]) for code, ch in channels.items()},
    }


def setup_two_channel_store(**kwargs) -> dict:
    """A store published to a marketplace channel and an aggregator channel."""
    kwargs.setdefault(
        "channel_payloads", [f.create_channel_payload(), f.create_aggregator_channel_payload()]
    )
    return setup_published_store(**kwargs)


def env_channel(env: dict, channel_code: str = None) -> dict:
    return env["channel"] if channel_code is None else env["channels"][channel_code]


def env_partner_headers(env: dict, channel_code: str = None) -> dict:
    return make_channel_partner_headers(env_channel(env, channel_code)["id"])


def env_store_headers(env: dict) -> dict:
    return make_store_operator_headers(env["store"]["id"])


def refresh_store(env: dict) -> dict:
    env["store"] = read_store(env["store"]["id"])
    return env["store"]


def listing_for(env: dict, sku: str, channel_code: str = None) -> dict:
    """The listing built for one item on one channel at this store."""
    channel = env_channel(env, channel_code)
    rows = list_listings(store_id=env["store"]["id"], channel_id=channel["id"], limit=100)
    for row in rows:
        if row["sku"] == sku:
            return row
    raise AssertionError(f"Setup failed: no listing for sku {sku} on channel {channel['code']}")


def suppress_listing(env: dict, sku: str, channel_code: str = None, suppressed: bool = True) -> dict:
    listing = listing_for(env, sku, channel_code)
    headers = env_partner_headers(env, channel_code)
    return get_success_data(
        api_client.patch_channel_listing(listing["id"], f.patch_listing_payload(suppressed), headers)
    )


# --------------------------------------------------------------------------- #
# Tier 3 — order lifecycle shortcuts
# --------------------------------------------------------------------------- #
def default_order_lines():
    return [f.order_line(f.BURGER_SKU, 2), f.order_line(f.FRIES_SKU, 1)]


def place_order(env: dict, channel_code: str = None, external_ref: str = "EXT-1",
                fulfillment_mode: str = "DELIVERY", lines=None, tip_cents: int = 200) -> dict:
    channel = env_channel(env, channel_code)
    payload = f.create_order_payload(
        env["store"]["id"],
        channel["id"],
        external_ref=external_ref,
        fulfillment_mode=fulfillment_mode,
        lines=lines if lines is not None else default_order_lines(),
        tip_cents=tip_cents,
    )
    return get_success_data(
        api_client.create_order(payload, make_channel_partner_headers(channel["id"]))
    )


def inject_order(env: dict, order_id: str, pos_result_code: str = "OK") -> dict:
    return get_success_data(
        api_client.inject_order(order_id, f.inject_payload(pos_result_code), env_store_headers(env))
    )


def place_injected_order(env: dict, **kwargs) -> dict:
    """Place an order and have the register accept it."""
    order = place_order(env, **kwargs)
    return inject_order(env, order["id"])


def mark_ready(env: dict, order_id: str) -> dict:
    return get_success_data(api_client.mark_order_ready(order_id, env_store_headers(env)))


def place_ready_order(env: dict, **kwargs) -> dict:
    """Place an order, inject it and mark it ready in the kitchen."""
    order = place_injected_order(env, **kwargs)
    return mark_ready(env, order["id"])


def cancel_order(env: dict, order_id: str, reason_code: str = "GUEST_CANCELLED",
                 as_partner_code: str = None) -> dict:
    headers = env_store_headers(env) if as_partner_code is None else env_partner_headers(env, as_partner_code)
    return get_success_data(
        api_client.cancel_order(order_id, f.cancel_order_payload(reason_code), headers)
    )


def recompute_throttle(env: dict) -> dict:
    store = get_success_data(api_client.recompute_throttle(env["store"]["id"], env_store_headers(env)))
    env["store"] = store
    return store


def quote(env: dict, channel_code: str = None, fulfillment_mode: str = "DELIVERY") -> dict:
    channel = env_channel(env, channel_code)
    params = {"channel_id": channel["id"], "fulfillment_mode": fulfillment_mode}
    return get_success_data(
        api_client.get_quote(env["store"]["id"], env_store_headers(env), params=params)
    )


def record_availability_event(env: dict, sku: str, event_type: str = "EIGHTY_SIX",
                              actor_channel_code: str = None, as_partner_code: str = None) -> dict:
    """86 or restore an item at this store, optionally reported by a channel."""
    item = env["items"][sku]
    payload = f.create_availability_event_payload(env["store"]["id"], item["id"], event_type)
    if actor_channel_code is not None:
        payload["actor_channel_id"] = env["channels"][actor_channel_code]["id"]
    headers = env_store_headers(env) if as_partner_code is None else env_partner_headers(env, as_partner_code)
    return get_success_data(api_client.create_availability_event(payload, headers))


def resume_injection(env: dict, order_id: str) -> dict:
    return get_success_data(api_client.resume_injection(order_id, env_store_headers(env)))


# --------------------------------------------------------------------------- #
# Tier 3 — delivery lifecycle shortcuts
# --------------------------------------------------------------------------- #
def dispatch_order(env: dict, order_id: str) -> dict:
    return get_success_data(api_client.dispatch_order(order_id, env_store_headers(env)))


def accept_assignment(assignment: dict) -> dict:
    headers = make_courier_agent_headers(assignment["courier_network_id"])
    return get_success_data(api_client.accept_assignment(assignment["id"], headers))


def decline_assignment(assignment: dict) -> dict:
    headers = make_courier_agent_headers(assignment["courier_network_id"])
    return get_success_data(api_client.decline_assignment(assignment["id"], headers))


def handoff_assignment(assignment: dict) -> dict:
    headers = make_courier_agent_headers(assignment["courier_network_id"])
    return get_success_data(api_client.handoff_assignment(assignment["id"], headers))


def deliver_assignment(assignment: dict) -> dict:
    headers = make_courier_agent_headers(assignment["courier_network_id"])
    return get_success_data(api_client.deliver_assignment(assignment["id"], headers))


def setup_ready_delivery_with_network(network_overrides=None, env=None, **env_kwargs) -> tuple:
    """A ready delivery order plus one registered courier network.

    Returns (env, order, network).
    """
    env = env if env is not None else setup_published_store(**env_kwargs)
    network = create_courier_network(**(network_overrides or {}))
    order = place_ready_order(env)
    return env, order, network


def setup_accepted_assignment(network_overrides=None, env=None, **env_kwargs) -> tuple:
    """A ready delivery order offered to and accepted by a courier network.

    Returns (env, order, network, assignment).
    """
    env, order, network = setup_ready_delivery_with_network(network_overrides, env, **env_kwargs)
    assignment = dispatch_order(env, order["id"])
    assignment = accept_assignment(assignment)
    return env, order, network, assignment


# --------------------------------------------------------------------------- #
# Tier 4 — accumulation and threshold targeting
# --------------------------------------------------------------------------- #
def fill_bucket(env: dict, count: int, channel_code: str = None, ref_prefix: str = "FILL") -> list:
    """Place `count` orders so the current capacity bucket carries that load."""
    return [
        place_order(env, channel_code=channel_code, external_ref=f"{ref_prefix}-{index}")
        for index in range(count)
    ]


def setup_throttled_store(env: dict = None, **env_kwargs) -> tuple:
    """Reserve exactly `prep_capacity_per_bucket` slots and recompute the posture.

    Returns (env, orders). The store lands in `THROTTLED` because the throttle
    thresholds are inclusive.
    """
    env = env if env is not None else setup_published_store(**env_kwargs)
    capacity = env["store"]["prep_capacity_per_bucket"]
    orders = fill_bucket(env, capacity, ref_prefix="THR")
    recompute_throttle(env)
    return env, orders


# --------------------------------------------------------------------------- #
# Tier 4 — adjustment lifecycle
# --------------------------------------------------------------------------- #
def propose_adjustment(order: dict, amount_cents: int = 1000, adjustment_type: str = "REFUND",
                       reason_code: str = "MISSING_ITEM", analyst_user_id: str = ANALYST_ONE_USER_ID,
                       expected_order_version: int = None) -> dict:
    version = order["version"] if expected_order_version is None else expected_order_version
    payload = f.create_adjustment_payload(
        order["id"], version,
        adjustment_type=adjustment_type, amount_cents=amount_cents, reason_code=reason_code,
    )
    return get_success_data(
        api_client.create_adjustment(payload, make_analyst_headers(analyst_user_id))
    )


def submit_adjustment(adjustment: dict, analyst_user_id: str = ANALYST_ONE_USER_ID) -> dict:
    return get_success_data(
        api_client.submit_adjustment(adjustment["id"], make_analyst_headers(analyst_user_id))
    )


def accept_adjustment(adjustment: dict) -> dict:
    headers = make_channel_partner_headers(adjustment["channel_id"])
    return get_success_data(api_client.accept_adjustment(adjustment["id"], headers))


def request_adjustment_revision(adjustment: dict, note: str = None) -> dict:
    headers = make_channel_partner_headers(adjustment["channel_id"])
    payload = f.request_revision_payload(**({"note": note} if note is not None else {}))
    return get_success_data(api_client.request_adjustment_revision(adjustment["id"], headers, payload))


def revise_adjustment(adjustment: dict, analyst_user_id: str = ANALYST_ONE_USER_ID, **overrides) -> dict:
    payload = f.revise_adjustment_payload(**overrides)
    return get_success_data(
        api_client.revise_adjustment(adjustment["id"], make_analyst_headers(analyst_user_id), payload)
    )


def reverse_adjustment(adjustment: dict, analyst_user_id: str = ANALYST_TWO_USER_ID,
                       reason_code: str = "PROPOSED_IN_ERROR") -> dict:
    return get_success_data(
        api_client.reverse_adjustment(
            adjustment["id"], f.reverse_adjustment_payload(reason_code),
            make_analyst_headers(analyst_user_id),
        )
    )


def create_accepted_adjustment(order: dict, amount_cents: int = 1000,
                               adjustment_type: str = "REFUND",
                               analyst_user_id: str = ANALYST_ONE_USER_ID) -> dict:
    """Propose, submit and accept an adjustment so the order's money has moved.

    On a channel that reviews adjustments by hand the partner accepts it; on an
    auto-accept channel submission already accepted it.
    """
    adjustment = propose_adjustment(
        order, amount_cents=amount_cents, adjustment_type=adjustment_type,
        analyst_user_id=analyst_user_id,
    )
    adjustment = submit_adjustment(adjustment, analyst_user_id)
    if adjustment["state"] == "CHANNEL_REVIEW":
        adjustment = accept_adjustment(adjustment)
    return adjustment


def create_adjustment_in_review(order: dict, amount_cents: int = 1000,
                                analyst_user_id: str = ANALYST_ONE_USER_ID) -> dict:
    """An adjustment left sitting with the channel partner (an open state)."""
    adjustment = propose_adjustment(order, amount_cents=amount_cents, analyst_user_id=analyst_user_id)
    return submit_adjustment(adjustment, analyst_user_id)


# --------------------------------------------------------------------------- #
# Tier 5 — statement lifecycle and terminal states
# --------------------------------------------------------------------------- #
def open_statement(channel_id: str, period_start: str = DEFAULT_PERIOD_START,
                   period_end: str = DEFAULT_PERIOD_END,
                   analyst_user_id: str = ANALYST_ONE_USER_ID) -> dict:
    payload = f.create_statement_payload(channel_id, period_start=period_start, period_end=period_end)
    return get_success_data(
        api_client.create_statement(payload, make_analyst_headers(analyst_user_id))
    )


def assign_orders(statement: dict, order_ids, analyst_user_id: str = ANALYST_ONE_USER_ID) -> dict:
    return get_success_data(
        api_client.assign_orders(
            statement["id"], f.assign_orders_payload(order_ids),
            make_analyst_headers(analyst_user_id),
        )
    )


def reconcile_statement(statement: dict, analyst_user_id: str = ANALYST_ONE_USER_ID) -> dict:
    return get_success_data(
        api_client.reconcile_statement(statement["id"], make_analyst_headers(analyst_user_id))
    )


def settle_statement(statement: dict, analyst_user_id: str = ANALYST_TWO_USER_ID) -> dict:
    return get_success_data(
        api_client.settle_statement(statement["id"], make_analyst_headers(analyst_user_id))
    )


def dispute_statement(statement: dict, reason_code: str = "FIGURES_DISPUTED") -> dict:
    headers = make_channel_partner_headers(statement["channel_id"])
    return get_success_data(
        api_client.dispute_statement(statement["id"], f.dispute_statement_payload(reason_code), headers)
    )


def preview_statement(statement: dict, analyst_user_id: str = ANALYST_ONE_USER_ID) -> dict:
    return get_success_data(
        api_client.preview_statement(statement["id"], make_analyst_headers(analyst_user_id))
    )


def setup_statement_with_orders(env: dict, orders, channel_code: str = None,
                                clock: str = SETTLEMENT_CLOCK,
                                period_start: str = DEFAULT_PERIOD_START,
                                period_end: str = DEFAULT_PERIOD_END,
                                analyst_user_id: str = ANALYST_ONE_USER_ID) -> dict:
    """Close the period on the clock, open a statement and attach the orders."""
    set_clock(clock)
    channel = env_channel(env, channel_code)
    statement = open_statement(channel["id"], period_start, period_end, analyst_user_id)
    return assign_orders(statement, [order["id"] for order in orders], analyst_user_id)


def setup_reconciled_statement(env: dict, orders, channel_code: str = None,
                               analyst_user_id: str = ANALYST_ONE_USER_ID, **kwargs) -> dict:
    statement = setup_statement_with_orders(
        env, orders, channel_code=channel_code, analyst_user_id=analyst_user_id, **kwargs
    )
    return reconcile_statement(statement, analyst_user_id)


def setup_settled_statement(env: dict, orders, channel_code: str = None,
                            reconciler_user_id: str = ANALYST_ONE_USER_ID,
                            settler_user_id: str = ANALYST_TWO_USER_ID, **kwargs) -> dict:
    statement = setup_reconciled_statement(
        env, orders, channel_code=channel_code, analyst_user_id=reconciler_user_id, **kwargs
    )
    return settle_statement(statement, settler_user_id)


def setup_settleable_ready_order(env: dict = None, channel_code: str = None, **env_kwargs) -> tuple:
    """A single fulfilled order that a statement may legitimately take.

    Returns (env, order).
    """
    env = env if env is not None else setup_published_store(**env_kwargs)
    order = place_ready_order(env, channel_code=channel_code)
    return env, order
