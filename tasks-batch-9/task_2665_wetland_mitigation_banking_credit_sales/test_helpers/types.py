"""Domain types for the Wetland Mitigation Banking API.

Entity TypedDicts, status enumerations and the role enumeration, all named
exactly as the PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles (PRD §2.1) ─────────────────────────────────

class UserRole(str, Enum):
    SPONSOR = "Sponsor"
    PERMITTEE = "Permittee"
    IRT_MEMBER = "IRTMember"
    IRT_CHAIR = "IRTChair"
    PROGRAM_ADMIN = "ProgramAdmin"


# ─── Enumerations ─────────────────────────────────────

class LegalEntityType(str, Enum):
    PRIVATE_ENTREPRENEURIAL = "PRIVATE_ENTREPRENEURIAL"
    PUBLIC_AGENCY = "PUBLIC_AGENCY"
    NGO = "NGO"


class Agency(str, Enum):
    USACE = "USACE"
    EPA = "EPA"
    USFWS = "USFWS"
    STATE_DEQ = "STATE_DEQ"
    TRIBAL = "TRIBAL"


class RosterStatus(str, Enum):
    SEATED = "SEATED"
    RECUSED = "RECUSED"


class HgmClass(str, Enum):
    RIVERINE = "RIVERINE"
    DEPRESSIONAL = "DEPRESSIONAL"
    SLOPE = "SLOPE"
    FLATS = "FLATS"
    ESTUARINE = "ESTUARINE"


class BankStatus(str, Enum):
    DRAFT = "DRAFT"
    PROSPECTUS_REVIEW = "PROSPECTUS_REVIEW"
    INSTRUMENT_EXECUTED = "INSTRUMENT_EXECUTED"
    MONITORING = "MONITORING"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class SalesPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    SOLD_OUT = "SOLD_OUT"
    FROZEN = "FROZEN"


class ProspectusStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class VotePosition(str, Enum):
    CONCUR = "CONCUR"
    OBJECT = "OBJECT"
    ABSTAIN = "ABSTAIN"


class WorkPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    RETURNED = "RETURNED"


class InvasiveControlProtocol(str, Enum):
    MECHANICAL = "MECHANICAL"
    HERBICIDE = "HERBICIDE"
    INTEGRATED = "INTEGRATED"


class StratumCode(str, Enum):
    UPLAND_BUFFER = "UPLAND_BUFFER"
    EMERGENT_MARSH = "EMERGENT_MARSH"
    FORESTED_WETLAND = "FORESTED_WETLAND"
    SCRUB_SHRUB = "SCRUB_SHRUB"
    OPEN_WATER = "OPEN_WATER"


class StandardCode(str, Enum):
    HYDROPERIOD_DAYS = "HYDROPERIOD_DAYS"
    INVASIVE_COVER_PCT = "INVASIVE_COVER_PCT"
    NATIVE_COVER_PCT = "NATIVE_COVER_PCT"
    STEM_DENSITY_PER_ACRE = "STEM_DENSITY_PER_ACRE"


class Comparator(str, Enum):
    GTE = "GTE"
    LTE = "LTE"


class MilestoneCode(str, Enum):
    INSTRUMENT_EXECUTION = "INSTRUMENT_EXECUTION"
    CONSTRUCTION_COMPLETE = "CONSTRUCTION_COMPLETE"
    PERF_YEAR_3 = "PERF_YEAR_3"
    PERF_YEAR_5 = "PERF_YEAR_5"
    PERF_YEAR_10 = "PERF_YEAR_10"


class MilestoneStatus(str, Enum):
    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    APPROVED = "APPROVED"
    DEFERRED = "DEFERRED"


class ReviewStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    RETURNED = "RETURNED"


class ComplianceStatus(str, Enum):
    UNEVALUATED = "UNEVALUATED"
    PASS = "PASS"
    PARTIAL = "PARTIAL"
    FAIL = "FAIL"


class RemedialStatus(str, Enum):
    OPEN = "OPEN"
    WORK_SUBMITTED = "WORK_SUBMITTED"
    REINSPECTION = "REINSPECTION"
    CLEARED = "CLEARED"
    FAILED = "FAILED"


class ReviewDecision(str, Enum):
    ACCEPT = "ACCEPT"
    RETURN = "RETURN"


class WorkPlanDecision(str, Enum):
    APPROVE = "APPROVE"
    RETURN = "RETURN"


class InspectionOutcome(str, Enum):
    CLEARED = "CLEARED"
    NOT_CLEARED = "NOT_CLEARED"


class SaleStatus(str, Enum):
    QUOTED = "QUOTED"
    RESERVED = "RESERVED"
    EXECUTED = "EXECUTED"
    ASSIGNED = "ASSIGNED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class ServiceAreaTier(str, Enum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"


class CancelledReason(str, Enum):
    BUYER_WITHDREW = "BUYER_WITHDREW"
    SPONSOR_WITHDREW = "SPONSOR_WITHDREW"
    BANK_POSTURE_RESTRICTED = "BANK_POSTURE_RESTRICTED"
    HOLD_EXPIRED = "HOLD_EXPIRED"
    IRT_REVERSAL = "IRT_REVERSAL"


class LedgerEntryType(str, Enum):
    GENERATED = "GENERATED"
    RELEASED = "RELEASED"
    HOLD_PLACED = "HOLD_PLACED"
    HOLD_RELEASED = "HOLD_RELEASED"
    SOLD = "SOLD"
    SALE_REVERSED = "SALE_REVERSED"
    ASSIGNED = "ASSIGNED"


class SourceEntityType(str, Enum):
    MITIGATION_BANK = "MITIGATION_BANK"
    RELEASE_MILESTONE = "RELEASE_MILESTONE"
    CREDIT_SALE = "CREDIT_SALE"
    REMEDIAL_ACTION = "REMEDIAL_ACTION"


# ─── Entity shapes ────────────────────────────────────
# Resources carry id + created_at + updated_at + version (PRD §2.4).
# Prospectus votes and credit ledger entries are immutable events and carry
# only id + created_at.

class Sponsor(TypedDict):
    id: str
    legal_name: str
    legal_entity_type: str
    performance_bond_cents: int
    banks_count: int
    good_standing: bool
    created_at: str
    updated_at: str
    version: int


class Permittee(TypedDict):
    id: str
    organization_name: str
    permit_number: str
    impact_huc8_code: str
    required_credits: float
    deposited_cents: int
    escrow_balance_cents: int
    assigned_credits: float
    unmet_requirement_credits: float
    created_at: str
    updated_at: str
    version: int


class IRTMember(TypedDict):
    id: str
    member_name: str
    agency: str
    veto_authority: bool
    roster_status: str
    created_at: str
    updated_at: str
    version: int


class MitigationBank(TypedDict):
    id: str
    sponsor_id: str
    site_name: str
    site_huc8_code: str
    service_area_huc8_codes: List[str]
    hgm_class: str
    annual_stewardship_cost_cents: int
    status: str
    sales_posture: str
    total_authorized_credits: float
    credits_released: float
    credits_sold: float
    credits_on_hold: float
    credits_available: float
    stewardship_required_cents: int
    stewardship_funded_cents: int
    easement_recorded: bool
    easement_recorded_at: Optional[str]
    easement_deed_reference: Optional[str]
    deferral_count: int
    open_quote_count: int
    instrument_executed_at: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Prospectus(TypedDict):
    id: str
    bank_id: str
    objective_summary: str
    proposed_credits: float
    status: str
    revision_round: int
    submitted_at: Optional[str]
    review_opened_at: Optional[str]
    concur_count: int
    object_count: int
    abstain_count: int
    veto_recorded: bool
    decision_recorded_by: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProspectusVote(TypedDict):
    id: str
    prospectus_id: str
    irt_member_id: str
    revision_round: int
    position: str
    comment: Optional[str]
    is_veto: bool
    created_at: str


class WorkPlan(TypedDict):
    id: str
    bank_id: str
    hydrology_restoration_acres: float
    planting_acres: float
    invasive_control_acres: float
    invasive_control_protocol: str
    credit_strata: List[dict]
    performance_standards: List[dict]
    total_planned_credits: float
    status: str
    submitted_at: Optional[str]
    decided_at: Optional[str]
    return_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PerformanceStandard(TypedDict):
    id: str
    bank_id: str
    standard_code: str
    comparator: str
    threshold_value: float
    weight: float
    effective_from_year: int
    created_at: str
    updated_at: str
    version: int


class ReleaseMilestone(TypedDict):
    id: str
    bank_id: str
    predecessor_milestone_id: Optional[str]
    milestone_code: str
    release_pct: float
    window_start: str
    window_end: str
    status: str
    provisional_release_credits: float
    final_release_credits: float
    attainment_factor_applied: Optional[float]
    claimed_at: Optional[str]
    approved_at: Optional[str]
    deferred_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MonitoringReport(TypedDict):
    id: str
    bank_id: str
    monitoring_year: int
    window_start: str
    window_end: str
    measurements: List[dict]
    review_status: str
    compliance_status: str
    attainment_score: Optional[float]
    failed_standard_codes: List[str]
    reviewed_by_member_id: Optional[str]
    submitted_at: Optional[str]
    reviewed_at: Optional[str]
    return_count: int
    created_at: str
    updated_at: str
    version: int


class RemedialAction(TypedDict):
    id: str
    monitoring_report_id: str
    deferred_milestone_id: Optional[str]
    verified_by_member_id: Optional[str]
    status: str
    round_number: int
    corrective_scope: str
    held_credits: float
    due_at: str
    opened_at: str
    work_submitted_at: Optional[str]
    cleared_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CreditSale(TypedDict):
    id: str
    bank_id: str
    permittee_id: str
    credits_requested: float
    impact_huc8_code: str
    service_area_tier: str
    status: str
    quoted_demand_index: float
    quoted_price_cents: int
    executed_price_cents: Optional[int]
    hold_start_at: Optional[str]
    hold_expires_at: Optional[str]
    executed_at: Optional[str]
    assigned_at: Optional[str]
    assignment_reference: Optional[str]
    cancelled_reason: Optional[str]
    cancelled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CreditLedgerEntry(TypedDict):
    id: str
    bank_id: str
    sequence_number: int
    entry_type: str
    delta_credits: float
    balance_after: float
    source_entity_type: str
    source_id: str
    memo: str
    created_at: str


class CreditForecast(TypedDict):
    demand_index: float
    trailing_quarter_average_credits: float
    forecast_horizon_credits: float
    projected_quarters_to_sellout: int
    credits_available: float
    credits_released: float
    credits_sold: float
    credits_on_hold: float
