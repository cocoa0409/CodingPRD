"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    APPLICANT = "Applicant"
    INTERCONNECTION_COORDINATOR = "InterconnectionCoordinator"
    DISTRIBUTION_ENGINEER = "DistributionEngineer"
    METER_TECHNICIAN = "MeterTechnician"
    INSPECTOR = "Inspector"
    PROGRAM_ADMINISTRATOR = "ProgramAdministrator"


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class ProgramStatus(str, Enum):
    OPEN = "OPEN"
    CAP_REACHED = "CAP_REACHED"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class MeteringVariant(str, Enum):
    ENERGY_BANKING = "ENERGY_BANKING"
    MONETARY_CREDIT = "MONETARY_CREDIT"


class TrueUpMode(str, Enum):
    AVOIDED_COST_PAYOUT = "AVOIDED_COST_PAYOUT"
    BANK_ROLLOVER = "BANK_ROLLOVER"


class ScreeningBasis(str, Enum):
    COMMITTED = "COMMITTED"
    INCLUDE_QUEUED = "INCLUDE_QUEUED"


class ServiceClass(str, Enum):
    RESIDENTIAL = "RESIDENTIAL"
    COMMERCIAL = "COMMERCIAL"
    INDUSTRIAL = "INDUSTRIAL"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class MeteringStatus(str, Enum):
    STANDARD = "STANDARD"
    NET_METERING = "NET_METERING"


class Technology(str, Enum):
    SOLAR_PV = "SOLAR_PV"
    WIND = "WIND"
    FUEL_CELL = "FUEL_CELL"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_COMPLETENESS = "PENDING_COMPLETENESS"
    INCOMPLETE = "INCOMPLETE"
    WAITING_FOR_CAPACITY = "WAITING_FOR_CAPACITY"
    CAPACITY_RESERVED = "CAPACITY_RESERVED"
    SUPPLEMENTAL_REVIEW = "SUPPLEMENTAL_REVIEW"
    SCREEN_PASSED = "SCREEN_PASSED"
    AWAITING_COST_ESTIMATE = "AWAITING_COST_ESTIMATE"
    CUSTOMER_DECISION_PENDING = "CUSTOMER_DECISION_PENDING"
    UPGRADE_IN_PROGRESS = "UPGRADE_IN_PROGRESS"
    PTO_GRANTED = "PTO_GRANTED"
    OPERATING = "OPERATING"
    WITHDRAWN = "WITHDRAWN"
    DENIED = "DENIED"


class DenialReason(str, Enum):
    PRODUCTION_EXCEEDS_LOAD = "PRODUCTION_EXCEEDS_LOAD"
    SIZE_EXCEEDS_CLASS_CAP = "SIZE_EXCEEDS_CLASS_CAP"
    TECHNICALLY_INFEASIBLE = "TECHNICALLY_INFEASIBLE"


class WithdrawalReason(str, Enum):
    APPLICANT_WITHDRAWN = "APPLICANT_WITHDRAWN"
    CUSTOMER_DECLINED = "CUSTOMER_DECLINED"
    ESTIMATE_EXPIRED = "ESTIMATE_EXPIRED"
    RESERVATION_EXPIRED = "RESERVATION_EXPIRED"


class DocType(str, Enum):
    SITE_PLAN = "SITE_PLAN"
    SINGLE_LINE_DIAGRAM = "SINGLE_LINE_DIAGRAM"
    INSURANCE_CERTIFICATE = "INSURANCE_CERTIFICATE"


class DocumentReviewStatus(str, Enum):
    UPLOADED = "UPLOADED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ReportStatus(str, Enum):
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"


class ScreenOutcome(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"


class FailingScreen(str, Enum):
    TRANSFORMER_CAPACITY = "TRANSFORMER_CAPACITY"
    FEEDER_PENETRATION = "FEEDER_PENETRATION"
    FAST_TRACK_SIZE = "FAST_TRACK_SIZE"


class ReviewType(str, Enum):
    FACILITIES_STUDY = "FACILITIES_STUDY"
    SYSTEM_IMPACT_STUDY = "SYSTEM_IMPACT_STUDY"


class SupplementalReviewStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"


class SupplementalOutcome(str, Enum):
    CLEARED = "CLEARED"
    UPGRADES_REQUIRED = "UPGRADES_REQUIRED"
    DENIED = "DENIED"


class EstimateStatus(str, Enum):
    ISSUED = "ISSUED"
    ACCEPTED = "ACCEPTED"
    WORK_COMPLETE = "WORK_COMPLETE"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RESULT_RECORDED = "RESULT_RECORDED"
    CANCELLED = "CANCELLED"


class InspectionOutcome(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"


class ExchangeStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ReadingStatus(str, Enum):
    POSTED = "POSTED"
    SUPERSEDED = "SUPERSEDED"
    VOIDED = "VOIDED"


class LedgerEntryType(str, Enum):
    EXPORT_SURPLUS_CREDIT = "EXPORT_SURPLUS_CREDIT"
    CREDIT_APPLIED = "CREDIT_APPLIED"
    BANK_DEPOSIT = "BANK_DEPOSIT"
    BANK_DRAW = "BANK_DRAW"
    BANK_FORFEIT = "BANK_FORFEIT"
    TRUE_UP_PAYOUT = "TRUE_UP_PAYOUT"
    TRUE_UP_FORFEIT = "TRUE_UP_FORFEIT"
    REVERSAL = "REVERSAL"


class ReconciliationStatus(str, Enum):
    COMPUTED = "COMPUTED"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------
# Every primary resource carries id / created_at / updated_at / version
# (PRD §2.5); the credit ledger entry is the deliberate exception and carries
# only id / created_at.

class Program(TypedDict):
    id: str
    name: str
    program_status: str
    aggregate_cap_watts: int
    metering_variant: str
    true_up_mode: str
    true_up_month: int
    screening_basis: str
    bank_cap_wh: Optional[int]
    interconnected_watts: int
    reserved_watts: int
    available_capacity_watts: int
    queued_count: int
    created_at: str
    updated_at: str
    version: int


class TariffSchedule(TypedDict):
    id: str
    program_id: str
    schedule_code: str
    effective_from: str
    effective_to: Optional[str]
    import_rate_millicents_per_kwh: int
    export_rate_millicents_per_kwh: int
    net_surplus_rate_millicents_per_kwh: int
    created_at: str
    updated_at: str
    version: int


class Feeder(TypedDict):
    id: str
    feeder_code: str
    peak_load_watts: int
    pre_existing_der_watts: int
    aggregate_der_watts: int
    created_at: str
    updated_at: str
    version: int


class ServiceTransformer(TypedDict):
    id: str
    feeder_id: str
    transformer_code: str
    nameplate_watts: int
    pre_existing_der_watts: int
    aggregate_der_watts: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    full_name: str
    email: str
    created_at: str
    updated_at: str
    version: int


class ServiceAccount(TypedDict):
    id: str
    customer_id: str
    transformer_id: str
    account_number: str
    service_class: str
    prior_annual_usage_wh: int
    account_status: str
    metering_status: str
    meter_serial: Optional[str]
    credit_balance_cents: int
    banked_wh: int
    created_at: str
    updated_at: str
    version: int


class InterconnectionApplication(TypedDict):
    id: str
    program_id: str
    service_account_id: str
    technology: str
    system_size_watts_ac: int
    estimated_annual_production_wh: int
    application_status: str
    denial_reason: Optional[str]
    withdrawal_reason: Optional[str]
    queue_position: Optional[int]
    capacity_reserved_watts: int
    reservation_expires_at: Optional[str]
    submission_round: int
    submitted_at: Optional[str]
    pto_granted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ApplicationDocument(TypedDict):
    id: str
    application_id: str
    doc_type: str
    title: str
    review_status: str
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScreeningReport(TypedDict):
    id: str
    application_id: str
    screening_round: int
    report_status: str
    aggregate_basis: str
    transformer_aggregate_after_watts: int
    transformer_limit_watts: int
    transformer_screen_passed: bool
    feeder_aggregate_after_watts: int
    feeder_limit_watts: int
    feeder_screen_passed: bool
    size_within_fast_track: bool
    outcome: str
    failing_screens: List[str]
    created_at: str
    updated_at: str
    version: int


class SupplementalReview(TypedDict):
    id: str
    application_id: str
    review_type: str
    review_status: str
    outcome: Optional[str]
    findings: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UpgradeCostEstimate(TypedDict):
    id: str
    application_id: str
    supplemental_review_id: str
    items: List[dict]
    contingency_pct: int
    total_cents: int
    estimate_status: str
    valid_until: str
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    application_id: str
    scheduled_date: str
    inspection_status: str
    outcome: Optional[str]
    occurred_at: Optional[str]
    defects: Optional[str]
    inspector_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MeterExchange(TypedDict):
    id: str
    application_id: str
    crew_id: str
    window_start: str
    window_end: str
    exchange_status: str
    installed_meter_serial: Optional[str]
    technician_user_id: Optional[str]
    fail_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MeterReading(TypedDict):
    id: str
    service_account_id: str
    period_start: str
    period_end: str
    import_wh: int
    export_wh: int
    reading_status: str
    tariff_id: str
    bill_cents: int
    credit_applied_cents: int
    bank_drawn_wh: int
    bank_deposited_wh: int
    created_at: str
    updated_at: str
    version: int


class CreditLedgerEntry(TypedDict):
    # Append-only (PRD §2.5): carries ONLY id + created_at of the common set.
    id: str
    created_at: str
    service_account_id: str
    meter_reading_id: Optional[str]
    annual_reconciliation_id: Optional[str]
    entry_type: str
    amount_cents: int
    quantity_wh: int
    posted_at: str


class AnnualReconciliation(TypedDict):
    id: str
    service_account_id: str
    reconciliation_year: int
    reconciliation_status: str
    window_start: str
    window_end: str
    surplus_wh: int
    credit_balance_at_compute_cents: int
    nsc_cents: int
    payout_cents: int
    forfeited_cents: int
    forfeited_wh: int
    tariff_id: str
    created_at: str
    updated_at: str
    version: int
