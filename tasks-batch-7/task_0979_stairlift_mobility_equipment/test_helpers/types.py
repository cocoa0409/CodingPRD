"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow the PRD: resources with standard lifecycle metadata carry
id + created_at + updated_at + version; ProductModel and AuditEvent are leaner
and carry only id + created_at (PRD section on resource identity).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class CustomerStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ACTIVE = "ACTIVE"
    FORMER = "FORMER"


class HomeAssessmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    MEASURED = "MEASURED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class StaircaseKind(str, Enum):
    STRAIGHT = "STRAIGHT"
    CURVED = "CURVED"
    OUTDOOR = "OUTDOOR"


class ProductKind(str, Enum):
    STAIRLIFT = "STAIRLIFT"
    VERTICAL_LIFT = "VERTICAL_LIFT"
    SCOOTER = "SCOOTER"


class ConditionGrade(str, Enum):
    NEW = "NEW"
    REFURB_A = "REFURB_A"
    REFURB_B = "REFURB_B"
    REFURB_C = "REFURB_C"
    RETIRED = "RETIRED"


class EquipmentUnitStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    RESERVED = "RESERVED"
    INSTALLED = "INSTALLED"
    IN_SERVICE = "IN_SERVICE"
    REMOVED = "REMOVED"
    RETIRED = "RETIRED"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    ACCEPTED = "ACCEPTED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class AcquisitionMode(str, Enum):
    RENTAL = "RENTAL"
    PURCHASE = "PURCHASE"


class FundingSourceKind(str, Enum):
    STATE_GRANT = "STATE_GRANT"
    INSURANCE = "INSURANCE"
    CHARITY = "CHARITY"
    VETERAN_BENEFIT = "VETERAN_BENEFIT"


class FundingApplicationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    PARTIALLY_APPROVED = "PARTIALLY_APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class AgreementStatus(str, Enum):
    PENDING_FUNDING = "PENDING_FUNDING"
    FUNDED = "FUNDED"
    SCHEDULED = "SCHEDULED"
    INSTALLED = "INSTALLED"
    ACTIVE = "ACTIVE"
    REMOVAL_REQUESTED = "REMOVAL_REQUESTED"
    REMOVED = "REMOVED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class InstallJobStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ServicePlanTier(str, Enum):
    BASIC = "BASIC"
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class ServicePlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    CANCELLED = "CANCELLED"


class ClaimKind(str, Enum):
    MECHANICAL = "MECHANICAL"
    ELECTRICAL = "ELECTRICAL"
    STRUCTURAL = "STRUCTURAL"
    WEAR_AND_TEAR = "WEAR_AND_TEAR"


class WarrantyClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"


class RemovalJobStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CUSTOMER = "Customer"
    SALES_REP = "SalesRep"
    ASSESSOR = "Assessor"
    ASSESSMENT_REVIEWER = "AssessmentReviewer"
    FUNDING_OFFICER = "FundingOfficer"
    INSTALL_COORDINATOR = "InstallCoordinator"
    INVENTORY_MANAGER = "InventoryManager"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class Customer(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    home_region_code: str
    status: str
    lifetime_outstanding_cents: int
    created_at: str
    updated_at: str
    version: int


class HomeAssessment(TypedDict, total=False):
    id: str
    customer_id: str
    scheduled_date: str
    status: str
    staircase_kind: str
    stair_rise_mm: int
    stair_run_mm: int
    stair_width_mm: int
    landing_clearance_mm: int
    has_outdoor_exposure: bool
    electrical_outlet_within_2m: bool
    measured_at: str
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProductModel(TypedDict, total=False):
    # Reference data: carries only id + created_at; no updated_at, no version.
    id: str
    model_code: str
    kind: str
    supports_curved: bool
    supports_outdoor: bool
    min_stair_width_mm: int
    base_purchase_price_cents: int
    monthly_rental_rate_cents: int
    install_labor_hours: int
    created_at: str


class EquipmentUnit(TypedDict, total=False):
    id: str
    model_code: str
    serial_number: str
    condition_grade: str
    status: str
    acquired_at: str
    lifetime_rental_months: int
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict, total=False):
    id: str
    customer_id: str
    home_assessment_id: str
    model_code: str
    acquisition_mode: str
    status: str
    revision_number: int
    provisional_total_cents: int
    issued_total_cents: int
    issued_at: Optional[str]
    expires_at: Optional[str]
    valid_rail_length_m: float
    created_at: str
    updated_at: str
    version: int


class FundingApplication(TypedDict, total=False):
    id: str
    quote_id: str
    source_kind: str
    requested_cents: int
    status: str
    approved_cents: int
    decision_reason: Optional[str]
    priority_rank: int
    created_at: str
    updated_at: str
    version: int


class Agreement(TypedDict, total=False):
    id: str
    quote_id: str
    customer_id: str
    mode: str
    status: str
    equipment_unit_id: str
    list_price_cents: int
    committed_rental_months: Optional[int]
    funding_applied_cents: int
    paid_to_date_cents: int
    liability_waiver_signed: bool
    version_anchor_quote_revision: int
    created_at: str
    updated_at: str
    version: int


class InstallJob(TypedDict, total=False):
    id: str
    agreement_id: str
    technician_crew_id: str
    scheduled_start_utc: str
    scheduled_end_utc: str
    status: str
    measured_labor_hours: Optional[int]
    installed_rail_length_m: Optional[float]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServicePlan(TypedDict, total=False):
    id: str
    agreement_id: str
    tier: str
    status: str
    monthly_fee_cents: int
    next_service_due_utc: str
    coverage_cap_cents: int
    coverage_used_cents: int
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    agreement_id: str
    service_plan_id: str
    claim_kind: str
    claimed_cents: int
    status: str
    approved_cents: int
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemovalJob(TypedDict, total=False):
    id: str
    agreement_id: str
    technician_crew_id: str
    scheduled_start_utc: str
    scheduled_end_utc: str
    status: str
    buyback_offered_cents: int
    condition_grade_at_removal: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuditEvent(TypedDict, total=False):
    # Append-only log row: carries only id + created_at.
    id: str
    entity_kind: str
    entity_id: str
    event_kind: str
    actor_role: str
    payload: dict
    created_at: str
