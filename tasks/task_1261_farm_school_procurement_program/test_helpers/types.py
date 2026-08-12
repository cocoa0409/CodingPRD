"""Domain types: entity TypedDicts, status enums, role enum (PRD sections 2-4)."""
from enum import Enum
from typing import Optional, TypedDict


class ProgramYearStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class FarmStatus(str, Enum):
    APPLIED = "APPLIED"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"


class ComplianceDocStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class DocType(str, Enum):
    SAFETY_CERT = "SAFETY_CERT"
    LIABILITY_INSURANCE = "LIABILITY_INSURANCE"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class OfferingStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"


class AgreementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    SIGNED = "SIGNED"
    AMENDMENT_PROPOSED = "AMENDMENT_PROPOSED"
    FULFILLING = "FULFILLING"
    COMPLETED = "COMPLETED"
    BREACHED = "BREACHED"
    CANCELLED = "CANCELLED"


class AmendmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class DeliveryStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    DISPUTED = "DISPUTED"
    CLOSED_REJECTED = "CLOSED_REJECTED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class ClaimStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    AWARDED = "AWARDED"
    PARTIALLY_AWARDED = "PARTIALLY_AWARDED"
    REJECTED = "REJECTED"
    RECONCILED = "RECONCILED"
    REVERSED = "REVERSED"


class ClaimLineAuditStatus(str, Enum):
    PENDING = "PENDING"
    ALLOWED = "ALLOWED"
    DISALLOWED = "DISALLOWED"


class SubstitutionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class PreferenceModel(str, Enum):
    LINEAR = "LINEAR"
    TIERED = "TIERED"


class UserRole(str, Enum):
    DISTRICT_PROGRAM_ADMIN = "DistrictProgramAdmin"
    FARM_MANAGER = "FarmManager"
    KITCHEN_MANAGER = "KitchenManager"
    CLAIMS_COORDINATOR = "ClaimsCoordinator"
    STATE_GRANT_AUDITOR = "StateGrantAuditor"


class ProgramYear(TypedDict, total=False):
    id: str
    school_year_label: str
    start_date: str
    end_date: str
    local_radius_miles: int
    preference_model: str
    grant_award_cents: int
    local_spend_target_pct: float
    grant_drawn_cents: int
    grant_remaining_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Farm(TypedDict, total=False):
    id: str
    legal_name: str
    contact_email: str
    distance_miles_to_hub: int
    acres: float
    is_small_farm: bool
    required_insurance_cents: int
    compliance_posture: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceDocument(TypedDict, total=False):
    id: str
    farm_id: str
    doc_type: str
    issuer: str
    coverage_cents: Optional[int]
    effective_on: str
    expires_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    name: str
    category: str
    unit: str
    season_start_week: int
    season_end_week: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FarmProductOffering(TypedDict, total=False):
    id: str
    farm_id: str
    program_year_id: str
    product_id: str
    price_cents_per_unit: int
    max_weekly_quantity: int
    harvest_start_week: int
    harvest_end_week: int
    is_local_eligible: bool
    preference_points: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MenuForecastLine(TypedDict, total=False):
    id: str
    program_year_id: str
    product_id: str
    week_number: int
    planned_quantity: int
    reserved_quantity: int
    uncovered_quantity: int
    created_at: str
    updated_at: str
    version: int


class Kitchen(TypedDict, total=False):
    id: str
    name: str
    created_at: str
    updated_at: str
    version: int


# Receiving windows are immutable after creation and carry only id + created_at
# (PRD section 2.4): no updated_at, no version.
class ReceivingWindow(TypedDict, total=False):
    id: str
    kitchen_id: str
    weekday: str
    start_minute: int
    end_minute: int
    capacity_deliveries: int
    created_at: str


class PlantingAgreement(TypedDict, total=False):
    id: str
    program_year_id: str
    offering_id: str
    committed_quantity: int
    harvest_start_week: int
    harvest_end_week: int
    unit_price_cents: int
    local_eligible: bool
    delivered_quantity: int
    remaining_quantity: int
    released_quantity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AgreementAmendment(TypedDict, total=False):
    id: str
    agreement_id: str
    proposed_by_role: str
    new_committed_quantity: Optional[int]
    new_unit_price_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Delivery(TypedDict, total=False):
    id: str
    agreement_id: str
    kitchen_id: str
    window_id: str
    delivery_date: str
    quantity: int
    week_number: int
    accepted_quantity: Optional[int]
    rejection_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    farm_id: str
    delivery_id: str
    agreement_id: str
    invoice_number: str
    quantity_billed: int
    unit_price_cents: int
    subtotal_cents: int
    incentive_credit_cents: int
    total_cents: int
    farm_compliant_at_delivery: bool
    approved_by_user_id: Optional[str]
    paid_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReimbursementClaim(TypedDict, total=False):
    id: str
    program_year_id: str
    period_month: str
    submitted_by_user_id: Optional[str]
    total_claimed_cents: int
    total_awarded_cents: int
    match_provisional_cents: int
    match_final_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ClaimLine(TypedDict, total=False):
    id: str
    claim_id: str
    invoice_id: str
    claimed_amount_cents: int
    audit_status: str
    disallowed_amount_cents: int
    disallowance_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SubstitutionRequest(TypedDict, total=False):
    id: str
    forecast_line_id: str
    substitute_product_id: str
    quantity: int
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int
