"""Business logic: calculations, derived-field recomputation, cascades."""
from datetime import timedelta
from decimal import Decimal, ROUND_CEILING

from mill.common import (
    D,
    fmt_dt,
    new_rec,
    now_dt,
    now_iso,
    q3,
    r0c,
    r2,
    r3,
    r4,
    touch,
)
from mill.store import store

NOMINAL_WIDTH_IN = D("54")
SELVAGE_TRIM_IN = D("2")

FREIGHT_CLASSES = [
    "CLASS_65", "CLASS_70", "CLASS_85", "CLASS_92_5", "CLASS_100", "CLASS_110",
    "CLASS_125", "CLASS_150", "CLASS_175", "CLASS_200", "CLASS_250", "CLASS_300",
    "CLASS_400",
]
FREIGHT_THRESHOLDS = [
    (D("22.5"), "CLASS_65"), (D("15"), "CLASS_70"), (D("12"), "CLASS_85"),
    (D("9"), "CLASS_92_5"), (D("8"), "CLASS_100"), (D("7"), "CLASS_110"),
    (D("6"), "CLASS_125"), (D("5"), "CLASS_150"), (D("4"), "CLASS_175"),
    (D("3"), "CLASS_200"), (D("2"), "CLASS_250"), (D("1"), "CLASS_300"),
]
FREIGHT_RATES_CENTS = {
    "CLASS_65": 40, "CLASS_70": 50, "CLASS_85": 65, "CLASS_92_5": 80,
    "CLASS_100": 95, "CLASS_110": 110, "CLASS_125": 130, "CLASS_150": 155,
    "CLASS_175": 190, "CLASS_200": 230, "CLASS_250": 280, "CLASS_300": 340,
    "CLASS_400": 420,
}
VALUE_PER_LB_THRESHOLD_CENTS = D("3000")
FUEL_PCT = D("0.18")
WG_MIN_CENTS = 15000
WG_PER_PIECE_CENTS = 8500
WG_INSIDE_SURCHARGE_CENTS = 4500

CONTAINER_MOQ = 50
CONTAINER_UNIT_COST_CENTS = 1200
CONTAINER_LEAD_DAYS = 45
DOMESTIC_UNIT_COST_CENTS = 2000
DOMESTIC_LEAD_DAYS = 7

REFURB_GAP_DAYS = 5

OP_REQUIRED_LINE_STAGE = {"CUT": "ALLOCATED", "SEW": "CUT", "UPHOLSTER": "SEWN"}
OP_CELL_TYPE = {"CUT": "CUTTING", "SEW": "SEWING", "UPHOLSTER": "UPHOLSTERY"}


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


def lines_of(order_id):
    return sorted(
        [l for l in store.order_lines.values() if l["order_id"] == order_id],
        key=lambda r: r["_seq"],
    )


def allocs_of_line(line_id):
    return sorted(
        [a for a in store.allocations.values() if a["order_line_id"] == line_id],
        key=lambda r: r["_seq"],
    )


def allocs_of_lot(lot_id):
    return [a for a in store.allocations.values() if a["lot_id"] == lot_id]


def active_alloc_sum_line(line_id):
    total = D("0")
    for a in allocs_of_line(line_id):
        if a["status"] == "ACTIVE":
            total += D(a["yards"])
    return total


def plans_of_line(line_id):
    return sorted(
        [p for p in store.cut_plans.values() if p["order_line_id"] == line_id],
        key=lambda r: r["_seq"],
    )


def bookings_of_line(line_id):
    return [b for b in store.cell_bookings.values() if b["order_line_id"] == line_id]


def bookings_of_cell(cell_id):
    return [b for b in store.cell_bookings.values() if b["cell_id"] == cell_id]


# ---------------------------------------------------------------------------
# Derived-field recomputation (each counts as a mutation of its owner)
# ---------------------------------------------------------------------------


def recompute_lot(lot):
    active = D("0")
    consumed = D("0")
    for a in allocs_of_lot(lot["id"]):
        if a["status"] == "ACTIVE":
            active += D(a["yards"])
        elif a["status"] == "CONSUMED":
            consumed += D(a["consumed_yards"])
    usable = D(lot["usable_yards"]) if lot["usable_yards"] is not None else D("0")
    lot["allocated_yards"] = r3(active)
    lot["available_yards"] = r3(usable - active - consumed)
    touch(lot)


def recompute_cell_hours(cell):
    total = D("0")
    for b in bookings_of_cell(cell["id"]):
        if b["status"] in ("BOOKED", "IN_PROGRESS"):
            total += D(b["duration_hours"])
    cell["committed_hours"] = r2(total)
    touch(cell)


def recompute_dealer_outstanding(dealer):
    total = 0
    for s in store.samples.values():
        if s["dealer_id"] == dealer["id"] and s["disposition"] == "ON_LOAN":
            total += s["sample_value_cents"]
    dealer["outstanding_sample_value_cents"] = total
    touch(dealer)


def recompute_order_credit(order):
    """COM credit: per-line round_half_up(allocated COM yards x credit), summed."""
    total_credit = 0
    for line in lines_of(order["id"]):
        com_yards = D("0")
        for a in allocs_of_line(line["id"]):
            if a["status"] in ("ACTIVE", "CONSUMED"):
                lot = store.material_lots.get(a["lot_id"])
                if lot and lot["ownership"] == "CUSTOMER":
                    com_yards += D(a["yards"])
        if com_yards > 0:
            spec = store.fabric_specs.get(line["fabric_spec_id"])
            credit_per_yard = D(spec["com_credit_per_yard_cents"]) if spec else D("0")
            total_credit += r0c(com_yards * credit_per_yard)
    order["com_credit_cents"] = total_credit
    order["total_cents"] = order["subtotal_cents"] - total_credit
    touch(order)


# ---------------------------------------------------------------------------
# Shortfall evaluation + order hold/release cascades
# ---------------------------------------------------------------------------


def eval_line(line):
    """Recompute allocated/shortfall; flip ALLOCATED<->MATERIAL_SHORTFALL; cascade."""
    active = active_alloc_sum_line(line["id"])
    line["allocated_yards"] = r3(active)
    req = line["required_yards_final"]
    if req is None:
        req = line["required_yards_provisional"]
    if req is None:
        line["shortfall_yards"] = 0
        touch(line)
        return
    req = D(req)
    line["shortfall_yards"] = r3(max(D("0"), req - active))
    old = line["status"]
    if old in ("MATERIAL_SHORTFALL", "ALLOCATED"):
        new = "ALLOCATED" if active >= req else "MATERIAL_SHORTFALL"
        if new != old:
            line["status"] = new
            touch(line)
            _cascade_line_flip(line, old, new)
            return
    touch(line)


def _cascade_line_flip(line, old, new):
    order = store.orders.get(line["order_id"])
    if order is None:
        return
    if new == "ALLOCATED" and order["status"] == "MATERIAL_HOLD":
        if all(l["status"] != "MATERIAL_SHORTFALL" for l in lines_of(order["id"])):
            order["status"] = "CONFIRMED"
            touch(order)
    elif new == "MATERIAL_SHORTFALL" and old == "ALLOCATED" and order["status"] == "CONFIRMED":
        order["status"] = "MATERIAL_HOLD"
        touch(order)
        release_booked_bookings(order)


def release_booked_bookings(order):
    for line in lines_of(order["id"]):
        for b in bookings_of_line(line["id"]):
            if b["status"] == "BOOKED":
                b["status"] = "RELEASED"
                touch(b)
                cell = store.cells.get(b["cell_id"])
                if cell:
                    recompute_cell_hours(cell)


def release_allocation(alloc, with_credit=True):
    """ACTIVE -> RELEASED with lot/line/order recomputation."""
    alloc["status"] = "RELEASED"
    touch(alloc)
    lot = store.material_lots.get(alloc["lot_id"])
    if lot:
        recompute_lot(lot)
    line = store.order_lines.get(alloc["order_line_id"])
    if line:
        eval_line(line)
        if with_credit:
            order = store.orders.get(line["order_id"])
            if order:
                recompute_order_credit(order)


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------


def provisional_yards(model, spec, quantity):
    """fabric_requirement_provisional: nominal-width spec-sheet estimate."""
    W = D(spec["nominal_width_inches"])
    width_factor = D("54") / (W - SELVAGE_TRIM_IN)
    if width_factor < 1:
        width_factor = D("1")
    B = D(model["base_fabric_yards"])
    R = D(spec["pattern_repeat_v_inches"])
    Q = D(quantity)
    if model["requires_pattern_match"] and R > 0:
        repeat_yards = R / D("36")
        if spec["match_method"] == "DROP_HALF":
            repeat_yards = repeat_yards * D("1.5")
        per_unit = B * width_factor
        repeats = int((per_unit / repeat_yards).to_integral_value(rounding=ROUND_CEILING))
        base = D(repeats) * repeat_yards * Q
    else:
        base = B * width_factor * Q
    if quantity <= 5:
        waste = D("0.15")
    elif quantity <= 20:
        waste = D("0.10")
    else:
        waste = D("0.07")
    return r3(base * (1 + waste))


def final_yards(marker_length_yards, measured_width_inches):
    """fabric_requirement_final: marker length scaled by measured usable width."""
    return r3(
        D(marker_length_yards)
        * (NOMINAL_WIDTH_IN - SELVAGE_TRIM_IN)
        / (D(measured_width_inches) - SELVAGE_TRIM_IN)
    )


def fefo_reserve(line):
    """lot_selector_fefo: reserve PLANT stock for the line, oldest received first."""
    remaining = D(line["required_yards_provisional"]) - active_alloc_sum_line(line["id"])
    pool = [
        l
        for l in store.material_lots.values()
        if l["fabric_spec_id"] == line["fabric_spec_id"]
        and l["ownership"] == "PLANT"
        and l["status"] == "AVAILABLE"
        and D(l["available_yards"]) > 0
    ]
    pool.sort(key=lambda l: (l["received_at"] or "", l["_seq"]))
    for lot in pool:
        if remaining <= 0:
            break
        y = min(D(lot["available_yards"]), remaining)
        alloc = new_rec()
        alloc.update(
            {
                "lot_id": lot["id"],
                "order_line_id": line["id"],
                "yards": r3(y),
                "consumed_yards": 0,
                "status": "ACTIVE",
            }
        )
        store.allocations[alloc["id"]] = alloc
        remaining -= y
        recompute_lot(lot)


def classify_freight(density_4dp, declared_value_cents, weight_lb):
    d = D(density_4dp)
    cls = "CLASS_400"
    for threshold, name in FREIGHT_THRESHOLDS:
        if d >= threshold:
            cls = name
            break
    # Declared-value override: strictly greater than threshold -> one step toward 400.
    if D(declared_value_cents) > VALUE_PER_LB_THRESHOLD_CENTS * D(weight_lb):
        idx = FREIGHT_CLASSES.index(cls)
        cls = FREIGHT_CLASSES[min(idx + 1, len(FREIGHT_CLASSES) - 1)]
    return cls


def freight_charge(method, freight_class, weight_lb, piece_count):
    if method == "LTL":
        base = r0c(D(weight_lb) * D(FREIGHT_RATES_CENTS[freight_class]))
        fuel = r0c(D(base) * FUEL_PCT)
        return base + fuel
    return max(WG_MIN_CENTS, piece_count * WG_PER_PIECE_CENTS) + WG_INSIDE_SURCHARGE_CENTS


def density_4dp(weight_lb, length_in, width_in, height_in):
    volume = D(length_in) * D(width_in) * D(height_in) / D("1728")
    return r4(D(weight_lb) / volume)
