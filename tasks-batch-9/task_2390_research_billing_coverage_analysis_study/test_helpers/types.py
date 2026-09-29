"""Domain types for the Research Billing Coverage Analysis API.

Status enums, role enum, and entity TypedDicts, all named exactly as the PRD
names them.  Studies, coverage analyses, study calendars, study subjects,
subject visits, charges, sponsor invoices, audit findings, and amendments carry
the full identity set (``id``, ``created_at``, ``updated_at``, ``version``).
Coverage items, calendar visits, and visit charge routes are write-once and
carry only ``id`` and ``created_at`` — no ``updated_at`` and no ``version``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------


class UserRole(str, Enum):
    RESEARCH_BILLING_MANAGER = "ResearchBillingManager"
    COVERAGE_ANALYST = "CoverageAnalyst"
    COMPLIANCE_REVIEWER = "ComplianceReviewer"
    STUDY_COORDINATOR = "StudyCoordinator"
    AUDIT_LIAISON = "AuditLiaison"


# --------------------------------------------------------------------------
# Study enums
# --------------------------------------------------------------------------


class StudyLifecycleStatus(str, Enum):
    DRAFT = "DRAFT"
    COVERAGE_PENDING = "COVERAGE_PENDING"
    COVERAGE_APPROVED = "COVERAGE_APPROVED"
    OPEN_TO_ACCRUAL = "OPEN_TO_ACCRUAL"
    CLOSED_TO_ACCRUAL = "CLOSED_TO_ACCRUAL"


class BudgetStatus(str, Enum):
    NOT_BUILT = "NOT_BUILT"
    BUILT = "BUILT"
    EXECUTED = "EXECUTED"
    SUPERSEDED = "SUPERSEDED"


class FundingSource(str, Enum):
    INDUSTRY_SPONSORED = "INDUSTRY_SPONSORED"
    FEDERALLY_FUNDED = "FEDERALLY_FUNDED"
    INVESTIGATOR_INITIATED = "INVESTIGATOR_INITIATED"


class IndIdeStatus(str, Enum):
    IND_HELD = "IND_HELD"
    IDE_CATEGORY_A = "IDE_CATEGORY_A"
    IDE_CATEGORY_B = "IDE_CATEGORY_B"
    NONE = "NONE"


class QctDetermination(str, Enum):
    UNDETERMINED = "UNDETERMINED"
    DEEMED_QUALIFYING = "DEEMED_QUALIFYING"
    SELF_CERTIFIED_QUALIFYING = "SELF_CERTIFIED_QUALIFYING"
    NON_QUALIFYING = "NON_QUALIFYING"


class QctBasis(str, Enum):
    DEEMED_IND_IDE = "DEEMED_IND_IDE"
    DEEMED_FEDERALLY_FUNDED = "DEEMED_FEDERALLY_FUNDED"
    SELF_CERTIFIED = "SELF_CERTIFIED"
    NOT_QUALIFYING_DECLARED = "NOT_QUALIFYING_DECLARED"


class BillingHoldPosture(str, Enum):
    OPEN = "OPEN"
    PAYER_BLOCKED = "PAYER_BLOCKED"
    ALL_BLOCKED = "ALL_BLOCKED"


class AccrualTargetStatus(str, Enum):
    OPEN_TO_ACCRUAL = "OPEN_TO_ACCRUAL"
    CLOSED_TO_ACCRUAL = "CLOSED_TO_ACCRUAL"


# --------------------------------------------------------------------------
# Coverage analysis / item enums
# --------------------------------------------------------------------------


class AnalysisStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    RETURNED = "RETURNED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class ItemClassification(str, Enum):
    ROUTINE_CARE = "ROUTINE_CARE"
    RESEARCH_PAID = "RESEARCH_PAID"
    PROMOTIONAL = "PROMOTIONAL"


class MedicareCoverageBasis(str, Enum):
    STANDARD_OF_CARE = "STANDARD_OF_CARE"
    QCT_CONDITIONAL = "QCT_CONDITIONAL"
    NOT_COVERED = "NOT_COVERED"


class BudgetCategory(str, Enum):
    PER_PATIENT = "PER_PATIENT"
    INVOICEABLE = "INVOICEABLE"
    NOT_BUDGETED = "NOT_BUDGETED"


class BillableTo(str, Enum):
    PAYER = "PAYER"
    SPONSOR = "SPONSOR"
    NONE = "NONE"


# --------------------------------------------------------------------------
# Calendar enums
# --------------------------------------------------------------------------


class CalendarStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    REBUILD_REQUIRED = "REBUILD_REQUIRED"
    RETIRED = "RETIRED"


class RoutingTarget(str, Enum):
    PAYER = "PAYER"
    SPONSOR = "SPONSOR"
    NONE = "NONE"


class BudgetBasis(str, Enum):
    COVERAGE_DRIVEN = "COVERAGE_DRIVEN"
    CALENDAR_DRIVEN = "CALENDAR_DRIVEN"


# --------------------------------------------------------------------------
# Accrual enums
# --------------------------------------------------------------------------


class SubjectStatus(str, Enum):
    SCREENING = "SCREENING"
    CONSENTED = "CONSENTED"
    OFF_STUDY = "OFF_STUDY"


class SubjectVisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OCCURRED = "OCCURRED"
    MISSED = "MISSED"


# --------------------------------------------------------------------------
# Charge enums
# --------------------------------------------------------------------------


class ChargeSource(str, Enum):
    VISIT_CASCADE = "VISIT_CASCADE"
    INTERFACE_POSTED = "INTERFACE_POSTED"
    REFUND_REPLACEMENT = "REFUND_REPLACEMENT"


class RoutingState(str, Enum):
    UNROUTED = "UNROUTED"
    ROUTED_PAYER = "ROUTED_PAYER"
    ROUTED_SPONSOR = "ROUTED_SPONSOR"
    ROUTED_NONE = "ROUTED_NONE"


class BillingState(str, Enum):
    UNBILLED = "UNBILLED"
    BILLED_PAYER = "BILLED_PAYER"
    INVOICED_SPONSOR = "INVOICED_SPONSOR"
    WRITTEN_OFF = "WRITTEN_OFF"
    REFUNDED = "REFUNDED"


class ExpectedRoutingTarget(str, Enum):
    PAYER = "PAYER"
    SPONSOR = "SPONSOR"
    NONE = "NONE"
    UNDETERMINED = "UNDETERMINED"


class HoldReason(str, Enum):
    NONE = "NONE"
    CALENDAR_REBUILD = "CALENDAR_REBUILD"
    AUDIT_OPEN = "AUDIT_OPEN"


class AgingBucket(str, Enum):
    CURRENT = "CURRENT"
    AGING_31_60 = "AGING_31_60"
    AGING_61_90 = "AGING_61_90"
    DELINQUENT_90_PLUS = "DELINQUENT_90_PLUS"


class ChargeReviewDecision(str, Enum):
    CLEAR_TO_PAYER = "CLEAR_TO_PAYER"
    HOLD_FOR_SPONSOR = "HOLD_FOR_SPONSOR"
    NO_CHARGE_PROMOTIONAL = "NO_CHARGE_PROMOTIONAL"


# --------------------------------------------------------------------------
# Invoice enums
# --------------------------------------------------------------------------


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"


class RemittanceOutcome(str, Enum):
    PAID_IN_FULL = "PAID_IN_FULL"
    SHORT_PAID = "SHORT_PAID"
    DISPUTED = "DISPUTED"


# --------------------------------------------------------------------------
# Audit / amendment enums
# --------------------------------------------------------------------------


class FindingType(str, Enum):
    IMPROPER_PAYER_BILL = "IMPROPER_PAYER_BILL"
    MISSING_REGISTRY_NUMBER = "MISSING_REGISTRY_NUMBER"
    UNSUPPORTED_ROUTINE_CLASSIFICATION = "UNSUPPORTED_ROUTINE_CLASSIFICATION"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    RESPONDED = "RESPONDED"
    CLOSED_NO_ACTION = "CLOSED_NO_ACTION"
    CLOSED_REFUNDED = "CLOSED_REFUNDED"


class FindingDisposition(str, Enum):
    NO_ACTION = "NO_ACTION"
    REFUND_AND_REROUTE = "REFUND_AND_REROUTE"


class AmendmentScope(str, Enum):
    ADMINISTRATIVE = "ADMINISTRATIVE"
    ITEM_CHANGE = "ITEM_CHANGE"
    VISIT_SCHEDULE_CHANGE = "VISIT_SCHEDULE_CHANGE"
    ITEM_AND_SCHEDULE_CHANGE = "ITEM_AND_SCHEDULE_CHANGE"


class AmendmentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    IMPLEMENTED = "IMPLEMENTED"


# --------------------------------------------------------------------------
# Entity TypedDicts — full identity set
# --------------------------------------------------------------------------


class Study(TypedDict, total=False):
    id: str
    protocol_number: str
    title: str
    sponsor_name: str
    funding_source: str
    ind_ide_status: str
    therapeutic_intent: bool
    registry_number: Optional[str]
    lifecycle_status: str
    budget_status: str
    qct_determination: str
    qct_basis: Optional[str]
    qct_determined_by_user_id: Optional[str]
    qct_determined_at: Optional[str]
    budget_source_analysis_id: Optional[str]
    budget_basis: Optional[str]
    indirect_rate_pct: Optional[float]
    effective_indirect_rate_pct: Optional[float]
    per_patient_subtotal_cents: int
    per_patient_budget_cents: int
    invoiceable_subtotal_cents: int
    invoiceable_budget_cents: int
    budget_built_by_user_id: Optional[str]
    budget_executed_by_user_id: Optional[str]
    billing_hold_posture: str
    payer_billed_cents: int
    payer_refunded_cents: int
    sponsor_unbilled_cents: int
    sponsor_receivable_cents: int
    sponsor_collected_cents: int
    sponsor_written_off_cents: int
    improper_payer_exposure_cents: int
    delinquent_sponsor_cents: int
    open_finding_count: int
    rebuild_required_calendar_count: int
    created_at: str
    updated_at: str
    version: int


class CoverageAnalysis(TypedDict, total=False):
    id: str
    study_id: str
    revision_number: int
    supersedes_analysis_id: Optional[str]
    status: str
    prepared_by_user_id: str
    returned_by_user_id: Optional[str]
    return_reason: Optional[str]
    return_count: int
    approved_by_user_id: Optional[str]
    approved_at: Optional[str]
    item_count: int
    routine_care_item_count: int
    research_paid_item_count: int
    promotional_item_count: int
    qct_conditional_item_count: int
    created_at: str
    updated_at: str
    version: int


class StudyCalendar(TypedDict, total=False):
    id: str
    study_id: str
    source_analysis_id: str
    build_generation: int
    status: str
    visit_count: int
    routed_item_count: int
    unrouted_per_patient_item_count: int
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StudySubject(TypedDict, total=False):
    id: str
    study_id: str
    subject_number: str
    status: str
    consented_calendar_id: Optional[str]
    consented_calendar_generation: Optional[int]
    consent_date: Optional[str]
    charge_count: int
    created_at: str
    updated_at: str
    version: int


class SubjectVisit(TypedDict, total=False):
    id: str
    study_subject_id: str
    calendar_visit_id: str
    actual_service_date: str
    day_offset_actual: int
    calendar_generation_at_schedule: int
    status: str
    generated_charge_count: int
    created_at: str
    updated_at: str
    version: int


class Charge(TypedDict, total=False):
    id: str
    study_id: str
    subject_visit_id: Optional[str]
    coverage_item_id: Optional[str]
    charge_code: str
    service_date: str
    amount_cents: int
    source: str
    posted_by_user_id: Optional[str]
    routing_state: str
    billing_state: str
    suggested_routing_target: Optional[str]
    expected_routing_target: str
    improper_flag: bool
    reviewed_by_user_id: Optional[str]
    reviewed_at: Optional[str]
    override_justification: Optional[str]
    hold_reason: str
    hold_applied_at: Optional[str]
    unbilled_since: Optional[str]
    aging_days: int
    aging_bucket: str
    sponsor_invoice_id: Optional[str]
    refunded_amount_cents: int
    replaces_charge_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SponsorInvoice(TypedDict, total=False):
    id: str
    study_id: str
    sequence_number: int
    invoice_number: str
    period_end_date: str
    status: str
    line_count: int
    subtotal_cents: int
    indirect_cents: int
    gross_total_cents: int
    volume_credit_cents: int
    net_total_cents: int
    amount_paid_cents: int
    short_paid: bool
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuditFinding(TypedDict, total=False):
    id: str
    study_id: str
    charge_id: Optional[str]
    finding_type: str
    claimed_amount_cents: int
    status: str
    opened_by_user_id: str
    responded_by_user_id: Optional[str]
    response_narrative: Optional[str]
    refund_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class Amendment(TypedDict, total=False):
    id: str
    study_id: str
    amendment_number: int
    scope: str
    effective_date: str
    status: str
    reanalysis_required: bool
    calendar_rebuild_required: bool
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Write-once entity TypedDicts — only id + created_at
# --------------------------------------------------------------------------


class CoverageItem(TypedDict, total=False):
    """Write-once: no ``updated_at``, no ``version``."""

    id: str
    coverage_analysis_id: str
    item_code: str
    description: str
    classification: str
    medicare_coverage_basis: str
    budget_category: str
    billable_to: str
    charge_master_unit_cents: int
    negotiated_unit_cents: int
    units_per_occurrence: int
    expected_occurrences: int
    created_at: str


class CalendarVisit(TypedDict, total=False):
    """Write-once: no ``updated_at``, no ``version``."""

    id: str
    study_calendar_id: str
    visit_name: str
    sequence_index: int
    target_day_offset: int
    window_before_days: int
    window_after_days: int
    window_start_day: int
    window_end_day: int
    expected_charge_total_cents: int
    created_at: str


class VisitChargeRoute(TypedDict, total=False):
    """Write-once: no ``updated_at``, no ``version``."""

    id: str
    calendar_visit_id: str
    coverage_item_id: str
    occurrences: int
    routing_target: str
    expected_amount_cents: int
    created_at: str


# --------------------------------------------------------------------------
# Computed reads
# --------------------------------------------------------------------------


class ChargeReviewSummary(TypedDict, total=False):
    study_id: str
    billing_hold_posture: str
    unrouted_charge_count: int
    sponsor_unbilled_cents: int
    sponsor_receivable_cents: int
    payer_billed_cents: int
    payer_refunded_cents: int
    improper_payer_exposure_cents: int
    delinquent_sponsor_cents: int
    open_finding_count: int


class AgingRunResult(TypedDict, total=False):
    study_id: str
    run_date: str
    charges_aged_count: int
    visits_missed_count: int
    delinquent_charge_count: int
    delinquent_sponsor_cents: int


WRITE_ONCE_ENTITY_NAMES: List[str] = [
    "CoverageItem",
    "CalendarVisit",
    "VisitChargeRoute",
]
