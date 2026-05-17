"""Resource serializers — convert stored records to JSON-friendly dicts.

Decimal values are serialized as floats so the API surface uses numeric JSON
types (per PRD §2.6 monetary precision is enforced via Decimal rounding on
write; the JSON surface presents the rounded value as a number).
"""
from decimal import Decimal
from typing import Any


def _num(value: Any) -> Any:
    """Convert Decimal -> float; pass-through for None and other types.

    JSON has no distinct decimal type. Because we always store values that have
    been quantized to 2 or 4 decimals at write time (via Decimal HALF_UP), the
    float conversion preserves the requested precision in the JSON output.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


# ---------- Patient ----------

def patient_view(p: dict) -> dict:
    return {
        "id": p["id"],
        "full_name": p["full_name"],
        "medicare_id": p["medicare_id"],
        "home_zip": p["home_zip"],
        "wage_index": _num(p.get("wage_index")),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


# ---------- Clinician ----------

def clinician_view(c: dict) -> dict:
    return {
        "id": c["id"],
        "full_name": c["full_name"],
        "discipline": c["discipline"],
        "license_expiration_date": c["license_expiration_date"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


# ---------- OASIS ----------

def oasis_view(o: dict) -> dict:
    return {
        "id": o["id"],
        "patient_id": o["patient_id"],
        "assessment_reason": o["assessment_reason"],
        "assessment_date": o["assessment_date"],
        "clinical_grouping": o["clinical_grouping"],
        "functional_impairment_level": o["functional_impairment_level"],
        "admission_source": o["admission_source"],
        "hha_companion_hours_ordered": _num(o.get("hha_companion_hours_ordered")),
        "status": o["status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


# ---------- Episode ----------

def episode_view(e: dict) -> dict:
    return {
        "id": e["id"],
        "patient_id": e["patient_id"],
        "source_oasis_id": e["source_oasis_id"],
        "episode_type": e["episode_type"],
        "start_date": e["start_date"],
        "end_date": e["end_date"],
        "timing_category": e["timing_category"],
        "recert_due_date": e["recert_due_date"],
        "status": e["status"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


# ---------- Visit ----------

def visit_view(v: dict) -> dict:
    return {
        "id": v["id"],
        "episode_id": v["episode_id"],
        "clinician_id": v["clinician_id"],
        "visit_type": v["visit_type"],
        "visit_date": v["visit_date"],
        "start_minute": v["start_minute"],
        "end_minute": v["end_minute"],
        "hha_hours": _num(v.get("hha_hours", 0)),
        "status": v["status"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


# ---------- MileageLog ----------

def mileage_view(m: dict) -> dict:
    # MileageLog has no updated_at / version per SCAFFOLD §1.1 + PRD §2.4.
    return {
        "id": m["id"],
        "visit_id": m["visit_id"],
        "episode_id": m["episode_id"],
        "miles_driven": _num(m["miles_driven"]),
        "reimbursement_amount": _num(m["reimbursement_amount"]),
        "created_at": m["created_at"],
    }


# ---------- PDGMClaim ----------

def claim_view(c: dict) -> dict:
    return {
        "id": c["id"],
        "episode_id": c["episode_id"],
        "hipps_code": c["hipps_code"],
        "case_mix_weight": _num(c["case_mix_weight"]),
        "provisional_payment": _num(c["provisional_payment"]),
        "final_payment": _num(c.get("final_payment")),
        "lupa_applied": c.get("lupa_applied"),
        "total_mileage_reimbursement": _num(c.get("total_mileage_reimbursement", Decimal("0.00"))),
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


# ---------- ClockState ----------

def clock_view(clock: dict) -> dict:
    # No id / timestamps / version per PRD §2.4.
    return {"current_date": clock["current_date"]}
