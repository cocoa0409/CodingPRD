"""Customer impact model and repricing runs (PRD 3.3)."""
from decimal import Decimal

import db
from constants import HOLD_THRESHOLD, MIGRATE_THRESHOLD, MODEL_BILLING_STATUSES
from services import rating
from util import D, rhu, rhu_int

ZERO = Decimal("0")


def modeled_shipments(program, window=None):
    def match(s):
        if s.get("customer_id") != program.get("customer_id"):
            return False
        if s.get("billing_status") not in MODEL_BILLING_STATUSES:
            return False
        if window is not None:
            start, end = window
            pickup = s.get("pickup_at")
            if pickup is None or pickup < start or pickup >= end:
                return False
        return True

    return db.all_rows("shipments", match)


def recommendation_for(delta_pct):
    if delta_pct >= MIGRATE_THRESHOLD:
        return "MIGRATE_DENSITY_BASED"
    if delta_pct <= HOLD_THRESHOLD:
        return "HOLD_CLASS_BASED"
    return "NEGOTIATE_FAK"


def compute_model(program, tariff_id=None, window=None):
    """Two normative passes: undiscounted gross fixes the volume tier, then discount + tier."""
    shipments = modeled_shipments(program, window)
    count = len(shipments)
    baseline = sum(int(s.get("assessed_total_cents") or 0) for s in shipments)

    if count == 0:
        delta = rhu(ZERO, 4)
        return {
            "modeled_shipment_count": 0,
            "baseline_revenue_cents": baseline,
            "modeled_annual_revenue_cents": 0,
            "modeled_delta_pct": delta,
            "migration_recommendation": recommendation_for(delta),
        }

    # ---- pass 1: undiscounted gross ---------------------------------------
    annual_gross = 0
    for shipment in shipments:
        raw, _ = rating.charge_raw(
            shipment, "MODELED", program=program, discount=0, tariff_id=tariff_id
        )
        annual_gross += rhu_int(raw)
    tier = rating.volume_tier(annual_gross)

    # ---- pass 2: contract discount, then the volume tier ------------------
    minimum = int(program.get("min_charge_cents") or 0)
    modeled_total = 0
    for shipment in shipments:
        raw, _ = rating.charge_raw(shipment, "MODELED", program=program, tariff_id=tariff_id)
        modeled_total += max(minimum, rhu_int(raw * (1 - tier)))

    if baseline == 0:
        delta = rhu(ZERO, 4)
    else:
        delta = rhu((D(modeled_total) - D(baseline)) / D(baseline), 4)

    return {
        "modeled_shipment_count": count,
        "baseline_revenue_cents": baseline,
        "modeled_annual_revenue_cents": modeled_total,
        "modeled_delta_pct": delta,
        "migration_recommendation": recommendation_for(delta),
    }


def apply_model(program, model):
    for key, value in model.items():
        program[key] = value
    db.touch(program)
    return program


def scoped_programs(scope):
    def match(p):
        if p.get("status") != "ACTIVE":
            return False
        if scope == "ALL_ACTIVE":
            return True
        if scope == "ALL_CLASS_BASED":
            return p.get("program_type") == "CLASS_BASED"
        if scope == "ALL_DENSITY_BASED":
            return p.get("program_type") == "DENSITY_BASED"
        return False

    return db.all_rows("rate_programs", match)
