"""Payload shapes for every entity (SCAFFOLD entities + PRD §2.4 audit stamps)."""

from services import derive

_AUDIT = ("id", "created_at", "updated_at", "version")


def _base(record):
    return {key: record[key] for key in _AUDIT if key in record}


def _num(value):
    return derive.as_float(value)


def insurer(record):
    payload = _base(record)
    payload.update(
        {
            "name": record["name"],
            "naic_code": record["naic_code"],
            "license_status": record["license_status"],
            "annual_premium_written_cents": record["annual_premium_written_cents"],
            "policy_count_in_force": record["policy_count_in_force"],
            "confirmed_complaints_12mo": record["confirmed_complaints_12mo"],
            "financial_stress_score": record["financial_stress_score"],
            "consumer_trend_score": record["consumer_trend_score"],
            "complaint_ratio_per_1k": _num(record["complaint_ratio_per_1k"]),
            "risk_tier": record["risk_tier"],
        }
    )
    payload.update(derive.insurer_counters(record["id"]))
    return payload


def cycle(record):
    payload = _base(record)
    payload.update(
        {
            "cycle_label": record["cycle_label"],
            "reference_period_start": record["reference_period_start"],
            "reference_period_end": record["reference_period_end"],
            "target_slot_capacity": record["target_slot_capacity"],
            "default_fieldwork_start": record["default_fieldwork_start"],
            "default_fieldwork_end": record["default_fieldwork_end"],
            "default_exam_mode": record["default_exam_mode"],
            "status": record["status"],
            "scored_at": record["scored_at"],
            "closed_at": record["closed_at"],
        }
    )
    payload.update(derive.cycle_counters(record))
    return payload


def analysis_score(record):
    payload = _base(record)
    payload.update(
        {
            "cycle_id": record["cycle_id"],
            "insurer_id": record["insurer_id"],
            "complaint_ratio_at_scoring": _num(record["complaint_ratio_at_scoring"]),
            "complaint_component": _num(record["complaint_component"]),
            "financial_component": _num(record["financial_component"]),
            "trend_component": _num(record["trend_component"]),
            "volume_multiplier": _num(record["volume_multiplier"]),
            "composite_score": _num(record["composite_score"]),
            "rank_position": record["rank_position"],
            "selected": record["selected"],
            "selection_reason": record["selection_reason"],
        }
    )
    return payload


def examination(record):
    payload = _base(record)
    payload.update(
        {
            "insurer_id": record["insurer_id"],
            "cycle_id": record["cycle_id"],
            "predecessor_exam_id": record["predecessor_exam_id"],
            "exam_type": record["exam_type"],
            "mode": record["mode"],
            "lead_state_code": record["lead_state_code"],
            "fieldwork_start_date": record["fieldwork_start_date"],
            "fieldwork_end_date": record["fieldwork_end_date"],
            "status": record["status"],
            "scope_locked": record["scope_locked"],
            "criticism_phase_opened_at": record["criticism_phase_opened_at"],
            "report_published_at": record["report_published_at"],
            "public_summary": record["public_summary"],
            "followup_required": record["followup_required"],
            "followup_due_date": record["followup_due_date"],
            "abort_reason": record["abort_reason"],
        }
    )
    payload.update(derive.exam_counters(record))
    return payload


def scope_area(record):
    payload = _base(record)
    payload.update(
        {
            "exam_id": record["exam_id"],
            "area": record["area"],
            "population_size": record["population_size"],
            "sample_size": record["sample_size"],
            "error_tolerance_pct": _num(record["error_tolerance_pct"]),
            "status": record["status"],
            "tested_at": record["tested_at"],
        }
    )
    metrics = derive.area_metrics(record)
    payload.update(
        {
            "reviewed_sample_count": metrics["reviewed_sample_count"],
            "error_count": metrics["error_count"],
            "material_error_count": metrics["material_error_count"],
            "error_rate_pct": _num(metrics["error_rate_pct"]),
            "material_error_rate_pct": _num(metrics["material_error_rate_pct"]),
            "tolerance_breached": metrics["tolerance_breached"],
            "escalation_required": metrics["escalation_required"],
        }
    )
    return payload


def data_call(record):
    payload = _base(record)
    payload.update(
        {
            "scope_area_id": record["scope_area_id"],
            "records_requested": record["records_requested"],
            "issued_date": record["issued_date"],
            "response_due_date": record["response_due_date"],
            "sampling_method": record["sampling_method"],
            "status": record["status"],
            "records_received": record["records_received"],
            "submitted_by_contact": record["submitted_by_contact"],
            "responded_at": record["responded_at"],
            "is_late": record["is_late"],
            "days_late": record["days_late"],
            "completeness_pct": _num(record["completeness_pct"]),
            "effective_completeness_pct": _num(record["effective_completeness_pct"]),
            "disposition_reason": record["disposition_reason"],
            "sample_draw_interval": record["sample_draw_interval"],
            "samples_drawn_count": len(derive.file_samples_of_call(record["id"])),
        }
    )
    return payload


def file_sample(record):
    payload = _base(record)
    payload.update(
        {
            "data_call_id": record["data_call_id"],
            "file_reference": record["file_reference"],
            "population_index": record["population_index"],
            "review_status": record["review_status"],
            "error_severity": record["error_severity"],
            "underpaid_amount_cents": record["underpaid_amount_cents"],
            "days_to_pay": record["days_to_pay"],
            "reviewed_at": record["reviewed_at"],
        }
    )
    return payload


def fieldwork_activity(record):
    # Append-only workpaper: no updated_at and no version key at all (PRD §2.4).
    return {
        "id": record["id"],
        "created_at": record["created_at"],
        "exam_id": record["exam_id"],
        "activity_type": record["activity_type"],
        "area": record["area"],
        "participant_name": record["participant_name"],
        "participant_title": record["participant_title"],
        "summary": record["summary"],
        "evidence_ref": record["evidence_ref"],
        "conducted_at": record["conducted_at"],
        "documented": record["documented"],
    }


def criticism(record):
    payload = _base(record)
    payload.update(
        {
            "exam_id": record["exam_id"],
            "scope_area_id": record["scope_area_id"],
            "statute_citation": record["statute_citation"],
            "severity": record["severity"],
            "affected_file_count": record["affected_file_count"],
            "status": record["status"],
            "response_round": record["response_round"],
            "rebuttal_count": record["rebuttal_count"],
            "restitution_method": record["restitution_method"],
            "restitution_exposure_cents": record["restitution_exposure_cents"],
            "penalty_units": record["penalty_units"],
            "issued_by_user_id": record["issued_by_user_id"],
            "finalized_by_user_id": record["finalized_by_user_id"],
            "finalized_at": record["finalized_at"],
            "disposition_note": record["disposition_note"],
        }
    )
    return payload


def company_response(record):
    # Append-only workpaper: no updated_at and no version key at all (PRD §2.4).
    return {
        "id": record["id"],
        "created_at": record["created_at"],
        "criticism_id": record["criticism_id"],
        "round_number": record["round_number"],
        "position": record["position"],
        "narrative": record["narrative"],
        "remediation_offer_cents": record["remediation_offer_cents"],
        "submitted_at": record["submitted_at"],
    }


def corrective_action_plan(record):
    payload = _base(record)
    payload.update(
        {
            "exam_id": record["exam_id"],
            "status": record["status"],
            "revision_round": record["revision_round"],
            "milestone_count": record["milestone_count"],
            "completion_due_date": record["completion_due_date"],
            "narrative": record["narrative"],
            "reviewed_by_user_id": record["reviewed_by_user_id"],
            "review_note": record["review_note"],
        }
    )
    return payload


def consent_order(record):
    payload = _base(record)
    payload.update(
        {
            "exam_id": record["exam_id"],
            "order_number": record["order_number"],
            "status": record["status"],
            "penalty_variant": record["penalty_variant"],
            "restitution_cents": record["restitution_cents"],
            "penalty_gross_cents": record["penalty_gross_cents"],
            "cooperation_credit_pct": _num(record["cooperation_credit_pct"]),
            "penalty_net_cents": record["penalty_net_cents"],
            "order_total_cents": record["order_total_cents"],
            "drafted_by_user_id": record["drafted_by_user_id"],
            "signed_by": record["signed_by"],
            "executed_at": record["executed_at"],
        }
    )
    return payload


def collaboration(record):
    payload = _base(record)
    participants = [
        {
            "state_code": p["state_code"],
            "policy_count_in_state": p["policy_count_in_state"],
            "has_examiner_resources": p["has_examiner_resources"],
            "allocated_cents": p["allocated_cents"],
        }
        for p in record["participating_states"]
    ]
    payload.update(
        {
            "exam_id": record["exam_id"],
            "call_reference": record["call_reference"],
            "participating_states": participants,
            "lead_state_code": record["lead_state_code"],
            "status": record["status"],
            "participant_count": len(participants),
            "allocated_total_cents": sum(p["allocated_cents"] for p in participants),
            "allocation_completed_at": record["allocation_completed_at"],
        }
    )
    return payload
