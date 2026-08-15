"""Entity serializers: exact public field sets with derivational fields
computed at read time. Internal bookkeeping fields are underscore-prefixed and
never leave the process."""
from services.core import (
    contract_available,
    contract_committed,
    contract_spent,
    department_compliance,
    department_posture,
    department_spent,
    document_translated_language_codes,
    interpreter_minutes_current_month,
)


def serialize_department(d):
    spent = department_spent(d["id"])
    score = department_compliance(d["id"])
    return {
        "id": d["id"],
        "name": d["name"],
        "service_area_code": d["service_area_code"],
        "annual_budget_cents": d["annual_budget_cents"],
        "signage_status": d["signage_status"],
        "spent_cents": spent,
        "remaining_cents": d["annual_budget_cents"] - spent,
        "compliance_score": score,
        "posture": ("GOOD_STANDING" if score >= 800 else "WATCH" if score >= 600 else "NONCOMPLIANT"),
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def serialize_assessment(a):
    return {
        "id": a["id"],
        "department_id": a["department_id"],
        "language_code": a["language_code"],
        "plan_year": a["plan_year"],
        "period_start": a["period_start"],
        "period_end": a["period_end"],
        "lep_speaker_count": a["lep_speaker_count"],
        "service_area_population": a["service_area_population"],
        "encounter_count": a["encounter_count"],
        "total_encounters": a["total_encounters"],
        "lep_share": float(a["lep_share"]),
        "encounter_share": float(a["encounter_share"]),
        "threshold_language_safe": a["threshold_language_safe"],
        "priority_language": a["priority_language"],
        "status": a["status"],
        "created_by_user_id": a["created_by_user_id"],
        "reviewed_by_user_id": a["reviewed_by_user_id"],
        "rejection_note": a["rejection_note"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def serialize_document(doc):
    return {
        "id": doc["id"],
        "department_id": doc["department_id"],
        "title": doc["title"],
        "document_type": doc["document_type"],
        "base_language": doc["base_language"],
        "status": doc["status"],
        "translated_language_codes": document_translated_language_codes(doc["id"]),
        "created_at": doc["created_at"],
        "updated_at": doc["updated_at"],
        "version": doc["version"],
    }


def serialize_job(j):
    return {
        "id": j["id"],
        "document_id": j["document_id"],
        "vendor_contract_id": j["vendor_contract_id"],
        "target_language_code": j["target_language_code"],
        "word_count": j["word_count"],
        "rush": j["rush"],
        "provisional_cost_cents": j["provisional_cost_cents"],
        "translator_id": j["translator_id"],
        "reviewer_id": j["reviewer_id"],
        "submitted_word_count": j["submitted_word_count"],
        "revision_count": j["revision_count"],
        "final_cost_cents": j["final_cost_cents"],
        "superseded_by_job_id": j["superseded_by_job_id"],
        "status": j["status"],
        "created_at": j["created_at"],
        "updated_at": j["updated_at"],
        "version": j["version"],
    }


def serialize_interpreter(it):
    return {
        "id": it["id"],
        "full_name": it["full_name"],
        "language_codes": list(it["language_codes"]),
        "modalities": list(it["modalities"]),
        "tier": it["tier"],
        "vendor_contract_id": it["vendor_contract_id"],
        "confidentiality_signed_at": it["confidentiality_signed_at"],
        "quality_rating": it["quality_rating"],
        "minutes_current_month": interpreter_minutes_current_month(it["id"]),
        "status": it["status"],
        "created_at": it["created_at"],
        "updated_at": it["updated_at"],
        "version": it["version"],
    }


def serialize_request(r):
    return {
        "id": r["id"],
        "department_id": r["department_id"],
        "language_code": r["language_code"],
        "modality": r["modality"],
        "encounter_setting": r["encounter_setting"],
        "scheduled_start": r["scheduled_start"],
        "scheduled_duration_minutes": r["scheduled_duration_minutes"],
        "interpreter_id": r["interpreter_id"],
        "estimated_cost_cents": r["estimated_cost_cents"],
        "actual_minutes": r["actual_minutes"],
        "final_cost_cents": r["final_cost_cents"],
        "completed_at": r["completed_at"],
        "refund_clawed_back": r["refund_clawed_back"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_complaint(c):
    return {
        "id": c["id"],
        "department_id": c["department_id"],
        "interpretation_request_id": c["interpretation_request_id"],
        "category": c["category"],
        "description": c["description"],
        "recorded_by_user_id": c["recorded_by_user_id"],
        "status": c["status"],
        "adjudicated_by_user_id": c["adjudicated_by_user_id"],
        "adjudicated_at": c["adjudicated_at"],
        "remedy": c["remedy"],
        "remediation_due_at": c["remediation_due_at"],
        "resolution_note": c["resolution_note"],
        "closed_at": c["closed_at"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_contract(c):
    committed = contract_committed(c["id"])
    spent = contract_spent(c["id"])
    return {
        "id": c["id"],
        "vendor_name": c["vendor_name"],
        "ceiling_cents": c["ceiling_cents"],
        "phone_per_minute_cents": c["phone_per_minute_cents"],
        "video_per_minute_cents": c["video_per_minute_cents"],
        "in_person_per_minute_cents": c["in_person_per_minute_cents"],
        "translation_per_word_cents": c["translation_per_word_cents"],
        "in_person_travel_flat_cents": c["in_person_travel_flat_cents"],
        "committed_cents": committed,
        "spent_cents": spent,
        "available_cents": c["ceiling_cents"] - spent - committed,
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_plan(p):
    return {
        "id": p["id"],
        "plan_year": p["plan_year"],
        "summary": p["summary"],
        "status": p["status"],
        "published_at": p["published_at"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }
