"""Domain types: entity TypedDicts, status enums, role enum for the Privacy DSAR API."""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    INTAKE_AGENT = "IntakeAgent"
    PRIVACY_OFFICER = "PrivacyOfficer"
    FULFILLMENT_WORKER = "FulfillmentWorker"
    PROCESSOR_AGENT = "ProcessorAgent"
    DATA_SUBJECT_AGENT = "DataSubjectAgent"


# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------
class Jurisdiction(str, Enum):
    GDPR = "GDPR"
    CCPA = "CCPA"


class RequestType(str, Enum):
    ACCESS = "ACCESS"
    DELETION = "DELETION"
    OPT_OUT = "OPT_OUT"


class DsarStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFICATION_REJECTED = "VERIFICATION_REJECTED"
    DISCOVERY = "DISCOVERY"
    UNDER_REVIEW = "UNDER_REVIEW"
    FULFILLING = "FULFILLING"
    CLOSED_FULFILLED = "CLOSED_FULFILLED"
    CLOSED_REJECTED = "CLOSED_REJECTED"
    CLOSED_EXPIRED = "CLOSED_EXPIRED"


class DataCategory(str, Enum):
    IDENTITY = "IDENTITY"
    FINANCIAL = "FINANCIAL"
    BEHAVIORAL = "BEHAVIORAL"
    CONTACT = "CONTACT"
    HEALTH = "HEALTH"


class Confidence(str, Enum):
    EXACT = "EXACT"
    PROBABLE = "PROBABLE"


class FindingState(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"


class ExemptionBasis(str, Enum):
    LEGAL_OBLIGATION = "LEGAL_OBLIGATION"
    FREEDOM_OF_EXPRESSION = "FREEDOM_OF_EXPRESSION"
    LEGAL_HOLD = "LEGAL_HOLD"
    TRADE_SECRET = "TRADE_SECRET"


class ExemptionState(str, Enum):
    ASSERTED = "ASSERTED"
    UPHELD = "UPHELD"
    OVERRULED = "OVERRULED"


class FulfillmentAction(str, Enum):
    DISCLOSE = "DISCLOSE"
    ERASE = "ERASE"
    SUPPRESS = "SUPPRESS"


class FulfillmentItemState(str, Enum):
    QUEUED = "QUEUED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    SKIPPED_EXEMPT = "SKIPPED_EXEMPT"


class NotificationState(str, Enum):
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    OVERDUE = "OVERDUE"


class ConsentPurpose(str, Enum):
    MARKETING = "MARKETING"
    ANALYTICS = "ANALYTICS"
    SALE_OF_DATA = "SALE_OF_DATA"
    ESSENTIAL = "ESSENTIAL"


class ConsentState(str, Enum):
    GRANTED = "GRANTED"
    WITHDRAWN = "WITHDRAWN"


class ProcessorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class LegalHoldState(str, Enum):
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"


class JurisdictionResidency(str, Enum):
    EU = "EU"
    CALIFORNIA = "CALIFORNIA"
    OTHER = "OTHER"


# --------------------------------------------------------------------------
# Entity TypedDicts
# --------------------------------------------------------------------------
# common_fields: true — id + created_at + updated_at + version
class Controller(TypedDict):
    id: str
    name: str
    jurisdiction: str
    dpo_email: str
    open_request_count: int
    created_at: str
    updated_at: str
    version: int


class DataSubject(TypedDict):
    id: str
    controller_id: str
    email: str
    full_name: str
    jurisdiction_residency: str
    known_record_count: int
    created_at: str
    updated_at: str
    version: int


class Processor(TypedDict):
    id: str
    controller_id: str
    name: str
    notify_email: str
    sla_ack_hours: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsentRecord(TypedDict):
    id: str
    data_subject_id: str
    purpose: str
    state: str
    withdrawn_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LegalHold(TypedDict):
    id: str
    controller_id: str
    data_subject_id: str
    matter_reference: str
    data_categories: List[str]
    state: str
    created_at: str
    updated_at: str
    version: int


class DsarRequest(TypedDict):
    id: str
    controller_id: str
    data_subject_id: str
    request_type: str
    received_at: str
    status: str
    identity_attempts: int
    extension_count: int
    deadline_at: str
    business_days_remaining: int
    discovery_finding_count: int
    fulfillment_progress_pct: float
    verified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DiscoveryFinding(TypedDict):
    id: str
    dsar_request_id: str
    processor_id: str
    data_category: str
    record_count: int
    confidence: str
    state: str
    created_at: str
    updated_at: str
    version: int


class ExemptionClaim(TypedDict):
    id: str
    dsar_request_id: str
    data_category: str
    basis: str
    state: str
    created_at: str
    updated_at: str
    version: int


class FulfillmentItem(TypedDict):
    id: str
    dsar_request_id: str
    discovery_finding_id: str
    processor_id: str
    data_category: str
    action: str
    record_count: int
    state: str
    created_at: str
    updated_at: str
    version: int


class ProcessorNotification(TypedDict):
    id: str
    fulfillment_item_id: str
    processor_id: str
    dispatched_at: str
    ack_deadline_at: str
    state: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only: id + created_at only
class AuditEvent(TypedDict):
    id: str
    dsar_request_id: str
    actor_role: str
    actor_user_id: str
    event_type: str
    detail: str
    created_at: str
