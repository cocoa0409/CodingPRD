"""Entity -> JSON serializers. Derived fields (open_findings_count,
monitoring_posture) are computed from the store at serialization time.
MetricReading is append-only: no updated_at, no version (PRD §2.4).
"""
from services import risk
from utils import fmt_ts, ts_or_none


def model_json(m):
    return {
        "id": m["id"],
        "name": m["name"],
        "business_unit": m["business_unit"],
        "owner_user_id": m["owner_user_id"],
        "is_vendor_model": m["is_vendor_model"],
        "declared_complexity": m["declared_complexity"],
        "assessed_complexity": m["assessed_complexity"],
        "usage_scope": m["usage_scope"],
        "exposure_amount": m["exposure_amount"],
        "risk_score": m["risk_score"],
        "risk_tier": m["risk_tier"],
        "status": m["status"],
        "monitoring_posture": risk.monitoring_posture(m["id"]),
        "open_findings_count": risk.open_findings_count(m["id"]),
        "last_validated_at": ts_or_none(m["last_validated_at"]),
        "validation_due_at": fmt_ts(m["validation_due_at"]),
        "replaced_by_model_id": m["replaced_by_model_id"],
        "created_at": fmt_ts(m["created_at"]),
        "updated_at": fmt_ts(m["updated_at"]),
        "version": m["version"],
    }


def documentation_json(d):
    return {
        "id": d["id"],
        "model_id": d["model_id"],
        "version_label": d["version_label"],
        "has_development_evidence": d["has_development_evidence"],
        "has_testing_evidence": d["has_testing_evidence"],
        "has_data_lineage": d["has_data_lineage"],
        "submitted_by_user_id": d["submitted_by_user_id"],
        "decided_by_user_id": d["decided_by_user_id"],
        "status": d["status"],
        "created_at": fmt_ts(d["created_at"]),
        "updated_at": fmt_ts(d["updated_at"]),
        "version": d["version"],
    }


def change_request_json(c):
    return {
        "id": c["id"],
        "model_id": c["model_id"],
        "change_type": c["change_type"],
        "description": c["description"],
        "submitted_by_user_id": c["submitted_by_user_id"],
        "decided_by_user_id": c["decided_by_user_id"],
        "status": c["status"],
        "created_at": fmt_ts(c["created_at"]),
        "updated_at": fmt_ts(c["updated_at"]),
        "version": c["version"],
    }


def engagement_json(e):
    return {
        "id": e["id"],
        "model_id": e["model_id"],
        "validator_user_id": e["validator_user_id"],
        "scope_conceptual_soundness": e["scope_conceptual_soundness"],
        "scope_outcomes_analysis": e["scope_outcomes_analysis"],
        "period_start": fmt_ts(e["period_start"]),
        "period_end": fmt_ts(e["period_end"]),
        "status": e["status"],
        "outcome": e["outcome"],
        "assessed_complexity": e["assessed_complexity"],
        "completed_at": ts_or_none(e["completed_at"]),
        "created_at": fmt_ts(e["created_at"]),
        "updated_at": fmt_ts(e["updated_at"]),
        "version": e["version"],
    }


def finding_json(f):
    return {
        "id": f["id"],
        "model_id": f["model_id"],
        "source": f["source"],
        "severity": f["severity"],
        "title": f["title"],
        "raised_by_user_id": f["raised_by_user_id"],
        "status": f["status"],
        "remediation_due_at": fmt_ts(f["remediation_due_at"]),
        "escalated_at": ts_or_none(f["escalated_at"]),
        "closed_at": ts_or_none(f["closed_at"]),
        "created_at": fmt_ts(f["created_at"]),
        "updated_at": fmt_ts(f["updated_at"]),
        "version": f["version"],
    }


def metric_json(m):
    return {
        "id": m["id"],
        "model_id": m["model_id"],
        "metric_name": m["metric_name"],
        "direction": m["direction"],
        "threshold_value": m["threshold_value"],
        "status": m["status"],
        "consecutive_breach_count": m["consecutive_breach_count"],
        "created_at": fmt_ts(m["created_at"]),
        "updated_at": fmt_ts(m["updated_at"]),
        "version": m["version"],
    }


def reading_json(r):
    return {
        "id": r["id"],
        "metric_id": r["metric_id"],
        "value": r["value"],
        "observed_at": fmt_ts(r["observed_at"]),
        "is_breach": r["is_breach"],
        "created_at": fmt_ts(r["created_at"]),
    }


def breach_event_json(b):
    return {
        "id": b["id"],
        "metric_id": b["metric_id"],
        "metric_name": b["metric_name"],
        "reading_id": b["reading_id"],
        "breach_value": b["breach_value"],
        "status": b["status"],
        "created_at": fmt_ts(b["created_at"]),
        "updated_at": fmt_ts(b["updated_at"]),
        "version": b["version"],
    }


def assessment_json(a):
    return {
        "id": a["id"],
        "model_id": a["model_id"],
        "completeness_score": a["completeness_score"],
        "valid_months": a["valid_months"],
        "assessed_at": fmt_ts(a["assessed_at"]),
        "valid_until": fmt_ts(a["valid_until"]),
        "status": a["status"],
        "created_at": fmt_ts(a["created_at"]),
        "updated_at": fmt_ts(a["updated_at"]),
        "version": a["version"],
    }


def report_json(r):
    return {
        "id": r["id"],
        "report_type": r["report_type"],
        "period_start": fmt_ts(r["period_start"]),
        "period_end": fmt_ts(r["period_end"]),
        "aggregation_method": r["aggregation_method"],
        "status": r["status"],
        "total_models": r["total_models"],
        "tier_1_count": r["tier_1_count"],
        "open_findings_total": r["open_findings_total"],
        "open_critical_count": r["open_critical_count"],
        "breach_event_count": r["breach_event_count"],
        "overdue_validation_count": r["overdue_validation_count"],
        "inventory_risk_index": r["inventory_risk_index"],
        "submitted_at": ts_or_none(r["submitted_at"]),
        "created_at": fmt_ts(r["created_at"]),
        "updated_at": fmt_ts(r["updated_at"]),
        "version": r["version"],
    }
