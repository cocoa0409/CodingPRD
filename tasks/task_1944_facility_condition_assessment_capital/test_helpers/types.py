"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    CONSULTANT = "Consultant"
    FACILITY_MANAGER = "FacilityManager"
    CAPITAL_PLANNER = "CapitalPlanner"
    APPROVER = "Approver"


class SystemCategory(str, Enum):
    HVAC = "HVAC"
    ROOF = "ROOF"
    ENVELOPE = "ENVELOPE"
    ELECTRICAL = "ELECTRICAL"
    PLUMBING = "PLUMBING"
    FIRE_PROTECTION = "FIRE_PROTECTION"
    CONVEYANCE = "CONVEYANCE"
    INTERIOR = "INTERIOR"
    SITE = "SITE"
    STRUCTURE = "STRUCTURE"


class AssetSystemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REASSESSED = "REASSESSED"
    RETIRED = "RETIRED"


class RemediationStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    CORRECTED = "CORRECTED"
    DEFERRED = "DEFERRED"


class VerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class CapitalPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"


class FundingScenarioStatus(str, Enum):
    CONFIGURED = "CONFIGURED"
    RUN = "RUN"
    SUPERSEDED = "SUPERSEDED"


class FundingStatus(str, Enum):
    FUNDED = "FUNDED"
    UNFUNDED = "UNFUNDED"
    REMOVED = "REMOVED"


class RefreshCycleStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class RefreshHealth(str, Enum):
    NO_DATA = "NO_DATA"
    STALE = "STALE"
    CRITICAL = "CRITICAL"
    WATCH = "WATCH"
    GOOD = "GOOD"


# --- Entities carrying the standard common fields (id/created_at/updated_at/version) ---

class Client(TypedDict):
    id: str
    name: str
    contact_email: str
    created_at: str
    updated_at: str
    version: int


class Facility(TypedDict):
    id: str
    client_id: str
    name: str
    address: str
    gross_square_feet: int
    current_replacement_value_cents: int
    backlog_cost_cents: int
    facility_condition_index: float
    assessment_epoch: int
    created_at: str
    updated_at: str
    version: int


class AssetSystem(TypedDict):
    id: str
    facility_id: str
    system_category: str
    name: str
    install_year: int
    design_life_years: int
    replacement_cost_cents: int
    condition_rating: int
    remaining_useful_life_years: int
    status: str
    last_assessed_epoch: int
    created_at: str
    updated_at: str
    version: int


class Deficiency(TypedDict):
    id: str
    asset_system_id: str
    description: str
    cost_estimate_cents: int
    severity: int
    urgency: int
    is_code_violation: bool
    is_accessibility_violation: bool
    recommended_year: int
    priority_score: float
    remediation_status: str
    verification_status: str
    created_at: str
    updated_at: str
    version: int


class CapitalPlan(TypedDict):
    id: str
    facility_id: str
    title: str
    start_year: int
    horizon_years: int
    status: str
    total_programmed_cents: int
    created_at: str
    updated_at: str
    version: int


class FundingScenario(TypedDict):
    id: str
    capital_plan_id: str
    name: str
    annual_budget_cents: int
    escalation_rate: float
    status: str
    created_at: str
    updated_at: str
    version: int


class PlanLineItem(TypedDict):
    id: str
    capital_plan_id: str
    deficiency_id: str
    funding_scenario_id: str
    planned_year: int
    escalated_cost_cents: int
    funding_status: str
    project_bundle_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProjectBundle(TypedDict):
    id: str
    capital_plan_id: str
    name: str
    phase_number: int
    bundled_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class RefreshCycle(TypedDict):
    id: str
    facility_id: str
    epoch: int
    status: str
    opened_at: str
    created_at: str
    updated_at: str
    version: int


# Append-only audit record: carries ONLY id + created_at (no updated_at, no version).
class ConditionSnapshot(TypedDict):
    id: str
    asset_system_id: str
    condition_rating: int
    remaining_useful_life_years: int
    epoch: int
    note: Optional[str]
    created_at: str
