"""Row -> JSON projection.  Every entity carries id/created_at/updated_at/version
except BinocularMeasurement, which is an immutable instrument reading and carries
only id and created_at (PRD §2.4)."""

from store import now, parse_instant

_COMMON = ("id", "created_at", "updated_at", "version")


def _pick(row, fields, common=_COMMON):
    out = {}
    for key in common:
        if key in row:
            out[key] = row[key]
    for key in fields:
        out[key] = row.get(key)
    return out


PATIENT_FIELDS = ("full_name", "date_of_birth", "diagnosis_category", "guardian_name",
                  "clinical_status", "discharge_reason", "discharged_at", "discharged_by_user_id")

PAYER_FIELDS = ("name", "payer_type", "allowed_amount_timed_unit", "allowed_amount_flat_session",
                "allowed_amount_evaluation", "coinsurance_rate", "frequency_limit_months")

COVERAGE_FIELDS = ("patient_id", "payer_id", "member_number", "status", "effective_start_date",
                   "effective_end_date", "deductible_total", "deductible_met",
                   "vision_allowance_total", "vision_allowance_used", "vision_allowance_remaining",
                   "last_paid_service_date_therapy", "last_paid_service_date_evaluation")

AUTHORIZATION_FIELDS = ("patient_id", "coverage_id", "auth_number", "visits_authorized",
                        "visits_consumed", "visits_released", "visits_remaining",
                        "window_start_date", "window_end_date", "status",
                        "reauthorization_count", "last_reauthorized_at", "close_reason")

THERAPIST_FIELDS = ("full_name", "credential", "credential_expires_at", "npi")

ROOM_FIELDS = ("name", "equipment_class")

ASSESSMENT_FIELDS = ("patient_id", "plan_id", "performed_by_therapist_id", "signed_by_therapist_id",
                     "assessment_type", "purpose", "encounter_date", "patient_age_years", "status",
                     "amendment_count", "signed_at", "therapy_indicated", "discharge_metric_met",
                     "composite_progress_score", "symptom_improvement_pct",
                     "improvement_delta_points", "plateau_flag", "red_flag_present")

MEASUREMENT_FIELDS = ("assessment_id", "metric_code", "eye", "npc_break_cm", "npc_recovery_cm",
                      "amplitude_d", "vergence_bo_break_pd", "acuity_logmar", "ciss_score",
                      "red_flag", "reference_variant", "expected_min_value", "expected_band_high",
                      "within_reference_band", "diagnostic_flag")

PLAN_FIELDS = ("patient_id", "source_assessment_id", "authorization_id", "status", "progress_state",
               "discharge_criteria_mode", "current_phase_index", "prescribed_home_sessions_per_week",
               "previous_prescribed_home_sessions_per_week", "prescription_changed_at",
               "cumulative_therapy_minutes", "home_compliance_pct", "revision_count",
               "consecutive_low_delta_count", "suspension_reason", "discharge_ready",
               "baseline_npc_break_cm", "baseline_amplitude_d", "baseline_vergence_bo_break_pd",
               "baseline_acuity_logmar", "baseline_ciss_score")

PHASE_FIELDS = ("plan_id", "sequence_index", "name", "required_mastery_count",
                "activities_mastered_count", "status", "started_at", "mastered_at")

SESSION_FIELDS = ("plan_id", "patient_id", "therapist_id", "room_id", "authorization_id",
                  "supervising_optometrist_id", "modality", "scheduled_start_at",
                  "scheduled_end_at", "performed_at", "timed_minutes", "procedure_code",
                  "billable_units", "charge_amount", "weighted_minutes", "schedule_status",
                  "billing_status", "activities_mastered_delta", "cancel_reason", "attested_at",
                  "attestation_statement", "activity_notes")

KIT_ITEM_FIELDS = ("name", "item_class", "replacement_cost", "useful_life_months",
                   "in_service_date", "initial_qty", "on_hand_qty", "on_loan_qty",
                   "dispensed_qty", "retired_qty")

KIT_LOAN_FIELDS = ("kit_item_id", "patient_id", "plan_id", "quantity", "status", "checked_out_at",
                   "due_at", "returned_at", "returned_condition", "damage_fee_amount",
                   "recall_due_at", "recalled_at", "issued_by_user_id")

CLAIM_FIELDS = ("patient_id", "coverage_id", "session_id", "assessment_id", "service_class",
                "service_date", "procedure_code", "units", "billed_amount", "allowed_amount",
                "contractual_adjustment_amount", "deductible_applied_amount", "coinsurance_amount",
                "plan_paid_amount", "patient_responsibility_amount", "denied_amount",
                "adjudication_variant", "status", "appeal_count", "appeal_attempt_log_count",
                "last_appeal_attempt_at", "correction_count", "submitted_by_user_id",
                "denial_reason")

REFERRAL_FIELDS = ("patient_id", "plan_id", "triggering_assessment_id", "direction", "urgency",
                   "referring_provider_name", "target_provider_name", "reason", "status",
                   "sla_due_at", "responded_at", "response_outcome", "decline_reason",
                   "attempt_count", "sla_breached")

OCCLUSION_FIELDS = ("patient_id", "source_assessment_id", "severity", "age_band",
                    "prescribed_daily_hours", "current_daily_hours", "taper_step_count",
                    "logged_days", "adherent_days", "adherence_pct", "baseline_acuity_logmar",
                    "status")


def patient(row):
    return _pick(row, PATIENT_FIELDS)


def payer(row):
    return _pick(row, PAYER_FIELDS)


def coverage(row):
    return _pick(row, COVERAGE_FIELDS)


def authorization(row):
    return _pick(row, AUTHORIZATION_FIELDS)


def therapist(row):
    return _pick(row, THERAPIST_FIELDS)


def room(row):
    return _pick(row, ROOM_FIELDS)


def assessment(row):
    return _pick(row, ASSESSMENT_FIELDS)


def measurement(row):
    return _pick(row, MEASUREMENT_FIELDS, common=("id", "created_at"))


def plan(row):
    return _pick(row, PLAN_FIELDS)


def phase(row):
    return _pick(row, PHASE_FIELDS)


def session(row):
    return _pick(row, SESSION_FIELDS)


def kit_item(row):
    return _pick(row, KIT_ITEM_FIELDS)


def kit_loan(row):
    return _pick(row, KIT_LOAN_FIELDS)


def claim(row):
    return _pick(row, CLAIM_FIELDS)


def referral(row):
    out = _pick(row, REFERRAL_FIELDS)
    # "sla_breached is true when responded_at ends up strictly after sla_due_at,
    #  and also when the logical clock has already passed sla_due_at while the
    #  referral is still sitting in SENT."  The second arm is evaluated live so
    #  that merely reading the row never mutates it.
    if row.get("status") == "SENT" and row.get("sla_due_at"):
        due = parse_instant(row["sla_due_at"])
        out["sla_breached"] = bool(due is not None and now() > due)
    return out


def occlusion(row):
    return _pick(row, OCCLUSION_FIELDS)
