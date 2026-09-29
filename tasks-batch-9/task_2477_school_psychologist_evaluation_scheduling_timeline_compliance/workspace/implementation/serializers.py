"""Resource serializers. Common fields (PRD §2.5) close every payload."""

import services


def _common(record, payload):
    payload["created_at"] = record["created_at"]
    payload["updated_at"] = record["updated_at"]
    payload["version"] = record["version"]
    return payload


def school(record):
    return _common(record, {
        "id": record["id"],
        "name": record["name"],
        "building_code": record["building_code"],
        "grade_band": record["grade_band"],
        "concurrent_meeting_capacity": record["concurrent_meeting_capacity"],
        "enrollment_count": record["enrollment_count"],
    })


def psychologist(record):
    return _common(record, {
        "id": record["id"],
        "full_name": record["full_name"],
        "employee_number": record["employee_number"],
        "credential_type": record["credential_type"],
        "languages_certified": list(record["languages_certified"]),
        "assigned_school_ids": list(record["assigned_school_ids"]),
        "weekly_capacity_points": record["weekly_capacity_points"],
        "status": record["status"],
        "open_case_points": record["open_case_points"],
        "caseload_status": record["caseload_status"],
        "pressure_index_assigned_basis": float(record["pressure_index_assigned_basis"]),
        "pressure_index_clock_weighted": float(record["pressure_index_clock_weighted"]),
    })


def referral(record):
    return _common(record, {
        "id": record["id"],
        "school_id": record["school_id"],
        "active_evaluation_id": record["active_evaluation_id"],
        "student_local_id": record["student_local_id"],
        "referral_type": record["referral_type"],
        "prior_evaluation_id": record["prior_evaluation_id"],
        "primary_language": record["primary_language"],
        "interpreter_required": record["interpreter_required"],
        "bilingual_evaluation_required": record["bilingual_evaluation_required"],
        "requested_domains": list(record["requested_domains"]),
        "intervention_team_summary": record["intervention_team_summary"],
        "status": record["status"],
        "consent_received_at": record["consent_received_at"],
        "last_consent_event_type": record["last_consent_event_type"],
        "parent_signature_reference": record["parent_signature_reference"],
        "waiver_reason": record["waiver_reason"],
    })


def evaluation(record):
    clock = services.resolve_clock(record)
    return _common(record, {
        "id": record["id"],
        "referral_id": record["referral_id"],
        "psychologist_id": record["psychologist_id"],
        "prior_evaluation_id": record["prior_evaluation_id"],
        "testing_instrument_id": record["testing_instrument_id"],
        "report_drafted_by_psychologist_id": record["report_drafted_by_psychologist_id"],
        "evaluation_domains": list(record["evaluation_domains"]),
        "interpreter_required": record["interpreter_required"],
        "referral_type": record["referral_type"],
        "assessment_status": record["assessment_status"],
        "compliance_status": record["compliance_status"],
        "clock_start_date": record["clock_start_date"],
        "base_due_date": clock["base_due_date"],
        "credited_exclusion_days": clock["credited_exclusion_days"],
        "statutory_due_date": clock["statutory_due_date"],
        "elapsed_statutory_days": clock["elapsed_statutory_days"],
        "days_remaining": clock["days_remaining"],
        "caseload_points": record["caseload_points"],
        "reassignment_count": record["reassignment_count"],
        "protocol_units_consumed": record["protocol_units_consumed"],
        "score_summary": record["score_summary"],
        "report_narrative": record["report_narrative"],
    })


def timeline_exclusion(record):
    return _common(record, {
        "id": record["id"],
        "evaluation_id": record["evaluation_id"],
        "exclusion_type": record["exclusion_type"],
        "start_date": record["start_date"],
        "end_date": record["end_date"],
        "claim_note": record["claim_note"],
        "status": record["status"],
        "days_claimed": record["days_claimed"],
        "days_credited": record["days_credited"],
        "decided_by_user_id": record["decided_by_user_id"],
        "decided_at": record["decided_at"],
    })


def assessment_instrument(record):
    return _common(record, {
        "id": record["id"],
        "name": record["name"],
        "instrument_code": record["instrument_code"],
        "protocol_stock_count": record["protocol_stock_count"],
        "protocol_units_per_administration": record["protocol_units_per_administration"],
        "protocol_unit_cost_cents": record["protocol_unit_cost_cents"],
        "license_seat_total": record["license_seat_total"],
        "license_seats_free": services.license_seats_free(record),
        "license_expires_on": record["license_expires_on"],
        "license_status": services.license_status(record),
        "supported_language_editions": list(record["supported_language_editions"]),
    })


def protocol_order(record):
    return _common(record, {
        "id": record["id"],
        "instrument_id": record["instrument_id"],
        "quantity_requested": record["quantity_requested"],
        "rush_flag": record["rush_flag"],
        "unit_price_cents": record["unit_price_cents"],
        "base_cents": record["base_cents"],
        "contract_discount_cents": record["contract_discount_cents"],
        "rush_surcharge_cents": record["rush_surcharge_cents"],
        "handling_fee_cents": record["handling_fee_cents"],
        "total_cost_cents": record["total_cost_cents"],
        "status": record["status"],
        "auto_approved": record["auto_approved"],
        "received_quantity": record["received_quantity"],
        "decided_by_user_id": record["decided_by_user_id"],
    })


def scoring_license_seat(record):
    return _common(record, {
        "id": record["id"],
        "instrument_id": record["instrument_id"],
        "psychologist_id": record["psychologist_id"],
        "status": record["status"],
        "assigned_at": record["assigned_at"],
        "released_at": record["released_at"],
    })


def interpreter_session(record):
    return _common(record, {
        "id": record["id"],
        "evaluation_id": record["evaluation_id"],
        "language_code": record["language_code"],
        "interpreter_name": record["interpreter_name"],
        "session_start_at": record["session_start_at"],
        "session_end_at": record["session_end_at"],
        "status": record["status"],
        "cancellation_reason": record["cancellation_reason"],
        "duration_minutes": record["duration_minutes"],
    })


def eligibility_meeting(record):
    return _common(record, {
        "id": record["id"],
        "evaluation_id": record["evaluation_id"],
        "school_id": record["school_id"],
        "scheduled_start_at": record["scheduled_start_at"],
        "scheduled_end_at": record["scheduled_end_at"],
        "parent_notice_sent_at": record["parent_notice_sent_at"],
        "notice_lead_days": record["notice_lead_days"],
        "reschedule_count": record["reschedule_count"],
        "status": record["status"],
        "held_at": record["held_at"],
    })


def timeline_breach(record):
    return _common(record, {
        "id": record["id"],
        "evaluation_id": record["evaluation_id"],
        "detected_at": record["detected_at"],
        "breach_days": record["breach_days"],
        "severity": record["severity"],
        "minutes_breach_day_basis": record["minutes_breach_day_basis"],
        "minutes_missed_service_basis": record["minutes_missed_service_basis"],
        "remedy_basis": record["remedy_basis"],
        "additional_minutes": record["additional_minutes"],
        "remedy_minutes_awarded": record["remedy_minutes_awarded"],
        "corrective_action_note": record["corrective_action_note"],
        "proposed_by_user_id": record["proposed_by_user_id"],
        "approved_by_user_id": record["approved_by_user_id"],
        "status": record["status"],
    })
