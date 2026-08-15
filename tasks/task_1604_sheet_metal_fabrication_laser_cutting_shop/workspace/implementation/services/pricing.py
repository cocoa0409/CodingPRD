"""Quote line pricing pipeline (QUOTED and COMMITTED variants) and quote rollups."""
import math
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

import db
from db import store, new_id, touch, new_common
from errors import ApiError
from services.audit import audit

# pinned constants
BASE_CUT_OVERHEAD_SEC = Decimal("8.0")
CUT_SPEED_SEC_PER_MM = Decimal("0.045")
PIERCE_SEC = Decimal("1.2")
TIER_RATE_STEP = Decimal("0.20")
BEND_UNIT_CENTS = 150
POWDER_CENTS_PER_CM2 = Decimal("0.040")
PLATING_CENTS_PER_CM2 = Decimal("0.060")
ANODIZE_CENTS_PER_CM2 = Decimal("0.055")
SETUP_FEE_PER_LINE = 900
MIN_BILLABLE_AREA_CM2 = Decimal("300")
EXPEDITE_MULT = {"STANDARD": Decimal("1.00"), "EXPEDITE": Decimal("1.25"), "RUSH": Decimal("1.50")}
FINISH_ENUM = ["NONE", "POWDER", "PLATING", "ANODIZING"]
QUOTE_VALIDITY_DAYS = 14


def dec(value):
    return Decimal(str(value))


def rhu(value, places=0):
    """round-half-up to the given number of decimal places; returns Decimal."""
    quantum = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


def money(value):
    return int(rhu(value, 0))


def part_area_cm2(spec):
    """bbox area in cm^2 (exact: integer mm^2 / 100)."""
    return Decimal(spec["bbox_width_mm"] * spec["bbox_height_mm"]) / Decimal(100)


def resolve_grade(grade_id):
    grade = store.material_grades.get(grade_id)
    if grade is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced grade_id does not exist")
    return grade


def resolve_tier(grade, thickness_mm):
    """Smallest index whose max_thickness_mm >= thickness; else 422 tier error."""
    for i, tier in enumerate(grade["thickness_tiers"]):
        if thickness_mm <= dec(tier["max_thickness_mm"]):
            return tier.get("tier_index", i), i
    raise ApiError("ERR_THICKNESS_TIER_UNRESOLVED", 422,
                   "thickness_mm exceeds every tier's max_thickness_mm")


def select_vendor(processes):
    """ACTIVE vendor of a matching process; lowest base cost, tie earliest created."""
    if isinstance(processes, str):
        processes = {processes}
    else:
        processes = set(processes)
    candidates = [v for v in store.outside_vendors.values()
                  if v["process"] in processes and v["status"] == "ACTIVE"]
    if not candidates:
        return None
    candidates.sort(key=lambda v: (v["base_cost_cents_per_part"], v["created_at"], v["_seq"]))
    return candidates[0]


def qty_discount_pct(qty):
    if qty >= 50:
        return Decimal("0.12")
    if qty >= 20:
        return Decimal("0.08")
    if qty >= 10:
        return Decimal("0.04")
    return Decimal("0")


def compute_line_numbers(grade, tier_index, spec, expedite_tier, material_cents):
    """Steps 2-9 of the pinned pipeline. material_cents is the per-part material figure
    for the variant in force. finish cost follows the pinned qty-inside construction."""
    w = spec["bbox_width_mm"]
    h = spec["bbox_height_mm"]
    holes = spec.get("hole_count", 0)
    hole_dia = dec(spec.get("hole_diameter_mm", 20))
    fillets = spec.get("corner_fillet_count", 0)
    bends = spec.get("bend_count", 0)
    finish = spec.get("finish", "NONE")
    qty = spec["qty"]

    # step 2: cut geometry
    cut_length_mm = Decimal(2 * (w + h)) + Decimal(holes) * Decimal(str(math.pi)) * hole_dia
    pierce_count = holes + fillets + 1
    est = BASE_CUT_OVERHEAD_SEC + CUT_SPEED_SEC_PER_MM * cut_length_mm + PIERCE_SEC * pierce_count
    cut_seconds_est = rhu(est, 3)
    billed_cut_seconds = int(cut_seconds_est.to_integral_value(rounding=ROUND_CEILING))

    # step 3: cut cost
    cut_rate = (dec(grade["base_cut_rate_cents_per_sec"])
                * (Decimal(1) + TIER_RATE_STEP * tier_index)
                * dec(grade["hardness_factor"]))
    cut_cost_cents = money(billed_cut_seconds * cut_rate)

    # step 4: bends
    thickness_class = 1 if tier_index == 0 else (2 if tier_index == 1 else 3)
    complexity_class = 1 if fillets >= 4 else 0
    bend_units = bends * (1 + thickness_class + complexity_class)
    bend_cost_cents = bend_units * BEND_UNIT_CENTS

    # step 5: finish (qty multiplied inside, per the pinned formula)
    area = part_area_cm2(spec)
    if finish == "NONE":
        finish_cost_cents = 0
    elif finish == "POWDER":
        finish_cost_cents = qty * money(area * POWDER_CENTS_PER_CM2)
    elif finish == "PLATING":
        vendor = select_vendor("PLATING")
        finish_cost_cents = qty * money(area * PLATING_CENTS_PER_CM2) + vendor["base_cost_cents_per_part"] * qty
    else:  # ANODIZING
        vendor = select_vendor("ANODIZING")
        finish_cost_cents = qty * money(area * ANODIZE_CENTS_PER_CM2) + vendor["base_cost_cents_per_part"] * qty

    # step 7: per-part base (material_cents is per part; finish is qty-inside per the spec)
    line_base_cents = cut_cost_cents + bend_cost_cents + finish_cost_cents + material_cents + SETUP_FEE_PER_LINE

    # step 8: quantity discount (inclusive tiers, top-down)
    discount = qty_discount_pct(qty)
    net_cents = money(line_base_cents * (Decimal(1) - discount))

    # step 9: expedite multiplier on the discounted net
    line_total_cents = money(net_cents * EXPEDITE_MULT[expedite_tier])

    return {
        "cut_seconds_est": float(cut_seconds_est),
        "billed_cut_seconds": billed_cut_seconds,
        "bend_units": bend_units,
        "finish_cost_cents": finish_cost_cents,
        "material_cost_cents": material_cents,
        "line_base_cents": line_base_cents,
        "qty_discount_pct": float(discount),
        "line_total_cents": line_total_cents,
        "_net_cents": net_cents,
    }


def validate_line(quote, spec):
    """Structural (tier 7) then compatibility (tier 8) checks for one line spec."""
    grade = store.material_grades.get(spec["grade_id"])
    if grade is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced grade_id does not exist")
    # structural
    if spec["bbox_width_mm"] <= 0 or spec["bbox_height_mm"] <= 0:
        raise ApiError("ERR_INVALID_LINE_SPEC", 422, "Bounding-box dimensions must be positive")
    if spec["qty"] < 1:
        raise ApiError("ERR_INVALID_LINE_SPEC", 422, "qty must be at least 1")
    for f in ("hole_count", "corner_fillet_count", "bend_count"):
        if spec.get(f, 0) < 0:
            raise ApiError("ERR_INVALID_LINE_SPEC", 422, "%s must be non-negative" % f)
    if spec.get("weld_inches", 0) < 0:
        raise ApiError("ERR_INVALID_LINE_SPEC", 422, "weld_inches must be non-negative")
    finish = spec.get("finish", "NONE")
    if finish not in FINISH_ENUM:
        raise ApiError("ERR_INVALID_LINE_SPEC", 422,
                       "finish must be one of NONE, POWDER, PLATING, ANODIZING")
    thickness = dec(spec["thickness_mm"])
    resolve_tier(grade, thickness)
    # compatibility
    if finish == "POWDER" and not grade["powder_compatible"]:
        raise ApiError("ERR_FINISH_NOT_COMPATIBLE", 422, "POWDER finish on powder-incompatible grade")
    if spec.get("weld_inches", 0) > 0 and not grade["weld_compatible"]:
        raise ApiError("ERR_FINISH_NOT_COMPATIBLE", 422, "Weld routing on weld-incompatible grade")
    if finish in ("PLATING", "ANODIZING") and select_vendor(finish) is None:
        raise ApiError("ERR_FINISH_NOT_COMPATIBLE", 422,
                       "No ACTIVE outside vendor for process %s" % finish)


def _quoted_material_cents(grade, spec):
    """QUOTED variant: per-part minimum-billing estimate, no nesting knowledge."""
    area = part_area_cm2(spec)
    return money(max(area, MIN_BILLABLE_AREA_CM2) * dec(grade["material_cost_cents_per_cm2"]))


def add_line(quote, spec, status="ESTIMATED"):
    grade = resolve_grade(spec["grade_id"])
    validate_line(quote, spec)
    thickness = dec(spec["thickness_mm"])
    tier_index, _ = resolve_tier(grade, thickness)
    material = _quoted_material_cents(grade, spec)
    numbers = compute_line_numbers(grade, tier_index, spec, quote["expedite_tier"], material)
    line = {
        "id": new_id(),
        "quote_id": quote["id"],
        "grade_id": grade["id"],
        "thickness_mm": spec["thickness_mm"],
        "bbox_width_mm": spec["bbox_width_mm"],
        "bbox_height_mm": spec["bbox_height_mm"],
        "hole_count": spec.get("hole_count", 0),
        "hole_diameter_mm": spec.get("hole_diameter_mm", 20),
        "corner_fillet_count": spec.get("corner_fillet_count", 0),
        "bend_count": spec.get("bend_count", 0),
        "weld_inches": spec.get("weld_inches", 0),
        "finish": spec.get("finish", "NONE"),
        "qty": spec["qty"],
        "thickness_tier_index": tier_index,
        "status": status,
    }
    line.update(numbers)
    new_common(line)
    store.quote_lines[line["id"]] = line
    return line


def quote_lines(quote_id):
    rows = [l for l in store.quote_lines.values() if l["quote_id"] == quote_id]
    rows.sort(key=lambda l: (l["created_at"], l["_seq"]))
    return rows


def reprice_line(quote, line):
    """Re-run the pinned pipeline for one line under the QUOTED variant."""
    grade = resolve_grade(line["grade_id"])
    spec = {k: line[k] for k in (
        "grade_id", "thickness_mm", "bbox_width_mm", "bbox_height_mm", "hole_count",
        "hole_diameter_mm", "corner_fillet_count", "bend_count", "weld_inches", "finish", "qty")}
    tier_index, _ = resolve_tier(grade, dec(line["thickness_mm"]))
    material = _quoted_material_cents(grade, spec)
    numbers = compute_line_numbers(grade, tier_index, spec, quote["expedite_tier"], material)
    line["thickness_tier_index"] = tier_index
    line.update(numbers)
    touch(line)


def recompute_quote_totals(quote):
    lines = quote_lines(quote["id"])
    subtotal = sum(l["_net_cents"] * l["qty"] for l in lines)
    expedite = sum((l["line_total_cents"] - l["_net_cents"]) * l["qty"] for l in lines)
    total = sum(l["line_total_cents"] * l["qty"] for l in lines)
    quote["quoted_subtotal_cents"] = subtotal
    quote["quoted_expedite_cents"] = expedite
    quote["quoted_total_cents"] = total


def recompute_committed(order, lines):
    """COMMITTED variant: order-level plate cost apportioned per line by chargeable
    area (largest remainder, area desc, ties by line created_at ASC), then the pinned
    pipeline is rebuilt per part."""
    sheets = [ns for ns in store.nest_sheets.values() if ns["order_id"] == order["id"]]
    by_grade = {}
    for ln in lines:
        by_grade.setdefault(ln["grade_id"], []).append(ln)

    for grade_id, glines in by_grade.items():
        grade = store.material_grades[grade_id]
        grade_area = sum((dec(ns["plate_in_area_cm2"]) for ns in sheets
                          if store.sheet_stock[ns["sheet_stock_id"]]["grade_id"] == grade_id),
                         Decimal(0))
        grade_cost = money(grade_area * dec(grade["material_cost_cents_per_cm2"]))
        areas = [(ln, part_area_cm2(ln) * ln["qty"]) for ln in glines]
        total_area = sum((a for _, a in areas), Decimal(0))
        shares = {}
        if total_area > 0 and grade_cost > 0:
            quotas = [(ln, Decimal(grade_cost) * a / total_area) for ln, a in areas]
            floors = {id(ln): int(q.to_integral_value(rounding="ROUND_FLOOR")) for ln, q in quotas}
            leftover = grade_cost - sum(floors.values())
            ranked = sorted(areas, key=lambda t: (-t[1], t[0]["created_at"], t[0]["_seq"]))
            for k in range(leftover):
                floors[id(ranked[k % len(ranked)][0])] += 1
            for ln, _ in areas:
                shares[ln["id"]] = floors[id(ln)]
        else:
            for ln, _ in areas:
                shares[ln["id"]] = 0
        for ln in glines:
            per_part_material = money(Decimal(shares[ln["id"]]) / Decimal(ln["qty"]))
            spec = {k: ln[k] for k in (
                "grade_id", "thickness_mm", "bbox_width_mm", "bbox_height_mm", "hole_count",
                "hole_diameter_mm", "corner_fillet_count", "bend_count", "weld_inches",
                "finish", "qty")}
            numbers = compute_line_numbers(grade, ln["thickness_tier_index"], spec,
                                           order["expedite_tier"], per_part_material)
            ln.update(numbers)
            touch(ln)

    order["committed_subtotal_cents"] = sum(l["line_base_cents"] * l["qty"] for l in lines)
    order["committed_total_cents"] = sum(l["line_total_cents"] * l["qty"] for l in lines)


def run_expiry_sweep():
    """Lazy quote expiry: SUBMITTED quotes with expires_at <= logical clock, processed
    in expires_at ASC order, ties by created_at ASC. Actor is the literal 'system'."""
    now = db.LOGICAL_CLOCK
    due = [q for q in store.quotes.values()
           if q["status"] == "SUBMITTED" and q.get("_expires_dt") is not None
           and q["_expires_dt"] <= now]
    due.sort(key=lambda q: (q["_expires_dt"], q["created_at"], q["_seq"]))
    for q in due:
        q["status"] = "EXPIRED"
        touch(q)
        for line in quote_lines(q["id"]):
            if line["status"] in ("ESTIMATED", "PRICED"):
                line["status"] = "SUPERSEDED"
                touch(line)
        audit("Quote", q["id"], "QUOTE_EXPIRED", "system", "system",
              {"before": {"status": "SUBMITTED"}, "after": {"status": "EXPIRED"}})
