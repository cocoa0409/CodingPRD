"""Entity serializers. Datetimes -> ISO 8601 UTC with three fractional
digits. ApplicabilityEvaluation carries no updated_at/version (PRD 2.4)."""
from utils import fmt_ts


def _common(e):
    return {
        "id": e["id"],
        "created_at": fmt_ts(e["created_at"]),
        "updated_at": fmt_ts(e["updated_at"]),
        "version": e["version"],
    }


def ser_retention_policy(p):
    out = {
        "policy_code": p["policy_code"],
        "duration_days": p["duration_days"],
        "disposal_action": p["disposal_action"],
    }
    out.update(_common(p))
    return out


def ser_data_element(e):
    out = {
        "element_key": e["element_key"],
        "category": e["category"],
        "classification": e["classification"],
        "status": e["status"],
    }
    out.update(_common(e))
    return out


def ser_data_system(s):
    out = {
        "system_key": s["system_key"],
        "hosting_region": s["hosting_region"],
        "stores_categories": list(s["stores_categories"]),
        "status": s["status"],
    }
    out.update(_common(s))
    return out


def ser_notice(n):
    out = {
        "scope": n["scope"],
        "title": n["title"],
        "body": n["body"],
        "effective_from": fmt_ts(n["effective_from"]),
        "effective_to": fmt_ts(n["effective_to"]),
        "supersedes_notice_id": n["supersedes_notice_id"],
        "status": n["status"],
        "published_at": fmt_ts(n["published_at"]),
        "superseded_by_notice_id": n["superseded_by_notice_id"],
    }
    out.update(_common(n))
    return out


def ser_state_law_rule(r):
    out = {
        "state_code": r["state_code"],
        "law_name": r["law_name"],
        "resident_records_threshold": r["resident_records_threshold"],
        "revenue_share_threshold_pct": r["revenue_share_threshold_pct"],
        "request_deadline_days": r["request_deadline_days"],
        "extension_days": r["extension_days"],
    }
    out.update(_common(r))
    return out


def ser_vendor(v):
    out = {
        "vendor_name": v["vendor_name"],
        "home_region": v["home_region"],
        "processes_categories": list(v["processes_categories"]),
        "risk_tier": v["risk_tier"],
        "status": v["status"],
    }
    out.update(_common(v))
    return out


def ser_contract(c):
    out = {
        "vendor_id": c["vendor_id"],
        "provided_clauses": list(c["provided_clauses"]),
        "required_clauses": list(c["required_clauses"]),
        "missing_clauses": list(c["missing_clauses"]),
        "verification_status": c["verification_status"],
        "status": c["status"],
    }
    out.update(_common(c))
    return out


def ser_activity(a):
    out = {
        "activity_name": a["activity_name"],
        "business_unit": a["business_unit"],
        "notice_scope": a["notice_scope"],
        "data_element_ids": list(a["data_element_ids"]),
        "vendor_id": a["vendor_id"],
        "risk_score": a["risk_score"],
        "pia_required": a["pia_required"],
        "status": a["status"],
    }
    out.update(_common(a))
    return out


def ser_purpose(p):
    out = {
        "activity_id": p["activity_id"],
        "purpose_type": p["purpose_type"],
        "legal_basis": p["legal_basis"],
        "retention_policy_id": p["retention_policy_id"],
        "pinned_notice_id": p["pinned_notice_id"],
        "retention_expires_at": fmt_ts(p["retention_expires_at"]),
        "status": p["status"],
    }
    out.update(_common(p))
    return out


def ser_assessment(a):
    out = {
        "activity_id": a["activity_id"],
        "trigger_reason": a["trigger_reason"],
        "screening_score": a["screening_score"],
        "final_score": a["final_score"],
        "submitted_by_user_id": a["submitted_by_user_id"],
        "status": a["status"],
    }
    out.update(_common(a))
    return out


def ser_consumer(c):
    out = {
        "email": c["email"],
        "full_name": c["full_name"],
        "state_code": c["state_code"],
    }
    out.update(_common(c))
    return out


def ser_rights_request(r):
    from services.requests_svc import is_overdue
    out = {
        "consumer_id": r["consumer_id"],
        "request_type": r["request_type"],
        "requested_categories": list(r["requested_categories"]),
        "applicable_state_code": r["applicable_state_code"],
        "provisional_due_at": fmt_ts(r["provisional_due_at"]),
        "final_due_at": fmt_ts(r["final_due_at"]),
        "is_overdue": is_overdue(r),
        "verification_status": r["verification_status"],
        "fulfillment_status": r["fulfillment_status"],
    }
    out.update(_common(r))
    return out


def ser_task(t):
    out = {
        "request_id": t["request_id"],
        "data_system_id": t["data_system_id"],
        "status": t["status"],
        "outcome_notes": t["outcome_notes"],
    }
    out.update(_common(t))
    return out


def ser_transfer(t):
    out = {
        "source_system_id": t["source_system_id"],
        "vendor_id": t["vendor_id"],
        "vendor_contract_id": t["vendor_contract_id"],
        "activity_id": t["activity_id"],
        "dest_region": t["dest_region"],
        "mechanism": t["mechanism"],
        "effective_from": fmt_ts(t["effective_from"]),
        "effective_to": fmt_ts(t["effective_to"]),
        "suspension_reason": t["suspension_reason"],
        "status": t["status"],
    }
    out.update(_common(t))
    return out


def ser_evaluation(e):
    return {
        "id": e["id"],
        "state_law_rule_id": e["state_law_rule_id"],
        "evaluation_run_id": e["evaluation_run_id"],
        "resident_consumer_count": e["resident_consumer_count"],
        "revenue_share_pct": e["revenue_share_pct"],
        "applies": e["applies"],
        "margin_to_threshold": e["margin_to_threshold"],
        "created_at": fmt_ts(e["created_at"]),
    }
