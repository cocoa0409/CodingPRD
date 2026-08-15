"""Business logic: calculations, state transitions, cascades, helpers."""

import math
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store
from errors import (
    ApiError, ERR_VALIDATION, ERR_INVALID_STATE, ERR_NOT_FOUND,
    ERR_REFERENCE_NOT_FOUND, ERR_STALE_VERSION,
    ERR_LOT_NOT_QUALIFIED, ERR_INSUFFICIENT_LAMINATE,
    ERR_LOT_EXPIRES_BEFORE_SHIP,
)

# ---- Constants ----
DEFECT_DENSITY_PER_SQIN = Decimal("0.01")
ARRAY_YIELD_FLOOR = Decimal("0.50")
IMPEDANCE_LINE_FEE_CENTS = 2500
RETEST_FEE_CENTS = 1500
MIN_LOT_CHARGE_CENTS = 2000
MAX_SPREAD_OHMS = Decimal("6.0")
MIN_HOLE_MILS = 6
SHELF_LIFE_DAYS = 365
PARETO_VITAL_THRESHOLD = Decimal("80.0")
MAX_RETESTS = 2

LAYER_RATES = {2: Decimal("120"), 4: Decimal("200"), 6: Decimal("300"), 8: Decimal("420")}
FINISH_RATES = {
    "HASL": Decimal("40"),
    "OSP": Decimal("35"),
    "ENIG": Decimal("90"),
    "IMMERSION_SILVER": Decimal("70"),
    "HARD_GOLD": Decimal("160"),
}


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC with three fractional digits from logical clock."""
    c = store.logical_clock
    return c.strftime("%Y-%m-%dT%H:%M:%S.") + f"{c.microsecond // 1000:03d}Z"


def parse_iso(s):
    """Parse an ISO 8601 datetime string to a timezone-aware datetime."""
    if isinstance(s, datetime):
        return s
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def iso_str(dt):
    """Format datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def round_half_up_decimal(value, places=0):
    """Round a Decimal using ROUND_HALF_UP to the given number of decimal places."""
    if places == 0:
        return value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    fmt = "1." + "0" * places
    return value.quantize(Decimal(fmt), rounding=ROUND_HALF_UP)


# ---- Common field helpers ----

def make_common_fields():
    """Return dict with id, created_at, updated_at, version for new entities."""
    return {
        "id": new_id(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }


def make_append_only_fields():
    """Return dict with id, created_at for append-only entities (CouponMeasurement, DefectRecord)."""
    return {
        "id": new_id(),
        "created_at": now_iso(),
    }


def touch(entity):
    """Bump version and updated_at."""
    entity["version"] += 1
    entity["updated_at"] = now_iso()


def touch_no_version(entity):
    """Update updated_at only (should rarely be used; version bumps with mutations)."""
    entity["updated_at"] = now_iso()


# ---- Entity serialization ----

def serialize_customer(c):
    return {
        "id": c["id"],
        "company_name": c["company_name"],
        "contact_email": c["contact_email"],
        "credit_limit_cents": c["credit_limit_cents"],
        "tax_exempt": c["tax_exempt"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_quick_turn_lane(lane):
    return {
        "id": lane["id"],
        "lane_code": lane["lane_code"],
        "turn_days": lane["turn_days"],
        "capacity_boards_per_day": lane["capacity_boards_per_day"],
        "premium_multiplier": lane["premium_multiplier"],
        "active": lane["active"],
        "created_at": lane["created_at"],
        "updated_at": lane["updated_at"],
        "version": lane["version"],
    }


def serialize_laminate_lot(lot, recompute=True):
    # recompute=False is used by the create endpoint: PRD §3.5 states "The lot
    # opens in RECEIVED status", so creation must report (and leave) the lot
    # as RECEIVED even when the clock is already past its expiry_date; the
    # lazy expiry re-evaluation happens on later accesses to the lot.
    if recompute:
        recompute_lot_status(lot)
    return {
        "id": lot["id"],
        "material_code": lot["material_code"],
        "lot_code": lot["lot_code"],
        "manufacture_date": iso_str(lot["manufacture_date"]) if isinstance(lot["manufacture_date"], datetime) else lot["manufacture_date"],
        "panels_total": lot["panels_total"],
        "panels_reserved": lot["panels_reserved"],
        "panels_consumed": lot["panels_consumed"],
        "panels_available": lot["panels_total"] - lot["panels_reserved"] - lot["panels_consumed"],
        "expiry_date": iso_str(lot["expiry_date"]),
        "status": lot["status"],
        "qualified_at": iso_str(lot["qualified_at"]) if lot.get("qualified_at") else None,
        "created_at": lot["created_at"],
        "updated_at": lot["updated_at"],
        "version": lot["version"],
    }


def serialize_fab_order(o):
    consumed_lots = set()
    for r in store.laminate_reservations.values():
        if r["fab_order_id"] == o["id"] and r["status"] == "CONSUMED":
            lot = store.laminate_lots.get(r["laminate_lot_id"])
            if lot:
                consumed_lots.add(lot["lot_code"])
    return {
        "id": o["id"],
        "customer_id": o["customer_id"],
        "order_number": o["order_number"],
        "service_lane": o["service_lane"],
        "quick_turn_lane_id": o["quick_turn_lane_id"],
        "board_x_mils": o["board_x_mils"],
        "board_y_mils": o["board_y_mils"],
        "layer_count": o["layer_count"],
        "surface_finish": o["surface_finish"],
        "quantity_boards": o["quantity_boards"],
        "requested_ship_date": iso_str(o["requested_ship_date"]) if isinstance(o["requested_ship_date"], datetime) else o["requested_ship_date"],
        "fab_status": o["fab_status"],
        "quality_disposition": o["quality_disposition"],
        "boards_scrapped": o["boards_scrapped"],
        "laminate_lot_codes": sorted(consumed_lots),
        "provisional_total_cents": o["provisional_total_cents"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def serialize_stackup(s):
    return {
        "id": s["id"],
        "fab_order_id": s["fab_order_id"],
        "revision": s["revision"],
        "total_thickness_mils": s["total_thickness_mils"],
        "dielectric_material": s["dielectric_material"],
        "copper_weight_oz": s["copper_weight_oz"],
        "impedance_controlled": s["impedance_controlled"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_spec_line(sl):
    return {
        "id": sl["id"],
        "stackup_id": sl["stackup_id"],
        "layer_name": sl["layer_name"],
        "target_ohms": sl["target_ohms"],
        "tolerance_plus_ohms": sl["tolerance_plus_ohms"],
        "tolerance_minus_ohms": sl["tolerance_minus_ohms"],
        "line_type": sl["line_type"],
        "coupon_required": sl["coupon_required"],
        "created_at": sl["created_at"],
        "updated_at": sl["updated_at"],
        "version": sl["version"],
    }


def serialize_panel_array(pa):
    return {
        "id": pa["id"],
        "fab_order_id": pa["fab_order_id"],
        "array_x": pa["array_x"],
        "array_y": pa["array_y"],
        "panel_width_mils": pa["panel_width_mils"],
        "panel_height_mils": pa["panel_height_mils"],
        "boards_per_panel": pa["boards_per_panel"],
        "array_yield": pa["array_yield"],
        "good_boards_per_panel": pa["good_boards_per_panel"],
        "panels_required": pa["panels_required"],
        "utilization_pct": pa["utilization_pct"],
        "status": pa["status"],
        "created_at": pa["created_at"],
        "updated_at": pa["updated_at"],
        "version": pa["version"],
    }


def serialize_drill_program(dp):
    return {
        "id": dp["id"],
        "fab_order_id": dp["fab_order_id"],
        "revision": dp["revision"],
        "min_hole_mils": dp["min_hole_mils"],
        "hole_count": dp["hole_count"],
        "plated_aspect_ratio": dp.get("plated_aspect_ratio"),
        "created_by_user_id": dp["created_by_user_id"],
        "rejection_reason": dp.get("rejection_reason"),
        "status": dp["status"],
        "created_at": dp["created_at"],
        "updated_at": dp["updated_at"],
        "version": dp["version"],
    }


def serialize_laminate_reservation(r):
    return {
        "id": r["id"],
        "fab_order_id": r["fab_order_id"],
        "panel_array_id": r["panel_array_id"],
        "laminate_lot_id": r["laminate_lot_id"],
        "panels_allocated": r["panels_allocated"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_lane_slot_commitment(c):
    return {
        "id": c["id"],
        "lane_id": c["lane_id"],
        "ship_date": iso_str(c["ship_date"]) if isinstance(c["ship_date"], datetime) else c["ship_date"],
        "committed_boards": c["committed_boards"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_coupon(cp):
    return {
        "id": cp["id"],
        "fab_order_id": cp["fab_order_id"],
        "spec_line_id": cp["spec_line_id"],
        "panel_ref": cp["panel_ref"],
        "status": cp["status"],
        "retest_count": cp["retest_count"],
        "latest_measured_ohms": cp.get("latest_measured_ohms"),
        "disposition_basis": cp.get("disposition_basis"),
        "created_at": cp["created_at"],
        "updated_at": cp["updated_at"],
        "version": cp["version"],
    }


def serialize_coupon_measurement(m):
    return {
        "id": m["id"],
        "coupon_id": m["coupon_id"],
        "lab_slot_booking_id": m["lab_slot_booking_id"],
        "measured_ohms": m["measured_ohms"],
        "measured_ohms_b": m.get("measured_ohms_b"),
        "measured_at": m["measured_at"],
        "result": m["result"],
        "created_at": m["created_at"],
    }


def serialize_lab_slot_booking(b):
    return {
        "id": b["id"],
        "coupon_id": b["coupon_id"],
        "station": b["station"],
        "starts_at": iso_str(b["starts_at"]) if isinstance(b["starts_at"], datetime) else b["starts_at"],
        "ends_at": iso_str(b["ends_at"]) if isinstance(b["ends_at"], datetime) else b["ends_at"],
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def serialize_elec_test_run(r):
    return {
        "id": r["id"],
        "fab_order_id": r["fab_order_id"],
        "fixture_id": r["fixture_id"],
        "test_voltage": r["test_voltage"],
        "status": r["status"],
        "boards_tested": r["boards_tested"],
        "boards_failed": r["boards_failed"],
        "opens_found": r["opens_found"],
        "shorts_found": r["shorts_found"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_defect_record(d):
    return {
        "id": d["id"],
        "fab_order_id": d["fab_order_id"],
        "panel_array_id": d["panel_array_id"],
        "defect_code": d["defect_code"],
        "severity": d["severity"],
        "boards_affected": d["boards_affected"],
        "detected_at": iso_str(d["detected_at"]) if isinstance(d["detected_at"], datetime) else d["detected_at"],
        "source": d["source"],
        "created_at": d["created_at"],
    }


def serialize_invoice(inv):
    return {
        "id": inv["id"],
        "fab_order_id": inv["fab_order_id"],
        "actual_panels_run": inv["actual_panels_run"],
        "line_items": inv["line_items"],
        "retest_fees_cents": inv["retest_fees_cents"],
        "total_cents": inv["total_cents"],
        "status": inv["status"],
        "created_at": inv["created_at"],
        "updated_at": inv["updated_at"],
        "version": inv["version"],
    }


# ---- Lookup helpers ----

def get_order(order_id):
    o = store.fab_orders.get(order_id)
    if not o:
        raise ApiError(ERR_NOT_FOUND, "FabOrder not found", 404)
    return o


def get_customer(customer_id):
    c = store.customers.get(customer_id)
    if not c:
        raise ApiError(ERR_NOT_FOUND, "Customer not found", 404)
    return c


def get_lane(lane_id):
    l = store.quick_turn_lanes.get(lane_id)
    if not l:
        raise ApiError(ERR_NOT_FOUND, "QuickTurnLane not found", 404)
    return l


def get_lot(lot_id):
    lot = store.laminate_lots.get(lot_id)
    if not lot:
        raise ApiError(ERR_NOT_FOUND, "LaminateLot not found", 404)
    recompute_lot_status(lot)
    return lot


def get_stackup(stackup_id):
    s = store.stackups.get(stackup_id)
    if not s:
        raise ApiError(ERR_NOT_FOUND, "Stackup not found", 404)
    return s


def get_panel_array(array_id):
    pa = store.panel_arrays.get(array_id)
    if not pa:
        raise ApiError(ERR_NOT_FOUND, "PanelArray not found", 404)
    return pa


def get_drill_program(dp_id):
    dp = store.drill_programs.get(dp_id)
    if not dp:
        raise ApiError(ERR_NOT_FOUND, "DrillProgram not found", 404)
    return dp


def get_reservation(rid):
    r = store.laminate_reservations.get(rid)
    if not r:
        raise ApiError(ERR_NOT_FOUND, "LaminateReservation not found", 404)
    return r


def get_coupon(cid):
    c = store.impedance_coupons.get(cid)
    if not c:
        raise ApiError(ERR_NOT_FOUND, "ImpedanceCoupon not found", 404)
    return c


def get_booking(bid):
    b = store.lab_slot_bookings.get(bid)
    if not b:
        raise ApiError(ERR_NOT_FOUND, "LabSlotBooking not found", 404)
    return b


def get_etest_run(rid):
    r = store.elec_test_runs.get(rid)
    if not r:
        raise ApiError(ERR_NOT_FOUND, "ElecTestRun not found", 404)
    return r


def get_invoice(inv_id):
    inv = store.invoices.get(inv_id)
    if not inv:
        raise ApiError(ERR_NOT_FOUND, "Invoice not found", 404)
    return inv


# ---- Lot helpers ----

def compute_expiry(manufacture_date):
    return manufacture_date + timedelta(days=SHELF_LIFE_DAYS)


def recompute_lot_status(lot):
    """Lazily evaluate lot expiry and depletion. Called on every lot access."""
    clock = store.logical_clock
    expiry = lot["expiry_date"]
    if isinstance(expiry, str):
        expiry = parse_iso(expiry)
        lot["expiry_date"] = expiry

    if lot["status"] in ("RECEIVED", "QUALIFIED"):
        if clock >= expiry:
            old_status = lot["status"]
            lot["status"] = "EXPIRED"
            touch(lot)
            if old_status == "QUALIFIED":
                _cascade_lot_expiry(lot)
    if lot["status"] == "QUALIFIED":
        avail = lot["panels_total"] - lot["panels_reserved"] - lot["panels_consumed"]
        if avail == 0:
            lot["status"] = "DEPLETED"
            touch(lot)
    if lot["status"] == "DEPLETED":
        avail = lot["panels_total"] - lot["panels_reserved"] - lot["panels_consumed"]
        if avail > 0:
            lot["status"] = "QUALIFIED"
            touch(lot)


def _cascade_lot_expiry(lot):
    """Fire cascade when a QUALIFIED lot expires: release reservations, re-evaluate orders."""
    for r in list(store.laminate_reservations.values()):
        if r["laminate_lot_id"] == lot["id"] and r["status"] == "RESERVED":
            _release_reservation(r, lot=lot)


def _release_reservation(reservation, lot=None):
    """Release a RESERVED reservation back to the lot."""
    if reservation["status"] != "RESERVED":
        return
    if lot is None:
        lot = store.laminate_lots.get(reservation["laminate_lot_id"])
    reservation["status"] = "RELEASED"
    touch(reservation)
    if lot:
        lot["panels_reserved"] -= reservation["panels_allocated"]
        touch(lot)
        # DEPLETED -> QUALIFIED if availability rises above 0
        if lot["status"] == "DEPLETED":
            avail = lot["panels_total"] - lot["panels_reserved"] - lot["panels_consumed"]
            if avail > 0:
                lot["status"] = "QUALIFIED"
                touch(lot)
    # Re-evaluate owning order coverage
    _reevaluate_order_coverage(reservation["fab_order_id"])


def _reevaluate_order_coverage(order_id):
    """If order is AWAITING_LAMINATE and coverage drops below panels_required, -> ON_HOLD."""
    order = store.fab_orders.get(order_id)
    if not order:
        return
    if order["fab_status"] != "AWAITING_LAMINATE":
        return
    # Find released panel array
    released_array = _find_released_array(order_id)
    if not released_array:
        return
    panels_required = released_array["panels_required"]
    reserved_coverage = sum(
        r["panels_allocated"]
        for r in store.laminate_reservations.values()
        if r["fab_order_id"] == order_id and r["status"] == "RESERVED"
    )
    if reserved_coverage < panels_required:
        order["fab_status"] = "ON_HOLD"
        touch(order)


def _find_released_array(order_id):
    """Find the RELEASED PanelArray for the order, if any."""
    for pa in store.panel_arrays.values():
        if pa["fab_order_id"] == order_id and pa["status"] == "RELEASED":
            return pa
    return None


def _find_locked_stackup(order_id):
    """Find the LOCKED Stackup for the order, if any."""
    for s in store.stackups.values():
        if s["fab_order_id"] == order_id and s["status"] == "LOCKED":
            return s
    return None


def _get_spec_lines(stackup_id):
    return [sl for sl in store.impedance_spec_lines.values() if sl["stackup_id"] == stackup_id]


# ---- Pricing calculation ----

def compute_provisional_pricing(order):
    """Compute PROVISIONAL pricing variant. Returns None if no RELEASED array exists."""
    released_array = _find_released_array(order["id"])
    if not released_array:
        return None
    return _compute_price(order, released_array, released_array["panels_required"], 0)


def compute_final_pricing(order, actual_panels_run):
    """Compute FINAL pricing variant."""
    released_array = _find_released_array(order["id"])
    if not released_array:
        # Should not happen in practice, but guard anyway
        return None
    total_retests = sum(
        c["retest_count"]
        for c in store.impedance_coupons.values()
        if c["fab_order_id"] == order["id"]
    )
    retest_cents = RETEST_FEE_CENTS * total_retests
    return _compute_price(order, released_array, actual_panels_run, retest_cents)


def _compute_price(order, panel_array, panels, retest_cents):
    """Pinned rounding: round each line to integer cents first, sum, multiply, round, floor."""
    panel_area_sqin = Decimal(panel_array["panel_width_mils"]) * Decimal(panel_array["panel_height_mils"]) / Decimal(1_000_000)
    panels_d = Decimal(panels)

    base_cents = int(round_half_up_decimal(panel_area_sqin * panels_d * LAYER_RATES[order["layer_count"]]))
    finish_cents = int(round_half_up_decimal(panel_area_sqin * panels_d * FINISH_RATES[order["surface_finish"]]))

    locked = _find_locked_stackup(order["id"])
    n_lines = len(_get_spec_lines(locked["id"])) if locked else 0
    impedance_cents = IMPEDANCE_LINE_FEE_CENTS * n_lines

    subtotal = base_cents + finish_cents + impedance_cents + retest_cents

    multiplier = Decimal("1.0")
    if order["service_lane"] == "QUICK_TURN" and order["quick_turn_lane_id"]:
        lane = store.quick_turn_lanes.get(order["quick_turn_lane_id"])
        if lane:
            multiplier = Decimal(str(lane["premium_multiplier"]))

    total = int(round_half_up_decimal(Decimal(subtotal) * multiplier))
    total = max(MIN_LOT_CHARGE_CENTS, total)

    line_items = [
        {"line_type": "base", "amount_cents": base_cents},
        {"line_type": "finish", "amount_cents": finish_cents},
        {"line_type": "impedance", "amount_cents": impedance_cents},
        {"line_type": "retest", "amount_cents": retest_cents},
    ]

    return {
        "line_items": line_items,
        "retest_fees_cents": retest_cents,
        "total_cents": total,
    }


# ---- Panel array yield calculation ----

def compute_array_yield_fields(order, array_x, array_y, panel_width_mils, panel_height_mils):
    board_area_sqin = Decimal(order["board_x_mils"]) * Decimal(order["board_y_mils"]) / Decimal(1_000_000)
    panel_area_sqin = Decimal(panel_width_mils) * Decimal(panel_height_mils) / Decimal(1_000_000)
    boards_per_panel = array_x * array_y

    # array_yield = max(0.50, 1 - 0.01 * board_area_sqin), 4dp
    raw_yield = Decimal("1") - DEFECT_DENSITY_PER_SQIN * board_area_sqin
    array_yield = max(ARRAY_YIELD_FLOOR, raw_yield)
    array_yield = round_half_up_decimal(array_yield, 4)

    good_boards_per_panel = int((Decimal(boards_per_panel) * array_yield).to_integral_value(rounding="ROUND_FLOOR"))

    panels_required = 0
    if good_boards_per_panel > 0:
        panels_required = math.ceil(order["quantity_boards"] / good_boards_per_panel)

    utilization_pct = round_half_up_decimal(
        Decimal(100) * Decimal(boards_per_panel) * board_area_sqin / panel_area_sqin, 2
    )

    return {
        "boards_per_panel": boards_per_panel,
        "array_yield": float(array_yield),
        "good_boards_per_panel": good_boards_per_panel,
        "panels_required": panels_required,
        "utilization_pct": float(utilization_pct),
    }


# ---- Lane slot commitment helpers ----

def _ship_date_key(requested_ship_date):
    """Normalize a datetime to UTC midnight for slot keying."""
    dt = requested_ship_date if isinstance(requested_ship_date, datetime) else parse_iso(requested_ship_date)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def get_committed_boards(lane_id, ship_date_key):
    """Get committed boards for a lane+date from the materialized commitment."""
    for c in store.lane_slot_commitments.values():
        if c["lane_id"] == lane_id and c["ship_date"] == ship_date_key:
            return c["committed_boards"]
    return 0


def upsert_lane_commitment(lane_id, ship_date_key, boards_delta):
    """Add (or subtract) boards from the lane commitment."""
    for c in store.lane_slot_commitments.values():
        if c["lane_id"] == lane_id and c["ship_date"] == ship_date_key:
            c["committed_boards"] += boards_delta
            touch(c)
            return c
    # Create new
    fields = make_common_fields()
    commitment = {
        **fields,
        "lane_id": lane_id,
        "ship_date": ship_date_key,
        "committed_boards": boards_delta,
    }
    store.lane_slot_commitments[commitment["id"]] = commitment
    return commitment


# ---- Order cancel cascade ----

def cancel_order_cascade(order):
    """Full depth-three cancel cascade per §3.9."""
    order_id = order["id"]

    # Link 1: cancel all PanelArrays in {DRAFT, RELEASED}
    cancelled_array_ids = set()
    for pa in store.panel_arrays.values():
        if pa["fab_order_id"] == order_id and pa["status"] in ("DRAFT", "RELEASED"):
            pa["status"] = "CANCELLED"
            touch(pa)
            cancelled_array_ids.add(pa["id"])

    # Link 2: release RESERVED reservations on just-cancelled arrays
    for r in store.laminate_reservations.values():
        if r["panel_array_id"] in cancelled_array_ids and r["status"] == "RESERVED":
            lot = store.laminate_lots.get(r["laminate_lot_id"])
            r["status"] = "RELEASED"
            touch(r)
            if lot:
                lot["panels_reserved"] -= r["panels_allocated"]
                touch(lot)
                if lot["status"] == "DEPLETED":
                    avail = lot["panels_total"] - lot["panels_reserved"] - lot["panels_consumed"]
                    if avail > 0:
                        lot["status"] = "QUALIFIED"
                        touch(lot)

    # Cancel all drill programs not already CANCELLED
    for dp in store.drill_programs.values():
        if dp["fab_order_id"] == order_id and dp["status"] != "CANCELLED":
            dp["status"] = "CANCELLED"
            touch(dp)

    # Cancel all coupons not in terminal state
    cancelled_coupon_ids = set()
    for cp in store.impedance_coupons.values():
        if cp["fab_order_id"] == order_id and cp["status"] not in ("PASSED", "CANCELLED"):
            cp["status"] = "CANCELLED"
            touch(cp)
            cancelled_coupon_ids.add(cp["id"])

    # Cancel BOOKED lab bookings of those coupons
    for b in store.lab_slot_bookings.values():
        if b["coupon_id"] in cancelled_coupon_ids and b["status"] == "BOOKED":
            b["status"] = "CANCELLED"
            touch(b)

    # Cancel all e-test runs in SCHEDULED or RUNNING
    for r in store.elec_test_runs.values():
        if r["fab_order_id"] == order_id and r["status"] in ("SCHEDULED", "RUNNING"):
            r["status"] = "CANCELLED"
            touch(r)

    # Release lane commitment for QUICK_TURN
    if order["service_lane"] == "QUICK_TURN" and order["quick_turn_lane_id"]:
        if order["fab_status"] in ("RELEASED", "IN_PRODUCTION", "ON_HOLD", "AWAITING_ETEST", "COMPLETED"):
            sdk = _ship_date_key(order["requested_ship_date"])
            upsert_lane_commitment(order["quick_turn_lane_id"], sdk, -order["quantity_boards"])

    # Transition the order itself
    order["fab_status"] = "CANCELLED"
    touch(order)


# ---- Start production cascade ----

def start_production_cascade(order):
    """Consume all RESERVED reservations for the order."""
    for r in store.laminate_reservations.values():
        if r["fab_order_id"] == order["id"] and r["status"] == "RESERVED":
            r["status"] = "CONSUMED"
            touch(r)
            lot = store.laminate_lots.get(r["laminate_lot_id"])
            if lot:
                lot["panels_reserved"] -= r["panels_allocated"]
                lot["panels_consumed"] += r["panels_allocated"]
                touch(lot)
                avail = lot["panels_total"] - lot["panels_reserved"] - lot["panels_consumed"]
                if lot["status"] == "QUALIFIED" and avail == 0:
                    lot["status"] = "DEPLETED"
                    touch(lot)
