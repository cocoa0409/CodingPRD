"""Domain types: entity TypedDicts, status enums, role enum (PRD 2.4, 3.x)."""
from enum import Enum
from typing import TypedDict, List, Optional


class UserRole(str, Enum):
    ACCOUNT_MANAGER = "AccountManager"
    DELIVERY_LEAD = "DeliveryLead"
    ENGINEER = "Engineer"
    CLIENT_CONTACT = "ClientContact"
    FINANCE_OFFICER = "FinanceOfficer"
    PLATFORM_ADMIN = "PlatformAdmin"


class SourceChannel(str, Enum):
    REFERRAL = "REFERRAL"
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"
    PARTNER = "PARTNER"


class BillingModel(str, Enum):
    FIXED = "FIXED"
    TIME_AND_MATERIALS = "TIME_AND_MATERIALS"


class EngagementStatus(str, Enum):
    LEAD = "LEAD"
    QUALIFIED = "QUALIFIED"
    DISQUALIFIED = "DISQUALIFIED"
    SOW_ISSUED = "SOW_ISSUED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    PARTIALLY_BILLED = "PARTIALLY_BILLED"
    FULLY_BILLED = "FULLY_BILLED"


class BudgetPosture(str, Enum):
    HEALTHY = "HEALTHY"
    AT_RISK = "AT_RISK"
    OVERBURNED = "OVERBURNED"


class MilestoneStatus(str, Enum):
    PLANNED = "PLANNED"
    COMPLETED = "COMPLETED"
    BILLED = "BILLED"


class SprintStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class TicketStatus(str, Enum):
    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    IN_QA = "IN_QA"
    REWORK = "REWORK"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class TimeEntryStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVERSED = "REVERSED"


class ChangeRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ReleaseStatus(str, Enum):
    BUILDING = "BUILDING"
    QA_PASSED = "QA_PASSED"
    REWORK = "REWORK"
    ACCEPTED = "ACCEPTED"
    DEPLOYED = "DEPLOYED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


class InvoiceKind(str, Enum):
    MILESTONE = "MILESTONE"
    TIME_AND_MATERIALS = "TIME_AND_MATERIALS"
    RETAINER = "RETAINER"


class SlaTier(str, Enum):
    GOLD = "GOLD"
    SILVER = "SILVER"
    BRONZE = "BRONZE"


class Severity(str, Enum):
    SEV1 = "SEV1"
    SEV2 = "SEV2"
    SEV3 = "SEV3"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    RESPONDED = "RESPONDED"
    RESOLVED = "RESOLVED"


# --- Entity shapes ---------------------------------------------------------
# Every entity in this system carries id / created_at / updated_at / version
# (PRD 2.4).


class Client(TypedDict):
    id: str
    name: str
    billing_email: str
    country_code: str
    created_at: str
    updated_at: str
    version: int


class Engagement(TypedDict):
    id: str
    client_id: str
    title: str
    source_channel: str
    status: str
    billing_status: str
    billing_model: Optional[str]
    contract_value: Optional[float]
    budget_hours_cap: Optional[float]
    standard_hourly_rate: Optional[float]
    start_date: Optional[str]
    end_date: Optional[str]
    signed_at: Optional[str]
    approved_hours: float
    burned_cost: float
    burn_ratio: float
    budget_posture: str
    invoiced_amount: float
    scope_hours_added: float
    created_at: str
    updated_at: str
    version: int


class Milestone(TypedDict):
    id: str
    engagement_id: str
    sequence: int
    title: str
    amount: float
    due_date: str
    status: str
    accepted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Sprint(TypedDict):
    id: str
    engagement_id: str
    milestone_id: Optional[str]
    name: str
    start_date: str
    end_date: str
    status: str
    spend_frozen: bool
    committed_hours: float
    created_at: str
    updated_at: str
    version: int


class Ticket(TypedDict):
    id: str
    sprint_id: str
    blocking_ticket_id: Optional[str]
    title: str
    estimated_hours: float
    assignee_user_id: str
    status: str
    actual_hours: float
    variance_ratio: float
    rework_rounds: int
    created_at: str
    updated_at: str
    version: int


class TimeEntry(TypedDict):
    id: str
    ticket_id: str
    employee_user_id: str
    work_date: str
    hours: float
    billable: bool
    note: Optional[str]
    status: str
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChangeRequest(TypedDict):
    id: str
    engagement_id: str
    title: str
    delta_hours: float
    rush: bool
    quoted_amount: float
    status: str
    revision_rounds: int
    created_at: str
    updated_at: str
    version: int


class Release(TypedDict):
    id: str
    engagement_id: str
    milestone_id: str
    version_label: str
    status: str
    defect_count: int
    qa_rounds: int
    accepted_at: Optional[str]
    environment: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InvoiceLine(TypedDict):
    label: str
    amount: float


class Invoice(TypedDict):
    id: str
    engagement_id: str
    milestone_id: Optional[str]
    retainer_id: Optional[str]
    kind: str
    period_start: Optional[str]
    period_end: Optional[str]
    lines: List[InvoiceLine]
    subtotal: float
    tax: float
    total: float
    status: str
    issued_at: Optional[str]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RetainerContract(TypedDict):
    id: str
    client_id: str
    engagement_id: str
    start_date: str
    end_date: str
    monthly_fee: float
    included_hours: float
    sla_tier: str
    created_at: str
    updated_at: str
    version: int


class SupportIncident(TypedDict):
    id: str
    retainer_id: str
    severity: str
    summary: str
    status: str
    opened_at: str
    responded_at: Optional[str]
    resolved_at: Optional[str]
    response_minutes: Optional[int]
    resolution_minutes: Optional[int]
    sla_response_breached: bool
    sla_resolution_breached: bool
    sla_credit_amount: float
    created_at: str
    updated_at: str
    version: int
