"""Public projections of every stored entity (PRD section 2.4 field sets)."""

import db

DEALER_FIELDS = (
    "id",
    "legal_name",
    "dba_name",
    "franchise_type",
    "state_code",
    "status",
    "risk_score",
    "risk_rating",
    "audit_frequency_days",
    "next_audit_due_at",
    "open_sot_incident_count",
    "open_sot_exposure_cents",
    "delinquent_unit_count",
    "covenant_breach_count",
    "last_covenant_result",
    "unapplied_credit_cents",
    "audit_in_progress",
    "created_at",
    "updated_at",
    "version",
)

CREDIT_LINE_FIELDS = (
    "id",
    "dealer_id",
    "status",
    "credit_limit_cents",
    "advance_rate_bps_new",
    "advance_rate_bps_used",
    "advance_rate_bps_demonstrator",
    "max_unit_advance_cents_new",
    "max_unit_advance_cents_used",
    "max_unit_advance_cents_demonstrator",
    "class_sublimit_cents_used",
    "class_sublimit_cents_demonstrator",
    "curtailment_grace_days",
    "outstanding_principal_cents",
    "charged_off_principal_cents",
    "available_credit_cents",
    "eligible_collateral_cents",
    "borrowing_base_deficiency_cents",
    "class_outstanding_cents_used",
    "class_outstanding_cents_demonstrator",
    "activated_at",
    "suspension_reason_code",
    "created_at",
    "updated_at",
    "version",
)

CURTAILMENT_TIER_FIELDS = (
    "id",
    "credit_line_id",
    "inventory_class",
    "age_days_from",
    "age_days_to",
    "cumulative_paydown_bps",
    "created_at",
)

UNIT_FIELDS = (
    "id",
    "dealer_id",
    "credit_line_id",
    "vin",
    "inventory_class",
    "invoice_amount_cents",
    "invoice_date",
    "odometer_miles",
    "title_document_type",
    "funding_status",
    "title_custody_status",
    "eligibility_status",
    "ineligibility_reason_code",
    "advance_amount_cents",
    "outstanding_principal_cents",
    "principal_paid_cents",
    "floored_at",
    "funded_by_user_id",
    "aging_exception_count",
    "curtailment_extension_days_total",
    "created_at",
    "updated_at",
    "version",
)

ADVANCE_FIELDS = (
    "id",
    "unit_id",
    "credit_line_id",
    "status",
    "requested_amount_cents",
    "approved_advance_amount_cents",
    "effective_advance_rate_bps",
    "rate_adjustment_codes",
    "invoice_age_days_at_funding",
    "dealer_invoice_reference",
    "disbursement_reference",
    "funded_at",
    "funded_by_user_id",
    "reason_code",
    "created_at",
    "updated_at",
    "version",
)

OBLIGATION_FIELDS = (
    "id",
    "unit_id",
    "dealer_id",
    "supersedes_obligation_id",
    "status",
    "tier_age_days_from",
    "tier_cumulative_paydown_bps",
    "due_date",
    "projected_principal_cents",
    "required_principal_cents",
    "late_fee_cents",
    "total_amount_due_cents",
    "principal_paid_cents",
    "fee_paid_cents",
    "became_due_at",
    "became_delinquent_at",
    "extension_days_applied",
    "created_at",
    "updated_at",
    "version",
)

EXCEPTION_FIELDS = (
    "id",
    "obligation_id",
    "status",
    "requested_extension_days",
    "justification_code",
    "requested_by_user_id",
    "decided_extension_days",
    "decided_by_user_id",
    "decided_at",
    "reason_code",
    "replacement_obligation_id",
    "created_at",
    "updated_at",
    "version",
)

AUDIT_FIELDS = (
    "id",
    "dealer_id",
    "audit_type",
    "status",
    "window_start_date",
    "window_end_date",
    "started_at",
    "reconciled_at",
    "units_in_scope_count",
    "units_verified_count",
    "units_exception_count",
    "units_unobserved_count",
    "sot_exposure_cents",
    "observer_user_ids",
    "reconciled_by_user_id",
    "abort_reason_code",
    "created_at",
    "updated_at",
    "version",
)

OBSERVATION_FIELDS = (
    "id",
    "audit_id",
    "unit_id",
    "observed_condition",
    "title_verified",
    "odometer_miles",
    "sale_contract_reference",
    "classification",
    "is_out_of_trust",
    "observed_by_user_id",
    "unit_outstanding_principal_cents_at_observation",
    "created_at",
)

INCIDENT_FIELDS = (
    "id",
    "dealer_id",
    "unit_id",
    "audit_id",
    "observation_id",
    "status",
    "exposure_cents",
    "cure_deadline_at",
    "cured_at",
    "charged_off_at",
    "resolution_reason_code",
    "created_at",
    "updated_at",
    "version",
)

REMITTANCE_FIELDS = (
    "id",
    "dealer_id",
    "target_unit_id",
    "target_obligation_id",
    "intent",
    "status",
    "amount_cents",
    "payment_reference",
    "applied_principal_cents",
    "applied_fee_cents",
    "applied_sot_cure_cents",
    "unapplied_cents",
    "allocation_breakdown",
    "applied_at",
    "created_at",
    "updated_at",
    "version",
)

COVENANT_TEST_FIELDS = (
    "id",
    "dealer_id",
    "period_end_date",
    "reported_tangible_net_worth_cents",
    "reported_ebitda_cents",
    "reported_interest_expense_cents",
    "reported_curtailment_paid_cents",
    "reported_unrestricted_cash_cents",
    "required_tangible_net_worth_cents",
    "dscr_lender_standard",
    "dscr_dealer_adjusted",
    "trailing_sot_incident_count",
    "result",
    "failure_reason_codes",
    "submitted_by_user_id",
    "created_at",
)

REMEDY_FIELDS = (
    "id",
    "dealer_id",
    "action_type",
    "status",
    "reason_code",
    "justification_snapshot",
    "issued_by_user_id",
    "executed_by_user_id",
    "executed_at",
    "units_repossessed_count",
    "principal_charged_off_cents",
    "created_at",
    "updated_at",
    "version",
)


def dealer(row):
    return db.public(row, DEALER_FIELDS)


def credit_line(row):
    return db.public(row, CREDIT_LINE_FIELDS)


def tier(row):
    return db.public(row, CURTAILMENT_TIER_FIELDS)


def unit(row):
    return db.public(row, UNIT_FIELDS)


def advance(row):
    return db.public(row, ADVANCE_FIELDS)


def obligation(row):
    return db.public(row, OBLIGATION_FIELDS)


def exception_request(row):
    return db.public(row, EXCEPTION_FIELDS)


def audit(row):
    return db.public(row, AUDIT_FIELDS)


def observation(row):
    return db.public(row, OBSERVATION_FIELDS)


def incident(row):
    return db.public(row, INCIDENT_FIELDS)


def remittance(row):
    return db.public(row, REMITTANCE_FIELDS)


def covenant_test(row):
    payload = db.public(row, COVENANT_TEST_FIELDS)
    payload["dscr_lender_standard"] = db.as_number(row["dscr_lender_standard"])
    payload["dscr_dealer_adjusted"] = db.as_number(row["dscr_dealer_adjusted"])
    return payload


def remedy(row):
    return db.public(row, REMEDY_FIELDS)
