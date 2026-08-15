"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    COLLECTOR = "Collector"
    FINANCIAL_COUNSELOR = "FinancialCounselor"
    REVENUE_INTEGRITY_OFFICER = "RevenueIntegrityOfficer"
    COLLECTION_AGENCY_USER = "CollectionAgencyUser"


class AccountStatus(str, Enum):
    OPEN = "OPEN"
    IN_EARLY_OUT = "IN_EARLY_OUT"
    IN_COLLECTIONS = "IN_COLLECTIONS"
    WRITTEN_OFF = "WRITTEN_OFF"
    CLOSED_PAID = "CLOSED_PAID"
    CLOSED_CHARITY = "CLOSED_CHARITY"


class AgingBucket(str, Enum):
    CURRENT = "CURRENT"
    BUCKET_30 = "BUCKET_30"
    BUCKET_60 = "BUCKET_60"
    BUCKET_90 = "BUCKET_90"
    BUCKET_120_PLUS = "BUCKET_120_PLUS"


class CreditReportingStatus(str, Enum):
    NOT_REPORTED = "NOT_REPORTED"
    REPORTABLE = "REPORTABLE"
    REPORTED = "REPORTED"
    FROZEN_BY_DISPUTE = "FROZEN_BY_DISPUTE"
    SUPPRESSED_BY_CHARITY = "SUPPRESSED_BY_CHARITY"


class StatementStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    RETURNED_UNDELIVERABLE = "RETURNED_UNDELIVERABLE"


class ScreeningModel(str, Enum):
    FPL_TIERED = "FPL_TIERED"
    SCORE_BASED = "SCORE_BASED"


class EligibilityOutcome(str, Enum):
    FULL_CHARITY = "FULL_CHARITY"
    PARTIAL_CHARITY = "PARTIAL_CHARITY"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    PENDING = "PENDING"


class ScreeningStatus(str, Enum):
    PENDING = "PENDING"
    EVALUATED = "EVALUATED"
    SUPERSEDED = "SUPERSEDED"
    APPLIED = "APPLIED"


class EarlyOutPlacementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RECALLED = "RECALLED"
    ESCALATED_TO_AGENCY = "ESCALATED_TO_AGENCY"
    COMPLETED_PAID = "COMPLETED_PAID"


class AgencyPlacementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RECALLED_NO_FEE = "RECALLED_NO_FEE"
    RECALLED_WITH_FEE = "RECALLED_WITH_FEE"
    CLOSED_PAID = "CLOSED_PAID"
    CLOSED_DISPUTE = "CLOSED_DISPUTE"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    EXPIRED = "EXPIRED"


class ResolutionOutcome(str, Enum):
    UPHELD_PATIENT = "UPHELD_PATIENT"
    UPHELD_PROVIDER = "UPHELD_PROVIDER"
    UNRESOLVED_EXPIRED = "UNRESOLVED_EXPIRED"


class PaymentPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    IN_DEFAULT = "IN_DEFAULT"
    CURED = "CURED"
    COMPLETED = "COMPLETED"
    TERMINATED_DEFAULT = "TERMINATED_DEFAULT"


class WriteOffKind(str, Enum):
    BAD_DEBT = "BAD_DEBT"
    CHARITY_CARE = "CHARITY_CARE"


class WriteOffStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class PaymentKind(str, Enum):
    INSTALLMENT = "INSTALLMENT"
    LUMP_SUM = "LUMP_SUM"
    AGENCY_REMITTANCE = "AGENCY_REMITTANCE"
    EARLY_OUT_REMITTANCE = "EARLY_OUT_REMITTANCE"
    POST_WRITEOFF_RECOVERY = "POST_WRITEOFF_RECOVERY"


# --- Entity TypedDicts -------------------------------------------------------
# Primary resources carry id + created_at + updated_at + version (PRD §2.5).


class SelfPayAccount(TypedDict, total=False):
    id: str
    patient_mrn: str
    patient_name: str
    original_balance_cents: int
    current_balance_cents: int
    guarantor_liability_date: str
    aging_bucket: str
    aging_bucket_entered_at: str
    statements_sent_count: int
    charity_writeoff_total_cents: int
    bad_debt_writeoff_total_cents: int
    recovery_total_cents: int
    credit_reporting_status: str
    status: str
    status_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Statement(TypedDict, total=False):
    id: str
    account_id: str
    statement_index: int
    issued_at: str
    due_date: str
    balance_at_issue_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PresumptiveCharityScreening(TypedDict, total=False):
    id: str
    account_id: str
    screening_model: str
    household_size: Optional[int]
    household_income_cents: Optional[int]
    third_party_score: Optional[int]
    fpl_percent: Optional[int]
    eligibility_outcome: str
    charity_writeoff_percent: int
    screened_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EarlyOutPlacement(TypedDict, total=False):
    id: str
    account_id: str
    vendor_name: str
    placement_balance_cents: int
    contingency_fee_bps: int
    placed_at: str
    recall_deadline: str
    recovered_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CollectionAgencyPlacement(TypedDict, total=False):
    id: str
    account_id: str
    agency_name: str
    placement_balance_cents: int
    contingency_fee_bps: int
    placed_at: str
    recall_window_closes_at: str
    recovered_cents: int
    credit_reported_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PatientDispute(TypedDict, total=False):
    id: str
    account_id: str
    dispute_reason: str
    dispute_amount_cents: int
    filed_at: str
    investigation_due_at: str
    resolved_at: Optional[str]
    resolution_outcome: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PaymentPlan(TypedDict, total=False):
    id: str
    account_id: str
    installment_amount_cents: int
    installment_count: int
    first_installment_due: str
    installments_paid_count: int
    missed_installment_count: int
    default_flagged_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BadDebtWriteOff(TypedDict, total=False):
    id: str
    account_id: str
    write_off_kind: str
    amount_cents: int
    screening_id: Optional[str]
    medicare_cost_report_year: Optional[int]
    posted_at: Optional[str]
    approved_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RecoveryTransaction(TypedDict, total=False):
    id: str
    account_id: str
    payment_kind: str
    amount_cents: int
    attributed_placement_id: Optional[str]
    payment_plan_id: Optional[str]
    write_off_id: Optional[str]
    net_to_hospital_cents: int
    posted_at: str
    created_at: str
    updated_at: str
    version: int


# Append-only families (PRD §2.5): carry only id + created_at from the standard
# set — no updated_at, no version.


class MedicareBadDebtLogEntry(TypedDict, total=False):
    id: str
    created_at: str
    write_off_id: str
    account_id: str
    cost_report_year: int
    claimed_amount_cents: int
    indigence_documented: bool
    collection_effort_days: int
    logged_at: str
    voided_at: Optional[str]


class VendorPerformanceSnapshot(TypedDict, total=False):
    id: str
    created_at: str
    vendor_name: str
    snapshot_period_start: str
    snapshot_period_end: str
    placements_in_window: int
    recovered_in_window_cents: int
    recovery_rate_bps: int
    meets_minimum_threshold: bool
    snapshot_generated_at: str
