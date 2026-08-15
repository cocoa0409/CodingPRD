"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    CUSTOMER_SERVICE_REP = "CustomerServiceRep"
    ELIGIBILITY_SPECIALIST = "EligibilitySpecialist"
    PROGRAM_ADMIN = "ProgramAdmin"
    FIELD_CREW = "FieldCrew"


class ServiceStatus(str, Enum):
    CONNECTED = "CONNECTED"
    DISCONNECT_PENDING = "DISCONNECT_PENDING"
    DISCONNECTED = "DISCONNECTED"


class ProtectionStatus(str, Enum):
    UNPROTECTED = "UNPROTECTED"
    WEATHER_MORATORIUM = "WEATHER_MORATORIUM"
    MEDICAL_MORATORIUM = "MEDICAL_MORATORIUM"


class DelinquencyTier(str, Enum):
    CURRENT = "CURRENT"
    DELINQUENT = "DELINQUENT"
    SEVERELY_DELINQUENT = "SEVERELY_DELINQUENT"


class BenefitTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"
    INELIGIBLE = "INELIGIBLE"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    DOCS_PENDING = "DOCS_PENDING"
    VERIFIED = "VERIFIED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class EnrollmentStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    TERMINATED = "TERMINATED"


class DpaStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DEFAULTED = "DEFAULTED"
    COMPLETED = "COMPLETED"
    BROKEN = "BROKEN"
    CANCELLED = "CANCELLED"


class ForgivenessCreditStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class CertificateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class OrderStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    BLOCKED = "BLOCKED"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"


class FundStatus(str, Enum):
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class AllocationStatus(str, Enum):
    PLEDGED = "PLEDGED"
    DISBURSED = "DISBURSED"
    RELEASED = "RELEASED"


class ReferralStatus(str, Enum):
    INITIATED = "INITIATED"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"


class IncomeMeasure(str, Enum):
    ANNUALIZED_CURRENT_MONTH = "ANNUALIZED_CURRENT_MONTH"
    ANNUAL_GROSS = "ANNUAL_GROSS"


class CustomerAccount(TypedDict, total=False):
    id: str
    service_address: str
    service_class: str
    heating_fuel_type: str
    deposit_held_cents: int
    arrearage_balance_cents: int
    current_charges_balance_cents: int
    credit_balance_cents: int
    arrearage_since: Optional[str]
    reconnection_fee_due_cents: int
    reconnection_fee_base_cents: int
    reconnection_fee_surcharge_cents: int
    reconnection_deposit_topup_cents: int
    reconnection_surcharge_applied: bool
    service_status: str
    protection_status: str
    delinquency_tier: str
    last_activity_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AssistanceApplication(TypedDict, total=False):
    id: str
    account_id: str
    household_size: int
    gross_annual_income_cents: int
    current_month_income_cents: int
    income_source: str
    status: str
    submitted_by_user_id: str
    reviewed_by_user_id: Optional[str]
    docs_requested: bool
    documents_received: bool
    provisional_benefit_tier: str
    benefit_tier: Optional[str]
    income_measure_used: str
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AssistanceEnrollment(TypedDict, total=False):
    id: str
    account_id: str
    application_id: str
    tier: str
    discount_pct: int
    status: str
    activated_on: Optional[str]
    recert_due_on: Optional[str]
    lapsed_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeferredPaymentAgreement(TypedDict, total=False):
    id: str
    account_id: str
    status: str
    covered_arrearage_cents: int
    down_payment_required_cents: int
    down_payment_received_cents: int
    installment_count: int
    installment_amount_cents: int
    final_installment_amount_cents: int
    forgiveness_pool_cents: int
    forgiven_posted_cents: int
    projected_forgiveness_cents: int
    paid_to_arrearage_cents: int
    remaining_balance_cents: int
    installments_settled_count: int
    on_time_payment_count: int
    missed_payment_count: int
    activated_on: Optional[str]
    first_installment_due_on: Optional[str]
    defaulted_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    """Immutable posting record (PRD §2.5): id + created_at only, no version/updated_at."""
    id: str
    account_id: str
    dpa_id: Optional[str]
    amount_cents: int
    tender_type: str
    paid_at: str
    applied_breakdown: dict
    installments_settled_count: int
    on_time: Optional[bool]
    credit_accrued_cents: int
    created_at: str


class ForgivenessCredit(TypedDict, total=False):
    id: str
    dpa_id: str
    installment_number: int
    amount_cents: int
    status: str
    posted_at: str
    reversed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MedicalCertificate(TypedDict, total=False):
    id: str
    account_id: str
    physician_name: str
    physician_license_number: str
    condition_class: str
    effective_from: str
    effective_to: str
    renewal_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ShutoffOrder(TypedDict, total=False):
    id: str
    account_id: str
    reason: str
    scheduled_date: str
    status: str
    origin: str
    blocked_reason: Optional[str]
    executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FundingSource(TypedDict, total=False):
    id: str
    name: str
    funder_type: str
    fiscal_year: int
    appropriated_cents: int
    priority_rank: int
    eligible_tiers: List[str]
    requires_completed_referral: bool
    status: str
    pledged_cents: int
    disbursed_cents: int
    released_cents: int
    available_cents: int
    created_at: str
    updated_at: str
    version: int


class FundAllocation(TypedDict, total=False):
    id: str
    funding_source_id: str
    account_id: str
    enrollment_id: str
    amount_cents: int
    status: str
    batch_id: str
    allocation_sequence: int
    created_at: str
    updated_at: str
    version: int


class AssistanceReferral(TypedDict, total=False):
    id: str
    account_id: str
    agency_code: str
    status: str
    initiated_on: str
    completed_on: Optional[str]
    created_at: str
    updated_at: str
    version: int
