"""Entity -> JSON projections. Field sets come from SCAFFOLD.yaml `entities`."""
from datetime import datetime
from decimal import Decimal

from clock import iso
from store import db

COMMON = ("created_at", "updated_at", "version")


def _value(raw):
    if isinstance(raw, datetime):
        return iso(raw)
    if isinstance(raw, Decimal):
        return float(raw)
    if isinstance(raw, list):
        return [_value(x) for x in raw]
    if isinstance(raw, dict):
        return {k: _value(v) for k, v in raw.items()}
    return raw


def _dump(entity, fields):
    # Section 2.4: the representation a mutating request returns must already
    # carry the incremented version and the new updated_at, so pending bumps are
    # flushed before the projection is built. commit() is idempotent.
    db.commit()
    out = {"id": entity["id"]}
    for name in fields:
        out[name] = _value(entity.get(name))
    for name in COMMON:
        out[name] = _value(entity.get(name))
    return out


DECISION_FIELDS = (
    "title", "decision_deadline", "reversibility", "impacted_user_count",
    "status", "evidence_confidence", "locked_at",
)
REQUEST_FIELDS = (
    "roadmap_decision_id", "requester_user_id", "question", "question_type",
    "evidence_gap", "status", "priority_score", "recommended_method",
    "approved_method", "revision_round", "triage_reason", "triaged_at",
)
POOL_FIELDS = (
    "name", "pool_type", "contact_cap_per_window", "contact_window_days",
    "incentive_budget_cents", "incentive_reserved_cents", "incentive_paid_cents",
    "incentive_available_cents", "last_estimate_cents", "settled_study_ids",
    "status", "participant_count", "suppressed_participant_count",
)
PARTICIPANT_FIELDS = (
    "pool_id", "external_ref", "segment", "locale", "pii_on_file",
    "last_contacted_at", "contacts_in_window", "no_show_strikes", "status",
)
STUDY_FIELDS = (
    "research_request_id", "participant_pool_id", "lead_user_id", "method",
    "target_participant_count", "screening_criteria", "incentive_amount_cents",
    "fielding_start", "fielding_end", "guide_version_label",
    "guide_question_count", "guide_status", "guide_version_pinned",
    "execution_status", "recruitment_status", "invited_count",
    "screened_in_count", "completed_count", "fielded_at", "fielding_closed_at",
)
RECRUITMENT_FIELDS = (
    "study_id", "participant_id", "screening_answers", "screen_score", "status",
    "incentive_state", "reserved_cents", "paid_cents", "scheduled_start",
    "scheduled_end", "moderator_user_id", "guide_version_pinned",
    "actual_duration_min", "reschedule_count", "closure_reason",
)
CONSENT_FIELDS = (
    "participant_id", "study_id", "scopes", "retention_days", "granted_at",
    "retention_until", "status", "revoked_at", "revocation_reason",
)
ARTIFACT_FIELDS = (
    "recruitment_id", "artifact_type", "contains_pii", "retention_until",
    "lifecycle_state", "purged_at", "purge_reason",
)
THEME_FIELDS = (
    "label", "parent_theme_id", "depth", "own_evidence_weight",
    "evidence_weight", "reuse_count", "status",
)
FINDING_FIELDS = (
    "study_id", "theme_id", "authored_by_user_id", "statement", "severity",
    "evidence_strength", "strength_variant", "admissible_link_count",
    "distinct_participant_count", "status", "retraction_reason", "published_at",
)
LINK_FIELDS = (
    "finding_id", "artifact_id", "excerpt_ref", "weight_class", "contribution",
    "is_admissible", "inadmissible_reason",
)
READOUT_FIELDS = (
    "study_id", "roadmap_decision_id", "recommendation", "recommended_action",
    "cited_finding_ids", "status", "delivered_at", "responded_at",
    "response_note", "decision_confidence_before", "decision_confidence_after",
)
FOLLOWUP_FIELDS = (
    "readout_id", "owner_user_id", "description", "due_date", "status",
    "completed_at",
)


def decision(e):
    return _dump(e, DECISION_FIELDS)


def research_request(e):
    return _dump(e, REQUEST_FIELDS)


def pool(e):
    return _dump(e, POOL_FIELDS)


def participant(e):
    return _dump(e, PARTICIPANT_FIELDS)


def study(e):
    return _dump(e, STUDY_FIELDS)


def recruitment(e):
    return _dump(e, RECRUITMENT_FIELDS)


def consent(e):
    return _dump(e, CONSENT_FIELDS)


def artifact(e):
    return _dump(e, ARTIFACT_FIELDS)


def theme(e):
    return _dump(e, THEME_FIELDS)


def finding(e):
    return _dump(e, FINDING_FIELDS)


def link(e):
    return _dump(e, LINK_FIELDS)


def readout(e):
    return _dump(e, READOUT_FIELDS)


def followup(e):
    return _dump(e, FOLLOWUP_FIELDS)
