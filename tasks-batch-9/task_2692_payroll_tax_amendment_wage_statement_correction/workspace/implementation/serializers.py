"""Row -> JSON projection.  Field lists come straight from SCAFFOLD.yaml entities."""

from common import iso

DATETIME_FIELDS = frozenset([
    "created_at", "updated_at", "activated_at", "deposit_due_date", "deposit_date",
    "filed_at", "original_due_date", "closed_at", "accrual_through_date",
    "submitted_at", "accepted_at", "issued_at", "acknowledged_at",
    "response_due_date", "responded_at", "target_date", "verified_at",
])

AUDIT_FULL = ("id", "created_at", "updated_at", "version")
AUDIT_IMMUTABLE = ("id", "created_at")

EMPLOYER_FIELDS = (
    "legal_name", "fein", "deposit_schedule", "authorization_limit_cents",
    "open_exposure_cents", "open_remediation_count", "granted_abatement_count",
)

AGENCY_FIELDS = (
    "agency_code", "level", "jurisdiction_code", "interest_rate_bps_annual",
    "interest_method", "penalty_multiplier_bps", "min_days_between_amendments",
    "amendment_window_days", "requires_registration",
)

ACCOUNT_FIELDS = (
    "employer_id", "agency_id", "account_number", "effective_from_tax_year",
    "effective_from_quarter", "effective_to_tax_year", "effective_to_quarter",
    "retroactive", "registration_status", "from_period_ordinal",
    "to_period_ordinal", "activated_at",
)

EMPLOYEE_FIELDS = (
    "employer_id", "full_name", "national_id_last4", "mailing_state_code",
    "active_statement_count",
)

REGISTER_LINE_FIELDS = (
    "employer_id", "employee_id", "agency_id", "tax_year", "quarter",
    "taxable_wage_cents", "withheld_cents", "work_jurisdiction_code",
    "workday_ratio_bps", "posting_status",
)

DEPOSIT_FIELDS = (
    "employer_id", "agency_id", "tax_year", "quarter", "deposit_due_date",
    "deposit_date", "amount_cents", "obligation_amount_cents", "clearing_status",
)

FILED_RETURN_FIELDS = (
    "employer_id", "agency_id", "tax_year", "quarter", "form_code", "filed_at",
    "reported_taxable_wage_cents", "reported_withheld_cents",
    "original_due_date", "status",
)

CASE_FIELDS = (
    "employer_id", "agency_id", "tax_year", "quarter", "status",
    "detection_status", "filing_status", "statement_status",
    "dominant_root_cause_code", "open_discrepancy_count", "total_exposure_cents",
    "corrected_wage_base_cents", "repayment_recovered_cents", "closed_at",
)

DISCREPANCY_FIELDS = (
    "correction_case_id", "employee_id", "register_line_id", "detected_category",
    "category", "root_cause_code", "amount_cents", "emission_index", "status",
    "dismissal_reason", "resolved_amended_return_id", "resolved_amount_cents",
)

AMENDED_RETURN_FIELDS = (
    "correction_case_id", "supersedes_amended_return_id", "form_code",
    "prepared_by_user_id", "signed_by_user_id", "accrual_through_date",
    "wage_delta_cents", "tax_delta_cents", "deposit_shortfall_cents", "days_late",
    "interest_variant", "interest_cents", "penalty_cents",
    "voluntary_reduction_applied", "status", "submitted_at", "accepted_at",
    "rejection_reason", "void_reason",
)

STATEMENT_FIELDS = (
    "correction_case_id", "employee_id", "supersedes_statement_id", "tax_year",
    "is_prior_year", "sequence_no", "wage_delta_cents", "fica_wage_delta_cents",
    "withholding_delta_cents", "delivery_channel", "status", "issued_at",
    "acknowledged_at", "undeliverable_reason",
)

REPAYMENT_FIELDS = (
    "correction_case_id", "employee_id", "overpaid_gross_cents",
    "overpaid_income_tax_withheld_cents", "overpaid_fica_withheld_cents",
    "overpayment_tax_year", "recovery_tax_year", "recovery_basis",
    "employee_due_cents", "agency_recoverable_cents", "installment_count",
    "collected_cents", "status", "write_off_reason",
)

NOTICE_FIELDS = (
    "employer_id", "agency_id", "correction_case_id", "tax_year", "quarter",
    "notice_number", "assessed_tax_cents", "assessed_penalty_cents",
    "assessed_interest_cents", "response_due_date", "response_narrative",
    "abatement_grounds", "requested_penalty_waiver_cents", "response_status",
    "abatement_status", "abatement_round", "waiver_pct_bps",
    "waived_penalty_cents", "waived_interest_cents", "net_exposure_cents",
    "responded_at", "agency_decision_reference",
)

REMEDIATION_FIELDS = (
    "correction_case_id", "root_cause_code", "control_gap_class",
    "owner_user_id", "target_date", "evidence_reference", "verified_by_user_id",
    "verification_round", "status", "verified_at",
)


def _project(row, fields, audit):
    out = {}
    for name in audit + fields:
        value = row.get(name)
        if name in DATETIME_FIELDS:
            value = iso(value)
        out[name] = value
    return out


def employer_json(row):
    return _project(row, EMPLOYER_FIELDS, AUDIT_FULL)


def agency_json(row):
    return _project(row, AGENCY_FIELDS, AUDIT_FULL)


def account_json(row):
    return _project(row, ACCOUNT_FIELDS, AUDIT_FULL)


def employee_json(row):
    return _project(row, EMPLOYEE_FIELDS, AUDIT_FULL)


def register_line_json(row):
    return _project(row, REGISTER_LINE_FIELDS, AUDIT_IMMUTABLE)


def deposit_json(row):
    return _project(row, DEPOSIT_FIELDS, AUDIT_IMMUTABLE)


def filed_return_json(row):
    return _project(row, FILED_RETURN_FIELDS, AUDIT_FULL)


def case_json(row):
    return _project(row, CASE_FIELDS, AUDIT_FULL)


def discrepancy_json(row):
    return _project(row, DISCREPANCY_FIELDS, AUDIT_FULL)


def amended_return_json(row):
    return _project(row, AMENDED_RETURN_FIELDS, AUDIT_FULL)


def statement_json(row):
    return _project(row, STATEMENT_FIELDS, AUDIT_FULL)


def repayment_json(row):
    return _project(row, REPAYMENT_FIELDS, AUDIT_FULL)


def notice_json(row):
    return _project(row, NOTICE_FIELDS, AUDIT_FULL)


def remediation_json(row):
    return _project(row, REMEDIATION_FIELDS, AUDIT_FULL)
