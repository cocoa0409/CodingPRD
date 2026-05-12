"""Entity-to-JSON serialization helpers. Common fields rendered uniformly."""

import clock
import db


def _ts(dt):
    return clock.iso_format(dt) if dt is not None else None


def lawyer_dict(lw):
    return {
        "id": lw["id"],
        "full_name": lw["full_name"],
        "bar_number": lw["bar_number"],
        "role": lw["role"],
        "hourly_rate_cents": lw["hourly_rate_cents"],
        "status": lw["status"],
        "client_history": list(lw["client_history"]),
        "created_at": _ts(lw["created_at"]),
        "updated_at": _ts(lw["updated_at"]),
        "version": lw["version"],
    }


def case_dict(c):
    return {
        "id": c["id"],
        "case_number": c["case_number"],
        "case_type": c["case_type"],
        "title": c["title"],
        "claim_amount_cents": c["claim_amount_cents"],
        "lead_lawyer_id": c["lead_lawyer_id"],
        "status": c["status"],
        "posture": c["posture"],
        "client_identity_hash": c["client_identity_hash"],
        "opposing_identity_hash": c["opposing_identity_hash"],
        "intake_document_id": c["intake_document_id"],
        "closed_at": _ts(c.get("closed_at")),
        "settlement_total_cents": c.get("settlement_total_cents"),
        "created_at": _ts(c["created_at"]),
        "updated_at": _ts(c["updated_at"]),
        "version": c["version"],
    }


def party_dict(p):
    return {
        "id": p["id"],
        "case_id": p["case_id"],
        "party_role": p["party_role"],
        "full_name": p["full_name"],
        "id_document_number": p["id_document_number"],
        "identity_verified": p["identity_verified"],
        "contact_email": p["contact_email"],
        "contact_phone": p["contact_phone"],
        "agency_lawyer_id": p.get("agency_lawyer_id"),
        "access_level": p["access_level"],
        "created_at": _ts(p["created_at"]),
        "updated_at": _ts(p["updated_at"]),
        "version": p["version"],
    }


def template_dict(t):
    return {
        "id": t["id"],
        "template_code": t["template_code"],
        "case_type": t["case_type"],
        "name": t["name"],
        "variables": list(t["variables"]),
        "body_template": t["body_template"],
        "status": t["status"],
        "created_at": _ts(t["created_at"]),
        "updated_at": _ts(t["updated_at"]),
        "version": t["version"],
    }


def draft_dict(d):
    return {
        "id": d["id"],
        "case_id": d["case_id"],
        "template_id": d["template_id"],
        "template_version_pinned": d["template_version_pinned"],
        "version_number": d["version_number"],
        "rendered_body": d["rendered_body"],
        "variable_overrides": dict(d.get("variable_overrides") or {}),
        "drafter_lawyer_id": d["drafter_lawyer_id"],
        "senior_reviewer_lawyer_id": d.get("senior_reviewer_lawyer_id"),
        "partner_signoff_lawyer_id": d.get("partner_signoff_lawyer_id"),
        "signed_off_at": _ts(d.get("signed_off_at")),
        "status": d["status"],
        "created_at": _ts(d["created_at"]),
        "updated_at": _ts(d["updated_at"]),
        "version": d["version"],
    }


def hearing_dict(h):
    return {
        "id": h["id"],
        "case_id": h["case_id"],
        "court_room": h["court_room"],
        "scheduled_start": _ts(h["scheduled_start"]),
        "scheduled_end": _ts(h["scheduled_end"]),
        "lead_lawyer_id": h["lead_lawyer_id"],
        "status": h["status"],
        "prep_tasks_generated": h["prep_tasks_generated"],
        "previous_hearing_id": h.get("previous_hearing_id"),
        "created_at": _ts(h["created_at"]),
        "updated_at": _ts(h["updated_at"]),
        "version": h["version"],
    }


def evidence_dict(e):
    # Surface custody chain inline per PRD §4 "Read evidence with custody chain"
    chain = [
        custody_event_dict(ev)
        for ev in sorted(
            (
                ce
                for ce in db.custody_events.values()
                if ce["evidence_id"] == e["id"]
            ),
            key=lambda x: x["occurred_at"],
        )
    ]
    return {
        "id": e["id"],
        "case_id": e["case_id"],
        "evidence_type": e["evidence_type"],
        "collected_at": _ts(e["collected_at"]),
        "collected_by_lawyer_id": e["collected_by_lawyer_id"],
        "case_fact_refs": list(e.get("case_fact_refs") or []),
        "status": e["status"],
        "submitted_at": _ts(e.get("submitted_at")),
        "rebuttal_count": e["rebuttal_count"],
        "custody_chain": chain,
        "created_at": _ts(e["created_at"]),
        "updated_at": _ts(e["updated_at"]),
        "version": e["version"],
    }


def custody_event_dict(ce):
    return {
        "id": ce["id"],
        "evidence_id": ce["evidence_id"],
        "actor_lawyer_id": ce["actor_lawyer_id"],
        "action": ce["action"],
        "occurred_at": _ts(ce["occurred_at"]),
        "location": ce.get("location"),
        "created_at": _ts(ce["created_at"]),
    }


def rebuttal_dict(r):
    return {
        "id": r["id"],
        "evidence_id": r["evidence_id"],
        "filed_by_lawyer_id": r["filed_by_lawyer_id"],
        "ground": r["ground"],
        "status": r["status"],
        "created_at": _ts(r["created_at"]),
    }


def time_entry_dict(te):
    return {
        "id": te["id"],
        "case_id": te["case_id"],
        "lawyer_id": te["lawyer_id"],
        "task_label": te["task_label"],
        "minutes": te["minutes"],
        "billable": te["billable"],
        "hourly_rate_cents_pinned": te["hourly_rate_cents_pinned"],
        "status": te["status"],
        "adjustment_minutes": te["adjustment_minutes"],
        "created_at": _ts(te["created_at"]),
        "updated_at": _ts(te["updated_at"]),
        "version": te["version"],
    }


def bill_dict(b):
    return {
        "id": b["id"],
        "case_id": b["case_id"],
        "billing_mode": b["billing_mode"],
        "fixed_fee_cents": b.get("fixed_fee_cents"),
        "contingent_rate_bps": b.get("contingent_rate_bps"),
        "recovered_amount_cents": b.get("recovered_amount_cents", 0),
        "court_fee_cents": b.get("court_fee_cents"),
        "attorney_fee_cents": b.get("attorney_fee_cents"),
        "expense_reimbursement_cents": b.get("expense_reimbursement_cents", 0),
        "cost_recovery_cents": b.get("cost_recovery_cents", 0),
        "total_due_cents": b.get("total_due_cents"),
        "status": b["status"],
        "created_at": _ts(b["created_at"]),
        "updated_at": _ts(b["updated_at"]),
        "version": b["version"],
    }


def audit_log_dict(a):
    return {
        "id": a["id"],
        "subject_type": a["subject_type"],
        "subject_id": a["subject_id"],
        "actor_role": a["actor_role"],
        "actor_id": a["actor_id"],
        "action": a["action"],
        "payload_snapshot": a.get("payload_snapshot") or {},
        "occurred_at": _ts(a["occurred_at"]),
        "created_at": _ts(a["created_at"]),
    }
