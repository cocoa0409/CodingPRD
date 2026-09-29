"""Entity serialisation: every declared field is always present, nulls included."""

from datetime import datetime
from decimal import Decimal

from util import iso_ms

COMMON = ("id", "created_at", "updated_at", "version")

FEE_PROGRAM_FIELDS = COMMON + (
    "name",
    "jurisdiction_code",
    "fiscal_year_start_month",
    "statutory_expenditure_deadline_years",
    "notice_min_days",
    "protest_threshold_bp",
    "effective_delay_days",
    "admin_charge_bp",
    "credit_cap_bp",
    "los_policy",
    "discount_rate_bp",
    "max_deferral_days",
    "default_penalty_bp",
    "at_risk_window_days",
    "report_grace_days",
    "effective_fee_study_id",
    "last_report_fiscal_year",
    "last_report_filed_at",
    "last_report_status",
    "last_report_filed_by_user_id",
)

FACILITY_CATEGORY_FIELDS = COMMON + (
    "fee_program_id",
    "code",
    "name",
    "demand_unit_label",
    "existing_los_per_demand_unit",
    "planned_los_per_demand_unit",
    "existing_deficiency_demand_units",
    "unit_cost_cents",
    "fund_posture",
    "fund_balance_cents",
    "refund_due_cents",
    "oldest_unexpended_vintage_at",
    "committed_demand_units",
    "deferred_receivable_cents",
)

FEE_STUDY_FIELDS = COMMON + (
    "fee_program_id",
    "title",
    "methodology",
    "status",
    "revision_round",
    "certified_by_user_id",
    "certified_at",
    "notice_method",
    "notice_days",
    "notice_published_at",
    "protest_window_ends_at",
    "protest_weight_bp",
    "protest_count",
    "adopted_at",
    "adopted_by_user_id",
    "effective_at",
    "activated_at",
    "superseded_by_fee_study_id",
)

NEXUS_COMPONENT_FIELDS = COMMON + (
    "fee_study_id",
    "facility_category_id",
    "horizon_start_year",
    "horizon_end_year",
    "projected_new_dwelling_units",
    "projected_new_nonres_sqft",
    "demand_units_per_dwelling",
    "demand_units_per_1000_nonres_sqft",
    "planned_facility_cost_cents",
    "planned_other_funding_cents",
    "planned_growth_share_bp",
    "planned_capacity_demand_units",
    "existing_tax_credit_per_unit_cents",
    "growth_demand_units",
    "plan_based_cost_per_unit_cents",
    "standard_based_cost_per_unit_cents",
    "adopted_cost_per_unit_cents",
    "nexus_ratio",
    "allocation_status",
    "allocated_at",
)

FEE_SCHEDULE_ITEM_FIELDS = COMMON + (
    "nexus_component_id",
    "land_use_category",
    "unit_basis",
    "conversion_factor",
    "fee_per_unit_cents",
    "schedule_status",
)

PROTEST_FILING_FIELDS = COMMON + (
    "fee_study_id",
    "protester_name",
    "parcel_count",
    "weight_bp",
    "status",
    "filed_at",
)

DEVELOPMENT_APPLICATION_FIELDS = COMMON + (
    "fee_program_id",
    "permit_number",
    "land_use_category",
    "dwelling_units",
    "nonres_sqft",
    "collection_trigger",
    "submitted_by_user_id",
    "pinned_fee_study_id",
    "pinned_fee_study_version",
    "assessment_status",
    "collection_status",
    "reassessment_required",
    "assessed_lines",
    "gross_assessed_cents",
    "credit_applied_cents",
    "admin_charge_cents",
    "net_due_cents",
    "paid_cents",
    "default_penalty_cents",
    "assessed_at",
    "reassessed_at",
    "co_issued_at",
)

CREDIT_CLAIM_FIELDS = COMMON + (
    "development_application_id",
    "facility_category_code",
    "credit_type",
    "valuation_method",
    "improvement_value_cents",
    "annual_tax_contribution_cents",
    "contribution_years",
    "claimed_credit_cents",
    "approved_cents",
    "status",
    "decided_by_user_id",
    "decided_at",
)

DEFERRAL_AGREEMENT_FIELDS = COMMON + (
    "development_application_id",
    "requested_security_type",
    "security_amount_cents",
    "requested_due_at",
    "due_at",
    "status",
    "decided_by_user_id",
    "decided_at",
    "executed_at",
    "satisfied_at",
    "defaulted_at",
)

FUND_LEDGER_ENTRY_FIELDS = COMMON + (
    "facility_category_id",
    "development_application_id",
    "refunded_entry_id",
    "kind",
    "amount_cents",
    "vintage_at",
    "deadline_at",
    "unexpended_cents",
    "entry_status",
    "project_name",
    "authorized_by_user_id",
)


def convert(value):
    if isinstance(value, datetime):
        return iso_ms(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [convert(item) for item in value]
    if isinstance(value, dict):
        return {key: convert(item) for key, item in value.items()}
    return value


def _dump(record, fields):
    return {field: convert(record.get(field)) for field in fields}


def fee_program(record):
    import services.derive as derive

    payload = _dump(record, FEE_PROGRAM_FIELDS)
    effective = derive.effective_study(record["id"])
    payload["effective_fee_study_id"] = effective["id"] if effective else None
    return payload


def facility_category(record):
    return _dump(record, FACILITY_CATEGORY_FIELDS)


def fee_study(record):
    return _dump(record, FEE_STUDY_FIELDS)


def nexus_component(record):
    return _dump(record, NEXUS_COMPONENT_FIELDS)


def fee_schedule_item(record):
    return _dump(record, FEE_SCHEDULE_ITEM_FIELDS)


def protest_filing(record):
    return _dump(record, PROTEST_FILING_FIELDS)


def development_application(record):
    return _dump(record, DEVELOPMENT_APPLICATION_FIELDS)


def credit_claim(record):
    return _dump(record, CREDIT_CLAIM_FIELDS)


def deferral_agreement(record):
    return _dump(record, DEFERRAL_AGREEMENT_FIELDS)


def fund_ledger_entry(record):
    return _dump(record, FUND_LEDGER_ENTRY_FIELDS)
