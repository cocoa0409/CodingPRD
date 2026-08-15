"""Calculation rules (SCAFFOLD §1.3 / PRD §2.6, §3). Decimal money math only."""
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

# --- constants (SCAFFOLD calculations[].constants) ---
DIM_DIVISOR_CM3_PER_KG = Decimal("5000")
BF_PER_M2 = Decimal("11")
TARE_KG_PER_BF = Decimal("1.8")
WOOD_RATE_CENTS_PER_BF = 350
INDICATOR_COST = {75: 900, 50: 1200, 25: 1800}
BARRIER_COST = {"NONE": 0, "VCI": 2500, "VACUUM_SEALED": 6000}
HAZMAT_SURCHARGE_CENTS = 4500
TRAVEL_FLAT_CENTS = 15000
RATE_CENTS_PER_HOUR = {"SHOP": 8500, "ONSITE": 12000}
HOURS_PER_M3 = {"SHOP": Decimal("1.5"), "ONSITE": Decimal("2.5")}
CLEARANCE_CM = {"STANDARD": 5, "DELICATE": 10, "HIGHLY_FRAGILE": 15}
SHOCK_INDICATOR_G = {"STANDARD": 75, "DELICATE": 50, "HIGHLY_FRAGILE": 25}
FREIGHT_TIERS = [  # (inclusive floor density, NMFC class)
    (800, "55"), (400, "60"), (200, "65"), (100, "70"),
    (50, "77.5"), (25, "85"), (10, "92.5"),
]
MAX_PAYLOAD_KG = {"20FT": 21770, "40FT": 26780, "40HC": 26680}

_D6 = Decimal("0.000001")
_D2 = Decimal("0.01")
_D0 = Decimal("1")


def _dec(v):
    return Decimal(str(v))


def _ceil_int(x):
    return int(x.quantize(_D0, rounding=ROUND_CEILING))


def _round0(x):
    return int(x.quantize(_D0, rounding=ROUND_HALF_UP))


def _round2(x):
    return x.quantize(_D2, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# item_chargeable_weight
# ---------------------------------------------------------------------------

def item_metrics(length_cm, width_cm, height_cm, weight_kg):
    L, W, H = _dec(length_cm), _dec(width_cm), _dec(height_cm)
    vol = (L * W * H / Decimal(1000000)).quantize(_D6, rounding=ROUND_HALF_UP)
    dim_w = (L * W * H / DIM_DIVISOR_CM3_PER_KG).quantize(_D2, rounding=ROUND_HALF_UP)
    chargeable = max(_dec(weight_kg), dim_w)
    return {
        "volume_m3": float(vol),
        "dimensional_weight_kg": float(dim_w),
        "chargeable_weight_kg": float(chargeable),
    }


# ---------------------------------------------------------------------------
# crate_design_geometry
# ---------------------------------------------------------------------------

def design_geometry(item):
    L, W, H = _dec(item["length_cm"]), _dec(item["width_cm"]), _dec(item["height_cm"])
    weight = _dec(item["weight_kg"])
    clearance = Decimal(CLEARANCE_CM[item["fragile_class"]])
    il, iw, ih = L + 2 * clearance, W + 2 * clearance, H + 2 * clearance
    if weight < 50:
        thickness = Decimal("1.2")
    elif weight < 500:
        thickness = Decimal("1.8")
    else:
        thickness = Decimal("2.5")
    el, ew, eh = il + 2 * thickness, iw + 2 * thickness, ih + 2 * thickness
    area_m2 = 2 * (el * ew + el * eh + ew * eh) / Decimal(10000)
    board_feet = _ceil_int(area_m2 * BF_PER_M2)
    tare = _round2(Decimal(board_feet) * TARE_KG_PER_BF)
    shock = SHOCK_INDICATOR_G[item["fragile_class"]]
    if item["battery_in_equipment"] != "NONE":
        barrier = "VACUUM_SEALED"
    elif item["fragile_class"] != "STANDARD":
        barrier = "VCI"
    else:
        barrier = "NONE"
    return {
        "clearance_cm": float(clearance),
        "internal_l_cm": float(il), "internal_w_cm": float(iw), "internal_h_cm": float(ih),
        "thickness_cm": float(thickness),
        "external_l_cm": float(el), "external_w_cm": float(ew), "external_h_cm": float(eh),
        "board_feet_required": board_feet,
        "tare_weight_kg": float(tare),
        "shock_indicator_g": shock,
        "moisture_barrier_required": barrier,
    }


# ---------------------------------------------------------------------------
# freight_classification
# ---------------------------------------------------------------------------

def crate_metrics(item, design):
    tare = design["tare_weight_kg"]
    gross = _dec(item["weight_kg"]) + _dec(tare)
    vol = (_dec(design["external_l_cm"]) * _dec(design["external_w_cm"])
           * _dec(design["external_h_cm"]) / Decimal(1000000)).quantize(_D6, rounding=ROUND_HALF_UP)
    density = (gross / vol).quantize(_D2, rounding=ROUND_HALF_UP)
    fclass = "125"
    for floor, klass in FREIGHT_TIERS:
        if density >= Decimal(floor):
            fclass = klass
            break
    return {
        "tare_weight_kg": float(_dec(tare)),
        "gross_weight_kg": float(gross),
        "external_volume_m3": float(vol),
        "freight_density_kg_m3": float(density),
        "freight_class": fclass,
    }


def freight_class_of(density):
    d = _dec(density)
    for floor, klass in FREIGHT_TIERS:
        if d >= Decimal(floor):
            return klass
    return "125"


# ---------------------------------------------------------------------------
# Aggregates + job_quote (PROVISIONAL / FINAL)
# ---------------------------------------------------------------------------

def estimated_labor_hours(mode, total_volume_m3):
    return _ceil_int(_dec(total_volume_m3) * HOURS_PER_M3[mode])


def quote(wood_bf_total, mode, est_hours, actual_completed_labor_cents,
          protection_cents, hazmat_item_count, variant):
    """Pinned evaluation order: lines -> subtotal -> handling(on subtotal)
    -> fuel(on subtotal+handling) -> total. Returns full breakdown."""
    wood_cost = wood_bf_total * WOOD_RATE_CENTS_PER_BF
    if wood_bf_total >= 500:
        discount = Decimal("0.10")
    elif wood_bf_total >= 200:
        discount = Decimal("0.05")
    else:
        discount = Decimal("0")
    wood_net = _round0(Decimal(wood_cost) * (Decimal(1) - discount))

    if variant == "FINAL":
        labor = actual_completed_labor_cents
    else:
        labor = est_hours * RATE_CENTS_PER_HOUR[mode]
        if mode == "ONSITE":
            labor += TRAVEL_FLAT_CENTS

    hazmat_cost = HAZMAT_SURCHARGE_CENTS * hazmat_item_count
    subtotal = wood_net + labor + protection_cents + hazmat_cost

    if subtotal >= 2000000:
        pct = Decimal("0.03")
    elif subtotal >= 500000:
        pct = Decimal("0.05")
    else:
        pct = Decimal("0.08")
    handling = _round0(Decimal(subtotal) * pct)
    fuel = _round0(Decimal(subtotal + handling) * Decimal("0.09"))
    total = subtotal + handling + fuel

    return {
        "quoted_price_cents": total,
        "subtotal_cents": subtotal,
        "wood_cost_cents": wood_net,
        "labor_cost_cents": labor,
        "protection_cost_cents": protection_cents,
        "hazmat_cost_cents": hazmat_cost,
        "handling_fee_cents": handling,
        "fuel_surcharge_cents": fuel,
    }


# ---------------------------------------------------------------------------
# invoice_totals (per-line round_half_up BEFORE summation — pinned order)
# ---------------------------------------------------------------------------

def invoice_totals(lines):
    total = 0
    duty = 0
    for ln in lines:
        line_total = _round0(Decimal(ln["qty"]) * Decimal(ln["unit_price_cents"]))
        line_duty = _round0(Decimal(line_total) * Decimal(ln["duty_rate_bp"]) / Decimal(10000))
        total += line_total
        duty += line_duty
    return total, duty


# ---------------------------------------------------------------------------
# claim_settlement (variants by claim_type)
# ---------------------------------------------------------------------------

def claim_approved_amount(claim_type, amount_claimed_cents, declared_value_cents,
                          delivered_at, filed_at):
    days = int((filed_at - delivered_at).total_seconds() // 86400)
    weeks = days // 7
    base = Decimal(declared_value_cents)
    if claim_type in ("IMPACT", "TILT"):
        cap = declared_value_cents
    elif claim_type == "MOISTURE":
        factor = max(Decimal("0.5"), Decimal(1) - Decimal("0.01") * weeks)
        cap = _round0(base * factor)
    else:  # OTHER
        cap = _round0(base * Decimal("0.5"))
    return min(amount_claimed_cents, cap)


# ---------------------------------------------------------------------------
# labor_booking_cost
# ---------------------------------------------------------------------------

def booking_cost(mode, start_at, end_at):
    seconds = Decimal(str((end_at - start_at).total_seconds()))
    hours = (seconds / Decimal(3600)).quantize(_D2, rounding=ROUND_HALF_UP)
    rate = RATE_CENTS_PER_HOUR[mode]
    surcharge = TRAVEL_FLAT_CENTS if mode == "ONSITE" else 0
    total = _round0(hours * Decimal(rate)) + surcharge
    return {
        "hours": float(hours),
        "rate_cents_per_hour": rate,
        "travel_surcharge_cents": surcharge,
        "total_cost_cents": total,
    }
