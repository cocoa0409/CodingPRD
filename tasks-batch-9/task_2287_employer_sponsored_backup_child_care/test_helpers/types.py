"""Domain types for the Employer Backup Care API: status enums, role enum, entity TypedDicts."""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1 — five peer roles, none a superset of another)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    BENEFITS_ADMIN = "benefits_admin"
    NETWORK_ADMIN = "network_admin"
    CARE_COORDINATOR = "care_coordinator"
    PROVIDER_MANAGER = "provider_manager"
    EMPLOYEE_USER = "employee_user"


# --------------------------------------------------------------------------
# Employer / BenefitPlan
# --------------------------------------------------------------------------
class ContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class InvoicingCycle(str, Enum):
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


# --------------------------------------------------------------------------
# Employee / Dependent
# --------------------------------------------------------------------------
class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LEAVE = "LEAVE"
    TERMINATED = "TERMINATED"


class EligibilityStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    RESTRICTED = "RESTRICTED"
    INELIGIBLE = "INELIGIBLE"


class DependentType(str, Enum):
    CHILD = "CHILD"
    ADULT_ELDER = "ADULT_ELDER"


class DependentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class DependentTypeMix(str, Enum):
    CHILD_ONLY = "CHILD_ONLY"
    ADULT_ELDER_ONLY = "ADULT_ELDER_ONLY"
    MIXED = "MIXED"


# --------------------------------------------------------------------------
# Provider / Credential / CapacityBlock
# --------------------------------------------------------------------------
class CareMode(str, Enum):
    CENTER_BASED = "CENTER_BASED"
    IN_HOME = "IN_HOME"


class RequestedCareMode(str, Enum):
    CENTER_BASED = "CENTER_BASED"
    IN_HOME = "IN_HOME"
    EITHER = "EITHER"


class NetworkStatus(str, Enum):
    PENDING = "PENDING"
    CREDENTIALED = "CREDENTIALED"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"
    DEPROVISIONED = "DEPROVISIONED"


class CredentialType(str, Enum):
    LICENSE = "LICENSE"
    BACKGROUND_CHECK = "BACKGROUND_CHECK"
    CPR = "CPR"
    INSURANCE = "INSURANCE"


class CredentialStatus(str, Enum):
    VALID = "VALID"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class BlockStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"
    CLOSED = "CLOSED"


# --------------------------------------------------------------------------
# Reservation (two independent state dimensions — PRD §2.9)
# --------------------------------------------------------------------------
class FulfillmentStatus(str, Enum):
    INTAKE = "INTAKE"
    MATCHING = "MATCHING"
    OFFERED = "OFFERED"
    CONFIRMED = "CONFIRMED"
    IN_SERVICE = "IN_SERVICE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"
    UNFULFILLED = "UNFULFILLED"


class BillingStatus(str, Enum):
    NOT_BILLABLE = "NOT_BILLABLE"
    ACCRUED = "ACCRUED"
    INVOICED = "INVOICED"
    PAID = "PAID"


class OfferStatus(str, Enum):
    PROPOSED = "PROPOSED"
    SELECTED = "SELECTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


# --------------------------------------------------------------------------
# Ledger / Invoicing
# --------------------------------------------------------------------------
class LedgerEntryType(str, Enum):
    RESERVE = "RESERVE"
    COMMIT = "COMMIT"
    RELEASE = "RELEASE"
    OVERAGE_ACCRUE = "OVERAGE_ACCRUE"
    OVERAGE_REVERSE = "OVERAGE_REVERSE"
    NO_SHOW_CHARGE = "NO_SHOW_CHARGE"
    LATE_CANCEL_CHARGE = "LATE_CANCEL_CHARGE"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


class InvoiceLineType(str, Enum):
    CARE_COPAY = "CARE_COPAY"
    CARE_OVERAGE = "CARE_OVERAGE"
    NO_SHOW_CHARGE = "NO_SHOW_CHARGE"
    LATE_CANCEL_CHARGE = "LATE_CANCEL_CHARGE"


# --------------------------------------------------------------------------
# Incident reporting
# --------------------------------------------------------------------------
class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    SUBSTANTIATED = "SUBSTANTIATED"
    DISMISSED = "DISMISSED"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class IncidentCategory(str, Enum):
    SUPERVISION = "SUPERVISION"
    FACILITY = "FACILITY"
    MEDICAL = "MEDICAL"
    CONDUCT = "CONDUCT"
    DOCUMENTATION = "DOCUMENTATION"


class QaAction(str, Enum):
    NONE = "NONE"
    PROBATION = "PROBATION"
    SUSPENSION = "SUSPENSION"
    DEPROVISION = "DEPROVISION"


class RenewalRiskBand(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


# --------------------------------------------------------------------------
# Entity TypedDicts
#
# Every resource carries id + created_at.  Most also carry updated_at and
# version (PRD §2.5).  UsageLedgerEntry and InvoiceLine are append-only and
# expose ONLY id + created_at — no updated_at, no version.
# --------------------------------------------------------------------------
class Employer(TypedDict):
    id: str
    name: str
    industry_code: str
    contract_status: str
    fiscal_year_start_month: int
    invoicing_cycle: str
    admin_fee_pct: float
    overage_billing_enabled: bool
    adult_elder_extension_enabled: bool
    accrued_overage_cents_current_period: int
    ytd_billed_cents: int
    created_at: str
    updated_at: str
    version: int


class BenefitPlan(TypedDict):
    id: str
    employer_id: str
    plan_code: str
    status: str
    annual_use_limit_days: int
    copay_center_cents_per_day: int
    copay_in_home_cents_per_hour: int
    in_home_min_billable_hours: float
    eligible_dependent_types: List[str]
    max_dependents_per_reservation: int
    overage_rate_center_cents_per_day: int
    overage_rate_in_home_cents_per_hour: int
    cancellation_window_hours: int
    no_show_charge_cents: int
    effective_from: str
    effective_to: Optional[str]
    superseded_by_plan_id: Optional[str]
    enrolled_employee_count: int
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict):
    id: str
    employer_id: str
    benefit_plan_id: str
    employee_external_id: str
    user_id: str
    email: str
    full_name: str
    employment_status: str
    eligibility_status: str
    entitlement_days_used: float
    entitlement_days_reserved: float
    no_show_strike_count: int
    created_at: str
    updated_at: str
    version: int


class Dependent(TypedDict):
    id: str
    employee_id: str
    full_name: str
    dependent_type: str
    date_of_birth: str
    relationship: str
    care_notes: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict):
    id: str
    provider_name: str
    owner_user_id: str
    care_mode: str
    market_code: str
    postal_code: str
    daily_capacity_slots: int
    max_concurrent_assignments: int
    same_day_available: bool
    network_status: str
    quality_score: float
    lifetime_quality_score: float
    substantiated_incident_count: int
    completed_reservation_count: int
    last_status_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Credential(TypedDict):
    id: str
    provider_id: str
    credential_type: str
    issued_on: str
    expires_on: str
    verified_by: str
    status: str
    revoked_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CapacityBlock(TypedDict):
    id: str
    provider_id: str
    start_time_utc: str
    end_time_utc: str
    service_date: str
    total_slots: int
    reserved_slots: int
    committed_slots: int
    block_status: str
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    employee_id: str
    benefit_plan_id: str
    plan_version_pinned: int
    requested_care_mode: str
    market_code: str
    care_start_utc: str
    care_end_utc: str
    care_date: str
    dependent_ids: List[str]
    dependent_count: int
    dependent_type_mix: str
    required_seats: int
    cancellation_deadline_utc: str
    fulfillment_status: str
    billing_status: str
    matched_provider_id: Optional[str]
    matched_capacity_block_id: Optional[str]
    confirmation_code: Optional[str]
    excluded_provider_ids: List[str]
    unfulfilled_reason_code: Optional[str]
    cancel_reason_code: Optional[str]
    actual_start_utc: Optional[str]
    actual_end_utc: Optional[str]
    billable_hours_provisional: float
    billable_hours_final: Optional[float]
    days_charged_provisional: float
    days_charged_final: Optional[float]
    covered_days: float
    overage_days: float
    overage_tier_multiplier: float
    copay_cents: int
    overage_cents: int
    penalty_cents: int
    created_at: str
    updated_at: str
    version: int


class MatchOffer(TypedDict):
    id: str
    reservation_id: str
    provider_id: str
    rank_score: float
    rank_position: int
    quality_component: float
    capacity_component: float
    mode_component: float
    continuity_component: float
    probation_penalty_applied: bool
    remaining_slots_at_offer: int
    offer_status: str
    offer_expires_at: str
    reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EmployerInvoice(TypedDict):
    id: str
    employer_id: str
    period_start: str
    period_end: str
    invoice_status: str
    copay_cents: int
    overage_cents: int
    penalty_cents: int
    subtotal_cents: int
    admin_fee_cents: int
    total_cents: int
    line_count: int
    reservation_count: int
    issued_at: Optional[str]
    paid_amount_cents: int
    void_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IncidentReport(TypedDict):
    id: str
    provider_id: str
    reservation_id: Optional[str]
    severity: str
    category: str
    narrative: str
    incident_status: str
    qa_action: str
    reported_at: str
    reported_by_user_id: str
    reviewed_by: Optional[str]
    resolution_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- Append-only records: id + created_at only (no updated_at, no version) ---
class UsageLedgerEntry(TypedDict):
    id: str
    employee_id: str
    reservation_id: str
    entry_type: str
    days_delta: float
    cents_delta: int
    benefit_year_start: str
    effective_at: str
    memo: str
    created_at: str


class InvoiceLine(TypedDict):
    id: str
    employer_invoice_id: str
    reservation_id: str
    employee_id: str
    line_type: str
    quantity: float
    unit_cents: int
    amount_cents: int
    created_at: str
