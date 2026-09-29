"""Typed shapes for every resource the Property Improvement Plan Compliance API exposes.

The TypedDicts mirror the field sets described in the PRD. They are used for editor
support and for the shape assertions in ``assertions.py``; the API is exercised over
HTTP so nothing here is validated at runtime by the framework itself.

Note the deliberate asymmetry on ``ComplianceLedgerEntry``: a ledger row is
append-only and carries only ``id`` and ``created_at``, so neither ``updated_at``
nor ``version`` appears in its shape.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, TypedDict

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

UserRole = Literal["FranchiseeOwner", "BrandManager", "BrandInspector"]

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

FranchiseeStanding = Literal["GOOD", "WATCH", "DEFAULT", "TERMINATED_PORTFOLIO"]

FranchiseAgreementStatus = Literal["ACTIVE", "DEFAULT_NOTICED", "IN_DEFAULT", "TERMINATED"]

CompliancePosture = Literal["COMPLIANT", "AT_RISK", "IN_DEFAULT", "TERMINATED"]

TriggerType = Literal["POST_INSPECTION", "TRANSACTION_CHANGE_OF_OWNERSHIP", "RELICENSING"]

PlanStatus = Literal[
    "DRAFT",
    "ISSUED",
    "OWNER_ACKNOWLEDGED",
    "IN_EXECUTION",
    "READY_FOR_COMPLETION_INSPECTION",
    "COMPLETED",
    "TERMINATED",
    "WITHDRAWN",
]

PlanDisputeState = Literal[
    "NONE",
    "DISPUTE_OPEN",
    "DISPUTE_RESOLVED_UPHELD",
    "DISPUTE_RESOLVED_REVISED",
    "DISPUTE_RESOLVED_REMOVED",
]

ItemCategory = Literal["LIFE_SAFETY", "GUEST_FACING", "BACK_OF_HOUSE"]

ItemStatus = Literal[
    "SCOPED",
    "DEFERRED_PENDING_EXTENSION",
    "IN_PROGRESS",
    "WORK_COMPLETE",
    "PUNCH_FAIL",
    "ACCEPTED",
    "REMOVED_BY_DISPUTE",
    "VOIDED",
]

ExtensionStatus = Literal[
    "SUBMITTED",
    "NEEDS_MORE_JUSTIFICATION",
    "APPROVED",
    "APPROVED_PARTIAL",
    "DENIED",
]

ExtensionDecision = Literal["APPROVE", "DENY", "REQUEST_MORE_JUSTIFICATION"]

FinancingSource = Literal["RESERVE_DRAW", "TERM_LOAN", "OWNER_EQUITY", "MIXED"]

BudgetStatus = Literal[
    "DRAFT",
    "APPROVED",
    "LOCKED",
    "UNDERFUNDED",
    "SUPERSEDED",
    "CLOSED",
]

DrawStatus = Literal["REQUESTED", "BRAND_CONSENTED", "REJECTED", "DISBURSED", "REVERSED"]

DrawDecision = Literal["CONSENT", "REJECT"]

PhaseStatus = Literal["PLANNED", "ACTIVE", "CLOSED_OUT", "CANCELLED"]

ContractorTrade = Literal["FIRE_PROTECTION", "FF_AND_E", "MEP", "GENERAL"]

BookingStatus = Literal["BOOKED", "CANCELLED", "COMPLETED"]

InspectionType = Literal["SCOPING", "PROGRESS", "COMPLETION", "RE_INSPECTION"]

InspectionStatus = Literal["SCHEDULED", "PERFORMED", "SIGNED_OFF"]

DefectSeverity = Literal["MINOR", "MAJOR", "CRITICAL"]

PunchStatus = Literal["OPEN", "REMEDIATED", "VERIFIED_CLOSED", "WAIVED"]

PunchOutcome = Literal["CLOSE", "REOPEN", "WAIVE"]

DisputeBasis = Literal["SCOPE_REASONABLENESS", "COST_ESTIMATE", "STANDARDS_APPLICABILITY"]

DisputeStatus = Literal[
    "FILED",
    "RESOLVED_UPHELD",
    "RESOLVED_REVISED",
    "RESOLVED_REMOVED",
]

DisputeResolution = Literal["UPHOLD", "REVISE", "REMOVE"]

NoticeStatus = Literal["ISSUED", "CURED", "ESCALATED_TO_TERMINATION"]

LedgerEntryType = Literal[
    "SCOPE_ISSUED",
    "COST_REVISED",
    "ITEM_REMOVED",
    "EXTENSION_GRANTED",
    "DRAW_DISBURSED",
    "DRAW_REVERSED",
    "PUNCH_WAIVED",
    "DEFAULT_ISSUED",
    "DEFAULT_CURED",
    "PLAN_COMPLETED",
    "PLAN_TERMINATED",
]


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------


class FranchiseeAccount(TypedDict):
    id: str
    legal_name: str
    contact_email: str
    portfolio_property_count: int
    standing: FranchiseeStanding
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict):
    id: str
    franchisee_id: str
    brand_code: str
    name: str
    room_count: int
    adr_baseline_cents: int
    occupancy_baseline_pct: float
    reserve_balance_cents: int
    minimum_retention_cents: int
    initial_reserve_balance_cents: int
    reserve_contributed_total_cents: int
    rooms_out_of_service_current: int
    franchise_agreement_status: FranchiseAgreementStatus
    compliance_risk_score: int
    compliance_posture: CompliancePosture
    open_plan_count: int
    created_at: str
    updated_at: str
    version: int


class PipPlan(TypedDict):
    id: str
    property_id: str
    trigger_type: TriggerType
    standards_edition: str
    status: PlanStatus
    dispute_state: PlanDisputeState
    issued_by_user_id: Optional[str]
    issued_at: Optional[str]
    life_safety_deadline_date: Optional[str]
    guest_facing_deadline_date: Optional[str]
    back_of_house_deadline_date: Optional[str]
    scope_item_count: int
    brand_scoped_total_cents: int
    owner_claimed_total_cents: int
    funding_requirement_cents: int
    funding_gap_cents: int
    overdue_item_count: int
    created_at: str
    updated_at: str
    version: int


class PipItem(TypedDict):
    id: str
    plan_id: str
    category: ItemCategory
    standards_reference: str
    brand_estimated_cost_cents: int
    approved_cost_cents: int
    owner_claimed_cost_cents: Optional[int]
    room_impacting: bool
    rooms_affected_count: int
    predecessor_item_id: Optional[str]
    status: ItemStatus
    deadline_date: Optional[str]
    extension_days_granted: int
    item_funding_cents: int
    priority_rank: Optional[int]
    is_overdue: bool
    created_at: str
    updated_at: str
    version: int


class ExtensionRequest(TypedDict):
    id: str
    item_id: str
    requested_days: int
    business_justification: str
    status: ExtensionStatus
    round_number: int
    granted_days: int
    pressure_ratio_at_decision: Optional[float]
    decided_by_user_id: Optional[str]
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CapitalBudget(TypedDict):
    id: str
    plan_id: str
    total_authorized_cents: int
    contingency_pct: float
    financing_source: FinancingSource
    status: BudgetStatus
    committed_cents: int
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReserveDraw(TypedDict):
    id: str
    property_id: str
    capital_budget_id: str
    purpose_item_id: str
    amount_cents: int
    status: DrawStatus
    consented_by_user_id: Optional[str]
    disbursed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RenovationPhase(TypedDict):
    id: str
    plan_id: str
    phase_number: int
    start_date: str
    end_date: str
    rooms_out_of_service: int
    status: PhaseStatus
    ooo_pct_at_activation: Optional[float]
    displacement_revenue_impact_cents: int
    created_at: str
    updated_at: str
    version: int


class Contractor(TypedDict):
    id: str
    name: str
    trade: ContractorTrade
    brand_approved: bool
    max_concurrent_bookings: int
    created_at: str
    updated_at: str
    version: int


class ContractorBooking(TypedDict):
    id: str
    contractor_id: str
    phase_id: str
    start_datetime: str
    end_datetime: str
    crew_size: int
    status: BookingStatus
    created_at: str
    updated_at: str
    version: int


class BrandInspection(TypedDict):
    id: str
    plan_id: str
    inspection_type: InspectionType
    inspector_user_id: str
    scheduled_date: str
    status: InspectionStatus
    punch_open_count: int
    performed_at: Optional[str]
    signed_off_at: Optional[str]
    signed_off_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PunchListItem(TypedDict):
    id: str
    inspection_id: str
    pip_item_id: str
    defect_note: str
    severity: DefectSeverity
    status: PunchStatus
    cure_deadline_date: str
    verification_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScopeDispute(TypedDict):
    id: str
    plan_id: str
    item_id: str
    dispute_basis: DisputeBasis
    claimed_cost_cents: int
    status: DisputeStatus
    filed_by_user_id: str
    revised_cost_cents: Optional[int]
    panel_decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DefaultNotice(TypedDict):
    id: str
    plan_id: str
    cure_period_days: int
    cure_deadline_date: str
    status: NoticeStatus
    issued_by_user_id: str
    breached_item_ids: List[str]
    liquidated_damages_cents: int
    created_at: str
    updated_at: str
    version: int


class ComplianceLedgerEntry(TypedDict):
    """Append-only: no ``updated_at`` and no ``version`` exist on this resource."""

    id: str
    plan_id: str
    item_id: Optional[str]
    entry_type: LedgerEntryType
    delta_cents: int
    memo: str
    recorded_at_clock: str
    created_at: str


# ---------------------------------------------------------------------------
# Computed reads
# ---------------------------------------------------------------------------


class RiskSummary(TypedDict):
    property_id: str
    snapshot_score: int
    snapshot_posture: CompliancePosture
    projected_score: int
    projected_posture: CompliancePosture
    projection_horizon_days: int
    overdue_life_safety_count: int
    overdue_guest_facing_count: int
    overdue_back_of_house_count: int
    projected_life_safety_count: int
    projected_guest_facing_count: int
    projected_back_of_house_count: int
    funding_gap_cents: int
    funding_gap_penalty: int
    open_major_defect_count: int
    open_critical_defect_count: int
    open_plan_count: int


class CostSummary(TypedDict):
    plan_id: str
    included_item_count: int
    brand_scoped_total_cents: int
    owner_claimed_total_cents: int
    variance_cents: int
    variance_pct: float
    contingency_pct_applied: float
    funding_requirement_cents: int
    authorized_cents: int
    funding_gap_cents: int
    funding_gap_pct: float


class ClockState(TypedDict):
    current_utc: str


JsonDict = Dict[str, Any]

__all__ = [
    "UserRole",
    "FranchiseeStanding",
    "FranchiseAgreementStatus",
    "CompliancePosture",
    "TriggerType",
    "PlanStatus",
    "PlanDisputeState",
    "ItemCategory",
    "ItemStatus",
    "ExtensionStatus",
    "ExtensionDecision",
    "FinancingSource",
    "BudgetStatus",
    "DrawStatus",
    "DrawDecision",
    "PhaseStatus",
    "ContractorTrade",
    "BookingStatus",
    "InspectionType",
    "InspectionStatus",
    "DefectSeverity",
    "PunchStatus",
    "PunchOutcome",
    "DisputeBasis",
    "DisputeStatus",
    "DisputeResolution",
    "NoticeStatus",
    "LedgerEntryType",
    "FranchiseeAccount",
    "Property",
    "PipPlan",
    "PipItem",
    "ExtensionRequest",
    "CapitalBudget",
    "ReserveDraw",
    "RenovationPhase",
    "Contractor",
    "ContractorBooking",
    "BrandInspection",
    "PunchListItem",
    "ScopeDispute",
    "DefaultNotice",
    "ComplianceLedgerEntry",
    "RiskSummary",
    "CostSummary",
    "ClockState",
    "JsonDict",
]
