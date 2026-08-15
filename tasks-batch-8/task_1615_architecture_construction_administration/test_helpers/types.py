"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class CaProjectStatus(str, Enum):
    SETUP = "SETUP"
    ACTIVE = "ACTIVE"
    SUBSTANTIAL_COMPLETION_ACHIEVED = "SUBSTANTIAL_COMPLETION_ACHIEVED"
    FINAL_COMPLETION_ACHIEVED = "FINAL_COMPLETION_ACHIEVED"
    CLOSED = "CLOSED"


class CaPosture(str, Enum):
    NORMAL = "NORMAL"
    EXTENDED_DURATION = "EXTENDED_DURATION"


class BillingMethod(str, Enum):
    PER_DIEM_PRORATED = "PER_DIEM_PRORATED"
    WHOLE_MONTH = "WHOLE_MONTH"


class RetainageMode(str, Enum):
    TIERED_MARGINAL = "TIERED_MARGINAL"
    REDUCTION_AT_HALFWAY = "REDUCTION_AT_HALFWAY"


class SubmittalStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    APPROVED_AS_NOTED = "APPROVED_AS_NOTED"
    REVISE_AND_RESUBMIT = "REVISE_AND_RESUBMIT"
    REJECTED = "REJECTED"


class SubmittalReviewOutcome(str, Enum):
    APPROVED = "APPROVED"
    APPROVED_AS_NOTED = "APPROVED_AS_NOTED"
    REVISE_AND_RESUBMIT = "REVISE_AND_RESUBMIT"
    REJECTED = "REJECTED"


class SiteVisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PERFORMED = "PERFORMED"
    REPORT_ISSUED = "REPORT_ISSUED"
    CANCELLED = "CANCELLED"


class SiteVisitPurpose(str, Enum):
    PROGRESS_OBSERVATION = "PROGRESS_OBSERVATION"
    PAYMENT_VERIFICATION = "PAYMENT_VERIFICATION"
    PUNCH_INSPECTION = "PUNCH_INSPECTION"
    FINAL_INSPECTION = "FINAL_INSPECTION"


class ConformanceSummary(str, Enum):
    CONFORMING = "CONFORMING"
    MINOR_DEVIATIONS = "MINOR_DEVIATIONS"
    NONCONFORMING = "NONCONFORMING"


class NonconformanceStatus(str, Enum):
    NONE = "NONE"
    OPEN = "OPEN"
    CLEARED = "CLEARED"


class RfiStatus(str, Enum):
    OPEN = "OPEN"
    CLARIFICATION_PENDING = "CLARIFICATION_PENDING"
    ANSWERED = "ANSWERED"
    CLOSED = "CLOSED"
    WITHDRAWN = "WITHDRAWN"


class ClarificationDrawingStatus(str, Enum):
    ISSUED = "ISSUED"
    SUPERSEDED = "SUPERSEDED"


class PaymentApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CERTIFIED = "CERTIFIED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class ChangeOrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    RECOMMEND_ACCEPTANCE = "RECOMMEND_ACCEPTANCE"
    RECOMMEND_REJECTION = "RECOMMEND_REJECTION"
    OWNER_ACCEPTED = "OWNER_ACCEPTED"
    OWNER_REJECTED = "OWNER_REJECTED"
    INCORPORATED = "INCORPORATED"


class ChangeOrderRecommendation(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class OwnerDecision(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class InvoiceOwnerDecision(str, Enum):
    APPROVE = "APPROVE"
    DISPUTE = "DISPUTE"


class PunchListItemStatus(str, Enum):
    OPEN = "OPEN"
    CLAIMED_COMPLETE = "CLAIMED_COMPLETE"
    VERIFIED = "VERIFIED"
    REOPENED = "REOPENED"


class RecordDocumentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    RETURNED_FOR_CORRECTION = "RETURNED_FOR_CORRECTION"


class RecordDocumentType(str, Enum):
    AS_BUILT = "AS_BUILT"
    OM_MANUAL = "OM_MANUAL"
    WARRANTY = "WARRANTY"
    TEST_REPORT = "TEST_REPORT"


class RecordDocumentReviewOutcome(str, Enum):
    ACCEPT = "ACCEPT"
    RETURN_FOR_CORRECTION = "RETURN_FOR_CORRECTION"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    OWNER_APPROVED = "OWNER_APPROVED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    FIRM_ADMIN = "FirmAdmin"
    ARCHITECT_CA = "ArchitectCA"
    CONTRACTOR = "Contractor"
    OWNER = "Owner"


class SovLine(TypedDict):
    line_code: str
    description: str
    scheduled_value_cents: int


class PaymentApplicationLine(TypedDict):
    sov_line_code: str
    work_completed_this_period_cents: int
    stored_materials_cents: int


# All entities carry common fields: id, created_at, updated_at, version.

class CaProject(TypedDict):
    id: str
    name: str
    owner_user_id: str
    contractor_user_id: str
    original_contract_sum_cents: int
    sov_lines: List[SovLine]
    base_substantial_completion_date: str
    adjusted_substantial_completion_date: str
    adjusted_contract_sum_cents: int
    daily_extension_rate_cents: int
    monthly_extension_rate_cents: int
    billing_method: str
    retainage_mode: str
    grace_days: int
    review_window_days_submittal: int
    review_window_days_rfi: int
    field_report_window_days: int
    excusable_delay_days: int
    certified_to_date_cents: int
    retainage_held_cents: int
    substantial_completion_actual_date: Optional[str]
    ca_posture: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Submittal(TypedDict):
    id: str
    project_id: str
    spec_section: str
    required_on_site_date: str
    revision_number: int
    received_at: str
    due_at: str
    reviewed_at: Optional[str]
    credited_delay_days: int
    review_notes: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SiteVisit(TypedDict):
    id: str
    project_id: str
    visit_date: str
    purpose: str
    performed_by_user_id: str
    performed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FieldReport(TypedDict):
    id: str
    site_visit_id: str
    issued_by_user_id: str
    issued_at: str
    conformance_summary: str
    nonconforming_work_flag: bool
    nonconformance_status: str
    clearing_visit_id: Optional[str]
    notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Rfi(TypedDict):
    id: str
    project_id: str
    question: str
    cost_impact_flag: bool
    received_at: str
    due_at: str
    answered_at: Optional[str]
    answer_text: Optional[str]
    credited_delay_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ClarificationDrawing(TypedDict):
    id: str
    rfi_id: str
    drawing_ref: str
    revision_number: int
    issued_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PaymentApplication(TypedDict):
    id: str
    project_id: str
    period_ending_date: str
    verification_visit_id: str
    previous_application_id: Optional[str]
    revision_number: int
    lines: List[PaymentApplicationLine]
    gross_work_completed_cents: int
    earned_work_this_period_cents: int
    retainage_work_cents: int
    retainage_stored_cents: int
    provisional_current_due_cents: int
    certified_current_due_cents: Optional[int]
    rejection_reason: Optional[str]
    certified_at: Optional[str]
    certified_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ChangeOrder(TypedDict):
    id: str
    project_id: str
    rfi_id: Optional[str]
    title: str
    net_cost_change_cents: int
    time_extension_days: int
    markup_cents: int
    total_amount_cents: int
    recommendation: Optional[str]
    recommended_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PunchListItem(TypedDict):
    id: str
    project_id: str
    raised_visit_id: str
    description: str
    location: str
    reopen_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RecordDocument(TypedDict):
    id: str
    project_id: str
    doc_type: str
    revision_number: int
    review_notes: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AdditionalServiceInvoice(TypedDict):
    id: str
    project_id: str
    period_start: str
    period_end: str
    horizon_start_date: str
    horizon_end_date: str
    billable_days: int
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
