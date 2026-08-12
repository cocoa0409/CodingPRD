"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_ADMINISTRATOR = "ProgramAdministrator"
    CASE_WORKER = "CaseWorker"
    APPEALS_OFFICER = "AppealsOfficer"
    PATIENT = "Patient"
    PRESCRIBER = "Prescriber"
    PHARMACY_DISPENSER = "PharmacyDispenser"


class ProgramPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    EXHAUSTED = "EXHAUSTED"


class BudgetPeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ScreeningStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    STALE = "STALE"


class DocumentStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class DocType(str, Enum):
    PROOF_OF_INCOME = "PROOF_OF_INCOME"
    IDENTITY = "IDENTITY"
    INSURANCE_VERIFICATION = "INSURANCE_VERIFICATION"
    OTHER = "OTHER"


class IncomeBasis(str, Enum):
    YTD_ANNUALIZED = "YTD_ANNUALIZED"
    PRIOR_YEAR = "PRIOR_YEAR"


class InsuranceStatus(str, Enum):
    UNINSURED = "UNINSURED"
    UNDERINSURED = "UNDERINSURED"
    INSURED_COMMERCIAL = "INSURED_COMMERCIAL"
    MEDICARE = "MEDICARE"
    MEDICAID = "MEDICAID"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    MORE_INFO_REQUESTED = "MORE_INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SUPERSEDED = "SUPERSEDED"


class EnrollmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"
    CLOSED_RENEWED = "CLOSED_RENEWED"


class CircumstanceStatus(str, Enum):
    REPORTED = "REPORTED"
    APPLIED = "APPLIED"
    DISMISSED = "DISMISSED"


class CircumstanceType(str, Enum):
    INCOME_CHANGE = "INCOME_CHANGE"
    INSURANCE_CHANGE = "INSURANCE_CHANGE"
    HOUSEHOLD_CHANGE = "HOUSEHOLD_CHANGE"


class CircumstanceOutcome(str, Enum):
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class AppealStatus(str, Enum):
    FILED = "FILED"
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"


class CopayCardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class LotStatus(str, Enum):
    ACTIVE = "ACTIVE"
    QUARANTINED = "QUARANTINED"
    EXPIRED = "EXPIRED"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"


class ShipmentStatus(str, Enum):
    RESERVED = "RESERVED"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    RETURNED = "RETURNED"


class Destination(str, Enum):
    PROVIDER = "PROVIDER"
    PATIENT = "PATIENT"


class ReconciliationStatus(str, Enum):
    CLEAN = "CLEAN"
    VARIANCE_FLAGGED = "VARIANCE_FLAGGED"


# --- Entity TypedDicts (common fields per PRD §2.4) ---


class AssistanceProgram(TypedDict, total=False):
    id: str
    name: str
    product_name: str
    unit_cost_per_unit: str
    max_units_per_enrollment: int
    max_units_per_shipment: int
    max_annual_benefit_cents: int
    enrollment_duration_days: int
    screening_validity_days: int
    appeal_window_days: int
    renewal_window_days: int
    lot_expiry_buffer_days: int
    allow_patient_direct_shipment: bool
    posture: str
    total_allocated_cents: int
    total_committed_cents: int
    total_disbursed_cents: int
    created_at: str
    updated_at: str
    version: int


class BudgetPeriod(TypedDict, total=False):
    id: str
    program_id: str
    period_start: str
    period_end: str
    allocated_cents: int
    committed_cents: int
    disbursed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    state_code: str
    created_at: str
    updated_at: str
    version: int


class Prescriber(TypedDict, total=False):
    id: str
    full_name: str
    npi_number: str
    state_code: str
    created_at: str
    updated_at: str
    version: int


class EligibilityScreening(TypedDict, total=False):
    id: str
    patient_id: str
    program_id: str
    household_size: int
    income_basis: str
    ytd_income_cents: Optional[int]
    ytd_months_elapsed: Optional[int]
    prior_year_income_cents: Optional[int]
    insurance_status: str
    insurance_coverage_pct: Optional[str]
    annualized_income_cents: int
    fpl_limit_cents: int
    fpl_percent: str
    eligibility_determination: Optional[str]
    status: str
    verified_at: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScreeningDocument(TypedDict, total=False):
    id: str
    screening_id: str
    doc_type: str
    file_reference: str
    status: str
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    patient_id: str
    program_id: str
    screening_id: str
    renewal_of_enrollment_id: Optional[str]
    status: str
    reviewer_id: Optional[str]
    info_request_note: Optional[str]
    decision_reason: Optional[str]
    decided_at: Optional[str]
    approved_via_appeal: bool
    enrollment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict, total=False):
    id: str
    patient_id: str
    program_id: str
    application_id: str
    commitment_budget_period_id: str
    start_date: str
    end_date: str
    benefit_cap_cents: int
    cap_units: int
    disbursed_cents: int
    remaining_units: int
    status: str
    status_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChangeOfCircumstance(TypedDict, total=False):
    id: str
    enrollment_id: str
    circumstance_type: str
    new_annual_income_cents: Optional[int]
    new_household_size: Optional[int]
    new_insurance_status: Optional[str]
    note: Optional[str]
    reported_by: str
    status: str
    outcome: Optional[str]
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict, total=False):
    id: str
    application_id: str
    grounds: str
    status: str
    decided_by: Optional[str]
    decision_reason: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CopayCard(TypedDict, total=False):
    id: str
    patient_id: str
    program_id: str
    coverage_start: str
    coverage_end: str
    status: str
    termination_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict, total=False):
    id: str
    program_id: str
    lot_number: str
    quantity_received: int
    unit_cost_per_unit: str
    expiry_date: str
    status: str
    quantity_on_hand: int
    quantity_reserved: int
    quantity_shipped: int
    quantity_dispensed: int
    quantity_quarantined: int
    status_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict, total=False):
    id: str
    enrollment_id: str
    destination: str
    prescriber_id: Optional[str]
    quantity_units: int
    status: str
    value_cents: int
    dispensed_value_cents: int
    idempotency_key: str
    requested_by: str
    status_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShipmentLine(TypedDict, total=False):
    id: str
    shipment_id: str
    lot_id: str
    quantity: int
    value_cents: int
    dispensed_quantity: int
    created_at: str
    updated_at: str
    version: int


class DispenseEvent(TypedDict, total=False):
    # Immutable audit record (PRD §2.4): carries only id and created_at —
    # no updated_at, no version.
    id: str
    shipment_id: str
    lot_id: str
    quantity: int
    dispensed_at: str
    value_cents: int
    dispenser_id: str
    created_at: str


class ReconciliationLine(TypedDict, total=False):
    lot_id: str
    book_on_hand: int
    actual_on_hand: int
    variance_units: int
    variance_value_cents: int


class ReconciliationRun(TypedDict, total=False):
    id: str
    program_id: str
    budget_period_id: str
    status: str
    lines: List[ReconciliationLine]
    created_at: str
    updated_at: str
    version: int
