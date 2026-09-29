"""Composite setup helpers.

Every helper builds its state from scratch through the PRD's own endpoints, so a
test may call any of them against an empty database. Setup calls go through the
lenient validator so a broken preamble reports "Setup step failed" rather than a
confusing assertion deep inside a test.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from .constants import DEFAULT_CLOCK_UTC, TEST_DEFAULTS
from .factories import (
    acknowledge_payload,
    create_blackout_payload,
    create_integration_test_payload,
    create_inventory_snapshot_payload,
    create_item_payload,
    create_order_payload,
    create_return_payload,
    create_serviceability_rule_payload,
    create_vendor_payload,
    evaluate_integration_test_payload,
    order_line_input,
    seeded_scorecard_payload,
    ship_confirm_payload,
)
from .test_users import (
    TEST_USERS,
    make_merchandise_manager_headers,
    make_vendor_ops_analyst_headers,
    make_vendor_user_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["vendor_ops_analyst_headers"]
MM = TEST_USERS["merchandise_manager_headers"]
CARE = TEST_USERS["care_agent_headers"]

ALL_MESSAGE_TYPES = ["CATALOG", "INVENTORY", "ORDER", "SHIP_CONFIRM"]


# ─── Logical clock ────────────────────────────────────


def set_clock(api: ApiClient, current_utc: str) -> Dict[str, Any]:
    """Move the logical clock. Only PlatformAdmin may drive it."""
    return get_success_data(api.set_clock(current_utc, ADMIN))


def reset_clock(api: ApiClient) -> Dict[str, Any]:
    """Pin the clock back to the default the system starts at."""
    return set_clock(api, DEFAULT_CLOCK_UTC)


# ─── Read-through refreshers ──────────────────────────


def refresh_vendor(api: ApiClient, vendor_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_vendor(vendor_id, ADMIN))


def refresh_item(api: ApiClient, item_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_item(item_id, ADMIN))


def refresh_order(api: ApiClient, order_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_order(order_id, ADMIN))


def refresh_line(api: ApiClient, line_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_order_line(line_id, ADMIN))


def refresh_return(api: ApiClient, return_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_return(return_id, ADMIN))


def order_lines_of(api: ApiClient, order_id: str) -> List[Dict[str, Any]]:
    """Lines of one order, ordered by line_number."""
    body = api.list_order_lines(ADMIN, params={"order_id": order_id, "limit": 100})
    data = body.json()["data"]
    return sorted(data, key=lambda row: row["line_number"])


# ─── Tier 1: vendor onboarding progression ────────────


def create_draft_vendor(
    api: ApiClient, suffix: str = "V1", **overrides
) -> Dict[str, Any]:
    """A DRAFT vendor with a unique vendor_code."""
    payload = create_vendor_payload(vendor_code=f"VEND-{suffix}", **overrides)
    return get_success_data(api.create_vendor(payload, ADMIN))


def run_integration_rounds(
    api: ApiClient,
    vendor_id: str,
    suffix: str = "V1",
    outcomes: Optional[Dict[str, str]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Begin integration and record plus evaluate one test per message type.

    The recorder and the evaluator are deliberately different operator ids: the
    same id may not do both. Returns the evaluated tests keyed by message type.
    """
    get_success_data(api.begin_integration(vendor_id, OPS))
    recorder = make_vendor_ops_analyst_headers(f"ops-recorder-{suffix}")
    evaluator = make_vendor_ops_analyst_headers(f"ops-evaluator-{suffix}")
    outcomes = outcomes or {}
    tests: Dict[str, Dict[str, Any]] = {}
    for message_type in ALL_MESSAGE_TYPES:
        created = get_success_data(
            api.record_integration_test(
                vendor_id, create_integration_test_payload(message_type), recorder
            )
        )
        tests[message_type] = created
    for message_type in ALL_MESSAGE_TYPES:
        outcome = outcomes.get(message_type, "PASS")
        tests[message_type] = get_success_data(
            api.evaluate_integration_test(
                tests[message_type]["id"],
                evaluate_integration_test_payload(outcome),
                evaluator,
            )
        )
    return tests


def add_serviceability_rule(
    api: ApiClient, vendor_id: str, **overrides
) -> Dict[str, Any]:
    """One coverage row for a vendor."""
    return get_success_data(
        api.create_serviceability_rule(
            vendor_id, create_serviceability_rule_payload(**overrides), MM
        )
    )


def create_certified_vendor(
    api: ApiClient,
    suffix: str = "V1",
    rules: Optional[List[Dict[str, Any]]] = None,
    **vendor_overrides,
) -> Dict[str, Any]:
    """Create a vendor, pass every integration test, add coverage, certify."""
    vendor = create_draft_vendor(api, suffix=suffix, **vendor_overrides)
    run_integration_rounds(api, vendor["id"], suffix=suffix)
    for rule in rules if rules is not None else [{}]:
        add_serviceability_rule(api, vendor["id"], **rule)
    certifier = make_vendor_ops_analyst_headers(f"ops-cert-{suffix}")
    return get_success_data(api.certify_vendor(vendor["id"], certifier))


def create_active_vendor(
    api: ApiClient,
    suffix: str = "V1",
    rules: Optional[List[Dict[str, Any]]] = None,
    **vendor_overrides,
) -> Dict[str, Any]:
    """Walk a vendor all the way to ACTIVE.

    Activation is performed by an operator id distinct from the certifier's.
    """
    vendor = create_certified_vendor(api, suffix=suffix, rules=rules, **vendor_overrides)
    activator = make_merchandise_manager_headers(f"mm-activator-{suffix}")
    return get_success_data(api.activate_vendor(vendor["id"], activator))


# ─── Tier 2: offers and inventory ─────────────────────


def create_draft_item(api: ApiClient, vendor_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_item(create_item_payload(vendor_id, **overrides), MM)
    )


def create_active_item(api: ApiClient, vendor_id: str, **overrides) -> Dict[str, Any]:
    """A DRAFT offer walked to ACTIVE. The owning vendor must already be ACTIVE."""
    item = create_draft_item(api, vendor_id, **overrides)
    return get_success_data(api.activate_item(item["id"], MM))


def feed_inventory(
    api: ApiClient,
    item_id: str,
    vendor_id: str,
    on_hand_units: int = TEST_DEFAULTS["ON_HAND_UNITS"],
    effective_from: str = "2026-08-03T09:00:00Z",
    feed_sequence: int = 1,
    effective_to: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    """Post one feed message as the owning vendor.

    The expected version is read back from the offer immediately before the post,
    so a caller never has to track version drift by hand.
    """
    current = refresh_item(api, item_id)
    payload = create_inventory_snapshot_payload(
        expected_item_version=current["version"],
        on_hand_units=on_hand_units,
        effective_from=effective_from,
        feed_sequence=feed_sequence,
        **overrides,
    )
    if effective_to is not None:
        payload["effective_to"] = effective_to
    return get_success_data(
        api.create_inventory_snapshot(
            item_id, payload, make_vendor_user_headers(vendor_id)
        )
    )


def setup_vendor_with_active_offer(
    api: ApiClient,
    suffix: str = "V1",
    vendor_overrides: Optional[Dict[str, Any]] = None,
    item_overrides: Optional[Dict[str, Any]] = None,
    rules: Optional[List[Dict[str, Any]]] = None,
    on_hand_units: int = TEST_DEFAULTS["ON_HAND_UNITS"],
    feed_at: str = "2026-08-03T09:00:00Z",
    now_at: str = "2026-08-03T10:00:00Z",
    feed: bool = True,
) -> Dict[str, Any]:
    """The canonical orderable state.

    Clock at the default, vendor ACTIVE with coverage, one ACTIVE offer, one fresh
    feed message, then the clock moved to `now_at`. Returns the vendor, the offer,
    and the ids of both.
    """
    reset_clock(api)
    vendor = create_active_vendor(
        api, suffix=suffix, rules=rules, **(vendor_overrides or {})
    )
    item = create_active_item(api, vendor["id"], **(item_overrides or {}))
    if feed:
        set_clock(api, feed_at)
        feed_inventory(
            api,
            item["id"],
            vendor["id"],
            on_hand_units=on_hand_units,
            effective_from=feed_at,
        )
    set_clock(api, now_at)
    return {
        "vendor": refresh_vendor(api, vendor["id"]),
        "item": refresh_item(api, item["id"]),
        "vendor_id": vendor["id"],
        "item_id": item["id"],
    }


def add_blackout(api: ApiClient, vendor_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_blackout(vendor_id, create_blackout_payload(**overrides), OPS)
    )


# ─── Tier 3: orders and line lifecycle ────────────────


def place_order(
    api: ApiClient,
    item_id: str,
    quantity: int = 1,
    order_ref: str = "ORD-1",
    customer_zone_code: str = TEST_DEFAULTS["ZONE_CODE"],
    extra_lines: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    lines = [order_line_input(item_id, quantity)]
    if extra_lines:
        lines.extend(extra_lines)
    return get_success_data(
        api.create_order(
            create_order_payload(order_ref, lines, customer_zone_code=customer_zone_code),
            CARE,
        )
    )


def place_and_transmit_order(
    api: ApiClient,
    item_id: str,
    quantity: int = 1,
    order_ref: str = "ORD-1",
    customer_zone_code: str = TEST_DEFAULTS["ZONE_CODE"],
    extra_lines: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Place an order and hand every line off to its vendor.

    Returns the order and its lines.
    """
    order = place_order(
        api,
        item_id,
        quantity=quantity,
        order_ref=order_ref,
        customer_zone_code=customer_zone_code,
        extra_lines=extra_lines,
    )
    get_success_data(api.transmit_order(order["id"], MM))
    return {
        "order": refresh_order(api, order["id"]),
        "lines": order_lines_of(api, order["id"]),
        "order_id": order["id"],
    }


def setup_transmitted_line(
    api: ApiClient,
    quantity: int = 2,
    order_ref: str = "ORD-1",
    suffix: str = "V1",
    **setup_kwargs,
) -> Dict[str, Any]:
    """One TRANSMITTED line on an ACTIVE offer of an ACTIVE vendor."""
    base = setup_vendor_with_active_offer(api, suffix=suffix, **setup_kwargs)
    placed = place_and_transmit_order(
        api, base["item_id"], quantity=quantity, order_ref=order_ref
    )
    line = placed["lines"][0]
    return {
        **base,
        "order": placed["order"],
        "order_id": placed["order_id"],
        "line": line,
        "line_id": line["id"],
        "quantity": quantity,
    }


def setup_acknowledged_line(
    api: ApiClient,
    quantity: int = 2,
    order_ref: str = "ORD-1",
    suffix: str = "V1",
    **setup_kwargs,
) -> Dict[str, Any]:
    """A transmitted line the vendor has accepted."""
    state = setup_transmitted_line(
        api, quantity=quantity, order_ref=order_ref, suffix=suffix, **setup_kwargs
    )
    get_success_data(
        api.acknowledge_line(
            state["line_id"],
            acknowledge_payload("ACCEPTED"),
            make_vendor_user_headers(state["vendor_id"]),
        )
    )
    state["line"] = refresh_line(api, state["line_id"])
    return state


def setup_backordered_line(
    api: ApiClient,
    quantity: int = 2,
    order_ref: str = "ORD-1",
    suffix: str = "V1",
    **setup_kwargs,
) -> Dict[str, Any]:
    """A transmitted line the vendor has backordered."""
    state = setup_transmitted_line(
        api, quantity=quantity, order_ref=order_ref, suffix=suffix, **setup_kwargs
    )
    get_success_data(
        api.acknowledge_line(
            state["line_id"],
            acknowledge_payload("BACKORDERED"),
            make_vendor_user_headers(state["vendor_id"]),
        )
    )
    state["line"] = refresh_line(api, state["line_id"])
    return state


def ship_confirm(
    api: ApiClient,
    line_id: str,
    vendor_id: str,
    shipped_units: int,
    **overrides,
) -> Dict[str, Any]:
    """Ship-confirm a line as its vendor. shipped_units must equal the quantity."""
    return get_success_data(
        api.ship_confirm_line(
            line_id,
            ship_confirm_payload(shipped_units, **overrides),
            make_vendor_user_headers(vendor_id),
        )
    )


def setup_shipped_line(
    api: ApiClient,
    quantity: int = 2,
    order_ref: str = "ORD-1",
    suffix: str = "V1",
    ship_at: Optional[str] = None,
    **setup_kwargs,
) -> Dict[str, Any]:
    """A line walked all the way to SHIPPED, with its shipment row created."""
    state = setup_acknowledged_line(
        api, quantity=quantity, order_ref=order_ref, suffix=suffix, **setup_kwargs
    )
    if ship_at is not None:
        set_clock(api, ship_at)
    shipment = ship_confirm(api, state["line_id"], state["vendor_id"], quantity)
    state["shipment"] = shipment
    state["line"] = refresh_line(api, state["line_id"])
    state["order"] = refresh_order(api, state["order_id"])
    state["item"] = refresh_item(api, state["item_id"])
    state["vendor"] = refresh_vendor(api, state["vendor_id"])
    return state


def cancel_line(api: ApiClient, line_id: str, vendor_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.cancel_line(line_id, make_vendor_user_headers(vendor_id))
    )


# ─── Tier 4: returns ──────────────────────────────────


def open_return(
    api: ApiClient,
    line_id: str,
    quantity_returned: int = 1,
    reason_code: str = "DEFECTIVE",
) -> Dict[str, Any]:
    return get_success_data(
        api.create_return(
            create_return_payload(
                line_id, quantity_returned=quantity_returned, reason_code=reason_code
            ),
            CARE,
        )
    )


def setup_authorized_return(
    api: ApiClient,
    quantity: int = 2,
    quantity_returned: int = 1,
    reason_code: str = "DEFECTIVE",
    order_ref: str = "ORD-1",
    suffix: str = "V1",
    **setup_kwargs,
) -> Dict[str, Any]:
    """A shipped line with one AUTHORIZED return against it."""
    state = setup_shipped_line(
        api, quantity=quantity, order_ref=order_ref, suffix=suffix, **setup_kwargs
    )
    ra = open_return(
        api,
        state["line_id"],
        quantity_returned=quantity_returned,
        reason_code=reason_code,
    )
    state["return"] = get_success_data(api.authorize_return(ra["id"], CARE))
    state["return_id"] = ra["id"]
    state["vendor"] = refresh_vendor(api, state["vendor_id"])
    state["order"] = refresh_order(api, state["order_id"])
    return state


# ─── Tier 5: scorecards ───────────────────────────────


def create_seeded_scorecard(
    api: ApiClient,
    vendor_id: str,
    avg_ship_hours: float,
    on_time_bps: int,
    cancellation_bps: int,
    defect_bps: int,
    period_start: str = "2026-07-01",
    period_end: str = "2026-07-31",
    metric_variant: str = "EVENT_EQUAL",
) -> Dict[str, Any]:
    """A DRAFT scorecard computed purely from seeded prior history."""
    return get_success_data(
        api.create_scorecard(
            vendor_id,
            seeded_scorecard_payload(
                avg_ship_hours,
                on_time_bps,
                cancellation_bps,
                defect_bps,
                period_start=period_start,
                period_end=period_end,
                metric_variant=metric_variant,
            ),
            OPS,
        )
    )


def publish_scorecard(
    api: ApiClient, scorecard_id: str, vendor_id: str
) -> Dict[str, Any]:
    """Publish a scorecard, reading the vendor's current version first."""
    vendor = refresh_vendor(api, vendor_id)
    return get_success_data(
        api.publish_scorecard(scorecard_id, vendor["version"], ADMIN)
    )


def publish_seeded_scorecard(
    api: ApiClient,
    vendor_id: str,
    avg_ship_hours: float,
    on_time_bps: int,
    cancellation_bps: int,
    defect_bps: int,
    period_start: str = "2026-07-01",
    period_end: str = "2026-07-31",
    metric_variant: str = "EVENT_EQUAL",
) -> Dict[str, Any]:
    """Create and publish a seeded scorecard, propagating its tier onto the vendor."""
    scorecard = create_seeded_scorecard(
        api,
        vendor_id,
        avg_ship_hours,
        on_time_bps,
        cancellation_bps,
        defect_bps,
        period_start=period_start,
        period_end=period_end,
        metric_variant=metric_variant,
    )
    return publish_scorecard(api, scorecard["id"], vendor_id)


def create_period_scorecard(
    api: ApiClient,
    vendor_id: str,
    period_start: str,
    period_end: str,
    metric_variant: str = "EVENT_EQUAL",
) -> Dict[str, Any]:
    """A DRAFT scorecard computed from real line history in the window."""
    return get_success_data(
        api.create_scorecard(
            vendor_id,
            {
                "period_start": period_start,
                "period_end": period_end,
                "metric_variant": metric_variant,
            },
            OPS,
        )
    )


# ─── Tier 6: endless-aisle fallback chains ────────────


def setup_fallback_pair(
    api: ApiClient,
    sku: str = TEST_DEFAULTS["SKU"],
    quantity_on_hand_primary: int = 60,
    quantity_on_hand_fallback: int = 60,
    primary_overrides: Optional[Dict[str, Any]] = None,
    fallback_overrides: Optional[Dict[str, Any]] = None,
    primary_vendor_overrides: Optional[Dict[str, Any]] = None,
    fallback_vendor_overrides: Optional[Dict[str, Any]] = None,
    zone_code: str = TEST_DEFAULTS["ZONE_CODE"],
    feed_at: str = "2026-08-03T09:00:00Z",
    now_at: str = "2026-08-03T10:00:00Z",
    feed_fallback: bool = True,
) -> Dict[str, Any]:
    """Two ACTIVE vendors carrying the same sku, the first pointing at the second.

    A fallback link may only point at another vendor's offer of the same sku, so
    the two offers live on two separate vendors. Returns both vendors and both
    offers plus their ids.
    """
    reset_clock(api)
    vendor_b = create_active_vendor(
        api,
        suffix="FB",
        rules=[{"zone_code": zone_code}],
        **(fallback_vendor_overrides or {}),
    )
    item_b = create_active_item(
        api, vendor_b["id"], sku=sku, **(fallback_overrides or {})
    )
    vendor_a = create_active_vendor(
        api,
        suffix="PR",
        rules=[{"zone_code": zone_code}],
        **(primary_vendor_overrides or {}),
    )
    item_a = create_active_item(
        api,
        vendor_a["id"],
        sku=sku,
        fallback_item_id=item_b["id"],
        **(primary_overrides or {}),
    )
    set_clock(api, feed_at)
    feed_inventory(
        api,
        item_a["id"],
        vendor_a["id"],
        on_hand_units=quantity_on_hand_primary,
        effective_from=feed_at,
    )
    if feed_fallback:
        feed_inventory(
            api,
            item_b["id"],
            vendor_b["id"],
            on_hand_units=quantity_on_hand_fallback,
            effective_from=feed_at,
        )
    set_clock(api, now_at)
    return {
        "primary_vendor": refresh_vendor(api, vendor_a["id"]),
        "fallback_vendor": refresh_vendor(api, vendor_b["id"]),
        "primary_item": refresh_item(api, item_a["id"]),
        "fallback_item": refresh_item(api, item_b["id"]),
        "primary_vendor_id": vendor_a["id"],
        "fallback_vendor_id": vendor_b["id"],
        "primary_item_id": item_a["id"],
        "fallback_item_id": item_b["id"],
    }


def setup_backordered_line_with_fallback(
    api: ApiClient,
    quantity: int = 2,
    order_ref: str = "ORD-FB-1",
    **pair_kwargs,
) -> Dict[str, Any]:
    """A BACKORDERED line whose offer declares a live endless-aisle fallback."""
    pair = setup_fallback_pair(api, **pair_kwargs)
    placed = place_and_transmit_order(
        api, pair["primary_item_id"], quantity=quantity, order_ref=order_ref
    )
    line = placed["lines"][0]
    get_success_data(
        api.acknowledge_line(
            line["id"],
            acknowledge_payload("BACKORDERED"),
            make_vendor_user_headers(pair["primary_vendor_id"]),
        )
    )
    return {
        **pair,
        "order": refresh_order(api, placed["order_id"]),
        "order_id": placed["order_id"],
        "line": refresh_line(api, line["id"]),
        "line_id": line["id"],
        "quantity": quantity,
    }
