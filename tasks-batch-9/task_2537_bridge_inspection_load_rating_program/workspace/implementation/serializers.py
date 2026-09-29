"""Entity field sets and response rendering (SCAFFOLD 1.1 entities).

Records are stored as plain dicts whose keys are exactly the public field names.
Parsed helper values live under keys prefixed with "_" and are never serialized.
"""

from datetime import date, datetime

import calc
import db

COMMON = ("id", "created_at", "updated_at", "version")

# Fields rendered as whole calendar dates rather than instants.
DATE_FIELDS = ("next_inspection_due_date", "next_underwater_due_date")

BRIDGE_FIELDS = COMMON + (
    "nbi_structure_number",
    "name",
    "owner_agency",
    "structure_type",
    "deck_area_sqm",
    "year_built",
    "adt",
    "detour_length_km",
    "spans_water",
    "underwater_elements",
    "fracture_critical",
    "deck_rating",
    "superstructure_rating",
    "substructure_rating",
    "min_nbi_rating",
    "bridge_health_index",
    "inventoried_quantity_total",
    "deficiency_pct",
    "service_posture",
    "scour_status",
    "poa_compliant",
    "inspection_interval_months",
    "underwater_interval_months",
    "last_routine_inspection_date",
    "next_inspection_due_date",
    "last_underwater_inspection_date",
    "next_underwater_due_date",
    "posting_required",
    "posted_limit_tons",
    "operating_rating_tons",
    "inventory_rating_tons",
    "governing_load_rating_id",
    "open_critical_finding_count",
    "initial_deck_rating",
    "initial_superstructure_rating",
    "initial_substructure_rating",
)

PERSONNEL_FIELDS = COMMON + (
    "full_name",
    "agency",
    "nbis_refresher_expiry_date",
    "team_leader_certified",
    "underwater_diver_certified",
    "fracture_critical_certified",
    "load_rating_engineer_licensed",
    "pe_license_number",
    "qualification_status",
)

INSPECTION_FIELDS = COMMON + (
    "bridge_id",
    "inspection_type",
    "team_leader_id",
    "qa_reviewer_id",
    "status",
    "field_window_start",
    "field_window_end",
    "inspection_date",
    "submitted_at",
    "qa_claimed_at",
    "accepted_at",
    "returned_count",
    "qa_escalation_required",
    "element_count",
    "reported_quantity_total",
    "deficient_quantity_total",
    "photo_count_total",
    "quantity_balanced",
    "deck_group_ehi",
    "superstructure_group_ehi",
    "substructure_group_ehi",
    "computed_deck_rating",
    "computed_superstructure_rating",
    "computed_substructure_rating",
    "bridge_health_index",
    "notes",
)

ELEMENT_CONDITION_FIELDS = COMMON + (
    "inspection_id",
    "element_key",
    "element_group",
    "unit",
    "total_quantity",
    "cs1_qty",
    "cs2_qty",
    "cs3_qty",
    "cs4_qty",
    "reported_sum",
    "balanced",
    "deficient_quantity",
    "element_health_index",
    "photo_count",
    "defect_notes",
)

CRITICAL_FINDING_FIELDS = COMMON + (
    "bridge_id",
    "source_inspection_id",
    "element_condition_id",
    "severity",
    "finding_status",
    "notification_status",
    "restriction_action",
    "restriction_authorized_by_id",
    "restriction_imposed_at",
    "notification_due_at",
    "notification_late",
    "description",
    "mitigation_note",
    "resolution_note",
)

NOTIFICATION_LOG_FIELDS = (
    "id",
    "created_at",
    "critical_finding_id",
    "tier",
    "channel",
    "recipient_label",
    "sent_at",
    "late",
)

LOAD_RATING_FIELDS = COMMON + (
    "bridge_id",
    "source_inspection_id",
    "method",
    "rating_vehicle",
    "capacity_c_kn_m",
    "dead_load_dc_kn_m",
    "dead_load_dw_kn_m",
    "live_load_ll_kn_m",
    "impact_im_factor",
    "system_factor_phi_s",
    "resistance_factor_phi",
    "condition_factor_phi_c",
    "rating_factor_operating",
    "rating_factor_inventory",
    "operating_rating_tons",
    "inventory_rating_tons",
    "posting_required",
    "posted_limit_tons",
    "rating_status",
    "sealed_by_id",
    "approved_by_id",
    "rating_effective_date",
    "rejection_note",
)

PERMIT_APPLICATION_FIELDS = COMMON + (
    "permit_number",
    "carrier_name",
    "axle_loads_tons",
    "route_bridge_ids",
    "axle_count",
    "gross_weight_tons",
    "speed_category",
    "status",
    "recommended_decision",
    "governing_analysis_min_rf",
    "decided_at",
    "revoked_at",
    "decision_note",
)

PERMIT_BRIDGE_ANALYSIS_FIELDS = COMMON + (
    "permit_application_id",
    "bridge_id",
    "governing_load_rating_id",
    "sequence_index",
    "permit_live_load_kn_m",
    "permit_impact_factor",
    "rating_factor_permit",
    "analysis_result",
    "result_reason",
)

SCOUR_EVALUATION_FIELDS = COMMON + (
    "bridge_id",
    "evaluated_by_id",
    "evaluation_method",
    "foundation_type",
    "scour_code",
    "observed_scour_depth_m",
    "status",
    "finalized_at",
    "derived_scour_status",
)

PLAN_OF_ACTION_FIELDS = COMMON + (
    "bridge_id",
    "scour_evaluation_id",
    "status",
    "monitoring_frequency_months",
    "closure_trigger_stage_m",
    "countermeasure_type",
    "approved_by_id",
    "revision_count",
    "submitted_at",
    "approved_at",
    "return_note",
)

PROGRAM_CYCLE_FIELDS = COMMON + (
    "fiscal_year",
    "authorized_budget_cents",
    "reserve_pct",
    "ranking_policy",
    "reserve_cents",
    "available_cents",
    "committed_cents",
    "remaining_cents",
    "status",
    "identified_count",
    "programmed_count",
    "deferred_count",
    "unprogrammed_cost_cents",
    "locked_at",
    "submitted_at",
    "closed_at",
)

PROJECT_CANDIDATE_FIELDS = COMMON + (
    "bridge_id",
    "program_cycle_id",
    "source_inspection_id",
    "work_type",
    "estimated_cost_cents",
    "priority_score",
    "ranking_policy_applied",
    "status",
    "origin",
    "programmed_at",
    "withdrawn_at",
    "deferred_at",
    "justification",
)

FEDERAL_SUBMISSION_FIELDS = COMMON + (
    "program_cycle_id",
    "submission_type",
    "status",
    "total_bridge_count",
    "overdue_inspection_count",
    "inspection_compliance_pct",
    "poa_noncompliant_count",
    "open_immediate_finding_count",
    "error_count",
    "submitted_by_user_id",
    "reviewer_user_id",
    "rejection_reason_code",
    "submitted_at",
    "reviewed_at",
)


def _value(field, value):
    if value is None:
        return None
    if field in DATE_FIELDS:
        if isinstance(value, (date, datetime)):
            return db.fmt_date(value)
        return value
    if isinstance(value, datetime):
        return db.fmt_dt(value)
    if isinstance(value, date):
        return db.fmt_date(value)
    return value


def render(record, fields):
    out = {}
    for field in fields:
        out[field] = _value(field, record.get(field))
    return out


def bridge(record):
    return render(record, BRIDGE_FIELDS)


def personnel(record):
    data = render(record, PERSONNEL_FIELDS)
    data["qualification_status"] = calc.qualification_status(
        record.get("_expiry_date"), db.now().date()
    )
    return data


def inspection(record):
    return render(record, INSPECTION_FIELDS)


def element_condition(record):
    return render(record, ELEMENT_CONDITION_FIELDS)


def critical_finding(record):
    data = render(record, CRITICAL_FINDING_FIELDS)
    sticky = bool(record.get("notification_late"))
    if not sticky and record.get("notification_status") == "PENDING":
        sticky = calc.is_late(db.now(), record.get("notification_due_at"))
    data["notification_late"] = sticky
    return data


def notification_log(record):
    return render(record, NOTIFICATION_LOG_FIELDS)


def load_rating(record):
    return render(record, LOAD_RATING_FIELDS)


def permit_application(record):
    return render(record, PERMIT_APPLICATION_FIELDS)


def permit_bridge_analysis(record):
    return render(record, PERMIT_BRIDGE_ANALYSIS_FIELDS)


def scour_evaluation(record):
    return render(record, SCOUR_EVALUATION_FIELDS)


def plan_of_action(record):
    return render(record, PLAN_OF_ACTION_FIELDS)


def program_cycle(record):
    return render(record, PROGRAM_CYCLE_FIELDS)


def project_candidate(record):
    return render(record, PROJECT_CANDIDATE_FIELDS)


def federal_submission(record):
    return render(record, FEDERAL_SUBMISSION_FIELDS)
