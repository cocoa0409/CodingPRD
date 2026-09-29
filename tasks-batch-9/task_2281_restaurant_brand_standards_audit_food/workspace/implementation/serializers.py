"""Wire representations for every entity."""

from decimal import Decimal

from common import fmt_dt


def _num(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _common(record):
    return {
        "created_at": fmt_dt(record["created_at"]),
        "updated_at": fmt_dt(record["updated_at"]),
        "version": record["version"],
    }


def brand(rec):
    out = {
        "id": rec["id"],
        "name": rec["name"],
        "brand_code": rec["brand_code"],
        "unannounced_min_ratio_pct": rec["unannounced_min_ratio_pct"],
        "brand_risk_index": _num(rec["brand_risk_index"]),
        "brand_risk_tier": rec["brand_risk_tier"],
        "location_count": rec["location_count"],
        "default_location_count": rec["default_location_count"],
    }
    out.update(_common(rec))
    return out


def franchisee(rec):
    out = {
        "id": rec["id"],
        "brand_id": rec["brand_id"],
        "legal_name": rec["legal_name"],
        "contact_email": rec["contact_email"],
        "agreement_signed_at": fmt_dt(rec["agreement_signed_at"]),
        "open_default_location_count": rec["open_default_location_count"],
        "termination_recommended": rec["termination_recommended"],
    }
    out.update(_common(rec))
    return out


def auditor(rec):
    out = {
        "id": rec["id"],
        "full_name": rec["full_name"],
        "employee_code": rec["employee_code"],
        "status": rec["status"],
        "certification_period_start": fmt_dt(rec["certification_period_start"]),
        "reliability_score": _num(rec["reliability_score"]),
        "suspension_reason": rec["suspension_reason"],
        "finalized_visit_count": rec["finalized_visit_count"],
    }
    out.update(_common(rec))
    return out


def location(rec):
    out = {
        "id": rec["id"],
        "brand_id": rec["brand_id"],
        "franchisee_id": rec["franchisee_id"],
        "store_number": rec["store_number"],
        "region_code": rec["region_code"],
        "standing_score": _num(rec["standing_score"]),
        "latest_grade": rec["latest_grade"],
        "open_corrective_action_count": rec["open_corrective_action_count"],
        "repeat_violation_count": rec["repeat_violation_count"],
        "escalation_level": rec["escalation_level"],
        "franchise_agreement_status": rec["franchise_agreement_status"],
        "cure_period_started_at": fmt_dt(rec["cure_period_started_at"]),
    }
    out.update(_common(rec))
    return out


def rubric_version(rec):
    out = {
        "id": rec["id"],
        "brand_id": rec["brand_id"],
        "supersedes_rubric_version_id": rec["supersedes_rubric_version_id"],
        "version_label": rec["version_label"],
        "effective_from": fmt_dt(rec["effective_from"]),
        "total_points": rec["total_points"],
        "status": rec["status"],
        "published_at": fmt_dt(rec["published_at"]),
        "item_count": rec["item_count"],
        "critical_item_count": rec["critical_item_count"],
    }
    out.update(_common(rec))
    return out


def rubric_item(rec):
    return {
        "id": rec["id"],
        "rubric_version_id": rec["rubric_version_id"],
        "item_code": rec["item_code"],
        "section": rec["section"],
        "max_points": rec["max_points"],
        "is_critical": rec["is_critical"],
        "display_order": rec["display_order"],
        "created_at": fmt_dt(rec["created_at"]),
    }


def audit_visit(rec):
    out = {
        "id": rec["id"],
        "location_id": rec["location_id"],
        "auditor_id": rec["auditor_id"],
        "rubric_version_id": rec["rubric_version_id"],
        "shadow_of_visit_id": rec["shadow_of_visit_id"],
        "linked_health_inspection_id": rec["linked_health_inspection_id"],
        "visit_type": rec["visit_type"],
        "scheduled_start_at": fmt_dt(rec["scheduled_start_at"]),
        "scheduled_end_at": fmt_dt(rec["scheduled_end_at"]),
        "announced_notice_hours": _num(rec["announced_notice_hours"]),
        "status": rec["status"],
        "started_at": fmt_dt(rec["started_at"]),
        "submitted_at": fmt_dt(rec["submitted_at"]),
        "finalized_at": fmt_dt(rec["finalized_at"]),
        "food_safety_percent": _num(rec["food_safety_percent"]),
        "brand_standards_percent": _num(rec["brand_standards_percent"]),
        "facility_percent": _num(rec["facility_percent"]),
        "critical_violation_count": rec["critical_violation_count"],
        "critical_penalty_points": _num(rec["critical_penalty_points"]),
        "health_component_percent": _num(rec["health_component_percent"]),
        "composite_score": _num(rec["composite_score"]),
        "composite_variant": rec["composite_variant"],
        "grade": rec["grade"],
        "rescore_count": rec["rescore_count"],
        "void_reason": rec["void_reason"],
    }
    out.update(_common(rec))
    return out


def scored_item(rec):
    out = {
        "id": rec["id"],
        "visit_id": rec["visit_id"],
        "rubric_item_id": rec["rubric_item_id"],
        "points_awarded": rec["points_awarded"],
        "original_points_awarded": rec["original_points_awarded"],
        "amended_points_awarded": rec["amended_points_awarded"],
        "effective_points_awarded": rec["effective_points_awarded"],
        "is_violation": rec["is_violation"],
        "severity": rec["severity"],
        "status": rec["status"],
        "note": rec["note"],
    }
    out.update(_common(rec))
    return out


def corrective_action(rec):
    out = {
        "id": rec["id"],
        "scored_item_id": rec["scored_item_id"],
        "location_id": rec["location_id"],
        "assigned_franchisee_id": rec["assigned_franchisee_id"],
        "severity": rec["severity"],
        "due_at": fmt_dt(rec["due_at"]),
        "status": rec["status"],
        "submission_count": rec["submission_count"],
        "rejection_count": rec["rejection_count"],
        "evidence_photo_count": rec["evidence_photo_count"],
        "submitted_at": fmt_dt(rec["submitted_at"]),
        "verified_at": fmt_dt(rec["verified_at"]),
        "escalated_at": fmt_dt(rec["escalated_at"]),
    }
    out.update(_common(rec))
    return out


def evidence_photo(rec):
    return {
        "id": rec["id"],
        "corrective_action_id": rec["corrective_action_id"],
        "dispute_id": rec["dispute_id"],
        "file_uri": rec["file_uri"],
        "captured_at": fmt_dt(rec["captured_at"]),
        "caption": rec["caption"],
        "uploaded_by_role": rec["uploaded_by_role"],
        "created_at": fmt_dt(rec["created_at"]),
    }


def dispute(rec):
    out = {
        "id": rec["id"],
        "scored_item_id": rec["scored_item_id"],
        "filed_by_franchisee_id": rec["filed_by_franchisee_id"],
        "reviewer_auditor_id": rec["reviewer_auditor_id"],
        "requested_points": rec["requested_points"],
        "reason": rec["reason"],
        "status": rec["status"],
        "info_request_count": rec["info_request_count"],
        "resolution_points": _num(rec["resolution_points"]),
        "filed_at": fmt_dt(rec["filed_at"]),
        "resolved_at": fmt_dt(rec["resolved_at"]),
    }
    out.update(_common(rec))
    return out


def health_inspection(rec):
    out = {
        "id": rec["id"],
        "location_id": rec["location_id"],
        "authority_name": rec["authority_name"],
        "inspection_date": fmt_dt(rec["inspection_date"]),
        "points_scored": rec["points_scored"],
        "points_possible": rec["points_possible"],
        "letter_grade": rec["letter_grade"],
        "status": rec["status"],
        "disregard_reason": rec["disregard_reason"],
    }
    out.update(_common(rec))
    return out


def calibration_record(rec):
    return {
        "id": rec["id"],
        "shadow_visit_id": rec["shadow_visit_id"],
        "primary_visit_id": rec["primary_visit_id"],
        "auditor_id": rec["auditor_id"],
        "reviewer_auditor_id": rec["reviewer_auditor_id"],
        "variance_points": _num(rec["variance_points"]),
        "reliability_delta": _num(rec["reliability_delta"]),
        "band": rec["band"],
        "recorded_at": fmt_dt(rec["recorded_at"]),
        "created_at": fmt_dt(rec["created_at"]),
    }


def escalation_event(rec):
    return {
        "id": rec["id"],
        "location_id": rec["location_id"],
        "corrective_action_id": rec["corrective_action_id"],
        "audit_visit_id": rec["audit_visit_id"],
        "event_type": rec["event_type"],
        "level_delta": rec["level_delta"],
        "resulting_escalation_level": rec["resulting_escalation_level"],
        "resulting_agreement_status": rec["resulting_agreement_status"],
        "occurred_at": fmt_dt(rec["occurred_at"]),
        "created_at": fmt_dt(rec["created_at"]),
    }
