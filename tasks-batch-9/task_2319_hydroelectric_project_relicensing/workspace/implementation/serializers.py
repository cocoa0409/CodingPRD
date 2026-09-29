"""Per-entity response projections (SCAFFOLD 1.1 field tables)."""
from decimal import Decimal

COMMON = ["id", "created_at", "updated_at", "version"]

PROJECT_FIELDS = [
    "id",
    "license_number",
    "project_name",
    "installed_capacity_mw",
    "base_annual_generation_mwh",
    "license_expiration_date",
    "infeasibility_waiver_granted",
    "stage",
    "pad_filed_at",
    "pad_year",
    "application_filed_at",
    "timeline_posture",
    "regulatory_posture",
    "total_pme_annual_cost_usd",
    "total_generation_loss_mwh",
    "administrative_annual_charge_usd",
    "total_annual_burden_usd",
    "burden_ratio_pct",
    "economically_infeasible",
    "wqc_status",
    "unresolved_mandatory_comment_count",
    "open_deficiency_count",
    "compliance_flag_count",
    "last_sweep_at",
    "created_at",
    "updated_at",
    "version",
]

DAM_FIELDS = [
    "id",
    "project_id",
    "dam_code",
    "hazard_class",
    "inspection_interval_months",
    "eap_exercise_required",
    "max_concurrent_field_activities",
    "created_at",
    "updated_at",
    "version",
]

SITE_FIELDS = [
    "id",
    "project_id",
    "site_code",
    "river_mile",
    "min_rest_buffer_days",
    "cultural_sensitivity",
    "created_at",
    "updated_at",
    "version",
]

PLAN_FIELDS = [
    "id",
    "project_id",
    "plan_title",
    "status",
    "revision_round",
    "submitted_at",
    "approved_at",
    "open_comment_count",
    "unresolved_mandatory_comment_count",
    "attached_study_count",
    "created_at",
    "updated_at",
    "version",
]

STUDY_FIELDS = [
    "id",
    "study_plan_id",
    "site_id",
    "resource_category",
    "study_title",
    "fieldwork_window_start",
    "fieldwork_window_end",
    "cultural_clearance_reference",
    "fieldwork_status",
    "review_status",
    "additional_round_count",
    "report_submitted_at",
    "report_submitted_by_user_id",
    "created_at",
    "updated_at",
    "version",
]

COMMENT_FIELDS = [
    "id",
    "study_plan_id",
    "party_id",
    "resource_category",
    "comment_text",
    "is_mandatory_condition",
    "resolution_status",
    "disposition",
    "resolved_at",
    "reopen_count",
    "created_at",
]

PARTY_FIELDS = [
    "id",
    "project_id",
    "party_name",
    "party_type",
    "has_conditioning_authority",
    "vote_weight",
    "contact_user_id",
    "created_at",
    "updated_at",
    "version",
]

SETTLEMENT_FIELDS = [
    "id",
    "project_id",
    "title",
    "status",
    "round_number",
    "circulated_at",
    "executed_at",
    "withdrawn_at",
    "support_pct",
    "total_vote_weight",
    "included_measure_count",
    "created_at",
    "updated_at",
    "version",
]

SIGNATURE_FIELDS = [
    "id",
    "settlement_id",
    "party_id",
    "round_number",
    "position",
    "share_pct",
    "signed_at",
    "created_at",
]

WQC_FIELDS = [
    "id",
    "project_id",
    "certifying_agency_name",
    "status",
    "requested_at",
    "statutory_waiver_date",
    "decided_at",
    "condition_count",
    "denial_reason",
    "created_at",
    "updated_at",
    "version",
]

MEASURE_FIELDS = [
    "id",
    "project_id",
    "settlement_id",
    "prerequisite_measure_id",
    "measure_name",
    "resource_category",
    "source",
    "status",
    "capital_cost_usd",
    "annual_om_cost_usd",
    "construction_start_year",
    "implementation_months",
    "flow_release_cfs",
    "gross_head_ft",
    "release_days",
    "cost_estimate_variant",
    "escalated_capital_usd",
    "annualized_capital_usd",
    "annual_cost_usd",
    "annual_generation_loss_mwh",
    "annual_generation_value_usd",
    "annual_burden_usd",
    "created_by_user_id",
    "definitive_estimate_by_user_id",
    "created_at",
    "updated_at",
    "version",
]

APPLICATION_FIELDS = [
    "id",
    "project_id",
    "amends_order_id",
    "application_type",
    "filing_status",
    "ea_stage",
    "filed_at",
    "pinned_study_plan_id",
    "pinned_study_plan_version",
    "pinned_settlement_id",
    "pinned_settlement_version",
    "pinned_measure_ids",
    "pinned_total_annual_burden_usd",
    "deficiency_count",
    "last_deficiency_note",
    "created_at",
    "updated_at",
    "version",
]

ORDER_FIELDS = [
    "id",
    "application_id",
    "order_number",
    "effective_date",
    "compliance_state",
    "amendment_pending",
    "article_count",
    "open_violation_count",
    "last_report_basis",
    "last_report_period_year",
    "assessed_obligation_count",
    "noncompliant_obligation_count",
    "compliance_score",
    "last_report_filed_at",
    "created_at",
    "updated_at",
    "version",
]

OBLIGATION_FIELDS = [
    "id",
    "order_id",
    "pme_measure_id",
    "dam_id",
    "obligation_type",
    "due_date",
    "status",
    "activity_window_start",
    "activity_window_end",
    "certified_at",
    "certified_by_user_id",
    "overdue_marked_at",
    "created_at",
    "updated_at",
    "version",
]


def _clean(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def _project(row, fields):
    return {name: _clean(row.get(name)) for name in fields}


def project(row):
    return _project(row, PROJECT_FIELDS)


def dam(row):
    return _project(row, DAM_FIELDS)


def site(row):
    return _project(row, SITE_FIELDS)


def plan(row):
    return _project(row, PLAN_FIELDS)


def study(row):
    return _project(row, STUDY_FIELDS)


def comment(row):
    return _project(row, COMMENT_FIELDS)


def party(row):
    return _project(row, PARTY_FIELDS)


def settlement(row):
    return _project(row, SETTLEMENT_FIELDS)


def signature(row):
    return _project(row, SIGNATURE_FIELDS)


def wqc(row):
    return _project(row, WQC_FIELDS)


def measure(row):
    return _project(row, MEASURE_FIELDS)


def application(row):
    return _project(row, APPLICATION_FIELDS)


def order(row):
    return _project(row, ORDER_FIELDS)


def obligation(row):
    return _project(row, OBLIGATION_FIELDS)
