"""Business-logic services: calculations, reconciliation, cascades.

All money is integer cents. Decimal is used for any rounding so we never touch
IEEE-754 float. Rounding disciplines per PRD 2.7:
  - per-term CEILING for area / labor / equipment-hour terms
  - ROUND_HALF_UP, applied per bucket (add-on) or once after aggregation (tax/storm)
"""

import math
from decimal import Decimal, ROUND_HALF_UP

import db

# --- Calculation constants (SCAFFOLD 1.3) ---
AREA_DIVISOR_SQFT = 1000

ADDON_TIER1_QTY = 10
ADDON_TIER2_QTY = 50
ADDON_DISCOUNT_T2 = Decimal("0.10")
ADDON_DISCOUNT_T3 = Decimal("0.20")

STORM_TIER_LIGHT_MAX = 3
STORM_TIER_HEAVY_MAX = 8
STORM_BASE_LIGHT_CENTS = 15000
STORM_BASE_MODERATE_CENTS = 30000
STORM_BASE_HEAVY_CENTS = 60000
STORM_PRIORITY_SURCHARGE = Decimal("0.25")

TAX_RATE = Decimal("0.0825")

# Inspection grading thresholds (PRD 3.9 / SCAFFOLD state machine).
# The PRD/scaffold pin the routing semantics symbolically (PASS_THRESHOLD,
# REWORK_FLOOR, MAX_REWORK) on a 0..100 score scale; concrete values below.
PASS_THRESHOLD = 80
REWORK_FLOOR = 60
MAX_REWORK = 2


def _round_half_up(value):
    """Round a Decimal to the nearest whole cent, half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# =========================================================================
# Visit charges (dual-variant: estimate vs final)
# =========================================================================
def _area_factor(plan, site):
    # ceil(base_rate_cents * turf_area_sqft / 1000)
    return math.ceil(plan["base_rate_cents"] * site["turf_area_sqft"] / AREA_DIVISOR_SQFT)


def _approved_addons_total(visit_id):
    total = 0
    for a in db.ADDONS.values():
        if a["service_visit_id"] == visit_id and a["status"] == "APPROVED":
            total += a["addon_charge_cents"]
    return total


def visit_estimated_charge(visit, plan, site, crew):
    """Provisional charge from planned inputs (SCAFFOLD visit_estimated_charge).
    area_factor + planned_labor_cost + approved_addons; ceil per term."""
    area_factor = _area_factor(plan, site)
    planned_labor_cost = math.ceil(crew["hourly_rate_cents"] * visit["slot_duration_minute"] / 60)
    approved_addons = _approved_addons_total(visit["id"])
    return area_factor + planned_labor_cost + approved_addons


def visit_final_charge(visit, plan, site, crew):
    """Final charge from actuals (SCAFFOLD visit_final_charge).
    area_factor + actual_labor_cost + equipment_cost + approved_addons; ceil per term.
    equipment_cost sums usage_cost over RESERVED/CONSUMED reservations of this visit."""
    area_factor = _area_factor(plan, site)
    actual_labor_cost = math.ceil(crew["hourly_rate_cents"] * visit["actual_labor_minutes"] / 60)
    equipment_cost = 0
    for r in db.RESERVATIONS.values():
        if r["service_visit_id"] == visit["id"] and r["status"] in ("RESERVED", "CONSUMED"):
            equipment_cost += r["usage_cost_cents"]
    approved_addons = _approved_addons_total(visit["id"])
    return area_factor + actual_labor_cost + equipment_cost + approved_addons


def recompute_visit_estimate(visit):
    """Recompute estimated_charge_cents in place (e.g., after addon approval)."""
    plan = db.PLANS[visit["service_plan_id"]]
    site = db.SITES[plan["site_id"]]
    crew = db.CREWS[visit["crew_id"]]
    visit["estimated_charge_cents"] = visit_estimated_charge(visit, plan, site, crew)


# =========================================================================
# Add-on tiered pricing
# =========================================================================
def addon_charge(quantity, unit_price_cents):
    """Marginal volume tiers; round_half_up PER BUCKET before summation
    (SCAFFOLD addon_charge)."""
    t1_units = min(quantity, ADDON_TIER1_QTY)
    t2_units = max(0, min(quantity, ADDON_TIER2_QTY) - ADDON_TIER1_QTY)
    t3_units = max(0, quantity - ADDON_TIER2_QTY)

    bucket1 = t1_units * unit_price_cents
    bucket2 = _round_half_up(Decimal(t2_units * unit_price_cents) * (Decimal(1) - ADDON_DISCOUNT_T2))
    bucket3 = _round_half_up(Decimal(t3_units * unit_price_cents) * (Decimal(1) - ADDON_DISCOUNT_T3))
    return bucket1 + bucket2 + bucket3


# =========================================================================
# Storm dispatch
# =========================================================================
def storm_dispatch_charge(snowfall_inches, snow_zone):
    """Snowfall tier base * priority surcharge; round_half_up (SCAFFOLD storm_dispatch_charge).
    Strict-< tier boundaries at 3 and 8 inches."""
    if snowfall_inches < STORM_TIER_LIGHT_MAX:
        base = STORM_BASE_LIGHT_CENTS
    elif snowfall_inches < STORM_TIER_HEAVY_MAX:
        base = STORM_BASE_MODERATE_CENTS
    else:
        base = STORM_BASE_HEAVY_CENTS
    if snow_zone == "PRIORITY":
        mult = Decimal(1) + STORM_PRIORITY_SURCHARGE
    else:
        mult = Decimal(1)
    return _round_half_up(Decimal(base) * mult)


def storm_crew_selector(service_account_id):
    """Cheapest certified crew under the account, tie-break earliest created_at.
    Returns the crew record or None if the certified pool is empty
    (SCAFFOLD storm_crew_selector)."""
    candidates = [
        c for c in db.CREWS.values()
        if c["service_account_id"] == service_account_id and c.get("certified_for_snow") is True
    ]
    if not candidates:
        return None
    # Rank by hourly_rate_cents ASC, tie-break created_at ASC (use _seq for a
    # stable, strictly-increasing proxy of creation order).
    candidates.sort(key=lambda c: (c["hourly_rate_cents"], c["created_at"], c["_seq"]))
    return candidates[0]


# =========================================================================
# Equipment usage cost
# =========================================================================
def equipment_usage_cost(reserved_minutes, hourly_usage_cost_cents):
    """ceil(reserved_minutes/60) * hourly_usage_cost_cents (SCAFFOLD equipment_usage_cost)."""
    return math.ceil(reserved_minutes / 60) * hourly_usage_cost_cents


# =========================================================================
# Invoice sweep / total
# =========================================================================
def invoice_sweep(contract_id):
    """Select COMPLETED + UNBILLED visits of this contract.
    Returns (swept_visit_ids, line_item_count, subtotal_cents)."""
    swept = [
        v for v in db.VISITS.values()
        if v["service_contract_id"] == contract_id
        and v["execution_status"] == "COMPLETED"
        and v["billing_status"] == "UNBILLED"
    ]
    line_item_count = len(swept)
    subtotal_cents = sum(v["final_charge_cents"] for v in swept)
    return [v["id"] for v in swept], line_item_count, subtotal_cents


def invoice_tax_total(subtotal_cents):
    """Single sum-then-round tax on the aggregate subtotal (SCAFFOLD invoice_total)."""
    tax_cents = _round_half_up(Decimal(subtotal_cents) * TAX_RATE)
    total_cents = subtotal_cents + tax_cents
    return tax_cents, total_cents


# =========================================================================
# Contract reconciliation (derived-field consistency)
# =========================================================================
def reconcile_committed(contract):
    """Recompute committed_cents / budget_remaining_cents from the visit set
    (SCAFFOLD contract_committed_reconcile). This is a mutation: it touches the
    contract (refreshes updated_at, increments version) per PRD 2.4/2.5."""
    committed = 0
    for v in db.VISITS.values():
        if v["service_contract_id"] != contract["id"]:
            continue
        if v["execution_status"] == "CANCELLED":
            continue
        if v["execution_status"] == "COMPLETED":
            committed += v["final_charge_cents"]
        else:
            committed += v["estimated_charge_cents"]
    contract["committed_cents"] = committed
    contract["budget_remaining_cents"] = contract["annual_budget_cents"] - committed
    db.touch(contract)


def recompute_billed(contract):
    """billed_cents = sum of total_cents over ISSUED or PAID invoices
    (PRD 3.2). This is a mutation of the contract."""
    billed = 0
    for inv in db.INVOICES.values():
        if inv["service_contract_id"] == contract["id"] and inv["status"] in ("ISSUED", "PAID"):
            billed += inv["total_cents"]
    contract["billed_cents"] = billed
    db.touch(contract)


# =========================================================================
# Cascade: cancel a single visit (used by visit cancel + contract suspend/terminate)
# =========================================================================
def cancel_visit_cascade(visit):
    """Move a SCHEDULED visit to CANCELLED, with the three-hop compensating
    release (route minutes, equipment release, asset usage return).
    Does NOT reconcile the contract — caller reconciles once after the batch."""
    visit["execution_status"] = "CANCELLED"
    db.touch(visit)

    # Hop 1: return route capacity.
    route = db.ROUTES.get(visit["route_schedule_id"])
    if route is not None:
        route["booked_minutes"] -= visit["slot_duration_minute"]
        db.touch(route)

    # Hops 2 & 3: release RESERVED equipment reservations, return usage to asset.
    for r in db.RESERVATIONS.values():
        if r["service_visit_id"] == visit["id"] and r["status"] == "RESERVED":
            r["status"] = "RELEASED"
            db.touch(r)
            asset = db.EQUIPMENT.get(r["equipment_asset_id"])
            if asset is not None:
                asset["accumulated_usage_minutes"] -= r["reserved_minutes"]
                db.touch(asset)
