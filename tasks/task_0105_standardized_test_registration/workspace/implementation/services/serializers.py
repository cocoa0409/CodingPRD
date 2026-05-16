"""Per-entity JSON serializers — return the public-facing shape only."""

from typing import Optional


def _copy(d: dict, fields):
    return {f: d.get(f) for f in fields}


def serialize_test_event(e: dict) -> dict:
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
        "test_type": e["test_type"],
        "form_code": e["form_code"],
        "subject": e.get("subject"),
        "test_date": e["test_date"],
        "registration_deadline": e["registration_deadline"],
        "late_registration_deadline": e["late_registration_deadline"],
        "score_release_date": e["score_release_date"],
        "base_fee_cents": e["base_fee_cents"],
        "late_fee_cents": e["late_fee_cents"],
        "status": e["status"],
    }


def serialize_test_center(c: dict) -> dict:
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "name": c["name"],
        "address": c["address"],
        "state_code": c["state_code"],
        "timezone": c["timezone"],
        "status": c["status"],
    }


def serialize_capacity(c: dict) -> dict:
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "test_event_id": c["test_event_id"],
        "test_center_id": c["test_center_id"],
        "total_capacity": c["total_capacity"],
        "accommodation_capacity": c["accommodation_capacity"],
        "confirmed_seats_used": c["confirmed_seats_used"],
        "accommodation_seats_used": c["accommodation_seats_used"],
        "standby_seats_pending": c["standby_seats_pending"],
        "available_seats": c["available_seats"],
    }


def serialize_candidate(c: dict) -> dict:
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "legal_name": c["legal_name"],
        "email": c["email"],
        "date_of_birth": c["date_of_birth"],
        "home_state_code": c["home_state_code"],
        "has_iep_or_504": c["has_iep_or_504"],
    }


def serialize_registration(r: dict) -> dict:
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "candidate_id": r["candidate_id"],
        "test_event_id": r["test_event_id"],
        "test_center_id": r["test_center_id"],
        "status": r["status"],
        "registered_at": r["registered_at"],
        "registration_channel": r["registration_channel"],
        "accommodation_required": r["accommodation_required"],
        "base_fee_cents_charged": r["base_fee_cents_charged"],
        "late_fee_cents_charged": r["late_fee_cents_charged"],
        "accommodation_fee_cents_charged": r["accommodation_fee_cents_charged"],
        "amount_charged_cents": r["amount_charged_cents"],
        "amount_refunded_cents": r["amount_refunded_cents"],
        "amount_retained_cents": r["amount_retained_cents"],
        "standby_promotion_eligibility_at": r["standby_promotion_eligibility_at"],
        "locked_accommodation_request_version": r.get("locked_accommodation_request_version"),
    }


def serialize_accommodation_request(a: dict) -> dict:
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "candidate_id": a["candidate_id"],
        "test_event_id": a["test_event_id"],
        "requested_accommodations": list(a["requested_accommodations"]),
        "supporting_documents": list(a["supporting_documents"]),
        "status": a["status"],
        "reviewer_user_id": a.get("reviewer_user_id"),
        "submission_deadline_at": a["submission_deadline_at"],
        "review_deadline_at": a["review_deadline_at"],
    }


def serialize_id_verification(v: dict) -> dict:
    return {
        "id": v["id"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
        "registration_id": v["registration_id"],
        "id_document_type": v["id_document_type"],
        "issuing_state_code": v.get("issuing_state_code"),
        "id_expires_on": v["id_expires_on"],
        "status": v["status"],
        "rejection_reason": v.get("rejection_reason"),
        "cross_state_override_granted": v["cross_state_override_granted"],
    }


def serialize_score_report(s: dict) -> dict:
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "registration_id": s["registration_id"],
        "section_scores": dict(s["section_scores"]),
        "total_score": s["total_score"],
        "report_type": s["report_type"],
    }


def serialize_clep_credit_award(c: dict) -> dict:
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "score_report_id": c["score_report_id"],
        "candidate_id": c["candidate_id"],
        "credit_status": c["credit_status"],
        "credit_units": c["credit_units"],
        "posted_by_user_id": c["posted_by_user_id"],
    }


def serialize_refund(r: dict) -> dict:
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "registration_id": r["registration_id"],
        "amount_cents": r["amount_cents"],
        "tier_label": r["tier_label"],
        "refund_channel": r["refund_channel"],
    }
