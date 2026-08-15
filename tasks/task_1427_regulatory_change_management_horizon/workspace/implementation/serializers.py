"""Entity -> API dict serialization (PRD §2.5 common fields).

Computed-on-read fields are derived here against the current logical clock so
they are always fresh: BusinessOwner counters, Control effectiveness /
next_review_due, TrainingRollout roll-ups and past_due, EvidencePackage
artifact_count.
"""

from decimal import Decimal

from db import fmt_dt, now_clock, store
from services.calculations import (effectiveness_factor, next_review_due,
                                   training_completion_pct)

ACTIVE_ASSESSMENT_STATUSES = ("ASSIGNED", "IN_PROGRESS", "RETURNED", "SUBMITTED")
OPEN_ESCALATION_STATUSES = ("OPEN", "ACKNOWLEDGED")


def _dt(value):
    return fmt_dt(value) if value is not None else None


def _num(value):
    """Decimal -> JSON number (float). Ints pass through."""
    if isinstance(value, Decimal):
        return float(value)
    return value


def _common(entity):
    return {
        "id": entity["id"],
        "created_at": _dt(entity["created_at"]),
        "updated_at": _dt(entity["updated_at"]),
        "version": entity["version"],
    }


# ---------------------------------------------------------------------------


def business_owner_to_api(owner):
    active = sum(
        1 for a in store.assessments.values()
        if a["business_owner_id"] == owner["id"] and a["status"] in ACTIVE_ASSESSMENT_STATUSES
    )
    open_esc = sum(
        1 for e in store.escalations.values()
        if e["business_owner_id"] == owner["id"] and e["status"] in OPEN_ESCALATION_STATUSES
    )
    out = _common(owner)
    out.update({
        "name": owner["name"],
        "department": owner["department"],
        "email": owner["email"],
        "active_assessment_count": active,
        "open_escalation_count": open_esc,
        "assignment_suspended": open_esc >= 3,
    })
    return out


def regulatory_change_to_api(change):
    out = _common(change)
    out.update({
        "citation": change["citation"],
        "title": change["title"],
        "summary": change["summary"],
        "feed_source": change["feed_source"],
        "jurisdiction": change["jurisdiction"],
        "regulator": change["regulator"],
        "published_at": _dt(change["published_at"]),
        "effective_date": _dt(change["effective_date"]),
        "comment_deadline": _dt(change["comment_deadline"]),
        "severity_hint": change["severity_hint"],
        "supersedes_change_id": change["supersedes_change_id"],
        "superseded_by_id": change["superseded_by_id"],
        "status": change["status"],
        "applicability": change["applicability"],
        "triage_rationale": change["triage_rationale"],
        "triage_round": change["triage_round"],
        "provisional_risk_tier": change["provisional_risk_tier"],
        "risk_tier": change["risk_tier"],
        "business_owner_id": change["business_owner_id"],
        "created_by_user_id": change["created_by_user_id"],
        "triaged_by_user_id": change["triaged_by_user_id"],
    })
    return out


def obligation_to_api(obligation):
    out = _common(obligation)
    out.update({
        "obligation_code": obligation["obligation_code"],
        "title": obligation["title"],
        "regulatory_change_id": obligation["regulatory_change_id"],
        "criticality": obligation["criticality"],
        "status": obligation["status"],
    })
    return out


def control_to_api(control):
    clock = now_clock()
    out = _common(control)
    out.update({
        "control_code": control["control_code"],
        "title": control["title"],
        "owner_department": control["owner_department"],
        "review_frequency_days": control["review_frequency_days"],
        "last_reviewed_at": _dt(control["last_reviewed_at"]),
        "effectiveness_factor": _num(effectiveness_factor(control, clock)),
        "next_review_due": _dt(next_review_due(control)),
        "policy_version": control["policy_version"],
        "status": control["status"],
    })
    return out


def mapping_to_api(mapping):
    out = _common(mapping)
    out.update({
        "obligation_id": mapping["obligation_id"],
        "control_id": mapping["control_id"],
        "coverage_weight": mapping["coverage_weight"],
        "status": mapping["status"],
        "created_by_user_id": mapping["created_by_user_id"],
        "approved_by_user_id": mapping["approved_by_user_id"],
    })
    return out


def register_to_api(register):
    out = _common(register)
    out.update({
        "current_version_number": register["current_version_number"],
        "singleton_note": register["singleton_note"],
    })
    return out


def register_version_to_api(version):
    # Append-only snapshot: only id + created_at (no updated_at / version).
    return {
        "id": version["id"],
        "created_at": _dt(version["created_at"]),
        "version_number": version["version_number"],
        "published_at": _dt(version["published_at"]),
        "obligation_codes": list(version["obligation_codes"]),
        "obligation_count": version["obligation_count"],
        "register_checksum": version["register_checksum"],
    }


def assessment_to_api(assessment):
    out = _common(assessment)
    out.update({
        "regulatory_change_id": assessment["regulatory_change_id"],
        "business_owner_id": assessment["business_owner_id"],
        "due_date": _dt(assessment["due_date"]),
        "likelihood_score": assessment["likelihood_score"],
        "severity_score": assessment["severity_score"],
        "affected_business_lines": assessment["affected_business_lines"],
        "findings_summary": assessment["findings_summary"],
        "impact_rating_raw": _num(assessment["impact_rating_raw"])
        if assessment["impact_rating_raw"] is not None else None,
        "impact_tier": assessment["impact_tier"],
        "sla_breached": assessment["sla_breached"],
        "status": assessment["status"],
        "supersedes_assessment_id": assessment["supersedes_assessment_id"],
        "return_count": assessment["return_count"],
        "submitted_at": _dt(assessment["submitted_at"]),
    })
    return out


def gap_to_api(gap):
    out = _common(gap)
    out.update({
        "impact_assessment_id": gap["impact_assessment_id"],
        "obligation_id": gap["obligation_id"],
        "requirement_points": gap["requirement_points"],
        "covered_points": _num(gap["covered_points"]),
        "residual_gap_points": _num(gap["residual_gap_points"]),
        "status": gap["status"],
        "confirmed_by_user_id": gap["confirmed_by_user_id"],
        "confirmed_at": _dt(gap["confirmed_at"]),
    })
    return out


def plan_to_api(plan):
    out = _common(plan)
    out.update({
        "gap_analysis_id": plan["gap_analysis_id"],
        "title": plan["title"],
        "target_completion_date": _dt(plan["target_completion_date"]),
        "obligation_id": plan["obligation_id"],
        "regulatory_change_id": plan["regulatory_change_id"],
        "business_owner_id": plan["business_owner_id"],
        "execution_status": plan["execution_status"],
        "deadline_posture": plan["deadline_posture"],
        "pinned_register_version_number": plan["pinned_register_version_number"],
        "extension_count": plan["extension_count"],
        "submitted_by_user_id": plan["submitted_by_user_id"],
        "approved_by_user_id": plan["approved_by_user_id"],
        "verification_evidence_id": plan["verification_evidence_id"],
    })
    return out


def policy_update_to_api(policy):
    out = _common(policy)
    out.update({
        "control_id": policy["control_id"],
        "implementation_plan_id": policy["implementation_plan_id"],
        "title": policy["title"],
        "change_summary": policy["change_summary"],
        "effective_date": _dt(policy["effective_date"]),
        "new_policy_version": policy["new_policy_version"],
        "status": policy["status"],
        "drafted_by_user_id": policy["drafted_by_user_id"],
        "approved_by_user_id": policy["approved_by_user_id"],
        "published_at": _dt(policy["published_at"]),
    })
    return out


def rollout_to_api(rollout):
    records = rollout["attestation_records"]
    assigned = len(records)
    completed = sum(1 for r in records if r["completed"])
    pct = training_completion_pct(records)
    past_due = rollout["status"] == "IN_PROGRESS" and now_clock() > rollout["window_end"]
    out = _common(rollout)
    out.update({
        "policy_update_id": rollout["policy_update_id"],
        "control_id": rollout["control_id"],
        "window_start": _dt(rollout["window_start"]),
        "window_end": _dt(rollout["window_end"]),
        "attestation_records": [
            {
                "person_ref": r["person_ref"],
                "department": r["department"],
                "completed": r["completed"],
                "updated_at": _dt(r["updated_at"]),
            }
            for r in records
        ],
        "assigned_count": assigned,
        "completed_count": completed,
        "completion_pct": _num(pct),
        "past_due": past_due,
        "status": rollout["status"],
    })
    return out


def package_to_api(package):
    out = _common(package)
    out.update({
        "implementation_plan_id": package["implementation_plan_id"],
        "artifacts": [
            {
                "artifact_id": a["artifact_id"],
                "artifact_type": a["artifact_type"],
                "uri": a["uri"],
                "attached_at": _dt(a["attached_at"]),
            }
            for a in package["artifacts"]
        ],
        "artifact_count": len(package["artifacts"]),
        "status": package["status"],
        "sealed_at": _dt(package["sealed_at"]),
        "examiner_reference": package["examiner_reference"],
    })
    return out


def escalation_to_api(escalation):
    out = _common(escalation)
    out.update({
        "target_type": escalation["target_type"],
        "target_id": escalation["target_id"],
        "trigger_rule": escalation["trigger_rule"],
        "business_owner_id": escalation["business_owner_id"],
        "level": escalation["level"],
        "status": escalation["status"],
        "resolution_code": escalation["resolution_code"],
        "opened_at": _dt(escalation["opened_at"]),
        "resolved_at": _dt(escalation["resolved_at"]),
    })
    return out


def report_to_api(report):
    out = _common(report)
    metrics = report["metrics"]
    out.update({
        "committee_name": report["committee_name"],
        "period_start": _dt(report["period_start"]),
        "period_end": _dt(report["period_end"]),
        "status": report["status"],
        "metrics": metrics,  # already JSON-ready once frozen
        "finalized_at": _dt(report["finalized_at"]),
    })
    return out


def audit_event_to_api(event):
    # Append-only: only id + created_at (no updated_at / version).
    return {
        "id": event["id"],
        "created_at": _dt(event["created_at"]),
        "sequence_number": event["sequence_number"],
        "actor_user_id": event["actor_user_id"],
        "actor_role": event["actor_role"],
        "action": event["action"],
        "entity_type": event["entity_type"],
        "entity_id": event["entity_id"],
        "occurred_at": event["occurred_at"],
        "prev_event_hash": event["prev_event_hash"],
        "event_hash": event["event_hash"],
    }


def created_sorted(collection_values):
    """Sort entities by created_at ASC; stable for equal timestamps (insertion)."""
    return sorted(collection_values, key=lambda e: e["created_at"])
