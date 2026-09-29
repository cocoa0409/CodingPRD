"""Wire representations. Field lists are explicit so a response never leaks an
internal bookkeeping key, and every timestamp is rendered with exactly three
fractional-second digits (PRD 2.4)."""
import cascade
from common import iso, num


def _audit(record, payload):
    payload["id"] = record["id"]
    payload["created_at"] = iso(record["created_at"])
    payload["updated_at"] = iso(record["updated_at"])
    payload["version"] = record["version"]
    return payload


def center(record):
    return _audit(
        record,
        {
            "name": record["name"],
            "state_code": record["state_code"],
            "designation_level": record["designation_level"],
            "verification_cycle_start_date": iso(record["verification_cycle_start_date"]),
            "national_verification_status": record["national_verification_status"],
            "state_designation_status": record["state_designation_status"],
            # computed live: an overdue loop degrades the posture with no write
            "readiness_posture": cascade.posture_of(record),
            "registry_compliance_score": num(record["registry_compliance_score"]),
            "under_triage_rate_pct": num(record["under_triage_rate_pct"]),
            "over_triage_rate_pct": num(record["over_triage_rate_pct"]),
            "outreach_credit_hours_ytd": num(record["outreach_credit_hours_ytd"]),
            "open_critical_deficiency_count": record["open_critical_deficiency_count"],
            "escalated_critical_deficiency_count": record["escalated_critical_deficiency_count"],
            "open_pi_event_count": record["open_pi_event_count"],
            "closed_pi_event_count": record["closed_pi_event_count"],
            "registry_included_case_count": record["registry_included_case_count"],
            "registry_excluded_case_count": record["registry_excluded_case_count"],
        },
    )


def tier(record):
    return _audit(
        record,
        {
            "center_id": record["center_id"],
            "tier_code": record["tier_code"],
            "surgeon_response_limit_minutes": record["surgeon_response_limit_minutes"],
            "specialty_response_limit_minutes": record["specialty_response_limit_minutes"],
            "iss_threshold": record["iss_threshold"],
        },
    )


def case(record):
    return _audit(
        record,
        {
            "center_id": record["center_id"],
            "activation_tier_id": record["activation_tier_id"],
            "mrn": record["mrn"],
            "arrival_at": iso(record["arrival_at"]),
            "injury_severity_score": record["injury_severity_score"],
            "los_hours": num(record["los_hours"]),
            "ed_disposition": record["ed_disposition"],
            "transfer_in_from_center_id": record["transfer_in_from_center_id"],
            "transfer_out_to_center_id": record["transfer_out_to_center_id"],
            "abstraction_status": record["abstraction_status"],
            "triage_review_status": record["triage_review_status"],
            "effective_iss": record["effective_iss"],
            "inclusion_status": record["inclusion_status"],
            "inclusion_reason": record["inclusion_reason"],
            "locked_at": iso(record["locked_at"]),
            "review_note": record.get("review_note"),
        },
    )


def abstraction(record):
    return _audit(
        record,
        {
            "case_id": record["case_id"],
            "submitted_by_user_id": record["submitted_by_user_id"],
            "iss_abstracted": record["iss_abstracted"],
            "gcs_arrival": record["gcs_arrival"],
            "mechanism_code": record["mechanism_code"],
            "ed_departure_at": iso(record["ed_departure_at"]),
            "validation_status": record["validation_status"],
            "validated_by_user_id": record["validated_by_user_id"],
            "rejection_reason": record["rejection_reason"],
            "dictionary_error_count": record["dictionary_error_count"],
            "applied_penalty_points": num(record["applied_penalty_points"]),
            "band_multiplier_used": float(record["band_multiplier_used"]),
        },
    )


def rule(record):
    # A DataDictionaryRule is immutable configuration: id and created_at only.
    return {
        "id": record["id"],
        "created_at": iso(record["created_at"]),
        "field_name": record["field_name"],
        "rule_kind": record["rule_kind"],
        "severity": record["severity"],
        "min_value": record["min_value"],
        "max_value": record["max_value"],
        "allowed_codes": record["allowed_codes"],
        "error_weight": record["error_weight"],
    }


def response_log(record):
    return _audit(
        record,
        {
            "case_id": record["case_id"],
            "responder_role": record["responder_role"],
            "responder_user_id": record["responder_user_id"],
            "notified_at": iso(record["notified_at"]),
            "arrived_at": iso(record["arrived_at"]),
            "response_minutes": (
                None if record["response_minutes"] is None else num(record["response_minutes"])
            ),
            "applicable_limit_minutes": record["applicable_limit_minutes"],
            "compliance_status": record["compliance_status"],
        },
    )


def pi_event(record):
    return _audit(
        record,
        {
            "center_id": record["center_id"],
            "case_id": record["case_id"],
            "source_deficiency_id": record["source_deficiency_id"],
            "event_type": record["event_type"],
            "severity": record["severity"],
            "status": record["status"],
            "origin": record["origin"],
            "opened_at": iso(record["opened_at"]),
            "loop_closure_due_at": iso(record["loop_closure_due_at"]),
            "closed_at": iso(record["closed_at"]),
            "review_round": record["review_round"],
            "corrective_action_count": record["corrective_action_count"],
            "verified_action_count": record["verified_action_count"],
            "loop_closure_note": record.get("loop_closure_note"),
            "reopen_reason": record.get("reopen_reason"),
        },
    )


def action(record):
    return _audit(
        record,
        {
            "pi_event_id": record["pi_event_id"],
            "action_type": record["action_type"],
            "owner_user_id": record["owner_user_id"],
            "due_at": iso(record["due_at"]),
            "completion_status": record["completion_status"],
            "completed_at": iso(record["completed_at"]),
            "verified_at": iso(record["verified_at"]),
            "verified_by_user_id": record["verified_by_user_id"],
            "completion_note": record.get("completion_note"),
        },
    )


def cycle(record):
    return _audit(
        record,
        {
            "center_id": record["center_id"],
            "cycle_type": record["cycle_type"],
            "site_visit_date": iso(record["site_visit_date"]),
            "status": record["status"],
            "readiness_score": num(record["readiness_score"]),
            "open_type_i_count": record["open_type_i_count"],
            "open_type_ii_count": record["open_type_ii_count"],
            "open_type_iii_count": record["open_type_iii_count"],
            "decided_at": iso(record["decided_at"]),
            "decision_effective_date": iso(record["decision_effective_date"]),
            "decision": record.get("decision"),
        },
    )


def deficiency(record):
    return _audit(
        record,
        {
            "verification_cycle_id": record["verification_cycle_id"],
            "criterion_code": record["criterion_code"],
            "deficiency_class": record["deficiency_class"],
            "status": record["status"],
            "remediation_due_at": iso(record["remediation_due_at"]),
            "remediation_note": record["remediation_note"],
            "closed_at": iso(record["closed_at"]),
            "escalation_reason": record.get("escalation_reason"),
        },
    )


def activity(record):
    return _audit(
        record,
        {
            "center_id": record["center_id"],
            "activity_kind": record["activity_kind"],
            "event_date": iso(record["event_date"]),
            "credit_hours": num(record["credit_hours"], 3),
            "audience_count": record["audience_count"],
            "verified_status": record["verified_status"],
            "weighted_credit_hours": num(record["weighted_credit_hours"]),
            "reviewed_by_user_id": record["reviewed_by_user_id"],
            "rejection_reason": record.get("rejection_reason"),
        },
    )


def agreement(record):
    return _audit(
        record,
        {
            "referring_center_id": record["referring_center_id"],
            "receiving_center_id": record["receiving_center_id"],
            "agreement_status": record["agreement_status"],
            "effective_from": iso(record["effective_from"]),
            "effective_to": iso(record["effective_to"]),
            "guaranteed_acceptance_minutes": record["guaranteed_acceptance_minutes"],
            "activated_at": iso(record["activated_at"]),
            "terminated_at": iso(record["terminated_at"]),
            "termination_reason": record.get("termination_reason"),
        },
    )


def booking(record):
    return _audit(
        record,
        {
            "verification_cycle_id": record["verification_cycle_id"],
            "surveyor_user_id": record["surveyor_user_id"],
            "window_start": iso(record["window_start"]),
            "window_end": iso(record["window_end"]),
            "travel_buffer_hours": record["travel_buffer_hours"],
        },
    )
