"""Composite setup helpers.

These encapsulate the multi-step API sequences the tests need so that each test
can focus on its assertion. Setup steps use get_success_data() (lenient) so a
broken precondition surfaces as a clear "Setup step failed" error.

The harness restarts the server (empty DB) before every individual test, so each
helper builds its full precondition graph from scratch using PRD endpoints only.
All four roles carry an opaque identity (PRD §2.1): the RevenueManager owns the
property graph, the GroupSalesManager owns group blocks, the ChannelManager owns
channel mappings, and the Analyst is read-only.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS
from . import factories as f

RM = TEST_USERS["revenue_manager_headers"]
GSM = TEST_USERS["group_sales_manager_headers"]
CM = TEST_USERS["channel_manager_headers"]
ANALYST = TEST_USERS["analyst_headers"]


# ─── Clock ────────────────────────────────────────────────────────────────
def set_clock(iso: str):
    """Advance the logical clock to the given ISO instant."""
    get_success_data(api_client.set_clock(iso, RM))


# ─── Base graph builders ────────────────────────────────────────────────────
def create_property(**overrides) -> dict:
    return get_success_data(api_client.create_property(f.create_property_payload(**overrides), RM))


def create_room_type(property_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_room_type(f.create_room_type_payload(property_id, **overrides), RM)
    )


def create_rate_plan(room_type_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_rate_plan(f.create_rate_plan_payload(room_type_id, **overrides), RM)
    )


def create_inventory_day(room_type_id, stay_date=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_inventory_day(
            f.create_inventory_day_payload(room_type_id, stay_date, **overrides), RM
        )
    )


def create_yield_rule(property_id, occupancy_threshold_pct, adjustment_pct, priority, **overrides) -> dict:
    return get_success_data(
        api_client.create_yield_rule(
            f.create_yield_rule_payload(
                property_id, occupancy_threshold_pct, adjustment_pct, priority, **overrides
            ),
            RM,
        )
    )


def create_rate_decision(rate_plan_id, stay_date=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_rate_decision(
            f.create_rate_decision_payload(rate_plan_id, stay_date, **overrides), RM
        )
    )


def create_channel_mapping(rate_plan_id, channel, **overrides) -> dict:
    return get_success_data(
        api_client.create_channel_mapping(
            f.create_channel_mapping_payload(rate_plan_id, channel, **overrides), CM
        )
    )


def create_group_block(room_type_id, arrival_date=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_group_block(
            f.create_group_block_payload(room_type_id, arrival_date, **overrides), GSM
        )
    )


def create_transient_reservation(room_type_id, rate_plan_id, arrival_date=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_transient_reservation(
            f.create_transient_reservation_payload(room_type_id, rate_plan_id, arrival_date, **overrides),
            RM,
        )
    )


def create_competitor_rate(property_id, **overrides) -> dict:
    """Record a competitor rate-shop snapshot (PRD §3.10).

    Either a RevenueManager or a ChannelManager may record snapshots; the
    RevenueManager already owns this fixture's property graph, so use RM.
    """
    return get_success_data(
        api_client.create_competitor_rate(
            f.create_competitor_rate_payload(property_id, **overrides), RM
        )
    )


# ─── Tier 1/2: hierarchy with a master BAR plan ─────────────────────────────
def setup_property_with_room_type(prop_overrides=None, rt_overrides=None):
    """Active property + one room type. Returns (property, room_type)."""
    prop = create_property(**(prop_overrides or {}))
    rt = create_room_type(prop["id"], **(rt_overrides or {}))
    return prop, rt


def setup_master_bar(prop_overrides=None, rt_overrides=None, plan_overrides=None):
    """Property + room type + a master BAR rate plan.

    Returns (property, room_type, rate_plan). The plan is ACTIVE with
    is_master_bar=true so it drives derived/parity rates.
    """
    prop, rt = setup_property_with_room_type(prop_overrides, rt_overrides)
    plan_kwargs = {"is_master_bar": True}
    plan_kwargs.update(plan_overrides or {})
    plan = create_rate_plan(rt["id"], **plan_kwargs)
    return prop, rt, plan


# ─── Tier 3: publish a decision so published_rate is set ────────────────────
def publish_decision(decision_id, expected_rate_plan_version) -> dict:
    return get_success_data(
        api_client.publish_rate_decision(
            decision_id, {"expected_rate_plan_version": expected_rate_plan_version}, RM
        )
    )


def setup_published_master_bar(
    stay_date,
    requested_rate=200.0,
    prop_overrides=None,
    rt_overrides=None,
    plan_overrides=None,
    inv_overrides=None,
):
    """Property/room type/master BAR plan + an InventoryDay for stay_date +
    a DRAFT decision published at requested_rate.

    Returns dict with keys: property, room_type, rate_plan (post-publish,
    so published_rate is set and version is bumped), inventory_day, decision.
    """
    prop, rt, plan = setup_master_bar(prop_overrides, rt_overrides, plan_overrides)
    inv = create_inventory_day(rt["id"], stay_date, **(inv_overrides or {}))
    dec = create_rate_decision(plan["id"], stay_date, requested_rate=requested_rate)
    published = publish_decision(dec["id"], plan["version"])
    plan_after = get_success_data(api_client.get_rate_plan(plan["id"], RM))
    return {
        "property": prop,
        "room_type": rt,
        "rate_plan": plan_after,
        "inventory_day": inv,
        "decision": published,
    }


# ─── Tier 4: group blocks (evaluate / commit) ───────────────────────────────
def evaluate_group_block(block_id, method="LRV") -> dict:
    return get_success_data(
        api_client.evaluate_group_block(block_id, {"method": method}, RM)
    )


def commit_group_block(block_id, expected_room_type_version) -> dict:
    return get_success_data(
        api_client.commit_group_block(
            block_id, {"expected_room_type_version": expected_room_type_version}, GSM
        )
    )


def setup_evaluated_block(
    room_type_id,
    arrival_date,
    method="LRV",
    block_overrides=None,
):
    """Create a NEGOTIATING group block and evaluate it. Returns the evaluated block."""
    block = create_group_block(room_type_id, arrival_date, **(block_overrides or {}))
    return evaluate_group_block(block["id"], method)


def setup_committed_block(
    room_type,
    arrival_date,
    method="LRV",
    block_overrides=None,
):
    """Create + evaluate (ACCEPT expected) + commit a group block on the given room type.

    `room_type` is the full room-type dict (its current version drives the OCC commit).
    Returns the committed block.
    """
    block = setup_evaluated_block(room_type["id"], arrival_date, method, block_overrides)
    return commit_group_block(block["id"], room_type["version"])


# ─── Tier 5: transient reservations ─────────────────────────────────────────
def confirm_reservation(reservation_id) -> dict:
    return get_success_data(api_client.confirm_transient_reservation(reservation_id, RM))


def setup_confirmed_reservation(
    stay_date,
    requested_rate=200.0,
    rooms=1,
    inv_overrides=None,
):
    """Full chain through a CONFIRMED transient reservation:
    property/master BAR plan + published decision + InventoryDay + HELD reservation,
    then confirm it.

    Returns dict: property, room_type, rate_plan, inventory_day, decision, reservation.
    """
    ctx = setup_published_master_bar(
        stay_date, requested_rate=requested_rate, inv_overrides=inv_overrides
    )
    res = create_transient_reservation(
        ctx["room_type"]["id"], ctx["rate_plan"]["id"], stay_date, rooms=rooms
    )
    confirmed = confirm_reservation(res["id"])
    ctx["reservation"] = confirmed
    return ctx
