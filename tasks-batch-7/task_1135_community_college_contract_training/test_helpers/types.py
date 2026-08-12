"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List, Any


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class EmployerStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ACTIVE = "ACTIVE"
    DORMANT = "DORMANT"


class NeedsAssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REVISION_REQUESTED = "REVISION_REQUESTED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    NEGOTIATING = "NEGOTIATING"
    SIGNED = "SIGNED"
    IN_DELIVERY = "IN_DELIVERY"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AgreementBillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    PARTIALLY_BILLED = "PARTIALLY_BILLED"
    SETTLED = "SETTLED"


class GrantProgramStatus(str, Enum):
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class GrantApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RETURNED = "RETURNED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CLAIMED = "CLAIMED"
    PAID = "PAID"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class InstructorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class VenueKind(str, Enum):
    CAMPUS_LAB = "CAMPUS_LAB"
    EMPLOYER_SITE = "EMPLOYER_SITE"


class DeliveryMode(str, Enum):
    ON_SITE = "ON_SITE"
    ON_CAMPUS = "ON_CAMPUS"


class PricingModel(str, Enum):
    PER_PARTICIPANT = "PER_PARTICIPANT"
    FLAT_COHORT = "FLAT_COHORT"


class CohortDeliveryStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    LAUNCHED = "LAUNCHED"
    IN_PROGRESS = "IN_PROGRESS"
    DELIVERED = "DELIVERED"
    CREDENTIALED = "CREDENTIALED"
    CANCELLED = "CANCELLED"


class CohortBillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    PAID = "PAID"


class SessionStatus(str, Enum):
    PLANNED = "PLANNED"
    HELD = "HELD"
    CANCELLED = "CANCELLED"


class InstructorAssignmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"
    COMPLETED = "COMPLETED"


class CompletionStatus(str, Enum):
    ENROLLED = "ENROLLED"
    COMPLETED = "COMPLETED"
    DROPPED = "DROPPED"
    NO_SHOW = "NO_SHOW"


class InvoiceVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


class OutcomeReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"


class UserRole(str, Enum):
    COLLEGE_ADMIN = "CollegeAdmin"
    WORKFORCE_COORDINATOR = "WorkforceCoordinator"
    CREDENTIAL_OFFICER = "CredentialOfficer"
    GRANT_OFFICER = "GrantOfficer"
    EMPLOYER_CONTACT = "EmployerContact"
    BILLING_CLERK = "BillingClerk"
    INSTRUCTOR = "Instructor"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all entities carry common_fields: id, created_at,
# updated_at, version)
# ---------------------------------------------------------------------------

class Employer(TypedDict, total=False):
    id: str
    legal_name: str
    industry_code: str
    contact_email: str
    status: str
    lifetime_billed_cents: int
    follow_on_pipeline_cents: int
    created_at: str
    updated_at: str
    version: int


class NeedsAssessment(TypedDict, total=False):
    id: str
    employer_id: str
    title: str
    skill_gaps: List[str]
    target_roles: List[str]
    curriculum_modules: List[dict]
    status: str
    revision_round: int
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrainingAgreement(TypedDict, total=False):
    id: str
    employer_id: str
    needs_assessment_id: str
    assessment_version_pinned: int
    pricing_model: str
    delivery_mode: str
    est_participant_count: int
    est_delivery_hours: float
    target_start_date: str
    max_cohorts: int
    campus_venue_id: Optional[str]
    quoted_total_cents: int
    quote_issued_at: Optional[str]
    quote_expires_at: Optional[str]
    negotiation_round: int
    contract_status: str
    billing_status: str
    signed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GrantProgram(TypedDict, total=False):
    id: str
    code: str
    name: str
    appropriation_cents: int
    max_share_pct: float
    cap_per_trainee_cents: int
    application_window_end: str
    claim_deadline_days: int
    available_cents: int
    reserved_cents: int
    committed_cents: int
    reimbursed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GrantApplication(TypedDict, total=False):
    id: str
    cohort_id: str
    program_id: str
    requested_cents: int
    provisional_award_cents: int
    final_award_cents: int
    reserved_cents: int
    committed_cents: int
    reimbursed_cents: int
    status: str
    submitted_at: Optional[str]
    decided_at: Optional[str]
    claim_by: Optional[str]
    claimed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Instructor(TypedDict, total=False):
    id: str
    full_name: str
    credentials: List[dict]
    hourly_rate_cents: int
    committed_hours: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Venue(TypedDict, total=False):
    id: str
    name: str
    kind: str
    capacity: int
    hourly_cost_cents: int
    turnover_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class Cohort(TypedDict, total=False):
    id: str
    agreement_id: str
    venue_id: Optional[str]
    delivery_mode: str
    min_enrollment: int
    start_date: str
    end_date: str
    enrolled_count: int
    completer_count: int
    delivery_status: str
    billing_status: str
    created_at: str
    updated_at: str
    version: int


class Session(TypedDict, total=False):
    id: str
    cohort_id: str
    venue_id: str
    start_at: str
    end_at: str
    hours: float
    status: str
    attendance_closed: bool
    created_at: str
    updated_at: str
    version: int


class InstructorAssignment(TypedDict, total=False):
    id: str
    session_id: str
    instructor_id: str
    proposed_by_user_id: str
    approved_by_user_id: Optional[str]
    match_score: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict, total=False):
    id: str
    cohort_id: str
    external_employee_ref: str
    full_name: str
    attended_hours: float
    attendance_pct: float
    completion_status: str
    credential_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InvoiceLine(TypedDict, total=False):
    session_id: str
    instruction_cents: int
    materials_cents: int
    line_cents: int


class Invoice(TypedDict, total=False):
    id: str
    cohort_id: str
    agreement_id: str
    variant: str
    lines: List[InvoiceLine]
    gross_cents: int
    grant_offset_cents: int
    net_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OutcomeReport(TypedDict, total=False):
    id: str
    agreement_id: str
    completers_employed_90d: int
    satisfaction_avg: float
    follow_on_opportunity_cents: int
    placement_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int
