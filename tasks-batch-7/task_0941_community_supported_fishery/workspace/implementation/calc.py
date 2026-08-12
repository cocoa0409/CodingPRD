"""Every calculation the PRD pins, in one place."""
import math
from decimal import Decimal
from fractions import Fraction

import constants as C
from money import ceil_int, lb, round_half_up, trunc_lb

ZERO_LB = Decimal("0.00")


def _trunc_fraction(fr):
    """Truncate an exact rational downward to 0.01 lb."""
    n = fr.numerator * 100
    d = fr.denominator
    floored = n // d if fr >= 0 else -((-n) // d + (1 if (-n) % d else 0))
    return (Decimal(floored) / Decimal(100)).quantize(Decimal("0.01"))


# --------------------------------------------------------------------------
# calculations.share_price_per_delivery  (PRD 3.1)
# --------------------------------------------------------------------------

def share_price_per_delivery(share_size, species_tier, delivery_frequency):
    base = Decimal(C.SHARE_SIZE_BASE_CENTS[share_size])
    product = base * C.SPECIES_TIER_MULTIPLIER[species_tier] * \
        C.FREQUENCY_FACTOR[delivery_frequency]
    return round_half_up(product)


def plan_physicals(share_size):
    units = C.SHARE_SIZE_WEIGHT_UNITS[share_size]
    return (units,
            lb(Decimal(units) * C.LB_PER_WEIGHT_UNIT),
            lb(C.SHARE_MIN_FLOOR_LB[share_size]))


# --------------------------------------------------------------------------
# calculations.scheduled_delivery_count  (PRD 3.1)
# --------------------------------------------------------------------------

def scheduled_delivery_count(total_weeks, delivery_frequency):
    if delivery_frequency == "WEEKLY":
        return total_weeks
    return -(-total_weeks // 2)


# --------------------------------------------------------------------------
# calculations.delivery_week_set / promised_delivery_count  (PRD 3.2)
# --------------------------------------------------------------------------

def delivery_week_set(join_week_index, total_weeks, delivery_frequency):
    """PRD 3.2: "the parity of a biweekly schedule is anchored on the join
    week, not on the season"."""
    if delivery_frequency == "WEEKLY":
        return list(range(join_week_index, total_weeks + 1))
    return [w for w in range(join_week_index, total_weeks + 1)
            if (w - join_week_index) % 2 == 0]


def scheduled_at_for_week(start_date, week_index):
    """PRD 3.2: start_date "advanced by seven days for each week beyond the
    first ... preserving the time of day of start_date"."""
    from datetime import timedelta
    return start_date + timedelta(days=7 * (week_index - 1))


# --------------------------------------------------------------------------
# calculations.subscription_commitment_total  (PRD 3.2)
# --------------------------------------------------------------------------

def subscription_commitment_total(list_ppd, payment_basis,
                                  promised_count, plan_scheduled_count):
    if payment_basis == "INSTALLMENT":
        ppd = list_ppd
        commitment = ppd * promised_count
    else:
        ppd = round_half_up(Decimal(list_ppd) * (Decimal(1) - C.PREPAY_DISCOUNT_PCT))
        commitment = ppd * plan_scheduled_count
    return ppd, commitment


# --------------------------------------------------------------------------
# calculations.sustainability_score  (PRD 3.3)
# --------------------------------------------------------------------------

def sustainability_score(gear_type, area_sensitivity_penalty, species_stock_adjustment):
    raw = C.GEAR_BASE_SCORE[gear_type] - area_sensitivity_penalty + species_stock_adjustment
    score = max(0, min(100, raw))
    if score >= C.SUSTAINABILITY_GREEN_MIN:
        band = "GREEN"
    elif score >= C.SUSTAINABILITY_YELLOW_MIN:
        band = "YELLOW"
    elif score >= C.SUSTAINABILITY_ORANGE_MIN:
        band = "ORANGE"
    else:
        band = "RED"
    return score, band


# --------------------------------------------------------------------------
# calculations.quota_debit  (PRD 3.3)
# --------------------------------------------------------------------------

def quota_debit(gross, remaining, allow_partial_fill):
    """Returns (net, discarded) or None when the landing must be refused."""
    if gross <= remaining:
        return lb(gross), ZERO_LB
    if allow_partial_fill:
        return lb(remaining), lb(gross - remaining)
    return None


def ledger_status_after(ledger):
    """PRD 3.3: the consumption thresholds, applied after a debit or a credit."""
    entitlement = ledger["entitlement_pounds"]
    committed = ledger["committed_pounds"]
    remaining = ledger["remaining_pounds"]
    if remaining <= 0:
        return "EXHAUSTED"
    if entitlement > 0 and (Fraction(committed) / Fraction(entitlement)) >= \
            Fraction(C.QUOTA_WARNING_PCT):
        return "WARNING"
    return "OPEN"


# --------------------------------------------------------------------------
# calculations.catch_allocation + surplus_routing  (PRD 3.4)
# --------------------------------------------------------------------------

def catch_allocation(pool, shares):
    """shares: list of dicts {key, weight_units, target, floor} already in the
    fixed order (weight_units DESC, then created_at ASC).

    Returns (variant, {key: Decimal allocated}).
    """
    allocated = {s["key"]: ZERO_LB for s in shares}
    if not shares:
        return "NORMAL_FILL", allocated

    total_units = sum(s["weight_units"] for s in shares)
    if total_units <= 0:
        return "NORMAL_FILL", allocated

    pool_fr = Fraction(pool)
    raws = {s["key"]: pool_fr * s["weight_units"] / total_units for s in shares}
    short = any(raws[s["key"]] < Fraction(s["floor"]) for s in shares)

    if not short:
        # NORMAL_FILL: exact share truncated down, capped at target.
        for s in shares:
            capped = min(_trunc_fraction(raws[s["key"]]), s["target"])
            allocated[s["key"]] = capped
        variant = "NORMAL_FILL"
    else:
        unassigned = lb(pool)
        floored = []
        for s in shares:
            if s["floor"] <= unassigned:
                allocated[s["key"]] = lb(s["floor"])
                unassigned = lb(unassigned - s["floor"])
                floored.append(s)
            else:
                allocated[s["key"]] = ZERO_LB
        if floored and unassigned > 0:
            units2 = sum(s["weight_units"] for s in floored)
            spread = Fraction(unassigned)
            for s in floored:
                extra = _trunc_fraction(spread * s["weight_units"] / units2)
                allocated[s["key"]] = lb(allocated[s["key"]] + extra)
        variant = "SHORT_FILL"

    # Residue pass: one hundredth of a pound at a time, walking the fixed order
    # repeatedly, to deliveries still strictly below their target.
    residue = lb(Decimal(pool) - sum(allocated.values(), ZERO_LB))
    step = C.ALLOCATION_POUND_PRECISION
    if variant == "SHORT_FILL":
        candidates = [s for s in shares if allocated[s["key"]] > 0]
    else:
        candidates = list(shares)
    while residue >= step:
        progressed = False
        for s in candidates:
            if residue < step:
                break
            if allocated[s["key"]] < s["target"]:
                allocated[s["key"]] = lb(allocated[s["key"]] + step)
                residue = lb(residue - step)
                progressed = True
        if not progressed:
            break
    return variant, allocated


def surplus_routing(landed_net, allocated_total):
    surplus = lb(Decimal(landed_net) - Decimal(allocated_total))
    secondary = trunc_lb(Fraction(surplus) * Fraction(C.SURPLUS_SECONDARY_MAX_PCT))
    donated = lb(surplus - secondary)
    return secondary, donated


# --------------------------------------------------------------------------
# calculations.lot_retail_value  (PRD 3.3)
# --------------------------------------------------------------------------

def lot_retail_value(species):
    return C.RETAIL_CENTS_PER_LB[C.SPECIES_TIER_MAP[species]]


# --------------------------------------------------------------------------
# calculations.substitution_value_settlement  (PRD 3.5)
# --------------------------------------------------------------------------

def substitution_value_settlement(target_pounds, allocated_pounds, plan_tier,
                                  substitute_pounds, substitute_retail_per_lb,
                                  subtotal_cap_cents):
    shortfall = lb(Decimal(target_pounds) - Decimal(allocated_pounds))
    owed = round_half_up(Fraction(shortfall) * C.RETAIL_CENTS_PER_LB[plan_tier])
    sub_value = round_half_up(Fraction(substitute_pounds) * substitute_retail_per_lb)
    if sub_value >= owed:
        return shortfall, owed, sub_value, "EQUAL_OR_GREATER", 0
    credit = min(owed - sub_value, subtotal_cap_cents)
    return shortfall, owed, sub_value, "BELOW_VALUE", credit


# --------------------------------------------------------------------------
# calculations.cold_chain_budget_evaluation  (PRD 3.6)
# --------------------------------------------------------------------------

def breach_type(this_minutes, cumulative_minutes):
    single = this_minutes > C.COLD_CHAIN_SINGLE_EXCURSION_MAX_MIN
    cumulative = cumulative_minutes > C.COLD_CHAIN_CUMULATIVE_BUDGET_MIN
    if single and cumulative:
        return "BOTH"
    if single:
        return "SINGLE_EXCURSION"
    if cumulative:
        return "CUMULATIVE"
    return "NONE"


# --------------------------------------------------------------------------
# calculations.pack_size_selection + gel_pack_count  (PRD 3.7)
# --------------------------------------------------------------------------

def pack_size_selection(fulfillment_mode, box_pounds):
    if fulfillment_mode == "HUB_PICKUP":
        return "NONE"
    if box_pounds <= C.PACK_SMALL_MAX_LB:
        return "SMALL"
    if box_pounds <= C.PACK_MEDIUM_MAX_LB:
        return "MEDIUM"
    return "LARGE"


def gel_pack_count(fulfillment_mode, ambient_band, pack_size, transit_hours):
    if fulfillment_mode == "HUB_PICKUP":
        return 0
    hours_per_pack = C.GEL_PACK_HOURS[ambient_band][pack_size]
    return max(1, ceil_int(Decimal(transit_hours) / hours_per_pack))


# --------------------------------------------------------------------------
# calculations.member_week_invoice  (PRD 3.7) -- evaluation order is pinned
# --------------------------------------------------------------------------

def member_week_invoice(price_per_delivery_cents, fulfillment_mode, pack_size,
                        gel_packs, zone_fee_tier):
    # step 1
    subtotal = price_per_delivery_cents
    # step 2
    if fulfillment_mode == "HUB_PICKUP":
        pack_cost = 0
        zone_base = 0
    else:
        pack_cost = C.PACK_BASE_FEE_CENTS[pack_size] + gel_packs * C.GEL_PACK_FEE_CENTS
        zone_base = C.ZONE_BASE_FEE_CENTS[zone_fee_tier]
    # step 3 -- the waiver test reads subtotal_cents and NOTHING else.
    if fulfillment_mode == "HUB_PICKUP":
        surcharge = 0
    elif subtotal >= C.FREE_SURCHARGE_THRESHOLD_CENTS:
        surcharge = 0
    else:
        surcharge = C.REMOTE_SURCHARGE_CENTS
    # step 4
    delivery_fee = zone_base + pack_cost + surcharge
    # step 5
    invoice_total = subtotal + delivery_fee
    return subtotal, surcharge, delivery_fee, invoice_total


# --------------------------------------------------------------------------
# calculations.no_show_escalation  (PRD 3.7)
# --------------------------------------------------------------------------

def standing_for(no_show_count, current):
    if no_show_count >= C.NO_SHOW_RESTRICT_THRESHOLD:
        return "RESTRICTED"
    if no_show_count >= C.NO_SHOW_WARN_THRESHOLD:
        return "WARNED"
    return current


# --------------------------------------------------------------------------
# calculations.skip_credit_expiry  (PRD 3.9)
# --------------------------------------------------------------------------

def skip_credit_expiry(commitment_cents, paid_cents, skip_credit_balance_cents):
    outstanding = max(0, commitment_cents - paid_cents)
    applied = min(skip_credit_balance_cents, outstanding)
    return applied, skip_credit_balance_cents - applied


# --------------------------------------------------------------------------
# calculations.vendor_settlement_gross / deductions / holdback  (PRD 3.9)
# --------------------------------------------------------------------------

def vendor_settlement_gross(landed_net, ex_vessel_price_cents_per_lb, band):
    p = Fraction(landed_net)
    ex_vessel = round_half_up(Fraction(ex_vessel_price_cents_per_lb) * p)
    b1 = min(p, Fraction(C.CSF_PREMIUM_BRACKET_1_MAX_LB))
    b2 = max(min(p, Fraction(C.CSF_PREMIUM_BRACKET_2_MAX_LB)) -
             Fraction(C.CSF_PREMIUM_BRACKET_1_MAX_LB), Fraction(0))
    b3 = max(p - Fraction(C.CSF_PREMIUM_BRACKET_2_MAX_LB), Fraction(0))
    raw = (b1 * C.CSF_PREMIUM_RATE_1_CENTS_PER_LB +
           b2 * C.CSF_PREMIUM_RATE_2_CENTS_PER_LB +
           b3 * C.CSF_PREMIUM_RATE_3_CENTS_PER_LB)
    premium = round_half_up(raw * Fraction(C.BAND_PREMIUM_FACTOR[band]))
    return ex_vessel, premium, ex_vessel + premium


def vendor_settlement_deductions(landed_net, offload_minutes, gross_cents):
    """The rounding order is pinned: each line is rounded on its own and only
    the already-rounded lines are summed (PRD 3.9)."""
    dock = C.DOCK_FEE_CENTS
    ice = round_half_up(Fraction(landed_net) * C.ICE_HANDLING_CENTS_PER_LB)
    labor = round_half_up(Fraction(offload_minutes) * C.OFFLOAD_LABOR_CENTS_PER_MINUTE)
    levy = round_half_up(Fraction(gross_cents) * Fraction(C.HANDLING_LEVY_PCT))
    # Adjudication of friction 7: deductions_cents sums FOUR individually
    # rounded lines (dock + ice + offload labour + handling levy), not three.
    # PRD 3.9's formula names four lines and its worked example adds four
    # (800 + 120 + 1140 + 114 = 2174); only the SettlementStatement field
    # description says "three", and a description cannot outrank the formula
    # plus the arithmetic that the rest of PRD 3.9 is built on.
    return dock, ice, labor, levy, dock + ice + labor + levy


def holdback_cents(gross_cents):
    return round_half_up(Fraction(gross_cents) * Fraction(C.HOLDBACK_PCT))


def settlement_final(quality_status, gross, deductions, holdback, ex_vessel):
    if quality_status in ("CLEAR", "RELEASED"):
        released, forfeited, offset = holdback, 0, 0
    elif quality_status == "DISCOUNTED":
        released = round_half_up(
            Fraction(holdback) * Fraction(C.VENDOR_DISCOUNT_HOLDBACK_RELEASE_PCT))
        forfeited = holdback - released
        offset = 0
    else:  # DISCARDED
        released = 0
        forfeited = holdback
        offset = min(round_half_up(Fraction(ex_vessel) * Fraction(C.DISCARD_OFFSET_PCT)),
                     gross - deductions - holdback)
    net_payable = gross - deductions - forfeited - offset
    return released, forfeited, offset, net_payable


# --------------------------------------------------------------------------
# calculations.transfer_settlement  (PRD 3.8)
# --------------------------------------------------------------------------

def transfer_settlement(remaining_delivery_count, ppd, payment_basis):
    fee = C.TRANSFER_FEE_CENTS
    if payment_basis == "PREPAID_FULL_SEASON":
        charge = remaining_delivery_count * ppd
        return "PREPAID", fee, charge - fee, charge
    charge = remaining_delivery_count * ppd + fee
    return "INSTALLMENT", fee, 0, charge
