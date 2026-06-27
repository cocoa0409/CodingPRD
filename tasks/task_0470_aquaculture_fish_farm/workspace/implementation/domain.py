"""Cross-entity domain helpers: recomputations, posture/freeze cascade, lot
weight conservation. Shared by route modules to keep behavior consistent.

PRD §2.4: any mutation (direct or cascaded) bumps version + updated_at via
common.touch()."""
import calculations
from common import touch, parse_iso, round2, D
from db import store

IN_PRODUCTION = {"STOCKED", "GROWING", "HARVESTING"}


# ---------------------------------------------------------------------------
# Biomass recomputation
# ---------------------------------------------------------------------------
def recompute_cohort_biomass(cohort):
    """Recompute estimated_biomass_kg for a cohort against the logical clock."""
    species = store.species.get(cohort["species_id"])
    if species is None:
        cohort["estimated_biomass_kg"] = 0
        return
    stocked_at = parse_iso(cohort["stocked_at"])
    cohort["estimated_biomass_kg"] = calculations.estimate_biomass(cohort, species, stocked_at)


def tank_current_biomass(tank_id):
    """PRD §3.1: sum estimated_biomass_kg over cohorts residing in the tank with
    lifecycle_status IN {STOCKED, GROWING, HARVESTING}. Recomputes each cohort's
    biomass first so the figure reflects the current clock."""
    total = D(0)
    for cohort in store.cohorts.values():
        if cohort["current_tank_id"] == tank_id and cohort["lifecycle_status"] in IN_PRODUCTION:
            recompute_cohort_biomass(cohort)
            total += D(cohort["estimated_biomass_kg"])
    return round2(total)


def recompute_tank_biomass(tank):
    tank["current_biomass_kg"] = tank_current_biomass(tank["id"])


# ---------------------------------------------------------------------------
# Posture recomputation + freeze cascade (PRD §2.7, §3.4)
# ---------------------------------------------------------------------------
def latest_reading_severity(tank_id):
    """Most recent water-quality reading's severity for a tank, or None."""
    readings = [r for r in store.water_quality_readings.values() if r["tank_id"] == tank_id]
    if not readings:
        return None
    # Most recent by measured_at; tie-break by insertion order (_seq).
    latest = max(readings, key=lambda r: (parse_iso(r["measured_at"]), r["_seq"]))
    return latest["severity"]


def effective_posture(tank):
    """Effective posture = more severe of (latest reading-derived posture, override).
    No reading -> reading-derived posture is OPEN."""
    severity = latest_reading_severity(tank["id"])
    reading_posture = calculations.severity_to_posture(severity) if severity else "OPEN"
    override = tank.get("posture_override")
    return calculations.more_severe(reading_posture, override)


def apply_posture(tank):
    """Recompute posture; if it changed, bump version and run freeze cascade /
    recovery as appropriate. Returns True if posture changed."""
    old = tank["posture"]
    new = effective_posture(tank)
    if new == old:
        return False
    tank["posture"] = new
    touch(tank)
    if new == "FROZEN":
        _freeze_cascade(tank)
    elif old == "FROZEN" and new == "OPEN":
        _recover_cascade(tank)
    return True


def _freeze_cascade(tank):
    """Hop 2: suspend in-production residing cohorts. Hop 3: block their
    SCHEDULED harvest orders (PRD §3.4)."""
    for cohort in store.cohorts.values():
        if (cohort["current_tank_id"] == tank["id"]
                and cohort["lifecycle_status"] in IN_PRODUCTION
                and cohort["operational_status"] != "SUSPENDED"):
            cohort["operational_status"] = "SUSPENDED"
            touch(cohort)
            # Hop 3: SCHEDULED harvest orders on this cohort -> BLOCKED
            for order in store.harvest_orders.values():
                if order["cohort_id"] == cohort["id"] and order["status"] == "SCHEDULED":
                    order["status"] = "BLOCKED"
                    touch(order)


def _recover_cascade(tank):
    """Recovery to OPEN: restore SUSPENDED residing cohorts to ACTIVE. Harvest
    orders that were auto-BLOCKED are NOT auto-restored (PRD §3.4)."""
    for cohort in store.cohorts.values():
        if cohort["current_tank_id"] == tank["id"] and cohort["operational_status"] == "SUSPENDED":
            cohort["operational_status"] = "ACTIVE"
            touch(cohort)


# ---------------------------------------------------------------------------
# Product lot weight conservation (PRD §2.10, §3.10)
# ---------------------------------------------------------------------------
def recompute_lot_weights(lot):
    """Recompute available_weight_kg = total - reserved - shipped and derive
    AVAILABLE/DEPLETED status. reserved/shipped are maintained incrementally by
    sales transitions; available is the derived field."""
    total = D(lot["total_weight_kg"])
    reserved = D(lot["reserved_weight_kg"])
    shipped = D(lot["shipped_weight_kg"])
    available = total - reserved - shipped
    lot["available_weight_kg"] = round2(available)
    lot["status"] = "AVAILABLE" if lot["available_weight_kg"] > 0 else "DEPLETED"
