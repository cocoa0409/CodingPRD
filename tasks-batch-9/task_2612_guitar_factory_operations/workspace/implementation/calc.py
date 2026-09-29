"""Every calculation in PRD 3.  Integer cents, integer basis points, and
decimal.Decimal with ROUND_HALF_UP -- never floats for money."""

from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR

import store
from constants import *  # noqa: F401,F403

ZERO = Decimal("0")
BP = Decimal("10000")


def rhu(value, places=0):
    quant = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def cents(value):
    return int(rhu(value, 0))


def bf(value):
    return rhu(value, 2)


def apply_bp(amount, basis_points):
    return cents(Decimal(amount) * Decimal(basis_points) / BP)


# ------------------------------------------------- custom shop quote total ----

def _quote_rows(order, statuses):
    rows = [s for s in store.SELECTIONS.values()
            if s["build_order_id"] == order["id"] and s["status"] in statuses]
    rows.sort(key=lambda s: (store.CATALOG[s["option_id"]]["option_code"],
                             s["created_at"], s["_seq"]))
    return rows


def compute_quote(order, statuses, use_locked, persist=True):
    """Round each line, then sum: the order is pinned by PRD 3.6."""
    subtotal = 0
    for sel in _quote_rows(order, statuses):
        option = store.CATALOG[sel["option_id"]]
        if use_locked:
            unit = sel.get("locked_upcharge_cents")
            if unit is None:
                unit = option["upcharge_cents"]
        else:
            unit = option["upcharge_cents"]
        mult = COMPLEXITY_MULTIPLIER_BP[option["complexity_class"]]
        line = cents(Decimal(unit) * Decimal(sel["quantity"]) * Decimal(mult) / BP)
        if persist:
            sel["line_total_cents"] = line
        subtotal += line
    pre_discount = subtotal + order["base_price_cents"]
    surcharge = (apply_bp(pre_discount, CUSTOM_SHOP_SURCHARGE_BP)
                 if order["is_custom_shop"] else 0)
    discount = apply_bp(subtotal, ARTIST_DISCOUNT_BP[order["artist_tier"]])
    return pre_discount + surcharge - discount


def refresh_provisional_quote(order):
    order["provisional_quote_total_cents"] = compute_quote(
        order, ("PENDING_APPROVAL", "SELECTED"), use_locked=False, persist=True)
    return order["provisional_quote_total_cents"]


def compute_binding_quote(order):
    order["binding_quote_total_cents"] = compute_quote(
        order, ("LOCKED",), use_locked=True, persist=True)
    return order["binding_quote_total_cents"]


# ----------------------------------------------------- tonewood lot yield -----

def shrink_bp(moisture_pct):
    excess = Decimal(moisture_pct) - TARGET_MOISTURE_PCT
    if excess < 0:
        excess = ZERO
    return excess * Decimal(SHRINK_BP_PER_PCT)


def nominal_yield(lot):
    factor = (BP - shrink_bp(lot["moisture_at_receipt_pct"])
              - Decimal(NOMINAL_KERF_BP)) / BP
    return bf(Decimal(lot["board_feet_received"]) * factor)


def cut_total(lot):
    rows = [b for b in store.BILLETS.values()
            if b["lot_id"] == lot["id"] and b["status"] != "QUARANTINED"]
    rows.sort(key=lambda b: (b["created_at"], b["billet_code"], b["_seq"]))
    total = ZERO
    for row in rows:
        total += Decimal(row["board_feet"])
    return bf(total)


def actual_yield(lot):
    factor = (BP - shrink_bp(lot["moisture_content_pct"])) / BP
    return bf(cut_total(lot) * factor)


def kerf_for(board_feet):
    return bf(Decimal(board_feet) * Decimal(ACTUAL_KERF_BP) / BP)


def board_feet_cut_mirror(lot):
    return bf(Decimal(lot["board_feet_unassigned"])
              + Decimal(lot["board_feet_reserved"])
              + Decimal(lot["board_feet_consumed"])
              + Decimal(lot["board_feet_scrapped"]))


# ------------------------------------------------------ finish cure timing ----

def booth_hold_hours(finish_system, coat_count):
    base = BASE_CURE_HOURS[finish_system]
    extra = max(0, coat_count - BASE_COATS[finish_system])
    return SPRAY_HOURS + base + extra * PER_EXTRA_COAT_HOURS[finish_system]


def cure_hours_for(finish_system, coat_count, latest_rh, latest_temp):
    base = BASE_CURE_HOURS[finish_system]
    extra = max(0, coat_count - BASE_COATS[finish_system])
    coat_hours = base + extra * PER_EXTRA_COAT_HOURS[finish_system]

    rh_excess = Decimal(latest_rh) - RH_NOMINAL_PCT
    if rh_excess < 0:
        rh_excess = ZERO
    rh_steps = int((rh_excess / RH_STEP_PCT).to_integral_value(
        rounding=ROUND_CEILING))
    rh_penalty = rh_steps * RH_PENALTY_HOURS_PER_STEP

    temp_excess = Decimal(latest_temp) - TEMP_NOMINAL_C
    if temp_excess < 0:
        temp_excess = ZERO
    temp_steps = int((temp_excess / TEMP_STEP_C).to_integral_value(
        rounding=ROUND_FLOOR))
    temp_relief = min(TEMP_RELIEF_CAP_HOURS,
                      temp_steps * TEMP_RELIEF_HOURS_PER_STEP)

    return max(MIN_CURE_HOURS[finish_system],
               coat_hours + rh_penalty - temp_relief)


# ------------------------------------------------ export declared value -------

def doc_fee_tier(goods_value_cents):
    if goods_value_cents <= TIER_1_MAX_CENTS:
        return "TIER_1"
    if goods_value_cents <= TIER_2_MAX_CENTS:
        return "TIER_2"
    return "TIER_3"


def price_declaration(goods_value_cents, cites_required):
    tier = doc_fee_tier(goods_value_cents)
    doc_fee = max(apply_bp(goods_value_cents, DOC_FEE_BP_BY_TIER[tier]),
                  DOC_FEE_MIN_CENTS)
    if cites_required:
        doc_fee += CITES_ENDORSEMENT_FEE_CENTS
    insurance = apply_bp(goods_value_cents + doc_fee, INSURANCE_BP)
    declared = goods_value_cents + doc_fee + insurance
    return doc_fee, insurance, declared


# ---------------------------------------------- playability deviation score ---

def deviation_score(treble_mm, bass_mm, relief_mm, intonation_cents):
    t = int(rhu(Decimal(treble_mm) * 100, 0))
    b = int(rhu(Decimal(bass_mm) * 100, 0))
    r = int(rhu(Decimal(relief_mm) * 100, 0))
    i = int(rhu(Decimal(intonation_cents) * 10, 0))
    weighted = (max(0, t - ACTION_TREBLE_LIMIT) * ACTION_TREBLE_WEIGHT
                + max(0, b - ACTION_BASS_LIMIT) * ACTION_BASS_WEIGHT
                + max(0, r - RELIEF_LIMIT) * RELIEF_WEIGHT
                + max(0, i - INTONATION_LIMIT) * INTONATION_WEIGHT)
    return rhu(Decimal(weighted) / Decimal(1000), 2)


# ------------------------------------------------------- priority scoring -----

def priority_score(order):
    points = Decimal(ARTIST_TIER_POINTS[order["artist_tier"]])
    if order["is_custom_shop"]:
        points += Decimal(CUSTOM_SHOP_POINTS)
    if order["commercial_status"] == "AT_RISK":
        points += Decimal(AT_RISK_POINTS)
    days_out = store.whole_days_between(store.now_utc(), order["promised_date"])
    remaining = LEAD_HORIZON_DAYS - days_out
    if remaining < 0:
        remaining = 0
    points += Decimal(remaining) * SLIP_POINTS_PER_DAY
    return rhu(points, 2)


def refresh_priority(order):
    order["priority_score"] = priority_score(order)
    return order["priority_score"]


# ------------------------------------------------ protected species posture ---

def contributing_lots(order):
    """Lots behind the components of this order in ACCEPTED or INSTALLED."""
    lots = {}
    for comp in store.COMPONENTS.values():
        if comp["build_order_id"] != order["id"]:
            continue
        if comp["status"] not in ("ACCEPTED", "INSTALLED"):
            continue
        billet = store.BILLETS.get(comp["billet_id"])
        if billet is None:
            continue
        lot = store.LOTS.get(billet["lot_id"])
        if lot is not None:
            lots[lot["id"]] = lot
    return list(lots.values())


def refresh_protected_species(order):
    strictest = "NONE"
    for lot in contributing_lots(order):
        appendix = lot["cites_appendix"]
        if APPENDIX_STRICTNESS.get(appendix, 0) > APPENDIX_STRICTNESS[strictest]:
            strictest = appendix
    order["strictest_cites_appendix"] = strictest
    order["cites_permit_required"] = strictest != "NONE"
    return strictest


# --------------------------------------------------------------- deposits -----

def min_deposit_cents(order):
    return apply_bp(order["provisional_quote_total_cents"], MIN_DEPOSIT_BP)


def min_settle_cents(order):
    return apply_bp(order.get("binding_quote_total_cents") or 0, MIN_SETTLE_BP)


def cancellation_disposition(order):
    if order["commercial_status"] in ("OPTIONS_LOCKED", "AT_RISK"):
        basis = order.get("binding_quote_total_cents") or 0
    else:
        basis = order["provisional_quote_total_cents"]
    held = order["deposit_held_cents"]
    forfeit = min(held, apply_bp(basis, CANCEL_FORFEIT_BP))
    return forfeit, held - forfeit


# ----------------------------------------------------- serial assignment ------

def next_serial(order):
    year = store.now_utc().year
    prefix_year = "%04d" % year
    count = 0
    for row in store.ORDERS.values():
        serial = row.get("serial_number")
        if not serial or row["model_code"] != order["model_code"]:
            continue
        parts = serial.rsplit("-", 2)
        if len(parts) == 3 and parts[1] == prefix_year:
            count += 1
    return "%s-%s-%05d" % (order["model_code"], prefix_year, count + 1)


# ------------------------------------------------------ warranty coverage -----

def coverage_months(order):
    return COVERAGE_MONTHS_CUSTOM if order["is_custom_shop"] \
        else COVERAGE_MONTHS_STANDARD
