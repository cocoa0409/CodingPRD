"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1 — all five roles use opaque operator identifiers)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    TENANT_REP = "TenantRep"
    LEASING_MANAGER = "LeasingManager"
    PROJECT_MANAGER = "ProjectManager"
    ASSET_MANAGER = "AssetManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# ---------------------------------------------------------------------------
# Field enums
# ---------------------------------------------------------------------------

class UseType(str, Enum):
    DISTRIBUTION = "DISTRIBUTION"
    MANUFACTURING = "MANUFACTURING"
    COLD_STORAGE = "COLD_STORAGE"
    R_AND_D = "R_AND_D"


class ParcelType(str, Enum):
    EXISTING = "EXISTING"
    LAND_BANK = "LAND_BANK"


class EnvironmentalPhase(str, Enum):
    PHASE_I_COMPLETE = "PHASE_I_COMPLETE"
    PHASE_II_REQUIRED = "PHASE_II_REQUIRED"
    REMEDIATED = "REMEDIATED"


class CommissionBasis(str, Enum):
    GROSS_AGGREGATE = "GROSS_AGGREGATE"
    NET_EFFECTIVE = "NET_EFFECTIVE"


class PricingMethod(str, Enum):
    YIELD_ON_COST = "YIELD_ON_COST"
    MARKET_COMP = "MARKET_COMP"


class MilestoneType(str, Enum):
    PERMITS = "PERMITS"
    SHELL = "SHELL"
    TI = "TI"
    SUBSTANTIAL_COMPLETION = "SUBSTANTIAL_COMPLETION"


class ReviewType(str, Enum):
    ENVIRONMENTAL = "ENVIRONMENTAL"
    ZONING_USE = "ZONING_USE"


class ReviewOutcome(str, Enum):
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"


class BrokerSide(str, Enum):
    TENANT_REP = "TENANT_REP"
    LANDLORD_REP = "LANDLORD_REP"


# ---------------------------------------------------------------------------
# Status enums (state machines, PRD §3)
# ---------------------------------------------------------------------------

class RequirementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SATISFIED = "SATISFIED"
    WITHDRAWN = "WITHDRAWN"


class SiteStatus(str, Enum):
    LISTED = "LISTED"
    RESERVED = "RESERVED"
    COMMITTED = "COMMITTED"
    LEASED = "LEASED"


class TourStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class LoiStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class PlanStatus(str, Enum):
    SCHEMATIC = "SCHEMATIC"
    PRICED = "PRICED"
    APPROVED = "APPROVED"
    DELIVERED = "DELIVERED"


class MilestoneStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETE = "COMPLETE"


class OptionStatus(str, Enum):
    GRANTED = "GRANTED"
    EXERCISED = "EXERCISED"
    EXPIRED = "EXPIRED"
    RELEASED = "RELEASED"


class ReviewStatus(str, Enum):
    PENDING = "PENDING"
    IN_REVIEW = "IN_REVIEW"
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"


class InvoiceStatus(str, Enum):
    ACCRUED = "ACCRUED"
    INVOICED = "INVOICED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    DISPUTED = "DISPUTED"


# ---------------------------------------------------------------------------
# Entity TypedDicts — every entity carries id, created_at, updated_at,
# version (PRD §2.4: "no entity in this system omits any of them")
# ---------------------------------------------------------------------------

class TenantRequirement(TypedDict, total=False):
    id: str
    tenant_name: str
    use_type: str
    min_sf: int
    max_sf: int
    min_clear_height_ft: float
    min_dock_doors: int
    min_power_amps: int
    min_yard_depth_ft: int
    target_submarket: str
    required_delivery_date: str
    tenant_rep_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Site(TypedDict, total=False):
    id: str
    site_name: str
    submarket: str
    parcel_type: str
    total_sf: int
    clear_height_ft: float
    dock_doors: int
    power_amps: int
    yard_depth_ft: int
    zoning_designation: str
    environmental_phase: str
    asking_rate_psf: float
    reserved_sf: int
    available_sf: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Tour(TypedDict, total=False):
    id: str
    site_id: str
    requirement_id: str
    tenant_rep_id: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LOI(TypedDict, total=False):
    id: str
    requirement_id: str
    site_id: str
    term_years: int
    leased_sf: int
    base_rate_psf: float
    ti_allowance_psf: float
    free_rent_months: int
    escalation_pct: float
    commission_basis: str
    aggregate_rent_total: float
    net_effective_rent_psf: float
    negotiation_round: int
    rent_commencement_date: Optional[str]
    abatement_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BuildToSuitPlan(TypedDict, total=False):
    id: str
    loi_id: str
    hard_cost_total: float
    soft_cost_total: float
    contingency_pct: float
    pricing_method: str
    provisional_base_rate_psf: float
    commission_cost_estimate: float
    total_project_cost: float
    converted_base_rate_psf: float
    yield_on_cost: float
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryMilestone(TypedDict, total=False):
    id: str
    plan_id: str
    milestone_type: str
    planned_date: str
    actual_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ExpansionOption(TypedDict, total=False):
    id: str
    loi_id: str
    land_site_id: str
    option_sf: int
    window_open_date: str
    window_close_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceReview(TypedDict, total=False):
    id: str
    site_id: str
    requirement_id: str
    review_type: str
    findings: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CommissionInvoice(TypedDict, total=False):
    id: str
    loi_id: str
    broker_side: str
    commission_basis: str
    commission_basis_amount: float
    total_commission: float
    installment_1_amount: float
    installment_2_amount: float
    installment_1_paid: bool
    installment_2_paid: bool
    installment_2_due: bool
    dispute_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
