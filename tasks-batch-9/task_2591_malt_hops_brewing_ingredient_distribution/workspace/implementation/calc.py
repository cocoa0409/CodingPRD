"""Every named calculation in the specification.

Money is integer cents throughout.  Poundage, litres, temperatures and
percentages are carried as Decimal.  Rounding is ROUND_HALF_UP except in the
three places the PRD names floor: the allocatable harvest pool, the
carry-forward cap and cold-chain interval / cumulative excursion minutes.
"""

from datetime import timedelta
from decimal import Decimal

from db import by_created, db, now, sort_key, touch
from util import (
    D,
    dec_floor,
    floor_int,
    rhu,
    rhu_int,
    whole_days_between,
    whole_minutes_between,
)

# --- order_fee_assessment constants ----------------------------------------
DISCOUNT_TIER_1_CENTS = 1000000
DISCOUNT_TIER_1_PCT = D("1.5")
DISCOUNT_TIER_2_CENTS = 5000000
DISCOUNT_TIER_2_PCT = D("3.0")

FREIGHT_RATE_CENTS_PER_LB = {
    "TIER_1": D("12"),
    "TIER_2": D("8"),
    "TIER_3": D("5"),
}
FREIGHT_MINIMUM_CENTS = {"TIER_1": 25000, "TIER_2": 15000, "TIER_3": 0}
REEFER_SURCHARGE_CENTS = 18000
PALLET_BREAK_FEE_CENTS = 4500
MOQ_ORDER_LBS = D("2000")
SMALL_ORDER_SURCHARGE_CENTS = 7500

# --- freight_program_tier constants ---------------------------------------
TRAILING_WINDOW_DAYS = 365
TIER_2_MIN_LBS = D("40000")
TIER_3_MIN_LBS = D("120000")

# --- settlement constants -------------------------------------------------
LIQUIDATED_DAMAGES_PCT = D("35")
ADMIN_FEE_HIGH_PCT = D("2.0")
ADMIN_FEE_LOW_PCT = D("1.0")
ADMIN_FEE_TIER_CENTS = 1000000

# --- carry forward --------------------------------------------------------
CARRY_FORWARD_CAP_PCT = D("25")
CARRY_FORWARD_FEE_PCT = D("8")
CARRY_FORWARD_SHIFT_DAYS = 365

# --- allocation -----------------------------------------------------------
CONTRACT_TYPE_RANK = {"FIXED_CROP_YEAR": 1, "SPOT_HOLD": 2}

# --- malt spec matching ---------------------------------------------------
WEIGHT_COLOR = D("0.40")
WEIGHT_EXTRACT = D("0.35")
WEIGHT_PROTEIN = D("0.25")
TOLERANCE_COLOR = D("1.5")
TOLERANCE_EXTRACT = D("1.0")
TOLERANCE_PROTEIN = D("0.8")
ADJUNCT_DIASTATIC_BUMP = D("10.0")
GRADE_EXACT_MIN = D("95.00")
GRADE_ACCEPTABLE_MIN = D("80.00")
GRADE_SUBSTITUTE_MIN = D("60.00")

# --- yeast pitch advisory -------------------------------------------------
LITRES_PER_BBL = D("117.348")
ALE_TARGET_RATE = D("0.75")
LAGER_TARGET_RATE = D("1.50")
VIABILITY_DECAY_PER_DAY = D("0.02")
VIABILITY_FLOOR = D("0.50")
PROPAGATION_HEADROOM = D("1.15")
PITCH_BAND_LOW = D("0.9")
PITCH_BAND_HIGH = D("1.1")

# --- credit posture -------------------------------------------------------
WATCH_UTILISATION_PCT = D("85.00")

# --- cold chain -----------------------------------------------------------
MAX_EXCURSION_MINUTES = 30

ROLLUP_LINE_STATUSES = ("OPEN", "TRIMMED")
COMMITTED_ORDER_STATUSES = ("CONFIRMED", "PICKED", "SHIPPED", "DELIVERED")
OPEN_EXPOSURE_STATUSES = ("DRAFT", "CONFIRMED", "PICKED")


# ===========================================================================
# collection helpers
# ===========================================================================

def orders_of(brewer_id):
    return [o for o in db.orders.values() if o["brewer_id"] == brewer_id]


def lines_of(order_id):
    return by_created([l for l in db.lines.values() if l["sales_order_id"] == order_id])


def contracts_of_program(program_id):
    return by_created(
        [c for c in db.contracts.values() if c["crop_year_program_id"] == program_id]
    )


def shipments_of_order(order_id):
    return by_created(
        [s for s in db.shipments.values() if s["sales_order_id"] == order_id]
    )


def readings_of_shipment(shipment_id):
    items = [r for r in db.readings.values() if r["cold_chain_shipment_id"] == shipment_id]
    return sorted(items, key=lambda r: (r["recorded_at"], r["_seq"]))


def line_item_entity(line):
    if line["item_type"] == "HOP":
        return db.varieties.get(line.get("hop_variety_id"))
    if line["item_type"] == "MALT":
        lot = db.malt_lots.get(line.get("malt_lot_id"))
        if lot is None:
            return None
        return db.malt_products.get(lot["malt_product_id"])
    job = db.jobs.get(line.get("yeast_propagation_job_id"))
    if job is None:
        return None
    return db.strains.get(job["yeast_strain_id"])


def line_pallet_quantity(line):
    if line["item_type"] == "YEAST":
        return None
    ent = line_item_entity(line)
    if ent is None:
        return None
    return ent.get("pallet_quantity_lbs")


# ===========================================================================
# calculations.contract_allocation_ledger
# ===========================================================================

def contract_remaining(contract):
    return (
        D(contract["allocated_lbs"])
        - D(contract["committed_lbs"])
        - D(contract["carried_forward_out_lbs"])
        - D(contract["defaulted_lbs"])
        - D(contract["resold_lbs"])
    )


def contract_shortfall(contract):
    gap = D(contract["contracted_lbs"]) - D(contract["allocated_lbs"])
    return gap if gap > 0 else D(0)


# ===========================================================================
# calculations.malt_lot_availability
# ===========================================================================

def malt_lot_committed(lot):
    total = D(0)
    for line in db.lines.values():
        if line["item_type"] != "MALT":
            continue
        if line.get("malt_lot_id") != lot["id"]:
            continue
        if line["status"] not in ROLLUP_LINE_STATUSES:
            continue
        order = db.orders.get(line["sales_order_id"])
        if order is None or order["fulfillment_status"] not in COMMITTED_ORDER_STATUSES:
            continue
        total += D(line["quantity"])
    return total


def malt_lot_available(lot):
    return D(lot["quantity_lbs"]) - malt_lot_committed(lot)


# ===========================================================================
# calculations.zone_occupancy_projection
# ===========================================================================

def zone_occupied(zone):
    instant = now()
    total = 0
    for shipment in db.shipments.values():
        if shipment["cold_storage_zone_id"] != zone["id"]:
            continue
        if shipment["status"] != "STAGED":
            continue
        if shipment["stage_from"] <= instant < shipment["stage_until"]:
            total += shipment["pallet_count"]
    return total


def zone_admits(zone, candidate, exclude_ids=()):
    """Aggregate boundary sweep: no sub-interval may exceed capacity.

    ``candidate`` is a (stage_from, stage_until, pallet_count) tuple, or None.
    Equality with capacity is accepted.
    """
    intervals = []
    for shipment in db.shipments.values():
        if shipment["cold_storage_zone_id"] != zone["id"]:
            continue
        if shipment["status"] != "STAGED":
            continue
        if shipment["id"] in exclude_ids:
            continue
        intervals.append(
            (shipment["stage_from"], shipment["stage_until"], shipment["pallet_count"])
        )
    if candidate is not None:
        intervals.append(candidate)
    if not intervals:
        return True
    bounds = sorted({b for iv in intervals for b in (iv[0], iv[1])})
    capacity = zone["capacity_pallets"]
    for point in bounds[:-1]:
        total = 0
        for start, end, pallets in intervals:
            if start <= point < end:
                total += pallets
        if total > capacity:
            return False
    return True


# ===========================================================================
# calculations.freight_program_tier
# ===========================================================================

def trailing_volume(brewer, exclude_order_id=None):
    """legacy_trailing_lbs plus delivered poundage inside the trailing window.

    The window is half-open on the older end: an order delivered exactly 365
    days ago has aged out; one delivered at the current instant is included.
    """
    total = D(brewer["legacy_trailing_lbs"])
    instant = now()
    oldest = instant - timedelta(days=TRAILING_WINDOW_DAYS)
    for order in db.orders.values():
        if order["brewer_id"] != brewer["id"]:
            continue
        if exclude_order_id is not None and order["id"] == exclude_order_id:
            continue
        if order["fulfillment_status"] != "DELIVERED":
            continue
        delivered = order.get("delivered_at")
        if delivered is None:
            continue
        if delivered <= oldest or delivered > instant:
            continue
        total += D(order["chargeable_lbs"])
    return total


def freight_tier(volume_lbs):
    volume = D(volume_lbs)
    if volume >= TIER_3_MIN_LBS:
        return "TIER_3"
    if volume >= TIER_2_MIN_LBS:
        return "TIER_2"
    return "TIER_1"


# ===========================================================================
# calculations.brewer_credit_posture
# ===========================================================================

def recompute_brewer(brewer, bump=True):
    """Refresh the brewery's freight tier and credit posture.

    A version bump is recorded only when a stored value actually moves.
    """
    trailing = trailing_volume(brewer)
    tier = freight_tier(trailing)
    open_exposure = 0
    for order in orders_of(brewer["id"]):
        if order["fulfillment_status"] in OPEN_EXPOSURE_STATUSES:
            open_exposure += int(order["total_cents"])
    exposure = int(brewer["ar_balance_cents"]) + open_exposure
    limit = int(brewer["credit_limit_cents"])
    utilisation = rhu(D(exposure) / D(limit) * D(100), 2)
    if exposure > limit:
        status = "HOLD"
    elif utilisation >= WATCH_UTILISATION_PCT:
        status = "WATCH"
    else:
        status = "GOOD_STANDING"
    updates = {
        "trailing_12mo_volume_lbs": trailing,
        "freight_program_tier": tier,
        "open_order_exposure_cents": open_exposure,
        "credit_exposure_cents": exposure,
        "credit_utilization_pct": utilisation,
        "credit_status": status,
    }
    changed = False
    for key, value in updates.items():
        if brewer.get(key) != value:
            brewer[key] = value
            changed = True
    if changed and bump:
        touch(brewer)
    return changed


# ===========================================================================
# calculations.order_subtotal_rollup
# ===========================================================================

def rollup_order(order):
    """Recompute per-line extended value first, then the order aggregates."""
    subtotal = 0
    chargeable = D(0)
    line_count = 0
    requires_cold_chain = False
    for line in lines_of(order["id"]):
        if line["status"] not in ROLLUP_LINE_STATUSES:
            continue
        refresh_line_derived(line)
        subtotal += int(line["extended_cents"])
        if line["uom"] == "LB":
            chargeable += D(line["quantity"])
        line_count += 1
        if line["cold_chain_required"]:
            requires_cold_chain = True
    order["subtotal_cents"] = subtotal
    order["chargeable_lbs"] = chargeable
    order["line_count"] = line_count
    order["requires_cold_chain"] = requires_cold_chain
    return order


def refresh_line_derived(line, bump=False):
    extended = rhu_int(D(line["quantity"]) * D(line["unit_price_cents"]))
    pallet_quantity = line_pallet_quantity(line)
    if pallet_quantity is None or D(pallet_quantity) <= 0:
        pallet_break = False
    else:
        pallet_break = (D(line["quantity"]) % D(pallet_quantity)) != 0
    changed = (
        line.get("extended_cents") != extended
        or line.get("pallet_break") != pallet_break
    )
    line["extended_cents"] = extended
    line["pallet_break"] = pallet_break
    if changed and bump:
        touch(line)
    return changed


# ===========================================================================
# calculations.order_fee_assessment
# ===========================================================================

def assess_order_fees(order, variant, persist=True):
    """PROVISIONAL at confirm time, FINAL at delivery time."""
    brewer = db.brewers[order["brewer_id"]]
    subtotal = int(order["subtotal_cents"])

    if subtotal >= DISCOUNT_TIER_2_CENTS:
        discount_pct = DISCOUNT_TIER_2_PCT
    elif subtotal >= DISCOUNT_TIER_1_CENTS:
        discount_pct = DISCOUNT_TIER_1_PCT
    else:
        discount_pct = D(0)
    volume_discount = rhu_int(D(subtotal) * discount_pct / D(100))
    discounted_subtotal = subtotal - volume_discount

    chargeable = D(order["chargeable_lbs"])
    tier_volume = trailing_volume(brewer, exclude_order_id=order["id"])
    if variant == "FINAL":
        tier_volume = tier_volume + chargeable
    tier = freight_tier(tier_volume)

    freight = rhu_int(chargeable * FREIGHT_RATE_CENTS_PER_LB[tier])
    minimum = FREIGHT_MINIMUM_CENTS[tier]
    if freight < minimum:
        freight = minimum
    if order["requires_cold_chain"]:
        freight += REEFER_SURCHARGE_CENTS

    pallet_break_lines = 0
    for line in lines_of(order["id"]):
        if line["status"] not in ROLLUP_LINE_STATUSES:
            continue
        if line["pallet_break"]:
            pallet_break_lines += 1
    pallet_break_fee = PALLET_BREAK_FEE_CENTS * pallet_break_lines

    if chargeable < MOQ_ORDER_LBS:
        small_order_surcharge = SMALL_ORDER_SURCHARGE_CENTS
    else:
        small_order_surcharge = 0

    total = discounted_subtotal + freight + pallet_break_fee + small_order_surcharge

    result = {
        "volume_discount_cents": volume_discount,
        "freight_cents": freight,
        "freight_tier_applied": tier,
        "pallet_break_fee_cents": pallet_break_fee,
        "small_order_surcharge_cents": small_order_surcharge,
        "total_cents": total,
        "fee_variant": variant,
    }
    if variant == "FINAL":
        result["final_freight_adjustment_cents"] = total - int(order["total_cents"])
    if persist:
        order.update(result)
    return result


# ===========================================================================
# calculations.contract_default_settlement
# ===========================================================================

def settle_default(contract, defaulted_lbs):
    program = db.programs[contract["crop_year_program_id"]]
    variety = db.varieties[contract["variety_id"]]
    price = D(contract["price_per_lb_cents"])
    volume = D(defaulted_lbs)
    if program["status"] in ("HARVEST_REPORTED", "SETTLED"):
        variant = "MARKET_SETTLED"
        spread = price - D(variety["spot_price_cents_per_lb"])
        if spread < 0:
            spread = D(0)
        damages = rhu_int(volume * spread)
    else:
        variant = "LIQUIDATED"
        damages = rhu_int(volume * price * LIQUIDATED_DAMAGES_PCT / D(100))
    if damages >= ADMIN_FEE_TIER_CENTS:
        admin_pct = ADMIN_FEE_LOW_PCT
    else:
        admin_pct = ADMIN_FEE_HIGH_PCT
    admin_fee = rhu_int(D(damages) * admin_pct / D(100))
    return {
        "settlement_variant": variant,
        "settlement_damages_cents": damages,
        "settlement_admin_fee_cents": admin_fee,
        "settlement_total_cents": damages + admin_fee,
    }


# ===========================================================================
# calculations.carry_forward_eligibility
# ===========================================================================

def carry_forward_cap(contract):
    return dec_floor(D(contract["contracted_lbs"]) * CARRY_FORWARD_CAP_PCT / D(100), 0)


def carry_forward_eligible(contract):
    cap = carry_forward_cap(contract)
    remaining = contract_remaining(contract)
    return cap if cap < remaining else remaining


def carry_forward_fee(contract, requested_lbs):
    return rhu_int(
        D(requested_lbs) * D(contract["price_per_lb_cents"]) * CARRY_FORWARD_FEE_PCT / D(100)
    )


# ===========================================================================
# calculations.substitution_ranking
# ===========================================================================

def rank_substitutes(shorted_variety, offered_lbs):
    candidates = []
    for variety in db.varieties.values():
        if variety["id"] == shorted_variety["id"]:
            continue
        if variety["substitution_group"] != shorted_variety["substitution_group"]:
            continue
        if D(variety["available_spot_lbs"]) < D(offered_lbs):
            continue
        candidates.append(variety)
    target = D(shorted_variety["alpha_acid_target_pct"])

    def key(variety):
        delta = abs(D(variety["alpha_acid_target_pct"]) - target)
        return (delta, D(variety["spot_price_cents_per_lb"])) + sort_key(variety)

    candidates.sort(key=key)
    return candidates


def alpha_delta(shorted_variety, substitute_variety):
    return rhu(
        abs(
            D(substitute_variety["alpha_acid_target_pct"])
            - D(shorted_variety["alpha_acid_target_pct"])
        ),
        2,
    )


# ===========================================================================
# calculations.malt_spec_match_score
# ===========================================================================

def applicable_diastatic_floor(product, recipe):
    floor_value = D(product["min_diastatic_power"])
    if D(recipe["adjunct_pct"]) > 0:
        floor_value = floor_value + ADJUNCT_DIASTATIC_BUMP
    return floor_value


def _deviation(lot_value, target_value, tolerance):
    if lot_value is None or target_value is None:
        return D(1)
    raw = rhu(abs(D(lot_value) - D(target_value)) / D(tolerance), 4)
    return raw if raw < 1 else D(1)


def spec_match(lot, recipe):
    product = db.malt_products[lot["malt_product_id"]]
    floor_value = applicable_diastatic_floor(product, recipe)
    result = {
        "malt_lot_id": lot["id"],
        "recipe_id": recipe["id"],
        "match_score": None,
        "match_grade": None,
        "deviation_color": None,
        "deviation_extract": None,
        "deviation_protein": None,
        "hard_fail_reason": None,
        "applicable_diastatic_power_floor": floor_value,
    }
    moisture = lot.get("moisture_pct")
    if moisture is not None and D(moisture) > D(product["max_moisture_pct"]):
        result["match_grade"] = "REJECTED"
        result["hard_fail_reason"] = "MOISTURE_ABOVE_MAX"
        return result
    diastatic = lot.get("diastatic_power")
    if diastatic is not None and D(diastatic) < floor_value:
        result["match_grade"] = "REJECTED"
        result["hard_fail_reason"] = "DIASTATIC_POWER_BELOW_MIN"
        return result

    dev_color = _deviation(
        lot.get("color_lovibond"), recipe.get("target_color_lovibond"), TOLERANCE_COLOR
    )
    dev_extract = _deviation(
        lot.get("extract_pct"), recipe.get("target_extract_pct"), TOLERANCE_EXTRACT
    )
    dev_protein = _deviation(
        lot.get("protein_pct"), recipe.get("target_protein_pct"), TOLERANCE_PROTEIN
    )
    weighted = (
        dev_color * WEIGHT_COLOR
        + dev_extract * WEIGHT_EXTRACT
        + dev_protein * WEIGHT_PROTEIN
    )
    score = rhu(D(100) * (D(1) - weighted), 2)
    if score >= GRADE_EXACT_MIN:
        grade = "EXACT"
    elif score >= GRADE_ACCEPTABLE_MIN:
        grade = "ACCEPTABLE"
    elif score >= GRADE_SUBSTITUTE_MIN:
        grade = "SUBSTITUTE_REQUIRED"
    else:
        grade = "REJECTED"
    result["deviation_color"] = dev_color
    result["deviation_extract"] = dev_extract
    result["deviation_protein"] = dev_protein
    result["match_score"] = score
    result["match_grade"] = grade
    return result


# ===========================================================================
# calculations.yeast_pitch_advisory
# ===========================================================================

def pitch_advisory(recipe, strain, pitch_date):
    if strain["fermentation_type"] == "LAGER":
        recommended_rate = LAGER_TARGET_RATE
    else:
        recommended_rate = ALE_TARGET_RATE
    batch_litres = D(recipe["batch_volume_bbl"]) * LITRES_PER_BBL
    required_cells = rhu(
        recommended_rate * D(recipe["original_gravity_plato"]) * batch_litres, 2
    )
    wait_days = whole_days_between(now(), pitch_date)
    if wait_days < 0:
        wait_days = 0
    viability = D(strain["viability_pct_at_ship"]) / D(100) - (
        VIABILITY_DECAY_PER_DAY * D(wait_days)
    )
    if viability < VIABILITY_FLOOR:
        viability = VIABILITY_FLOOR
    viability = rhu(viability, 4)
    slurry = rhu(
        required_cells / (D(strain["cells_per_ml_slurry_billion"]) * viability) / D(1000),
        3,
    )
    volume = rhu(slurry * PROPAGATION_HEADROOM, 3)
    min_batch = D(strain["min_batch_l"])
    if volume < min_batch:
        volume = min_batch
    vessel_max = D(strain["vessel_max_l"])
    if volume > vessel_max:
        volume = vessel_max
    requested = D(recipe["requested_pitch_rate_million_cells_per_ml_per_plato"])
    if requested < recommended_rate * PITCH_BAND_LOW:
        advice = "UNDERPITCH"
    elif requested > recommended_rate * PITCH_BAND_HIGH:
        advice = "OVERPITCH"
    else:
        advice = "OPTIMAL"
    return {
        "recommended_pitch_rate_million_cells_per_ml_per_plato": recommended_rate,
        "required_cells_billion": required_cells,
        "recommended_slurry_l": slurry,
        "propagation_volume_l": volume,
        "pitch_rate_advice": advice,
    }


# ===========================================================================
# calculations.cold_chain_excursion_assessment
# ===========================================================================

def assess_reading(shipment, reading, previous):
    setpoint = D(shipment["reefer_setpoint_c"])
    tolerance = D(shipment["reefer_tolerance_c"])
    low = setpoint - tolerance
    high = setpoint + tolerance
    temp = D(reading["temp_c"])
    in_violation = temp < low or temp > high
    if previous is None:
        interval = 0
        prior_cumulative = 0
    else:
        interval = whole_minutes_between(previous["recorded_at"], reading["recorded_at"])
        if interval < 0:
            interval = 0
        prior_cumulative = int(previous["cumulative_excursion_minutes"])
    cumulative = prior_cumulative + (interval if in_violation else 0)
    reading["in_violation"] = in_violation
    reading["interval_minutes"] = interval
    reading["cumulative_excursion_minutes"] = cumulative
    return cumulative > MAX_EXCURSION_MINUTES
