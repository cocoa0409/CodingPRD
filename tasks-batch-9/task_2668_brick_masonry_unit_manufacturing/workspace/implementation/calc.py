"""Calculation rules (PRD 2.7 rounding discipline and section 3 formulas)."""

from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

D = Decimal

# ---- body_blend_chemistry ------------------------------------------------
ABSORPTION_BASE = D("18.0")
IRON_ABSORPTION_COEFF = D("1.2")
SHALE_ABSORPTION_COEFF = D("0.08")
LIME_ABSORPTION_COEFF = D("1.5")
ABSORPTION_MIN = D("2.0")
ABSORPTION_MAX = D("22.0")
SW_MAX_ABSORPTION = D("8.00")
MW_MAX_ABSORPTION = D("14.00")

# ---- green_yield ---------------------------------------------------------
GREEN_HANDLING_LOSS_BP = D("350")
SETTING_LOSS_UNITS_PER_CAR = 12
GREEN_LOSS_HOLD_PCT = D("6.00")

# ---- firing_color_development -------------------------------------------
CDI_TEMP_ORIGIN_C = D("900")
CDI_TEMP_COEFF = D("0.62")
CDI_SOAK_COEFF = D("4.0")
POSITION_TEMP_GRADIENT_C = D("6.0")
OVERFIRE_CDI_MARGIN = D("6.00")
UNDERFIRE_CDI_MARGIN = D("6.00")
ON_COLOR_CDI_BAND = D("3.00")
COLOR_INDEX_MIDPOINT = D("50.0")
COLOR_INDEX_CDI_SLOPE = D("3.2")

# ---- blends --------------------------------------------------------------
BLEND_SPAN_CEILING = D("12.00")
DURABILITY_RANK = {"SW": 3, "MW": 2, "NW": 1}

# ---- freight -------------------------------------------------------------
UNIT_WEIGHT_LB = D("4.5")
LB_PER_TON = D("2000")
PALLET_TARE_LB = D("60")
PALLET_UNITS = 500
BAND_WEIGHT_LB = {"STEEL": D("3.0"), "POLY": D("1.2")}
SURCHARGE_TIER_1_CEILING_CENTS = 50000
SURCHARGE_TIER_2_CEILING_CENTS = 150000
SURCHARGE_TIER_1_PCT = D("6.5")
SURCHARGE_TIER_2_PCT = D("4.5")
SURCHARGE_TIER_3_PCT = D("3.0")

# ---- lead time -----------------------------------------------------------
BASE_LEAD_DAYS = 14
SPECIAL_ORDER_LEAD_DAYS = 28
PANEL_APPROVAL_LEAD_DAYS = 7

# ---- panels --------------------------------------------------------------
PANEL_APPROVAL_VALID_DAYS = 180
PANEL_MAX_REVISION_ROUNDS = 3
DYE_LOT_CLOSURE_MAX_HOPS = 16


def rh(value, places=2):
    """Round half up (away from zero on a tie) to `places` decimals."""
    quantum = D(1).scaleb(-places)
    return D(value).quantize(quantum, rounding=ROUND_HALF_UP)


def rh_int(value):
    return int(D(value).quantize(D(1), rounding=ROUND_HALF_UP))


def ceil_int(value):
    return int(D(value).quantize(D(1), rounding=ROUND_CEILING))


def clamp(low, high, value):
    if value < low:
        return low
    if value > high:
        return high
    return value


def rank(grade):
    return DURABILITY_RANK.get(grade, 0)


# --------------------------------------------------------------------------
# body_blend_chemistry
# --------------------------------------------------------------------------
def body_chemistry(components, pit_lookup):
    """Share-weighted body chemistry; accumulate at full precision, round once."""
    iron_acc = D("0")
    lime_acc = D("0")
    shale_total = D("0")
    share_total = D("0")
    for comp in components:
        pit = pit_lookup(comp["pit_id"])
        share = D(comp["share_pct"])
        share_total += share
        if pit is None:
            continue
        iron_acc += D(pit["iron_oxide_pct"]) * share
        lime_acc += D(pit["lime_pct"]) * share
        if pit["material_type"] == "SHALE":
            shale_total += share
    blend_iron = rh(iron_acc / D("100"), 3)
    blend_lime = rh(lime_acc / D("100"), 3)
    raw_absorption = (
        ABSORPTION_BASE
        - IRON_ABSORPTION_COEFF * blend_iron
        - SHALE_ABSORPTION_COEFF * shale_total
        + LIME_ABSORPTION_COEFF * blend_lime
    )
    absorption = rh(clamp(ABSORPTION_MIN, ABSORPTION_MAX, raw_absorption), 2)
    if absorption <= SW_MAX_ABSORPTION:
        grade = "SW"
    elif absorption <= MW_MAX_ABSORPTION:
        grade = "MW"
    else:
        grade = "NW"
    return {
        "component_share_total_pct": share_total,
        "blend_iron_oxide_pct": blend_iron,
        "blend_lime_pct": blend_lime,
        "shale_share_pct": shale_total,
        "absorption_index": absorption,
        "computed_durability_grade": grade,
    }


# --------------------------------------------------------------------------
# clay_tonnage_commitment (two-level split, residual on the LAST component)
# --------------------------------------------------------------------------
def clay_total_tons(green_units_set, tons_per_thousand):
    return rh(D(green_units_set) / D("1000") * D(tons_per_thousand), 2)


def clay_split(total_tons, components):
    """Return [(pit_id, tons)] in component append order; residual on the last."""
    if not components:
        return []
    amounts = []
    running = D("0.00")
    for comp in components:
        share = rh(D(total_tons) * D(comp["share_pct"]) / D("100"), 2)
        running += share
        amounts.append([comp["pit_id"], share])
    residual = rh(D(total_tons) - running, 2)
    amounts[-1][1] = amounts[-1][1] + residual
    return [(pit_id, tons) for pit_id, tons in amounts]


# --------------------------------------------------------------------------
# green_yield
# --------------------------------------------------------------------------
def projected_net_green_units(green_units_set):
    projected_loss = (
        ceil_int(D(green_units_set) * GREEN_HANDLING_LOSS_BP / D("10000"))
        + SETTING_LOSS_UNITS_PER_CAR
    )
    return green_units_set - projected_loss


def green_loss_pct(green_loss_units, green_units_set):
    return rh(D(green_loss_units) * D("100") / D(green_units_set), 2)


# --------------------------------------------------------------------------
# firing_color_development
# --------------------------------------------------------------------------
def base_cdi(actual_peak_temp_c, actual_soak_hours):
    return rh(
        CDI_TEMP_COEFF * (D(actual_peak_temp_c) - CDI_TEMP_ORIGIN_C) / D("10")
        + CDI_SOAK_COEFF * D(actual_soak_hours),
        2,
    )


def firing_curve_deviation(actual_peak_temp_c, setpoint_peak_c, actual_soak_hours, target_soak_hours):
    return rh(
        abs(D(actual_peak_temp_c) - D(setpoint_peak_c)) / D("10")
        + abs(D(actual_soak_hours) - D(target_soak_hours)),
        2,
    )


def position_temp_delta_c(kiln_position, position_count):
    centerline = (D(position_count) + D("1")) / D("2")
    return rh(-POSITION_TEMP_GRADIENT_C * abs(D(kiln_position) - centerline), 2)


def position_cdi(base, delta):
    return rh(D(base) + CDI_TEMP_COEFF * D(delta) / D("10"), 2)


def firing_grade(pos_cdi, target_cdi):
    pos_cdi = D(pos_cdi)
    target = D(target_cdi)
    if pos_cdi > target + OVERFIRE_CDI_MARGIN:
        return "OVERFIRE_SCRAP"
    if pos_cdi < target - UNDERFIRE_CDI_MARGIN:
        return "UNDERFIRE_SCRAP"
    if abs(pos_cdi - target) <= ON_COLOR_CDI_BAND:
        return "ON_COLOR"
    return "OFF_COLOR_SALVAGE"


def lot_color_index(pos_cdi, target_cdi):
    raw = COLOR_INDEX_MIDPOINT + COLOR_INDEX_CDI_SLOPE * (D(pos_cdi) - D(target_cdi))
    return rh(clamp(D("0.00"), D("100.00"), raw), 2)


# --------------------------------------------------------------------------
# order_freight_cost
# --------------------------------------------------------------------------
def surcharge_pct(base_cents):
    if base_cents < SURCHARGE_TIER_1_CEILING_CENTS:
        return SURCHARGE_TIER_1_PCT
    if base_cents < SURCHARGE_TIER_2_CEILING_CENTS:
        return SURCHARGE_TIER_2_PCT
    return SURCHARGE_TIER_3_PCT


def freight(distance_miles, rate_cents_per_ton_mile, billable_tons):
    base = rh_int(D(distance_miles) * D(rate_cents_per_ton_mile) * D(billable_tons))
    pct = surcharge_pct(base)
    surcharge = rh_int(D(base) * pct / D("100"))
    return base, surcharge, base + surcharge


def estimated_billable_tons(requested_units):
    return rh(D(requested_units) * UNIT_WEIGHT_LB / LB_PER_TON, 2)


def final_billable_tons(pallet_count, band_count, banding_type, allocated_units):
    total_lb = (
        D(pallet_count) * PALLET_TARE_LB
        + D(band_count) * BAND_WEIGHT_LB[banding_type]
        + D(allocated_units) * UNIT_WEIGHT_LB
    )
    return rh(total_lb / LB_PER_TON, 2)


def rectilinear(ax, ay, bx, by):
    return abs(int(ax) - int(bx)) + abs(int(ay) - int(by))


def lead_time_days(requested_units, capacity_per_day, is_special_order, requires_panel_approval):
    days = BASE_LEAD_DAYS
    if is_special_order:
        days += SPECIAL_ORDER_LEAD_DAYS
    if requires_panel_approval:
        days += PANEL_APPROVAL_LEAD_DAYS
    days += ceil_int(D(requested_units) / D(capacity_per_day))
    return days
