from __future__ import annotations

"""Public serialization of entity dicts to JSON-friendly response shapes.

Internal dicts may carry helper fields (such as recomputed booleans cached for
speed) that we keep but make sure to expose the documented shape.
"""

from clock import now as clock_now


def _common(entity: dict, *, append_only: bool = False) -> dict:
    out = {
        "id": entity["id"],
        "created_at": entity["created_at"],
    }
    if not append_only:
        out["updated_at"] = entity["updated_at"]
        out["version"] = entity["version"]
    return out


def serialize_application(a: dict) -> dict:
    return {
        **_common(a),
        "sponsor_name": a["sponsor_name"],
        "drug_name": a["drug_name"],
        "indication": a["indication"],
        "phase": a["phase"],
        "applicant_id": a["applicant_id"],
        "review_track": a["review_track"],
        "status": a["status"],
        "current_submission_version": a["current_submission_version"],
        "approved_submission_version": a.get("approved_submission_version"),
        "approval_resolution_id": a.get("approval_resolution_id"),
    }


def serialize_submission(s: dict) -> dict:
    return {
        **_common(s),
        "application_id": s["application_id"],
        "version_number": s["version_number"],
        "protocol_doc_uri": s.get("protocol_doc_uri"),
        "investigator_brochure_uri": s.get("investigator_brochure_uri"),
        "informed_consent_uri": s.get("informed_consent_uri"),
        "cv_doc_uri": s.get("cv_doc_uri"),
        "checklist_complete": s["checklist_complete"],
        "prescreen_status": s["prescreen_status"],
        "prescreen_notes": s.get("prescreen_notes"),
        "is_current": s["is_current"],
    }


def serialize_committee_member(m: dict) -> dict:
    from services_state import compute_member_is_active

    return {
        **_common(m),
        "full_name": m["full_name"],
        "qualification": m["qualification"],
        "term_start": m["term_start"],
        "term_end": m["term_end"],
        "is_active": compute_member_is_active(m),
        "status": m["status"],
        "affiliated_sponsors": list(m.get("affiliated_sponsors", [])),
    }


def serialize_conflict(c: dict) -> dict:
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "member_id": c["member_id"],
        "application_id": c["application_id"],
        "conflict_type": c["conflict_type"],
        "details": c.get("details"),
        "auto_detected": c["auto_detected"],
    }


def serialize_meeting(m: dict) -> dict:
    return {
        **_common(m),
        "meeting_type": m["meeting_type"],
        "scheduled_at": m["scheduled_at"],
        "status": m["status"],
        "agenda_published_at": m.get("agenda_published_at"),
        "convener_member_id": m["convener_member_id"],
        "lead_time_hours": m["lead_time_hours"],
    }


def serialize_agenda_item(a: dict) -> dict:
    return {
        **_common(a),
        "meeting_id": a["meeting_id"],
        "application_id": a["application_id"],
        "pinned_submission_version": a.get("pinned_submission_version"),
        "review_kind": a["review_kind"],
        "status": a["status"],
        "quorum_required": a.get("quorum_required"),
        "eligible_voter_count": a.get("eligible_voter_count"),
        "annual_report_id": a.get("annual_report_id"),
        "rectification_id": a.get("rectification_id"),
    }


def serialize_attendance(a: dict) -> dict:
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "agenda_item_id": a["agenda_item_id"],
        "member_id": a["member_id"],
        "confirmed_at": a["confirmed_at"],
    }


def serialize_vote(v: dict) -> dict:
    return {
        "id": v["id"],
        "created_at": v["created_at"],
        "agenda_item_id": v["agenda_item_id"],
        "member_id": v["member_id"],
        "vote_mode": v["vote_mode"],
    }


def serialize_resolution(r: dict) -> dict:
    return {
        **_common(r),
        "agenda_item_id": r["agenda_item_id"],
        "application_id": r["application_id"],
        "outcome": r["outcome"],
        "tally": r["tally"],
        "document_uri": r["document_uri"],
        "pinned_submission_version": r.get("pinned_submission_version"),
    }


def serialize_rectification(r: dict) -> dict:
    return {
        **_common(r),
        "application_id": r["application_id"],
        "source_resolution_id": r["source_resolution_id"],
        "opinions": list(r.get("opinions", [])),
        "due_at": r["due_at"],
        "applicant_response_uri": r.get("applicant_response_uri"),
        "responded_at": r.get("responded_at"),
        "status": r["status"],
    }


def serialize_annual_report(a: dict) -> dict:
    return {
        **_common(a),
        "application_id": a["application_id"],
        "report_period_start": a["report_period_start"],
        "report_period_end": a["report_period_end"],
        "report_kind": a["report_kind"],
        "serious_adverse_event_count": a["serious_adverse_event_count"],
        "total_adverse_event_count": a["total_adverse_event_count"],
        "enrollment_count": a["enrollment_count"],
        "outcome": a.get("outcome"),
        "safety_alert_flag": a["safety_alert_flag"],
        "status": a["status"],
    }


def serialize_audit_log(a: dict) -> dict:
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "actor_role": a["actor_role"],
        "actor_id": a["actor_id"],
        "event_type": a["event_type"],
        "subject_entity": a["subject_entity"],
        "subject_id": a["subject_id"],
        "payload": a.get("payload", {}),
    }
