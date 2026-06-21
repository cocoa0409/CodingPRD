"""Composite setup helpers.

Each helper builds the multi-step precondition state a family of tests shares,
using only PRD-declared endpoints, and returns the created entities. All setup
calls use the lenient get_success_data() validator so a broken precondition
surfaces as a clear "Setup step failed" error rather than a confusing assertion.

Identity threading: the Patron role is entity-backed, so every order-ownership
gated call uses make_patron_headers(patron["id"]).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_patron_headers
from . import factories as f

MANAGER = TEST_USERS["manager_headers"]
RUNNER = TEST_USERS["runner_headers"]
OPERATOR = TEST_USERS["operator_headers"]


# ===========================================================================
# Tier 1 — Catalog / venue building blocks
# ===========================================================================
def create_venue(**overrides) -> dict:
    """Create a venue with controllable contract terms. Returns the Venue."""
    resp = api_client.create_venue(f.create_venue_payload(**overrides), MANAGER)
    return get_success_data(resp)


def create_product(venue_id, **overrides) -> dict:
    """Create a catalog product under a venue. Returns the Product."""
    resp = api_client.create_product(f.create_product_payload(venue_id, **overrides), MANAGER)
    return get_success_data(resp)


def create_patron(**overrides) -> dict:
    """Register a patron. Returns the Patron."""
    resp = api_client.create_patron(f.create_patron_payload(**overrides), TEST_USERS["patron_headers"])
    return get_success_data(resp)


def create_event(venue_id, **overrides) -> dict:
    """Create a SCHEDULED event under a venue. Returns the Event."""
    resp = api_client.create_event(f.create_event_payload(venue_id, **overrides), MANAGER)
    return get_success_data(resp)


def create_stand(event_id, **overrides) -> dict:
    """Create a CLOSED stand under an event. Returns the Stand."""
    resp = api_client.create_stand(f.create_stand_payload(event_id, **overrides), MANAGER)
    return get_success_data(resp)


def create_lot(stand_id, product_id, **overrides) -> dict:
    """Create an inventory lot on a stand. Returns the InventoryLot."""
    resp = api_client.create_inventory_lot(
        f.create_inventory_lot_payload(stand_id, product_id, **overrides), RUNNER
    )
    return get_success_data(resp)


def create_checked_in_shift(stand_id, **overrides) -> dict:
    """Schedule a staff shift at the stand and check it in (assigned_staff_count += 1).
    Returns the CHECKED_IN StaffShift."""
    shift = get_success_data(
        api_client.create_staff_shift(f.create_staff_shift_payload(stand_id, **overrides), MANAGER)
    )
    return get_success_data(api_client.check_in_shift(shift["id"], OPERATOR))


# ===========================================================================
# Tier 2 — Event lifecycle progression
# ===========================================================================
def create_event_doors_open(venue_id, **event_overrides) -> dict:
    """Create an event with one stand and advance it to DOORS_OPEN.

    Returns {"event": Event, "stand": Stand}. open-doors requires >=1 stand.
    """
    event = create_event(venue_id, **event_overrides)
    stand = create_stand(event["id"])
    get_success_data(api_client.open_doors(event["id"], MANAGER))
    event = get_success_data(api_client.get_event(event["id"], MANAGER))
    return {"event": event, "stand": stand}


def create_stand_opened_with_staff(
    venue_id=None, event_overrides=None, stand_overrides=None
) -> dict:
    """The dominant preamble: venue (if not supplied) + event doors-open + a fresh
    stand + one checked-in shift + open the stand. Returns
    {"venue", "event", "stand", "shift"} with the stand in OPEN status.
    """
    event_overrides = event_overrides or {}
    stand_overrides = stand_overrides or {}
    if venue_id is None:
        venue = create_venue()
        venue_id = venue["id"]
    else:
        venue = None
    event = create_event(venue_id, **event_overrides)
    # open-doors needs at least one stand; create the test stand first.
    stand = create_stand(event["id"], **stand_overrides)
    get_success_data(api_client.open_doors(event["id"], MANAGER))
    shift = create_checked_in_shift(stand["id"])
    stand = get_success_data(api_client.open_stand(stand["id"], OPERATOR))
    return {"venue": venue, "event": event, "stand": stand, "shift": shift}


# ===========================================================================
# Tier 3 — Sellable stand: stand OPEN + menu item + stock
# ===========================================================================
def setup_sellable_stand(
    venue_overrides=None, product_overrides=None, event_overrides=None,
    stand_overrides=None, lot_overrides=None,
) -> dict:
    """Active venue + product + event doors-open + open stand + a menu item +
    one stocked lot of the product. Returns
    {"venue", "product", "event", "stand", "shift", "menu_item", "lot"}.
    """
    venue_overrides = venue_overrides or {}
    product_overrides = product_overrides or {}
    lot_overrides = lot_overrides or {}
    venue = create_venue(**venue_overrides)
    product = create_product(venue["id"], **product_overrides)
    base = create_stand_opened_with_staff(
        venue_id=venue["id"],
        event_overrides=event_overrides or {},
        stand_overrides=stand_overrides or {},
    )
    event, stand, shift = base["event"], base["stand"], base["shift"]
    menu_item = get_success_data(
        api_client.create_menu_item(f.create_menu_item_payload(stand["id"], product["id"]), MANAGER)
    )
    lot = create_lot(stand["id"], product["id"], **lot_overrides)
    return {
        "venue": venue, "product": product, "event": event, "stand": stand,
        "shift": shift, "menu_item": menu_item, "lot": lot,
    }


# ===========================================================================
# Tier 4 — Order lifecycle shortcuts
# ===========================================================================
def setup_cart_order(scenario=None, line_qtys=(1,), product_overrides=None,
                     venue_overrides=None, lot_overrides=None,
                     stand_overrides=None, event_overrides=None) -> dict:
    """Sellable stand + a registered patron + a CART order carrying the given
    per-line quantities. Returns the sellable-stand dict plus
    {"patron", "patron_headers", "order"}.
    """
    scenario = scenario or setup_sellable_stand(
        venue_overrides=venue_overrides, product_overrides=product_overrides,
        lot_overrides=lot_overrides, stand_overrides=stand_overrides,
        event_overrides=event_overrides,
    )
    patron = create_patron()
    ph = make_patron_headers(patron["id"])
    order = get_success_data(
        api_client.create_order(
            f.create_order_payload(scenario["event"]["id"], scenario["stand"]["id"], patron["id"]), ph
        )
    )
    for qty in line_qtys:
        get_success_data(
            api_client.add_order_line(order["id"], f.create_order_line_payload(scenario["menu_item"]["id"], qty), ph)
        )
    order = get_success_data(api_client.get_order(order["id"], ph))
    result = dict(scenario)
    result.update({"patron": patron, "patron_headers": ph, "order": order})
    return result


def setup_placed_order(line_qtys=(1,), **kwargs) -> dict:
    """Cart order then PLACED. Returns the cart-order dict with order updated to PLACED."""
    state = setup_cart_order(line_qtys=line_qtys, **kwargs)
    ph = state["patron_headers"]
    state["order"] = get_success_data(api_client.place_order(state["order"]["id"], ph))
    return state


def setup_paid_order(line_qtys=(1,), **kwargs) -> dict:
    """Placed then PAID order. Returns the dict with order PLACED/PAID."""
    state = setup_placed_order(line_qtys=line_qtys, **kwargs)
    ph = state["patron_headers"]
    state["order"] = get_success_data(api_client.pay_order(state["order"]["id"], ph))
    return state


def current_stand_version(stand_id) -> int:
    """Read the live Stand.version (operator's last-observed value for OCC calls)."""
    return get_success_data(api_client.get_stand(stand_id, OPERATOR))["version"]


def setup_ready_eligible_order(line_qtys=(1,), **kwargs) -> dict:
    """A PLACED+PAID order plus the live stand version captured, ready to be
    marked READY by an operator. Returns the dict with an added "stand_version".
    """
    state = setup_paid_order(line_qtys=line_qtys, **kwargs)
    state["stand_version"] = current_stand_version(state["stand"]["id"])
    return state


def setup_readied_order(line_qtys=(1,), **kwargs) -> dict:
    """A PLACED+PAID+READY order (stock decremented). Returns the dict with order READY."""
    state = setup_ready_eligible_order(line_qtys=line_qtys, **kwargs)
    ph = state["patron_headers"]
    state["order"] = get_success_data(
        api_client.ready_order(state["order"]["id"], {"expected_stand_version": state["stand_version"]}, OPERATOR)
    )
    return state


def setup_picked_up_order(line_qtys=(1,), **kwargs) -> dict:
    """A fully fulfilled (PICKED_UP) order; event gross_sales_cents advanced.
    Returns the dict with order PICKED_UP."""
    state = setup_readied_order(line_qtys=line_qtys, **kwargs)
    state["order"] = get_success_data(api_client.pickup_order(state["order"]["id"], OPERATOR))
    return state


# ===========================================================================
# Tier 5 — Transfers between two stands of one event
# ===========================================================================
def setup_two_stands_one_event(
    source_lot_qty=100, lot_unit_cost=30, venue_overrides=None,
    product_overrides=None, event_overrides=None, source_lots=None,
) -> dict:
    """One venue/event with two stands (A, B). Stand A is stocked.

    If source_lots is given, it is a list of (qty, unit_cost) tuples creating
    multiple lots on A (oldest first). Otherwise a single lot of source_lot_qty
    at lot_unit_cost is created. Returns
    {"venue", "product", "event", "stand_a", "stand_b", "lots"}.
    """
    venue = create_venue(**(venue_overrides or {}))
    product = create_product(venue["id"], **(product_overrides or {}))
    event = create_event(venue["id"], **(event_overrides or {}))
    stand_a = create_stand(event["id"], name="StandA")
    stand_b = create_stand(event["id"], name="StandB")
    lots = []
    if source_lots is None:
        source_lots = [(source_lot_qty, lot_unit_cost)]
    for qty, cost in source_lots:
        lots.append(create_lot(
            stand_a["id"], product["id"], received_qty=qty, unit_cost_cents=cost,
            par_level=max(qty, 200), reorder_point=20,
        ))
    return {
        "venue": venue, "product": product, "event": event,
        "stand_a": stand_a, "stand_b": stand_b, "lots": lots,
    }


def setup_draft_transfer(qty=10, **kwargs) -> dict:
    """Two stands of one event (A stocked) + a DRAFT transfer of qty A->B, with
    stand A's live version captured. Returns the two-stand dict plus
    {"transfer", "stand_a_version"}.
    """
    base = setup_two_stands_one_event(**kwargs)
    transfer = get_success_data(
        api_client.create_transfer(
            f.create_transfer_payload(base["stand_a"]["id"], base["stand_b"]["id"], base["product"]["id"], qty=qty),
            RUNNER,
        )
    )
    sa_v = get_success_data(api_client.get_stand(base["stand_a"]["id"], RUNNER))["version"]
    result = dict(base)
    result.update({"transfer": transfer, "stand_a_version": sa_v})
    return result


def setup_dispatched_transfer(qty=30, **kwargs) -> dict:
    """A DRAFT transfer of qty A->B then DISPATCHED (source debited; IN_TRANSIT).
    Returns the draft-transfer dict with transfer updated to IN_TRANSIT."""
    state = setup_draft_transfer(qty=qty, **kwargs)
    state["transfer"] = get_success_data(
        api_client.dispatch_transfer(
            state["transfer"]["id"], {"expected_from_stand_version": state["stand_a_version"]}, RUNNER
        )
    )
    return state


# ===========================================================================
# Tier 6 — Settlement readiness
# ===========================================================================
def setup_in_progress_event(venue_id=None, stand_overrides=None) -> dict:
    """A stand opened with staff, event advanced to IN_PROGRESS (peak window opened).
    Returns the create_stand_opened_with_staff dict (event now IN_PROGRESS)."""
    state = create_stand_opened_with_staff(venue_id=venue_id, stand_overrides=stand_overrides or {})
    # peak-window/open advances DOORS_OPEN -> IN_PROGRESS.
    state["event"] = get_success_data(api_client.open_peak_window(state["event"]["id"], MANAGER))
    return state


def setup_settled_empty_event() -> dict:
    """Drive an event to terminal SETTLED with no orders and an open-then-closed
    stand path (gross 0, waste 0). Returns {"venue", "event", "stand"} (event SETTLED)."""
    venue = create_venue()
    event = create_event(venue["id"])
    stand = create_stand(event["id"])
    get_success_data(api_client.open_doors(event["id"], MANAGER))
    get_success_data(api_client.open_peak_window(event["id"], MANAGER))  # -> IN_PROGRESS
    get_success_data(api_client.settle_event(event["id"], MANAGER))
    event = get_success_data(api_client.get_event(event["id"], MANAGER))
    return {"venue": venue, "event": event, "stand": stand}


def setup_settled_event_with_sales_and_waste(
    share_basis="GROSS", spoilage_valuation="FIFO", venue_share_pct=20, service_fee_pct=7,
    hotdog_qty=4, spillage_buns=10,
) -> dict:
    """Drive a complete event to SETTLED with one picked-up hotdog order
    (gross_sales) and one SPILLAGE bun waste (waste_cost), then settle.

    With the defaults (hotdog base 1000, MID off-peak surge 115, mult 100,
    service_fee_pct 7), an order of 4 hotdogs picked up gives gross_sales 4922,
    and a SPILLAGE of 10 buns @ 30c gives waste_cost 300.

    Returns {"venue", "event", "stand", "statement", "gross_sales_cents",
    "waste_cost_cents"} where statement is the RevenueShareStatement.
    """
    venue = create_venue(venue_share_pct=venue_share_pct, share_basis=share_basis,
                         spoilage_valuation=spoilage_valuation, service_fee_pct=service_fee_pct)
    hotdog = create_product(venue["id"], sku="HOTDOG", name="Hot Dog",
                            base_price_cents=1000, unit_cost_cents=200, perishable=False)
    bun = create_product(venue["id"], sku="BUN", name="Bun",
                         base_price_cents=0, unit_cost_cents=30, perishable=True)
    base = create_stand_opened_with_staff(
        venue_id=venue["id"], stand_overrides={"demand_tier": "MID", "expected_orders_per_hour": 80}
    )
    event, stand = base["event"], base["stand"]
    menu_item = get_success_data(
        api_client.create_menu_item(f.create_menu_item_payload(stand["id"], hotdog["id"]), MANAGER)
    )
    create_lot(stand["id"], hotdog["id"], received_qty=50, unit_cost_cents=200, par_level=50, reorder_point=10)
    create_lot(stand["id"], bun["id"], received_qty=100, unit_cost_cents=30, par_level=100, reorder_point=20)
    # One hotdog order picked up -> gross_sales.
    patron = create_patron()
    ph = make_patron_headers(patron["id"])
    order = get_success_data(api_client.create_order(
        f.create_order_payload(event["id"], stand["id"], patron["id"]), ph))
    get_success_data(api_client.add_order_line(order["id"], f.create_order_line_payload(menu_item["id"], hotdog_qty), ph))
    get_success_data(api_client.place_order(order["id"], ph))
    get_success_data(api_client.pay_order(order["id"], ph))
    sv = current_stand_version(stand["id"])
    get_success_data(api_client.ready_order(order["id"], {"expected_stand_version": sv}, OPERATOR))
    order = get_success_data(api_client.pickup_order(order["id"], OPERATOR))
    # SPILLAGE bun waste -> waste_cost.
    get_success_data(api_client.create_waste_record(
        f.create_waste_record_payload(stand["id"], bun["id"], "SPILLAGE", spillage_buns), RUNNER))
    # Settlement requires the event be IN_PROGRESS (PRD §3.5). Advance via the
    # peak window after the sale is already picked up — gross_sales_cents was
    # snapshotted at pickup from the line's pre-peak unit_price snapshot, so this
    # leaves gross 4922 and waste untouched while satisfying the settle gate.
    get_success_data(api_client.open_peak_window(event["id"], MANAGER))
    get_success_data(api_client.close_stand(stand["id"], OPERATOR))
    statement = get_success_data(api_client.settle_event(event["id"], MANAGER))
    event = get_success_data(api_client.get_event(event["id"], MANAGER))
    return {
        "venue": venue, "event": event, "stand": stand, "order": order,
        "statement": statement,
        "gross_sales_cents": event["gross_sales_cents"],
        "waste_cost_cents": event["waste_cost_cents"],
    }


def setup_stand_with_two_bun_lots(spoilage_valuation="WEIGHTED_AVG") -> dict:
    """A stand (opened with staff) holding two bun lots: 100@30c (older) then
    100@50c (newer), for spoilage-costing tests. Returns
    {"venue", "product", "event", "stand", "lots"}.
    """
    venue = create_venue(venue_share_pct=20, share_basis="GROSS",
                         spoilage_valuation=spoilage_valuation, service_fee_pct=7)
    bun = create_product(venue["id"], sku="BUN", name="Bun",
                         base_price_cents=0, unit_cost_cents=30, perishable=True)
    base = create_stand_opened_with_staff(venue_id=venue["id"],
                                          stand_overrides={"demand_tier": "MID", "expected_orders_per_hour": 40})
    stand = base["stand"]
    lot_a = create_lot(stand["id"], bun["id"], received_qty=100, unit_cost_cents=30, par_level=200, reorder_point=20)
    lot_b = create_lot(stand["id"], bun["id"], received_qty=100, unit_cost_cents=50, par_level=200, reorder_point=20)
    return {"venue": venue, "product": bun, "event": base["event"], "stand": stand, "lots": [lot_a, lot_b]}


def stand_onhand(stand_id, product_id) -> int:
    """Sum remaining_qty over the stand's ACTIVE lots of the product."""
    lots, _meta = _list_active_lots(stand_id, product_id)
    return sum(l["remaining_qty"] for l in lots)


def _list_active_lots(stand_id, product_id):
    resp = api_client.list_stand_inventory_lots(stand_id, RUNNER, params={"product_id": product_id, "limit": 100})
    body = resp.json()
    lots = [l for l in body["data"] if l.get("product_id") == product_id and l.get("status") == "ACTIVE"]
    return lots, body["meta"]
