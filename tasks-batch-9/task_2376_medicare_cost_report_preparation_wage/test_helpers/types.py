"""Domain types for the Medicare Cost Report Wage Index API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.  Every persisted resource in this system carries `id`,
`created_at`, `updated_at` and `version` (PRD 2.4), so every TypedDict below
lists all four.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    REIMBURSEMENT_ANALYST = "ReimbursementAnalyst"
    REIMBURSEMENT_MANAGER = "ReimbursementManager"
    MAC_AUDITOR = "MacAuditor"
    REVIEW_BOARD_CLERK = "ReviewBoardClerk"


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class TeachingStatus(str, Enum):
    TEACHING = "TEACHING"
    NON_TEACHING = "NON_TEACHING"


class CostReportStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    TENTATIVE_SETTLED = "TENTATIVE_SETTLED"
    FINAL_SETTLED = "FINAL_SETTLED"
    REOPENED = "REOPENED"
    AMENDED_FILED = "AMENDED_FILED"
    CLOSED = "CLOSED"


class WageDataStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    COLLECTED = "COLLECTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    VERIFIED = "VERIFIED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    REJECTED = "REJECTED"


class AllocationStatus(str, Enum):
    NOT_RUN = "NOT_RUN"
    CURRENT = "CURRENT"
    STALE = "STALE"


class ApportionmentMethod(str, Enum):
    SINGLE_APPORTIONMENT = "SINGLE_APPORTIONMENT"
    DOUBLE_APPORTIONMENT = "DOUBLE_APPORTIONMENT"


class CenterType(str, Enum):
    GENERAL_SERVICE = "GENERAL_SERVICE"
    ANCILLARY = "ANCILLARY"
    ROUTINE = "ROUTINE"
    NONREIMBURSABLE = "NONREIMBURSABLE"


class AllocationBasis(str, Enum):
    SQUARE_FEET = "SQUARE_FEET"
    MEALS_SERVED = "MEALS_SERVED"
    POUNDS_LAUNDRY = "POUNDS_LAUNDRY"
    NURSING_HOURS = "NURSING_HOURS"
    NONE = "NONE"


class TrialBalanceLineStatus(str, Enum):
    UNMAPPED = "UNMAPPED"
    MAPPED = "MAPPED"


class WorkpaperEntryType(str, Enum):
    RECLASSIFICATION = "RECLASSIFICATION"
    ADJUSTMENT = "ADJUSTMENT"


class WorkpaperEntrySource(str, Enum):
    MANUAL = "MANUAL"
    AUDIT = "AUDIT"


class WorkpaperEntryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVERSED = "REVERSED"


class StepdownRunStatus(str, Enum):
    QUEUED = "QUEUED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    STALE = "STALE"


class StaleReason(str, Enum):
    SUPERSEDED_BY_NEWER_RUN = "SUPERSEDED_BY_NEWER_RUN"
    COST_CENTER_INPUT_CHANGED = "COST_CENTER_INPUT_CHANGED"
    WORKPAPER_ENTRY_CHANGED = "WORKPAPER_ENTRY_CHANGED"


class WageIndexSubmissionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CHANGE_REQUESTED = "CHANGE_REQUESTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ReviewDecision(str, Enum):
    ACCEPT = "ACCEPT"
    REQUEST_CHANGE = "REQUEST_CHANGE"
    REJECT = "REJECT"


class OccMixCategory(str, Enum):
    RN = "RN"
    LPN = "LPN"
    NURSE_AIDE = "NURSE_AIDE"
    MEDICAL_ASSISTANT = "MEDICAL_ASSISTANT"
    NURSE_PRACTITIONER = "NURSE_PRACTITIONER"


class IrpStatus(str, Enum):
    WITHIN_IRP = "WITHIN_IRP"
    BEYOND_IRP = "BEYOND_IRP"


class RotationAssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOID = "VOID"


class SettlementStage(str, Enum):
    TENTATIVE = "TENTATIVE"
    FINAL = "FINAL"


class SettlementStatus(str, Enum):
    ISSUED = "ISSUED"
    APPEALED = "APPEALED"
    SUPERSEDED = "SUPERSEDED"
    RESETTLED = "RESETTLED"


class AuditAdjustmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED_BY_PROVIDER = "ACCEPTED_BY_PROVIDER"
    PROTESTED = "PROTESTED"
    INCORPORATED = "INCORPORATED"
    WITHDRAWN = "WITHDRAWN"


class AuditResponse(str, Enum):
    ACCEPT = "ACCEPT"
    PROTEST = "PROTEST"


class AuditResolutionOutcome(str, Enum):
    INCORPORATE = "INCORPORATE"
    WITHDRAW = "WITHDRAW"


class AppealKind(str, Enum):
    REOPENING = "REOPENING"
    PRRB_APPEAL = "PRRB_APPEAL"


class AppealCaseStatus(str, Enum):
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    HEARD = "HEARD"
    DECIDED_FOR_PROVIDER = "DECIDED_FOR_PROVIDER"
    DECIDED_FOR_CONTRACTOR = "DECIDED_FOR_CONTRACTOR"


class AppealOutcome(str, Enum):
    GRANT = "GRANT"
    DENY = "DENY"
    HEAR = "HEAR"
    DECIDE_FOR_PROVIDER = "DECIDE_FOR_PROVIDER"
    DECIDE_FOR_CONTRACTOR = "DECIDE_FOR_CONTRACTOR"


class InterimRateRequestStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SUPERSEDED = "SUPERSEDED"


class InterimRateDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------


class Provider(TypedDict):
    id: str
    ccn: str
    name: str
    cbsa_code: str
    teaching_status: str
    fte_cap: float
    current_interim_rate_cents: int
    approved_interim_period_count: int
    created_at: str
    updated_at: str
    version: int


class CostReport(TypedDict):
    id: str
    provider_id: str
    fiscal_year_begin: str
    fiscal_year_end: str
    filing_deadline: str
    status: str
    wage_data_status: str
    allocation_status: str
    apportionment_method: str
    medicare_utilization_ratio: float
    interim_payments_received_cents: int
    total_charges_cents: int
    medicare_discharges: int
    total_direct_cost_cents: int
    unmapped_tb_total_cents: int
    total_allowable_cost_cents: int
    cost_to_charge_ratio: float
    unweighted_fte_days_total: float
    unweighted_fte_total: float
    capped_unweighted_fte: float
    weighted_fte_total: float
    rolling_average_fte: float
    allowable_cost_per_discharge_cents: int
    filed_at: Optional[str]
    amendment_count: int
    created_at: str
    updated_at: str
    version: int


class CostCenter(TypedDict):
    id: str
    cost_report_id: str
    code: str
    name: str
    center_type: str
    allocation_basis: str
    stepdown_order: Optional[int]
    statistics: Dict[str, float]
    direct_cost_cents: int
    reclassified_amount_cents: int
    adjustment_amount_cents: int
    post_reclass_direct_cost_cents: int
    post_adjustment_cost_cents: int
    allocated_in_cents: int
    allocated_out_cents: int
    allocated_total_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class TrialBalanceLine(TypedDict):
    id: str
    cost_report_id: str
    gl_account: str
    description: str
    amount_cents: int
    mapped_cost_center_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkpaperEntryLeg(TypedDict):
    cost_center_id: str
    amount_cents: int


class WorkpaperEntry(TypedDict):
    id: str
    cost_report_id: str
    entry_type: str
    code: str
    description: str
    legs: List[WorkpaperEntryLeg]
    source: str
    is_non_allowable: bool
    status: str
    source_audit_adjustment_id: Optional[str]
    reversed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AllocationLine(TypedDict):
    pass_: int
    from_cost_center_id: str
    to_cost_center_id: str
    amount_cents: int


class StepdownRun(TypedDict):
    id: str
    cost_report_id: str
    method: str
    status: str
    total_allocated_cents: int
    residual_unallocated_cents: int
    allocation_lines: List[Dict[str, Any]]
    failure_reason: Optional[str]
    stale_reason: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WageIndexSubmission(TypedDict):
    id: str
    cost_report_id: str
    status: str
    revision_number: int
    total_salaries_cents: int
    total_paid_hours: float
    wage_related_costs_cents: int
    contract_labor_cents: int
    contract_labor_hours: float
    excluded_area_salaries_cents: int
    excluded_area_hours: float
    allowed_wage_related_costs_cents: int
    unadjusted_ahw_cents: int
    occ_mix_adjusted_ahw_cents: Optional[int]
    occ_mix_category_count: int
    effective_ahw_cents: int
    reported_hours_total: float
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OccMixResponse(TypedDict):
    id: str
    wage_index_submission_id: str
    category: str
    reported_hours: float
    reported_salaries_cents: int
    category_ahw_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Resident(TypedDict):
    id: str
    provider_id: str
    full_name: str
    program: str
    irp_status: str
    assigned_fte_days: float
    created_at: str
    updated_at: str
    version: int


class RotationAssignment(TypedDict):
    id: str
    resident_id: str
    cost_center_id: str
    start_date: str
    end_date: str
    fte_fraction: float
    status: str
    overlap_days: int
    fte_days: float
    created_at: str
    updated_at: str
    version: int


class UccDataSet(TypedDict):
    id: str
    cost_report_id: str
    medicaid_non_medicare_days: int
    total_inpatient_days: int
    ssi_days: int
    medicare_part_a_days: int
    charity_care_charges_cents: int
    non_medicare_bad_debt_cents: int
    medicaid_fraction: float
    ssi_fraction: float
    dsh_patient_percentage: float
    dsh_eligible: bool
    cost_to_charge_ratio: float
    uncompensated_care_cost_cents: int
    ucc_payment_cents: int
    recompute_required: bool
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict):
    id: str
    cost_report_id: str
    stage: str
    status: str
    basis_method: str
    basis_allowable_cost_cents: int
    reimbursable_cost_cents: int
    ucc_payment_cents: int
    prior_tentative_paid_cents: int
    amount_due_provider_cents: int
    recompute_required: bool
    issued_at: str
    created_at: str
    updated_at: str
    version: int


class AuditAdjustment(TypedDict):
    id: str
    settlement_id: str
    target_cost_center_id: str
    code: str
    rationale: str
    proposed_amount_cents: int
    status: str
    proposed_by_user_id: str
    resolved_by_user_id: Optional[str]
    provider_response_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AppealCase(TypedDict):
    id: str
    cost_report_id: str
    settlement_id: str
    kind: str
    issue_description: str
    amount_at_issue_cents: int
    status: str
    decided_at: Optional[str]
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InterimRateRequest(TypedDict):
    id: str
    provider_id: str
    basis_cost_report_id: str
    projected_discharges: int
    trend_factor: float
    effective_from: str
    effective_to: str
    status: str
    projected_cost_per_discharge_cents: int
    variance_ratio: float
    approved_rate_cents: int
    adjustment_amount_cents: int
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GmeSummary(TypedDict):
    cost_report_id: str
    period_days: int
    unweighted_fte_days_total: float
    unweighted_fte_total: float
    capped_unweighted_fte: float
    weighted_fte_total: float
    rolling_average_fte: float
    prior_period_count: int
