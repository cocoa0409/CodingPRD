"""Business logic: serializers, cost accrual, chemical counters, cascades."""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import db
from services.core import dec_to_1dp, round_cents


# ---------- Serializers ----------

def serialize_event(e: dict) -> dict:
    return {
        "id": e["id"],
        "event_code": e["event_code"],
        "season_label": e["season_label"],
        "chemical_limit_lbs": float(e["chemical_limit_lbs"]),
        "budget_cents": e["budget_cents"],
        "status": e["status"],
        "closure_status": e["closure_status"],
        "airline_acknowledged": e["airline_acknowledged"],
        "activated_at": e["activated_at"],
        "estimated_cost_cents": e["estimated_cost_cents"],
        "actual_cost_cents": e["actual_cost_cents"],
        "chemical_used_lbs": float(e["chemical_used_lbs"]),
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def serialize_surface(s: dict) -> dict:
    return {
        "id": s["id"],
        "surface_code": s["surface_code"],
        "surface_type": s["surface_type"],
        "length_ft": float(s["length_ft"]),
        "width_ft": float(s["width_ft"]),
        "area_sqft": float(s["area_sqft"]),
        "priority_rank": s["priority_rank"],
        "status": s["status"],
        "current_condition_code": s["current_condition_code"],
        "active_notam_count": s["active_notam_count"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_condition_report(r: dict) -> dict:
    return {
        "id": r["id"],
        "event_id": r["event_id"],
        "surface_id": r["surface_id"],
        "contaminant_type": r["contaminant_type"],
        "coverage_pct": r["coverage_pct"],
        "depth_inches": float(r["depth_inches"]),
        "observed_at": r["observed_at"],
        "condition_code": r["condition_code"],
        "status": r["status"],
        "superseded_by_id": r["superseded_by_id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_friction_assessment(a: dict) -> dict:
    return {
        "id": a["id"],
        "event_id": a["event_id"],
        "surface_id": a["surface_id"],
        "mu_value": float(a["mu_value"]),
        "measured_at": a["measured_at"],
        "braking_action": a["braking_action"],
        "status": a["status"],
        "superseded_by_id": a["superseded_by_id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def serialize_notam(n: dict) -> dict:
    return {
        "id": n["id"],
        "event_id": n["event_id"],
        "surface_id": n["surface_id"],
        "notam_type": n["notam_type"],
        "effective_from": n["effective_from"],
        "effective_until": n["effective_until"],
        "message": n["message"],
        "source_assessment_id": n["source_assessment_id"],
        "source_report_id": n["source_report_id"],
        "status": n["status"],
        "created_at": n["created_at"],
        "updated_at": n["updated_at"],
        "version": n["version"],
    }


def serialize_chemical_product(p: dict) -> dict:
    return {
        "id": p["id"],
        "product_code": p["product_code"],
        "base_rate_lbs_per_1000sqft": float(p["base_rate_lbs_per_1000sqft"]),
        "unit_cost_cents_per_lb": p["unit_cost_cents_per_lb"],
        "seasonal_limit_lbs": float(p["seasonal_limit_lbs"]),
        "seasonal_reserved_lbs": float(p["seasonal_reserved_lbs"]),
        "seasonal_dispensed_lbs": float(p["seasonal_dispensed_lbs"]),
        "seasonal_available_lbs": float(p["seasonal_available_lbs"]),
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_chemical_application(a: dict) -> dict:
    return {
        "id": a["id"],
        "event_id": a["event_id"],
        "surface_id": a["surface_id"],
        "product_id": a["product_id"],
        "pavement_temp_f": float(a["pavement_temp_f"]),
        "raw_quantity_lbs": float(a["raw_quantity_lbs"]),
        "authorized_quantity_lbs": (float(a["authorized_quantity_lbs"])
                                    if a["authorized_quantity_lbs"] is not None else None),
        "capped": a["capped"],
        "authorized_by": a["authorized_by"],
        "line_cost_cents": a["line_cost_cents"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def serialize_equipment_unit(u: dict) -> dict:
    return {
        "id": u["id"],
        "unit_code": u["unit_code"],
        "unit_type": u["unit_type"],
        "hourly_rate_cents": u["hourly_rate_cents"],
        "readiness": u["readiness"],
        "created_at": u["created_at"],
        "updated_at": u["updated_at"],
        "version": u["version"],
    }


def serialize_operator_shift(s: dict) -> dict:
    return {
        "id": s["id"],
        "operator_code": s["operator_code"],
        "event_id": s["event_id"],
        "equipment_unit_id": s["equipment_unit_id"],
        "base_rate_cents_per_hour": s["base_rate_cents_per_hour"],
        "start_utc": s["start_utc"],
        "end_utc": s["end_utc"],
        "worked_hours": (float(s["worked_hours"]) if s["worked_hours"] is not None else None),
        "line_cost_cents": s["line_cost_cents"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


# ---------- Calculations ----------

CONDITION_BASE = {
    "DRY": 6,
    "WET": 5,
    "DRY_SNOW": 4,
    "WET_SNOW": 3,
    "COMPACTED_SNOW": 2,
    "SLUSH": 2,
    "STANDING_WATER": 2,
    "ICE": 1,
}


def derive_condition_code(contaminant_type: str, coverage_pct: int,
                          depth_inches: Decimal) -> int:
    base = CONDITION_BASE[contaminant_type]
    if coverage_pct > 50 and depth_inches >= Decimal("0.25"):
        base -= 1
    return max(0, base)


def derive_braking_action(mu: Decimal) -> str:
    if mu >= Decimal("0.50"):
        return "GOOD"
    if mu >= Decimal("0.36"):
        return "MEDIUM"
    if mu >= Decimal("0.26"):
        return "MEDIUM_POOR"
    if mu >= Decimal("0.10"):
        return "POOR"
    return "NIL"


def compute_raw_quantity_lbs(surface: dict, product: dict,
                              pavement_temp_f: Decimal) -> Decimal:
    area_units = surface["area_sqft"] / Decimal(1000)
    if pavement_temp_f < Decimal(15):
        temp_factor = Decimal("1.25")
    elif pavement_temp_f <= Decimal(28):
        temp_factor = Decimal("1.10")
    else:
        temp_factor = Decimal("1.00")
    raw = area_units * product["base_rate_lbs_per_1000sqft"] * temp_factor
    return dec_to_1dp(raw)


def compute_event_remaining_lbs(event: dict) -> Decimal:
    used = event["chemical_used_lbs"]
    authorized = Decimal(0)
    for app in db.chemical_applications.values():
        if app["event_id"] == event["id"] and app["status"] == "AUTHORIZED":
            authorized += app["authorized_quantity_lbs"] or Decimal(0)
    return event["chemical_limit_lbs"] - used - authorized


def compute_shift_line_cost_cents(shift: dict, hours: Decimal) -> int:
    regular = min(hours, Decimal(8))
    overtime = max(Decimal(0), hours - Decimal(8))
    labor = regular * shift["base_rate_cents_per_hour"] + \
        overtime * shift["base_rate_cents_per_hour"] * Decimal("1.5")
    total = round_cents(labor)
    if shift.get("equipment_unit_id"):
        unit = db.equipment_units.get(shift["equipment_unit_id"])
        if unit:
            equip = hours * unit["hourly_rate_cents"]
            total += round_cents(equip)
    return total


def shift_planned_hours(shift: dict) -> Decimal:
    start = shift["_start_dt"]
    end = shift["_end_dt"]
    delta = (end - start).total_seconds()
    return Decimal(str(delta)) / Decimal(3600)


def recompute_event_costs(event: dict) -> None:
    est = 0
    act = 0
    for sh in db.operator_shifts.values():
        if sh["event_id"] != event["id"]:
            continue
        if sh["status"] == "SCHEDULED":
            h = shift_planned_hours(sh)
            est += compute_shift_line_cost_cents(sh, h)
        elif sh["status"] == "COMPLETED":
            h = sh["worked_hours"]
            act += compute_shift_line_cost_cents(sh, h)
    for app in db.chemical_applications.values():
        if app["event_id"] != event["id"]:
            continue
        if app["status"] == "AUTHORIZED":
            est += app["line_cost_cents"]
        elif app["status"] == "DISPENSED":
            act += app["line_cost_cents"]
    event["estimated_cost_cents"] = est
    event["actual_cost_cents"] = act


def recompute_product_counters(product: dict) -> None:
    reserved = Decimal(0)
    dispensed = Decimal(0)
    for app in db.chemical_applications.values():
        if app["product_id"] != product["id"]:
            continue
        if app["status"] == "AUTHORIZED":
            reserved += app["authorized_quantity_lbs"] or Decimal(0)
        elif app["status"] == "DISPENSED":
            dispensed += app["authorized_quantity_lbs"] or Decimal(0)
    product["seasonal_reserved_lbs"] = reserved
    product["seasonal_dispensed_lbs"] = dispensed
    product["seasonal_available_lbs"] = (
        product["seasonal_limit_lbs"] - dispensed - reserved
    )


def recompute_event_chemical_used(event: dict) -> None:
    used = Decimal(0)
    for app in db.chemical_applications.values():
        if app["event_id"] == event["id"] and app["status"] == "DISPENSED":
            used += app["authorized_quantity_lbs"] or Decimal(0)
    event["chemical_used_lbs"] = used


def supersede_notams_for_report(report_id: str) -> None:
    """Flip ISSUED Notams whose source_report_id == report_id to REISSUE_REQUIRED.
    Each flip recomputes the surface's active_notam_count."""
    affected_surfaces = set()
    for n in db.notams.values():
        if n["source_report_id"] == report_id and n["status"] == "ISSUED":
            n["status"] = "REISSUE_REQUIRED"
            n["version"] += 1
            n["updated_at"] = now_iso()
            affected_surfaces.add(n["surface_id"])
    for sid in affected_surfaces:
        recompute_active_notam_count(sid)


def supersede_notams_for_assessment(assessment_id: str) -> None:
    affected_surfaces = set()
    for n in db.notams.values():
        if n["source_assessment_id"] == assessment_id and n["status"] == "ISSUED":
            n["status"] = "REISSUE_REQUIRED"
            n["version"] += 1
            n["updated_at"] = now_iso()
            affected_surfaces.add(n["surface_id"])
    for sid in affected_surfaces:
        recompute_active_notam_count(sid)


def recompute_active_notam_count(surface_id: str) -> None:
    count = 0
    for n in db.notams.values():
        if n["surface_id"] == surface_id and n["status"] == "ISSUED":
            count += 1
    surface = db.airfield_surfaces.get(surface_id)
    if surface:
        surface["active_notam_count"] = count


def now_iso() -> str:
    from services.core import now_iso_ms
    return now_iso_ms()


def flip_product_constrained_if_threshold(product: dict) -> None:
    """If seasonal_dispensed >= 0.9 * seasonal_limit and status == ACTIVE,
    flip to CONSTRAINED and reject all PROPOSED applications on this product."""
    if product["status"] != "ACTIVE":
        return
    threshold = product["seasonal_limit_lbs"] * Decimal("0.9")
    if product["seasonal_dispensed_lbs"] >= threshold:
        product["status"] = "CONSTRAINED"
        product["version"] += 1
        product["updated_at"] = now_iso()
        for app in db.chemical_applications.values():
            if app["product_id"] == product["id"] and app["status"] == "PROPOSED":
                app["status"] = "REJECTED"
                app["version"] += 1
                app["updated_at"] = now_iso()
