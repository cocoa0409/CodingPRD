"""Calculation rules (SCAFFOLD table 3 / PRD sections 2.8, 2.10, 3.3-3.9).

All monetary math uses Decimal; every computed line rounds half-up to integer
cents FIRST, then the rounded lines are summed (pinned order). The single
exception is the exchange core-credit cap, which rounds half-down.
"""

from decimal import Decimal, ROUND_HALF_UP, ROUND_HALF_DOWN

from db import DB


# ---------------------------------------------------------------------------
# Shop configuration resolution
# ---------------------------------------------------------------------------

SHOP_DEFAULTS = {
    "labor_rate_cents_per_hour": 14500,
    "expedite_multiplier": 1.35,
    "emergency_multiplier": 1.75,
    "expedite_cutoff_hours": 48,
    "emergency_cutoff_hours": 24,
    "honing_pass_fee_cents": 4000,
    "cut_fee_cents": 1500,
    "kerf_mm": 3,
    "min_remnant_mm": 300,
    "default_chrome_rod_cost_per_mm_cents": 42,
    "default_honing_tube_cost_per_mm_cents": 65,
    "supplies_pct_of_labor": 0.04,
    "cleanliness_target_code4": 18,
    "cleanliness_target_code6": 16,
    "cleanliness_target_code14": 13,
    "quote_ttl_hours": 168,
    "bay_buffer_minutes": 30,
    "loyalty_silver_threshold_cents": 100000,
    "loyalty_gold_threshold_cents": 500000,
    "loyalty_silver_pct": 0.05,
    "loyalty_gold_pct": 0.10,
    "env_fee_pct": 0.02,
    "env_fee_min_cents": 500,
    "callout_base_cents": 25000,
    "emergency_callout_window_hours": 4,
    "emergency_callout_multiplier": 2.0,
    "mileage_free_km": 50,
    "mileage_rate_cents_per_km": 250,
    "crimp_fee_cents": 4500,
    "crimp_tolerance_mm": 0.3,
    "hose_price_wire_braid_2sn_cents_per_m": 3200,
    "hose_price_spiral_4sh_cents_per_m": 5700,
    "hose_price_thermoplastic_cents_per_m": 1800,
    "exchange_credit_cap_pct": 0.30,
    "core_disposal_fee_cents": 7500,
    "core_base_small_cents": 40000,
    "core_base_medium_cents": 90000,
    "core_base_large_cents": 160000,
    "core_bore_medium_max_mm": 100,
    "core_bore_large_max_mm": 200,
    "pressure_test_factor": 1.5,
    "test_hold_min_minutes": 10,
    "rated_pressure_class_3000_psi": 3000,
    "rated_pressure_class_5000_psi": 5000,
}


def current_shop():
    """The shop configuration resource (created once via POST /shops).
    When several exist, the earliest-created governs; when none exists the
    documented defaults apply."""
    if not DB.shops:
        return None
    return min(DB.shops.values(), key=lambda s: (s["created_at"], s["_seq"]))


def shop_config():
    shop = current_shop()
    if shop is None:
        return dict(SHOP_DEFAULTS)
    cfg = dict(SHOP_DEFAULTS)
    for key in SHOP_DEFAULTS:
        if key in shop and shop[key] is not None:
            cfg[key] = shop[key]
    return cfg


# ---------------------------------------------------------------------------
# Rounding helpers
# ---------------------------------------------------------------------------

def dec(value):
    """Exact Decimal from a JSON number (avoids binary float artifacts)."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up_cents(value):
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_down_cents(value):
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_DOWN))


def tier_multiplier(cfg, tier):
    if tier == "EXPEDITE":
        return dec(cfg["expedite_multiplier"])
    if tier == "EMERGENCY":
        return dec(cfg["emergency_multiplier"])
    return Decimal("1.0")


# ---------------------------------------------------------------------------
# 1. quote_pricing (provisional at quote creation; final at work-order close)
# ---------------------------------------------------------------------------

def _quote_lines(cfg, tier, seal_kit_price_cents, rod_line_raw, tube_line_raw,
                 honing_passes, labor_hours, scrap_total_cents=None):
    """Shared line structure. rod_line_raw / tube_line_raw are None when the
    teardown does not require the part. Returns (line_items, total_cents) with
    per-line round-half-up before summing."""
    mult = tier_multiplier(cfg, tier)
    lines = []
    lines.append(("SEAL_KIT", dec(seal_kit_price_cents)))
    if rod_line_raw is not None:
        lines.append(("ROD", dec(rod_line_raw)))
    if tube_line_raw is not None:
        lines.append(("TUBE", dec(tube_line_raw)))
    lines.append(("HONING", dec(honing_passes) * dec(cfg["honing_pass_fee_cents"])))
    labor_raw = dec(labor_hours) * dec(cfg["labor_rate_cents_per_hour"]) * mult
    lines.append(("LABOR", labor_raw))
    supplies_raw = dec(cfg["supplies_pct_of_labor"]) * labor_raw  # RAW labor, unrounded
    lines.append(("SUPPLIES", supplies_raw))
    if scrap_total_cents is not None:
        lines.append(("SCRAP", dec(scrap_total_cents)))
    line_items = [{"kind": kind, "amount_cents": round_half_up_cents(raw)} for kind, raw in lines]
    total = sum(item["amount_cents"] for item in line_items)
    return line_items, total


def quote_pricing_provisional(cfg, tier, teardown, cylinder, seal_kits):
    """Provisional variant: estimated labor hours, shop default per-mm material
    costs, no SCRAP line."""
    kit_id = teardown.get("seal_kit_id") or cylinder["seal_kit_id"]
    kit = seal_kits[kit_id]
    rod_raw = None
    if teardown.get("rod_needed"):
        rod_raw = (dec(teardown["rod_cut_length_mm"])
                   * dec(cfg["default_chrome_rod_cost_per_mm_cents"])
                   + dec(cfg["cut_fee_cents"]))
    tube_raw = None
    if teardown.get("tube_needed"):
        tube_raw = (dec(teardown["tube_cut_length_mm"])
                    * dec(cfg["default_honing_tube_cost_per_mm_cents"])
                    + dec(cfg["cut_fee_cents"]))
    return _quote_lines(cfg, tier, kit["price_cents"], rod_raw, tube_raw,
                        teardown.get("honing_passes", 0),
                        teardown["estimated_labor_hours"], scrap_total_cents=None)


def quote_pricing_final(cfg, tier, teardown, cylinder, seal_kits, reservations,
                        inventory_items, actual_labor_hours):
    """Final variant at close: actual labor hours, consumed reservation material
    costs, plus a SCRAP line summing scrap charges across all reservations."""
    kit_id = teardown.get("seal_kit_id") or cylinder["seal_kit_id"]
    kit = seal_kits[kit_id]
    rod_raw = None
    if teardown.get("rod_needed"):
        consumed = [r for r in reservations
                    if r["material"] == "CHROME_ROD" and r["status"] == "CONSUMED"]
        material_cost = sum(
            dec(r["consumed_length_mm"]) * dec(inventory_items[r["inventory_item_id"]]["cost_per_mm_cents"])
            for r in consumed
        )
        rod_raw = material_cost + dec(cfg["cut_fee_cents"])
    tube_raw = None
    if teardown.get("tube_needed"):
        consumed = [r for r in reservations
                    if r["material"] == "HONING_TUBE" and r["status"] == "CONSUMED"]
        material_cost = sum(
            dec(r["consumed_length_mm"]) * dec(inventory_items[r["inventory_item_id"]]["cost_per_mm_cents"])
            for r in consumed
        )
        tube_raw = material_cost + dec(cfg["cut_fee_cents"])
    scrap_total = sum(r.get("scrap_charge_cents", 0) for r in reservations)
    _, total = _quote_lines(cfg, tier, kit["price_cents"], rod_raw, tube_raw,
                            teardown.get("honing_passes", 0), actual_labor_hours,
                            scrap_total_cents=scrap_total)
    return total


# ---------------------------------------------------------------------------
# 2. invoice_total_settlement (repair-path close waterfall)
# ---------------------------------------------------------------------------

def invoice_total_settlement(cfg, customer, subtotal_cents):
    """Pinned order: tier test uses PRE-invoice ytd + PRE-discount subtotal;
    discount rounds half-up; env fee = max(floor, half-up(discounted * pct))."""
    tier_test = customer["ytd_spend_cents"] + subtotal_cents
    if tier_test >= cfg["loyalty_gold_threshold_cents"]:
        pct = dec(cfg["loyalty_gold_pct"])
    elif tier_test >= cfg["loyalty_silver_threshold_cents"]:
        pct = dec(cfg["loyalty_silver_pct"])
    else:
        pct = Decimal("0")
    discount = round_half_up_cents(dec(subtotal_cents) * pct)
    discounted = subtotal_cents - discount
    env_fee = max(cfg["env_fee_min_cents"],
                  round_half_up_cents(dec(discounted) * dec(cfg["env_fee_pct"])))
    return discounted + env_fee


# ---------------------------------------------------------------------------
# 3. exchange_core_credit (provisional at fulfill; final at evaluate-core)
# ---------------------------------------------------------------------------

_CONDITION_FACTORS = {"GOOD": "1.0", "WORN": "0.6", "DAMAGED": "0.25", "SCRAP": "0.0"}
_COMPLETENESS_FACTORS = {"COMPLETE": "1.0", "MISSING_PARTS": "0.5"}


def exchange_core_credit(cfg, unit_price_cents, bore_mm, condition, completeness):
    if bore_mm <= cfg["core_bore_medium_max_mm"]:
        base = cfg["core_base_small_cents"]
    elif bore_mm <= cfg["core_bore_large_max_mm"]:
        base = cfg["core_base_medium_cents"]
    else:
        base = cfg["core_base_large_cents"]
    cond = Decimal(_CONDITION_FACTORS[condition])
    comp = Decimal(_COMPLETENESS_FACTORS[completeness])
    uncapped = round_half_up_cents(dec(base) * cond * comp)
    cap = round_half_down_cents(dec(unit_price_cents) * dec(cfg["exchange_credit_cap_pct"]))
    return max(0, min(cap, uncapped))


# ---------------------------------------------------------------------------
# 4. stock_cut_allocation selector
# ---------------------------------------------------------------------------

def select_stock_piece(material, diameter_mm, required_mm):
    """Smallest sufficient AVAILABLE piece; ties broken by earliest created_at.
    Returns the InventoryItem or None when no candidate fits."""
    candidates = [
        item for item in DB.inventory_items.values()
        if item["material"] == material
        and item["diameter_mm"] == diameter_mm
        and item["status"] == "AVAILABLE"
        and item["length_mm"] >= required_mm
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda i: (i["length_mm"], i["created_at"], i["_seq"]))
    return candidates[0]


# ---------------------------------------------------------------------------
# 5. cleanliness_code_rollup (ISO 4406)
# ---------------------------------------------------------------------------

def iso_4406_code(count):
    """code(c) = 0 if c == 0 else ceil(log2(c)); boundary inclusive
    (8192 -> 13, 8193 -> 14)."""
    if count <= 0:
        return 0
    return (count - 1).bit_length()


def cleanliness_result(cfg, c4, c6, c14):
    code4 = iso_4406_code(c4)
    code6 = iso_4406_code(c6)
    code14 = iso_4406_code(c14)
    passed = (code4 <= cfg["cleanliness_target_code4"]
              and code6 <= cfg["cleanliness_target_code6"]
              and code14 <= cfg["cleanliness_target_code14"])
    return code4, code6, code14, passed


# ---------------------------------------------------------------------------
# 6. pressure_hold_requirement
# ---------------------------------------------------------------------------

def required_hold_psi(cfg, pressure_class):
    rated = (cfg["rated_pressure_class_3000_psi"] if pressure_class == "CLASS_3000"
             else cfg["rated_pressure_class_5000_psi"])
    return round_half_up_cents(dec(cfg["pressure_test_factor"]) * dec(rated))


# ---------------------------------------------------------------------------
# 7. turnaround_tier_gate (both boundaries inclusive)
# ---------------------------------------------------------------------------

def tier_gate_ok(cfg, tier, promised_hours):
    if promised_hours <= cfg["emergency_cutoff_hours"]:
        return tier == "EMERGENCY"
    if promised_hours <= cfg["expedite_cutoff_hours"]:
        return tier in ("EMERGENCY", "EXPEDITE")
    return True


# ---------------------------------------------------------------------------
# 8. field_service_pricing (provisional at creation; final at completion)
# ---------------------------------------------------------------------------

def _hose_rate(cfg, hose_type):
    if hose_type == "WIRE_BRAID_2SN":
        return cfg["hose_price_wire_braid_2sn_cents_per_m"]
    if hose_type == "SPIRAL_4SH":
        return cfg["hose_price_spiral_4sh_cents_per_m"]
    return cfg["hose_price_thermoplastic_cents_per_m"]


def field_service_price(cfg, assemblies, distance_km, emergency_callout):
    per_assembly_total = 0
    for a in assemblies:
        hose_term = round_half_up_cents(dec(a["length_m"]) * dec(_hose_rate(cfg, a["hose_type"])))
        per_assembly_total += cfg["crimp_fee_cents"] + hose_term + 2 * a["fitting_price_cents"]
    mileage = max(0, distance_km - cfg["mileage_free_km"]) * cfg["mileage_rate_cents_per_km"]
    callout_mult = dec(cfg["emergency_callout_multiplier"]) if emergency_callout else Decimal("1.0")
    callout = round_half_up_cents(dec(cfg["callout_base_cents"]) * callout_mult)
    return callout + per_assembly_total + mileage


# ---------------------------------------------------------------------------
# 9. credit_exposure_check (quote approval; inclusive boundary passes)
# ---------------------------------------------------------------------------

def open_credit_exposure(customer_id):
    """Sum of provisional_total_cents over APPROVED quotes whose work order
    belongs to this customer and is not CLOSED/CANCELLED/SCRAPPED."""
    total = 0
    for quote in DB.quotes.values():
        if quote["status"] != "APPROVED":
            continue
        wo = DB.work_orders.get(quote["work_order_id"])
        if wo is None or wo["customer_id"] != customer_id:
            continue
        if wo["status"] in ("CLOSED", "CANCELLED", "SCRAPPED"):
            continue
        total += quote["provisional_total_cents"]
    return total


def credit_exposure_ok(customer, quote):
    exposure = open_credit_exposure(customer["id"])
    return exposure + quote["provisional_total_cents"] <= customer["credit_limit_cents"]
