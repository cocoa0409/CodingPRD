"""Wire representations.

Client-supplied instants are echoed back exactly as the client wrote them; every
server-stamped instant is rendered canonically with three fractional digits
(PRD 2.4).  Training recommendations omit updated_at and version entirely.
"""
import calc
from store import store
from util import fmt_dt, num


def _raw_or_fmt(rec, field):
    raw = rec.get(field + "_raw")
    if raw is not None:
        return raw
    return fmt_dt(rec.get(field))


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": fmt_dt(rec["created_at"]),
        "updated_at": fmt_dt(rec["updated_at"]),
        "version": rec["version"],
    }


def asset(rec):
    out = _common(rec)
    out.update(
        {
            "name": rec["name"],
            "asset_class": rec["asset_class"],
            "criticality_tier": rec["criticality_tier"],
            "compliance_regimes": list(rec["compliance_regimes"]),
            "exposure_score": num(rec["exposure_score"]),
            "last_tested_at": _raw_or_fmt(rec, "last_tested_at"),
            "exposure_state": rec["exposure_state"],
            "open_finding_count": rec["open_finding_count"],
            "open_critical_finding_count": rec["open_critical_finding_count"],
            "remediated_finding_count": rec["remediated_finding_count"],
            "last_cleared_at": fmt_dt(rec["last_cleared_at"]),
        }
    )
    return out


def test_plan(rec):
    out = _common(rec)
    out.update(
        {
            "fiscal_year": rec["fiscal_year"],
            "prioritization_mode": rec["prioritization_mode"],
            "risk_appetite_score": rec["risk_appetite_score"],
            "planned_engagement_count": rec["planned_engagement_count"],
            "admission_threshold": num(rec["admission_threshold"]),
            "coverage_score": num(rec["coverage_score"]),
            "status": rec["status"],
            "total_risk_points": rec["total_risk_points"],
            "open_risk_points": rec["open_risk_points"],
            "closed_risk_points": rec["closed_risk_points"],
            "accepted_risk_points": rec["accepted_risk_points"],
            "duplicate_risk_points": rec["duplicate_risk_points"],
        }
    )
    return out


def scope_item(rec):
    out = _common(rec)
    out.update(
        {
            "test_plan_id": rec["test_plan_id"],
            "asset_id": rec["asset_id"],
            "justification": rec["justification"],
            "requested_engagement_hours": num(rec["requested_engagement_hours"]),
            "priority_score": num(rec["priority_score"]),
            "priority_rank": rec["priority_rank"],
            "below_threshold_flag": rec["below_threshold_flag"],
            "status": rec["status"],
            "decision_note": rec["decision_note"],
            "scored_mode": rec["scored_mode"],
        }
    )
    return out


def engagement(rec):
    out = _common(rec)
    out.update(
        {
            "test_plan_id": rec["test_plan_id"],
            "scope_item_id": rec["scope_item_id"],
            "engagement_type": rec["engagement_type"],
            "window_start": _raw_or_fmt(rec, "window_start"),
            "window_end": _raw_or_fmt(rec, "window_end"),
            "hours_allocated": num(rec["hours_allocated"]),
            "hours_reserved": num(rec["hours_reserved"]),
            "hours_consumed": num(rec["hours_consumed"]),
            "hours_available": num(rec["hours_available"]),
            "execution_state": rec["execution_state"],
            "authorization_state": rec["authorization_state"],
            "suspension_reason": rec["suspension_reason"],
            "provisional_assurance_score": num(rec["provisional_assurance_score"]),
            "final_assurance_score": num(rec["final_assurance_score"]),
        }
    )
    return out


def roe(rec):
    out = _common(rec)
    out.update(
        {
            "engagement_id": rec["engagement_id"],
            "drafted_by_user_id": rec["drafted_by_user_id"],
            "exclusions": list(rec["exclusions"]),
            "allowed_techniques": list(rec["allowed_techniques"]),
            "emergency_stop_procedure": rec["emergency_stop_procedure"],
            "escalation_contact": rec["escalation_contact"],
            "status": rec["status"],
            "signed_by_user_id": rec["signed_by_user_id"],
            "signed_at": fmt_dt(rec["signed_at"]),
            "active_target_count": rec["active_target_count"],
        }
    )
    return out


def target(rec):
    out = _common(rec)
    out.update(
        {
            "roe_id": rec["roe_id"],
            "asset_id": rec["asset_id"],
            "window_start": _raw_or_fmt(rec, "window_start"),
            "window_end": _raw_or_fmt(rec, "window_end"),
            "technique_allowlist": list(rec["technique_allowlist"]),
            "state": rec["state"],
            "exclusion_reason": rec["exclusion_reason"],
            "cooldown_hours": rec["cooldown_hours"],
        }
    )
    return out


def tester(rec):
    out = _common(rec)
    out.update(
        {
            "full_name": rec["full_name"],
            "certifications": list(rec["certifications"]),
            "max_concurrent_engagements": rec["max_concurrent_engagements"],
            "clearance_expires_at": _raw_or_fmt(rec, "clearance_expires_at"),
            "background_check_status": rec["background_check_status"],
            "background_check_at": fmt_dt(rec["background_check_at"]),
            "qualification_score": num(rec["qualification_score"]),
            "availability_state": rec["availability_state"],
            "active_assignment_count": rec["active_assignment_count"],
        }
    )
    return out


def assignment(rec):
    out = _common(rec)
    out.update(
        {
            "engagement_id": rec["engagement_id"],
            "tester_id": rec["tester_id"],
            "assignment_role": rec["assignment_role"],
            "interval_start": _raw_or_fmt(rec, "interval_start"),
            "interval_end": _raw_or_fmt(rec, "interval_end"),
            "requested_hours": num(rec["requested_hours"]),
            "granted_asset_ids": list(rec["granted_asset_ids"]),
            "access_state": rec["access_state"],
            "provisioned_at": fmt_dt(rec["provisioned_at"]),
            "revoked_at": fmt_dt(rec["revoked_at"]),
            "settled_hours": num(rec["settled_hours"]),
        }
    )
    return out


def finding(rec):
    out = _common(rec)
    out.update(
        {
            "engagement_id": rec["engagement_id"],
            "asset_id": rec["asset_id"],
            "discovered_by_tester_id": rec["discovered_by_tester_id"],
            "duplicate_of_finding_id": rec["duplicate_of_finding_id"],
            "title": rec["title"],
            "reproduction_steps": rec["reproduction_steps"],
            "business_impact_narrative": rec["business_impact_narrative"],
            "technical_base_score": num(rec["technical_base_score"]),
            "exposure_class": rec["exposure_class"],
            "root_cause_theme": rec["root_cause_theme"],
            "severity_score": num(rec["severity_score"]),
            "severity_band": rec["severity_band"],
            "severity_points": rec["severity_points"],
            "immediate_action_required": rec["immediate_action_required"],
            "status": rec["status"],
            "discovered_at": fmt_dt(rec["discovered_at"]),
            "closed_at": fmt_dt(rec["closed_at"]),
        }
    )
    return out


def alert(rec):
    out = _common(rec)
    out.update(
        {
            "finding_id": rec["finding_id"],
            "raised_at": fmt_dt(rec["raised_at"]),
            "ack_deadline_at": fmt_dt(rec["ack_deadline_at"]),
            "acknowledged_at": fmt_dt(rec["acknowledged_at"]),
            "acknowledged_by_user_id": rec["acknowledged_by_user_id"],
            "containment_action": rec["containment_action"],
            "escalation_level": rec["escalation_level"],
            "state": rec["state"],
        }
    )
    return out


def remediation(rec):
    out = _common(rec)
    out.update(
        {
            "finding_id": rec["finding_id"],
            "owner_user_id": rec["owner_user_id"],
            "validation_requirement": rec["validation_requirement"],
            "remediation_plan": rec["remediation_plan"],
            "sla_days": rec["sla_days"],
            "due_at": fmt_dt(rec["due_at"]),
            "extension_count": rec["extension_count"],
            "overdue_flag": calc.is_overdue(rec, store.now()),
            "status": rec["status"],
            "submitted_at": fmt_dt(rec["submitted_at"]),
            "evidence_uri": rec["evidence_uri"],
        }
    )
    return out


def retest(rec):
    out = _common(rec)
    out.update(
        {
            "remediation_id": rec["remediation_id"],
            "verifier_tester_id": rec["verifier_tester_id"],
            "evidence_uri": rec["evidence_uri"],
            "outcome": rec["outcome"],
            "residual_note": rec["residual_note"],
            "state": rec["state"],
            "verified_at": fmt_dt(rec["verified_at"]),
            "days_late": rec["days_late"],
            "signed_off_by_user_id": rec["signed_off_by_user_id"],
            "signed_off_at": fmt_dt(rec["signed_off_at"]),
            "closure_note": rec["closure_note"],
        }
    )
    return out


def training(rec):
    return {
        "id": rec["id"],
        "created_at": fmt_dt(rec["created_at"]),
        "test_plan_id": rec["test_plan_id"],
        "root_cause_theme": rec["root_cause_theme"],
        "window_start": _raw_or_fmt(rec, "window_start"),
        "window_end": _raw_or_fmt(rec, "window_end"),
        "recurrence_count": rec["recurrence_count"],
        "priority_score": num(rec["priority_score"]),
        "urgency_band": rec["urgency_band"],
        "source_engagement_count": rec["source_engagement_count"],
        "generated_at": fmt_dt(rec["generated_at"]),
        "contributing_finding_ids": list(rec["contributing_finding_ids"]),
    }
