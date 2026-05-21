"""Per-entity serializers — convert internal dicts to JSON-ready payloads.

Internal representations may use Decimal for money; serializers downcast to
float for the wire. Datetimes are stored as ISO strings already.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any


def _money(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def serialize_veteran(v: dict) -> dict:
    return {
        "id": v["id"],
        "full_name": v["full_name"],
        "branch": v["branch"],
        "aggregate_active_duty_days": v["aggregate_active_duty_days"],
        "discharge_status": v["discharge_status"],
        "combined_rating": v["combined_rating"],
        "post_911_eligibility_tier": v["post_911_eligibility_tier"],
        "months_entitlement_used": _money(v["months_entitlement_used"]),
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


def serialize_dependent(d: dict) -> dict:
    return {
        "id": d["id"],
        "veteran_id": d["veteran_id"],
        "relationship": d["relationship"],
        "date_of_birth": d["date_of_birth"],
        "school_enrolled": d["school_enrolled"],
        "status": d["status"],
        "removed_at": d.get("removed_at"),
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def serialize_claim(c: dict) -> dict:
    return {
        "id": c["id"],
        "veteran_id": c["veteran_id"],
        "condition_code": c["condition_code"],
        "claim_type": c["claim_type"],
        "original_claim_id": c.get("original_claim_id"),
        "status": c["status"],
        "proposed_rating": c["proposed_rating"],
        "granted_rating": c.get("granted_rating"),
        "decided_at": c.get("decided_at"),
        "rater_id": c.get("rater_id"),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_school(s: dict) -> dict:
    return {
        "id": s["id"],
        "name": s["name"],
        "facility_code": s["facility_code"],
        "program_type": s["program_type"],
        "yellow_ribbon_enrolled": s["yellow_ribbon_enrolled"],
        "yellow_ribbon_max_per_year": _money(s["yellow_ribbon_max_per_year"]),
        "zip_bah_code": s["zip_bah_code"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_enrollment(e: dict) -> dict:
    return {
        "id": e["id"],
        "veteran_id": e["veteran_id"],
        "school_id": e["school_id"],
        "term_start": e["term_start"],
        "term_end": e["term_end"],
        "tuition_charged": _money(e["tuition_charged"]),
        "training_time": e["training_time"],
        "delivery_mode": e["delivery_mode"],
        "status": e["status"],
        "months_consumed": _money(e["months_consumed"]),
        "certified_tuition_payable": _money(e.get("certified_tuition_payable")),
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def serialize_housing_payment(h: dict) -> dict:
    return {
        "id": h["id"],
        "enrollment_id": h["enrollment_id"],
        "month_year": h["month_year"],
        "amount": _money(h["amount"]),
        "computation_basis": h["computation_basis"],
        "created_at": h["created_at"],
    }


def serialize_yellow_ribbon(y: dict) -> dict:
    return {
        "id": y["id"],
        "enrollment_id": y["enrollment_id"],
        "tuition_gap": _money(y["tuition_gap"]),
        "school_contribution": _money(y["school_contribution"]),
        "va_match": _money(y["va_match"]),
        "student_responsibility": _money(y["student_responsibility"]),
        "created_at": y["created_at"],
        "updated_at": y["updated_at"],
        "version": y["version"],
    }


def serialize_voc_rehab_plan(p: dict) -> dict:
    return {
        "id": p["id"],
        "veteran_id": p["veteran_id"],
        "training_mode": p["training_mode"],
        "counselor_id": p.get("counselor_id"),
        "status": p["status"],
        "suspension_count": p["suspension_count"],
        "monthly_subsistence": _money(p.get("monthly_subsistence")),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_ledger_entry(l: dict) -> dict:
    return {
        "id": l["id"],
        "veteran_id": l["veteran_id"],
        "source_entity": l["source_entity"],
        "source_id": l["source_id"],
        "amount_dollars": _money(l["amount_dollars"]),
        "posted_at": l["posted_at"],
        "created_at": l["created_at"],
    }
