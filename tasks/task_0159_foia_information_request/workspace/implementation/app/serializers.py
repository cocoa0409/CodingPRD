"""Public-facing serializers — produce the JSON shape returned to clients.

Each function takes the internal dict (as stored in :mod:`app.store`) and
returns a plain dict suitable for the response envelope's ``data`` field.
"""

from __future__ import annotations

from typing import Optional


def _versioned_common(entity: dict) -> dict:
    return {
        "id": entity["id"],
        "created_at": entity["created_at"],
        "updated_at": entity.get("updated_at"),
        "version": entity.get("version"),
    }


def _immutable_common(entity: dict) -> dict:
    return {
        "id": entity["id"],
        "created_at": entity["created_at"],
    }


def serialize_requester(r: dict) -> dict:
    return {
        **_versioned_common(r),
        "full_name": r["full_name"],
        "contact_email": r["contact_email"],
        "requester_tier": r["requester_tier"],
        "tier_justification": r.get("tier_justification"),
        "status": r["status"],
    }


def serialize_request(r: dict) -> dict:
    return {
        **_versioned_common(r),
        "requester_id": r["requester_id"],
        "subject_summary": r["subject_summary"],
        "status": r["status"],
        "fee_estimate_accepted": r.get("fee_estimate_accepted", False),
        "fee_waiver_requested": r.get("fee_waiver_requested", False),
        "fee_waiver_granted": r.get("fee_waiver_granted"),
        "glomar_invoked": r.get("glomar_invoked", False),
        "glomar_exemption_basis": list(r.get("glomar_exemption_basis") or []),
        "filed_at": r.get("filed_at"),
        "response_due_at": r.get("response_due_at"),
        "tolling_days_consumed": r.get("tolling_days_consumed", 0),
        "determination_at": r.get("determination_at"),
    }


def serialize_responsive_record(r: dict) -> dict:
    return {
        **_versioned_common(r),
        "request_id": r["request_id"],
        "title": r["title"],
        "page_count": r["page_count"],
        "contains_third_party_info": r.get("contains_third_party_info", False),
        "third_party_id": r.get("third_party_id"),
        "disposition": r["disposition"],
    }


def serialize_exemption_claim(c: dict) -> dict:
    return {
        **_immutable_common(c),
        "record_id": c["record_id"],
        "exemption_code": c["exemption_code"],
        "redaction_scope": c["redaction_scope"],
        "rationale": c["rationale"],
    }


def serialize_third_party_notice(n: dict) -> dict:
    return {
        **_versioned_common(n),
        "request_id": n["request_id"],
        "record_id": n["record_id"],
        "third_party_id": n["third_party_id"],
        "status": n["status"],
        "response_deadline": n.get("response_deadline"),
        "objection_grounds": n.get("objection_grounds"),
    }


def serialize_appeal(a: dict) -> dict:
    return {
        **_versioned_common(a),
        "request_id": a["request_id"],
        "appellant_role": a["appellant_role"],
        "grounds": a["grounds"],
        "status": a["status"],
        "filed_at": a.get("filed_at"),
        "decision_at": a.get("decision_at"),
        "deciding_officer_id": a.get("deciding_officer_id"),
    }


def serialize_fee_assessment(f: dict) -> dict:
    return {
        **_versioned_common(f),
        "request_id": f["request_id"],
        "tier_at_assessment": f.get("tier_at_assessment"),
        "estimated_pages": f["estimated_pages"],
        "estimated_search_hours": f["estimated_search_hours"],
        "estimated_review_hours": f["estimated_review_hours"],
        "estimate_total_cents": f.get("estimate_total_cents", 0),
        "final_total_cents": f.get("final_total_cents", 0),
        "status": f["status"],
    }


def serialize_audit_entry(e: dict) -> dict:
    return {
        **_immutable_common(e),
        "subject_type": e["subject_type"],
        "subject_id": e["subject_id"],
        "event_code": e["event_code"],
        "actor_role": e.get("actor_role"),
        "actor_id": e.get("actor_id"),
        "payload": e.get("payload") or {},
    }
