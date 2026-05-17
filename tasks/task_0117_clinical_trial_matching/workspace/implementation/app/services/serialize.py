"""Entity → JSON serializers. Produce stable, fully-populated output shapes."""
from __future__ import annotations

from typing import Any

from ..clock import iso_format


def _iso(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return iso_format(value)


def serialize_trial(t: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": t["id"],
        "protocol_code": t["protocol_code"],
        "title": t["title"],
        "sponsor_org": t["sponsor_org"],
        "status": t["status"],
        "inclusion_criteria": t["inclusion_criteria"],
        "exclusion_criteria": t["exclusion_criteria"],
        "active_consent_version": t["active_consent_version"],
        "randomization_scheme": t["randomization_scheme"],
        "block_size": t["block_size"],
        "stratification_field": t["stratification_field"],
        "target_enrollment": t["target_enrollment"],
        "enrolled_count": t["enrolled_count"],
        "irb_decision_note": t["irb_decision_note"],
        "irb_approval_expires_at": _iso(t["irb_approval_expires_at"]),
        "blood_draw_window_days": t["blood_draw_window_days"],
        "created_by_user_id": t["created_by_user_id"],
        "created_at": _iso(t["created_at"]),
        "updated_at": _iso(t["updated_at"]),
        "version": t["version"],
    }


def serialize_arm(a: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": a["id"],
        "trial_id": a["trial_id"],
        "code": a["code"],
        "label": a["label"],
        "weight": a["weight"],
        "assigned_count": a["assigned_count"],
        "created_at": _iso(a["created_at"]),
        "updated_at": _iso(a["updated_at"]),
        "version": a["version"],
    }


def serialize_consent_version(cv: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": cv["id"],
        "trial_id": cv["trial_id"],
        "version": cv["version"],
        "document_uri": cv["document_uri"],
        "change_summary": cv["change_summary"],
        "requires_re_consent": cv["requires_re_consent"],
        "published_at": _iso(cv["published_at"]),
        "created_at": _iso(cv["created_at"]),
    }


def serialize_participant(p: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": p["id"],
        "trial_id": p["trial_id"],
        "arm_id": p["arm_id"],
        "profile": p["profile"],
        "status": p["status"],
        "signed_consent_version": p["signed_consent_version"],
        "eligibility_score": p["eligibility_score"],
        "open_ae_count": p["open_ae_count"],
        "enrolled_at": _iso(p["enrolled_at"]),
        "created_at": _iso(p["created_at"]),
        "updated_at": _iso(p["updated_at"]),
        "version": p["version"],
    }


def serialize_visit(v: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": v["id"],
        "participant_id": v["participant_id"],
        "sequence_no": v["sequence_no"],
        "target_date": _iso(v["target_date"]),
        "status": v["status"],
        "actual_draw_at": _iso(v["actual_draw_at"]),
        "compensation_cents": v["compensation_cents"],
        "created_at": _iso(v["created_at"]),
        "updated_at": _iso(v["updated_at"]),
        "version": v["version"],
    }


def serialize_adverse_event(ae: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": ae["id"],
        "participant_id": ae["participant_id"],
        "severity": ae["severity"],
        "status": ae["status"],
        "reported_at": _iso(ae["reported_at"]),
        "narrative": ae["narrative"],
        "caused_visit_id": ae["caused_visit_id"],
        "resolution_note": ae["resolution_note"],
        "created_at": _iso(ae["created_at"]),
        "updated_at": _iso(ae["updated_at"]),
        "version": ae["version"],
    }


def serialize_payment(p: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": p["id"],
        "participant_id": p["participant_id"],
        "visit_id": p["visit_id"],
        "kind": p["kind"],
        "amount_cents": p["amount_cents"],
        "paid_at": _iso(p["paid_at"]),
        "created_at": _iso(p["created_at"]),
    }


def serialize_irb_review(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": r["id"],
        "trial_id": r["trial_id"],
        "decision": r["decision"],
        "reviewer_id": r["reviewer_id"],
        "decided_at": _iso(r["decided_at"]),
        "notes": r["notes"],
        "created_at": _iso(r["created_at"]),
        "updated_at": _iso(r["updated_at"]),
        "version": r["version"],
    }
