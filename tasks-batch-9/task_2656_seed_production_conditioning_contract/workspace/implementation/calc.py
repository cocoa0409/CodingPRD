"""Calculation rules (PRD 2.7, 3.2, 3.3, 3.4, 3.5, 3.7, 3.9; SCAFFOLD 1.3)."""

from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

# ---- constants -----------------------------------------------------------
UNIT_KG = Decimal("25.0")
MOISTURE_BASE_PCT = Decimal("12.0")
MOISTURE_SHRINK_FACTOR = Decimal("1.5")

HISTORY_BASE_RISK = Decimal("100.0")
DECAY_FACTOR = Decimal("0.5")
ISOLATION_RISK_PER_M = Decimal("0.5")
DECAY_ELIGIBILITY_MAX_SCORE = Decimal("25.0")

ROGUEABLE_MULTIPLE = Decimal("3.0")

ADJ_CAP_PCT = Decimal("8.0")
ADJ_FLOOR_PCT = Decimal("-35.0")

WATCH_AT_FLAGS = 2
SUSPEND_AT_FLAGS = 4

INSPECTOR_DAILY_CAPACITY = 2

TIER_TABLE = (
    (5000000, Decimal("100.0")),
    (2000000, Decimal("60.0")),
    (500000, Decimal("35.0")),
)
TIER_4_CAP_PCT = Decimal("15.0")

STRICT_CLASSES = ("FOUNDATION", "REGISTERED", "CERTIFIED")
CLASS_RANK = {"CERTIFIED": 1, "REGISTERED": 2, "FOUNDATION": 3}


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, dp):
    """round_half_up: a value exactly halfway rounds away from zero."""
    q = Decimal(1).scaleb(-dp) if dp > 0 else Decimal(1)
    return dec(value).quantize(q, rounding=ROUND_HALF_UP)


def trunc_toward_zero(value):
    """Whole number obtained by discarding the fraction (bag counts)."""
    d = dec(value)
    return int(d.to_integral_value(rounding=ROUND_FLOOR)) if d >= 0 else -int(
        (-d).to_integral_value(rounding=ROUND_FLOOR))


def moisture_dockage_pct(moisture_pct):
    """max(0, (moisture_pct - 12.0) * 1.5), a dockage pct carried at 2 dp."""
    raw = (dec(moisture_pct) - MOISTURE_BASE_PCT) * MOISTURE_SHRINK_FACTOR
    if raw < 0:
        raw = Decimal("0")
    return round_half_up(raw, 2)


# ---- clean_seed_unit_accounting -----------------------------------------
def provisional_harvest_basis(gross_weight_kg, moisture_pct, shrink_pct):
    """Variant A: book estimate written on the harvest event and the lot."""
    dockage = moisture_dockage_pct(moisture_pct)
    clean_kg = round_half_up(
        dec(gross_weight_kg)
        * (Decimal("1") - dockage / Decimal("100"))
        * (Decimal("1") - dec(shrink_pct) / Decimal("100")),
        3,
    )
    units = round_half_up(clean_kg / UNIT_KG, 2)
    return dockage, clean_kg, units


def final_bagged_basis(output_kg):
    """Variant B: measured bagged mass only."""
    return round_half_up(dec(output_kg) / UNIT_KG, 2)


def bag_count_for(output_kg, bag_size_kg):
    return trunc_toward_zero(dec(output_kg) / dec(bag_size_kg))


# ---- field_eligibility_assessment ---------------------------------------
def applied_variant_for(seed_class):
    return "STRICT_HISTORY" if seed_class in STRICT_CLASSES else "DECAY_WEIGHTED"


def field_eligibility_assessment(history_records, variety, field, season_year, seed_class):
    """Both variants of the eligibility question over the same inputs."""
    restricted_kinds = variety.get("restricted_prior_crop_kinds") or []
    look_back = variety["restricted_prior_crop_years"]
    cutoff = season_year - look_back
    restricted = [
        h for h in history_records
        if h["crop_kind"] in restricted_kinds and h["crop_year"] > cutoff
    ]

    shortfall = dec(variety["isolation_min_m"]) - dec(field["isolation_distance_m"])
    if shortfall < 0:
        shortfall = Decimal("0")
    isolation_shortfall_m = round_half_up(shortfall, 2)

    # Variant A - STRICT_HISTORY
    if restricted:
        strict_result = "INELIGIBLE"
        strict_block = "ERR_FIELD_HISTORY_RESTRICTED"
    elif isolation_shortfall_m > 0:
        strict_result = "INELIGIBLE"
        strict_block = "ERR_ISOLATION_DISTANCE_INSUFFICIENT"
    else:
        strict_result = "ELIGIBLE"
        strict_block = None

    # Variant B - DECAY_WEIGHTED
    history_component = Decimal("0")
    for h in restricted:
        elapsed = season_year - h["crop_year"]
        contribution = HISTORY_BASE_RISK * (DECAY_FACTOR ** elapsed)
        history_component += round_half_up(contribution, 2)
    history_component = round_half_up(history_component, 2)
    isolation_component = round_half_up(isolation_shortfall_m * ISOLATION_RISK_PER_M, 2)
    risk_score = round_half_up(history_component + isolation_component, 2)

    if risk_score <= DECAY_ELIGIBILITY_MAX_SCORE:
        decay_result = "ELIGIBLE"
        decay_block = None
    else:
        decay_result = "INELIGIBLE"
        decay_block = ("ERR_FIELD_HISTORY_RESTRICTED"
                       if history_component > isolation_component
                       else "ERR_ISOLATION_DISTANCE_INSUFFICIENT")

    applied_variant = applied_variant_for(seed_class)
    if applied_variant == "STRICT_HISTORY":
        applied_result, blocking = strict_result, strict_block
    else:
        applied_result, blocking = decay_result, decay_block

    return {
        "strict_history_result": strict_result,
        "decay_weighted_result": decay_result,
        "restricted_record_count": len(restricted),
        "history_component": history_component,
        "isolation_component": isolation_component,
        "contamination_risk_score": risk_score,
        "isolation_shortfall_m": isolation_shortfall_m,
        "applied_variant": applied_variant,
        "applied_result": applied_result,
        "blocking_error_id": blocking,
    }


# ---- inspection_outcome_determination -----------------------------------
def inspection_rates(sampled_plants, off_type_plants, restricted_weed_plants, diseased_plants):
    sampled = dec(sampled_plants)
    return (
        round_half_up(dec(off_type_plants) / sampled * Decimal("10000"), 2),
        round_half_up(dec(restricted_weed_plants) / sampled * Decimal("10000"), 2),
        round_half_up(dec(diseased_plants) / sampled * Decimal("100"), 2),
    )


def inspection_outcome(off_type_rate, weed_rate, disease_pct, isolation_verified_m,
                       variety, rogueing_rounds_used):
    max_off = dec(variety["max_off_type_per_10000"])
    max_weed = dec(variety["max_restricted_weed_per_10000"])
    purity_breach = off_type_rate > max_off
    weed_breach = weed_rate > max_weed
    if purity_breach or weed_breach:
        ratios = []
        ratios.append(off_type_rate / max_off if max_off != 0 else Decimal("Infinity"))
        ratios.append(weed_rate / max_weed if max_weed != 0 else Decimal("Infinity"))
        worst_ratio = max(ratios)
        if (worst_ratio <= ROGUEABLE_MULTIPLE
                and rogueing_rounds_used < variety["max_rogueing_rounds"]):
            return "ROGUEING_ORDERED"
        return "FAILED"
    if disease_pct > dec(variety["max_disease_incidence_pct"]):
        return "FAILED"
    if dec(isolation_verified_m) < dec(variety["isolation_min_m"]):
        return "FAILED"
    return "PASSED"


# ---- adjusted_price_per_unit --------------------------------------------
def adjusted_price_per_unit(germination_pct, purity_pct, weed_seed_count_per_kg,
                           intake_moisture_pct, variety, base_price_per_unit_cents):
    germ = dec(germination_pct)
    pur = dec(purity_pct)
    weeds = int(weed_seed_count_per_kg)

    if germ >= Decimal("95.0"):
        germ_adj = Decimal("6.0")
    elif germ >= Decimal("90.0"):
        germ_adj = Decimal("2.0")
    else:
        germ_adj = Decimal("0.0")

    if pur >= Decimal("99.5"):
        purity_adj = Decimal("2.0")
    elif pur >= Decimal("98.0"):
        purity_adj = Decimal("0.0")
    else:
        purity_adj = Decimal("-4.0")

    if weeds == 0:
        weed_penalty = Decimal("0.0")
    elif weeds <= 10:
        weed_penalty = Decimal("-3.0")
    else:
        weed_penalty = Decimal("-9.0")

    dockage = moisture_dockage_pct(intake_moisture_pct)
    raw_adj = germ_adj + purity_adj + weed_penalty - dockage
    clamped = min(ADJ_CAP_PCT, max(ADJ_FLOOR_PCT, raw_adj))
    price = round_half_up(
        dec(base_price_per_unit_cents) * (Decimal("1") + clamped / Decimal("100")), 0)
    return int(price)


# ---- settlement ---------------------------------------------------------
def settlement_rollup(lines, conditioning_charge_per_unit_cents):
    """Per-line amounts are rounded to whole cents BEFORE summation."""
    gross_total = 0
    charge_total = 0
    units_sum = Decimal("0")
    charge_rate = dec(conditioning_charge_per_unit_cents)
    for lot in lines:
        units = dec(lot["final_clean_units"])
        units_sum += units
        gross_total += int(round_half_up(units * dec(lot["adjusted_price_per_unit_cents"]), 0))
        charge_total += int(round_half_up(units * charge_rate, 0))
    return {
        "line_count": len(lines),
        "settled_units_total": round_half_up(units_sum, 2),
        "gross_payable_cents": gross_total,
        "conditioning_charges_cents": charge_total,
    }


def recovery_cap_pct_for(provisional_net_cents):
    for minimum, cap in TIER_TABLE:
        if provisional_net_cents >= minimum:
            return cap
    return TIER_4_CAP_PCT


def settlement_net_payable(provisional_net_cents, advance_outstanding_cents):
    cap = recovery_cap_pct_for(provisional_net_cents)
    capped = int(round_half_up(dec(provisional_net_cents) * cap / Decimal("100"), 0))
    recovery = min(int(advance_outstanding_cents), capped)
    return cap, recovery, provisional_net_cents - recovery


def grower_standing_for(flag_count):
    if flag_count >= SUSPEND_AT_FLAGS:
        return "SUSPENDED"
    if flag_count >= WATCH_AT_FLAGS:
        return "WATCH"
    return "GOOD_STANDING"


def dockage_pct_for(cumulative_shrink_kg, gross_kg):
    if dec(gross_kg) == 0:
        return round_half_up(0, 2)
    return round_half_up(dec(cumulative_shrink_kg) / dec(gross_kg) * Decimal("100"), 2)
