"""Entity serializers. Computed fields are derived at read time."""
import calc
import db
from db import store


def _num(value):
    return None if value is None else float(value)


def _common(row, out):
    out["id"] = row["id"]
    out["created_at"] = db.fmt_dt(row["created_at"])
    if "version" in row:
        out["updated_at"] = db.fmt_dt(row["updated_at"])
        out["version"] = row["version"]
    return out


def facility(row):
    balance = calc.penalty_balance(row)
    return _common(row, {
        "name": row["name"],
        "facility_type": row["facility_type"],
        "region_code": row["region_code"],
        "navigation_budget_units_total": row["navigation_budget_units_total"],
        "navigation_budget_units_remaining": calc.budget_remaining(row),
        "penalty_points_balance": balance,
        "manual_adjustment_points_total": row["manual_adjustment_points_total"],
        "reporting_compliance_status": calc.compliance_posture(balance),
        "performance_score": _num(row["performance_score"]),
        "encounter_basis_performance_score":
            _num(row["encounter_basis_performance_score"]),
        "last_closed_period_label": row["last_closed_period_label"],
    })


def provider(row):
    return _common(row, {
        "facility_id": row["facility_id"],
        "provider_type": row["provider_type"],
        "full_name": row["full_name"],
        "region_code": row["region_code"],
        "languages": list(row["languages"]),
        "credential_status": row["credential_status"],
        "max_open_tasks": row["max_open_tasks"],
        "open_task_count": calc.provider_open_task_count(row["id"]),
    })


def infant(row):
    return _common(row, {
        "birth_facility_id": row["birth_facility_id"],
        "birth_datetime": db.fmt_dt(row["birth_datetime"]),
        "birth_setting": row["birth_setting"],
        "gestational_age_weeks": row["gestational_age_weeks"],
        "nicu_stay_days": row["nicu_stay_days"],
        "preferred_language": row["preferred_language"],
        "interpreter_required": row["interpreter_required"],
        "guardian_name": row["guardian_name"],
        "guardian_contact_phone": row["guardian_contact_phone"],
        "guardian_consent_status": row["guardian_consent_status"],
        "discharge_datetime": db.fmt_dt(row["discharge_datetime"]),
        "discharged_unscreened": row["discharged_unscreened"],
        "screening_status": row["screening_status"],
        "intervention_status": row["intervention_status"],
        "ltf_risk_score": row["ltf_risk_score"],
        "priority_band": row["priority_band"],
        "missed_appointment_count": calc.missed_appointment_count(row["id"]),
        "risk_factor_count": calc.risk_factor_count(row["id"]),
        "reengagement_count": row["reengagement_count"],
    })


def encounter(row):
    return _common(row, {
        "infant_id": row["infant_id"],
        "facility_id": row["facility_id"],
        "performed_by_provider_id": row["performed_by_provider_id"],
        "episode_id": row["episode_id"],
        "appointment_id": row["appointment_id"],
        "prior_encounter_id": row["prior_encounter_id"],
        "encounter_type": row["encounter_type"],
        "method": row["method"],
        "performed_at": db.fmt_dt(row["performed_at"]),
        "left_ear_result": row["left_ear_result"],
        "right_ear_result": row["right_ear_result"],
        "overall_result": row["overall_result"],
        "before_discharge": row["before_discharge"],
        "age_days_at_encounter": row["age_days_at_encounter"],
    })


def episode(row):
    return _common(row, {
        "infant_id": row["infant_id"],
        "supersedes_episode_id": row["supersedes_episode_id"],
        "episode_type": row["episode_type"],
        "status": row["status"],
        "owner_scope": row["owner_scope"],
        "escalation_flag": row["escalation_flag"],
        "benchmark_days": row["benchmark_days"],
        "due_date": db.fmt_dt(row["due_date"]),
        "attempt_count": calc.attempt_count(row),
        "timeliness_status": row["timeliness_status"],
        "closure_reason": row["closure_reason"],
        "closed_at": db.fmt_dt(row["closed_at"]),
    })


def slot(row):
    return _common(row, {
        "facility_id": row["facility_id"],
        "provider_id": row["provider_id"],
        "starts_at": db.fmt_dt(row["starts_at"]),
        "ends_at": db.fmt_dt(row["ends_at"]),
        "slot_type": row["slot_type"],
        "total_capacity": row["total_capacity"],
        "booked_count": calc.slot_booked_count(row),
        "remaining_capacity": calc.slot_remaining(row),
        "status": calc.slot_status(row),
    })


def appointment(row):
    return _common(row, {
        "episode_id": row["episode_id"],
        "slot_id": row["slot_id"],
        "infant_id": row["infant_id"],
        "linked_navigation_task_id": row["linked_navigation_task_id"],
        "interpreter_needed": row["interpreter_needed"],
        "status": row["status"],
        "disposition_reason": row["disposition_reason"],
    })


def evaluation(row):
    return _common(row, {
        "infant_id": row["infant_id"],
        "episode_id": row["episode_id"],
        "facility_id": row["facility_id"],
        "performed_by_provider_id": row["performed_by_provider_id"],
        "attested_by_provider_id": row["attested_by_provider_id"],
        "evaluation_datetime": db.fmt_dt(row["evaluation_datetime"]),
        "method": row["method"],
        "left_ear_threshold_db": row["left_ear_threshold_db"],
        "right_ear_threshold_db": row["right_ear_threshold_db"],
        "outcome": row["outcome"],
        "status": row["status"],
        "finalized_at": db.fmt_dt(row["finalized_at"]),
        "age_days_at_finalize": row["age_days_at_finalize"],
        "timeliness_status": row["timeliness_status"],
        "timeliness_status_chronological_basis":
            row["timeliness_status_chronological_basis"],
        "attestation_note": row["attestation_note"],
    })


def referral(row):
    return _common(row, {
        "infant_id": row["infant_id"],
        "diagnostic_evaluation_id": row["diagnostic_evaluation_id"],
        "ei_program_facility_id": row["ei_program_facility_id"],
        "status": row["status"],
        "referred_at": db.fmt_dt(row["referred_at"]),
        "accepted_at": db.fmt_dt(row["accepted_at"]),
        "ifsp_date": db.fmt_dt(row["ifsp_date"]),
        "enrollment_age_days": row["enrollment_age_days"],
        "ei_timeliness_status": row["ei_timeliness_status"],
        "resolution_reason": row["resolution_reason"],
    })


def risk_entry(row):
    return _common(row, {
        "infant_id": row["infant_id"],
        "risk_factor_code": row["risk_factor_code"],
        "identified_at": db.fmt_dt(row["identified_at"]),
        "source": row["source"],
        "surveillance_due_date": db.fmt_dt(row["surveillance_due_date"]),
        "status": row["status"],
        "surveillance_result": row["surveillance_result"],
        "surveillance_recorded_at": db.fmt_dt(row["surveillance_recorded_at"]),
    })


def task(row):
    return _common(row, {
        "infant_id": row["infant_id"],
        "episode_id": row["episode_id"],
        "funding_facility_id": row["funding_facility_id"],
        "assigned_provider_id": row["assigned_provider_id"],
        "task_type": row["task_type"],
        "visit_starts_at": db.fmt_dt(row["visit_starts_at"]),
        "visit_ends_at": db.fmt_dt(row["visit_ends_at"]),
        "units_reserved": row["units_reserved"],
        "budget_shortfall_flag": row["budget_shortfall_flag"],
        "status": row["status"],
        "outcome": row["outcome"],
        "contacted_language": row["contacted_language"],
        "closure_note": row["closure_note"],
    })


def period(row):
    return _common(row, {
        "period_start": db.fmt_dt(row["period_start"]),
        "period_end": db.fmt_dt(row["period_end"]),
        "submission_due_datetime": db.fmt_dt(row["submission_due_datetime"]),
        "status": row["status"],
        "closed_at": db.fmt_dt(row["closed_at"]),
        "facilities_assessed_count": row["facilities_assessed_count"],
        "episodes_escalated_count": row["episodes_escalated_count"],
        "episodes_lost_count": row["episodes_lost_count"],
    })


def report(row):
    return _common(row, {
        "facility_id": row["facility_id"],
        "reporting_period_id": row["reporting_period_id"],
        "supersedes_report_id": row["supersedes_report_id"],
        "attested_screened_count": row["attested_screened_count"],
        "attested_refer_count": row["attested_refer_count"],
        "actual_screened_count": row["actual_screened_count"],
        "actual_refer_count": row["actual_refer_count"],
        "variance_case_count": row["variance_case_count"],
        "submitted_at": db.fmt_dt(row["submitted_at"]),
        "submitted_late": row["submitted_late"],
        "auto_generated": row["auto_generated"],
        "status": row["status"],
        "accepted_by_user_id": row["accepted_by_user_id"],
        "review_note": row["review_note"],
        "assessed_penalty_points": row["assessed_penalty_points"],
        "waiver_reason": row["waiver_reason"],
    })
