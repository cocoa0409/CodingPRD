"""Per-entity response serialisation.

Each spec is an ordered list of (field_name, kind) pairs where kind is:
    s  string / passthrough scalar
    i  integer
    n  2dp number (stored as Decimal, emitted as a JSON number)
    d  datetime -> ISO 8601 UTC with three fractional digits
    b  boolean
    o  object / array passthrough
"""

from util import iso, num

_SPECS = {
    "Domain": [
        ("code", "s"),
        ("name", "s"),
        ("status", "s"),
        ("governance_posture", "s"),
        ("classification_level", "s"),
        ("sensitive_handling_required", "b"),
        ("authoritative_source_code", "s"),
        ("notification_lead_days_floor", "i"),
        ("expected_attribute_count", "i"),
        ("open_finding_weight", "n"),
        ("quality_score_provisional", "n"),
        ("quality_score_certified", "n"),
        ("scorecard_run_seq", "i"),
        ("reference_data_revision", "i"),
        ("published_master_record_count", "i"),
        ("scheduled_change_count", "i"),
        ("activated_at", "d"),
    ],
    "SourceSystem": [
        ("code", "s"),
        ("name", "s"),
        ("trust_tier", "i"),
        ("status", "s"),
        ("certified_at", "d"),
        ("decertified_at", "d"),
        ("decertification_reason", "s"),
    ],
    "Steward": [
        ("full_name", "s"),
        ("email", "s"),
        ("certification_level", "s"),
        ("open_finding_load", "i"),
    ],
    "SourceRegistration": [
        ("domain_id", "s"),
        ("source_system_id", "s"),
        ("role", "s"),
        ("trust_rank", "i"),
        ("effective_from", "d"),
        ("effective_to", "d"),
        ("status", "s"),
        ("superseded_at", "d"),
        ("revoked_reason", "s"),
    ],
    "StewardAssignment": [
        ("domain_id", "s"),
        ("steward_id", "s"),
        ("steward_role", "s"),
        ("effective_from", "d"),
        ("effective_to", "d"),
        ("status", "s"),
        ("superseded_at", "d"),
    ],
    "QualityRule": [
        ("domain_id", "s"),
        ("owner_steward_id", "s"),
        ("rule_code", "s"),
        ("dimension", "s"),
        ("weight_points", "i"),
        ("threshold_pct", "n"),
        ("severity", "s"),
        ("status", "s"),
    ],
    "ScorecardRun": [
        ("domain_id", "s"),
        ("run_seq", "i"),
        ("basis", "s"),
        ("measured_at", "d"),
        ("weighted_score", "n"),
        ("rules_evaluated_count", "i"),
        ("rules_failed_count", "i"),
        ("findings_created_count", "i"),
        ("posture_before", "s"),
        ("posture_after", "s"),
        ("posture_multiplier_applied", "n"),
    ],
    "QualityFinding": [
        ("scorecard_run_id", "s"),
        ("quality_rule_id", "s"),
        ("status", "s"),
        ("severity_weight", "n"),
        ("measured_pct", "n"),
        ("gap_pct", "n"),
        ("assigned_steward_id", "s"),
        ("planned_by_steward_id", "s"),
        ("waived_by_steward_id", "s"),
        ("due_at", "d"),
        ("plan_note", "s"),
        ("resolution_note", "s"),
        ("waiver_justification", "s"),
        ("opened_at", "d"),
        ("resolved_at", "d"),
    ],
    "MasterRecord": [
        ("domain_id", "s"),
        ("source_system_id", "s"),
        ("natural_key", "s"),
        ("attributes", "o"),
        ("completeness_pct", "n"),
        ("last_verified_at", "d"),
        ("curation_status", "s"),
        ("publication_status", "s"),
        ("superseded_by_master_record_id", "s"),
        ("survivorship_score", "n"),
        ("published_at", "d"),
        ("quarantine_reason", "s"),
    ],
    "MergeProposal": [
        ("domain_id", "s"),
        ("survivor_master_record_id", "s"),
        ("duplicate_master_record_id", "s"),
        ("proposer_steward_id", "s"),
        ("reviewer_steward_id", "s"),
        ("name_similarity_pct", "n"),
        ("key_overlap_pct", "n"),
        ("match_score", "n"),
        ("match_confidence", "s"),
        ("status", "s"),
        ("effective_survivor_master_record_id", "s"),
        ("survivor_swapped", "b"),
        ("survivorship_variant", "s"),
        ("survivorship_field_map", "o"),
        ("rework_count", "i"),
        ("override_justification", "s"),
        ("decided_at", "d"),
    ],
    "ChangeRequest": [
        ("domain_id", "s"),
        ("requester_steward_id", "s"),
        ("reviewer_steward_id", "s"),
        ("change_type", "s"),
        ("structural", "b"),
        ("title", "s"),
        ("proposed_values", "o"),
        ("status", "s"),
        ("impact_consumer_count", "i"),
        ("required_lead_days", "i"),
        ("submitted_at", "d"),
        ("earliest_apply_at", "d"),
        ("scheduled_apply_at", "d"),
        ("freeze_window_start", "d"),
        ("freeze_window_end", "d"),
        ("revision_cycle_count", "i"),
        ("applied_at", "d"),
        ("review_note", "s"),
        ("withdraw_reason", "s"),
    ],
    "ConsumerSubscription": [
        ("domain_id", "s"),
        ("consumer_code", "s"),
        ("reporting_asset_key", "s"),
        ("clearance_level", "s"),
        ("criticality", "s"),
        ("required_lead_days", "i"),
        ("status", "s"),
        ("lineage_path", "o"),
        ("lineage_status", "s"),
        ("lineage_revision", "i"),
        ("lineage_documented_at", "d"),
        ("pending_change_request_id", "s"),
        ("notified_at", "d"),
        ("acknowledged_at", "d"),
        ("acknowledged_revision", "i"),
        ("suspended_reason", "s"),
    ],
}

# ScorecardRun is an immutable audit artefact: id + created_at only, no
# updated_at and no version (PRD 2.4).
_NO_COMMON = ("ScorecardRun",)


def one(entity):
    kind = entity["_kind"]
    out = {"id": entity["id"]}
    for field, kindcode in _SPECS[kind]:
        value = entity.get(field)
        if value is None:
            out[field] = None
        elif kindcode == "n":
            out[field] = num(value)
        elif kindcode == "d":
            out[field] = iso(value)
        elif kindcode == "i":
            out[field] = int(value)
        elif kindcode == "b":
            out[field] = bool(value)
        else:
            out[field] = value
    out["created_at"] = iso(entity["created_at"])
    if kind not in _NO_COMMON:
        out["updated_at"] = iso(entity["updated_at"])
        out["version"] = entity["version"]
    return out


def many(entities):
    return [one(e) for e in entities]
