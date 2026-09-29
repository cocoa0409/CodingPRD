"""Public representations. Field sets follow SCAFFOLD entities exactly."""
from datetime import datetime

from util import fmt_dt

PROGRAM_FIELDS = [
    "id", "program_code", "title", "total_credits_required", "residency_min_credits",
    "pla_max_credits", "pla_max_pct_bp", "pla_upper_division_max_credits",
    "pla_pass_threshold_bp", "allowed_source_types", "status",
    "effective_pla_cap_credits", "created_at", "updated_at", "version",
]

COURSE_FIELDS = [
    "id", "course_code", "title", "department_code", "credits", "level",
    "pla_eligible", "outcome_count", "created_at", "updated_at", "version",
]

OUTCOME_FIELDS = [
    "id", "course_id", "outcome_code", "description", "weight_bp",
    "mastery_threshold_bp", "created_at",
]

RECOMMENDATION_FIELDS = [
    "id", "source_type", "credential_code", "title", "issuing_body",
    "recommended_credits", "recommended_level", "effective_from", "effective_to",
    "status", "approved_rule_count", "terms_version", "retire_reason",
    "created_at", "updated_at", "version",
]

RULE_FIELDS = [
    "id", "recommendation_id", "course_id", "awarded_credits", "effective_from",
    "effective_to", "status", "pinned_recommendation_version", "reviewed_by_user_id",
    "approved_by_user_id", "suspend_reason", "created_at", "updated_at", "version",
]

STUDENT_FIELDS = [
    "id", "student_number", "full_name", "program_id", "enrollment_status",
    "transfer_credits_accepted", "institutional_credits_earned",
    "pla_credits_reserved", "pla_credits_awarded", "pla_credits_posted",
    "pla_upper_division_committed", "fee_paid_net_cents",
    "created_at", "updated_at", "version",
]

ASSESSOR_FIELDS = [
    "id", "employee_number", "full_name", "department_code", "credential_rank",
    "max_concurrent_assignments", "appeal_panel_member", "status",
    "active_assignment_count", "created_at", "updated_at", "version",
]

CLAIM_FIELDS = [
    "id", "claim_number", "student_id", "course_id", "articulation_rule_id",
    "supersedes_claim_id", "source_type", "credits_requested", "credits_awarded",
    "attempt_date", "rush_requested", "priority_tier", "assessment_status",
    "fee_status", "credit_status", "provisional_coverage_bp", "verified_coverage_bp",
    "assessor_recommendation", "revision_round", "sla_breach_count", "appeal_count",
    "hold_reason", "denial_reason", "appeal_deadline_at", "submitted_at",
    "posted_term", "posted_credits", "created_at", "updated_at", "version",
]

PORTFOLIO_FIELDS = [
    "id", "claim_id", "narrative", "status", "artifact_count",
    "provisional_coverage_bp", "verified_coverage_bp", "revision_round",
    "submitted_at", "created_at", "updated_at", "version",
]

ARTIFACT_FIELDS = [
    "id", "portfolio_id", "artifact_type", "title", "description",
    "evidence_uri", "outcome_mappings", "created_at",
]

ASSIGNMENT_FIELDS = [
    "id", "claim_id", "assessor_id", "status", "selection_reason", "assigned_at",
    "accepted_at", "sla_hours", "due_at", "at_risk_at", "elapsed_bp", "sla_state",
    "rubric_submitted_at", "recommendation", "verified_coverage_bp",
    "revoke_reason", "decline_reason", "created_at", "updated_at", "version",
]

RUBRIC_SCORE_FIELDS = [
    "id", "assignment_id", "learning_outcome_id", "points_awarded", "points_possible",
    "score_ratio_bp", "outcome_met", "narrative", "created_at", "updated_at", "version",
]

APPEAL_FIELDS = [
    "id", "claim_id", "grounds", "status", "reviewer_assessor_id", "filed_at",
    "assigned_at", "decided_at", "decision_note", "prior_scorer_assessor_ids",
    "created_at", "updated_at", "version",
]

INVOICE_FIELDS = [
    "id", "claim_id", "student_id", "fee_status", "lines", "subtotal_cents",
    "discount_bp", "discount_cents", "total_cents", "paid_cents", "refunded_cents",
    "waived_cents", "balance_due_cents", "aid_eligible", "recompute_count",
    "created_at", "updated_at", "version",
]


def _value(row, name):
    value = row.get(name)
    if isinstance(value, datetime):
        return fmt_dt(value)
    if isinstance(value, list):
        return list(value)
    return value


def _project(row, fields):
    return dict((name, _value(row, name)) for name in fields)


def program_out(row):
    return _project(row, PROGRAM_FIELDS)


def course_out(row):
    return _project(row, COURSE_FIELDS)


def outcome_out(row):
    return _project(row, OUTCOME_FIELDS)


def recommendation_out(row):
    return _project(row, RECOMMENDATION_FIELDS)


def rule_out(row):
    return _project(row, RULE_FIELDS)


def student_out(row):
    return _project(row, STUDENT_FIELDS)


def assessor_out(row):
    return _project(row, ASSESSOR_FIELDS)


def claim_out(row):
    return _project(row, CLAIM_FIELDS)


def portfolio_out(row):
    return _project(row, PORTFOLIO_FIELDS)


def artifact_out(row):
    out = _project(row, ARTIFACT_FIELDS)
    out["outcome_mappings"] = [dict(m) for m in (row.get("outcome_mappings") or [])]
    return out


def assignment_out(row):
    from services.sla import refresh_posture
    refresh_posture(row)
    return _project(row, ASSIGNMENT_FIELDS)


def rubric_score_out(row):
    return _project(row, RUBRIC_SCORE_FIELDS)


def appeal_out(row):
    out = _project(row, APPEAL_FIELDS)
    out["prior_scorer_assessor_ids"] = list(row.get("prior_scorer_assessor_ids") or [])
    return out


def invoice_out(row):
    from db import db
    out = _project(row, INVOICE_FIELDS)
    out["lines"] = [dict(line) for line in (row.get("lines") or [])]
    claim = db.claims.get(row["claim_id"])
    if claim is not None:
        out["fee_status"] = claim["fee_status"]
    return out
