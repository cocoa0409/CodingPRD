"""Domain types: status enums, role enum and entity TypedDicts.

Field names mirror the PRD exactly. The three append-only records
(`ServiceEvent`, `PriorityScore`, `CommitteeVote`) carry only `id` and
`created_at` — for them both `updated_at` and `version` are absent.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────────────────────


class UserRole(str, Enum):
    CAPITAL_PLANNER = "CapitalPlanner"
    CLINICAL_REQUESTER = "ClinicalRequester"
    FACILITY_DIRECTOR = "FacilityDirector"
    COMMITTEE_MEMBER = "CommitteeMember"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"


# ─── Enumerations ─────────────────────────────────────────────────────


class Region(str, Enum):
    NORTH = "NORTH"
    SOUTH = "SOUTH"
    EAST = "EAST"
    WEST = "WEST"


class Modality(str, Enum):
    CT = "CT"
    MRI = "MRI"
    CATH_LAB = "CATH_LAB"
    ULTRASOUND = "ULTRASOUND"
    LAB = "LAB"
    SURGICAL = "SURGICAL"


class AssetStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    DERATED = "DERATED"
    REPLACEMENT_PENDING = "REPLACEMENT_PENDING"
    DECOMMISSIONED = "DECOMMISSIONED"


class DispositionStatus(str, Enum):
    NONE = "NONE"
    HELD_FOR_TRADE_IN = "HELD_FOR_TRADE_IN"
    TRADED_IN = "TRADED_IN"
    SCRAPPED = "SCRAPPED"


class ServiceEventCategory(str, Enum):
    PM = "PM"
    CORRECTIVE = "CORRECTIVE"
    RECALL = "RECALL"
    UPGRADE = "UPGRADE"


class CycleStatus(str, Enum):
    DRAFT = "DRAFT"
    INTAKE_OPEN = "INTAKE_OPEN"
    SCORING = "SCORING"
    ALLOCATED = "ALLOCATED"
    COMMITTED = "COMMITTED"


class AllocationMethod(str, Enum):
    PRO_RATA = "PRO_RATA"
    RANK_ORDERED = "RANK_ORDERED"


class AllocationPosture(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    SUPERSEDED = "SUPERSEDED"


class ContingencyStatus(str, Enum):
    HELD = "HELD"
    RELEASED = "RELEASED"


class RequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    SCREENED = "SCREENED"
    RETURNED = "RETURNED"
    SCORED = "SCORED"
    IN_COMMITTEE = "IN_COMMITTEE"
    APPROVED = "APPROVED"
    DEFERRED = "DEFERRED"
    REJECTED = "REJECTED"
    FUNDED = "FUNDED"
    IMPLEMENTED = "IMPLEMENTED"
    AUDITED = "AUDITED"
    WITHDRAWN = "WITHDRAWN"


class ScreeningDecision(str, Enum):
    ACCEPT = "ACCEPT"
    RETURN = "RETURN"


class ScoreReason(str, Enum):
    CYCLE_SCORING = "CYCLE_SCORING"
    ASSET_CONDITION_CHANGE = "ASSET_CONDITION_CHANGE"
    DEPARTMENT_PENALTY_CHANGE = "DEPARTMENT_PENALTY_CHANGE"


class MemberSeat(str, Enum):
    CHAIR = "CHAIR"
    FINANCE = "FINANCE"
    CLINICAL = "CLINICAL"
    FACILITIES = "FACILITIES"
    SAFETY_OFFICER = "SAFETY_OFFICER"


class VoteChoice(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    ABSTAIN = "ABSTAIN"
    VETO = "VETO"


class GpoTier(str, Enum):
    SMALL = "SMALL"
    MID = "MID"
    LARGE = "LARGE"


class QuoteStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    WITHDRAWN = "WITHDRAWN"
    SUPERSEDED = "SUPERSEDED"


class ProjectRecordStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class ConstructionStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    DESIGN = "DESIGN"
    PERMIT = "PERMIT"
    BUILD = "BUILD"
    COMPLETE = "COMPLETE"


class EquipmentStatus(str, Enum):
    AWAITING_DELIVERY = "AWAITING_DELIVERY"
    DELIVERED = "DELIVERED"
    INSTALLED = "INSTALLED"
    COMMISSIONED = "COMMISSIONED"


class AuditStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    UNDERPERFORMING = "UNDERPERFORMING"


class AssetDisposition(str, Enum):
    TRADED_IN = "TRADED_IN"
    SCRAPPED = "SCRAPPED"


# ─── Entities carrying id / created_at / updated_at / version ─────────


class Facility(TypedDict):
    id: str
    name: str
    code: str
    region: str
    max_concurrent_construction: int
    active_asset_count: int
    created_at: str
    updated_at: str
    version: int


class Department(TypedDict):
    id: str
    facility_id: str
    name: str
    modality_scope: str
    utilization_penalty_points: int
    underperformance_flag: bool
    created_at: str
    updated_at: str
    version: int


class EquipmentAsset(TypedDict):
    id: str
    facility_id: str
    department_id: str
    modality: str
    model_name: str
    install_date: str
    expected_life_years: int
    acquisition_cost_cents: int
    oem_support_end_date: str
    status: str
    disposition_status: str
    trade_in_credit_applied_cents: int
    age_years: float
    nominal_ruls_score: float
    adjusted_ruls_score: float
    service_penalty_points: float
    corrective_count_24m: int
    downtime_hours_24m: float
    unresolved_recall: bool
    ruls_as_of: str
    created_at: str
    updated_at: str
    version: int


class CapitalCycle(TypedDict):
    id: str
    plan_year: int
    plan_year_start: str
    total_capital_cents: int
    contingency_pct: float
    facility_contingency_pct: float
    status: str
    allocation_method: Optional[str]
    allocated_by_user_id: Optional[str]
    system_contingency_cents: int
    distributable_cents: int
    unallocated_cents: int
    contingency_drawn_cents: int
    allocation_count: int
    exhausted_allocation_count: int
    scored_count: int
    expedited_count: int
    created_at: str
    updated_at: str
    version: int


class FacilityAllocation(TypedDict):
    id: str
    cycle_id: str
    facility_id: str
    demand_cents: int
    weighted_score: float
    allocated_cents: int
    contingency_reserve_cents: int
    released_contingency_cents: int
    committed_cents: int
    available_cents: int
    contingency_status: str
    posture: str
    created_at: str
    updated_at: str
    version: int


class ReplacementRequest(TypedDict):
    id: str
    cycle_id: str
    department_id: str
    asset_id: str
    clinical_justification: str
    current_annual_volume: int
    projected_annual_volume: int
    estimated_capital_cents: int
    facility_modification_cents: int
    annual_service_contract_cents: int
    disposable_unit_cents: int
    sponsor_member_id: Optional[str]
    regulatory_mandate_flag: bool
    mandate_deadline: Optional[str]
    status: str
    safety_driver: float
    growth_driver: float
    regulatory_driver: float
    eos_driver: float
    composite_score: float
    expedited: bool
    revision_count: int
    return_count: int
    budgetary_operating_5y_cents: Optional[int]
    budgetary_tco_cents: Optional[int]
    negotiated_operating_5y_cents: Optional[int]
    negotiated_tco_cents: Optional[int]
    baseline_year1_opex_cents: Optional[int]
    funded_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class CommitteeMember(TypedDict):
    id: str
    full_name: str
    seat: str
    voting_weight: int
    facility_id: Optional[str]
    department_id: Optional[str]
    active: bool
    created_at: str
    updated_at: str
    version: int


class GpoContract(TypedDict):
    id: str
    contract_code: str
    vendor_name: str
    small_tier_pct: float
    mid_tier_pct: float
    large_tier_pct: float
    tier_mid_floor_cents: int
    tier_large_floor_cents: int
    multi_unit_addendum_pct: float
    trade_in_cap_pct: float
    expires_on: str
    created_at: str
    updated_at: str
    version: int


class VendorQuote(TypedDict):
    id: str
    request_id: str
    gpo_contract_id: str
    vendor_name: str
    list_price_cents: int
    service_escalation_pct: float
    valid_until: str
    trade_in_asset_id: Optional[str]
    trade_in_offer_cents: int
    multi_unit_count: int
    warranty_months: int
    gpo_tier: str
    gpo_discount_cents: int
    multi_unit_addendum_cents: int
    subtotal_cents: int
    trade_in_credit_cents: int
    net_capital_cents: int
    negotiation_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InstallationProject(TypedDict):
    id: str
    request_id: str
    facility_id: str
    department_id: str
    downtime_start: str
    downtime_end: str
    construction_required: bool
    construction_start: Optional[str]
    construction_end: Optional[str]
    predecessor_project_id: Optional[str]
    record_status: str
    construction_status: str
    equipment_status: str
    go_live_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UtilizationAudit(TypedDict):
    id: str
    request_id: str
    installation_project_id: str
    audit_window_start: str
    audit_window_end: str
    projected_annual_volume_snapshot: int
    baseline_year1_opex_snapshot: int
    actual_annual_volume: Optional[int]
    actual_annual_opex_cents: Optional[int]
    volume_attainment_pct: Optional[float]
    opex_variance_pct: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Append-only records: id + created_at only ────────────────────────


class ServiceEvent(TypedDict):
    id: str
    asset_id: str
    event_date: str
    category: str
    downtime_hours: float
    cost_cents: int
    recall_resolved: bool
    notes: Optional[str]
    created_at: str


class PriorityScore(TypedDict):
    id: str
    request_id: str
    sequence: int
    reason: str
    asset_adjusted_ruls_snapshot: float
    corrective_count_snapshot: int
    safety_driver: float
    growth_driver: float
    regulatory_driver: float
    eos_driver: float
    department_penalty_points: int
    composite_score: float
    expedited: bool
    created_at: str


class CommitteeVote(TypedDict):
    id: str
    request_id: str
    member_id: str
    vote: str
    counted_weight: int
    superseded: bool
    rationale: Optional[str]
    created_at: str


APPEND_ONLY_ENTITIES: List[str] = ["ServiceEvent", "PriorityScore", "CommitteeVote"]
