"""Entity serializers: only scaffold-declared fields are exposed."""

import calc
import db


def _common(entity):
    return {
        "id": entity["id"],
        "created_at": db.fmt_ts(entity["created_at"]),
        "updated_at": db.fmt_ts(entity["updated_at"]),
        "version": entity["version"],
    }


def member_out(m):
    data = _common(m)
    data.update({
        "member_ref": m["member_ref"],
        "full_name": m["full_name"],
        "program": m["program"],
        "enrollment_status": m["enrollment_status"],
        "open_case_count": calc.member_open_case_count(m["id"]),
        "ctm_linked_case_count": calc.member_ctm_linked_case_count(m["id"]),
    })
    return data


def provider_out(p):
    data = _common(p)
    data.update({
        "npi": p["npi"],
        "legal_name": p["legal_name"],
        "contract_status": p["contract_status"],
        "w9_on_file": p["w9_on_file"],
    })
    return data


def policy_out(p):
    data = _common(p)
    data.update({
        "program": p["program"],
        "case_kind": p["case_kind"],
        "priority_track": p["priority_track"],
        "resolution_hours": p["resolution_hours"],
        "extension_hours": p["extension_hours"],
        "effectuation_hours": p["effectuation_hours"],
        "business_hours_only": p["business_hours_only"],
        "active": p["active"],
    })
    return data


def case_out(c):
    data = _common(c)
    data.update({
        "member_id": c["member_id"],
        "provider_id": c["provider_id"],
        "case_kind": c["case_kind"],
        "priority_track": c["priority_track"],
        "expedited_requested": c["expedited_requested"],
        "expedited_justification": c["expedited_justification"],
        "status": c["status"],
        "decision_outcome": c["decision_outcome"],
        "received_at": db.fmt_ts(c["received_at"]),
        "acknowledged_at": db.fmt_ts(c["acknowledged_at"]),
        "decided_at": db.fmt_ts(c["decided_at"]),
        "notified_at": db.fmt_ts(c["notified_at"]),
        "closed_at": db.fmt_ts(c["closed_at"]),
        "extension_applied": c["extension_applied"],
        "resolution_due_at": db.fmt_ts(c["resolution_due_at"]),
        "effectuation_due_at": db.fmt_ts(c["effectuation_due_at"]),
        "ctm_linked": c["ctm_linked"],
        "reopened_from_case_id": c["reopened_from_case_id"],
        "overdue": calc.case_overdue(c),
    })
    return data


def event_out(e):
    return {
        "id": e["id"],
        "case_id": e["case_id"],
        "event_type": e["event_type"],
        "actor_role": e["actor_role"],
        "actor_id": e["actor_id"],
        "body": e["body"],
        "occurred_at": db.fmt_ts(e["occurred_at"]),
        "created_at": db.fmt_ts(e["created_at"]),
    }


def review_out(r):
    data = _common(r)
    score = r["medical_necessity_score"]
    data.update({
        "case_id": r["case_id"],
        "reviewer_physician_id": r["reviewer_physician_id"],
        "status": r["status"],
        "determination": r["determination"],
        "medical_necessity_score": float(score) if score is not None else None,
        "superseded_by_review_id": r["superseded_by_review_id"],
    })
    return data


def notification_out(n):
    data = _common(n)
    score = n["completeness_score"]
    data.update({
        "case_id": n["case_id"],
        "recipient_kind": n["recipient_kind"],
        "notification_kind": n["notification_kind"],
        "status": n["status"],
        "required_elements": list(n["required_elements"]),
        "supplied_elements": list(n["supplied_elements"]),
        "completeness_score": float(score) if score is not None else None,
        "sent_at": db.fmt_ts(n["sent_at"]),
    })
    return data


def referral_out(r):
    data = _common(r)
    data.update({
        "case_id": r["case_id"],
        "ire_organization_code": r["ire_organization_code"],
        "status": r["status"],
        "forwarded_at": db.fmt_ts(r["forwarded_at"]),
        "ire_decision": r["ire_decision"],
        "ire_decision_received_at": db.fmt_ts(r["ire_decision_received_at"]),
    })
    return data


def effectuation_out(e):
    data = _common(e)
    pct = e["timeliness_percent"]
    data.update({
        "case_id": e["case_id"],
        "referral_id": e["referral_id"],
        "status": e["status"],
        "payment_amount_cents": e["payment_amount_cents"],
        "timeliness_percent": float(pct) if pct is not None else None,
        "completed_at": db.fmt_ts(e["completed_at"]),
    })
    return data


def reopening_out(r):
    data = _common(r)
    data.update({
        "case_id": r["case_id"],
        "request_reason": r["request_reason"],
        "status": r["status"],
        "requested_at": db.fmt_ts(r["requested_at"]),
        "decided_at": db.fmt_ts(r["decided_at"]),
        "spawned_case_id": r["spawned_case_id"],
    })
    return data


def audit_record_out(r):
    return {
        "id": r["id"],
        "report_period": r["report_period"],
        "case_id": r["case_id"],
        "case_kind": r["case_kind"],
        "priority_track": r["priority_track"],
        "resolution_timely": r["resolution_timely"],
        "effectuation_timely": r["effectuation_timely"],
        "snapshot_at": db.fmt_ts(r["snapshot_at"]),
        "created_at": db.fmt_ts(r["created_at"]),
    }
