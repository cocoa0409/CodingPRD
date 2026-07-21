"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, List, Optional


class UserRole(str, Enum):
    DESK_EXAMINER = "DeskExaminer"
    FIELD_ADJUSTER = "FieldAdjuster"
    QA_REVIEWER = "QAReviewer"
    LICENSING_ADMIN = "LicensingAdmin"
    BILLING_MANAGER = "BillingManager"


class AdjusterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class LicenseStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class CatEventStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class DeploymentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"


class ClaimStatus(str, Enum):
    INTAKE = "INTAKE"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    UNDER_REVIEW = "UNDER_REVIEW"
    SETTLED = "SETTLED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


class WorkStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    FIELDWORK = "FIELDWORK"
    WORK_COMPLETE = "WORK_COMPLETE"
    DECLINED = "DECLINED"


class BillingStatus(str, Enum):
    NOT_BILLED = "NOT_BILLED"
    BILLED = "BILLED"
    PAID = "PAID"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    REOPENED = "REOPENED"


class EstimateStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REVISION_REQUESTED = "REVISION_REQUESTED"


class FeeBillStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    REJECTED = "REJECTED"
    VOID = "VOID"


# ---- Entities with common_fields: true (id + created_at + updated_at + version) ----

class Adjuster(TypedDict):
    id: str
    full_name: str
    email: str
    adjuster_type: str
    home_state: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AdjusterLicense(TypedDict):
    id: str
    adjuster_id: str
    state_code: str
    license_number: str
    license_type: str
    issued_at: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CatEvent(TypedDict):
    id: str
    name: str
    peril_type: str
    affected_states: List[str]
    roster_capacity: int
    roster_filled_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Deployment(TypedDict):
    id: str
    adjuster_id: str
    cat_event_id: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    claim_number: str
    policyholder_name: str
    loss_state: str
    peril_type: str
    policy_type: str
    cat_event_id: Optional[str]
    rcv_cents: int
    reserve_consumed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict):
    id: str
    claim_id: str
    adjuster_id: str
    offered_at: str
    work_status: str
    billing_status: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    assignment_id: str
    claim_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Estimate(TypedDict):
    id: str
    inspection_id: str
    claim_id: str
    line_items: list
    rcv_total_cents: int
    acv_total_cents: int
    recoverable_depreciation_cents: int
    net_payable_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Report(TypedDict):
    id: str
    inspection_id: str
    assignment_id: str
    scope_narrative: str
    photo_count: int
    qa_reviewer_id: Optional[str]
    qa_decision: Optional[str]
    qa_notes: Optional[str]
    revision_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FeeSchedule(TypedDict):
    id: str
    name: str
    tier1_max_rcv_cents: int
    tier2_max_rcv_cents: int
    tier1_flat_fee_cents: int
    tier2_flat_fee_cents: int
    tier3_flat_fee_cents: int
    rcv_pct_bps: int
    pct_cap_cents: int
    hourly_rate_cents: int
    cat_peril_multiplier_bps: int
    created_at: str
    updated_at: str
    version: int


class FeeBill(TypedDict):
    id: str
    assignment_id: str
    claim_id: str
    fee_schedule_id: str
    billing_method: str
    expected_assignment_version: int
    subtotal_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ---- Entities with common_fields: false (id + created_at only) ----

class TimeEntry(TypedDict):
    id: str
    assignment_id: str
    work_date: str
    activity: str
    hours: float
    expense_cents: int
    created_at: str


class Payment(TypedDict):
    id: str
    fee_bill_id: str
    amount_cents: int
    method: str
    paid_at: str
    created_at: str
