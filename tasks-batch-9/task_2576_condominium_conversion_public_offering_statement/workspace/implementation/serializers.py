"""Record -> JSON projection.  Every entity exposes exactly the fields the
scaffold declares for it plus the four common properties of PRD 2.5."""

from datetime import datetime
from decimal import Decimal

import clock

FIELDS = {
    "ConversionProject": [
        "building_address", "year_built", "total_unit_count",
        "sponsor_user_id", "max_overlapping_remediations", "status", "posture",
        "suitability_gate", "suitability_score", "included_unit_count",
        "escrow_deposits_received_cents", "escrow_balance_cents",
        "escrow_refunded_cents", "escrow_disbursed_cents",
        "relocation_obligation_accrued_cents", "relocation_paid_cents",
        "relocation_reversed_cents", "warranty_reserve_charge_cents",
        "relocation_outstanding_cents", "escrow_reconciliation_delta_cents",
        "relocation_reconciliation_delta_cents", "bp_conservation_total",
        "warrantability_verdict", "warrantability_verdict_closed_basis",
        "owner_occupancy_pct_contract_basis",
        "investor_concentration_pct_contract_basis",
        "owner_occupancy_pct_closed_basis",
        "investor_concentration_pct_closed_basis", "single_investor_max_pct",
        "presale_sold_pct", "declaration_recorded_at", "warranty_start_at",
        "last_posture_recalculated_at",
    ],
    "EngineeringReport": [
        "conversion_project_id", "report_label", "inspection_date",
        "submitted_by_user_id", "reviewed_by_user_id", "status",
        "revision_round", "verified_component_count",
        "total_replacement_cost_cents",
    ],
    "MajorComponent": [
        "engineering_report_id", "component_type",
        "remaining_useful_life_years", "effective_age_years",
        "replacement_cost_cents", "funded_pct_bp", "condition_rating",
        "planned_remediation_gain_years", "is_life_safety", "is_structural",
        "verification_status",
    ],
    "SuitabilityAssessment": [
        "engineering_report_id", "conversion_project_id", "variant", "score",
        "basis", "critical_cap_applied", "verdict", "status",
    ],
    "DeclarationPackage": [
        "conversion_project_id", "declaration_text_ref", "bylaws_text_ref",
        "plat_revision", "boundary_convention", "status", "recorded_at",
        "allocated_bp_total",
    ],
    "Unit": [
        "declaration_package_id", "conversion_project_id", "unit_number",
        "floor_level", "heated_square_feet", "boundary_note",
        "base_percentage_interest_bp", "percentage_interest_bp",
        "unit_annual_assessment_cents", "unit_monthly_assessment_cents",
        "declaration_status", "sale_status", "withdrawal_reason",
    ],
    "PublicOfferingStatement": [
        "conversion_project_id", "declaration_package_id", "reserve_study_id",
        "initial_budget_id", "status", "effective_at", "amendment_count",
        "last_material_amendment_at", "complete_section_count",
    ],
    "POSSection": [
        "public_offering_statement_id", "section_code", "body_ref",
        "word_count", "content_status", "attested_by_user_id",
        "last_attested_at",
    ],
    "TenantHousehold": [
        "conversion_project_id", "occupied_unit_id", "household_label",
        "tenancy_start_date", "monthly_rent_cents", "protected_class",
        "notice_status", "rofr_status", "relocation_status", "notice_served_at",
        "notice_period_days", "vacate_deadline_at", "rofr_expires_at",
        "relocation_assistance_cents", "relocation_paid_cents",
        "relocation_reversed_cents",
    ],
    "ReserveStudy": [
        "conversion_project_id", "engineering_report_id", "method",
        "opening_reserve_balance_cents", "fully_funded_balance_cents",
        "recommended_annual_contribution_cents", "percent_funded_bp",
        "funding_status", "adoption_status",
    ],
    "InitialBudget": [
        "conversion_project_id", "reserve_study_id", "fiscal_year_label",
        "annual_operating_expense_cents", "reserve_contribution_cents",
        "base_expense_cents", "management_fee_bp", "management_fee_cents",
        "total_annual_expense_cents", "assessment_income_cents",
        "developer_deficit_funding_cents", "developer_subsidy_flag", "status",
        "adopted_at",
    ],
    "ClosingBatch": [
        "conversion_project_id", "batch_sequence_no", "window_start_at",
        "window_end_at", "min_presale_threshold_pct", "min_absolute_unit_count",
        "assigned_agreement_count", "qualifying_agreement_count",
        "presale_pct", "status", "released_at", "last_evaluated_at",
    ],
    "PurchaseAgreement": [
        "unit_id", "conversion_project_id", "public_offering_statement_id",
        "closing_batch_id", "tenant_household_id", "purchaser_name",
        "purchaser_tax_id", "purchaser_type", "price_cents", "deposit_cents",
        "signed_at", "pos_delivered_at", "rescission_deadline_at",
        "rescission_restart_count", "contract_status", "escrow_status",
        "closed_at", "rescission_reason",
    ],
    "WarrantyClaim": [
        "conversion_project_id", "major_component_id", "reported_by_unit_id",
        "defect_description", "claimed_cost_cents", "reported_at",
        "warranty_expires_at", "status", "triage_outcome",
        "accrued_charge_cents", "remediation_start_at", "remediation_end_at",
        "reopen_count", "triage_note", "completion_note", "reopen_reason",
    ],
}


def _value(value):
    if isinstance(value, datetime):
        return clock.format_instant(value)
    if isinstance(value, Decimal):
        return float(value)
    return value


def dump(rec):
    out = {"id": rec["id"]}
    for name in FIELDS[rec["_type"]]:
        out[name] = _value(rec.get(name))
    out["created_at"] = clock.format_instant(rec["created_at"])
    out["updated_at"] = clock.format_instant(rec["updated_at"])
    out["version"] = rec["version"]
    return out


def dump_all(records):
    return [dump(r) for r in records]
