"""Calculation rules (SCAFFOLD §1.3 / PRD section 3).

Money is integer cents throughout; every fractional cent is rounded HALF UP
(away from zero on a tie). Floats never touch a monetary computation: every
percentage crosses into Decimal through its string form so that 1010 * 0.15
evaluates to exactly 151.50 and rounds to 152 (PRD 3.7 step eight).
"""

from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

import constants as C
import store


def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(value)


def round_half_up(value):
    """Round a Decimal to a whole cent, half away from zero."""
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_places(value, places):
    exp = Decimal(1).scaleb(-places)
    return dec(value).quantize(exp, rounding=ROUND_HALF_UP)


def floor_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_FLOOR))


# ---------------------------------------------------------------------------
# stage_from_weight
# ---------------------------------------------------------------------------
def raw_stage(weight_grams):
    """Lower bound INCLUSIVE, upper bound EXCLUSIVE; a boundary weight belongs
    to the UPPER band (6400 -> S2)."""
    for name, lo, hi in C.STAGE_BANDS:
        if lo <= weight_grams < hi:
            return name
    if weight_grams >= C.STAGE_BANDS[-1][2]:
        return C.STAGE_BANDS[-1][0]
    return C.STAGE_BANDS[0][0]


def clamped_stage(current_stage, weight_grams):
    """Never more than MAX_STAGE_STEP_PER_RESIZE positions from the current band."""
    target = raw_stage(weight_grams)
    if current_stage is None:
        return target
    i_cur = C.STAGE_ORDER.index(current_stage)
    i_raw = C.STAGE_ORDER.index(target)
    if i_raw == i_cur:
        return current_stage
    direction = 1 if i_raw > i_cur else -1
    step = direction * min(abs(i_raw - i_cur), C.MAX_STAGE_STEP_PER_RESIZE)
    return C.STAGE_ORDER[i_cur + step]


def stage_distance(a, b):
    return abs(C.STAGE_ORDER.index(a) - C.STAGE_ORDER.index(b))


# ---------------------------------------------------------------------------
# cadence_interval_days
# ---------------------------------------------------------------------------
def cadence_interval_days(pack_count, consumption_rate_per_day, override_days):
    if override_days is not None:
        return int(override_days)
    derived = round_half_up(
        dec(pack_count) * dec(C.UNITS_PER_PACK_DEFAULT) / dec(consumption_rate_per_day))
    return min(C.CADENCE_MAX_INTERVAL_DAYS,
               max(C.CADENCE_MIN_INTERVAL_DAYS, derived))


# ---------------------------------------------------------------------------
# line_unit_price_cents / gift_order_total_cents (SHARED RUNG)
# ---------------------------------------------------------------------------
def effective_unit_price(sku):
    surcharge = C.HYPOALLERGENIC_SURCHARGE_CENTS if sku["line"] == "HYPOALLERGENIC" else 0
    return int(sku["pack_price_cents"]) + surcharge


# ---------------------------------------------------------------------------
# sku_allergen_eligibility (SHARED RUNG)
# ---------------------------------------------------------------------------
def child_flag_tags(child_id):
    severe = set()
    mild = set()
    for flag in store.db.allergen_flags.values():
        if flag["child_id"] != child_id:
            continue
        if flag["severity"] == "SEVERE":
            severe.add(flag["allergen_tag"])
        else:
            mild.add(flag["allergen_tag"])
    return severe, mild


def allergen_eligible(sku, child):
    tags = set(sku.get("allergen_tags") or [])
    severe, mild = child_flag_tags(child["id"])
    if tags & severe:
        return False
    if (tags & mild) and sku["line"] == "STANDARD":
        return False
    return True


def hypo_required_ok(sku, child):
    """A child with hypoallergenic_required never receives a STANDARD SKU."""
    if child.get("hypoallergenic_required") and sku["line"] == "STANDARD":
        return False
    return True


def plan_allows_ok(sku, plan):
    """A plan with allows_hypoallergenic false never receives a HYPOALLERGENIC SKU."""
    if plan is not None and not plan.get("allows_hypoallergenic") and \
            sku["line"] == "HYPOALLERGENIC":
        return False
    return True


def rank_key(sku):
    """pack_price_cents ASC, pack_size_units DESC, created_at ASC.
    Sku.id is NEVER a sort key."""
    return (int(sku["pack_price_cents"]), -int(sku["pack_size_units"]),
            sku["created_at"], sku["_seq"])


# ---------------------------------------------------------------------------
# shipping_cents
# ---------------------------------------------------------------------------
def total_units(lines):
    total = 0
    for line in lines:
        sku = store.db.skus.get(line["sku_id"])
        size = int(sku["pack_size_units"]) if sku else 0
        total += int(line["quantity_packs"]) * size
    return total


def shipping_cents(subtotal, units, free_shipping_eligible):
    if free_shipping_eligible:
        return 0
    if subtotal >= C.FREE_SHIPPING_SUBTOTAL_CENTS:
        return 0
    fee = C.SHIPPING_BASE_CENTS
    if units > C.SHIPPING_HEAVY_THRESHOLD_UNITS:
        fee += C.SHIPPING_HEAVY_SURCHARGE_CENTS
    return fee


# ---------------------------------------------------------------------------
# credit stack
# ---------------------------------------------------------------------------
def credit_pool_key(credit):
    """expires_at ASC then created_at ASC; never by identifier."""
    return (credit["expires_at"], credit["created_at"], credit["_seq"])


def spendable(credit, now):
    return (credit["status"] in ("AVAILABLE", "PARTIALLY_CONSUMED")
            and credit["expires_at"] > now)


def referral_cap(base):
    return round_half_up(dec(base) * dec(C.REFERRAL_CREDIT_MAX_PCT))


def loyalty_cap(after_ref):
    return round_half_up(dec(after_ref) * dec(C.LOYALTY_REDEMPTION_MAX_PCT))


def loyalty_redemption(after_ref, points_balance):
    """The floor applies TWICE: once to the balance and once to the points
    actually burned (PRD 3.7 step six)."""
    cap = loyalty_cap(after_ref)
    if points_balance < C.POINT_REDEMPTION_FLOOR_POINTS:
        return 0, 0
    applied = min(cap, after_ref, points_balance * C.POINT_VALUE_CENTS)
    if applied < 0:
        applied = 0
    points = applied // C.POINT_VALUE_CENTS
    if points < C.POINT_REDEMPTION_FLOOR_POINTS:
        return 0, 0
    return applied, points


def promo_discount(lines, promo_pct, after_loyalty_amount):
    """PINNED ROUNDING ORDER: round PER LINE first, then sum."""
    pct = dec(promo_pct or 0)
    raw = 0
    for line in lines:
        raw += round_half_up(dec(line["line_total_cents"]) * pct)
    return min(raw, after_loyalty_amount)


# ---------------------------------------------------------------------------
# points
# ---------------------------------------------------------------------------
def points_earn_base_cents(cycle):
    return max(0, int(cycle["subtotal_cents"])
               - int(cycle["gift_credit_applied_cents"])
               - int(cycle["promo_discount_cents"]))


TIER_MULTIPLIERS = {
    "BRONZE": C.TIER_MULTIPLIER_BRONZE,
    "SILVER": C.TIER_MULTIPLIER_SILVER,
    "GOLD": C.TIER_MULTIPLIER_GOLD,
}


def points_earned(base_cents, tier):
    multiplier = dec(TIER_MULTIPLIERS.get(tier, C.TIER_MULTIPLIER_BRONZE))
    whole = base_cents // C.POINTS_EARN_DIVISOR_CENTS
    return floor_int(dec(whole) * multiplier)


def tier_for(trailing_points):
    if trailing_points >= C.TIER_GOLD_THRESHOLD_POINTS:
        return "GOLD"
    if trailing_points >= C.TIER_SILVER_THRESHOLD_POINTS:
        return "SILVER"
    return "BRONZE"


TIER_RANK = {"BRONZE": 0, "SILVER": 1, "GOLD": 2}


# ---------------------------------------------------------------------------
# proration / cancellation refund
# ---------------------------------------------------------------------------
def used_fraction(dispatched_at, cadence_interval_days_value, now):
    if dispatched_at is None or not cadence_interval_days_value:
        return dec(0)
    elapsed_seconds = (now - dispatched_at).total_seconds()
    days_elapsed = floor_int(dec(elapsed_seconds) / dec(86400))
    fraction = dec(days_elapsed) / dec(cadence_interval_days_value)
    if fraction < 0:
        return dec(0)
    if fraction > 1:
        return dec(1)
    return fraction


def cancel_refund_cents(cycle, cadence_days, now, status_override=None):
    """Dual variant, keyed on the cycle's fulfilment status.
    Returns (requested_cents, restock_fee_cents)."""
    status = status_override or cycle["status"]
    charged = int(cycle["charged_cash_cents"])
    if status in ("PLANNED", "ALLOCATED", "CUTOFF_LOCKED"):
        return charged, 0
    if status in ("DISPATCHED", "DELIVERED"):
        fraction = used_fraction(cycle["dispatched_at"], cadence_days, now)
        gross = round_half_up(dec(charged) * (dec(1) - fraction))
        return max(0, gross - C.RESTOCK_FEE_CENTS), C.RESTOCK_FEE_CENTS
    # RETURNED / CANCELLED / SKIPPED carry no declared variant.
    return 0, 0


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------
def registry_completion_pct(requested, fulfilled):
    if requested == 0:
        return 0
    value = round_half_up_places(dec(fulfilled) / dec(requested), 4)
    return float(value)


# ---------------------------------------------------------------------------
# referral credit
# ---------------------------------------------------------------------------
def referral_credit_amount_cents(vesting_instant):
    start = store.parse_instant(C.REFERRAL_PROMO_WINDOW_START_UTC)
    end = store.parse_instant(C.REFERRAL_PROMO_WINDOW_END_UTC)
    if start <= vesting_instant < end:
        return C.REFERRAL_CREDIT_CENTS * C.REFERRAL_PROMO_MULTIPLIER
    return C.REFERRAL_CREDIT_CENTS


# ---------------------------------------------------------------------------
# shipment
# ---------------------------------------------------------------------------
def shipment_eta_days(service_level):
    if service_level == "EXPEDITED":
        return C.SHIPMENT_ETA_DAYS_EXPEDITED
    return C.SHIPMENT_ETA_DAYS_STANDARD
