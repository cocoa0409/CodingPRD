"""Composite setup helpers.

Multi-step PRD workflows (dealer onboarding, order submission, batch
assignment, run release, route assignment, dispatch) are encapsulated here so
tests focus on assertions. All helpers use get_success_data() so setup
failures surface as clear "Setup failed" errors.

Identity threading: after creating a Dealer record, every ownership-gated
call (order create/submit/cancel, line add, mod create/resubmit, claim file)
uses make_dealer_headers(dealer["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_assembly_line_payload,
    create_box_line_payload,
    create_component_payload,
    create_dealer_payload,
    create_delivery_route_payload,
    create_door_line_payload,
    create_door_style_payload,
    create_finish_batch_payload,
    create_finish_spec_payload,
    create_modification_payload,
    create_nesting_run_payload,
    create_nesting_station_payload,
    create_replacement_claim_payload,
    create_sub_lot_payload,
)
from .test_users import (
    TEST_USERS,
    make_dealer_headers,
)

ADMIN = TEST_USERS["plant_admin_headers"]
ENGINEER = TEST_USERS["engineer_headers"]
FINISH = TEST_USERS["finish_supervisor_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
SHIPPING = TEST_USERS["shipping_coordinator_headers"]


# ---------------------------------------------------------------------------
# Tier 1: leaf resources
# ---------------------------------------------------------------------------

def create_dealer(price_level="L3", credit_limit_cents=None, **overrides):
    """Register a dealer. Returns the dealer dict."""
    if credit_limit_cents is None:
        credit_limit_cents = TEST_DEFAULTS["DEALER_CREDIT_CENTS"]
    payload = create_dealer_payload(
        price_level=price_level, credit_limit_cents=credit_limit_cents, **overrides
    )
    return get_success_data(api_client.create_dealer(payload, ADMIN))


def create_door_style(**overrides):
    """Create an active door style. Returns the style dict."""
    return get_success_data(api_client.create_door_style(create_door_style_payload(**overrides), ADMIN))


def create_finish(upcharge_pct=0.0, tolerance=1.5, **overrides):
    """Create an active finish spec. Returns the finish dict."""
    payload = create_finish_spec_payload(
        upcharge_pct=upcharge_pct, delta_e_tolerance=tolerance, **overrides
    )
    return get_success_data(api_client.create_finish_spec(payload, ADMIN))


def create_sheet_component(on_hand_qty=100, width=96, height=48, **overrides):
    """Create a SHEET_GOODS component. Returns the component dict."""
    payload = create_component_payload(
        sheet_width_in=width, sheet_height_in=height, on_hand_qty=on_hand_qty, **overrides
    )
    return get_success_data(api_client.create_component(payload, ADMIN))


def create_assembly_line(**overrides):
    """Create an assembly line. Returns the line dict."""
    return get_success_data(api_client.create_assembly_line(create_assembly_line_payload(**overrides), ADMIN))


def create_station(changeover_minutes=0, **overrides):
    """Create a nesting station. Returns the station dict."""
    payload = create_nesting_station_payload(changeover_minutes=changeover_minutes, **overrides)
    return get_success_data(api_client.create_nesting_station(payload, ADMIN))


def create_route(**overrides):
    """Create a PLANNED delivery route. Returns the route dict."""
    return get_success_data(api_client.create_delivery_route(create_delivery_route_payload(**overrides), SHIPPING))


# ---------------------------------------------------------------------------
# Tier 2: orders and lines
# ---------------------------------------------------------------------------

def create_draft_order(dealer):
    """Create a DRAFT order owned by the dealer. Returns the order dict."""
    return get_success_data(api_client.create_order(make_dealer_headers(dealer["id"])))


def add_box_line(order, finish, qty=1, unit_price=None, dealer=None, **overrides):
    """Add a BOX line to a DRAFT order. Returns the line dict."""
    if unit_price is None:
        unit_price = TEST_DEFAULTS["BOX_UNIT_PRICE_CENTS"]
    headers = make_dealer_headers(dealer["id"]) if dealer else make_dealer_headers(order["dealer_id"])
    payload = create_box_line_payload(finish["id"], qty=qty, unit_list_price_cents=unit_price, **overrides)
    return get_success_data(api_client.create_order_line(order["id"], payload, headers))


def add_door_line(order, style, finish, qty=1, unit_price=None, dealer=None, **overrides):
    """Add a DOOR line to a DRAFT order. Returns the line dict."""
    if unit_price is None:
        unit_price = TEST_DEFAULTS["DOOR_UNIT_PRICE_CENTS"]
    headers = make_dealer_headers(dealer["id"]) if dealer else make_dealer_headers(order["dealer_id"])
    payload = create_door_line_payload(
        style["id"], finish["id"], qty=qty, unit_list_price_cents=unit_price, **overrides
    )
    return get_success_data(api_client.create_order_line(order["id"], payload, headers))


def create_submitted_box_order(price_level="L3", qty=1, unit_price=None, upcharge_pct=0.0,
                               credit_limit_cents=None, **line_overrides):
    """Dealer + finish + DRAFT order with one BOX line + submit.

    Returns dict(dealer, finish, order, line). The order is SUBMITTED and the
    line is QUOTED.
    """
    dealer = create_dealer(price_level=price_level, credit_limit_cents=credit_limit_cents)
    finish = create_finish(upcharge_pct=upcharge_pct)
    order = create_draft_order(dealer)
    line = add_box_line(order, finish, qty=qty, unit_price=unit_price, **line_overrides)
    submitted = get_success_data(api_client.submit_order(order["id"], make_dealer_headers(dealer["id"])))
    return {"dealer": dealer, "finish": finish, "order": submitted, "line": line}


def create_submitted_door_order(price_level="L3", qty=1, unit_price=None, upcharge_pct=0.0,
                                tolerance=1.5, credit_limit_cents=None, **line_overrides):
    """Dealer + style + finish + DRAFT order with one DOOR line + submit.

    Returns dict(dealer, style, finish, order, line). The order is SUBMITTED
    and the line is QUOTED.
    """
    dealer = create_dealer(price_level=price_level, credit_limit_cents=credit_limit_cents)
    style = create_door_style()
    finish = create_finish(upcharge_pct=upcharge_pct, tolerance=tolerance)
    order = create_draft_order(dealer)
    line = add_door_line(order, style, finish, qty=qty, unit_price=unit_price, **line_overrides)
    submitted = get_success_data(api_client.submit_order(order["id"], make_dealer_headers(dealer["id"])))
    return {"dealer": dealer, "style": style, "finish": finish, "order": submitted, "line": line}


# ---------------------------------------------------------------------------
# Tier 3: production progression
# ---------------------------------------------------------------------------

def create_mixing_batch(finish, capacity_doors=10, sheen_lot_no="LOT-1", **overrides):
    """Create a MIXING finish batch. Returns the batch dict."""
    payload = create_finish_batch_payload(
        finish["id"], sheen_lot_no=sheen_lot_no, capacity_doors=capacity_doors, **overrides
    )
    return get_success_data(api_client.create_finish_batch(payload, FINISH))


def assign_line_to_batch(batch, line):
    """Assign a QUOTED DOOR line to a MIXING batch. Returns the batch dict."""
    return get_success_data(api_client.assign_batch_line(batch["id"], {"order_line_id": line["id"]}, FINISH))


def qc_release_batch(batch, measured_delta_e=1.0):
    """Record a passing QC measurement. Returns the RELEASED batch dict."""
    return get_success_data(api_client.record_batch_qc(batch["id"], {"measured_delta_e": measured_delta_e}, FINISH))


def create_and_release_run(station, component, door_line_ids, **overrides):
    """Create a DRAFT nesting run and release it. Returns the RELEASED run dict."""
    payload = create_nesting_run_payload(station["id"], component["id"], door_line_ids, **overrides)
    run = get_success_data(api_client.create_nesting_run(payload, PLANNER))
    return get_success_data(api_client.release_nesting_run(run["id"], PLANNER))


def slot_and_complete_box_line(line, qty=None, assembly_line=None, **overrides):
    """Schedule one sub-lot covering the full BOX line and complete it.

    Returns dict(assembly_line, sub_lot). After this helper the covered line
    is COMPLETED.
    """
    if assembly_line is None:
        assembly_line = create_assembly_line()
    if qty is None:
        qty = line["qty"]
    payload = create_sub_lot_payload(line["id"], assembly_line["id"], qty=qty, **overrides)
    sub_lot = get_success_data(api_client.create_sub_lot(payload, PLANNER))
    completed = get_success_data(api_client.complete_sub_lot(sub_lot["id"], PLANNER))
    return {"assembly_line": assembly_line, "sub_lot": completed}


def setup_door_order_in_production(price_level="L3", qty=4, unit_price=None, upcharge_pct=0.0,
                                   tolerance=1.5, capacity_doors=10, **line_overrides):
    """Submitted door order with its line batch-assigned (order IN_PRODUCTION).

    Returns dict(dealer, style, finish, order, line, batch).
    """
    env = create_submitted_door_order(
        price_level=price_level, qty=qty, unit_price=unit_price,
        upcharge_pct=upcharge_pct, tolerance=tolerance, **line_overrides
    )
    batch = create_mixing_batch(env["finish"], capacity_doors=capacity_doors)
    assign_line_to_batch(batch, env["line"])
    env["batch"] = get_success_data(api_client.get_finish_batch(batch["id"], FINISH))
    env["order"] = get_success_data(api_client.get_order(env["order"]["id"], ADMIN))
    return env


def setup_box_order_ready_to_ship(price_level="L3", qty=10, unit_price=None, upcharge_pct=0.0,
                                  assembly_line=None, **line_overrides):
    """Submitted BOX order fully sub-lotted and completed (READY_TO_SHIP).

    Returns dict(dealer, finish, order, line, assembly_line, sub_lot).
    """
    env = create_submitted_box_order(
        price_level=price_level, qty=qty, unit_price=unit_price,
        upcharge_pct=upcharge_pct, **line_overrides
    )
    if assembly_line is None:
        assembly_line = create_assembly_line()
    result = slot_and_complete_box_line(env["line"], assembly_line=assembly_line)
    env.update(result)
    env["order"] = get_success_data(api_client.get_order(env["order"]["id"], ADMIN))
    return env


def setup_door_order_ready_to_ship(price_level="L3", qty=4, unit_price=None, upcharge_pct=0.0,
                                   tolerance=1.5, capacity_doors=10, **line_overrides):
    """Submitted door order whose batch QC-released (order READY_TO_SHIP).

    Returns dict(dealer, style, finish, order, line, batch).
    """
    env = setup_door_order_in_production(
        price_level=price_level, qty=qty, unit_price=unit_price,
        upcharge_pct=upcharge_pct, tolerance=tolerance, capacity_doors=capacity_doors,
        **line_overrides
    )
    env["batch"] = qc_release_batch(env["batch"])
    env["order"] = get_success_data(api_client.get_order(env["order"]["id"], ADMIN))
    return env


# ---------------------------------------------------------------------------
# Tier 4: shipping / dispatch
# ---------------------------------------------------------------------------

def assign_order_to_route(route, order):
    """Assign an order to a PLANNED route with a freshly-read OCC version.

    Returns dict(order, route) after the assignment.
    """
    fresh = get_success_data(api_client.get_order(order["id"], SHIPPING))
    route_after = get_success_data(
        api_client.assign_order_to_route(
            route["id"],
            {"order_id": order["id"], "expected_order_version": fresh["version"]},
            SHIPPING,
        )
    )
    order_after = get_success_data(api_client.get_order(order["id"], SHIPPING))
    return {"order": order_after, "route": route_after}


def setup_shipped_door_order(price_level="L4", qty=4, unit_price=None, upcharge_pct=0.0,
                             tolerance=1.5, route_capacity=100.0, **line_overrides):
    """Full lifecycle to SHIPPED for a single-door-line order.

    Dealer + style + finish + order + line + submit + batch assign + QC pass
    + route assign + lock + dispatch. Returns dict(dealer, style, finish,
    order, line, batch, route); order is the SHIPPED representation.
    """
    if unit_price is None:
        unit_price = TEST_DEFAULTS["DOOR_UNIT_PRICE_CENTS"]
    env = setup_door_order_ready_to_ship(
        price_level=price_level, qty=qty, unit_price=unit_price,
        upcharge_pct=upcharge_pct, tolerance=tolerance, **line_overrides
    )
    route = create_route(capacity_cu_ft=route_capacity)
    assign_order_to_route(route, env["order"])
    get_success_data(api_client.lock_route(route["id"], SHIPPING))
    get_success_data(api_client.dispatch_route(route["id"], SHIPPING))
    env["route"] = route
    env["order"] = get_success_data(api_client.get_order(env["order"]["id"], SHIPPING))
    env["line"] = get_success_data(api_client.get_order_line(env["line"]["id"], SHIPPING))
    return env


def setup_shipped_box_order(price_level="L3", qty=2, unit_price=None, upcharge_pct=0.0,
                            route_capacity=100.0, **line_overrides):
    """Full lifecycle to SHIPPED for a single-box-line order.

    Returns dict(dealer, finish, order, line, assembly_line, sub_lot, route).
    """
    if unit_price is None:
        unit_price = TEST_DEFAULTS["BOX_UNIT_PRICE_CENTS"]
    env = setup_box_order_ready_to_ship(
        price_level=price_level, qty=qty, unit_price=unit_price,
        upcharge_pct=upcharge_pct, **line_overrides
    )
    route = create_route(capacity_cu_ft=route_capacity)
    assign_order_to_route(route, env["order"])
    get_success_data(api_client.lock_route(route["id"], SHIPPING))
    get_success_data(api_client.dispatch_route(route["id"], SHIPPING))
    env["route"] = route
    env["order"] = get_success_data(api_client.get_order(env["order"]["id"], SHIPPING))
    env["line"] = get_success_data(api_client.get_order_line(env["line"]["id"], SHIPPING))
    return env


def setup_shortage_hold_environment(on_hand_qty=0, line_qty=50, line_width=30, line_height=20,
                                    station_changeover=0):
    """Submitted door order + run release that overdrafts the sheet component.

    Returns dict(dealer, style, finish, component, order, line, station, run,
    hold). After this helper the component's available_qty is negative, a
    COMPONENT_SHORTAGE hold is PLACED, and the order is ON_HOLD.
    """
    dealer = create_dealer(price_level="L3")
    style = create_door_style(construction="SLAB", base_list_price_cents=15000)
    finish = create_finish(upcharge_pct=0.0)
    component = create_sheet_component(on_hand_qty=on_hand_qty)
    order = create_draft_order(dealer)
    line = add_door_line(
        order, style, finish, qty=line_qty, unit_price=15000,
        width_in=line_width, height_in=line_height,
    )
    submitted = get_success_data(api_client.submit_order(order["id"], make_dealer_headers(dealer["id"])))
    station = create_station(changeover_minutes=station_changeover)
    run = create_and_release_run(station, component, [line["id"]])
    holds, _meta = _list_order_holds(submitted["id"])
    hold = holds[0] if holds else None
    return {
        "dealer": dealer, "style": style, "finish": finish, "component": component,
        "order": get_success_data(api_client.get_order(submitted["id"], PLANNER)),
        "line": line, "station": station, "run": run, "hold": hold,
    }


def _list_order_holds(order_id):
    resp = api_client.list_order_holds(order_id, PLANNER)
    body = resp.json()
    assert resp.status_code == 200, f"Setup step failed listing holds: HTTP {resp.status_code}"
    return body["data"], body["meta"]


# ---------------------------------------------------------------------------
# Tier 5: claims
# ---------------------------------------------------------------------------

def create_claim(env, claim_type="FREIGHT_DAMAGE", qty=1, line=None):
    """File a replacement claim against a shipped order's line.

    `env` is the dict returned by setup_shipped_door_order. Returns the claim.
    """
    if line is None:
        line = env["line"]
    payload = create_replacement_claim_payload(line["id"], claim_type=claim_type, qty=qty)
    return get_success_data(
        api_client.create_replacement_claim(payload, make_dealer_headers(env["dealer"]["id"]))
    )


def create_mod_under_review(order, line, dealer, mod_code="TOE_KICK_NOTCH", new_dimension_in=4):
    """File a modification on a line of a DRAFT order. Returns the mod dict."""
    payload = create_modification_payload(mod_code=mod_code, new_dimension_in=new_dimension_in)
    return get_success_data(
        api_client.create_modification(line["id"], payload, make_dealer_headers(dealer["id"]))
    )
