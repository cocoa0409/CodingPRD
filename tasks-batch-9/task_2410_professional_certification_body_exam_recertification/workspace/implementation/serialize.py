"""Record -> JSON projection.

Every entity carries the four common fields of PRD 2.4 (`id`, `created_at`,
`updated_at`, `version`).  Derived fields are refreshed at projection time so a
read always reflects the current logical clock and the current child rows.
"""

from services import derive
from util import fmt_ts, num_out


def _common(record):
    return {
        "id": record["id"],
        "created_at": fmt_ts(record["created_at"]),
        "updated_at": fmt_ts(record["updated_at"]),
        "version": record["version"],
    }


PROGRAM_KNOBS = (
    "psychometric_stat_basis",
    "min_discrimination",
    "min_p_value",
    "max_p_value",
    "min_responses_for_stats",
    "form_retirement_tolerance_pct",
    "min_panelists",
    "panel_trim_count",
    "cut_score_sem_multiplier",
    "education_recency_years",
    "min_experience_months",
    "audit_every_nth",
    "eligibility_valid_days",
    "exam_fee_cents",
    "max_attempts_per_cycle",
    "retake_wait_days",
    "cycle_length_months",
    "required_ceu_credits",
    "ceu_credit_accrual_basis",
    "ceu_carryover_max_credits",
    "recert_grace_days",
)


def program(record):
    body = _common(record)
    body.update({
        "name": record["name"],
        "credential_code": record["credential_code"],
        "jta_version": record["jta_version"],
        "domain_specs": [
            {
                "domain_code": spec["domain_code"],
                "weight_pct": spec["weight_pct"],
                "min_operational_items": spec["min_operational_items"],
            }
            for spec in record["domain_specs"]
        ],
        "form_length": record["form_length"],
        "accepted_education_credentials": list(record["accepted_education_credentials"]),
        "status": record["status"],
        "operational_item_count": record["operational_item_count"],
        "deficient_domain_codes": list(record["deficient_domain_codes"]),
        "blueprint_posture": record["blueprint_posture"],
        "verified_application_counter": record["verified_application_counter"],
        "certificants_issued_count": record["certificants_issued_count"],
    })
    for knob in PROGRAM_KNOBS:
        body[knob] = num_out(record[knob])
    return body


ITEM_ACCUMULATORS = (
    "pretest_response_count",
    "pretest_correct_count",
    "pretest_upper_n",
    "pretest_upper_correct",
    "pretest_lower_n",
    "pretest_lower_correct",
    "operational_response_count",
    "operational_correct_count",
    "operational_upper_n",
    "operational_upper_correct",
    "operational_lower_n",
    "operational_lower_correct",
)


def item(record):
    body = _common(record)
    body.update({
        "program_id": record["program_id"],
        "domain_code": record["domain_code"],
        "cognitive_level": record["cognitive_level"],
        "stem": record["stem"],
        "author_user_id": record["author_user_id"],
        "approver_user_ids": list(record["approver_user_ids"]),
        "review_round": record["review_round"],
        "status": record["status"],
        "p_value": num_out(record["p_value"]),
        "discrimination_index": num_out(record["discrimination_index"]),
        "stat_basis_applied": record["stat_basis_applied"],
        "flag_reason": record["flag_reason"],
        "retirement_reason": record["retirement_reason"],
        "retired_at": fmt_ts(record["retired_at"]),
    })
    for name in ITEM_ACCUMULATORS:
        body[name] = record[name]
    return body


def form(record):
    body = _common(record)
    body.update({
        "program_id": record["program_id"],
        "form_code": record["form_code"],
        "item_ids": list(record["item_ids"]),
        "pretest_item_ids": list(record["pretest_item_ids"]),
        "panelist_user_ids": list(record["panelist_user_ids"]),
        "panel_method": record["panel_method"],
        "panel_status": record["panel_status"],
        "panel_ratings": [
            {
                "panelist_user_id": rating["panelist_user_id"],
                "mean_expected_pass_rate": num_out(rating["mean_expected_pass_rate"]),
                "submitted_at": fmt_ts(rating["submitted_at"]),
            }
            for rating in record["panel_ratings"]
        ],
        "mean_expected_pass_rate": num_out(record["mean_expected_pass_rate"]),
        "raw_cut_score": record["raw_cut_score"],
        "scored_item_count": record["scored_item_count"],
        "retired_item_count": record["retired_item_count"],
        "status": record["status"],
    })
    return body


def candidate(record):
    body = _common(record)
    body.update({
        "email": record["email"],
        "full_name": record["full_name"],
        "status": record["status"],
        "barred_until": fmt_ts(record["barred_until"]),
        "bar_reason": record["bar_reason"],
    })
    return body


def application(record):
    body = _common(record)
    body.update({
        "candidate_id": record["candidate_id"],
        "program_id": record["program_id"],
        "education_credential": record["education_credential"],
        "education_completion_year": record["education_completion_year"],
        "experience_months": record["experience_months"],
        "attestation_signed": record["attestation_signed"],
        "education_status": record["education_status"],
        "experience_status": record["experience_status"],
        "status": record["status"],
        "verifier_user_ids": [
            {"dimension": entry["dimension"], "user_id": entry["user_id"]}
            for entry in record["verifier_user_ids"]
        ],
        "auditor_user_id": record["auditor_user_id"],
        "audit_sequence_number": record["audit_sequence_number"],
        "eligibility_expires_on": fmt_ts(record["eligibility_expires_on"]),
        "denial_reason": record["denial_reason"],
        "attempts_consumed": derive.application_attempts_consumed(record),
    })
    return body


def session(record):
    derive.refresh_session_projection(record)
    body = _common(record)
    body.update({
        "modality": record["modality"],
        "center_code": record["center_code"],
        "room_code": record["room_code"],
        "proctor_pool_code": record["proctor_pool_code"],
        "starts_at": fmt_ts(record["starts_at"]),
        "ends_at": fmt_ts(record["ends_at"]),
        "seat_capacity": record["seat_capacity"],
        "seats_reserved": record["seats_reserved"],
        "status": record["status"],
    })
    return body


def registration(record):
    body = _common(record)
    body.update({
        "candidate_id": record["candidate_id"],
        "application_id": record["application_id"],
        "form_id": record["form_id"],
        "session_id": record["session_id"],
        "session_ends_at": fmt_ts(record["session_ends_at"]),
        "fee_paid_cents": record["fee_paid_cents"],
        "attempt_number": record["attempt_number"],
        "eligibility_expires_on_snapshot": fmt_ts(record["eligibility_expires_on_snapshot"]),
        "seat_status": record["seat_status"],
        "score_status": record["score_status"],
        "score_status_before_hold": record["score_status_before_hold"],
        "raw_score": record["raw_score"],
        "scaled_score": record["scaled_score"],
        "outcome": record["outcome"],
        "form_reassignment_required": record["form_reassignment_required"],
    })
    return body


def incident(record):
    body = _common(record)
    body.update({
        "registration_id": record["registration_id"],
        "incident_type": record["incident_type"],
        "severity": record["severity"],
        "description": record["description"],
        "status": record["status"],
        "outcome_note": record["outcome_note"],
        "placed_hold": record["placed_hold"],
    })
    return body


def certificant(record):
    derive.refresh_certificant_projection(record)
    body = _common(record)
    body.update({
        "candidate_id": record["candidate_id"],
        "program_id": record["program_id"],
        "certificate_number": record["certificate_number"],
        "issued_on": fmt_ts(record["issued_on"]),
        "valid_through": fmt_ts(record["valid_through"]),
        "status": record["status"],
        "suspension_until": fmt_ts(record["suspension_until"]),
        "publication_status": record["publication_status"],
        "ceu_credits_applied": num_out(record["ceu_credits_applied"]),
        "current_cycle_id": record["current_cycle_id"],
    })
    return body


def cycle(record):
    body = _common(record)
    body.update({
        "certificant_id": record["certificant_id"],
        "reexam_registration_id": record["reexam_registration_id"],
        "cycle_number": record["cycle_number"],
        "starts_on": fmt_ts(record["starts_on"]),
        "ends_on": fmt_ts(record["ends_on"]),
        "grace_ends_on": fmt_ts(record["grace_ends_on"]),
        "required_credits": num_out(record["required_credits"]),
        "accrual_basis_snapshot": record["accrual_basis_snapshot"],
        "carryover_credits_in": num_out(record["carryover_credits_in"]),
        "credits_applied": num_out(record["credits_applied"]),
        "carryover_credits_out": num_out(record["carryover_credits_out"]),
        "path": record["path"],
        "status": record["status"],
        "reinstatement_fee_cents": record["reinstatement_fee_cents"],
    })
    return body


def activity(record):
    body = _common(record)
    body.update({
        "cycle_id": record["cycle_id"],
        "activity_date": fmt_ts(record["activity_date"]),
        "category": record["category"],
        "provider": record["provider"],
        "contact_hours": num_out(record["contact_hours"]),
        "credits_awarded": num_out(record["credits_awarded"]),
        "credits_counted": num_out(record["credits_counted"]),
        "counted": record["counted"],
        "status": record["status"],
        "reviewer_user_id": record["reviewer_user_id"],
        "audit_verifier_user_id": record["audit_verifier_user_id"],
        "review_note": record["review_note"],
    })
    return body


def case(record):
    body = _common(record)
    body.update({
        "certificant_id": record["certificant_id"],
        "allegation_type": record["allegation_type"],
        "description": record["description"],
        "status": record["status"],
        "response_round": record["response_round"],
        "response_text": record["response_text"],
        "outcome": record["outcome"],
        "sanction_months": record["sanction_months"],
        "decided_on": fmt_ts(record["decided_on"]),
        "opened_by_user_id": record["opened_by_user_id"],
    })
    return body
