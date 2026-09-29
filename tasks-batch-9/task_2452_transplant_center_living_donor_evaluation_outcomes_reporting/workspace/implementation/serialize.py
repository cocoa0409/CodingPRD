"""Entity serializers.  Derived figures are computed at read time."""

import domain
from util import iso, num


def _common(row, payload):
    payload["id"] = row["id"]
    payload["created_at"] = iso(row["created_at"])
    payload["updated_at"] = iso(row["updated_at"])
    payload["version"] = row["version"]
    return payload


def program(row):
    committed = domain.fund_committed_cents(row)
    return _common(
        row,
        {
            "name": row["name"],
            "center_code": row["center_code"],
            "organ_type": row["organ_type"],
            "cooling_off_days": row["cooling_off_days"],
            "follow_up_completeness_threshold_pct": num(
                row["follow_up_completeness_threshold_pct"]
            ),
            "follow_up_compliance_threshold_pct": num(row["follow_up_compliance_threshold_pct"]),
            "expected_one_year_survival_rate": num(row["expected_one_year_survival_rate"]),
            "donor_fund_pool_cents": row["donor_fund_pool_cents"],
            "lost_wage_daily_cap_cents": row["lost_wage_daily_cap_cents"],
            "lost_wage_weekly_cap_cents": row["lost_wage_weekly_cap_cents"],
            "donor_fund_committed_cents": committed,
            "donor_fund_remaining_cents": row["donor_fund_pool_cents"] - committed,
            "follow_up_compliance_pct": num(domain.program_compliance_pct(row)),
            "cit_breach_count": domain.program_cit_breach_count(row),
            "compliance_posture": row["compliance_posture"],
            "last_sweep_at": iso(row["last_sweep_at"]),
        },
    )


def staff_member(row):
    return _common(
        row,
        {
            "program_id": row["program_id"],
            "full_name": row["full_name"],
            "staff_role": row["staff_role"],
            "npi": row["npi"],
            "is_active": row["is_active"],
        },
    )


def operating_room(row):
    return _common(
        row,
        {
            "program_id": row["program_id"],
            "room_code": row["room_code"],
            "turnover_buffer_minutes": row["turnover_buffer_minutes"],
            "reserved_minutes_total": domain.room_reserved_minutes(row),
        },
    )


def recipient_candidate(row):
    return _common(
        row,
        {
            "program_id": row["program_id"],
            "mrn": row["mrn"],
            "abo_blood_type": row["abo_blood_type"],
            "age_years": row["age_years"],
            "cpra": num(row["cpra"]),
            "dialysis_years": num(row["dialysis_years"]),
            "medical_urgency_points": row["medical_urgency_points"],
            "listing_status": row["listing_status"],
            "candidacy_approved_by_staff_id": row["candidacy_approved_by_staff_id"],
            "registered_at": iso(row["registered_at"]),
            "active_days_total": domain.recipient_active_days(row),
            "waitlist_priority_score": num(domain.recipient_priority_score(row)),
            "offer_decline_count": domain.recipient_decline_count(row),
        },
    )


def waitlist_event(row):
    return {
        "id": row["id"],
        "recipient_candidate_id": row["recipient_candidate_id"],
        "from_status": row["from_status"],
        "to_status": row["to_status"],
        "reason_code": row["reason_code"],
        "effective_at": iso(row["effective_at"]),
        "actor_user_id": row["actor_user_id"],
        "created_at": iso(row["created_at"]),
    }


def donor_candidate(row):
    return _common(
        row,
        {
            "program_id": row["program_id"],
            "intended_recipient_id": row["intended_recipient_id"],
            "referred_by_staff_id": row["referred_by_staff_id"],
            "advocate_staff_id": row["advocate_staff_id"],
            "mrn": row["mrn"],
            "abo_blood_type": row["abo_blood_type"],
            "age_years": row["age_years"],
            "advocacy_status": row["advocacy_status"],
            "disclosure_at": iso(row["disclosure_at"]),
            "disclosure_sequence": row["disclosure_sequence"],
            "cooling_off_ends_at": iso(row["cooling_off_ends_at"]),
            "attestation_at": iso(row["attestation_at"]),
            "objection_reason_code": row["objection_reason_code"],
            "medical_status": row["medical_status"],
            "psychosocial_status": row["psychosocial_status"],
            "medical_risk_points": row["medical_risk_points"],
            "psychosocial_risk_points": row["psychosocial_risk_points"],
            "deferral_count": row["deferral_count"],
            "screening_risk_index": num(domain.donor_screening_index(row)),
            "final_risk_index": num(row["final_risk_index"]),
            "overall_status": row["overall_status"],
            "donated_at": iso(row["donated_at"]),
        },
    )


def donor_evaluation(row):
    return _common(
        row,
        {
            "donor_candidate_id": row["donor_candidate_id"],
            "reviewer_staff_id": row["reviewer_staff_id"],
            "domain": row["domain"],
            "status": row["status"],
            "bmi": num(row["bmi"]),
            "egfr_ml_min": num(row["egfr_ml_min"]),
            "systolic_bp": row["systolic_bp"],
            "hba1c": num(row["hba1c"]),
            "coercion_flag": row["coercion_flag"],
            "unmanaged_substance_use": row["unmanaged_substance_use"],
            "decisional_capacity_ok": row["decisional_capacity_ok"],
            "financial_hardship_score": row["financial_hardship_score"],
            "social_support_score": row["social_support_score"],
            "exclusion_codes": list(row["exclusion_codes"]),
            "hard_exclusion_count": row["hard_exclusion_count"],
            "risk_points": row["risk_points"],
            "submission_count": row["submission_count"],
            "determined_at": iso(row["determined_at"]),
        },
    )


def exchange_chain(row):
    return _common(
        row,
        {
            "program_id": row["program_id"],
            "chain_type": row["chain_type"],
            "status": row["status"],
            "segment_count": domain.chain_segment_count(row),
            "is_closed_loop": domain.chain_is_closed_loop(row),
            "total_planned_cit_minutes": domain.chain_total_planned_cit(row),
            "committed_donor_count": domain.chain_committed_donor_count(row),
            "validated_at": iso(row["validated_at"]),
            "committed_at": iso(row["committed_at"]),
            "break_reason_code": row["break_reason_code"],
        },
    )


def chain_segment(row):
    return _common(
        row,
        {
            "exchange_chain_id": row["exchange_chain_id"],
            "position": row["position"],
            "donor_candidate_id": row["donor_candidate_id"],
            "recipient_candidate_id": row["recipient_candidate_id"],
            "predecessor_segment_id": row["predecessor_segment_id"],
            "status": row["status"],
            "planned_cross_clamp_at": iso(row["planned_cross_clamp_at"]),
            "planned_reperfusion_at": iso(row["planned_reperfusion_at"]),
            "planned_transport_minutes": row["planned_transport_minutes"],
            "offer_sent_at": iso(row["offer_sent_at"]),
            "offer_response_deadline_at": iso(row["offer_response_deadline_at"]),
            "offer_responded_at": iso(row["offer_responded_at"]),
            "decline_reason_code": row["decline_reason_code"],
            "planned_cit_minutes": row["planned_cit_minutes"],
            "actual_cross_clamp_at": iso(row["actual_cross_clamp_at"]),
            "actual_reperfusion_at": iso(row["actual_reperfusion_at"]),
            "actual_cit_minutes": row["actual_cit_minutes"],
            "cit_breach": row["cit_breach"],
        },
    )


def procedure_booking(row):
    return _common(
        row,
        {
            "operating_room_id": row["operating_room_id"],
            "chain_segment_id": row["chain_segment_id"],
            "surgeon_staff_id": row["surgeon_staff_id"],
            "booking_role": row["booking_role"],
            "start_at": iso(row["start_at"]),
            "end_at": iso(row["end_at"]),
            "status": row["status"],
            "duration_minutes": row["duration_minutes"],
            "cancel_reason_code": row["cancel_reason_code"],
        },
    )


def donor_follow_up(row):
    return _common(
        row,
        {
            "donor_candidate_id": row["donor_candidate_id"],
            "interval_code": row["interval_code"],
            "due_on": iso(row["due_on"]),
            "required_fields_count": row["required_fields_count"],
            "submitted_field_count": row["submitted_field_count"],
            "completeness_pct": num(row["completeness_pct"]),
            "status": row["status"],
            "submitted_at": iso(row["submitted_at"]),
            "waiver_reason_code": row["waiver_reason_code"],
        },
    )


def outcome_review(row):
    return _common(
        row,
        {
            "program_id": row["program_id"],
            "period_start_on": row["period_start_on"],
            "period_end_on": row["period_end_on"],
            "cohort_size": row["cohort_size"],
            "observed_survivor_count": row["observed_survivor_count"],
            "expected_survival_rate_used": num(row["expected_survival_rate_used"]),
            "expected_survivor_count": num(row["expected_survivor_count"]),
            "oe_ratio": num(row["oe_ratio"]),
            "flag_level": row["flag_level"],
            "requires_improvement_plan": row["requires_improvement_plan"],
            "status": row["status"],
            "finalized_at": iso(row["finalized_at"]),
        },
    )


def improvement_plan(row):
    return _common(
        row,
        {
            "program_outcome_review_id": row["program_outcome_review_id"],
            "title": row["title"],
            "milestone_count": row["milestone_count"],
            "target_completion_on": row["target_completion_on"],
            "status": row["status"],
            "decision_reason_code": row["decision_reason_code"],
            "decided_at": iso(row["decided_at"]),
            "closed_at": iso(row["closed_at"]),
        },
    )


def donor_cost_claim(row):
    return _common(
        row,
        {
            "donor_candidate_id": row["donor_candidate_id"],
            "claim_type": row["claim_type"],
            "coverage_source": row["coverage_source"],
            "submitted_amount_cents": row["submitted_amount_cents"],
            "lost_wage_days": row["lost_wage_days"],
            "service_from_on": row["service_from_on"],
            "service_to_on": row["service_to_on"],
            "estimated_reimbursement_cents": row["estimated_reimbursement_cents"],
            "adjudicated_reimbursement_cents": row["adjudicated_reimbursement_cents"],
            "insurance_part_cents": row["insurance_part_cents"],
            "grant_part_cents": row["grant_part_cents"],
            "fund_part_cents": row["fund_part_cents"],
            "unfunded_cents": row["unfunded_cents"],
            "status": row["status"],
            "adjudicated_at": iso(row["adjudicated_at"]),
            "adjudicated_by_user_id": row["adjudicated_by_user_id"],
            "reversal_reason_code": row["reversal_reason_code"],
        },
    )
