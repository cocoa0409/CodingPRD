"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class ProjectStatus(str, Enum):
    SETUP = "SETUP"
    BUYOUT_OPEN = "BUYOUT_OPEN"
    BUYOUT_COMPLETE = "BUYOUT_COMPLETE"


class TradePackageStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    UNDER_LEVELING = "UNDER_LEVELING"
    BUYOUT_IN_PROGRESS = "BUYOUT_IN_PROGRESS"
    AWARDED = "AWARDED"


class BidStatus(str, Enum):
    RECEIVED = "RECEIVED"
    PLACED = "PLACED"
    WITHDRAWN = "WITHDRAWN"
    AWARDED = "AWARDED"


class ScopeGapStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    DEFERRED = "DEFERRED"


class SubcontractStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_AWARD = "PENDING_AWARD"
    AWARDED = "AWARDED"
    ISSUED = "ISSUED"
    EXECUTED = "EXECUTED"
    DEFAULTED = "DEFAULTED"
    REPLACED = "REPLACED"
    TERMINATED = "TERMINATED"


class ScheduleOfValuesStatus(str, Enum):
    DRAFT = "DRAFT"
    BALANCED = "BALANCED"
    REJECTED = "REJECTED"
    REVISED = "REVISED"
    APPROVED = "APPROVED"


class ChangeOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class InsuranceCertificateStatus(str, Enum):
    ISSUED = "ISSUED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class BondingPolicy(str, Enum):
    REQUIRED = "REQUIRED"
    PER_TRADE_RISK = "PER_TRADE_RISK"
    WAIVED = "WAIVED"


class BondingRequirement(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    SURETY_BOND = "SURETY_BOND"
    SUBGUARD = "SUBGUARD"
    PENDING_DECISION = "PENDING_DECISION"


class InsuranceStatus(str, Enum):
    MISSING = "MISSING"
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"
    EXPIRED_CERT_ONLY = "EXPIRED_CERT_ONLY"


class ComplianceVerdict(str, Enum):
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"
    COMPLIANT_BY_GAP_ANALYSIS = "COMPLIANT_BY_GAP_ANALYSIS"


class EvaluationBasis(str, Enum):
    FULL_ENDORSEMENTS = "FULL_ENDORSEMENTS"
    GAP_ANALYSIS = "GAP_ANALYSIS"


class BuyoutPosture(str, Enum):
    FAVORABLE = "FAVORABLE"
    NEUTRAL = "NEUTRAL"
    UNFAVORABLE = "UNFAVORABLE"


class UserRole(str, Enum):
    GC_ADMIN = "GCAdmin"
    BUYOUT_LEAD = "BuyoutLead"
    OPERATIONS_MANAGER = "OperationsManager"
    PROJECT_EXECUTIVE = "ProjectExecutive"
    PROJECT_MANAGER = "ProjectManager"
    VICE_PRESIDENT = "VicePresident"
    ESTIMATOR = "Estimator"
    SUPPLIER_DIVERSITY = "SupplierDiversity"


# --- Entity TypedDicts ---
# Project, TradePackage, Bid, ScopeGap, Subcontract, InsuranceCertificate,
# BondDecision, ScheduleOfValues, ChangeOrder carry id/created_at/updated_at/version.
# NegotiationRound is append-only: id + created_at only (no updated_at, no version).


class Project(TypedDict, total=False):
    id: str
    name: str
    project_number: str
    estimated_budget_cents: int
    buyout_target_savings_pct: float
    status: str
    current_time_utc: str
    created_at: str
    updated_at: str
    version: int


class TradePackage(TypedDict, total=False):
    id: str
    project_id: str
    trade_code: str
    title: str
    estimated_budget_cents: int
    budgeted_contingency_cents: int
    spec_section: str
    bid_due_at: str
    bonding_policy: str
    status: str
    awarded_value_cents: int
    buyout_savings_cents: int
    buyout_posture: str
    created_at: str
    updated_at: str
    version: int


class Bid(TypedDict, total=False):
    id: str
    trade_package_id: str
    bidder_name: str
    contact_email: str
    base_bid_cents: int
    alternates: List[Dict[str, Any]]
    allowances: List[Dict[str, Any]]
    bid_received_at: str
    leveled_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ScopeGap(TypedDict, total=False):
    id: str
    trade_package_id: str
    category: str
    description: str
    estimated_impact_cents: int
    resolution_kind: str
    priced_amount_cents: int
    waived_by_role: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Subcontract(TypedDict, total=False):
    id: str
    trade_package_id: str
    subcontractor_name: str
    source_bid_id: str
    replaces_subcontract_id: Optional[str]
    replacement_subcontract_id: Optional[str]
    flow_down_terms: str
    insurance_requirements_snapshot: Dict[str, Any]
    payment_terms: Dict[str, Any]
    change_authority_limits: List[Dict[str, Any]]
    contract_value_cents: int
    cumulative_co_cents: int
    negotiation_round: int
    insurance_status: str
    bonding_requirement: str
    sov_status: str
    default_flag: bool
    default_recorded_at: str
    estimated_replacement_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class NegotiationRound(TypedDict, total=False):
    # Append-only: id + created_at only, NO updated_at / version.
    id: str
    created_at: str
    subcontract_id: str
    round_index: int
    proposed_value_cents: int
    allowance_dispositions: List[Dict[str, Any]]
    alternate_selections: List[Dict[str, Any]]
    note: str
    recorded_at: str


class InsuranceCertificate(TypedDict, total=False):
    id: str
    subcontract_id: str
    certificate_number: str
    gl_occurrence_cents: int
    gl_aggregate_cents: int
    auto_cents: int
    umbrella_cents: int
    workers_comp: str
    ai_endorsed: bool
    wos_endorsed: bool
    ptd_endorsed: bool
    pollution_cents: int
    expires_on: str
    evaluation_basis: str
    compliance_verdict: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BondDecision(TypedDict, total=False):
    id: str
    subcontract_id: str
    trade_risk_score: int
    trade_history: str
    decision: str
    premium_cents: int
    decided_by_user_id: str
    decision_rationale: str
    created_at: str
    updated_at: str
    version: int


class ScheduleOfValues(TypedDict, total=False):
    id: str
    subcontract_id: str
    revision_number: int
    lines: List[Dict[str, Any]]
    status: str
    approved_at: str
    created_at: str
    updated_at: str
    version: int


class ChangeOrder(TypedDict, total=False):
    id: str
    subcontract_id: str
    description: str
    amount_cents: int
    initiating_role: str
    approval_roles_received: List[str]
    created_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int
