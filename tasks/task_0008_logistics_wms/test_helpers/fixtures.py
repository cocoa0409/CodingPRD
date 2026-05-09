"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures produce clear
"Setup failed" errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_warehouse_payload,
    create_bin_payload,
    create_lot_payload,
    create_inbound_shipment_payload,
    create_inbound_shipment_multiline_payload,
    create_complete_inspection_payload,
    create_order_payload,
    create_wave_payload,
    create_cycle_count_payload,
    create_recall_payload,
    create_clock_advance_payload,
    create_pick_complete_payload,
    create_submit_count_payload,
)
from .test_users import TEST_USERS, make_staff_headers, make_auditor_headers
from .constants import TEST_DEFAULTS


# ─── Counter helpers (avoid uniqueness collisions across many fixtures) ────

_warehouse_counter = {"n": 0}
_bin_counter = {"n": 0}
_lot_counter = {"n": 0}
_asn_counter = {"n": 0}
_order_counter = {"n": 0}
_wave_counter = {"n": 0}


def _next_warehouse_name():
    _warehouse_counter["n"] += 1
    return f"W{_warehouse_counter['n']}_{TEST_DEFAULTS['WAREHOUSE_NAME']}"


def _next_bin_code():
    _bin_counter["n"] += 1
    return f"BIN_{_bin_counter['n']:05d}"


def _next_lot_code():
    _lot_counter["n"] += 1
    return f"LOT_{_lot_counter['n']:05d}"


def _next_asn_number():
    _asn_counter["n"] += 1
    return f"ASN_{_asn_counter['n']:05d}"


def _next_order_number():
    _order_counter["n"] += 1
    return f"ORD_{_order_counter['n']:05d}"


def _next_wave_code():
    _wave_counter["n"] += 1
    return f"WAVE_{_wave_counter['n']:05d}"


# ─── Tier 1: Atomic creation helpers ──────────────────────────────────────

def create_warehouse(name=None, dock_position_x=0, dock_position_y=0,
                    putaway_strategy=None, advance_clock_to=None):
    """Create a warehouse and (optionally) advance its clock to a known time.

    The default warehouse uses dock=(0,0) and DISTANCE_OPTIMIZED strategy.
    `advance_clock_to` accepts an ISO 8601 string (defaults to TEST_DEFAULTS["DEFAULT_CLOCK_TIME"]
    when None — pass explicit False to skip advancing).
    """
    overrides = {}
    if name is None:
        name = _next_warehouse_name()
    overrides["name"] = name
    overrides["dock_position_x"] = dock_position_x
    overrides["dock_position_y"] = dock_position_y
    if putaway_strategy is not None:
        overrides["putaway_strategy"] = putaway_strategy

    payload = create_warehouse_payload(**overrides)
    res = api_client.create_warehouse(payload, TEST_USERS["manager_headers"])
    warehouse = get_success_data(res)

    if advance_clock_to is not False:
        target_time = advance_clock_to or TEST_DEFAULTS["DEFAULT_CLOCK_TIME"]
        adv_res = api_client.advance_clock(
            create_clock_advance_payload(warehouse["id"], target_time),
            TEST_USERS["manager_headers"],
        )
        warehouse = get_success_data(adv_res)
    return warehouse


def create_bin(warehouse_id, bin_code=None, zone="AMBIENT",
              position_x=1, position_y=0,
              capacity_volume_cm3=None, capacity_weight_g=None):
    if bin_code is None:
        bin_code = _next_bin_code()
    overrides = {
        "bin_code": bin_code,
        "zone": zone,
        "position_x": position_x,
        "position_y": position_y,
    }
    if capacity_volume_cm3 is not None:
        overrides["capacity_volume_cm3"] = capacity_volume_cm3
    if capacity_weight_g is not None:
        overrides["capacity_weight_g"] = capacity_weight_g
    payload = create_bin_payload(**overrides)
    res = api_client.create_bin(warehouse_id, payload, TEST_USERS["manager_headers"])
    return get_success_data(res)


def create_lot(warehouse_id, lot_code=None, sku=None, category="AMBIENT",
              unit_weight_g=None, unit_volume_cm3=None, unit_value_cents=None,
              manufacture_date=None, expiry_date=None, supplier_lot_ref=None):
    if lot_code is None:
        lot_code = _next_lot_code()
    overrides = {
        "lot_code": lot_code,
        "category": category,
    }
    if sku is not None:
        overrides["sku"] = sku
    if unit_weight_g is not None:
        overrides["unit_weight_g"] = unit_weight_g
    if unit_volume_cm3 is not None:
        overrides["unit_volume_cm3"] = unit_volume_cm3
    if unit_value_cents is not None:
        overrides["unit_value_cents"] = unit_value_cents
    if manufacture_date is not None:
        overrides["manufacture_date"] = manufacture_date
    if expiry_date is not None:
        overrides["expiry_date"] = expiry_date
    if supplier_lot_ref is not None:
        overrides["supplier_lot_ref"] = supplier_lot_ref
    payload = create_lot_payload(**overrides)
    res = api_client.create_lot(warehouse_id, payload, TEST_USERS["manager_headers"])
    return get_success_data(res)


# ─── Tier 2: Inbound shipment cycle (create → inspect → putaway) ─────────

def putaway_lot_units(warehouse_id, lot_id, units, asn_number=None, defects=0):
    """Run the full inbound cycle to putaway `units` of `lot_id`:
      create shipment → start_inspection → complete_inspection (defects=0 by default)
      → putaway.
    Returns the final shipment dict.
    """
    if asn_number is None:
        asn_number = _next_asn_number()
    sh_payload = create_inbound_shipment_payload(
        lot_id=lot_id, declared_units=units, asn_number=asn_number,
    )
    sh = get_success_data(api_client.create_inbound_shipment(
        warehouse_id, sh_payload, TEST_USERS["staff_headers"]
    ))
    get_success_data(api_client.start_inspection(
        warehouse_id, sh["id"], TEST_USERS["staff_headers"]
    ))
    ci_payload = create_complete_inspection_payload(
        lot_id=lot_id, received_units=units, inspection_defect_count=defects,
    )
    get_success_data(api_client.complete_inspection(
        warehouse_id, sh["id"], ci_payload, TEST_USERS["staff_headers"]
    ))
    final = get_success_data(api_client.putaway_inbound_shipment(
        warehouse_id, sh["id"], TEST_USERS["staff_headers"]
    ))
    return final


def setup_warehouse_with_inventory(units=50, sku=None, unit_volume_cm3=None,
                                  unit_weight_g=None, unit_value_cents=None,
                                  expiry_date=None, putaway_strategy=None,
                                  bin_capacity_volume_cm3=None,
                                  bin_capacity_weight_g=None,
                                  warehouse_kwargs=None):
    """Create a warehouse with one bin, one lot, and `units` of that lot putaway
    into the bin. Returns (warehouse, bin, lot)."""
    wh_kwargs = warehouse_kwargs or {}
    wh = create_warehouse(putaway_strategy=putaway_strategy, **wh_kwargs)
    bin_obj = create_bin(
        wh["id"], zone="AMBIENT",
        capacity_volume_cm3=bin_capacity_volume_cm3,
        capacity_weight_g=bin_capacity_weight_g,
    )
    lot = create_lot(
        wh["id"], sku=sku, category="AMBIENT",
        unit_volume_cm3=unit_volume_cm3,
        unit_weight_g=unit_weight_g,
        unit_value_cents=unit_value_cents,
        expiry_date=expiry_date,
    )
    putaway_lot_units(wh["id"], lot["id"], units)
    # Refresh with computed used_volume etc.
    bin_obj = get_success_data(api_client.get_bin(wh["id"], bin_obj["id"], TEST_USERS["staff_headers"]))
    lot = get_success_data(api_client.get_lot(wh["id"], lot["id"], TEST_USERS["staff_headers"]))
    return wh, bin_obj, lot


# ─── Tier 3: Order pipeline shortcuts ────────────────────────────────────

def create_allocated_order(warehouse_id, sku, qty_units, pick_strategy=None,
                          carrier="UPS", order_number=None):
    """Create an order and allocate it. Returns the allocated order."""
    if order_number is None:
        order_number = _next_order_number()
    payload = create_order_payload(
        requested_lines=[{"sku": sku, "qty_units": qty_units}],
        order_number=order_number,
        carrier=carrier,
        pick_strategy=pick_strategy,
    )
    order = get_success_data(api_client.create_order(
        warehouse_id, payload, TEST_USERS["staff_headers"]
    ))
    allocated = get_success_data(api_client.allocate_order(
        warehouse_id, order["id"], TEST_USERS["staff_headers"]
    ))
    return allocated


def get_pick_tasks_for_order(warehouse_id, order_id):
    """Return the list of pick tasks belonging to an order, by reading the
    order resource (which includes pick_tasks per PRD §4 — 'Get an order
    (includes pick_tasks summary)')."""
    order = get_success_data(api_client.get_order(
        warehouse_id, order_id, TEST_USERS["staff_headers"]
    ))
    pick_tasks = order.get("pick_tasks") or []
    # pick_tasks may be embedded fully or as id summaries; resolve to full objects
    resolved = []
    for pt in pick_tasks:
        if isinstance(pt, dict) and "status" in pt and "planned_units" in pt:
            resolved.append(pt)
        elif isinstance(pt, dict) and "id" in pt:
            full = get_success_data(api_client.get_pick_task(
                warehouse_id, pt["id"], TEST_USERS["staff_headers"]
            ))
            resolved.append(full)
        elif isinstance(pt, str):
            full = get_success_data(api_client.get_pick_task(
                warehouse_id, pt, TEST_USERS["staff_headers"]
            ))
            resolved.append(full)
    return resolved


def setup_released_wave_for_order(warehouse_id, order_id, wave_code=None,
                                 strategy="BATCH"):
    """Wrap an ALLOCATED order in a wave and release the wave. Returns the wave."""
    if wave_code is None:
        wave_code = _next_wave_code()
    wave_payload = create_wave_payload(
        order_ids=[order_id], wave_code=wave_code, strategy=strategy,
    )
    wave = get_success_data(api_client.create_wave(
        warehouse_id, wave_payload, TEST_USERS["staff_headers"]
    ))
    released = get_success_data(api_client.release_wave(
        warehouse_id, wave["id"], TEST_USERS["staff_headers"]
    ))
    return released


def setup_picking_pick_task(sku="PEN", inventory_units=50,
                           order_qty=10, pick_strategy="FEFO"):
    """Drive an order through allocate → wave released → pick task started.
    Returns (warehouse, bin, lot, order, wave, pick_task) where pick_task is
    in PICKING status."""
    wh, bin_obj, lot = setup_warehouse_with_inventory(
        units=inventory_units, sku=sku,
    )
    order = create_allocated_order(
        wh["id"], sku=lot["sku"], qty_units=order_qty, pick_strategy=pick_strategy,
    )
    wave = setup_released_wave_for_order(wh["id"], order["id"])
    pick_tasks = get_pick_tasks_for_order(wh["id"], order["id"])
    assert len(pick_tasks) >= 1, "Setup failed: expected at least one pick task after allocation"
    pt = pick_tasks[0]
    pt = get_success_data(api_client.start_pick_task(
        wh["id"], pt["id"], TEST_USERS["staff_headers"]
    ))
    return wh, bin_obj, lot, order, wave, pt


# ─── Tier 4: Risk-score / posture targeting ──────────────────────────────

def setup_warehouse_with_recalls(num_recalls=3, putaway_strategy=None):
    """Create a warehouse with `num_recalls` lots that have been recalled.
    Each recall increments recall_count_open by 1. With num_recalls=3 and
    no other counters, risk_score = 3 * 100 = 300, so posture = FROZEN.
    Returns the warehouse (refreshed). The recalled lots remain in the
    warehouse (they exist in RECALLED status).
    """
    wh = create_warehouse(putaway_strategy=putaway_strategy)
    for i in range(num_recalls):
        lot = create_lot(
            wh["id"], sku=f"RECALL_SKU_{i}",
            lot_code=f"LOT_RECALL_{i}_{_lot_counter['n']}",
        )
        get_success_data(api_client.recall_lot(
            wh["id"], lot["id"], create_recall_payload("SUPPLIER_RECALL"),
            TEST_USERS["manager_headers"],
        ))
    wh = get_success_data(api_client.get_warehouse(wh["id"], TEST_USERS["manager_headers"]))
    return wh


# ─── Tier 5: Cycle count helpers ─────────────────────────────────────────

def setup_cycle_count_in_state(warehouse_id, bin_id, lot_id, target_state,
                              counted_qty_offset=0,
                              submitter_user_id=None, approver_user_id=None):
    """Drive a cycle count to `target_state` ∈ {SCHEDULED, COUNTING,
    RECONCILED, VARIANCE_FOUND, ADJUSTED, DISPUTED}.

    `counted_qty_offset` is added to book_qty (use 0 for RECONCILED, nonzero
    for VARIANCE_FOUND/ADJUSTED/DISPUTED).
    """
    submitter = make_staff_headers(submitter_user_id) if submitter_user_id \
        else TEST_USERS["staff_headers"]
    approver = make_auditor_headers(approver_user_id) if approver_user_id \
        else TEST_USERS["auditor_headers"]
    cc_payload = create_cycle_count_payload(bin_id=bin_id, lot_id=lot_id)
    cc = get_success_data(api_client.create_cycle_count(
        warehouse_id, cc_payload, submitter,
    ))
    if target_state == "SCHEDULED":
        return cc
    cc = get_success_data(api_client.start_cycle_count(
        warehouse_id, cc["id"], submitter,
    ))
    if target_state == "COUNTING":
        return cc
    counted_qty = cc["book_qty"] + counted_qty_offset
    cc = get_success_data(api_client.submit_cycle_count(
        warehouse_id, cc["id"],
        create_submit_count_payload(counted_qty), submitter,
    ))
    if target_state in ("RECONCILED", "VARIANCE_FOUND"):
        return cc
    if target_state == "ADJUSTED":
        return get_success_data(api_client.approve_cycle_count(
            warehouse_id, cc["id"], approver,
        ))
    if target_state == "DISPUTED":
        return get_success_data(api_client.dispute_cycle_count(
            warehouse_id, cc["id"], submitter,
        ))
    raise AssertionError(f"Unknown cycle count target state: {target_state}")


# ─── Tier 6: Multi-lot setups for selector tests ─────────────────────────

def setup_two_lots_same_sku(sku="PEN",
                           lot_a_expiry="2030-06-01T00:00:00.000Z",
                           lot_a_received_at_clock="2025-01-01T00:00:00.000Z",
                           lot_b_expiry="2025-12-31T00:00:00.000Z",
                           lot_b_received_at_clock="2025-02-01T00:00:00.000Z",
                           lot_a_units=50, lot_b_units=50,
                           unit_volume_cm3=20, unit_weight_g=10):
    """Create a warehouse with two ACTIVE lots of the same SKU putaway in
    that order, where:
      - LOT_A has earlier received_at and later expiry_date
      - LOT_B has later received_at and earlier expiry_date
    This is the canonical FEFO-vs-FIFO setup: FEFO picks LOT_B (earlier
    expiry); FIFO picks LOT_A (earlier received_at).

    Returns (warehouse, bin, lot_a, lot_b) with the warehouse clock at
    lot_b_received_at_clock at the end.
    """
    wh = create_warehouse(advance_clock_to=lot_a_received_at_clock)
    bin_obj = create_bin(
        wh["id"], zone="AMBIENT",
        capacity_volume_cm3=max(lot_a_units, lot_b_units) * unit_volume_cm3 * 4,
        capacity_weight_g=max(lot_a_units, lot_b_units) * unit_weight_g * 4,
    )
    lot_a = create_lot(
        wh["id"], sku=sku, category="AMBIENT",
        unit_volume_cm3=unit_volume_cm3, unit_weight_g=unit_weight_g,
        expiry_date=lot_a_expiry,
    )
    putaway_lot_units(wh["id"], lot_a["id"], lot_a_units)
    # Advance clock so LOT_B receives later
    get_success_data(api_client.advance_clock(
        create_clock_advance_payload(wh["id"], lot_b_received_at_clock),
        TEST_USERS["manager_headers"],
    ))
    lot_b = create_lot(
        wh["id"], sku=sku, category="AMBIENT",
        unit_volume_cm3=unit_volume_cm3, unit_weight_g=unit_weight_g,
        expiry_date=lot_b_expiry,
    )
    putaway_lot_units(wh["id"], lot_b["id"], lot_b_units)
    lot_a = get_success_data(api_client.get_lot(wh["id"], lot_a["id"], TEST_USERS["staff_headers"]))
    lot_b = get_success_data(api_client.get_lot(wh["id"], lot_b["id"], TEST_USERS["staff_headers"]))
    return wh, bin_obj, lot_a, lot_b


def setup_two_bins_distinct_distance_capacity(putaway_strategy):
    """Create a warehouse and two AMBIENT bins:
      BIN_C: position=(2,0), capacity_volume_cm3=2000  (closer, smaller)
      BIN_D: position=(5,0), capacity_volume_cm3=10000 (farther, bigger)
    Both have ample weight capacity. Returns (warehouse, bin_c, bin_d, lot)
    where lot has unit_volume_cm3=500 (so 1 unit fits in either).
    """
    wh = create_warehouse(putaway_strategy=putaway_strategy,
                         dock_position_x=0, dock_position_y=0)
    bin_c = create_bin(
        wh["id"], bin_code="BIN_C", zone="AMBIENT",
        position_x=2, position_y=0,
        capacity_volume_cm3=2000, capacity_weight_g=10000,
    )
    bin_d = create_bin(
        wh["id"], bin_code="BIN_D", zone="AMBIENT",
        position_x=5, position_y=0,
        capacity_volume_cm3=10000, capacity_weight_g=10000,
    )
    lot = create_lot(
        wh["id"], sku="PEN", category="AMBIENT",
        unit_volume_cm3=500, unit_weight_g=10, unit_value_cents=100,
    )
    return wh, bin_c, bin_d, lot


# ─── Tier 7: Inventory listing helper ────────────────────────────────────

def get_inventory_row(warehouse_id, bin_id, lot_id):
    """Return the inventory row matching (bin_id, lot_id) within warehouse,
    or None if not present."""
    res = api_client.list_inventory(
        warehouse_id, TEST_USERS["staff_headers"],
        params={"bin_id": bin_id, "lot_id": lot_id, "limit": 100},
    )
    body = get_success_data(res)
    rows = body if isinstance(body, list) else body.get("items") or body.get("data") or []
    for row in rows:
        if row.get("bin_id") == bin_id and row.get("lot_id") == lot_id:
            return row
    return None


def sum_inventory_qty_for_lot(warehouse_id, lot_id):
    """Sum of qty_units across all inventory rows for the given lot."""
    res = api_client.list_inventory(
        warehouse_id, TEST_USERS["staff_headers"],
        params={"lot_id": lot_id, "limit": 100},
    )
    body = get_success_data(res)
    rows = body if isinstance(body, list) else body.get("items") or body.get("data") or []
    return sum(int(r.get("qty_units", 0)) for r in rows
               if r.get("lot_id") == lot_id)
