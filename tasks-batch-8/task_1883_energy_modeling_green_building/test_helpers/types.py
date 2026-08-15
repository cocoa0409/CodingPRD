"""Domain types: entity TypedDicts, status enums, role enum (PRD §2-§3)."""
from enum import Enum
from typing import Optional, TypedDict


# ─── Roles (PRD §2.1) ─────────────────────────────────

class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    PROJECT_ADMINISTRATOR = "ProjectAdministrator"
    ENERGY_MODELER = "EnergyModeler"
    DOCUMENTATION_SPECIALIST = "DocumentationSpecialist"
    COMMISSIONING_AGENT = "CommissioningAgent"
    CERTIFICATION_REVIEWER = "CertificationReviewer"
    ANY = "Any"


# ─── Status / enum types (PRD §3) ─────────────────────

class Specialty(str, Enum):
    MANAGEMENT = "MANAGEMENT"
    MODELING = "MODELING"
    DOCUMENTATION = "DOCUMENTATION"
    COMMISSIONING = "COMMISSIONING"


class RatingSystem(str, Enum):
    LEED_BD_C = "LEED_BD_C"
    LEED_ID_C = "LEED_ID_C"
    LEED_O_M = "LEED_O_M"


class CompliancePath(str, Enum):
    PRESCRIPTIVE = "PRESCRIPTIVE"
    PERFORMANCE = "PERFORMANCE"


class CertificationLevel(str, Enum):
    NONE = "NONE"
    CERTIFIED = "CERTIFIED"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class ProjectStatus(str, Enum):
    REGISTERED = "REGISTERED"
    STRATEGY_LOCKED = "STRATEGY_LOCKED"
    DESIGN_SUBMITTED = "DESIGN_SUBMITTED"
    DESIGN_REVIEWED = "DESIGN_REVIEWED"
    CONSTRUCTION_SUBMITTED = "CONSTRUCTION_SUBMITTED"
    CONSTRUCTION_REVIEWED = "CONSTRUCTION_REVIEWED"
    CERTIFIED = "CERTIFIED"
    PERFORMANCE_REPORTING = "PERFORMANCE_REPORTING"
    RECERTIFICATION_REVIEW = "RECERTIFICATION_REVIEW"
    LAPSED = "LAPSED"
    DENIED = "DENIED"


class CreditCategory(str, Enum):
    ENERGY_ATMOSPHERE = "ENERGY_ATMOSPHERE"
    MATERIALS = "MATERIALS"
    INDOOR_ENVIRONMENT = "INDOOR_ENVIRONMENT"
    WATER = "WATER"
    SUSTAINABLE_SITES = "SUSTAINABLE_SITES"
    INTEGRATIVE = "INTEGRATIVE"


class PhaseEligibility(str, Enum):
    DESIGN = "DESIGN"
    CONSTRUCTION = "CONSTRUCTION"
    BOTH = "BOTH"


class ModelType(str, Enum):
    BASELINE = "BASELINE"
    PROPOSED = "PROPOSED"


class ModelingStandard(str, Enum):
    ASHRAE_90_1_2016 = "ASHRAE_90_1_2016"
    ASHRAE_90_1_2019 = "ASHRAE_90_1_2019"


class ModelStatus(str, Enum):
    DRAFT = "DRAFT"
    LOCKED = "LOCKED"
    SUPERSEDED = "SUPERSEDED"


class AttemptStatus(str, Enum):
    SELECTED = "SELECTED"
    DOCUMENTATION_IN_PROGRESS = "DOCUMENTATION_IN_PROGRESS"
    READY_FOR_SUBMITTAL = "READY_FOR_SUBMITTAL"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CLARIFICATION_REQUESTED = "CLARIFICATION_REQUESTED"
    RESUBMITTED = "RESUBMITTED"
    AWARDED = "AWARDED"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    DROPPED = "DROPPED"


class CommentSeverity(str, Enum):
    CLARIFICATION = "CLARIFICATION"
    DEFICIENCY = "DEFICIENCY"


class CommentStatus(str, Enum):
    OPEN = "OPEN"
    ADDRESSED = "ADDRESSED"
    REOPENED = "REOPENED"
    ACCEPTED = "ACCEPTED"


class TaskType(str, Enum):
    OPR_DOCUMENT = "OPR_DOCUMENT"
    CX_PLAN = "CX_PLAN"
    FUNCTIONAL_TESTING = "FUNCTIONAL_TESTING"
    SYSTEMS_MANUAL = "SYSTEMS_MANUAL"
    CX_REPORT = "CX_REPORT"


class TaskStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    FAILED = "FAILED"


class IncentiveType(str, Enum):
    TAX_CREDIT = "TAX_CREDIT"
    GRANT = "GRANT"
    UTILITY_REBATE = "UTILITY_REBATE"


class ProjectIncentiveStatus(str, Enum):
    APPLIED = "APPLIED"
    APPROVED = "APPROVED"
    DISBURSED = "DISBURSED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


# ─── Entity TypedDicts (all carry the four common properties, PRD §2.4) ──

class TeamMember(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    specialty: str
    is_independent: bool
    created_at: str
    updated_at: str
    version: int


class CertificationProject(TypedDict, total=False):
    id: str
    project_name: str
    rating_system: str
    compliance_path: str
    gross_floor_area_sqft: int
    target_level: str
    fee_budget_cents: int
    administrator_id: str
    status: str
    fee_balance_cents: int
    points_pursued_total: int
    points_awarded_total: int
    projected_level: str
    conservative_level: str
    prerequisites_satisfied: bool
    certified_level: Optional[str]
    certified_at: Optional[str]
    plaque_marketing_rights_granted: bool
    created_at: str
    updated_at: str
    version: int


class CreditLibraryEntry(TypedDict, total=False):
    id: str
    credit_code: str
    title: str
    category: str
    points_possible: int
    is_prerequisite: bool
    phase_eligibility: str
    requires_energy_model: bool
    created_at: str
    updated_at: str
    version: int


class EnergyModel(TypedDict, total=False):
    id: str
    project_id: str
    model_type: str
    modeling_standard: str
    annual_energy_cost_modeled_cents: int
    annual_energy_cost_confirmed_only_cents: int
    includes_unconfirmed_measures: bool
    version_index: int
    created_by: str
    status: str
    improvement_pct_provisional: Optional[float]
    improvement_pct_final: Optional[float]
    created_at: str
    updated_at: str
    version: int


class CreditAttempt(TypedDict, total=False):
    id: str
    project_id: str
    credit_library_entry_id: str
    credit_code: str
    points_possible: int
    is_prerequisite: bool
    phase: str
    documentation_owner_id: str
    pinned_proposed_model_id: Optional[str]
    has_stale_model_pin: bool
    raw_points_earned: Optional[float]
    points_awarded: Optional[int]
    submission_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReviewComment(TypedDict, total=False):
    id: str
    credit_attempt_id: str
    round: int
    severity: str
    comment_text: str
    response_text: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CommissioningTask(TypedDict, total=False):
    id: str
    project_id: str
    task_type: str
    agent_id: str
    scheduled_start: str
    scheduled_end: str
    is_prerequisite_linked: bool
    outcome: Optional[str]
    result_notes: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class IncentiveProgram(TypedDict, total=False):
    id: str
    program_name: str
    incentive_type: str
    benefit_amount_cents: int
    minimum_certification_level: str
    is_combinable: bool
    created_at: str
    updated_at: str
    version: int


class ProjectIncentive(TypedDict, total=False):
    id: str
    project_id: str
    incentive_program_id: str
    claimed_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CostPremiumAnalysis(TypedDict, total=False):
    id: str
    project_id: str
    incremental_construction_cost_cents: int
    annual_energy_savings_cents: int
    incentive_total_cents: int
    net_cost_premium_cents: int
    simple_payback_years: float
    analysis_version: int
    created_at: str
    updated_at: str
    version: int


class PerformanceReport(TypedDict, total=False):
    id: str
    project_id: str
    period_start: str
    period_end: str
    actual_annual_energy_cost_cents: int
    performance_gap_pct: float
    within_tolerance: bool
    rejection_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
