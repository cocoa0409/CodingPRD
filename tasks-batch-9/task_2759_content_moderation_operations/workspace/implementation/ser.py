"""Resource serializers.  Field sets follow SCAFFOLD.yaml entities exactly;
timestamps are ISO 8601 UTC with three fractional digits (PRD §2.5) and every
four-decimal figure is emitted as a JSON number (PRD §2.6)."""

from core import num4

COMMON = ["id", "created_at", "updated_at", "version"]


def _pick(record, names):
    return {name: record.get(name) for name in names}


def account(record):
    out = _pick(record, [
        "id", "external_handle", "region_code", "tier", "appeal_credits_remaining",
        "strike_points", "lifetime_removed_count", "standing",
        "created_at", "updated_at", "version",
    ])
    return out


def content_item(record):
    return _pick(record, [
        "id", "account_id", "language", "media_kind", "graphic_weight", "posted_at",
        "visibility_status", "review_status", "open_case_count", "reinstated_at",
        "created_at", "updated_at", "version",
    ])


def policy_category(record):
    return _pick(record, [
        "id", "code", "name", "parent_category_id", "severity_tier", "specialty",
        "status", "active_version_id", "created_at", "updated_at", "version",
    ])


def policy_version(record):
    out = _pick(record, [
        "id", "policy_category_id", "supersedes_version_id", "version_label",
        "auto_action_threshold", "review_floor", "enforcement_action",
        "appeal_window_hours", "review_sla_minutes", "requires_recertification",
        "backtest_sample_size", "backtest_divergence_rate", "backtest_completed_at",
        "authored_by_user_id", "activated_by_user_id", "activated_at", "status",
        "created_at", "updated_at", "version",
    ])
    out["auto_action_threshold"] = num4(record.get("auto_action_threshold"))
    out["review_floor"] = num4(record.get("review_floor"))
    out["backtest_divergence_rate"] = num4(record.get("backtest_divergence_rate"))
    return out


def reviewer(record):
    out = _pick(record, [
        "id", "display_name", "languages", "specialties", "utc_offset_minutes",
        "shift_start_local_hour", "shift_end_local_hour", "role_class",
        "max_concurrent_cases", "daily_exposure_cap_points",
        "certified_policy_version_ids", "pending_retraining_version_ids",
        "open_case_count", "exposure_points_today", "audited_count", "agree_count",
        "appealed_count", "upheld_appeal_count", "accuracy_score_audit_only",
        "accuracy_score_blended", "wellness_break_start", "wellness_break_end",
        "wellness_breaks_taken", "status", "created_at", "updated_at", "version",
    ])
    out["languages"] = list(record.get("languages") or [])
    out["specialties"] = list(record.get("specialties") or [])
    out["certified_policy_version_ids"] = list(record.get("certified_policy_version_ids") or [])
    out["pending_retraining_version_ids"] = list(record.get("pending_retraining_version_ids") or [])
    out["accuracy_score_audit_only"] = num4(record.get("accuracy_score_audit_only"))
    out["accuracy_score_blended"] = num4(record.get("accuracy_score_blended"))
    return out


def review_queue(record):
    return _pick(record, [
        "id", "name", "policy_category_id", "language", "specialty",
        "open_case_count", "unassigned_case_count",
        "created_at", "updated_at", "version",
    ])


def detection_signal(record):
    """A signal is immutable: it carries id and created_at only -- no
    updated_at and no version (PRD §2.5)."""
    out = _pick(record, [
        "id", "content_item_id", "policy_category_code", "classifier_id",
        "classifier_confidence", "effective_confidence", "disposition",
        "resulting_case_id", "pinned_policy_version_label", "created_at",
    ])
    out["classifier_confidence"] = num4(record.get("classifier_confidence"))
    out["effective_confidence"] = num4(record.get("effective_confidence"))
    return out


def moderation_case(record):
    return _pick(record, [
        "id", "content_item_id", "detection_signal_id", "policy_version_id",
        "queue_id", "assigned_reviewer_id", "decided_by_reviewer_id", "origin",
        "escalation_reason", "escalation_tier", "legal_jurisdiction",
        "legal_reference", "sla_due_at", "sla_breached", "decision_outcome",
        "decision_source", "decided_at", "strike_points_applied", "is_overturned",
        "appeal_deadline_at", "exposure_points_charged",
        "requires_recertified_review", "reassignment_count", "status",
        "created_at", "updated_at", "version",
    ])


def appeal(record):
    return _pick(record, [
        "id", "case_id", "account_id", "independent_reviewer_id", "grounds_text",
        "filed_at", "resolved_at", "resolution_note", "reinstated_content",
        "status", "created_at", "updated_at", "version",
    ])


def audit_sample(record):
    return _pick(record, [
        "id", "case_id", "auditor_reviewer_id", "sampling_reason", "verdict",
        "correct_outcome", "audited_at", "dispute_note", "disputed_at",
        "counts_toward_accuracy", "status", "created_at", "updated_at", "version",
    ])


def transparency_report(record):
    out = _pick(record, [
        "id", "period_start", "period_end", "variant", "enforcement_volume",
        "removal_volume", "age_gate_volume", "warn_volume",
        "overturn_adjusted_volume", "appeal_count", "appeal_overturn_rate",
        "category_rate_breakdown", "legal_request_count", "legal_grant_rate",
        "computed_at", "published_at", "status",
        "created_at", "updated_at", "version",
    ])
    out["appeal_overturn_rate"] = num4(record.get("appeal_overturn_rate"))
    out["legal_grant_rate"] = num4(record.get("legal_grant_rate"))
    out["category_rate_breakdown"] = [
        {
            "category_code": row["category_code"],
            "appealed": row["appealed"],
            "overturned": row["overturned"],
            "rate": num4(row["rate"]),
        }
        for row in (record.get("category_rate_breakdown") or [])
    ]
    return out
