"""Serializers and computed-field helpers (single source of truth for reads)."""
import db
import core


# --------------------------------------------------------------------------
# Cross-entity computed helpers for a Client
# --------------------------------------------------------------------------
def active_meal_plan(client_id):
    for mp in db.meal_plans.values():
        if mp["client_id"] == client_id and mp["status"] == "ACTIVE":
            return mp
    return None


def suspended_meal_plan(client_id):
    for mp in db.meal_plans.values():
        if mp["client_id"] == client_id and mp["status"] == "SUSPENDED":
            return mp
    return None


def count_active_meal_plans(client_id):
    return sum(
        1 for mp in db.meal_plans.values()
        if mp["client_id"] == client_id and mp["status"] == "ACTIVE"
    )


def donation_balance_cents(client_id):
    return sum(
        c["amount_cents"] for c in db.contributions.values()
        if c["client_id"] == client_id and c["status"] == "RECORDED"
    )


def delivered_units(client_id):
    return sum(
        d["meal_count"] for d in db.deliveries.values()
        if d["client_id"] == client_id and d["status"] == "DELIVERED"
    )


def provisioned_monthly_units(client_id):
    mp = active_meal_plan(client_id)
    if not mp:
        return 0
    return mp["weekly_meal_count"] * core.WEEKS_PER_MONTH


def suggested_contribution_monthly_cents(client):
    mp = active_meal_plan(client["id"])
    if not mp:
        return 0
    per_meal = core.per_meal_contribution_cents(client["income_tier"])
    return per_meal * mp["weekly_meal_count"] * core.WEEKS_PER_MONTH


# --------------------------------------------------------------------------
# Serializers
# --------------------------------------------------------------------------
def _common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def client(c):
    out = _common(c)
    out.update({
        "full_name": c["full_name"],
        "birth_date": c["birth_date"],
        "household_size": c["household_size"],
        "monthly_income_cents": c["monthly_income_cents"],
        "address_zone": c["address_zone"],
        "phone": c["phone"],
        "enrollment_status": c["enrollment_status"],
        "oaa_eligible": c["oaa_eligible"],
        "income_tier": c["income_tier"],
        "suggested_contribution_cents": suggested_contribution_monthly_cents(c),
        "donation_balance_cents": donation_balance_cents(c["id"]),
        "lifetime_oaa_units": delivered_units(c["id"]),
        "consecutive_no_answer": c["consecutive_no_answer"],
    })
    return out


def client_summary(c):
    return {
        "income_tier": c["income_tier"],
        "oaa_eligible": c["oaa_eligible"],
        "suggested_contribution_cents": suggested_contribution_monthly_cents(c),
        "donation_balance_cents": donation_balance_cents(c["id"]),
        "provisioned_monthly_units": provisioned_monthly_units(c["id"]),
        "delivered_units": delivered_units(c["id"]),
        "lifetime_oaa_units": delivered_units(c["id"]),
    }


def assessment(a):
    out = _common(a)
    out.update({
        "client_id": a["client_id"],
        "nutrition_determine_points": a["nutrition_determine_points"],
        "nutrition_risk_category": a["nutrition_risk_category"],
        "adl_score": a["adl_score"],
        "functional_level": a["functional_level"],
        "therapeutic_diet_required": a["therapeutic_diet_required"],
        "therapeutic_diet_type": a["therapeutic_diet_type"],
        "recommended_meals_per_day": a["recommended_meals_per_day"],
        "status": a["status"],
    })
    return out


def meal_plan(m):
    out = _common(m)
    out.update({
        "client_id": m["client_id"],
        "assessment_id": m["assessment_id"],
        "route_id": m["route_id"],
        "meal_type": m["meal_type"],
        "therapeutic_diet_type": m["therapeutic_diet_type"],
        "meals_per_day": m["meals_per_day"],
        "delivery_days": m["delivery_days"],
        "weekly_meal_count": m["weekly_meal_count"],
        "suggested_contribution_per_meal_cents": m["suggested_contribution_per_meal_cents"],
        "status": m["status"],
    })
    return out


def route(r):
    out = _common(r)
    out.update({
        "name": r["name"],
        "zone": r["zone"],
        "service_days": r["service_days"],
        "driver_id": r["driver_id"],
        "max_meals_per_run": r["max_meals_per_run"],
        "status": r["status"],
    })
    return out


def driver(d):
    out = _common(d)
    out.update({
        "full_name": d["full_name"],
        "phone": d["phone"],
        "status": d["status"],
    })
    return out


def delivery(d):
    out = _common(d)
    out.update({
        "meal_plan_id": d["meal_plan_id"],
        "client_id": d["client_id"],
        "route_id": d["route_id"],
        "scheduled_date": d["scheduled_date"],
        "meal_type": d["meal_type"],
        "meal_count": d["meal_count"],
        "oaa_units_accrued": d["oaa_units_accrued"],
        "status": d["status"],
        "delivered_at": d["delivered_at"],
    })
    return out


def wellness_check(w):
    return {
        "id": w["id"],
        "created_at": w["created_at"],
        "delivery_id": w["delivery_id"],
        "client_id": w["client_id"],
        "outcome": w["outcome"],
        "notes": w["notes"],
    }


def welfare_alert(a):
    out = _common(a)
    out.update({
        "client_id": a["client_id"],
        "triggering_wellness_check_id": a["triggering_wellness_check_id"],
        "severity": a["severity"],
        "status": a["status"],
        "acknowledged_by": a["acknowledged_by"],
    })
    return out


def contribution(c):
    out = _common(c)
    out.update({
        "client_id": c["client_id"],
        "amount_cents": c["amount_cents"],
        "period_month": c["period_month"],
        "status": c["status"],
    })
    return out


def vacation_hold(h):
    out = _common(h)
    out.update({
        "client_id": h["client_id"],
        "start_date": h["start_date"],
        "end_date": h["end_date"],
        "status": h["status"],
    })
    return out


# --------------------------------------------------------------------------
# List helper: filter -> sort by created order -> paginate -> envelope
# --------------------------------------------------------------------------
def sorted_by_seq(records):
    return sorted(records, key=lambda r: r["_seq"])
