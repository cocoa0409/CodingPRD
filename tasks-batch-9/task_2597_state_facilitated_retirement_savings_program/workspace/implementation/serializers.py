"""JSON projections.  Purely derived figures are recomputed here so a response
can never expose a stale derivation.
"""
import calc
from store import db

COMMON = ("id", "created_at", "updated_at", "version")

PROGRAM_YEAR_FIELDS = (
    "calendar_year", "ira_annual_limit_cents", "catch_up_limit_cents",
    "default_contribution_rate_bp", "escalation_increment_bp", "escalation_cap_bp",
    "escalation_seasoning_days", "opt_out_window_days", "remittance_due_days",
    "notice_period_days", "sustained_notice_days",
    "register_penalty_initial_cents_per_employee",
    "register_penalty_sustained_cents_per_employee", "remit_penalty_monthly_rate_bp",
    "remit_penalty_floor_cents", "remit_penalty_cap_bp", "nia_daily_rate_bp",
    "correction_deadline_month_day",
)

INVESTMENT_OPTION_FIELDS = (
    "fund_code", "name", "category", "target_year", "expense_ratio_bp",
    "default_eligible", "status",
)

EMPLOYER_FIELDS = (
    "ein", "legal_name", "worksite_state", "employee_count", "wave_tier",
    "registration_deadline", "registration_status", "compliance_status",
    "non_fiduciary_acknowledged", "payroll_contact_email", "registered_at",
    "unremitted_deduction_cents", "last_recount_effective_date",
)

CERTIFICATION_FIELDS = (
    "employer_id", "qualified_plan_type", "plan_sponsor_ein", "plan_effective_date",
    "attestation_accepted", "status", "coverage_period_start", "coverage_period_end",
    "decision_note", "revocation_reason", "decided_at", "revoked_at",
)

PARTICIPANT_FIELDS = (
    "full_name", "date_of_birth", "email", "ssn_last4", "state_resident",
    "mailing_address", "phone",
)

ENROLLMENT_FIELDS = (
    "employer_id", "participant_id", "hire_date", "annual_compensation_cents",
    "contribution_rate_bp", "rate_source", "enrollment_status", "opt_out_deadline",
    "escalation_opt_out", "employment_end_date", "opted_out_at",
    "opt_out_reason_code", "permissible_withdrawal_cents", "reenrollment_count",
)

ACCOUNT_FIELDS = (
    "participant_id", "account_type", "rolled_over_from_account_id", "account_status",
    "posture", "balance_cents", "contribution_basis_cents", "ytd_contribution_cents",
    "remaining_headroom_cents", "uncorrected_excess_cents", "fund_balances",
    "active_election_id", "closure_reason", "residual_disposition", "closed_at",
)

ELECTION_FIELDS = (
    "account_id", "allocations", "source", "status", "effective_date",
    "superseded_at", "selection_basis",
)

REMITTANCE_FIELDS = (
    "employer_id", "pay_period_start", "pay_period_end", "pay_date",
    "total_deducted_cents", "status", "line_count", "total_allocated_cents",
    "total_excess_cents", "days_late", "submitted_at", "posted_at", "reversed_at",
    "posting_reference", "rejection_reason", "reversal_reason",
)

LINE_FIELDS = (
    "remittance_id", "enrollment_id", "gross_wages_cents", "deducted_cents",
    "expected_deduction_cents", "allocated_cents", "excess_cents", "status",
)

EXCESS_CASE_FIELDS = (
    "account_id", "calendar_year", "detected_excess_cents", "detected_at_pay_date",
    "computation_period_start", "opening_fmv_cents", "period_contributions_cents",
    "period_distributions_cents", "closing_fmv_cents", "nia_adjusted_balance_cents",
    "nia_daily_prorata_cents", "nia_method_applied", "applied_nia_cents",
    "correction_method", "status", "deadline_date", "corrected_amount_cents",
    "excise_tax_cents", "settlement_reference", "completed_at",
)

PENALTY_FIELDS = (
    "employer_id", "violation_type", "notice_date", "cure_days", "cure_deadline",
    "employee_count_at_assessment", "statutory_amount_cents",
    "graduated_amount_cents", "assessed_cents", "shortfall_basis_cents",
    "months_late", "status", "assessed_by_user_id", "disposed_by_user_id",
    "disposition_note", "origin", "last_accrual_date",
)

REFERRAL_FIELDS = (
    "penalty_id", "agency", "referral_basis", "status", "referred_at",
    "referred_by_user_id", "withdrawn_reason", "employer_ein_snapshot",
)

TRANSFER_FIELDS = (
    "participant_id", "source_account_id", "destination_type",
    "destination_account_id", "external_institution_name", "transfer_kind",
    "amount_cents", "fee_cents", "basis_portion_cents", "taxable_cents",
    "withholding_cents", "net_cents", "in_transit_cents", "status", "requested_on",
    "settle_by_date", "settled_on", "settlement_reference", "return_reason",
    "is_taxable_distribution",
)


def _project(row, fields, common=True, versioned=True):
    out = {"id": row["id"], "created_at": row["created_at"]}
    if common and versioned:
        out["updated_at"] = row.get("updated_at")
        out["version"] = row.get("version")
    for name in fields:
        out[name] = row.get(name)
    return out


# --------------------------------------------------------------- configuration

def program_year(row):
    return _project(row, PROGRAM_YEAR_FIELDS, versioned=False)


def investment_option(row):
    return _project(row, INVESTMENT_OPTION_FIELDS, versioned=False)


# ------------------------------------------------------------------- employers

def employer(row):
    return _project(row, EMPLOYER_FIELDS)


def certification(row):
    return _project(row, CERTIFICATION_FIELDS)


# ---------------------------------------------------------------- participants

def participant(row):
    out = _project(row, PARTICIPANT_FIELDS)
    out["age_at_year_end"] = calc.participant_age_at_year_end(row)
    out["catch_up_eligible"] = calc.catch_up_eligible(row)
    out["indirect_rollover_count"] = calc.indirect_rollover_count(row["id"])
    return out


def enrollment(row):
    out = _project(row, ENROLLMENT_FIELDS)
    out["first_contribution_date"] = calc.first_contribution_date(row["id"])
    out["lifetime_deducted_cents"] = calc.lifetime_deducted_cents(row["id"])
    return out


# --------------------------------------------------------------------- accounts

def account(row):
    calc.refresh_account(row)
    return _project(row, ACCOUNT_FIELDS)


def election(row):
    return _project(row, ELECTION_FIELDS)


# ------------------------------------------------------------------ remittances

def remittance(row):
    calc.refresh_remittance(row)
    return _project(row, REMITTANCE_FIELDS)


def remittance_line(row):
    return _project(row, LINE_FIELDS)


# ------------------------------------------------------- corrections and money

def excess_case(row):
    return _project(row, EXCESS_CASE_FIELDS)


def penalty(row):
    return _project(row, PENALTY_FIELDS)


def referral(row):
    return _project(row, REFERRAL_FIELDS)


def transfer(row):
    return _project(row, TRANSFER_FIELDS)


SERIALIZERS = {
    "program_years": program_year,
    "investment_options": investment_option,
    "employers": employer,
    "exemption_certifications": certification,
    "participants": participant,
    "enrollments": enrollment,
    "participant_accounts": account,
    "investment_elections": election,
    "payroll_remittances": remittance,
    "remittance_lines": remittance_line,
    "excess_cases": excess_case,
    "penalty_assessments": penalty,
    "enforcement_referrals": referral,
    "portability_transfers": transfer,
}


def ordered(collection):
    return db.ordered(collection)
