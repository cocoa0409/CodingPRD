"""Typed shapes for the entities the API returns.

Every money field is an integer count of cents and every rate is an integer
count of basis points, exactly as the PRD declares them. ``PayrollRegisterLine``
and ``DepositRecord`` are immutable evidence rows and therefore carry only ``id``
and ``created_at``; every other entity carries ``updated_at`` and ``version`` too.
"""

from typing import Any, Dict, List, Optional, TypedDict

JsonDict = Dict[str, Any]


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class EvidenceCommonFields(TypedDict):
    id: str
    created_at: str


class Employer(CommonFields, total=False):
    legal_name: str
    fein: str
    deposit_schedule: str
    authorization_limit_cents: int
    open_exposure_cents: int
    open_remediation_count: int
    granted_abatement_count: int


class TaxAgency(CommonFields, total=False):
    agency_code: str
    level: str
    jurisdiction_code: str
    interest_rate_bps_annual: int
    interest_method: str
    penalty_multiplier_bps: int
    min_days_between_amendments: int
    amendment_window_days: int
    requires_registration: bool


class AgencyAccount(CommonFields, total=False):
    employer_id: str
    agency_id: str
    account_number: Optional[str]
    effective_from_tax_year: int
    effective_from_quarter: int
    effective_to_tax_year: Optional[int]
    effective_to_quarter: Optional[int]
    retroactive: bool
    registration_status: str
    from_period_ordinal: int
    to_period_ordinal: int
    activated_at: Optional[str]


class Employee(CommonFields, total=False):
    employer_id: str
    full_name: str
    national_id_last4: str
    mailing_state_code: str
    active_statement_count: int


class PayrollRegisterLine(EvidenceCommonFields, total=False):
    employer_id: str
    employee_id: str
    agency_id: str
    tax_year: int
    quarter: int
    taxable_wage_cents: int
    withheld_cents: int
    work_jurisdiction_code: str
    workday_ratio_bps: int
    posting_status: str


class DepositRecord(EvidenceCommonFields, total=False):
    employer_id: str
    agency_id: str
    tax_year: int
    quarter: int
    deposit_due_date: str
    deposit_date: str
    amount_cents: int
    obligation_amount_cents: int
    clearing_status: str


class FiledReturn(CommonFields, total=False):
    employer_id: str
    agency_id: str
    tax_year: int
    quarter: int
    form_code: str
    filed_at: str
    reported_taxable_wage_cents: int
    reported_withheld_cents: int
    original_due_date: str
    status: str


class CorrectionCase(CommonFields, total=False):
    employer_id: str
    agency_id: str
    tax_year: int
    quarter: int
    status: str
    detection_status: str
    filing_status: str
    statement_status: str
    dominant_root_cause_code: Optional[str]
    open_discrepancy_count: int
    total_exposure_cents: int
    corrected_wage_base_cents: int
    repayment_recovered_cents: int
    closed_at: Optional[str]


class Discrepancy(CommonFields, total=False):
    correction_case_id: str
    employee_id: Optional[str]
    register_line_id: Optional[str]
    detected_category: str
    category: Optional[str]
    root_cause_code: Optional[str]
    amount_cents: int
    emission_index: int
    status: str
    dismissal_reason: Optional[str]
    resolved_amended_return_id: Optional[str]
    resolved_amount_cents: Optional[int]


class AmendedReturn(CommonFields, total=False):
    correction_case_id: str
    supersedes_amended_return_id: Optional[str]
    form_code: str
    prepared_by_user_id: Optional[str]
    signed_by_user_id: Optional[str]
    accrual_through_date: Optional[str]
    wage_delta_cents: int
    tax_delta_cents: int
    deposit_shortfall_cents: int
    days_late: int
    interest_variant: Optional[str]
    interest_cents: int
    penalty_cents: int
    voluntary_reduction_applied: bool
    status: str
    submitted_at: Optional[str]
    accepted_at: Optional[str]
    rejection_reason: Optional[str]
    void_reason: Optional[str]


class CorrectedWageStatement(CommonFields, total=False):
    correction_case_id: str
    employee_id: str
    supersedes_statement_id: Optional[str]
    tax_year: int
    is_prior_year: bool
    sequence_no: int
    wage_delta_cents: int
    fica_wage_delta_cents: int
    withholding_delta_cents: int
    delivery_channel: Optional[str]
    status: str
    issued_at: Optional[str]
    acknowledged_at: Optional[str]
    undeliverable_reason: Optional[str]


class WageRepayment(CommonFields, total=False):
    correction_case_id: str
    employee_id: str
    overpaid_gross_cents: int
    overpaid_income_tax_withheld_cents: int
    overpaid_fica_withheld_cents: int
    overpayment_tax_year: int
    recovery_tax_year: int
    recovery_basis: Optional[str]
    employee_due_cents: int
    agency_recoverable_cents: int
    installment_count: Optional[int]
    collected_cents: int
    status: str
    write_off_reason: Optional[str]


class AgencyNotice(CommonFields, total=False):
    employer_id: str
    agency_id: str
    correction_case_id: Optional[str]
    tax_year: int
    quarter: int
    notice_number: str
    assessed_tax_cents: int
    assessed_penalty_cents: int
    assessed_interest_cents: int
    response_due_date: str
    response_narrative: Optional[str]
    abatement_grounds: Optional[str]
    requested_penalty_waiver_cents: Optional[int]
    response_status: str
    abatement_status: str
    abatement_round: int
    waiver_pct_bps: int
    waived_penalty_cents: int
    waived_interest_cents: int
    net_exposure_cents: int
    responded_at: Optional[str]
    agency_decision_reference: Optional[str]


class ControlRemediation(CommonFields, total=False):
    correction_case_id: str
    root_cause_code: str
    control_gap_class: str
    owner_user_id: Optional[str]
    target_date: str
    evidence_reference: Optional[str]
    verified_by_user_id: Optional[str]
    verification_round: int
    status: str
    verified_at: Optional[str]


class ExposureSummary(TypedDict, total=False):
    gross_exposure_cents: int
    waived_cents: int
    total_exposure_cents: int
    corrected_wage_base_cents: int
    repayment_recovered_cents: int
    dominant_root_cause_code: Optional[str]


class PaginationMeta(TypedDict, total=False):
    limit: int
    offset: int
    total_count: int
    has_more: bool


EntityList = List[JsonDict]
