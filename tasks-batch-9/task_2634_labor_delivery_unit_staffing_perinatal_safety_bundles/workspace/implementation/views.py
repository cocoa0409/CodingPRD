"""Record -> JSON projection. One field list per entity, from SCAFFOLD 1.1."""

import datetime

import clock

FIELDS = {
    "units": ("unit_name", "licensed_ldr_beds", "licensed_or_rooms",
              "max_daily_induction_bed_minutes", "staffing_posture",
              "coverage_deficit_units", "cesarean_readiness_state",
              "readiness_reason", "current_drill_id", "current_drill_expires_at",
              "mean_d2i_minutes",
              "escalation_breach_count", "bundle_breach_count",
              "turnover_buffer_minutes", "committed_bed_minutes_by_day",
              "held_bed_minutes_by_day", "last_capacity_sweep_at"),
    "staff": ("unit_id", "full_name", "staff_role", "fetal_monitoring_cert_level",
              "credential_expires_at", "or_circulating_qualified",
              "employment_status", "last_validated_drill_at",
              "drill_currency_state", "capacity_units"),
    "shifts": ("unit_id", "staff_id", "role_slot", "shift_start_utc",
               "shift_end_utc", "status", "capacity_units_effective",
               "assigned_acuity_load_units", "relieved_by_shift_id"),
    "beds": ("unit_id", "bed_label", "bed_type", "status", "current_encounter_id",
             "held_booking_id", "turnover_clear_at"),
    "encounters": ("unit_id", "bed_id", "source_booking_id", "patient_record_code",
                   "labor_phase", "staffing_state", "parity", "prior_cesarean",
                   "gestational_age_weeks", "fetus_count", "presentation",
                   "is_ntsv", "acuity_tier", "one_to_one_required",
                   "required_coverage_units", "assigned_coverage_units",
                   "magnesium_infusion_active", "delivery_mode",
                   "episiotomy_performed", "admitted_at", "delivery_recorded_at",
                   "review_required"),
    "care": ("encounter_id", "shift_assignment_id", "staff_id", "coverage_mode",
             "acuity_units_consumed", "status", "released_at",
             "superseded_by_assignment_id"),
    "bookings": ("unit_id", "bed_id", "encounter_id", "patient_record_code",
                 "gestational_age_weeks", "indication_code", "priority_class",
                 "requested_start_utc", "expected_labor_minutes",
                 "projected_occupancy_minutes", "hold_expires_at", "status",
                 "bump_count"),
    "activations": ("encounter_id", "unit_id", "bundle_type", "activation_trigger",
                    "quantitative_blood_loss_ml", "systolic_mmhg", "diastolic_mmhg",
                    "activated_at", "status", "highest_stage_reached",
                    "on_time_step_count", "late_step_count", "missed_step_count",
                    "timeliness_score", "sequence_adjusted_score", "rescind_reason"),
    "items": ("activation_id", "step_code", "step_sequence", "stage_gate",
              "required_within_minutes", "due_at_activation_anchored",
              "due_at_sequence_anchored", "status", "completed_at",
              "performed_by_staff_id", "minutes_from_activation"),
    "assessments": ("encounter_id", "interpreted_by_staff_id",
                    "supersedes_assessment_id", "assessed_at", "category",
                    "baseline_rate_bpm", "variability", "recurrent_decelerations",
                    "escalation_status", "escalation_tier_high_water",
                    "escalation_due_at", "next_tier_due_at", "reassessment_due_at"),
    "cesareans": ("encounter_id", "or_bed_id", "triggering_assessment_id",
                  "triggering_activation_id", "urgency_class", "decision_at",
                  "incision_at", "delivery_at", "decision_to_incision_minutes",
                  "met_target", "mobilized_staff_ids", "status"),
    "drills": ("unit_id", "drill_type", "scheduled_for_utc",
               "participant_staff_ids", "decision_at", "incision_at",
               "measured_d2i_minutes", "status", "validated_at",
               "validated_by_user_id", "documented_by_staff_id", "expires_at",
               "invalidation_reason", "revision_count"),
    "reviews": ("encounter_id", "complication_code", "facilitator_staff_id",
                "opened_at", "debrief_due_at", "debrief_scheduled_for_utc",
                "debrief_held_at", "findings_summary", "contributing_factor_codes",
                "status", "rework_count", "closed_by_user_id"),
    "passes": ("encounter_id", "person_name", "credential_type",
               "doula_certification_expires_at", "or_credentialed", "status",
               "checked_in_at", "checked_out_at", "valid_until", "reentry_count"),
    "snapshots": ("unit_id", "period_start_utc", "period_end_utc",
                  "attribution_basis", "ntsv_cesarean_numerator",
                  "ntsv_cesarean_denominator", "ntsv_cesarean_rate_pct",
                  "episiotomy_numerator", "episiotomy_denominator",
                  "episiotomy_rate_pct", "shadow_ntsv_rate_pct",
                  "composite_quality_index", "status", "certified_at",
                  "certified_by_user_id", "superseded_by_snapshot_id"),
}


def scalar(value):
    if isinstance(value, datetime.datetime):
        return clock.fmt_dt(value)
    if isinstance(value, list):
        return [scalar(v) for v in value]
    if isinstance(value, dict):
        return {k: scalar(v) for k, v in value.items()}
    return value


def dump(kind, rec):
    if rec is None:
        return None
    out = {"id": rec["id"]}
    for field in FIELDS[kind]:
        out[field] = scalar(rec.get(field))
    out["created_at"] = clock.fmt_dt(rec["created_at"])
    out["updated_at"] = clock.fmt_dt(rec["updated_at"])
    out["version"] = rec["version"]
    return out


def dump_all(kind, records):
    return [dump(kind, rec) for rec in records]
