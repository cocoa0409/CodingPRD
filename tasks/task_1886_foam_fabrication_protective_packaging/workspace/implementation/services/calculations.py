"""Calculation rules per scaffold §1.3 / PRD §3. All money is integer cents;
intermediate components carry full Decimal precision with no intermediate
rounding; round-half-up wherever a rounded value is stored (PRD §2.6)."""
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

import db
import errors
from errors import ApiError

# --- Constants (scaffold §1.3) ---------------------------------------------
KERF = Decimal("0.25")
PROVISIONAL_YIELD_PCT = Decimal("0.70")
DIE_CUT_PART_COST_CENTS = 25
MACHINE_RATE_CENTS_PER_SEC = 3
SETUP_FEE_DIE_CENTS = 5000
SETUP_FEE_CNC_CENTS = 15000
SCRAP_BONUS_THRESHOLD_LB = Decimal("500")
SCRAP_BONUS_MULT = Decimal("1.25")

_LOW_FACTOR = 8
_MEDIUM_FACTOR = 10
_HIGH_FACTOR = 12


def D(x):
    """Exact Decimal from a JSON number (str() avoids float binary noise)."""
    return Decimal(str(x))


def rhu(x, places):
    """Round half-up to the given number of decimal places."""
    return x.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def ceil_int(x):
    return int(x.to_integral_value(rounding=ROUND_CEILING))


def floor_int(x):
    return int(x.to_integral_value(rounding=ROUND_FLOOR))


def tier_mult(qty):
    if qty <= 99:
        return Decimal("1.35")
    if qty <= 999:
        return Decimal("1.15")
    return Decimal("1.00")


def setup_fee(method):
    return SETUP_FEE_DIE_CENTS if method == "DIE_CUT" else SETUP_FEE_CNC_CENTS


# ---------------------------------------------------------------------------
# cushion_ild_calc — drop-height banding, band lower edges inclusive.
# ---------------------------------------------------------------------------

def cushion_required_ild(product_weight_lb, required_drop_height_in):
    h = int(required_drop_height_in)
    if h < 24:
        factor = _LOW_FACTOR
    elif h < 48:
        factor = _MEDIUM_FACTOR
    else:
        factor = _HIGH_FACTOR
    return ceil_int(D(product_weight_lb) * factor)


# ---------------------------------------------------------------------------
# nesting_yield_calc — two orientations, quarter-inch kerf, keep the better.
# ---------------------------------------------------------------------------

def nesting_yield(part_length_in, part_width_in, sheet_length_in, sheet_width_in):
    pl, pw = D(part_length_in), D(part_width_in)
    sl, sw = D(sheet_length_in), D(sheet_width_in)
    part_area = pl * pw
    sheet_area = sl * sw
    best = 0
    for a, b in ((pl, pw), (pw, pl)):
        cols = floor_int((sl + KERF) / (a + KERF))
        rows = floor_int((sw + KERF) / (b + KERF))
        best = max(best, cols * rows)
    kerf_waste_sqin = best * KERF * (pl + pw)
    utilization = rhu(Decimal(100) * best * part_area / sheet_area, 2)
    offcut_sqft = rhu((sheet_area - best * part_area - kerf_waste_sqin) / Decimal(144), 2)
    return best, float(utilization), float(offcut_sqft)


def sheet_board_feet(material):
    return rhu(
        D(material["sheet_length_in"])
        * D(material["sheet_width_in"])
        * D(material["sheet_thickness_in"])
        / Decimal(144),
        2,
    )


# ---------------------------------------------------------------------------
# Tooling selection for pricing: prefer IN_SERVICE, then earliest created.
# ---------------------------------------------------------------------------

def toolings_for_program(cut_program_id):
    cands = [t for t in db.toolings.values() if t["cut_program_id"] == cut_program_id]
    cands.sort(key=lambda t: t["_seq"])
    return cands


def in_service_tooling(cut_program_id):
    for t in toolings_for_program(cut_program_id):
        if t["status"] == "IN_SERVICE":
            return t
    return None


def pricing_tooling(cut_program_id):
    svc = in_service_tooling(cut_program_id)
    if svc is not None:
        return svc
    cands = toolings_for_program(cut_program_id)
    return cands[0] if cands else None


# ---------------------------------------------------------------------------
# quote_pricing_calc + order_total_rounding (pinned order: round the unit
# half-up to integer cents FIRST, then multiply by qty, then add setup fee).
# ---------------------------------------------------------------------------

def _unit_price(qty, effective_pps, material, method, machine_seconds_per_part,
                tooling, cost_bf_cents=None, include_amort=True):
    """Returns (unit_price_cents:int, amort_per_part:int). Full precision inside."""
    bf = sheet_board_feet(material)
    sheets_needed = ceil_int(D(qty) / D(effective_pps))
    cost = material["cost_per_board_ft_cents"] if cost_bf_cents is None else cost_bf_cents
    material_per_part = D(sheets_needed) * bf * D(cost) / D(qty)
    if method == "DIE_CUT":
        cutting = Decimal(DIE_CUT_PART_COST_CENTS)
    else:
        cutting = D(machine_seconds_per_part) * MACHINE_RATE_CENTS_PER_SEC
    amort = 0
    if include_amort and method == "DIE_CUT" and tooling is not None:
        remaining = tooling["die_cost_cents"] - tooling["amortized_cents"]
        amort = ceil_int(D(remaining) / D(tooling["amortization_qty"]))
    unit_raw = (material_per_part + cutting + D(amort)) * tier_mult(qty)
    unit = int(rhu(unit_raw, 0))  # step 1 of the pinned rounding order
    return unit, amort


def provisional_pricing(spec, material, program, qty):
    """Provisional variant: assumed yield floor(theoretical_best_nesting * 0.70)."""
    best, _, _ = nesting_yield(
        spec["part_length_in"], spec["part_width_in"],
        material["sheet_length_in"], material["sheet_width_in"],
    )
    effective = floor_int(D(best) * PROVISIONAL_YIELD_PCT)
    if effective < 1:
        effective = 1  # degenerate guard; infeasible geometry cannot be locked anyway
    tooling = pricing_tooling(program["id"]) if program["method"] == "DIE_CUT" else None
    unit, _ = _unit_price(qty, effective, material, program["method"],
                          program.get("machine_seconds_per_part"), tooling)
    total = unit * qty + setup_fee(program["method"])  # setup fee added AFTER, never tiered
    return unit, total


def final_pricing(order, material, program, tooling):
    """Final variant: locked program's actual parts_per_sheet, tooling's current
    remaining unamortized cents. Returns (unit, total, tooling_charge)."""
    unit, amort_per_part = _unit_price(
        order["qty"], program["parts_per_sheet"], material, program["method"],
        program.get("machine_seconds_per_part"), tooling,
    )
    total = unit * order["qty"] + setup_fee(program["method"])
    charge = 0
    if program["method"] == "DIE_CUT" and tooling is not None:
        remaining = tooling["die_cost_cents"] - tooling["amortized_cents"]
        charge = min(remaining, amort_per_part * min(order["qty"], tooling["amortization_qty"]))
    return unit, total, charge


# ---------------------------------------------------------------------------
# Locked cut-program selector (release pricing & replenishment): most recently
# updated, ties broken by earliest created_at — never by identifier.
# ---------------------------------------------------------------------------

def select_locked_cut_program(package_spec_id):
    cands = [
        p for p in db.cut_programs.values()
        if p["package_spec_id"] == package_spec_id and p["status"] == "LOCKED"
    ]
    if not cands:
        return None
    cands.sort(key=lambda p: p["_seq"])          # final deterministic tie-break
    cands.sort(key=lambda p: p["created_at"])    # tie-break: earliest created
    cands.sort(key=lambda p: p["updated_at"], reverse=True)  # primary: most recently updated
    return cands[0]


# ---------------------------------------------------------------------------
# release_pricing_calc — LOCKED variant prices from the pinned cost, CURRENT
# re-reads the material at allocate time; no amortization, no setup fee.
# ---------------------------------------------------------------------------

def release_pricing(release, inv_program, material):
    program = select_locked_cut_program(inv_program["package_spec_id"])
    if program is None:
        raise ApiError(
            errors.ERR_NO_LOCKED_PROGRAM,
            "No LOCKED cut program exists for the program's package spec",
            409,
        )
    if inv_program["pricing_mode"] == "LOCKED":
        cost = inv_program["locked_material_cost_bf_cents"]
    else:
        cost = material["cost_per_board_ft_cents"]
    unit, _ = _unit_price(
        release["qty"], program["parts_per_sheet"], material, program["method"],
        program.get("machine_seconds_per_part"), None,
        cost_bf_cents=cost, include_amort=False,
    )
    return unit, unit * release["qty"]


# ---------------------------------------------------------------------------
# scrap_credit_calc — monthly cumulative volume bonus, sequential evaluation.
# ---------------------------------------------------------------------------

def net_recyclable_lb(gross_weight_lb, contamination_pct):
    return float(rhu(D(gross_weight_lb) * (1 - D(contamination_pct) / Decimal(100)), 2))


def scrap_credit_cents(batch, material):
    now = db.now_dt()
    month = (now.year, now.month)
    cumulative_before = Decimal(0)
    for b in db.scrap_batches.values():
        if b["status"] != "CREDITED" or not b.get("credited_at") or b["id"] == batch["id"]:
            continue
        stamp = b["credited_at"]
        s = stamp[:-1] + "+00:00" if isinstance(stamp, str) and stamp.endswith("Z") else stamp
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if (dt.year, dt.month) == month:
            cumulative_before += D(b["net_recyclable_lb"])
    rate = D(material["scrap_credit_per_lb_cents"])
    if cumulative_before >= SCRAP_BONUS_THRESHOLD_LB:  # exactly 500 lb qualifies (>=)
        rate = rate * SCRAP_BONUS_MULT
    return int(rhu(D(batch["net_recyclable_lb"]) * rate, 0))
