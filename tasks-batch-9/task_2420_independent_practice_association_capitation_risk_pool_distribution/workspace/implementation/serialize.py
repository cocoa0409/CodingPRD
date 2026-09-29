"""Explicit per-entity output projections (scaffold 1.1 field names)."""

import db

AGREEMENT_FIELDS = [
    "id", "payer_name", "payer_tax_id", "delegation_scope", "base_pmpm_cents",
    "reconciliation_method", "ibnr_method", "ibnr_completion_factor_bps",
    "target_claims_pmpm_cents", "professional_pool_share_bps",
    "institutional_pool_share_bps", "quality_withhold_bps",
    "stop_loss_attachment_cents", "reinsurance_recovery_bps",
    "continuity_of_care_days", "max_panel_size", "status", "capitation_posture",
    "accrued_capitation_cents", "withheld_balance_cents",
    "forfeited_withhold_cents", "total_assigned_members",
    "created_at", "updated_at", "version",
]

PHYSICIAN_FIELDS = [
    "id", "agreement_id", "npi", "full_name", "specialty", "credential_status",
    "panel_status", "panel_size", "exit_notice_at", "continuity_of_care_until",
    "quality_composite_bps", "latest_scorecard_period",
    "created_at", "updated_at", "version",
]

ENROLLEE_FIELDS = [
    "id", "agreement_id", "external_member_id", "age_band", "benefit_tier",
    "risk_score_bps", "coverage_start_date", "coverage_end_date",
    "assigned_physician_id", "gross_pmpm_cents", "withhold_cents",
    "net_pmpm_cents", "cumulative_paid_claims_cents",
    "created_at", "updated_at", "version",
]

ASSIGNMENT_FIELDS = [
    "id", "enrollee_id", "physician_id", "pending_to_physician_id",
    "effective_date", "term_date", "status", "assignment_source",
    "continuity_of_care_until", "superseded_by_assignment_id",
    "created_at", "updated_at", "version",
]

FILE_FIELDS = [
    "id", "agreement_id", "coverage_month", "payer_file_reference", "received_at",
    "status", "row_count", "matched_row_count", "exception_row_count",
    "claimed_capitation_cents", "created_at", "updated_at", "version",
]

# EnrollmentFileRow carries only id and created_at (PRD 2.4) — no updated_at,
# no version.
ROW_FIELDS = [
    "id", "file_id", "external_member_id", "physician_npi", "row_action",
    "claimed_capitation_cents", "effective_date", "match_status", "created_at",
]

REMITTANCE_FIELDS = [
    "id", "file_id", "coverage_month", "reconciliation_method_used",
    "expected_capitation_cents", "claimed_capitation_cents",
    "retro_adjustment_cents", "variance_cents", "withhold_cents",
    "net_payable_cents", "institutional_allocation_cents",
    "professional_allocation_cents", "member_month_count_bps", "status",
    "created_at", "updated_at", "version",
]

POOL_FIELDS = [
    "id", "agreement_id", "pool_type", "pool_year_start", "pool_year_end",
    "status", "settlement_due_date", "funded_cents", "member_months_bps",
    "paid_claims_cents", "ibnr_reserve_cents", "ibnr_method_used",
    "stop_loss_recovery_cents", "stop_loss_eligible_enrollee_count",
    "loss_ratio_bps", "deficit_flag", "surplus_tier", "raw_surplus_cents",
    "admin_fee_cents", "distributable_surplus_cents", "shared_savings_pool_cents",
    "created_at", "updated_at", "version",
]

CLAIM_FIELDS = [
    "id", "agreement_id", "enrollee_id", "attributed_physician_id", "pool_id",
    "pool_type", "downstream_provider_name", "billed_cents", "service_date",
    "received_date", "allowed_cents", "paid_cents", "status", "denial_reason",
    "appeal_count", "created_at", "updated_at", "version",
]

RECOVERY_FIELDS = [
    "id", "pool_id", "enrollee_id", "attachment_cents", "eligible_paid_cents",
    "excess_cents", "recovery_cents", "status", "submitted_by_user_id",
    "adjudicated_by_user_id", "denial_reason",
    "created_at", "updated_at", "version",
]

SCORECARD_FIELDS = [
    "id", "physician_id", "measurement_period", "hedis_composite_bps",
    "access_score_bps", "patient_experience_bps", "attributed_member_months",
    "composite_score_bps", "withhold_release_bps", "status",
    "created_at", "updated_at", "version",
]

DISTRIBUTION_FIELDS = [
    "id", "pool_id", "physician_id", "composite_score_bps_snapshot",
    "withhold_release_bps_snapshot", "panel_member_months_bps",
    "withhold_share_cents", "withhold_release_cents", "shared_savings_cents",
    "net_distribution_cents", "status", "created_at", "updated_at", "version",
]


def _render(value):
    if isinstance(value, db.Instant):
        return value.render()
    return value


def project(entity, fields):
    return {name: _render(entity.get(name)) for name in fields}


def agreement(entity):
    return project(entity, AGREEMENT_FIELDS)


def physician(entity):
    return project(entity, PHYSICIAN_FIELDS)


def enrollee(entity):
    return project(entity, ENROLLEE_FIELDS)


def assignment(entity):
    return project(entity, ASSIGNMENT_FIELDS)


def enrollment_file(entity):
    return project(entity, FILE_FIELDS)


def row(entity):
    return project(entity, ROW_FIELDS)


def remittance(entity):
    return project(entity, REMITTANCE_FIELDS)


def pool(entity):
    return project(entity, POOL_FIELDS)


def claim(entity):
    return project(entity, CLAIM_FIELDS)


def recovery(entity):
    return project(entity, RECOVERY_FIELDS)


def scorecard(entity):
    return project(entity, SCORECARD_FIELDS)


def distribution(entity):
    return project(entity, DISTRIBUTION_FIELDS)
