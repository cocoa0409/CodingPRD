"""Entity -> JSON projections.  Field lists come straight from SCAFFOLD entities."""

COMMON = ("id", "created_at", "updated_at", "version")
APPEND_ONLY = ("id", "created_at")

FIELDS = {
    "certificates": (
        "certificate_number", "certificate_type", "permitted_complexity",
        "effective_date", "expiration_date", "status", "suspension_reason",
        "covered_site_count",
    ),
    "sites": (
        "name", "department_code", "complexity_scope", "lab_director_operator_id",
        "oversight_posture", "manual_entry_blocked", "open_deficiency_weight",
        "held_result_count", "total_operator_count", "locked_out_operator_count",
        "lapsed_or_locked_operator_count", "pt_unsuccessful_count",
        "site_qc_compliance_index", "inspection_readiness_score",
        "scope_creep_flag", "last_oversight_run_at",
    ),
    "coverages": (
        "site_id", "certificate_id", "coverage_start", "coverage_end",
        "permitted_complexity_snapshot",
    ),
    "operators": (
        "site_id", "full_name", "role_title", "hire_date", "training_completed_at",
        "training_module_code", "competency_status", "access_status",
        "lockout_reason", "competency_expires_at", "current_grace_days",
        "lapse_deadline", "consecutive_rejection_count",
    ),
    "assessments": (
        "operator_id", "assessor_operator_id", "device_model", "assessment_type",
        "methods_demonstrated", "effective_date", "expires_at", "status",
        "decided_by_user_id", "decision_note",
    ),
    "devices": (
        "site_id", "device_model", "serial_number", "analyte", "complexity_class",
        "connectivity_mode", "qc_frequency_days", "status", "qc_lock_reason",
        "manual_entry_suspended", "last_two_level_qc_pass_on", "qc_next_due_at",
        "use_day_count", "qc_compliance_rate_calendar",
        "qc_compliance_rate_day_of_use", "retirement_reason",
    ),
    "storage_units": (
        "site_id", "name", "min_temp_c", "max_temp_c", "excursion_state",
        "excursion_opened_at", "last_reading_c", "quarantined_lot_count",
    ),
    "temp_readings": (
        "storage_unit_id", "reading_c", "recorded_at", "recorded_by_user_id",
        "disposition", "triggered_excursion",
    ),
    "lots": (
        "site_id", "storage_unit_id", "device_model", "lot_number",
        "expiration_date", "received_at", "control_min_level_1",
        "control_max_level_1", "control_min_level_2", "control_max_level_2",
        "verification_status", "verified_at", "quarantine_reason",
    ),
    "qc_runs": (
        "device_id", "reagent_lot_id", "operator_id", "control_level",
        "measured_value", "performed_at", "expected_min", "expected_max",
        "result", "locked_device",
    ),
    "results": (
        "device_id", "operator_id", "reagent_lot_id", "patient_mrn", "analyte",
        "measured_value", "entry_mode", "manual_entry_reason", "posted_value",
        "posting_status", "posted_by_user_id", "posted_at",
        "held_by_device_lock_at", "correction_count", "correction_reason",
    ),
    "enrollments": (
        "site_id", "analyte", "program_year", "program_provider", "status",
        "graded_event_count", "fail_count_last_three",
    ),
    "pt_events": (
        "enrollment_id", "shipment_number", "due_date", "score_pct", "graded_on",
        "outcome", "status", "root_cause", "corrective_action",
        "investigation_round",
    ),
    "inspections": (
        "site_id", "inspection_type", "scheduled_date", "status", "issued_on",
        "issued_by_user_id", "issued_weight_total", "readiness_score_at_issue",
        "rescind_reason",
    ),
    "findings": (
        "site_id", "inspection_id", "parent_finding_id", "category", "severity",
        "description", "correction_due_date", "weight", "repeat_multiplier",
        "status", "issued_by_user_id", "correction_narrative", "evidence_ref",
        "correction_round", "closed_by_user_id",
    ),
}

# QcRun and TemperatureReading declare common_fields: false — they carry only
# id and created_at.
NO_COMMON = ("qc_runs", "temp_readings")


def dump(table, row):
    out = {"id": row["id"]}
    for name in FIELDS[table]:
        out[name] = row.get(name)
    out["created_at"] = row["created_at"]
    if table not in NO_COMMON:
        out["updated_at"] = row.get("updated_at")
        out["version"] = row.get("version")
    return out


def dump_many(table, items):
    return [dump(table, row) for row in items]
