"""Entity serializers — output exactly the fields declared in the scaffold
entity table. EscalationEvent carries only id/created_at (PRD 2.4 exception);
everything else carries id/created_at/updated_at/version."""
from timeutil import fmt_dt, fmt_date


def _common(e):
    return {
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def ser_project(p):
    out = {
        "id": p["id"],
        "project_name": p["project_name"],
        "contract_start_date": fmt_date(p.get("contract_start_date")),
        "rfi_response_days": p["rfi_response_days"],
        "ack_required_days": p["ack_required_days"],
        "mobilization_buffer_days": p["mobilization_buffer_days"],
        "long_lead_threshold_days": p["long_lead_threshold_days"],
        "expedite_window_days": p["expedite_window_days"],
        "holiday_dates": sorted([d.isoformat() for d in p["_holidays_set"]]),
        "initial_contingency_cents": p["initial_contingency_cents"],
        "contingency_reserved_cents": p["contingency_reserved_cents"],
        "contingency_spent_cents": p["contingency_spent_cents"],
        "contingency_available_cents": p["contingency_available_cents"],
        "gc_tier_threshold_cents": p["gc_tier_threshold_cents"],
        "ops_scan_index": p["ops_scan_index"],
        "posture": p["posture"],
    }
    out.update(_common(p))
    return out


def ser_spec_section(s):
    out = {
        "id": s["id"],
        "project_id": s["project_id"],
        "section_number": s["section_number"],
        "title": s["title"],
        "lead_time_days": s["lead_time_days"],
        "review_days": s["review_days"],
        "required_discipline": s["required_discipline"],
        "default_need_date": fmt_date(s.get("default_need_date")),
        "responsible_subcontractor_id": s.get("responsible_subcontractor_id"),
        "required_submittal_kinds": list(s["required_submittal_kinds"]),
        "status": s["status"],
    }
    out.update(_common(s))
    return out


def ser_subcontractor(s):
    out = {
        "id": s["id"],
        "project_id": s["project_id"],
        "company_name": s["company_name"],
        "trade": s["trade"],
        "contact_email": s["contact_email"],
        "late_ack_count": s["late_ack_count"],
        "standing": s["standing"],
    }
    out.update(_common(s))
    return out


def ser_reviewer(r):
    out = {
        "id": r["id"],
        "project_id": r["project_id"],
        "display_name": r["display_name"],
        "discipline": r["discipline"],
        "review_capacity": r["review_capacity"],
        "open_review_count": r["open_review_count"],
        "reviewer_status": r["reviewer_status"],
    }
    out.update(_common(r))
    return out


def ser_submittal(s):
    out = {
        "id": s["id"],
        "project_id": s["project_id"],
        "spec_section_id": s["spec_section_id"],
        "submittal_kind": s["submittal_kind"],
        "item_number": s["item_number"],
        "required_on_site_date": fmt_date(s.get("required_on_site_date")),
        "required_approval_date": fmt_date(s.get("required_approval_date")),
        "required_submission_date": fmt_date(s.get("required_submission_date")),
        "is_long_lead": s["is_long_lead"],
        "review_status": s["review_status"],
        "expediting_status": s["expediting_status"],
        "deferral_status": s["deferral_status"],
        "revision_count": s["revision_count"],
    }
    out.update(_common(s))
    return out


def ser_revision(r):
    out = {
        "id": r["id"],
        "submittal_id": r["submittal_id"],
        "revision_number": r["revision_number"],
        "document_ref": r["document_ref"],
        "notes": r["notes"],
        "status": r["status"],
        "action_code": r.get("action_code"),
        "reviewer_id": r.get("reviewer_id"),
        "submitted_date": fmt_date(r.get("submitted_date")),
        "routed_date": fmt_date(r.get("routed_date")),
        "review_due_date": fmt_date(r.get("review_due_date")),
        "returned_date": fmt_date(r.get("returned_date")),
        "is_late_return": r["is_late_return"],
        "return_comments": r.get("return_comments", ""),
    }
    out.update(_common(r))
    return out


def ser_lli(i):
    out = {
        "id": i["id"],
        "project_id": i["project_id"],
        "submittal_id": i["submittal_id"],
        "description": i["description"],
        "criticality": i["criticality"],
        "status": i["status"],
        "required_on_site_date": fmt_date(i.get("required_on_site_date")),
        "days_late": i["days_late"],
        "escalation_level": i["escalation_level"],
        "priority_score": i["priority_score"],
        "quoted_date": fmt_date(i.get("quoted_date")),
        "po_issued_date": fmt_date(i.get("po_issued_date")),
        "shipped_date": fmt_date(i.get("shipped_date")),
        "delivered_date": fmt_date(i.get("delivered_date")),
    }
    out.update(_common(i))
    return out


def ser_rfi(r):
    out = {
        "id": r["id"],
        "project_id": r["project_id"],
        "rfi_number": r["rfi_number"],
        "subject": r["subject"],
        "question_text": r["question_text"],
        "spec_section_id": r.get("spec_section_id"),
        "submittal_id": r.get("submittal_id"),
        "priority": r["priority"],
        "required_discipline": r["required_discipline"],
        "status": r["status"],
        "cycle_count": r["cycle_count"],
        "opened_date": fmt_date(r.get("opened_date")),
        "due_date": fmt_date(r.get("due_date")),
        "is_overdue": r["is_overdue"],
        "routed_reviewer_id": r.get("routed_reviewer_id"),
        "routed_date": fmt_date(r.get("routed_date")),
        "answer_text": r.get("answer_text"),
        "answered_date": fmt_date(r.get("answered_date")),
        "answered_by_reviewer_id": r.get("answered_by_reviewer_id"),
        "is_late_answer": r["is_late_answer"],
        "cost_impact_flag": r["cost_impact_flag"],
        "schedule_impact_flag": r["schedule_impact_flag"],
        "estimated_schedule_days": r.get("estimated_schedule_days"),
    }
    out.update(_common(r))
    return out


def ser_assessment(a):
    out = {
        "id": a["id"],
        "project_id": a["project_id"],
        "rfi_id": a["rfi_id"],
        "status": a["status"],
        "estimated_cost_cents": a["estimated_cost_cents"],
        "provisional_delta_cents": a["provisional_delta_cents"],
        "sub_quote_cents": a.get("sub_quote_cents"),
        "gc_markup_tier": a.get("gc_markup_tier"),
        "final_delta_cents": a.get("final_delta_cents"),
        "priced_by_user_id": a.get("priced_by_user_id"),
        "decided_by_user_id": a.get("decided_by_user_id"),
        "price_cycle": a["price_cycle"],
    }
    out.update(_common(a))
    return out


def ser_distribution(d):
    out = {
        "id": d["id"],
        "project_id": d["project_id"],
        "subcontractor_id": d["subcontractor_id"],
        "source_type": d["source_type"],
        "source_id": d["source_id"],
        "status": d["status"],
        "sent_date": fmt_date(d.get("sent_date")),
        "ack_due_date": fmt_date(d.get("ack_due_date")),
        "acknowledged_date": fmt_date(d.get("acknowledged_date")),
        "is_overdue": d["is_overdue"],
    }
    out.update(_common(d))
    return out


def ser_activity(a):
    out = {
        "id": a["id"],
        "project_id": a["project_id"],
        "submittal_id": a["submittal_id"],
        "subcontractor_id": a["subcontractor_id"],
        "description": a["description"],
        "start_date": fmt_date(a.get("start_date")),
        "end_date": fmt_date(a.get("end_date")),
        "status": a["status"],
        "shift_applied_days": a["shift_applied_days"],
    }
    out.update(_common(a))
    return out


def ser_owner_report(r):
    out = {
        "id": r["id"],
        "project_id": r["project_id"],
        "period_start": fmt_date(r.get("period_start")),
        "period_end": fmt_date(r.get("period_end")),
        "status": r["status"],
        "published_at": fmt_dt(r["published_at"]) if r.get("published_at") else None,
        "snapshot_metrics": r.get("snapshot_metrics"),
        "superseded_by_report_id": r.get("superseded_by_report_id"),
    }
    out.update(_common(r))
    return out


def ser_escalation_event(e):
    # Append-only log: id + created_at only, no updated_at/version.
    return {
        "id": e["id"],
        "project_id": e["project_id"],
        "event_type": e["event_type"],
        "source_type": e["source_type"],
        "source_id": e["source_id"],
        "detail": e["detail"],
        "event_date": fmt_date(e.get("event_date")),
        "created_at": fmt_dt(e["created_at"]),
    }
