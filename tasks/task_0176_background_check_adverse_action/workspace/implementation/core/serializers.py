"""Resource serializers — produce the JSON-safe dicts returned by routes."""
from __future__ import annotations

from typing import Any, Dict


def _copy_common(row: dict) -> dict:
    """Copy the standard system fields that every resource exposes."""
    out: Dict[str, Any] = {
        "id": row["id"],
        "created_at": row["created_at"],
    }
    if "updated_at" in row:
        out["updated_at"] = row["updated_at"]
    if "version" in row:
        out["version"] = row["version"]
    return out


def serialize_candidate(row: dict) -> dict:
    out = _copy_common(row)
    out.update(
        {
            "full_name": row.get("full_name"),
            "email": row.get("email"),
            "residence_jurisdiction": row.get("residence_jurisdiction"),
            "date_of_birth": row.get("date_of_birth"),
            "eligibility_posture": row.get("eligibility_posture"),
            "salary_history_disclosed": row.get("salary_history_disclosed", False),
            "archived_at": row.get("archived_at"),
        }
    )
    return out


def serialize_consent(row: dict) -> dict:
    out = _copy_common(row)
    out.update(
        {
            "candidate_id": row.get("candidate_id"),
            "disclosure_text_hash": row.get("disclosure_text_hash"),
            "consent_signature": row.get("consent_signature"),
            "consent_timestamp": row.get("consent_timestamp"),
            "disclosure_presented_at": row.get("disclosure_presented_at"),
            "revoked_at": row.get("revoked_at"),
            "status": row.get("status"),
        }
    )
    return out


def serialize_jurisdiction(row: dict) -> dict:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "jurisdiction_code": row.get("jurisdiction_code"),
        "criminal_lookback_years": row.get("criminal_lookback_years"),
        "salary_history_ban": row.get("salary_history_ban"),
        "ban_the_box_stage": row.get("ban_the_box_stage"),
        "adverse_action_waiting_business_days": row.get(
            "adverse_action_waiting_business_days"
        ),
    }


def serialize_order(row: dict) -> dict:
    out = _copy_common(row)
    out.update(
        {
            "candidate_id": row.get("candidate_id"),
            "consent_disclosure_id": row.get("consent_disclosure_id"),
            "stage_at_order": row.get("stage_at_order"),
            "requested_packages": list(row.get("requested_packages", [])),
            "status": row.get("status"),
            "composite_decision": row.get("composite_decision"),
            "opened_by_role": row.get("opened_by_role"),
            "opened_by_user_id": row.get("opened_by_user_id"),
            "adjudicated_by_user_id": row.get("adjudicated_by_user_id"),
        }
    )
    # Include the spawned VerificationItem summaries (id + kind) so the
    # order response exposes the child items it spawned. PRD §3.3 says a
    # successful order creation "spawns one VerificationItem per entry
    # of requested_packages"; surfacing the resulting ids here lets the
    # client follow up via GET /fcra/verification-items/{itemId} without
    # a separate list endpoint.
    from core.store import store
    out["verification_items"] = [
        {"id": it["id"], "kind": it["kind"]}
        for it in store.list_items_for_order(row["id"])
    ]
    return out


def serialize_item(row: dict) -> dict:
    out = _copy_common(row)
    out.update(
        {
            "order_id": row.get("order_id"),
            "kind": row.get("kind"),
            "status": row.get("status"),
            "raw_finding": row.get("raw_finding"),
            "severity_score": row.get("severity_score"),
            "rework_count": row.get("rework_count", 0),
            "dispute_id": row.get("dispute_id"),
        }
    )
    return out


def serialize_dispute(row: dict) -> dict:
    out = _copy_common(row)
    out.update(
        {
            "verification_item_id": row.get("verification_item_id"),
            "candidate_id": row.get("candidate_id"),
            "reason_text": row.get("reason_text"),
            "status": row.get("status"),
            "resolution_note": row.get("resolution_note"),
        }
    )
    return out


def serialize_flow(row: dict) -> dict:
    out = _copy_common(row)
    out.update(
        {
            "order_id": row.get("order_id"),
            "pre_adverse_notice_sent_at": row.get("pre_adverse_notice_sent_at"),
            "waiting_period_business_days": row.get("waiting_period_business_days"),
            "earliest_final_eligible_at": row.get("earliest_final_eligible_at"),
            "final_adverse_action_at": row.get("final_adverse_action_at"),
            "notification_status": row.get("notification_status"),
            "procedural_status": row.get("procedural_status"),
        }
    )
    return out


def serialize_audit_event(row: dict) -> dict:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "event_type": row.get("event_type"),
        "subject_entity": row.get("subject_entity"),
        "subject_id": row.get("subject_id"),
        "actor_role": row.get("actor_role"),
        "actor_user_id": row.get("actor_user_id"),
        "previous_event_id": row.get("previous_event_id"),
        "payload_hash": row.get("payload_hash"),
    }
