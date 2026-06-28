"""Domain types: entity TypedDicts, status enums, role enum.

All field names and enum values are taken verbatim from the PRD contract.
"""
from enum import Enum
from typing import TypedDict, List


# --------------------------------------------------------------------------
# Role enum
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    HOMEOWNER = "Homeowner"
    COORDINATOR = "Coordinator"
    ELECTRICIAN = "Electrician"
    UTILITY_REVIEWER = "UtilityReviewer"
    ANONYMOUS = "Anonymous"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class InstallJobWorkflowStatus(str, Enum):
    CREATED = "CREATED"
    ASSESSED = "ASSESSED"
    QUOTED = "QUOTED"
    SCHEDULED = "SCHEDULED"
    INSTALLED = "INSTALLED"
    ACTIVATED = "ACTIVATED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class InstallJobComplianceStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    PERMIT_PENDING = "PERMIT_PENDING"
    CLEARED = "CLEARED"
    BLOCKED = "BLOCKED"


class ElectricianStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SiteAssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"


class AssessmentMethod(str, Enum):
    STANDARD_220_83 = "STANDARD_220_83"
    LOAD_STUDY_220_87 = "LOAD_STUDY_220_87"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class PermitApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CORRECTIONS_REQUESTED = "CORRECTIONS_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class InterconnectionRequestStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class DispatchAssignmentStatus(str, Enum):
    BOOKED = "BOOKED"
    EN_ROUTE = "EN_ROUTE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class IncentiveProgramKind(str, Enum):
    FEDERAL_45W = "FEDERAL_45W"
    UTILITY_REBATE = "UTILITY_REBATE"


class UtilityProgramTier(str, Enum):
    BASIC = "BASIC"
    PREMIUM = "PREMIUM"


class IncentiveClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PAID = "PAID"
    REVERSED = "REVERSED"


class PanelUpgradeReferralStatus(str, Enum):
    OPEN = "OPEN"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    COMPLETED = "COMPLETED"


class WarrantyTicketStatus(str, Enum):
    OPEN = "OPEN"
    DIAGNOSING = "DIAGNOSING"
    AWAITING_PARTS = "AWAITING_PARTS"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


# --------------------------------------------------------------------------
# Entity TypedDicts
# --------------------------------------------------------------------------
# Entities with full common fields carry id + created_at + updated_at + version.
# ChargerProduct is immutable: id + created_at only (no updated_at, no version).

class Homeowner(TypedDict):
    id: str
    email: str
    full_name: str
    state_code: str
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict):
    id: str
    homeowner_id: str
    address_line: str
    state_code: str
    utility_territory_code: str
    service_voltage: int
    main_breaker_amps: int
    floor_area_sqft: int
    created_at: str
    updated_at: str
    version: int


class Electrician(TypedDict):
    id: str
    full_name: str
    license_state_code: str
    max_daily_jobs: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable catalog entry, no updated_at / version
class ChargerProduct(TypedDict):
    id: str
    sku: str
    name: str
    rated_amps: int
    required_circuit_amps: int
    msrp_cents: int
    created_at: str


class InstallJob(TypedDict):
    id: str
    property_id: str
    charger_product_sku: str
    workflow_status: str
    compliance_status: str
    requires_panel_upgrade: bool
    activation_pairing_code: str
    created_at: str
    updated_at: str
    version: int


class SiteAssessment(TypedDict):
    id: str
    property_id: str
    install_job_id: str
    assessment_method: str
    declared_fixed_appliance_va: int
    max_measured_demand_va: int
    existing_demand_va: int
    spare_capacity_va: int
    charger_fits: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict):
    id: str
    install_job_id: str
    labor_cents: int
    parts_line_cents: List[int]
    base_subtotal_cents: int
    discount_cents: int
    tax_cents: int
    permit_fee_cents: int
    quote_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PermitApplication(TypedDict):
    id: str
    install_job_id: str
    jurisdiction_code: str
    status: str
    correction_rounds: int
    created_at: str
    updated_at: str
    version: int


class InterconnectionRequest(TypedDict):
    id: str
    install_job_id: str
    utility_territory_code: str
    requested_load_amps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DispatchAssignment(TypedDict):
    id: str
    install_job_id: str
    electrician_id: str
    window_date: str
    window_start_minute: int
    window_end_minute: int
    status: str
    created_at: str
    updated_at: str
    version: int


class IncentiveClaim(TypedDict):
    id: str
    install_job_id: str
    program_kind: str
    eligible_cost_cents: int
    utility_program_tier: str
    includes_panel_upgrade: bool
    award_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PanelUpgradeReferral(TypedDict):
    id: str
    install_job_id: str
    recommended_main_amps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyTicket(TypedDict):
    id: str
    install_job_id: str
    summary: str
    reopen_count: int
    status: str
    created_at: str
    updated_at: str
    version: int
