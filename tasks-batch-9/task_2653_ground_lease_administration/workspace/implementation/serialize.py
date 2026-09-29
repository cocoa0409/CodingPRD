"""Response serialisation.  One projection per entity, field order as declared."""

import datetime

from store import iso

AUDIT = ("id", "created_at", "updated_at", "version")

DATETIME_FIELDS = {
    "created_at", "updated_at",
    "commencement_date", "expiration_date", "next_revaluation_date",
    "insurance_expires_at", "mortgagee_notified_at",
    "new_lease_election_deadline", "valuation_date", "hearing_date",
    "period_start", "period_end",
    "construction_window_start", "construction_window_end",
    "term_start", "term_end", "served_at", "lessee_cure_deadline",
    "mortgagee_cure_deadline", "occurred_at", "issued_at",
}

LESSEE_FIELDS = ("legal_name", "notice_email", "credit_rating_code")

LEASE_FIELDS = (
    "lessee_id", "predecessor_lease_id", "origin_mortgage_id", "premises_code",
    "commencement_date", "expiration_date", "lease_status", "rent_status",
    "initial_annual_base_rent_cents", "current_annual_base_rent_cents",
    "revaluation_interval_years", "next_revaluation_date",
    "reval_collar_min_uplift_bps", "reval_collar_max_uplift_bps",
    "percentage_rent_rate_bps", "percentage_rent_breakpoint_cents",
    "percentage_rent_sublease_base_cents", "arrears_balance_cents",
    "permitted_use_code", "total_permitted_gfa_sqft", "gfa_allocated_sqft",
    "gfa_unallocated_sqft", "improvements_value_cents",
    "reversion_land_value_cents", "reversion_standard_code",
    "security_deposit_cents", "deposit_held_cents", "deposit_applied_cents",
    "deposit_refunded_cents", "insurance_status",
    "property_all_risk_limit_cents", "builders_risk_limit_cents",
    "lessor_additional_insured", "insurance_expires_at",
)

MORTGAGE_FIELDS = (
    "lease_id", "mortgagee_legal_name", "notice_email",
    "original_principal_cents", "outstanding_principal_cents",
    "priority_rank", "cure_extension_days", "status",
    "mortgagee_notified_at", "new_lease_election_deadline",
)

REVALUATION_FIELDS = (
    "lease_id", "valuation_date", "status", "round_number",
    "prior_annual_base_rent_cents", "lessor_appraised_rent_cents",
    "lessee_appraised_rent_cents", "divergence_bps", "resolution_method",
    "resolved_annual_base_rent_cents",
)

APPRAISAL_FIELDS = (
    "revaluation_id", "appointed_by", "appraiser_user_id",
    "appraised_annual_rent_cents", "valuation_method_code", "round_number",
)

ARBITRATION_FIELDS = (
    "revaluation_id", "arbitrator_user_id", "hearing_date", "status",
    "independent_annual_rent_cents", "awarded_annual_rent_cents",
    "award_basis",
)

STATEMENT_FIELDS = (
    "lease_id", "period_start", "period_end", "reported_gross_sales_cents",
    "audited_gross_sales_cents", "status", "included_sublease_rent_cents",
    "gross_percentage_rent_cents", "base_rent_offset_credit_cents",
    "amount_due_cents", "underreport_penalty_cents", "assessment_variant",
)

ALTERATION_FIELDS = (
    "lease_id", "scope_code", "proposed_use_code", "requested_gfa_sqft",
    "construction_window_start", "construction_window_end",
    "estimated_cost_cents", "status", "decided_by_user_id",
)

TRANSFER_FIELDS = (
    "lease_id", "parent_transfer_id", "transfer_type",
    "transferee_legal_name", "transferee_lessee_id",
    "transferee_credit_rating_code", "premises_unit_code", "term_start",
    "term_end", "annual_sublease_rent_cents", "sublet_area_sqft",
    "net_consideration_cents", "consent_deposit_cents", "submitted_late",
    "tier_depth", "allocable_base_rent_cents", "transfer_fee_gross_cents",
    "admin_charge_cents", "late_surcharge_cents", "total_transfer_fee_cents",
    "transfer_fee_paid_cents", "status",
)

NOTICE_FIELDS = (
    "lease_id", "default_type", "claimed_amount_cents", "served_at",
    "served_by_user_id", "mortgagee_notified_at", "lessee_cure_deadline",
    "mortgagee_cure_deadline", "status", "cured_by", "terminated_by_user_id",
)

LOSS_FIELDS = (
    "lease_id", "event_type", "scope_code", "occurred_at",
    "damage_estimate_cents", "damaged_area_sqft", "distributable_pool_cents",
    "allocation_method", "status", "rent_abatement_bps",
    "allocated_arrears_cents", "allocated_mortgagee_cents",
    "allocated_lessee_cents", "allocated_lessor_cents", "lessee_share_bps",
    "allocation_detail",
)

ASSESSMENT_FIELDS = (
    "lease_id", "required_standard_code", "structural_condition_score",
    "envelope_condition_score", "systems_condition_score",
    "inspected_by_user_id", "weighted_score_bps", "deficiency_bps",
    "holdback_cents", "deposit_released_cents", "status",
)

CERTIFICATE_FIELDS = (
    "lease_id", "requested_by_mortgage_id", "certified_annual_base_rent_cents",
    "certified_arrears_cents", "certified_rent_status",
    "certified_lease_version", "status", "issued_at", "issued_by_user_id",
)


def _value(field, raw):
    if isinstance(raw, datetime.datetime):
        return iso(raw)
    if field in DATETIME_FIELDS and raw is not None and not isinstance(raw, str):
        return iso(raw)
    if field == "allocation_detail":
        return [dict(entry) for entry in (raw or [])]
    return raw


def _project(record, fields, audit=AUDIT):
    if record is None:
        return None
    out = {}
    for field in audit:
        out[field] = _value(field, record.get(field))
    for field in fields:
        out[field] = _value(field, record.get(field))
    return out


def lessee(record):
    return _project(record, LESSEE_FIELDS)


def lease(record):
    return _project(record, LEASE_FIELDS)


def mortgage(record):
    return _project(record, MORTGAGE_FIELDS)


def revaluation(record):
    return _project(record, REVALUATION_FIELDS)


def appraisal(record):
    # Immutable once lodged: only id and created_at, no updated_at, no version.
    return _project(record, APPRAISAL_FIELDS, audit=("id", "created_at"))


def arbitration(record):
    return _project(record, ARBITRATION_FIELDS)


def statement(record):
    return _project(record, STATEMENT_FIELDS)


def alteration(record):
    return _project(record, ALTERATION_FIELDS)


def transfer(record):
    return _project(record, TRANSFER_FIELDS)


def notice(record):
    return _project(record, NOTICE_FIELDS)


def loss_event(record):
    return _project(record, LOSS_FIELDS)


def assessment(record):
    return _project(record, ASSESSMENT_FIELDS)


def certificate(record):
    return _project(record, CERTIFICATE_FIELDS)
