"""Entity serializers. Computed fields are derived at read time."""

import db
from services import calc, derive


def _common(entity, payload):
    payload["id"] = entity["id"]
    payload["created_at"] = db.iso(entity["created_at"])
    payload["updated_at"] = db.iso(entity["updated_at"])
    payload["version"] = entity["version"]
    return payload


def source_system(entity):
    submitted, valid, rate = derive.source_totals(entity)
    return _common(entity, {
        "code": entity["code"],
        "display_name": entity["display_name"],
        "channel_type": entity["channel_type"],
        "trust_tier": entity["trust_tier"],
        "dq_scoring_mode": entity["dq_scoring_mode"],
        "pii_completeness_floor": entity["pii_completeness_floor"],
        "status": entity["status"],
        "dq_window_start_at": db.iso(entity["dq_window_start_at"]),
        "submitted_record_total": submitted,
        "valid_record_total": valid,
        "dq_pass_rate": float(rate),
        "quarantine_count": entity["quarantine_count"],
        "last_reinstated_at": db.iso(entity["last_reinstated_at"]),
    })


def _record(record):
    payload = {
        "external_id": record["external_id"],
        "email_raw": record["email_raw"],
        "phone_raw": record["phone_raw"],
        "loyalty_number": record["loyalty_number"],
        "first_name": record["first_name"],
        "last_name": record["last_name"],
        "postal_code": record["postal_code"],
        "address_line": record["address_line"],
        "event_timestamp": db.iso(record["event_timestamp"]),
        "consent_signals": [dict(signal) for signal in record["consent_signals"]],
    }
    if record.get("loyalty_tier") is not None:
        payload["loyalty_tier"] = record["loyalty_tier"]
    for attribute in derive.SENSITIVE_ATTRIBUTES:
        if record.get(attribute) is not None:
            payload[attribute] = record[attribute]
    return payload


def ingest_batch(entity):
    return _common(entity, {
        "source_system_id": entity["source_system_id"],
        "batch_label": entity["batch_label"],
        "records": [_record(r) for r in entity["records"]],
        "record_count": entity["record_count"],
        "valid_record_count": entity["valid_record_count"],
        "invalid_record_count": entity["invalid_record_count"],
        "dq_score": None if entity["dq_score"] is None else float(entity["dq_score"]),
        "dq_failure_breakdown": dict(entity["dq_failure_breakdown"]),
        "status": entity["status"],
        "retry_round": entity["retry_round"],
        "rejection_reason": entity["rejection_reason"],
        "validated_at": db.iso(entity["validated_at"]),
        "promoted_at": db.iso(entity["promoted_at"]),
        "new_profile_count": entity["new_profile_count"],
        "matched_deterministic_count": entity["matched_deterministic_count"],
        "matched_probabilistic_count": entity["matched_probabilistic_count"],
    })


def profile(entity):
    channels = derive.activatable_channels(entity)
    return _common(entity, {
        "origin_batch_id": entity["origin_batch_id"],
        "primary_source_system_id": entity["primary_source_system_id"],
        "household_id": entity["household_id"],
        "merged_into_profile_id": entity["merged_into_profile_id"],
        "email_norm": entity["email_norm"],
        "phone_norm": entity["phone_norm"],
        "first_name": entity["first_name"],
        "last_name": entity["last_name"],
        "postal_code": entity["postal_code"],
        "address_hash": entity["address_hash"],
        "loyalty_number": entity["loyalty_number"],
        "loyalty_tier": entity["loyalty_tier"],
        "lifetime_value_cents": entity["lifetime_value_cents"],
        "channel_engagement_score": float(derive.engagement_score(entity)),
        "inferred_health_interest": entity["inferred_health_interest"],
        "inferred_ethnicity_affinity": entity["inferred_ethnicity_affinity"],
        "precise_geolocation_grid": entity["precise_geolocation_grid"],
        "resolution_status": entity["resolution_status"],
        "privacy_status": entity["privacy_status"],
        "activatable_channels": channels,
        "source_record_count": entity["source_record_count"],
        "contributing_source_system_codes": list(entity["contributing_source_system_codes"]),
        "consent_record_count": derive.active_consent_count(entity["id"]),
        "last_activity_at": db.iso(entity["last_activity_at"]),
    })


def household(entity):
    members = derive.household_members(entity["id"])
    dissolved = entity["status"] != "ACTIVE"
    return _common(entity, {
        "address_hash": entity["address_hash"],
        "sequence_no": entity["sequence_no"],
        "member_count": len(members),
        "status": entity["status"],
        "dominant_last_name": None if dissolved else derive.dominant_last_name(members),
        "combined_lifetime_value_cents": 0 if dissolved else derive.combined_lifetime_value(members),
    })


def match_rule(entity):
    return _common(entity, {
        "code": entity["code"],
        "rule_kind": entity["rule_kind"],
        "deterministic_key": entity["deterministic_key"],
        "missing_identifier_policy": entity["missing_identifier_policy"],
        "auto_merge_threshold": entity["auto_merge_threshold"],
        "review_floor": entity["review_floor"],
        "min_precision": entity["min_precision"],
        "status": entity["status"],
        "confirmed_count": entity["confirmed_count"],
        "rejected_count": entity["rejected_count"],
        "precision_estimate": float(
            calc.precision_estimate(entity["confirmed_count"], entity["rejected_count"])
        ),
    })


def identity_link(entity):
    return _common(entity, {
        "left_profile_id": entity["left_profile_id"],
        "right_profile_id": entity["right_profile_id"],
        "match_rule_id": entity["match_rule_id"],
        "survivor_profile_id": entity["survivor_profile_id"],
        "evidence": dict(entity["evidence"]),
        "match_method": entity["match_method"],
        "confidence": float(entity["confidence"]),
        "status": entity["status"],
        "decided_by_user_id": entity["decided_by_user_id"],
        "decided_at": db.iso(entity["decided_at"]),
        "void_reason": entity["void_reason"],
    })


def consent_record(entity):
    return _common(entity, {
        "profile_id": entity["profile_id"],
        "source_system_id": entity["source_system_id"],
        "channel": entity["channel"],
        "purpose": entity["purpose"],
        "consent_state": entity["consent_state"],
        "captured_at": db.iso(entity["captured_at"]),
        "expires_at": db.iso(entity["expires_at"]),
        "status": entity["status"],
        "precedence_rank": entity["precedence_rank"],
    })


def suppression_entry(entity):
    return _common(entity, {
        "profile_id": entity["profile_id"],
        "deletion_request_id": entity["deletion_request_id"],
        "entry_type": entity["entry_type"],
        "reason_code": entity["reason_code"],
        "effective_at": db.iso(entity["effective_at"]),
        "expires_at": db.iso(entity["expires_at"]),
        "status": entity["status"],
        "created_by_user_id": entity["created_by_user_id"],
        "released_by_user_id": entity["released_by_user_id"],
        "released_at": db.iso(entity["released_at"]),
    })


def segment(entity):
    return _common(entity, {
        "name": entity["name"],
        "criteria": [dict(c) for c in entity["criteria"]],
        "uses_sensitive_attributes": entity["uses_sensitive_attributes"],
        "governance_justification": entity["governance_justification"],
        "governance_valid_days": entity["governance_valid_days"],
        "status": entity["status"],
        "submitted_by_user_id": entity["submitted_by_user_id"],
        "decided_by_user_id": entity["decided_by_user_id"],
        "sensitive_use_approved": entity["sensitive_use_approved"],
        "approved_at": db.iso(entity["approved_at"]),
        "governance_expires_at": db.iso(entity["governance_expires_at"]),
        "rejection_count": entity["rejection_count"],
        "member_count": len(derive.segment_members(entity)),
        "active_activation_count": derive.active_activation_count(entity["id"]),
    })


def destination(entity):
    return _common(entity, {
        "code": entity["code"],
        "platform_kind": entity["platform_kind"],
        "channel": entity["channel"],
        "hashing_algorithm": entity["hashing_algorithm"],
        "match_rate_basis": entity["match_rate_basis"],
        "min_match_rate": entity["min_match_rate"],
        "min_audience_size": entity["min_audience_size"],
        "daily_hash_quota": entity["daily_hash_quota"],
        "remaining_daily_hash_quota": entity["remaining_daily_hash_quota"],
        "quota_reset_on": entity["quota_reset_on"],
        "cooldown_minutes": entity["cooldown_minutes"],
        "max_concurrent_activations": entity["max_concurrent_activations"],
        "sensitive_attribute_permitted": entity["sensitive_attribute_permitted"],
        "deletion_ack_sla_hours": entity["deletion_ack_sla_hours"],
        "status": entity["status"],
        "underperforming_activation_count": derive.underperforming_count(entity["id"]),
    })


def _conversion(conversion):
    return {
        "profile_id": conversion["profile_id"],
        "converted_at": db.iso(conversion["converted_at"]),
        "revenue_cents": conversion["revenue_cents"],
    }


def _rate(value):
    return None if value is None else float(value)


def activation(entity):
    return _common(entity, {
        "segment_id": entity["segment_id"],
        "destination_id": entity["destination_id"],
        "window_start_at": db.iso(entity["window_start_at"]),
        "window_end_at": db.iso(entity["window_end_at"]),
        "status": entity["status"],
        "candidate_count": entity["candidate_count"],
        "audience_size": entity["audience_size"],
        "suppressed_count": entity["suppressed_count"],
        "dispatched_hash_count": entity["dispatched_hash_count"],
        "unusable_hash_count": entity["unusable_hash_count"],
        "vendor_matched_count": entity["vendor_matched_count"],
        "gross_match_rate": _rate(entity["gross_match_rate"]),
        "net_match_rate": _rate(entity["net_match_rate"]),
        "effective_match_rate": _rate(entity["effective_match_rate"]),
        "attributed_conversion_count": len(entity["attributed_conversions"]),
        "attributed_conversions": [_conversion(c) for c in entity["attributed_conversions"]],
        "dispatched_at": db.iso(entity["dispatched_at"]),
        "paused_reason": entity["paused_reason"],
        "terminated_at": db.iso(entity["terminated_at"]),
    })


def _task_counts(request_id):
    counts = {"PENDING": 0, "DISPATCHED": 0, "ACKNOWLEDGED": 0, "FAILED": 0, "TIMED_OUT": 0}
    total = 0
    for task in db.all_of("vendor_deletion_tasks"):
        if task["deletion_request_id"] != request_id:
            continue
        total += 1
        counts[task["status"]] = counts.get(task["status"], 0) + 1
    return total, counts


def deletion_request(entity):
    total, counts = _task_counts(entity["id"])
    return _common(entity, {
        "profile_id": entity["profile_id"],
        "request_origin": entity["request_origin"],
        "requester_reference": entity["requester_reference"],
        "status": entity["status"],
        "total_vendor_task_count": total,
        "pending_vendor_task_count": counts["PENDING"] + counts["DISPATCHED"],
        "acknowledged_vendor_task_count": counts["ACKNOWLEDGED"],
        "failed_vendor_task_count": counts["FAILED"],
        "timed_out_vendor_task_count": counts["TIMED_OUT"],
        "propagated_at": db.iso(entity["propagated_at"]),
        "verified_at": db.iso(entity["verified_at"]),
        "blocked_reason": entity["blocked_reason"],
    })


def vendor_task(entity):
    return _common(entity, {
        "deletion_request_id": entity["deletion_request_id"],
        "destination_id": entity["destination_id"],
        "status": entity["status"],
        "dispatched_at": db.iso(entity["dispatched_at"]),
        "ack_deadline_at": db.iso(entity["ack_deadline_at"]),
        "acknowledged_at": db.iso(entity["acknowledged_at"]),
        "deletion_evidence_reference": entity["deletion_evidence_reference"],
        "acknowledged_record_count": entity["acknowledged_record_count"],
        "attempt_count": entity["attempt_count"],
    })


SERIALIZERS = {
    "source_systems": source_system,
    "ingest_batches": ingest_batch,
    "profiles": profile,
    "households": household,
    "match_rules": match_rule,
    "identity_links": identity_link,
    "consent_records": consent_record,
    "suppression_entries": suppression_entry,
    "segments": segment,
    "destinations": destination,
    "activations": activation,
    "deletion_requests": deletion_request,
    "vendor_deletion_tasks": vendor_task,
}
