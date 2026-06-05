"""Resource serializers (PRD §2.4 common fields + per-entity fields).

Each entity is stored as a plain dict whose keys are already the wire field
names, plus internal bookkeeping keys prefixed with '_' (e.g. '_seq',
'_created_dt', '_updated_dt'). Serialization formats datetimes to ISO 8601 and
strips internal keys.

Common fields on every entity: id, created_at, updated_at, version (PRD §2.4).
"""
from util import iso

# Per-entity public field order (common fields first, then entity-specific).
_COMMON = ["id", "created_at", "updated_at", "version"]

_FIELDS = {
    "Trial": [
        "title", "sponsor_user_id", "target_enrollment", "randomization_method",
        "block_size", "irb_status", "posture", "enrolled_count", "active_safety_holds",
    ],
    "EligibilityCriterion": ["trial_id", "kind", "attribute", "comparator", "threshold"],
    "RandomizationArm": ["trial_id", "name", "allocation_weight", "assigned_count"],
    "ConsentDocument": ["trial_id", "version_number", "body_hash", "status", "irb_review_id"],
    "IRBReview": [
        "trial_id", "scope", "consent_document_id", "reviewer_user_id",
        "decision", "decided_at",
    ],
    "Participant": [
        "full_name", "age_years", "weight_kg", "hba1c",
        "prior_trials_count", "biomarker_positive",
    ],
    "Screening": [
        "trial_id", "participant_id", "match_result", "failed_criteria_count", "match_score",
    ],
    "Enrollment": [
        "trial_id", "participant_id", "screening_id", "enrollment_status",
        "safety_status", "arm_id", "signed_consent_document_id",
        "signed_consent_version", "completed_visits_count",
    ],
    "Visit": [
        "enrollment_id", "sequence_index", "scheduled_at", "draw_window_minutes",
        "drawn_at", "draw_in_window", "draw_deviation_minutes", "status",
        "payable_amount_cents",
    ],
    "AdverseEvent": [
        "enrollment_id", "reporter_user_id", "severity", "is_serious",
        "occurred_at", "report_status", "adjudicator_user_id",
    ],
    "CompensationPayment": [
        "enrollment_id", "amount_cents", "gross_cents", "visit_ids", "status",
    ],
}

# Fields that hold datetime objects and must be ISO-formatted on output.
_DT_FIELDS = {"created_at", "updated_at", "decided_at", "scheduled_at", "drawn_at", "occurred_at"}


def serialize(kind, rec):
    out = {}
    for f in _COMMON + _FIELDS[kind]:
        val = rec.get(f)
        if f in _DT_FIELDS and val is not None and not isinstance(val, str):
            val = iso(val)
        out[f] = val
    return out
