"""Domain types: entity TypedDicts, status enums, role enum.

Per PRD §2.5, all resources carry `id` + `created_at`; everything except
RiskAssessment and KRIObservation additionally carries `updated_at` + `version`.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    RISK_MANAGER = "RiskManager"
    RISK_OWNER = "RiskOwner"
    CONTROL_OWNER = "ControlOwner"
    BOARD_REPORTER = "BoardReporter"
    INTERNAL_AUDITOR = "InternalAuditor"


# ---------------------------------------------------------------------------
# Status enums (PRD §3.1–§3.8)
# ---------------------------------------------------------------------------

class RiskStatus(str, Enum):
    DRAFT = "DRAFT"
    IDENTIFIED = "IDENTIFIED"
    ASSESSED = "ASSESSED"
    TREATMENT = "TREATMENT"
    MONITORING = "MONITORING"
    REASSESSMENT = "REASSESSMENT"
    CLOSED = "CLOSED"


class Band(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AssessmentKind(str, Enum):
    INHERENT = "INHERENT"
    RESIDUAL = "RESIDUAL"


class ControlStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    UNDER_REVIEW = "UNDER_REVIEW"
    RETIRED = "RETIRED"


class MappingStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class AppetiteStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    RETIRED = "RETIRED"


class BreachStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    ACCEPTED = "ACCEPTED"


class PlanStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    IN_PROGRESS = "IN_PROGRESS"
    OVERDUE = "OVERDUE"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class PlanPriority(str, Enum):
    STANDARD = "STANDARD"
    URGENT = "URGENT"


class ActionStatus(str, Enum):
    PENDING = "PENDING"
    DONE = "DONE"


class KriLifecycleStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class KriBreachStatus(str, Enum):
    NORMAL = "NORMAL"
    AMBER_BREACH = "AMBER_BREACH"
    RED_BREACH = "RED_BREACH"


class KriDirection(str, Enum):
    ABOVE = "ABOVE"
    BELOW = "BELOW"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    CANCELLED = "CANCELLED"


class ReportVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class EmergingStatus(str, Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    PROMOTED = "PROMOTED"
    DISMISSED = "DISMISSED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

# common_fields: true
class TaxonomyCategory(TypedDict, total=False):
    id: str
    name: str
    parent_category_id: Optional[str]
    weight_factor: float
    current_tolerance_score: Optional[int]
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Risk(TypedDict, total=False):
    id: str
    category_id: str
    source_emerging_risk_id: Optional[str]
    title: str
    description: Optional[str]
    owner_user_id: str
    treatment_budget_cents: int
    status: str
    likelihood: Optional[int]
    impact: Optional[int]
    inherent_score: Optional[int]
    inherent_band: Optional[str]
    residual_score: Optional[int]
    residual_band: Optional[str]
    reserved_treatment_cents: int
    available_treatment_cents: int
    kri_alert: bool
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only event record (PRD §2.5)
class RiskAssessment(TypedDict, total=False):
    id: str
    created_at: str
    risk_id: str
    kind: str
    likelihood: Optional[int]
    impact: Optional[int]
    notes: Optional[str]
    inherent_score: Optional[int]
    residual_score: Optional[int]
    breach_created: bool
    # NO updated_at, NO version


# common_fields: true
class Control(TypedDict, total=False):
    id: str
    name: str
    description: Optional[str]
    effectiveness_pct: float
    max_mapped_risks: int
    mapped_active_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class RiskControlMapping(TypedDict, total=False):
    id: str
    risk_id: str
    control_id: str
    coverage_weight: float
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class AppetiteStatement(TypedDict, total=False):
    id: str
    category_id: str
    tolerance_score: int
    acceptance_cap_score: int
    effective_from: str
    effective_to: str
    status: str
    created_by: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class ToleranceBreach(TypedDict, total=False):
    id: str
    risk_id: str
    appetite_statement_id: str
    residual_at_breach: int
    status: str
    rationale: Optional[str]
    review_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class TreatmentPlan(TypedDict, total=False):
    id: str
    risk_id: str
    title: str
    budget_cents: int
    due_date: str
    owner_user_id: str
    proposer_user_id: str
    status: str
    priority: str
    extension_count: int
    progress_pct: float
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class TreatmentAction(TypedDict, total=False):
    id: str
    plan_id: str
    title: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class KRI(TypedDict, total=False):
    id: str
    category_id: str
    name: str
    direction: str
    amber_threshold: float
    red_threshold: float
    min_observation_interval_days: int
    unit: Optional[str]
    status: str
    current_breach_status: str
    last_observation_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable event record (PRD §2.5)
class KRIObservation(TypedDict, total=False):
    id: str
    created_at: str
    kri_id: str
    observed_value: float
    observed_at: str
    resulting_breach_status: str
    # NO updated_at, NO version


# common_fields: true
class RiskReport(TypedDict, total=False):
    id: str
    period_start: str
    period_end: str
    variant: str
    status: str
    heat_score_total: float
    category_breakdown: List[dict]
    band_counts: dict
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class EmergingRisk(TypedDict, total=False):
    id: str
    category_id: str
    title: str
    description: Optional[str]
    scenario_severity: int
    scenario_probability: int
    stress_factor: float
    scenario_score: int
    status: str
    created_at: str
    updated_at: str
    version: int
