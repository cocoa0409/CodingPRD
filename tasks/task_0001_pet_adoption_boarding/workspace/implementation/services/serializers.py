"""Resource serializers: convert internal dicts into API-facing JSON dicts."""

from db import store, fmt_dt
from services.compliance import compute_compliance
from services.home_visit import compute_adopter_home_visit_status


def _common(rec):
    return {
        "created_at": fmt_dt(rec["created_at"]),
        "updated_at": fmt_dt(rec["updated_at"]),
        "version": rec["version"],
    }


def serialize_shelter(rec):
    reserved = sum(
        1
        for r in store.reservations.values()
        if r["shelter_id"] == rec["id"] and r["status"] in ("RESERVED", "ACTIVE")
    )
    available = max(0, rec["boarding_capacity"] - reserved)
    out = {
        "id": rec["id"],
        "name": rec["name"],
        "boarding_capacity": rec["boarding_capacity"],
        "reserved_slots": reserved,
        "available_slots": available,
        "adoption_fee_base": rec["adoption_fee_base"],
        "boarding_rate_per_night": rec["boarding_rate_per_night"],
        "status": rec["status"],
    }
    out.update(_common(rec))
    return out


def serialize_animal(rec):
    out = {
        "id": rec["id"],
        "shelter_id": rec["shelter_id"],
        "name": rec["name"],
        "species": rec["species"],
        "age_months": rec["age_months"],
        "temperament_tags": list(rec.get("temperament_tags", [])),
        "adoption_fee_override": rec.get("adoption_fee_override"),
        "special_care_level": rec.get("special_care_level", "NONE"),
        "intake_date": fmt_dt(rec["intake_date"]),
        "status": rec["status"],
    }
    out.update(_common(rec))
    return out


def serialize_vaccination(rec):
    return {
        "id": rec["id"],
        "animal_id": rec["animal_id"],
        "vaccine_type": rec["vaccine_type"],
        "administered_date": fmt_dt(rec["administered_date"]),
        "expires_date": fmt_dt(rec["expires_date"]),
        "lot_number": rec["lot_number"],
        "created_at": fmt_dt(rec["created_at"]),
    }


def serialize_adopter(rec):
    status, expires_at = compute_adopter_home_visit_status(rec["id"])
    out = {
        "id": rec["id"],
        "full_name": rec["full_name"],
        "household_size": rec["household_size"],
        "has_yard": rec["has_yard"],
        "home_visit_status": status,
        "home_visit_expires_at": fmt_dt(expires_at) if expires_at else None,
        "disqualified": rec.get("disqualified", False),
    }
    out.update(_common(rec))
    return out


def serialize_home_visit(rec):
    out = {
        "id": rec["id"],
        "adopter_id": rec["adopter_id"],
        "scheduled_for": fmt_dt(rec["scheduled_for"]),
        "completed_at": fmt_dt(rec.get("completed_at")) if rec.get("completed_at") else None,
        "safety_score": rec.get("safety_score"),
        "yard_verified": rec.get("yard_verified", False),
        "inspector_id": rec["inspector_id"],
        "status": rec["status"],
    }
    out.update(_common(rec))
    return out


def serialize_application(rec):
    out = {
        "id": rec["id"],
        "adopter_id": rec["adopter_id"],
        "animal_id": rec["animal_id"],
        "shelter_id": rec["shelter_id"],
        "pinned_animal_version": rec.get("pinned_animal_version"),
        "pinned_vaccination_snapshot": rec.get("pinned_vaccination_snapshot"),
        "pinned_fee": rec.get("pinned_fee"),
        "review_notes": rec.get("review_notes", ""),
        "reviewer_user_id": rec.get("reviewer_user_id"),
        "status": rec["status"],
    }
    out.update(_common(rec))
    return out


def serialize_reservation(rec):
    out = {
        "id": rec["id"],
        "shelter_id": rec["shelter_id"],
        "animal_id": rec["animal_id"],
        "owner_id": rec["owner_id"],
        "check_in_date": fmt_dt(rec["check_in_date"]),
        "check_out_date": fmt_dt(rec["check_out_date"]),
        "nights": rec.get("nights"),
        "quoted_total": rec.get("quoted_total"),
        "final_total": rec.get("final_total"),
        "status": rec["status"],
    }
    out.update(_common(rec))
    return out


def serialize_settlement(rec):
    out = {
        "id": rec["id"],
        "subject_type": rec["subject_type"],
        "subject_id": rec["subject_id"],
        "amount": rec["amount"],
        "method": rec["method"],
        "status": rec["status"],
        "settled_at": fmt_dt(rec.get("settled_at")) if rec.get("settled_at") else None,
    }
    out.update(_common(rec))
    return out


def serialize_compliance(animal_id):
    result = compute_compliance(animal_id)
    return {
        "status": result["status"],
        "missing": result["missing"],
        "expired": result["expired"],
    }
