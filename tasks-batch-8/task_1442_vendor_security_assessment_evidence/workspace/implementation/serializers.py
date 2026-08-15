"""Entity serializers: exactly the scaffold fields plus the common system
fields. Internal bookkeeping fields (prefixed "_") are never emitted.
ReassessmentSchedule and VendorContact carry only id + created_at (PRD §2.4).
"""

COMMON = ("id", "created_at", "updated_at", "version")
APPEND_ONLY_COMMON = ("id", "created_at")

FIELDS = {
    "vendor": ["legal_name", "data_sensitivity", "access_level", "criticality",
               "current_tier", "posture", "active_cycle_id", "risk_score",
               "next_reassessment_due", "offboarding_deadline"],
    "policy": ["name", "active", "tier_matrix", "tier1_reassessment_months",
               "tier2_reassessment_months", "tier3_reassessment_months",
               "tier4_reassessment_months"],
    "template": ["title", "applies_to_tiers", "items", "status", "published_version"],
    "cycle": ["vendor_id", "template_id", "template_version", "tier_at_issue",
              "status", "issued_at", "response_due_at", "questionnaire_score",
              "evidence_score", "composite_score", "open_exception_count",
              "acceptance_required"],
    "response": ["cycle_id", "submitted_by", "answers", "status", "submitted_at",
                 "raw_score", "revision_count"],
    "artifact": ["cycle_id", "kind", "period_start", "period_end", "issued_by",
                 "status", "coverage_gap_days"],
    "exception": ["cycle_id", "source", "evidence_artifact_id", "severity",
                  "description", "status", "closure_reason"],
    "plan": ["cycle_id", "exception_ids", "tasks", "status", "approved_by",
             "completed_task_keys", "verified_at"],
    "acceptance": ["cycle_id", "exception_ids", "justification",
                   "compensating_controls", "expires_at", "status", "decided_by"],
    "addendum": ["vendor_id", "cycle_id", "clause_set", "status", "signed_at",
                 "waived_reason"],
    "alert": ["vendor_id", "signal", "severity", "detected_at", "status",
              "disposition"],
    "subprocessor": ["vendor_id", "subprocessor_name", "data_categories",
                     "region", "status", "decided_by"],
    "attestation": ["vendor_id", "data_returned", "data_destroyed",
                    "destruction_method", "attested_by", "status", "submitted_at"],
    "schedule": ["vendor_id", "kind", "previous_due", "new_due", "reason_ref"],
    "contact": ["vendor_id", "email", "full_name", "is_primary"],
}

APPEND_ONLY = ("schedule", "contact")


def serialize(kind, record):
    out = {}
    commons = APPEND_ONLY_COMMON if kind in APPEND_ONLY else COMMON
    for f in commons:
        out[f] = record.get(f)
    for f in FIELDS[kind]:
        out[f] = record.get(f)
    return out


def serialize_list(kind, records):
    return [serialize(kind, r) for r in records]
