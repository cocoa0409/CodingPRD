"""Per-entity output shaping."""

from decimal import Decimal

from db import db


def num(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _common(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def client_out(row):
    out = _common(row)
    out.update(
        {
            "name": row["name"],
            "client_code": row["client_code"],
            "industry_code": row["industry_code"],
            "decision_process": row["decision_process"],
            "adverse_party_codes": list(row["adverse_party_codes"]),
            "stated_budget_authority_cents": row["stated_budget_authority_cents"],
            "status": row["status"],
            "completed_engagement_count": row["completed_engagement_count"],
            "at_risk_engagement_count": row["at_risk_engagement_count"],
        }
    )
    return out


def active_lead_deliverable_count(consultant_id):
    return sum(
        1
        for d in db.deliverables.values()
        if d.get("lead_consultant_id") == consultant_id and d["status"] != "ACCEPTED"
    )


def consultant_out(row):
    out = _common(row)
    out.update(
        {
            "name": row["name"],
            "grade": row["grade"],
            "practice_code": row["practice_code"],
            "cost_rate_cents_per_hour": row["cost_rate_cents_per_hour"],
            "quality_reviewer_certified": row["quality_reviewer_certified"],
            "active_lead_deliverable_count": active_lead_deliverable_count(row["id"]),
        }
    )
    return out


def opportunity_out(row):
    out = _common(row)
    out.update(
        {
            "client_id": row["client_id"],
            "owner_partner_consultant_id": row["owner_partner_consultant_id"],
            "scoping_manager_consultant_id": row["scoping_manager_consultant_id"],
            "origin_engagement_id": row["origin_engagement_id"],
            "requested_practice_code": row["requested_practice_code"],
            "estimated_value_cents": row["estimated_value_cents"],
            "stated_budget_cents": row["stated_budget_cents"],
            "verified_budget_cents": row["verified_budget_cents"],
            "decision_maker_identified": row["decision_maker_identified"],
            "target_start_date": row["target_start_date"],
            "target_end_date": row["target_end_date"],
            "objective_summary": row["objective_summary"],
            "assumptions": list(row["assumptions"]),
            "exclusions": list(row["exclusions"]),
            "client_responsibilities": list(row["client_responsibilities"]),
            "status": row["status"],
            "conflict_status": row["conflict_status"],
            "screened_adverse_party_codes": list(row["screened_adverse_party_codes"]),
            "qualification_score_intake": num(row["qualification_score_intake"]),
            "qualification_score_verified": num(row["qualification_score_verified"]),
            "total_estimated_hours": num(row["total_estimated_hours"]),
            "scope_discount_pct": num(row["scope_discount_pct"]),
            "baseline_effort_cost_cents": row["baseline_effort_cost_cents"],
            "longest_dependency_chain": row["longest_dependency_chain"],
            "baselined_at": row["baselined_at"],
        }
    )
    return out


def deliverable_out(row):
    out = _common(row)
    out.update(
        {
            "opportunity_id": row["opportunity_id"],
            "lead_consultant_id": row["lead_consultant_id"],
            "depends_on_deliverable_id": row["depends_on_deliverable_id"],
            "name": row["name"],
            "primary_grade": row["primary_grade"],
            "effort_hours_estimate": num(row["effort_hours_estimate"]),
            "completion_weight_pct": num(row["completion_weight_pct"]),
            "acceptance_criteria": row["acceptance_criteria"],
            "planned_start_date": row["planned_start_date"],
            "planned_end_date": row["planned_end_date"],
            "status": row["status"],
            "prior_status": row["prior_status"],
            "line_cost_cents": row["line_cost_cents"],
            "hours_consumed": num(row["hours_consumed"]),
        }
    )
    return out


def sow_out(row):
    out = _common(row)
    out.update(
        {
            "opportunity_id": row["opportunity_id"],
            "supersedes_sow_id": row["supersedes_sow_id"],
            "pricing_model": row["pricing_model"],
            "target_bonus_cents": row["target_bonus_cents"],
            "acceptance_summary": row["acceptance_summary"],
            "status": row["status"],
            "revision_round": row["revision_round"],
            "risk_score": row["risk_score"],
            "risk_premium_pct": num(row["risk_premium_pct"]),
            "pinned_scope_discount_pct": num(row["pinned_scope_discount_pct"]),
            "baseline_effort_cost_cents": row["baseline_effort_cost_cents"],
            "quoted_fee_cents": row["quoted_fee_cents"],
            "fixed_component_cents": row["fixed_component_cents"],
            "at_risk_component_cents": row["at_risk_component_cents"],
            "not_to_exceed_cents": row["not_to_exceed_cents"],
            "signature_name": row["signature_name"],
            "signed_at": row["signed_at"],
        }
    )
    return out


def engagement_out(row):
    out = _common(row)
    out.update(
        {
            "sow_id": row["sow_id"],
            "opportunity_id": row["opportunity_id"],
            "client_id": row["client_id"],
            "lead_partner_consultant_id": row["lead_partner_consultant_id"],
            "engagement_manager_consultant_id": row["engagement_manager_consultant_id"],
            "delivery_state": row["delivery_state"],
            "economics_state": row["economics_state"],
            "pricing_model": row["pricing_model"],
            "original_fee_cents": row["original_fee_cents"],
            "contracted_fee_cents": row["contracted_fee_cents"],
            "contracted_hours": num(row["contracted_hours"]),
            "not_to_exceed_cents": row["not_to_exceed_cents"],
            "pinned_scope_discount_pct": num(row["pinned_scope_discount_pct"]),
            "pinned_risk_premium_pct": num(row["pinned_risk_premium_pct"]),
            "approved_hours_burned": num(row["approved_hours_burned"]),
            "burned_cost_cents": row["burned_cost_cents"],
            "cumulative_change_pct": num(row["cumulative_change_pct"]),
            "suspended_deliverable_count": row["suspended_deliverable_count"],
            "schedule_relief_days": row["schedule_relief_days"],
            "planned_start_date": row["planned_start_date"],
            "planned_end_date": row["planned_end_date"],
            "leadership_review_required": row["leadership_review_required"],
            "closed_at": row["closed_at"],
        }
    )
    return out


def change_request_out(row):
    out = _common(row)
    out.update(
        {
            "engagement_id": row["engagement_id"],
            "requested_by_consultant_id": row["requested_by_consultant_id"],
            "leadership_approver_consultant_id": row["leadership_approver_consultant_id"],
            "supersedes_change_request_id": row["supersedes_change_request_id"],
            "origin": row["origin"],
            "summary": row["summary"],
            "added_hours": num(row["added_hours"]),
            "added_grade": row["added_grade"],
            "requested_schedule_days": row["requested_schedule_days"],
            "status": row["status"],
            "routing": row["routing"],
            "gross_delta_cents": row["gross_delta_cents"],
            "fee_delta_cents": row["fee_delta_cents"],
            "cumulative_change_pct_at_assessment": num(
                row["cumulative_change_pct_at_assessment"]
            ),
            "approved_at": row["approved_at"],
            "rescinded_at": row["rescinded_at"],
            "note": row.get("note"),
        }
    )
    return out


def time_entry_out(row):
    out = _common(row)
    out.update(
        {
            "engagement_id": row["engagement_id"],
            "deliverable_id": row["deliverable_id"],
            "consultant_id": row["consultant_id"],
            "week_ending_date": row["week_ending_date"],
            "hours": num(row["hours"]),
            "billable": row["billable"],
            "status": row["status"],
            "cost_cents": row["cost_cents"],
            "billed_value_cents": row["billed_value_cents"],
            "reversal_reason": row["reversal_reason"],
        }
    )
    return out


def quality_review_out(row):
    out = _common(row)
    out.update(
        {
            "engagement_id": row["engagement_id"],
            "reviewer_consultant_id": row["reviewer_consultant_id"],
            "checkpoint_type": row["checkpoint_type"],
            "window_start_date": row["window_start_date"],
            "window_end_date": row["window_end_date"],
            "status": row["status"],
            "findings_severity": row["findings_severity"],
            "note": row["note"],
        }
    )
    return out


def risk_escalation_out(row):
    out = _common(row)
    out.update(
        {
            "engagement_id": row["engagement_id"],
            "source_quality_review_id": row["source_quality_review_id"],
            "source": row["source"],
            "severity": row["severity"],
            "opened_reason": row["opened_reason"],
            "status": row["status"],
            "leadership_response": row["leadership_response"],
            "resolved_at": row["resolved_at"],
        }
    )
    return out


def satisfaction_out(row):
    # PRD 2.4: this family carries only id and created_at.
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "engagement_id": row["engagement_id"],
        "delivery_score": row["delivery_score"],
        "value_score": row["value_score"],
        "communication_score": row["communication_score"],
        "would_refer": row["would_refer"],
        "comments": row["comments"],
        "csat_score": num(row["csat_score"]),
    }
