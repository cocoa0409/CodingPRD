"""Composite setup helpers for the Warehouse Management API.

Most interesting test claims require the system to be driven through a multi-step
inbound/outbound chain before the behaviour under test can fire. These helpers
encapsulate those chains so test functions focus on assertions.

The test harness restarts the server (empty DB) before every test, so every
helper builds its preconditions from scratch using only PRD-declared endpoints.
All setup calls go through get_success_data() (lenient 2xx validator) so a setup
failure surfaces as a clear "Setup step failed" message.

Identity note (PRD 2.1): all six roles are opaque; X-User-ID is never an ownership
key. The cycle-count helpers thread distinct controller user ids only to exercise
the segregation-of-duties separation (PRD 2.9).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_inventory_controller_headers
from . import factories as f


ADMIN = TEST_USERS["platform_admin_headers"]
CLERK = TEST_USERS["receiving_clerk_headers"]
PUTAWAY = TEST_USERS["putaway_operator_headers"]
PICKER = TEST_USERS["picker_headers"]
PLANNER = TEST_USERS["wave_planner_headers"]
IC = TEST_USERS["inventory_controller_headers"]


# ─── Low-level building blocks ────────────────────────────────────────────────

def create_sku(**overrides) -> dict:
    """Create a SKU (PlatformAdmin). Returns the created Sku."""
    return get_success_data(api_client.create_sku(f.create_sku_payload(**overrides), ADMIN))


def create_location(**overrides) -> dict:
    """Create a Location. Returns the created Location."""
    return get_success_data(api_client.create_location(f.create_location_payload(**overrides), ADMIN))


def create_asn(**overrides) -> dict:
    """Announce an InboundAsn (ReceivingClerk). Returns the ASN."""
    return get_success_data(api_client.create_inbound_asn(f.create_inbound_asn_payload(**overrides), CLERK))


def add_asn_line(asn_id, sku_id, expected_qty) -> dict:
    return get_success_data(
        api_client.add_asn_line(asn_id, f.create_asn_line_payload(sku_id, expected_qty=expected_qty), CLERK)
    )


def post_receipt(asn_id, asn_line_id, received_qty) -> dict:
    """Post a receipt; mints an LPN. Returns the ReceiptEvent (carries lpn_id)."""
    return get_success_data(
        api_client.post_receipt(asn_id, f.create_receipt_payload(asn_line_id, received_qty=received_qty), CLERK)
    )


def get_lpn(lpn_id) -> dict:
    return get_success_data(api_client.get_license_plate(lpn_id, PLANNER))


def first_putaway_task_for_lpn(lpn_id) -> dict:
    """Return the (single) putaway task whose lpn_id matches."""
    data, _ = _list(api_client.list_putaway_tasks(PUTAWAY, params={"lpn_id": lpn_id}))
    assert data, f"expected a putaway task for lpn {lpn_id}"
    return data[0]


def _list(resp):
    body = resp.json()
    return body.get("data", []), body.get("meta", {})


# ─── Receive → putaway → STORED chains ────────────────────────────────────────

def receive_one_lpn(sku_id, qty, handling_mode="PUTAWAY", asn_overrides=None):
    """Announce an ASN, add a line, post one receipt of `qty`.

    Returns (asn, line, lpn) where lpn is the freshly-minted PUTAWAY_PENDING plate
    (fetched fresh). Does NOT close the ASN.
    """
    asn = create_asn(**(asn_overrides or {}), handling_mode=handling_mode)
    line = add_asn_line(asn["id"], sku_id, qty)
    receipt = post_receipt(asn["id"], line["id"], qty)
    lpn = get_lpn(receipt["lpn_id"])
    return asn, line, lpn


def store_lpn(sku_id, qty, asn_overrides=None):
    """Receive one LPN of `qty`, close the (PUTAWAY) ASN, assign + complete its
    putaway task so the plate ends STORED at a freshly-created RESERVE bin.

    Returns (location, lpn) with the plate fetched fresh (disposition STORED).
    """
    loc = create_location(zone="RESERVE", max_volume_cm3=100000)
    asn, line, lpn = receive_one_lpn(sku_id, qty, "PUTAWAY", asn_overrides)
    get_success_data(api_client.close_asn(asn["id"], CLERK))
    task = first_putaway_task_for_lpn(lpn["id"])
    get_success_data(api_client.assign_putaway_task(task["id"], PUTAWAY))
    get_success_data(api_client.complete_putaway_task(task["id"], PUTAWAY))
    return loc, get_lpn(lpn["id"])


def setup_stored_lpn(sku_overrides=None, qty=10):
    """Create a SKU and one STORED LPN of `qty` at a RESERVE bin.

    Returns (sku, location, lpn). The most common base scenario.
    """
    sku = create_sku(**(sku_overrides or {}))
    loc, lpn = store_lpn(sku["id"], qty)
    return sku, loc, lpn


def setup_open_putaway_task(sku_overrides=None, qty=5, location_overrides=None):
    """Create a SKU, a candidate RESERVE/PICK_FACE bin, receive one LPN of `qty`,
    close the PUTAWAY ASN to spawn a CREATED putaway task.

    Returns (sku, location, lpn, task). `location_overrides` configures the single
    candidate bin (defaults to a large RESERVE bin).
    """
    sku = create_sku(**(sku_overrides or {}))
    loc_kwargs = {"zone": "RESERVE", "max_volume_cm3": 100000}
    if location_overrides:
        loc_kwargs.update(location_overrides)
    loc = create_location(**loc_kwargs)
    asn, line, lpn = receive_one_lpn(sku["id"], qty, "PUTAWAY")
    get_success_data(api_client.close_asn(asn["id"], CLERK))
    task = first_putaway_task_for_lpn(lpn["id"])
    return sku, loc, get_lpn(lpn["id"]), task


# ─── Outbound order / line helpers ────────────────────────────────────────────

def create_order(**overrides) -> dict:
    return get_success_data(api_client.create_outbound_order(f.create_outbound_order_payload(**overrides), PLANNER))


def add_order_line(order_id, sku_id, ordered_qty) -> dict:
    return get_success_data(
        api_client.add_order_line(order_id, f.create_order_line_payload(sku_id, ordered_qty=ordered_qty), PLANNER)
    )


def create_order_with_line(sku_id, ordered_qty, order_overrides=None):
    """Create an OPEN order with one line. Returns (order, line)."""
    order = create_order(**(order_overrides or {}))
    line = add_order_line(order["id"], sku_id, ordered_qty)
    return order, line


# ─── Manual allocation ────────────────────────────────────────────────────────

def create_manual_allocation(order_line_id, lpn_id, allocated_qty):
    """Create a RESERVED allocation, re-reading the LPN version immediately before
    so expected_lpn_version is current. Returns the InventoryAllocation."""
    lpn = get_lpn(lpn_id)
    payload = f.create_allocation_payload(order_line_id, lpn_id, allocated_qty, lpn["version"])
    return get_success_data(api_client.create_allocation(payload, PLANNER))


# ─── Wave lifecycle ───────────────────────────────────────────────────────────

def create_planning_wave(**overrides) -> dict:
    return get_success_data(api_client.create_wave(f.create_wave_payload(**overrides), PLANNER))


def setup_wave_ready_to_release(sku, location, lpn, ordered_qty, order_overrides=None):
    """Given an existing STORED lpn (qty >= ordered_qty), create an order+line and
    a PLANNING wave with the order added.

    Returns (order, line, wave). Wave is fetched fresh (version reflects add-order).
    """
    order, line = create_order_with_line(sku["id"], ordered_qty, order_overrides)
    wave = create_planning_wave()
    get_success_data(api_client.add_order_to_wave(wave["id"], f.add_order_to_wave_payload(order["id"]), PLANNER))
    wave = get_success_data(api_client.get_wave(wave["id"], PLANNER))
    return order, line, wave


def release_wave(wave):
    """Release a PLANNING wave using its current version. Returns the released wave."""
    payload = f.release_wave_payload(wave["version"])
    return get_success_data(api_client.release_wave(wave["id"], payload, PLANNER))


def setup_released_wave(sku_overrides=None, ordered_qty=10, lpn_qty=10):
    """Single-line order, STORED LPN, released wave (fulfillment ALLOCATED).

    Returns (sku, location, lpn, order, line, wave) with wave fetched fresh.
    """
    sku, loc, lpn = setup_stored_lpn(sku_overrides, qty=lpn_qty)
    order, line, wave = setup_wave_ready_to_release(sku, loc, lpn, ordered_qty)
    wave = release_wave(wave)
    return sku, loc, lpn, order, line, wave


def setup_in_progress_pick(sku_overrides=None, ordered_qty=5, lpn_qty=5):
    """Drive a single-line order all the way to one IN_PROGRESS pick task.

    Returns (sku, location, lpn, order, line, wave, pick_task).
    """
    sku, loc, lpn, order, line, wave = setup_released_wave(sku_overrides, ordered_qty, lpn_qty)
    get_success_data(api_client.start_picking_wave(wave["id"], PLANNER))
    tasks, _ = _list(api_client.list_wave_pick_tasks(wave["id"], PICKER))
    assert tasks, "expected at least one pick task after start-picking"
    pick = tasks[0]
    get_success_data(api_client.start_pick_task(pick["id"], PICKER))
    pick = get_success_data(api_client.get_pick_task(pick["id"], PICKER))
    return sku, loc, lpn, order, line, wave, pick


# ─── Cycle-count chains ───────────────────────────────────────────────────────

def setup_open_cycle_count(stored_qty=20, sku_overrides=None):
    """Create a SKU with `stored_qty` STORED at one RESERVE bin, then OPEN a cycle
    count for that SKU+location (snapshots system_qty).

    Returns (sku, location, lpn, cycle_count).
    """
    sku, loc, lpn = setup_stored_lpn(sku_overrides, qty=stored_qty)
    cc = get_success_data(api_client.create_cycle_count(f.create_cycle_count_payload(loc["id"], sku["id"]), IC))
    return sku, loc, lpn, cc


def setup_counted_cycle_count(stored_qty=20, counted_qty=20, counter_user_id="ic-counter",
                              sku_overrides=None):
    """OPEN then SUBMIT a cycle count (status COUNTED), pinning counted_by_user_id
    to `counter_user_id`.

    Returns (sku, location, lpn, cycle_count).
    """
    sku, loc, lpn, cc = setup_open_cycle_count(stored_qty, sku_overrides)
    counter = make_inventory_controller_headers(counter_user_id)
    cc = get_success_data(
        api_client.submit_cycle_count(cc["id"], f.submit_cycle_count_payload(counted_qty), counter)
    )
    return sku, loc, lpn, cc


def setup_reconciled_sku_at_clock(reconcile_iso, sku_overrides=None, stored_qty=5):
    """Set the clock to `reconcile_iso`, create a SKU, store stock, then open/submit/
    approve a cycle count (counted == system, variance 0) so the SKU has a RECONCILED
    count at `reconcile_iso`. Uses two distinct controller ids to satisfy segregation.

    Returns (sku, location, lpn, cycle_count).
    """
    get_success_data(api_client.set_clock(f.set_clock_payload(reconcile_iso), ADMIN))
    sku, loc, lpn, cc = setup_counted_cycle_count(
        stored_qty=stored_qty, counted_qty=stored_qty,
        counter_user_id="ic-counter", sku_overrides=sku_overrides,
    )
    approver = make_inventory_controller_headers("ic-approver")
    cc = get_success_data(api_client.approve_cycle_count(cc["id"], approver))
    return sku, loc, lpn, cc


# ─── Replenishment chains ─────────────────────────────────────────────────────

def setup_pick_face_with_onhand(sku, face_qty, max_volume_cm3=100000):
    """Create a PICK_FACE location dedicated to `sku` and, if face_qty > 0, store
    `face_qty` eaches there (received then put away to the pick face).

    Returns the pick-face Location (fetched fresh).
    """
    pf = create_location(zone="PICK_FACE", max_volume_cm3=max_volume_cm3, pick_face_for_sku_id=sku["id"])
    if face_qty > 0:
        asn, line, lpn = receive_one_lpn(sku["id"], face_qty, "PUTAWAY")
        get_success_data(api_client.close_asn(asn["id"], CLERK))
        task = first_putaway_task_for_lpn(lpn["id"])
        get_success_data(api_client.assign_putaway_task(task["id"], PUTAWAY))
        get_success_data(api_client.complete_putaway_task(task["id"], PUTAWAY))
    return get_success_data(api_client.get_location(pf["id"], ADMIN))


def setup_replen_eligible(sku_overrides=None, face_qty=0, reserve_qty=0):
    """Create a SKU with a dedicated PICK_FACE holding `face_qty` and (optionally)
    `reserve_qty` STORED in a RESERVE bin.

    Returns (sku, pick_face, reserve_location_or_None). For A-class SKUs the
    putaway selector slots the pick-face stock to the pick face (PICK_FACE preferred);
    callers needing reserve stock should pass a B/C-class SKU so reserve stock lands
    in RESERVE.
    """
    sku = create_sku(**(sku_overrides or {}))
    pf = setup_pick_face_with_onhand(sku, face_qty)
    reserve_loc = None
    if reserve_qty > 0:
        reserve_loc = create_location(zone="RESERVE", max_volume_cm3=100000)
        asn, line, lpn = receive_one_lpn(sku["id"], reserve_qty, "PUTAWAY")
        get_success_data(api_client.close_asn(asn["id"], CLERK))
        task = first_putaway_task_for_lpn(lpn["id"])
        get_success_data(api_client.assign_putaway_task(task["id"], PUTAWAY))
        get_success_data(api_client.complete_putaway_task(task["id"], PUTAWAY))
    return sku, pf, reserve_loc
