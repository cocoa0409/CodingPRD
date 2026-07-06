"""Entity serializers — produce the exact public field shape for each entity
(scaffold §1.1). Computed read-time fields (e.g. supplier accreditation_status)
are recomputed here against the logical clock where the scaffold says so.
"""
from clock import parse_iso


def patient_out(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "full_name": p["full_name"],
        "date_of_birth": p["date_of_birth"],
        "payer_type": p["payer_type"],
        "medicare_beneficiary_id": p["medicare_beneficiary_id"],
        "functional_k_level": p["functional_k_level"],
    }


def physician_out(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "full_name": p["full_name"],
        "npi": p["npi"],
        "pecos_enrolled": p["pecos_enrolled"],
    }


def supplier_accreditation_status(supplier, current_utc):
    """calc supplier_accreditation_status (PRD §2.8).

    null expiry -> UNACCREDITED; clock <= expiry -> ACCREDITED (inclusive);
    clock > expiry -> LAPSED.
    """
    expiry = supplier.get("accreditation_expiry")
    if expiry is None:
        return "UNACCREDITED"
    if parse_iso(current_utc) <= parse_iso(expiry):
        return "ACCREDITED"
    return "LAPSED"


def supplier_out(s, current_utc):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "legal_name": s["legal_name"],
        "accreditation_status": supplier_accreditation_status(s, current_utc),
        "accreditation_expiry": s["accreditation_expiry"],
        "surety_bond_active": s["surety_bond_active"],
    }


def prescription_out(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "patient_id": p["patient_id"],
        "physician_id": p["physician_id"],
        "device_category": p["device_category"],
        "primary_diagnosis_code": p["primary_diagnosis_code"],
        "face_to_face_date": p["face_to_face_date"],
        "status": p["status"],
    }


def device_order_out(o):
    return {
        "id": o["id"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
        "prescription_id": o["prescription_id"],
        "supplier_id": o["supplier_id"],
        "fitting_practitioner_id": o["fitting_practitioner_id"],
        "status": o["status"],
        "requires_prior_auth": o["requires_prior_auth"],
        "milestone_progress_pct": o["milestone_progress_pct"],
        "delivery_date": o["delivery_date"],
        "warranty_expiry": o["warranty_expiry"],
        "allowed_total_cents": o["allowed_total_cents"],
    }


def prior_auth_out(a):
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "device_order_id": a["device_order_id"],
        "status": a["status"],
        "auth_number": a["auth_number"],
        "submission_round": a["submission_round"],
        "decision_deadline": a["decision_deadline"],
    }


def claim_line_out(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "device_order_id": c["device_order_id"],
        "l_code": c["l_code"],
        "modifier": c["modifier"],
        "billed_units": c["billed_units"],
        "fee_schedule_cents": c["fee_schedule_cents"],
        "adjudication_status": c["adjudication_status"],
        "appeal_status": c["appeal_status"],
        "allowed_cents": c["allowed_cents"],
    }


def milestone_out(m):
    return {
        "id": m["id"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
        "device_order_id": m["device_order_id"],
        "step": m["step"],
        "weight": m["weight"],
        "completed": m["completed"],
    }


def adjustment_out(a):
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "device_order_id": a["device_order_id"],
        "adjustment_date": a["adjustment_date"],
        "within_warranty": a["within_warranty"],
        "billable": a["billable"],
    }


def repair_request_out(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "device_order_id": r["device_order_id"],
        "replaces_order_id": r["replaces_order_id"],
        "status": r["status"],
        "cost_cents": r["cost_cents"],
        "warranty_applies": r["warranty_applies"],
    }


def compliance_check_out(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "device_order_id": c["device_order_id"],
        "passed": c["passed"],
        "failure_reasons": c["failure_reasons"],
    }


def clock_state_out(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "current_utc": c["current_utc"],
    }
