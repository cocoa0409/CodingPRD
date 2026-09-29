"""Entity serializers (SCAFFOLD 1.1 field sets).

Datetime values are rendered as ISO-8601 UTC with exactly three fractional
digits. Internal bookkeeping keys (prefixed with '_') never leave the server.
"""
from datetime import datetime

from clock import iso

PROPERTY_FIELDS = [
    "id", "parcel_id", "address", "situs_ward", "lot_area_sqft",
    "assessed_value_cents", "structure_present", "structure_condition_grade",
    "vacancy_months", "nuisance_complaint_count", "open_code_violation_count",
    "delinquent_tax_balance_cents", "pre_acquisition_delinquency_cents",
    "custody_status", "title_status", "acquisition_channel", "acquired_at",
    "acquisition_cost_cents", "intake_blight_score", "current_blight_score",
    "secured", "last_mow_at", "demolished_at", "owner_of_record_applicant_id",
    "listed_at", "created_at", "updated_at", "version",
]

FUNDING_SOURCE_FIELDS = [
    "id", "name", "source_type", "authorized_cents", "restriction",
    "expires_on", "committed_cents", "disbursed_cents", "available_cents",
    "reserve_floor_cents", "open_run_count", "status", "recaptured_cents",
    "created_at", "updated_at", "version",
]

PACKET_FIELDS = [
    "id", "property_id", "funding_source_id", "channel", "offer_price_cents",
    "title_search_fee_cents", "foreclosure_case_no", "donor_name", "status",
    "committed_cents", "initiated_by_user_id", "closed_by_user_id",
    "resolution_no", "deed_reference", "declined_reason", "hold_reason",
    "created_at", "updated_at", "version",
]

TITLE_ACTION_FIELDS = [
    "id", "property_id", "action_type", "round_no", "filed_at", "defect_count",
    "status", "adjudicated_at", "created_at", "updated_at", "version",
]

CONTRACTOR_FIELDS = [
    "id", "name", "license_expires_on", "max_concurrent_crews", "specialties",
    "debarred", "created_at", "updated_at", "version",
]

ORDER_FIELDS = [
    "id", "property_id", "contractor_id", "funding_source_id",
    "demolition_run_id", "work_type", "window_start", "window_end",
    "openings_count", "estimated_cost_cents", "actual_cost_cents", "status",
    "completed_at", "cancelled_reason", "created_at", "updated_at", "version",
]

RUN_FIELDS = [
    "id", "funding_source_id", "run_sequence", "budget_cents",
    "situs_ward_filter", "provisional_cap_cents", "selected_property_ids",
    "skipped_property_ids", "properties_selected_count",
    "skipped_property_count", "committed_subtotal_cents", "admin_fee_cents",
    "total_committed_cents", "dropped_property_ids", "orders_created_count",
    "status", "executed_at", "created_at", "updated_at", "version",
]

APPLICANT_FIELDS = [
    "id", "legal_name", "applicant_type", "contact_email",
    "nonprofit_registration_no", "reverter_count", "last_reverter_at",
    "good_standing_count", "delinquent_tax_total_cents",
    "open_code_violation_total", "recent_reverter_count",
    "conveyed_property_count", "eligibility_status", "created_at",
    "updated_at", "version",
]

ADJACENCY_FIELDS = [
    "id", "property_id", "adjacent_property_id", "shared_boundary_feet",
    "recorded_by_user_id", "created_at",
]

HEARING_FIELDS = [
    "id", "property_id", "hearing_at", "comment_count", "support_count",
    "support_ratio", "summary", "created_at",
]

APPLICATION_FIELDS = [
    "id", "property_id", "applicant_id", "program", "proposed_use",
    "offer_price_cents", "quoted_price_cents", "status", "revision_round",
    "submitted_at", "screening_count", "suspended_from_status",
    "recommended_by_user_id", "recommendation_memo", "decided_by_user_id",
    "board_decision_at", "denial_reason", "created_at", "updated_at",
    "version",
]

SCREENING_FIELDS = [
    "id", "application_id", "sequence_no", "screened_by_user_id",
    "screened_at", "delinquent_tax_total_cents", "open_code_violation_total",
    "recent_reverter_count", "disqualifiers", "eligibility_score", "outcome",
    "created_at",
]

AGREEMENT_FIELDS = [
    "id", "application_id", "property_id", "performance_deadline",
    "cure_deadline", "milestone_count", "milestones_completed",
    "reverter_clause_active", "abatement_years", "discharge_mode",
    "projected_improved_value_cents", "sale_price_cents",
    "discharged_tax_cents", "abatement_annual_cents", "abatement_total_cents",
    "status", "executed_at", "complied_at", "reverted_at", "created_at",
    "updated_at", "version",
]


def _value(value):
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, list):
        return [_value(item) for item in value]
    return value


def _serialize(record, fields):
    return {field: _value(record.get(field)) for field in fields}


def property_out(record):
    return _serialize(record, PROPERTY_FIELDS)


def funding_source_out(record):
    return _serialize(record, FUNDING_SOURCE_FIELDS)


def packet_out(record):
    return _serialize(record, PACKET_FIELDS)


def title_action_out(record):
    return _serialize(record, TITLE_ACTION_FIELDS)


def contractor_out(record):
    return _serialize(record, CONTRACTOR_FIELDS)


def order_out(record):
    return _serialize(record, ORDER_FIELDS)


def run_out(record):
    return _serialize(record, RUN_FIELDS)


def applicant_out(record):
    return _serialize(record, APPLICANT_FIELDS)


def adjacency_out(record):
    return _serialize(record, ADJACENCY_FIELDS)


def hearing_out(record):
    return _serialize(record, HEARING_FIELDS)


def application_out(record):
    return _serialize(record, APPLICATION_FIELDS)


def screening_out(record):
    return _serialize(record, SCREENING_FIELDS)


def agreement_out(record):
    return _serialize(record, AGREEMENT_FIELDS)
