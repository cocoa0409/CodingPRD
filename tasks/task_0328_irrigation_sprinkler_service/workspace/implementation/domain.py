"""Domain logic: serialization, calculations, computed-field recompute, cascades.

All monetary math uses Decimal with ROUND_HALF_UP. All constants are taken
literally from SCAFFOLD §1.3 and PRD §3.
"""
from decimal import Decimal, ROUND_HALF_UP

from db import db, touch

# ---------------------------------------------------------------------------
# Constants (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
TAX_RATE = Decimal("0.08")

# winter_risk_score
PLANT_WEIGHT = {"TURF": 4, "ROTOR": 3, "SHRUB": 2, "DRIP": 1}
HIGH_PSI = 80
RISK_CAP = 1000

# blowout_price
BASE_FEE_CENTS = 4500
TIER1_RATE_CENTS = 1200
TIER2_RATE_CENTS = 1000
TIER3_RATE_CENTS = 850
PSI_SURCHARGE_PER_PSI = 50
PSI_SURCHARGE_CAP_CENTS = 3000

# plan_annual_dues
TIER_RATE = {"BASIC": 6000, "PLUS": 9000, "PREMIUM": 13000}
LOYALTY_LO_CENTS = 60000
LOYALTY_HI_CENTS = 120000

# backflow_result
MIN_RELIEF_PSI = 2
MIN_HOLD_PSI = 1

# program_slot_overlap_check
VALVE_SWITCH_BUFFER_SEC = 120

# route_capacity_check
MAX_STOPS_PER_ROUTE = 8

WO_TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}


def round_half_up(amount):
    """Round a Decimal to a whole integer of cents, half up."""
    return int(Decimal(amount).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Serialization — strip internal fields (those prefixed with "_")
# ---------------------------------------------------------------------------
def serialize(record):
    return {k: v for k, v in record.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Calculations (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
def quote_estimated_total(line_items):
    """variant=estimated: subtotal then single round at the end (Rule 2b)."""
    subtotal = 0
    for li in line_items:
        subtotal += li["quantity"] * li["unit_rate_cents"]
    return round_half_up(Decimal(subtotal) * (Decimal(1) + TAX_RATE))


def quote_final_total(actual_labor_cents, actual_parts_cents):
    """variant=final: tax+round EACH line, THEN sum (pinned order)."""
    labor_component = round_half_up(Decimal(actual_labor_cents) * (Decimal(1) + TAX_RATE))
    parts_component = round_half_up(Decimal(actual_parts_cents) * (Decimal(1) + TAX_RATE))
    return labor_component + parts_component


def plan_annual_dues(tier, visits_per_year):
    """Compute gross FIRST, then select loyalty discount from gross, then apply."""
    base_per_visit = TIER_RATE[tier]
    gross = base_per_visit * visits_per_year
    if gross >= LOYALTY_HI_CENTS:
        discount_pct = Decimal("0.15")
    elif gross >= LOYALTY_LO_CENTS:
        discount_pct = Decimal("0.08")
    else:
        discount_pct = Decimal("0")
    return round_half_up(Decimal(gross) * (Decimal(1) - discount_pct))


def blowout_price(zone_count, static_psi):
    n = zone_count
    if n <= 4:
        per_zone = TIER1_RATE_CENTS
    elif n <= 10:
        per_zone = TIER2_RATE_CENTS
    else:
        per_zone = TIER3_RATE_CENTS
    surcharge = max(0, min(PSI_SURCHARGE_CAP_CENTS, (static_psi - HIGH_PSI) * PSI_SURCHARGE_PER_PSI))
    return BASE_FEE_CENTS + per_zone * n + surcharge


def backflow_result(relief_open_psi, checkvalve_hold_psi):
    if relief_open_psi >= MIN_RELIEF_PSI and checkvalve_hold_psi >= MIN_HOLD_PSI:
        return "PASS"
    return "FAIL"


# ---------------------------------------------------------------------------
# System-scoped helpers
# ---------------------------------------------------------------------------
def zones_of_system(system_id):
    return [z for z in db.zones.values() if z["system_id"] == system_id]


def non_archived_zones(system_id):
    return [z for z in zones_of_system(system_id) if z["zone_state"] != "ARCHIVED"]


def workorders_of_system(system_id):
    return [w for w in db.work_orders.values() if w["system_id"] == system_id]


def systems_of_property(property_id):
    return [s for s in db.irrigation_systems.values() if s["property_id"] == property_id]


def _psi_factor(static_psi):
    return 2 if static_psi >= HIGH_PSI else 1


def _zone_exposure(system):
    total = 0
    for z in non_archived_zones(system["id"]):
        total += PLANT_WEIGHT[z["plant_type"]] * z["head_count"]
    return total


def _has_completed_winterization(system_id):
    for w in workorders_of_system(system_id):
        if w["job_type"] == "WINTERIZATION" and w["completion_status"] == "COMPLETED":
            return True
    return False


# ---------------------------------------------------------------------------
# Computed-field recompute. Each helper returns the freshly computed value;
# apply_* helpers write it and register the mutation when it changes.
# ---------------------------------------------------------------------------
def compute_zone_count(system):
    return sum(
        1 for z in zones_of_system(system["id"]) if z["zone_state"] in ("MAPPED", "ACTIVE")
    )


def compute_committed_cost_cents(system):
    total = 0
    for w in workorders_of_system(system["id"]):
        if w["completion_status"] not in WO_TERMINAL:
            total += w["estimated_cost_cents"]
    return total


def compute_provisional_winter_risk(system):
    return min(RISK_CAP, _zone_exposure(system) * _psi_factor(system["static_psi"]))


def compute_assessed_winter_risk(system):
    if _has_completed_winterization(system["id"]):
        drained = 0
    else:
        drained = _zone_exposure(system)
    return min(RISK_CAP, drained * _psi_factor(system["static_psi"]))


def recompute_system_derived(system):
    """Recompute all four derived fields on a system; mutate (touch) only if any
    derived value actually changed. PRD §2.7: a recompute that changes a derived
    value is itself a mutation that bumps version/updated_at."""
    new_vals = {
        "zone_count": compute_zone_count(system),
        "committed_cost_cents": compute_committed_cost_cents(system),
        "provisional_winter_risk": compute_provisional_winter_risk(system),
        "assessed_winter_risk": compute_assessed_winter_risk(system),
    }
    changed = any(system.get(k) != v for k, v in new_vals.items())
    if changed:
        system.update(new_vals)
        touch(system)
    return changed


def compute_compliance_status(property_id):
    systems = [s for s in systems_of_property(property_id) if s["lifecycle_state"] != "DECOMMISSIONED"]
    if systems and all(s["backflow_status"] == "CERTIFIED" for s in systems):
        return "COMPLIANT"
    return "NON_COMPLIANT"


def recompute_property_compliance(prop):
    new_val = compute_compliance_status(prop["id"])
    if prop.get("compliance_status") != new_val:
        prop["compliance_status"] = new_val
        touch(prop)
        return True
    return False


def recompute_route_derived(route):
    stops = [
        rs for rs in db.route_stops.values()
        if rs["route_id"] == route["id"] and rs["stop_state"] == "SCHEDULED"
    ]
    new_stops_used = len(stops)
    new_minutes = sum(rs["window_minutes"] for rs in stops)
    if route.get("stops_used") != new_stops_used or route.get("minutes_committed") != new_minutes:
        route["stops_used"] = new_stops_used
        route["minutes_committed"] = new_minutes
        touch(route)
        return True
    return False


def recompute_program_total(program):
    program["total_run_minutes"] = sum(s["run_minutes"] for s in program["slots"])
