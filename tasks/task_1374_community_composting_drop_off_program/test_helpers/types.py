"""Domain types: entity TypedDicts, status enums, role enum.

Per PRD §2.4: most resources carry id + created_at + updated_at + version.
DistributionAllocation and DiversionReport carry only id + created_at.
"""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class SiteStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    OPERATIONAL = "OPERATIONAL"
    DECOMMISSIONED = "DECOMMISSIONED"


class SitePosture(str, Enum):
    OPEN = "OPEN"
    WATCH = "WATCH"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    BREACH_NOTICED = "BREACH_NOTICED"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"


class ContaminationSensitivity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ParticipantStatus(str, Enum):
    PENDING_VERIFY = "PENDING_VERIFY"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEACTIVATED = "DEACTIVATED"


class AccessGrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class CreditState(str, Enum):
    UNCREDITED = "UNCREDITED"
    PROVISIONALLY_CREDITED = "PROVISIONALLY_CREDITED"
    FINALLY_CREDITED = "FINALLY_CREDITED"
    REVOKED = "REVOKED"


class VerificationState(str, Enum):
    PENDING_AUDIT = "PENDING_AUDIT"
    ACCEPTED = "ACCEPTED"
    FLAGGED_CONTAMINATED = "FLAGGED_CONTAMINATED"
    REJECTED = "REJECTED"


class ContaminationSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class ContaminationReportStatus(str, Enum):
    OPEN = "OPEN"
    FEEDBACK_SENT = "FEEDBACK_SENT"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


class RouteStatus(str, Enum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RouteStopStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COLLECTED = "COLLECTED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


class BatchStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED_ACCEPTED = "CLOSED_ACCEPTED"
    CLOSED_REJECTED = "CLOSED_REJECTED"


class DistributionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class AllocationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    DISTRIBUTED = "DISTRIBUTED"
    CANCELLED = "CANCELLED"


class ComplaintKind(str, Enum):
    ODOR = "ODOR"
    VECTOR = "VECTOR"
    OTHER = "OTHER"


class ComplaintStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"
    CLOSED = "CLOSED"


class DiversionMethod(str, Enum):
    PROVISIONAL_NET = "PROVISIONAL_NET"
    FINAL_NET = "FINAL_NET"


class DiversionReportStatus(str, Enum):
    DRAFT = "DRAFT"
    CERTIFIED = "CERTIFIED"
    SUPERSEDED = "SUPERSEDED"


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    PROGRAM_ADMIN = "ProgramAdmin"
    SITE_HOST = "SiteHost"
    PARTICIPANT = "Participant"
    ROUTE_OPERATOR = "RouteOperator"
    PROCESSING_PARTNER = "ProcessingPartner"
    MUNICIPAL_AUDITOR = "MunicipalAuditor"


# ---------------------------------------------------------------------------
# Entity TypedDicts (common_fields entities carry id/created_at/updated_at/version)
# ---------------------------------------------------------------------------

class Program(TypedDict, total=False):
    id: str
    name: str
    fiscal_year: int
    status: str
    posture_contam_threshold: int
    posture_complaint_threshold: int
    diversion_credit_rate: float
    ops_run_index: int
    total_diverted_kg: float
    total_contamination_kg: float
    created_at: str
    updated_at: str
    version: int


class Site(TypedDict, total=False):
    id: str
    program_id: str
    name: str
    address: str
    capacity_kg: int
    stored_kg: float
    pending_pickup_kg: float
    posture: str
    host_agreement_id: Optional[str]
    archived: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class SiteHostAgreement(TypedDict, total=False):
    id: str
    program_id: str
    site_id: str
    host_name: str
    term_start: str
    term_end: str
    cure_period_days: int
    status: str
    breach_noticed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MaterialCategory(TypedDict, total=False):
    id: str
    program_id: str
    code: str
    description: str
    accepted_start_month_day: str
    accepted_end_month_day: str
    contamination_sensitivity: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict, total=False):
    id: str
    program_id: str
    email: str
    full_name: str
    household_size: int
    status: str
    verification_token: Optional[str]
    bucket_credit_balance: int
    bucket_credits_granted_total: int
    bucket_credits_redeemed_total: int
    bucket_credits_expired_total: int
    suspension_count: int
    created_at: str
    updated_at: str
    version: int


class AccessGrant(TypedDict, total=False):
    id: str
    participant_id: str
    site_id: str
    access_code: str
    bucket_quota: int
    buckets_checked_out: int
    status: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class DropEvent(TypedDict, total=False):
    id: str
    site_id: str
    participant_id: str
    access_grant_id: str
    material_category_id: str
    gross_weight_kg: float
    contamination_kg: float
    provisional_net_kg: float
    final_net_kg: Optional[float]
    credit_state: str
    verification_state: str
    processing_batch_id: Optional[str]
    occurred_at: str
    created_at: str
    updated_at: str
    version: int


class ContaminationReport(TypedDict, total=False):
    id: str
    site_id: str
    drop_event_id: Optional[str]
    auditor_id: str
    severity: str
    finding_note: str
    feedback_sent_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CollectionRoute(TypedDict, total=False):
    id: str
    program_id: str
    route_code: str
    vehicle_capacity_kg: int
    processing_partner_id: str
    status: str
    scheduled_start: str
    scheduled_end: str
    assigned_load_kg: float
    created_at: str
    updated_at: str
    version: int


class ProcessingPartner(TypedDict, total=False):
    id: str
    program_id: str
    name: str
    intake_capacity_kg_per_day: int
    yield_ratio: float
    contamination_reject_threshold_pct: float
    active: bool
    created_at: str
    updated_at: str
    version: int


class RouteStop(TypedDict, total=False):
    id: str
    route_id: str
    site_id: str
    planned_pickup_kg: int
    actual_pickup_kg: Optional[float]
    stop_sequence: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProcessingBatch(TypedDict, total=False):
    id: str
    partner_id: str
    route_id: str
    input_gross_kg: float
    measured_contamination_kg: Optional[float]
    measured_net_kg: Optional[float]
    contamination_pct: Optional[float]
    finished_compost_kg: Optional[float]
    status: str
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CompostDistribution(TypedDict, total=False):
    id: str
    program_id: str
    batch_id: str
    total_pool_kg: float
    allocated_kg: float
    status: str
    opened_at: str
    created_at: str
    updated_at: str
    version: int


# Append-only per PRD §2.4: NO updated_at / version
class DistributionAllocation(TypedDict, total=False):
    id: str
    distribution_id: str
    participant_id: str
    requested_kg: float
    credits_redeemed: int
    allocation_kg: Optional[float]
    status: str
    created_at: str


class ComplaintTicket(TypedDict, total=False):
    id: str
    site_id: str
    reporter_contact: str
    kind: str
    description: str
    reported_at: str
    sla_due_at: str
    acknowledged_at: Optional[str]
    resolved_at: Optional[str]
    sla_breached: bool
    reopen_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only per PRD §2.4: NO updated_at / version
class DiversionReport(TypedDict, total=False):
    id: str
    program_id: str
    period_start: str
    period_end: str
    method: str
    gross_diverted_kg: float
    net_diverted_kg: float
    contamination_kg: float
    diversion_rate_pct: float
    certified_by: Optional[str]
    status: str
    created_at: str
