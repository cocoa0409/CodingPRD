"""Domain logic: calculations, state transitions, cascades, serializers."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from common import ApiError, D, TWO_DP, fmt_dt, fmt_ts, num_out
from store import STORE, new_entity, touch

SHAPE_AREA_FACTOR = {
    "RECTANGLE": D("1.0"), "ARCH": D("0.85"), "CIRCLE": D("0.785"), "TRAPEZOID": D("0.9"),
}
GRID_ADDER = {"NONE": 0, "COLONIAL": 4000, "PRAIRIE": 5500, "DIAMOND": 7000}
HARDWARE_ADDER = {"STANDARD": 0, "BRUSHED_NICKEL": 2500, "OIL_RUBBED_BRONZE": 3200}
ARGON_DERATE_PER_PT = D("0.002")
SPACER_DERATE = {"ALUMINUM": D("0.01"), "WARM_EDGE": D("0.0")}
CARRIER_FEE = {"PARCEL": 2500, "STANDARD_FREIGHT": 8000, "EXPEDITED": 15000}
MAX_REMAKES_PER_UNIT = 3
COMPONENT_WINDOW = {"FRAME": 20, "IG_SEAL": 20, "HARDWARE": 10, "GRID": 10, "GLASS": 2}
WHOLE_UNIT_WINDOW = 15

SHAPES = set(SHAPE_AREA_FACTOR)
GRID_STYLES = set(GRID_ADDER)
HARDWARE_FINISHES = set(HARDWARE_ADDER)
FRAME_MATERIALS = {"VINYL", "WOOD", "ALUMINUM_CLAD", "FIBERGLASS"}
SPACER_TYPES = {"ALUMINUM", "WARM_EDGE"}
MANUAL_BREAK_CAUSES = {"HANDLING", "LAMINATION_DEFECT", "SEAL_FAILURE", "SHIPPING_DAMAGE"}
COMPONENTS = {"FRAME", "IG_SEAL", "GLASS", "HARDWARE", "GRID"}
COVERAGE_VARIANTS = {"COMPONENT", "WHOLE_UNIT"}
CARRIERS = {"PARCEL", "STANDARD_FREIGHT", "EXPEDITED"}
REMEDIES = {"REPAIR_PART", "REFUND"}
CLAIM_ACTIVE_STATUSES = {"SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "APPROVED"}
IG_IN_FLIGHT = {"QUEUED", "GLASS_CUT", "SEALED", "GAS_FILLED"}
LINE_COUNTED_STATUSES = {"RELEASED", "IN_PRODUCTION", "COMPLETED"}


# ------------------------------------------------------------------ lookups

def get_or_404(table, key):
    e = table.get(key)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced resource does not exist")
    return e


def lines_of_order(order_id):
    return [l for l in STORE.lines.values() if l["order_id"] == order_id]


def live_lines(order_id):
    return [l for l in lines_of_order(order_id) if l["status"] != "CANCELLED"]


def label_of_line(line_id):
    for lab in STORE.labels.values():
        if lab["order_line_id"] == line_id:
            return lab
    return None


def units_of_line(line_id):
    return [u for u in STORE.ig_units.values() if u["order_line_id"] == line_id]


# ------------------------------------------------------------------ line pricing

def compute_line_fields(line, series, gp):
    w = D(line["width_in"])
    h = D(line["height_in"])
    ui = w + h
    glazing = (w * h / D(144) * SHAPE_AREA_FACTOR[line["shape"]]).quantize(
        TWO_DP, rounding=ROUND_HALF_UP)
    billable = max(glazing, D(series["min_billable_sqft"]))
    if line["shape"] == "RECTANGLE":
        mult = D(1)
    else:
        mult = D(1) + D(series["special_shape_upcharge_pct"]) / D(100)
    per_unit = (
        ui * D(series["base_rate_cents_per_ui"]) * mult
        + billable * D(gp["price_per_sqft_cents"])
        + D(GRID_ADDER[line["grid_style"]])
        + D(HARDWARE_ADDER[line["hardware_finish"]])
    )
    total = int((per_unit * D(line["quantity"])).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    line["united_inches"] = ui
    line["glazing_sqft"] = glazing
    line["billable_sqft"] = billable
    line["lead_time_days"] = (series["lead_time_special_shape_days"]
                              if line["shape"] != "RECTANGLE"
                              else series["lead_time_standard_days"])
    line["line_total_cents"] = total


def order_recompute(order, do_touch=True):
    """Recompute subtotal/discount/total and promised_date from non-CANCELLED lines."""
    lines = live_lines(order["id"])
    subtotal = sum(l["line_total_cents"] for l in lines)
    if subtotal >= 5_000_000:
        pct = D("0.12")
    elif subtotal >= 2_000_000:
        pct = D("0.08")
    elif subtotal >= 500_000:
        pct = D("0.05")
    else:
        pct = D("0")
    discount = int((D(subtotal) * pct).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    order["subtotal_cents"] = subtotal
    order["discount_cents"] = discount
    order["total_price_cents"] = subtotal - discount
    if lines:
        order["promised_date"] = order["order_date"] + timedelta(
            days=max(l["lead_time_days"] for l in lines))
    else:
        order["promised_date"] = None
    if do_touch:
        touch(order)


# ------------------------------------------------------------------ energy labels

def select_rule(state_code, when):
    cands = [r for r in STORE.energy_rules.values()
             if r["state_code"] == state_code
             and r["effective_from"] <= when
             and (r["effective_to"] is None or when < r["effective_to"])]
    cands.sort(key=lambda r: r["_seq"])
    return cands[0] if cands else None


def eval_compliance(u_factor, shgc, rule):
    if rule is None:
        return "UNEVALUATED"
    if D(u_factor) <= D(rule["max_u_factor"]) and D(shgc) <= D(rule["max_shgc"]):
        return "PASS"
    return "FAIL"


def label_recalc_provisional(label, line, order, gp, do_touch=False, initial=False):
    rule = select_rule(order["ship_to_state_code"], order["order_date"])
    before = (label["basis"], label["status"], label["u_factor"], label["shgc"],
              label["applied_energy_code_rule_id"], label["compliance"])
    label["basis"] = "PROVISIONAL"
    label["status"] = "PROVISIONAL"
    label["u_factor"] = D(gp["catalog_u_factor"])
    label["shgc"] = D(gp["catalog_shgc"])
    label["applied_energy_code_rule_id"] = rule["id"] if rule else None
    label["compliance"] = eval_compliance(label["u_factor"], label["shgc"], rule)
    after = (label["basis"], label["status"], label["u_factor"], label["shgc"],
             label["applied_energy_code_rule_id"], label["compliance"])
    if not initial and (do_touch or before != after):
        touch(label)


def certified_u_factor(catalog_u, argon_target_pct, argon_measured_pct, spacer_type):
    return (D(catalog_u)
            + D(argon_target_pct - argon_measured_pct) * ARGON_DERATE_PER_PT
            + SPACER_DERATE[spacer_type]).quantize(TWO_DP, rounding=ROUND_HALF_UP)


def label_certify(label, line, gp):
    passed = [u for u in units_of_line(line["id"]) if u["status"] == "QC_PASSED"]
    worst = min(u["argon_measured_pct"] for u in passed)
    u_c = certified_u_factor(gp["catalog_u_factor"], gp["argon_target_pct"], worst,
                             gp["spacer_type"])
    label["basis"] = "CERTIFIED"
    label["status"] = "CERTIFIED"
    label["u_factor"] = u_c
    label["shgc"] = D(gp["catalog_shgc"])
    rule = STORE.energy_rules.get(label["applied_energy_code_rule_id"]) \
        if label["applied_energy_code_rule_id"] else None
    label["compliance"] = eval_compliance(u_c, label["shgc"], rule)
    touch(label)


# ------------------------------------------------------------------ waves

def wave_counted_lines(wave):
    out = []
    for l in STORE.lines.values():
        o = STORE.orders.get(l["order_id"])
        if o and o["wave_id"] == wave["id"] and l["status"] in LINE_COUNTED_STATUSES:
            out.append(l)
    return out


def wave_allocation(wave, extra_lines=None, exclude_line_ids=None):
    """Raw (unrounded-sum) allocation over counted lines plus prospective extras."""
    exclude_line_ids = exclude_line_ids or set()
    units = 0
    glass = D(0)
    for l in wave_counted_lines(wave):
        if l["id"] in exclude_line_ids:
            continue
        units += l["quantity"]
        glass += D(l["glazing_sqft"]) * D(l["quantity"])
    for l in (extra_lines or []):
        units += l["quantity"]
        glass += D(l["glazing_sqft"]) * D(l["quantity"])
    return units, glass.quantize(TWO_DP, rounding=ROUND_HALF_UP)


def wave_recompute(wave):
    units, glass = wave_allocation(wave)
    changed = (units != wave["allocated_units"]) or (glass != D(wave["allocated_glass_sqft"]))
    wave["allocated_units"] = units
    wave["allocated_glass_sqft"] = glass
    # Auto-unlock: downward recompute leaving a LOCKED/RELEASED wave under half capacity.
    if wave["status"] in ("LOCKED", "RELEASED") and units < (wave["capacity_units"] + 1) // 2:
        wave["status"] = "OPEN"
        changed = True
    if changed:
        touch(wave)


# ------------------------------------------------------------------ racks

def rack_recompute(rack):
    active = any(r["rack_id"] == rack["id"] and r["status"] in ("RESERVED", "LOADING")
                 for r in STORE.reservations.values())
    st = "BOOKED" if active else "AVAILABLE"
    if st != rack["status"]:
        rack["status"] = st
        touch(rack)


# ------------------------------------------------------------------ cascades

def transition_line(line, status):
    line["status"] = status
    touch(line)


def transition_order(order, status):
    order["production_status"] = status
    touch(order)


def order_completion_check(order):
    """Bubble-up: all non-CANCELLED lines COMPLETED -> order COMPLETED + CERTIFIED."""
    if order["production_status"] != "IN_PROGRESS":
        return
    lines = live_lines(order["id"])
    if lines and all(l["status"] == "COMPLETED" for l in lines):
        order["production_status"] = "COMPLETED"
        order["compliance_status"] = "CERTIFIED"
        touch(order)


def line_completion_check(line):
    """Bubble-up: no in-flight units left -> line COMPLETED, label certifies."""
    if line["status"] != "IN_PRODUCTION":
        return
    units = units_of_line(line["id"])
    if any(u["status"] in IG_IN_FLIGHT for u in units):
        return
    line["status"] = "COMPLETED"
    touch(line)
    gp = STORE.glass_packages.get(line["glass_package_id"])
    label = label_of_line(line["id"])
    if label and gp:
        label_certify(label, line, gp)
    order = STORE.orders.get(line["order_id"])
    if order:
        order_completion_check(order)


def remake_depth(unit):
    depth = 0
    cur = unit
    while cur.get("remake_of_id"):
        parent = STORE.ig_units.get(cur["remake_of_id"])
        if parent is None:
            break
        depth += 1
        cur = parent
    return depth


def break_unit(unit, cause, measured=None):
    """Shared three-hop breakage cascade: BROKEN + auto-remake, GLASS_HOLD, wave release.

    Atomic: the remake-limit check runs before any mutation.
    """
    if remake_depth(unit) + 1 > MAX_REMAKES_PER_UNIT:
        raise ApiError("ERR_REMAKE_LIMIT_EXCEEDED", 409,
                       "Remake chain limit (3) reached for this unit")
    if measured is not None:
        unit["argon_measured_pct"] = measured
    unit["status"] = "BROKEN"
    unit["break_cause"] = cause
    touch(unit)
    # Auto-remake: replacement starts at QUEUED pointing at the broken unit.
    remake = new_entity({
        "order_line_id": unit["order_line_id"],
        "unit_index": unit["unit_index"],
        "remake_of_id": unit["id"],
        "spacer_type": unit["spacer_type"],
        "argon_measured_pct": None,
        "break_cause": None,
        "status": "QUEUED",
    })
    STORE.ig_units[remake["id"]] = remake
    line = STORE.lines.get(unit["order_line_id"])
    if line and line["status"] == "IN_PRODUCTION":
        line["status"] = "GLASS_HOLD"
        touch(line)
        order = STORE.orders.get(line["order_id"])
        if order and order["wave_id"]:
            wave = STORE.waves.get(order["wave_id"])
            if wave:
                wave_recompute(wave)
    return unit


def cancel_order_cascade(order, role):
    st = order["production_status"]
    if st == "IN_PROGRESS" and role != "PlantManager":
        raise ApiError("ERR_FORBIDDEN_ROLE", 403,
                       "Only PlantManager may cancel an IN_PROGRESS order")
    if st not in ("DRAFT", "CONFIRMED", "RELEASED", "IN_PROGRESS"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Order in {st} cannot be cancelled")
    for line in lines_of_order(order["id"]):
        if st == "DRAFT" and line["status"] == "PENDING":
            transition_line(line, "CANCELLED")
        elif st == "CONFIRMED" and line["status"] == "CONFIRMED":
            transition_line(line, "CANCELLED")
        elif st == "RELEASED" and line["status"] == "RELEASED":
            transition_line(line, "CANCELLED")
        elif st == "IN_PROGRESS" and line["status"] in ("IN_PRODUCTION", "GLASS_HOLD"):
            transition_line(line, "CANCELLED")
            for unit in units_of_line(line["id"]):
                if unit["status"] in IG_IN_FLIGHT:
                    unit["status"] = "SCRAPPED"
                    touch(unit)
    if st in ("RELEASED", "IN_PROGRESS") and order["wave_id"]:
        wave = STORE.waves.get(order["wave_id"])
        order["wave_id"] = None
        if wave:
            wave_recompute(wave)
    order["production_status"] = "CANCELLED"
    order_recompute(order, do_touch=True)


# ------------------------------------------------------------------ warranty coverage

def coverage_pct_for(claim, order, line):
    delivered = order["delivered_at"]
    failure = claim["failure_date"]
    years = (failure - delivered).days // 365
    if years < 0:
        years = 0
    if claim["coverage_variant"] == "WHOLE_UNIT":
        if years >= WHOLE_UNIT_WINDOW:
            return 0
        if years < 5:
            return 100
        return max(0, 100 - 20 * (years - 5))
    component = claim["component"]
    if component == "FRAME":
        window = STORE.series[line["series_id"]]["frame_warranty_years"]
        if years >= window:
            return 0
        if years < 10:
            return 100
        return max(0, 100 - 10 * (years - 10))
    if component == "IG_SEAL":
        window = STORE.glass_packages[line["glass_package_id"]]["ig_warranty_years"]
        if years >= window:
            return 0
        if years < 10:
            return 100
        return max(0, 100 - 10 * (years - 10))
    if component in ("HARDWARE", "GRID"):
        return 100 if years < COMPONENT_WINDOW[component] else 0
    # GLASS
    return 100 if years < COMPONENT_WINDOW["GLASS"] else 0


# ------------------------------------------------------------------ serializers

def ser_dealer(d):
    return {
        "id": d["id"], "name": d["name"], "ship_to_state_code": d["ship_to_state_code"],
        "credit_status": d["credit_status"],
        "created_at": fmt_ts(d["created_at"]), "updated_at": fmt_ts(d["updated_at"]),
        "version": d["version"],
    }


def ser_series(s):
    return {
        "id": s["id"], "series_code": s["series_code"], "frame_material": s["frame_material"],
        "base_rate_cents_per_ui": s["base_rate_cents_per_ui"],
        "min_billable_sqft": num_out(s["min_billable_sqft"]),
        "max_united_inches": s["max_united_inches"],
        "special_shape_upcharge_pct": s["special_shape_upcharge_pct"],
        "lead_time_standard_days": s["lead_time_standard_days"],
        "lead_time_special_shape_days": s["lead_time_special_shape_days"],
        "frame_warranty_years": s["frame_warranty_years"], "status": s["status"],
        "created_at": fmt_ts(s["created_at"]), "updated_at": fmt_ts(s["updated_at"]),
        "version": s["version"],
    }


def ser_glass(gp):
    return {
        "id": gp["id"], "code": gp["code"], "pane_count": gp["pane_count"],
        "spacer_type": gp["spacer_type"], "argon_target_pct": gp["argon_target_pct"],
        "argon_min_pct": gp["argon_min_pct"],
        "catalog_u_factor": num_out(gp["catalog_u_factor"]),
        "catalog_shgc": num_out(gp["catalog_shgc"]),
        "price_per_sqft_cents": gp["price_per_sqft_cents"],
        "ig_warranty_years": gp["ig_warranty_years"],
        "created_at": fmt_ts(gp["created_at"]), "updated_at": fmt_ts(gp["updated_at"]),
        "version": gp["version"],
    }


def ser_rule(r):
    return {
        "id": r["id"], "state_code": r["state_code"],
        "max_u_factor": num_out(r["max_u_factor"]), "max_shgc": num_out(r["max_shgc"]),
        "effective_from": fmt_dt(r["effective_from"]),
        "effective_to": fmt_dt(r["effective_to"]),
        "created_at": fmt_ts(r["created_at"]), "updated_at": fmt_ts(r["updated_at"]),
        "version": r["version"],
    }


def ser_order(o):
    return {
        "id": o["id"], "dealer_id": o["dealer_id"],
        "ship_to_state_code": o["ship_to_state_code"],
        "order_date": fmt_dt(o["order_date"]),
        "production_status": o["production_status"],
        "compliance_status": o["compliance_status"],
        "wave_id": o["wave_id"],
        "promised_date": fmt_dt(o["promised_date"]),
        "subtotal_cents": o["subtotal_cents"], "discount_cents": o["discount_cents"],
        "total_price_cents": o["total_price_cents"],
        "delivered_at": fmt_dt(o["delivered_at"]),
        "created_at": fmt_ts(o["created_at"]), "updated_at": fmt_ts(o["updated_at"]),
        "version": o["version"],
    }


def ser_line(l):
    return {
        "id": l["id"], "order_id": l["order_id"], "series_id": l["series_id"],
        "glass_package_id": l["glass_package_id"], "shape": l["shape"],
        "width_in": num_out(l["width_in"]), "height_in": num_out(l["height_in"]),
        "quantity": l["quantity"], "grid_style": l["grid_style"],
        "hardware_finish": l["hardware_finish"],
        "united_inches": num_out(l["united_inches"]),
        "glazing_sqft": num_out(l["glazing_sqft"]),
        "billable_sqft": num_out(l["billable_sqft"]),
        "lead_time_days": l["lead_time_days"],
        "line_total_cents": l["line_total_cents"],
        "status": l["status"], "rack_id": l["rack_id"],
        "created_at": fmt_ts(l["created_at"]), "updated_at": fmt_ts(l["updated_at"]),
        "version": l["version"],
    }


def ser_label(e):
    return {
        "id": e["id"], "order_line_id": e["order_line_id"], "basis": e["basis"],
        "u_factor": num_out(e["u_factor"]), "shgc": num_out(e["shgc"]),
        "applied_energy_code_rule_id": e["applied_energy_code_rule_id"],
        "compliance": e["compliance"], "status": e["status"],
        "created_at": fmt_ts(e["created_at"]), "updated_at": fmt_ts(e["updated_at"]),
        "version": e["version"],
    }


def ser_ig(u):
    return {
        "id": u["id"], "order_line_id": u["order_line_id"], "unit_index": u["unit_index"],
        "remake_of_id": u["remake_of_id"], "spacer_type": u["spacer_type"],
        "argon_measured_pct": u["argon_measured_pct"], "break_cause": u["break_cause"],
        "status": u["status"],
        "created_at": fmt_ts(u["created_at"]), "updated_at": fmt_ts(u["updated_at"]),
        "version": u["version"],
    }


def ser_wave(w):
    return {
        "id": w["id"], "wave_date": fmt_dt(w["wave_date"]),
        "capacity_units": w["capacity_units"],
        "capacity_glass_sqft": num_out(w["capacity_glass_sqft"]),
        "allocated_units": w["allocated_units"],
        "allocated_glass_sqft": num_out(w["allocated_glass_sqft"]),
        "status": w["status"],
        "created_at": fmt_ts(w["created_at"]), "updated_at": fmt_ts(w["updated_at"]),
        "version": w["version"],
    }


def ser_rack(r):
    return {
        "id": r["id"], "rack_code": r["rack_code"], "slot_capacity": r["slot_capacity"],
        "status": r["status"],
        "created_at": fmt_ts(r["created_at"]), "updated_at": fmt_ts(r["updated_at"]),
        "version": r["version"],
    }


def ser_resv(r):
    return {
        "id": r["id"], "rack_id": r["rack_id"], "order_id": r["order_id"],
        "load_date": fmt_dt(r["load_date"]), "ship_date": fmt_dt(r["ship_date"]),
        "assigned_units": r["assigned_units"], "status": r["status"],
        "created_at": fmt_ts(r["created_at"]), "updated_at": fmt_ts(r["updated_at"]),
        "version": r["version"],
    }


def ser_claim(c):
    return {
        "id": c["id"], "order_id": c["order_id"], "order_line_id": c["order_line_id"],
        "component": c["component"], "coverage_variant": c["coverage_variant"],
        "failure_date": fmt_dt(c["failure_date"]), "description": c["description"],
        "coverage_pct": c["coverage_pct"], "remedy": c["remedy"],
        "remedy_value_cents": c["remedy_value_cents"], "status": c["status"],
        "denial_reason": c["denial_reason"],
        "created_at": fmt_ts(c["created_at"]), "updated_at": fmt_ts(c["updated_at"]),
        "version": c["version"],
    }


def ser_shipment(s):
    return {
        "id": s["id"], "warranty_claim_id": s["warranty_claim_id"],
        "part_sku": s["part_sku"], "quantity": s["quantity"], "carrier": s["carrier"],
        "shipping_charge_cents": s["shipping_charge_cents"], "status": s["status"],
        "created_at": fmt_ts(s["created_at"]), "updated_at": fmt_ts(s["updated_at"]),
        "version": s["version"],
    }
