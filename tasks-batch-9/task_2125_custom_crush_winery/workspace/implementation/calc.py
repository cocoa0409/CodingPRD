"""Calculation rules (SCAFFOLD 1.3 / PRD 3).

Money is always an integer count of cents; every derived monetary figure is
rounded half up to a whole cent, and where a formula sums per-subject or
per-tier segments each segment is rounded BEFORE it joins the running total.
"""

import math
from decimal import Decimal, ROUND_CEILING

from store import rhu, rhu_cents

D = Decimal

# --- intake_yield -------------------------------------------------------------
LBS_PER_TON = D(2000)
BASE_YIELD_GALLONS_PER_TON = D("165.0")
HIGH_BRIX_THRESHOLD = D("25.0")
HIGH_BRIX_STEP_PENALTY = D("5.0")
HIGH_BRIX_SLOPE_PENALTY = D("2.5")
LOW_BRIX_THRESHOLD = D("22.0")
LOW_BRIX_STEP_BONUS = D("3.0")

# --- crush_fee ----------------------------------------------------------------
CRUSH_TIER1_TONS = D(25)
CRUSH_TIER2_TONS = D(75)
CRUSH_TIER1_MULTIPLIER = D("1.00")
CRUSH_TIER2_MULTIPLIER = D("0.90")
CRUSH_TIER3_MULTIPLIER = D("0.80")

# --- labels -------------------------------------------------------------------
VARIETAL_LABEL_MIN_PCT = D("75.00")
APPELLATION_LABEL_MIN_PCT = D("85.00")
BRIX_TO_ALCOHOL_FACTOR = D("0.55")
GENERIC_VARIETAL_LABEL = "RED_BLEND"
GENERIC_APPELLATION_LABEL = "CALIFORNIA"

# --- work_order_billing -------------------------------------------------------
RUSH_SURCHARGE_PCT = D(25)
DISCOUNT_TIER1_CENTS = 1000000
DISCOUNT_TIER1_PCT = D(5)
DISCOUNT_TIER2_CENTS = 3000000
DISCOUNT_TIER2_PCT = D(10)

# --- storage_accrual ----------------------------------------------------------
DAYS_PER_MONTH = D(30)

# --- bottling -----------------------------------------------------------------
ML_PER_GALLON = D("3785.411784")
BOTTLES_PER_CASE = {375: 24, 750: 12, 1500: 6}
LABELS_PER_BOTTLE = 2

# --- excise_tax ---------------------------------------------------------------
EXCISE_TIER1_GALLONS = D(30000)
EXCISE_TIER2_GALLONS = D(130000)
EXCISE_TIER1_CENTS_PER_GALLON = D(7)
EXCISE_TIER2_CENTS_PER_GALLON = D(17)
EXCISE_TIER3_CENTS_PER_GALLON = D(107)

# --- vessel occupancy ---------------------------------------------------------
CLEANING_BUFFER_HOURS = 48


def tons_from_lbs(net_weight_lbs):
    """Tonnage at full precision -- never rounded before it is multiplied."""
    return D(net_weight_lbs) / LBS_PER_TON


def intake_yield(net_weight_lbs, brix):
    """Brix-adjusted juice yield in gallons, 2 dp round half up."""
    tons = tons_from_lbs(net_weight_lbs)
    if brix >= HIGH_BRIX_THRESHOLD:
        adjustment = -(HIGH_BRIX_STEP_PENALTY
                       + (brix - HIGH_BRIX_THRESHOLD) * HIGH_BRIX_SLOPE_PENALTY)
    elif brix <= LOW_BRIX_THRESHOLD:
        adjustment = LOW_BRIX_STEP_BONUS
    else:
        adjustment = D(0)
    return rhu(tons * (BASE_YIELD_GALLONS_PER_TON + adjustment), 2)


def crush_fee(start_tons, load_tons, crush_rate_cents_per_ton):
    """Marginal tiering against the contract's running tonnage."""
    start = D(start_tons)
    end = start + D(load_tons)
    rate = D(crush_rate_cents_per_ton)
    tiers = (
        (D(0), CRUSH_TIER1_TONS, CRUSH_TIER1_MULTIPLIER),
        (CRUSH_TIER1_TONS, CRUSH_TIER2_TONS, CRUSH_TIER2_MULTIPLIER),
        (CRUSH_TIER2_TONS, None, CRUSH_TIER3_MULTIPLIER),
    )
    total = 0
    for low, high, multiplier in tiers:
        seg_lo = max(start, low)
        seg_hi = end if high is None else min(end, high)
        if seg_hi > seg_lo:
            seg_tons = rhu(seg_hi - seg_lo, 4)
            total += rhu_cents(seg_tons * rate * multiplier)
    return total


def excise_tax(start_gallons, gallons):
    """Marginal federal excise tax against the client's YTD taxpaid removals."""
    start = D(start_gallons)
    end = start + D(gallons)
    tiers = (
        (D(0), EXCISE_TIER1_GALLONS, EXCISE_TIER1_CENTS_PER_GALLON),
        (EXCISE_TIER1_GALLONS, EXCISE_TIER2_GALLONS, EXCISE_TIER2_CENTS_PER_GALLON),
        (EXCISE_TIER2_GALLONS, None, EXCISE_TIER3_CENTS_PER_GALLON),
    )
    total = 0
    for low, high, rate in tiers:
        seg_lo = max(start, low)
        seg_hi = end if high is None else min(end, high)
        if seg_hi > seg_lo:
            total += rhu_cents((seg_hi - seg_lo) * rate)
    return total


def dominant(totals, earliest):
    """argmax by gallons DESC, tie-break by the earliest contributing key ASC."""
    if not totals:
        return None, D(0)
    best = None
    for value, gallons in totals.items():
        key = (-gallons, earliest.get(value))
        if best is None or key < best[0]:
            best = (key, value, gallons)
    return best[1], best[2]


def share_pct(part, whole):
    if whole is None or whole == 0:
        return D(0)
    return rhu(D(100) * D(part) / D(whole), 2)


def varietal_label(value, pct):
    return value if pct >= VARIETAL_LABEL_MIN_PCT else GENERIC_VARIETAL_LABEL


def appellation_label(value, pct):
    return value if pct >= APPELLATION_LABEL_MIN_PCT else GENERIC_APPELLATION_LABEL


def lot_composition(intakes):
    """Derive a lot's composition from the ACCEPTED intakes folded into it.

    `intakes` are ordered by the caller; each is the stored intake dict.
    """
    total = sum((D(i["estimated_gallons"]) for i in intakes), D(0))
    volume_gallons = rhu(total, 2)

    if total > 0:
        weighted = sum(
            (D(i["estimated_gallons"]) * D(i["brix"] if i["brix"] is not None else 0)
             for i in intakes), D(0))
        brix_at_crush = rhu(weighted / total, 2)
    else:
        brix_at_crush = D(0)

    var_totals, var_first = {}, {}
    app_totals, app_first = {}, {}
    for intake in intakes:
        gallons = D(intake["estimated_gallons"])
        key = (intake.get("_created_dt"), intake.get("_seq", 0))
        v = intake["varietal"]
        var_totals[v] = var_totals.get(v, D(0)) + gallons
        if v not in var_first or key < var_first[v]:
            var_first[v] = key
        a = intake["appellation"]
        app_totals[a] = app_totals.get(a, D(0)) + gallons
        if a not in app_first or key < app_first[a]:
            app_first[a] = key

    var_value, var_gallons = dominant(var_totals, var_first)
    app_value, app_gallons = dominant(app_totals, app_first)
    var_pct = share_pct(var_gallons, volume_gallons)
    app_pct = share_pct(app_gallons, volume_gallons)

    return {
        "volume_gallons": volume_gallons,
        "brix_at_crush": brix_at_crush,
        "varietal": var_value,
        "appellation": app_value,
        "varietal_share_pct": var_pct,
        "appellation_share_pct": app_pct,
        "varietal_label": varietal_label(var_value, var_pct),
        "appellation_label": appellation_label(app_value, app_pct),
    }


def blend_projection(components, declared_loss_pct, lots_by_id):
    """Projected outcome of a blend trial, measured over the draw."""
    total = rhu(sum((D(c["volume_gallons"]) for c in components), D(0)), 2)
    loss = rhu(total * D(declared_loss_pct) / D(100), 2)
    blend = rhu(total - loss, 2)

    alcohol = None
    if total > 0 and all(
            lots_by_id.get(c["source_lot_id"], {}).get("alcohol_pct") is not None
            for c in components):
        weighted = sum(
            (D(c["volume_gallons"]) * D(lots_by_id[c["source_lot_id"]]["alcohol_pct"])
             for c in components), D(0))
        alcohol = rhu(weighted / total, 2)

    var_totals, var_first = {}, {}
    app_totals, app_first = {}, {}
    for component in components:
        lot = lots_by_id.get(component["source_lot_id"])
        if lot is None:
            continue
        gallons = D(component["volume_gallons"])
        key = (lot.get("_created_dt"), lot.get("_seq", 0))
        v = lot.get("varietal")
        if v is not None:
            var_totals[v] = var_totals.get(v, D(0)) + gallons
            if v not in var_first or key < var_first[v]:
                var_first[v] = key
        a = lot.get("appellation")
        if a is not None:
            app_totals[a] = app_totals.get(a, D(0)) + gallons
            if a not in app_first or key < app_first[a]:
                app_first[a] = key

    var_value, var_gallons = dominant(var_totals, var_first)
    app_value, app_gallons = dominant(app_totals, app_first)
    var_pct = share_pct(var_gallons, total)
    app_pct = share_pct(app_gallons, total)

    return {
        "total_component_gallons": total,
        "projected_loss_gallons": loss,
        "projected_blend_gallons": blend,
        "projected_alcohol_pct": alcohol,
        "varietal": var_value,
        "appellation": app_value,
        "projected_varietal_label": (
            varietal_label(var_value, var_pct) if var_value is not None
            else GENERIC_VARIETAL_LABEL),
        "projected_appellation_label": (
            appellation_label(app_value, app_pct) if app_value is not None
            else GENERIC_APPELLATION_LABEL),
    }


def work_order_billing(actual_labor_hours, crew_size, labor_rate_cents_per_hour,
                       rush, material_cost_cents, contract_billed_total_cents):
    """Five pinned steps; the tier is selected once from the UNDISCOUNTED basis."""
    base_labor_cents = rhu_cents(
        D(actual_labor_hours) * D(crew_size) * D(labor_rate_cents_per_hour))
    rush_surcharge_cents = (
        rhu_cents(D(base_labor_cents) * RUSH_SURCHARGE_PCT / D(100)) if rush else 0)
    subtotal_cents = base_labor_cents + rush_surcharge_cents + int(material_cost_cents)

    tier_basis_cents = int(contract_billed_total_cents) + subtotal_cents
    if tier_basis_cents >= DISCOUNT_TIER2_CENTS:
        volume_discount_pct = DISCOUNT_TIER2_PCT
    elif tier_basis_cents >= DISCOUNT_TIER1_CENTS:
        volume_discount_pct = DISCOUNT_TIER1_PCT
    else:
        volume_discount_pct = D(0)

    discount_cents = rhu_cents(D(subtotal_cents) * volume_discount_pct / D(100))
    billable_amount_cents = subtotal_cents - discount_cents

    return {
        "base_labor_cents": base_labor_cents,
        "rush_surcharge_cents": rush_surcharge_cents,
        "subtotal_cents": subtotal_cents,
        "volume_discount_pct": volume_discount_pct,
        "billable_amount_cents": billable_amount_cents,
    }


def storage_charge(gallons, rate_cents_per_gallon_month, days):
    return rhu_cents(D(gallons) * D(rate_cents_per_gallon_month) * D(days)
                     / DAYS_PER_MONTH)


def bottles_per_case(bottle_size_ml):
    return BOTTLES_PER_CASE[int(bottle_size_ml)]


def run_hours(cases_planned, cases_per_hour):
    """Rounded UP to the next quarter hour."""
    quarters = (D(cases_planned) / D(cases_per_hour)) * D(4)
    quarters = quarters.to_integral_value(rounding=ROUND_CEILING)
    return rhu(quarters / D(4), 2)


def gallons_consumed(cases, bottle_size_ml):
    per_case = bottles_per_case(bottle_size_ml)
    return rhu(D(cases) * D(per_case) * D(int(bottle_size_ml)) / ML_PER_GALLON, 2)


def dry_goods_requirement(cases_planned, bottle_size_ml):
    bottles = int(cases_planned) * bottles_per_case(bottle_size_ml)
    return {
        "BOTTLE": bottles,
        "CORK": bottles,
        "CAPSULE": bottles,
        "LABEL": bottles * LABELS_PER_BOTTLE,
        "CASE_BOX": int(cases_planned),
    }
