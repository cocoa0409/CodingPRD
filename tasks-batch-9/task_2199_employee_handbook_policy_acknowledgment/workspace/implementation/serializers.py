"""Entity -> JSON projections."""
from datetime import datetime
from decimal import Decimal

import calc
import clock

COMMON = ["id", "created_at", "updated_at", "version"]
EVIDENCE = ["id", "created_at"]

FIELDS = {
    "jurisdictions": COMMON + [
        "state_code", "display_name", "min_legal_review_days", "ack_deadline_days",
        "esign_permitted", "proxy_ack_permitted", "retention_years",
        "required_language_codes", "ack_window_buffer_days",
    ],
    "legal_reviewers": COMMON + [
        "jurisdiction_id", "full_name", "bar_number", "concurrent_review_limit",
        "open_review_count", "is_active",
    ],
    "employees": COMMON + [
        "jurisdiction_id", "manager_id", "work_email", "full_name",
        "preferred_language_code", "needs_accessible_format", "employment_status",
        "open_ack_count", "open_escalation_count",
    ],
    "policy_documents": COMMON + [
        "title", "category", "owner_user_id", "current_published_version_id",
        "latest_version_no", "max_ack_deadline_days",
    ],
    "policy_versions": COMMON + [
        "policy_document_id", "version_no", "body_text", "section_count", "status",
        "required_jurisdiction_ids", "effective_date", "window_end_date",
        "revision_round", "approved_at", "pinned_addendum_ids",
    ],
    "addenda": COMMON + [
        "policy_version_id", "jurisdiction_id", "body_text", "status",
        "approved_by_reviewer_id",
    ],
    "legal_reviews": COMMON + [
        "policy_version_id", "jurisdiction_id", "reviewer_id", "assigned_at",
        "due_at", "status", "decided_at", "round_no", "comment",
    ],
    "translations": COMMON + [
        "policy_version_id", "language_code", "status", "section_scores",
        "a11y_index", "a11y_round_no", "conformance_level",
    ],
    "release_packages": COMMON + [
        "name", "effective_date", "scope_jurisdiction_ids", "status", "scheduled_at",
        "released_at", "legal_review_deadline", "roster_snapshot_size",
        "coverage_snapshot_pct", "coverage_live_pct",
    ],
    "release_items": EVIDENCE + [
        "release_package_id", "policy_version_id", "supersedes_version_id",
    ],
    "assignments": COMMON + [
        "release_package_id", "policy_version_id", "employee_id", "jurisdiction_id",
        "ack_state", "escalation_state", "window_start_date", "due_date",
        "delivered_at", "acknowledged_at", "days_overdue", "policy_category",
    ],
    "acknowledgments": EVIDENCE + [
        "assignment_id", "employee_id", "method", "language_code", "signature_text",
        "captured_at", "status", "revoked_at",
    ],
    "escalations": COMMON + [
        "assignment_id", "employee_id", "notified_manager_id", "tier", "status",
        "opened_at", "closed_at", "notice_count",
    ],
    "policy_exceptions": COMMON + [
        "employee_id", "policy_version_id", "assignment_id", "approving_manager_id",
        "deciding_reviewer_id", "reason_code", "justification", "requested_days",
        "prior_exception_count", "status", "risk_score_conservative",
        "risk_score_aggregate", "expires_at",
    ],
    "retention_records": EVIDENCE + [
        "acknowledgment_id", "employee_id", "jurisdiction_id", "record_kind",
        "signed_delta", "retained_from", "retention_until", "legal_hold",
        "hold_reason",
    ],
}


def _scalar(value):
    if isinstance(value, datetime):
        return clock.fmt(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [_scalar(v) for v in value]
    return value


def dump(table, row):
    out = {}
    for key in FIELDS[table]:
        out[key] = _scalar(row.get(key))
    if table == "assignments":
        out["days_overdue"] = calc.days_overdue(row["due_date"], clock.now())
    return out


def dump_list(table, rows):
    return [dump(table, r) for r in rows]
