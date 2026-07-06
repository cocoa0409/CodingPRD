"""Domain types for the Foundation Repair API: entity TypedDicts, status enums, role enum.

Every entity in this system is a top-level resource carrying id, created_at, updated_at,
and version (PRD §2.4). Job is the one entity that exposes two independent state dimensions
(fulfillment_status and permit_status) instead of a single status field (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Status enums ─────────────────────────────────────────────────────────────

class RegionCode(str, Enum):
    NORTH = "NORTH"
    SOUTH = "SOUTH"
    EAST = "EAST"
    WEST = "WEST"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SoilClass(str, Enum):
    STABLE = "STABLE"
    EXPANSIVE = "EXPANSIVE"
    UNSTABLE = "UNSTABLE"


class EngineeringScopeStatus(str, Enum):
    DRAFT = "DRAFT"
    ENGINEERED = "ENGINEERED"
    SUPERSEDED = "SUPERSEDED"


class AccessDifficulty(str, Enum):
    EASY = "EASY"
    MODERATE = "MODERATE"
    HARD = "HARD"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    REVISED = "REVISED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class FinancingPlan(str, Enum):
    CASH = "CASH"
    PLAN_12 = "PLAN_12"
    PLAN_60 = "PLAN_60"


class JobFulfillmentStatus(str, Enum):
    UNSCHEDULED = "UNSCHEDULED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class JobPermitStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PermitStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PermitType(str, Enum):
    STANDARD = "STANDARD"
    STRUCTURAL = "STRUCTURAL"
    ENGINEERED = "ENGINEERED"


class PermitDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class WarrantyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOID = "VOID"


class MaintenanceVisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_INFO = "NEEDS_INFO"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    RESOLVED = "RESOLVED"


class CoverageVariant(str, Enum):
    FULL = "FULL"
    PRORATED = "PRORATED"


class UserRole(str, Enum):
    SALES_AGENT = "SalesAgent"
    FIELD_ENGINEER = "FieldEngineer"
    OPS_COORDINATOR = "OpsCoordinator"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    CUSTOMER = "Customer"
    ADMIN = "Admin"


# ─── Entity TypedDicts (all carry the four common fields, PRD §2.4) ────────────

class Lead(TypedDict):
    id: str
    customer_name: str
    property_address: str
    contact_email: str
    region_code: str
    financing_balance_cents: int
    active_visit_count: int
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    lead_id: str
    scheduled_at: str
    soil_class: Optional[str]
    crack_severity: Optional[int]
    max_crack_width_mm: Optional[float]
    settlement_inches: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class EngineeringScope(TypedDict):
    id: str
    lead_id: str
    inspection_id: str
    pier_count: int
    anchor_count: int
    avg_pier_depth_ft: float
    access_difficulty: str
    supplemental_engineering: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict):
    id: str
    lead_id: str
    scope_id: str
    financing_plan: str
    subtotal_cents: int
    financing_fee_cents: int
    total_cents: int
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Job(TypedDict):
    id: str
    lead_id: str
    quote_id: Optional[str]
    source_claim_id: Optional[str]
    crew_id: Optional[str]
    scheduled_start: Optional[str]
    scheduled_end: Optional[str]
    piers_installed: Optional[int]
    adjustment_inches: Optional[float]
    final_subtotal_cents: Optional[int]
    final_total_cents: Optional[int]
    fulfillment_status: str
    permit_status: str
    created_at: str
    updated_at: str
    version: int


class Crew(TypedDict):
    id: str
    crew_name: str
    region_code: str
    booked_minutes: int
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    job_id: str
    permit_type: str
    decision: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Warranty(TypedDict):
    id: str
    lead_id: str
    job_id: str
    holder_name: str
    activated_at: str
    transfer_count: int
    remediation_count: int
    covered_pier_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MaintenanceVisit(TypedDict):
    id: str
    warranty_id: str
    crew_id: Optional[str]
    scheduled_date: str
    tightening_turns: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    warranty_id: str
    description: str
    reported_settlement_inches: float
    settlement_cents: Optional[int]
    coverage_variant: Optional[str]
    remediation_job_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
