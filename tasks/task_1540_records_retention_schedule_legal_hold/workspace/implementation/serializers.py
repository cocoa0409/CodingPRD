"""Entity -> JSON dict serialization. Derived fields (posture, hold counts,
obligation counts, ack aggregates) are computed at read time."""
from db import db
from utils import fmt_ts
from services.core import (
    derive_posture,
    record_active_hold_count,
    hold_active_scope_count,
    hold_all_acknowledged,
    hold_late_ack_count,
    custodian_open_obligations,
)


def _common(e):
    return {
        "id": e["id"],
        "created_at": fmt_ts(e["created_at"]),
        "updated_at": fmt_ts(e["updated_at"]),
        "version": e["version"],
    }


def program_view(p):
    d = _common(p)
    d.update({
        "name": p["name"],
        "fiscal_year_end_month": p["fiscal_year_end_month"],
        "fiscal_year_end_day": p["fiscal_year_end_day"],
        "ack_deadline_days": p["ack_deadline_days"],
        "reminder_interval_days": p["reminder_interval_days"],
        "max_reminders_before_escalation": p["max_reminders_before_escalation"],
        "stale_hold_days": p["stale_hold_days"],
        "over_preservation_warn_pct": p["over_preservation_warn_pct"],
        "ack_sla_mode": p["ack_sla_mode"],
    })
    return d


def record_class_view(c):
    d = _common(c)
    d.update({
        "program_id": c["program_id"],
        "code": c["code"],
        "name": c["name"],
        "monthly_storage_cost_cents_per_gb": c["monthly_storage_cost_cents_per_gb"],
    })
    return d


def jurisdiction_view(j):
    d = _common(j)
    d.update({"program_id": j["program_id"], "code": j["code"], "name": j["name"]})
    return d


def custodian_view(c):
    d = _common(c)
    d.update({
        "program_id": c["program_id"],
        "email": c["email"],
        "full_name": c["full_name"],
        "department": c["department"],
        "open_obligation_count": custodian_open_obligations(c["id"]),
    })
    return d


def rule_view(r):
    d = _common(r)
    d.update({
        "program_id": r["program_id"],
        "record_class_id": r["record_class_id"],
        "jurisdiction_id": r["jurisdiction_id"],
        "rule_code": r["rule_code"],
        "retention_months": r["retention_months"],
        "trigger_basis": r["trigger_basis"],
        "effective_from": fmt_ts(r["effective_from"]),
        "effective_to": fmt_ts(r["effective_to"]),
        "supersedes_rule_id": r["supersedes_rule_id"],
        "superseded_by_id": r["superseded_by_id"],
        "status": r["status"],
    })
    return d


def conflict_view(c):
    d = _common(c)
    d.update({
        "program_id": c["program_id"],
        "record_class_id": c["record_class_id"],
        "jurisdiction_id": c["jurisdiction_id"],
        "incumbent_rule_id": c["incumbent_rule_id"],
        "challenger_rule_id": c["challenger_rule_id"],
        "governing_rule_id": c["governing_rule_id"],
        "resolution_strategy": c["resolution_strategy"],
        "resolution_justification": c["resolution_justification"],
        "resolved_by_user_id": c["resolved_by_user_id"],
        "status": c["status"],
    })
    return d


def record_view(r):
    ahc = record_active_hold_count(r)
    d = _common(r)
    d.update({
        "program_id": r["program_id"],
        "record_class_id": r["record_class_id"],
        "jurisdiction_id": r["jurisdiction_id"],
        "owner_custodian_id": r["owner_custodian_id"],
        "title": r["title"],
        "source_system": r["source_system"],
        "event_date": fmt_ts(r["event_date"]),
        "size_gb": r["size_gb"],
        "auto_delete_enabled": r["auto_delete_enabled"],
        "retention_due_date": fmt_ts(r.get("retention_due_date")),
        "governing_rule_id": r.get("governing_rule_id"),
        "active_hold_count": ahc,
        "auto_delete_suspended": ahc > 0,
        "disposition_posture": derive_posture(r),
        "destroyed_at": fmt_ts(r.get("destroyed_at")),
        "status": r["status"],
    })
    return d


def hold_view(h):
    d = _common(h)
    d.update({
        "program_id": h["program_id"],
        "matter_ref": h["matter_ref"],
        "title": h["title"],
        "reason": h["reason"],
        "created_by_user_id": h["created_by_user_id"],
        "issued_at": fmt_ts(h["issued_at"]),
        "released_at": fmt_ts(h["released_at"]),
        "release_reason": h["release_reason"],
        "last_activity_at": fmt_ts(h["last_activity_at"]),
        "late_ack_count": hold_late_ack_count(h["id"]),
        "all_acknowledged": hold_all_acknowledged(h["id"]),
        "active_scope_count": hold_active_scope_count(h["id"]),
        "status": h["status"],
    })
    return d


def hold_custodian_view(a):
    d = _common(a)
    d.update({
        "hold_id": a["hold_id"],
        "custodian_id": a["custodian_id"],
        "program_id": a["program_id"],
        "ack_due_date": fmt_ts(a["ack_due_date"]),
        "acknowledged_at": fmt_ts(a["acknowledged_at"]),
        "was_late": a["was_late"],
        "reminder_count": a["reminder_count"],
        "last_reminder_at": fmt_ts(a["last_reminder_at"]),
        "escalated_at": fmt_ts(a["escalated_at"]),
        "status": a["status"],
    })
    return d


def hold_scope_item_view(i):
    d = _common(i)
    d.update({
        "hold_id": i["hold_id"],
        "record_id": i["record_id"],
        "program_id": i["program_id"],
        "added_at": fmt_ts(i["added_at"]),
        "activated_at": fmt_ts(i["activated_at"]),
        "released_at": fmt_ts(i["released_at"]),
        "status": i["status"],
    })
    return d


def disposition_request_view(r):
    d = _common(r)
    d.update({
        "program_id": r["program_id"],
        "requester_user_id": r["requester_user_id"],
        "method": r["method"],
        "justification": r["justification"],
        "submitted_at": fmt_ts(r["submitted_at"]),
        "decided_at": fmt_ts(r["decided_at"]),
        "decided_by_user_id": r["decided_by_user_id"],
        "rejection_reason": r["rejection_reason"],
        "executed_at": fmt_ts(r["executed_at"]),
        "stale_item_count": r["stale_item_count"],
        "status": r["status"],
    })
    return d


def disposition_item_view(i):
    d = _common(i)
    d.update({
        "request_id": i["request_id"],
        "record_id": i["record_id"],
        "program_id": i["program_id"],
        "snapshot_posture": i["snapshot_posture"],
        "snapshot_due_date": fmt_ts(i["snapshot_due_date"]),
        "snapshot_hold_count": i["snapshot_hold_count"],
        "destroyed_at": fmt_ts(i["destroyed_at"]),
        "status": i["status"],
    })
    return d


def certificate_view(c):
    return {
        "id": c["id"],
        "created_at": fmt_ts(c["created_at"]),
        "program_id": c["program_id"],
        "request_id": c["request_id"],
        "disposition_item_id": c["disposition_item_id"],
        "record_id": c["record_id"],
        "record_title": c["record_title"],
        "record_class_code": c["record_class_code"],
        "jurisdiction_code": c["jurisdiction_code"],
        "retention_due_date": fmt_ts(c["retention_due_date"]),
        "destroyed_at": fmt_ts(c["destroyed_at"]),
        "method": c["method"],
        "content_hash": c["content_hash"],
        "witness_user_id": c["witness_user_id"],
        "certificate_seq": c["certificate_seq"],
    }


def audit_view(a):
    d = _common(a)
    d.update({
        "program_id": a["program_id"],
        "active_hold_count": a["active_hold_count"],
        "stale_hold_count": a["stale_hold_count"],
        "held_record_count": a["held_record_count"],
        "eligible_record_count": a["eligible_record_count"],
        "over_preserved_record_count": a["over_preserved_record_count"],
        "over_preservation_pct": a["over_preservation_pct"],
        "over_preservation_cost_cents": a["over_preservation_cost_cents"],
        "threshold_breached": a["threshold_breached"],
        "closed_at": fmt_ts(a["closed_at"]),
        "status": a["status"],
    })
    return d


def reminder_log_view(e):
    return {
        "id": e["id"],
        "created_at": fmt_ts(e["created_at"]),
        "program_id": e["program_id"],
        "hold_id": e["hold_id"],
        "hold_custodian_id": e["hold_custodian_id"],
        "custodian_id": e["custodian_id"],
        "kind": e["kind"],
        "sent_at": fmt_ts(e["sent_at"]),
        "reminder_seq": e["reminder_seq"],
    }


def freeze_window_view(w):
    d = _common(w)
    d.update({
        "program_id": w["program_id"],
        "start_at": fmt_ts(w["start_at"]),
        "end_at": fmt_ts(w["end_at"]),
        "reason": w["reason"],
        "cancelled_at": fmt_ts(w["cancelled_at"]),
        "status": w["status"],
    })
    return d
