"""Domain types: entity TypedDicts, status enums, role enum (PRD §3, §4)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PRIVACY_ADMIN = "PrivacyAdmin"
    DATA_STEWARD = "DataSteward"
    BUSINESS_OWNER = "BusinessOwner"
    LEGAL_COUNSEL = "LegalCounsel"
    VENDOR_MANAGER = "VendorManager"
    CONSUMER = "Consumer"


class DataElementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class DataSystemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DECOMMISSIONED = "DECOMMISSIONED"


class NoticeStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    RETRACTED = "RETRACTED"


class VendorStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ASSESSMENT = "ASSESSMENT"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    OFFBOARDED = "OFFBOARDED"


class VendorContractStatus(str, Enum):
    DRAFT = "DRAFT"
    VERIFIED = "VERIFIED"
    EXECUTED = "EXECUTED"
    SUPERSEDED = "SUPERSEDED"


class ContractVerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class ActivityStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLIANCE_HOLD = "COMPLIANCE_HOLD"
    RETIRED = "RETIRED"


class PurposeStatus(str, Enum):
    DOCUMENTED = "DOCUMENTED"
    CONSENT_STALE = "CONSENT_STALE"
    RETIRED = "RETIRED"


class AssessmentStatus(str, Enum):
    TRIGGERED = "TRIGGERED"
    IN_REVIEW = "IN_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class RequestVerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"


class FulfillmentStatus(str, Enum):
    INTAKE = "INTAKE"
    ROUTED = "ROUTED"
    IN_PROGRESS = "IN_PROGRESS"
    READY_TO_RESPOND = "READY_TO_RESPOND"
    COMPLETED = "COMPLETED"
    DENIED = "DENIED"


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TransferStatus(str, Enum):
    PROPOSED = "PROPOSED"
    UNDER_ASSESSMENT = "UNDER_ASSESSMENT"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class RetentionPolicy(TypedDict, total=False):
    id: str
    policy_code: str
    duration_days: int
    disposal_action: str
    created_at: str
    updated_at: str
    version: int


class DataElement(TypedDict, total=False):
    id: str
    element_key: str
    category: str
    classification: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DataSystem(TypedDict, total=False):
    id: str
    system_key: str
    hosting_region: str
    stores_categories: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Notice(TypedDict, total=False):
    id: str
    scope: str
    title: str
    body: str
    effective_from: str
    effective_to: Optional[str]
    supersedes_notice_id: Optional[str]
    status: str
    published_at: Optional[str]
    superseded_by_notice_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StateLawRule(TypedDict, total=False):
    id: str
    state_code: str
    law_name: str
    resident_records_threshold: int
    revenue_share_threshold_pct: float
    request_deadline_days: int
    extension_days: int
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict, total=False):
    id: str
    vendor_name: str
    home_region: str
    processes_categories: List[str]
    risk_tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class VendorContract(TypedDict, total=False):
    id: str
    vendor_id: str
    provided_clauses: List[str]
    required_clauses: List[str]
    missing_clauses: List[str]
    verification_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ProcessingActivity(TypedDict, total=False):
    id: str
    activity_name: str
    business_unit: str
    notice_scope: str
    data_element_ids: List[str]
    vendor_id: Optional[str]
    risk_score: int
    pia_required: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Purpose(TypedDict, total=False):
    id: str
    activity_id: str
    purpose_type: str
    legal_basis: str
    retention_policy_id: str
    pinned_notice_id: Optional[str]
    retention_expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PrivacyImpactAssessment(TypedDict, total=False):
    id: str
    activity_id: str
    trigger_reason: str
    screening_score: int
    final_score: Optional[int]
    submitted_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Consumer(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    state_code: str
    created_at: str
    updated_at: str
    version: int


class RightsRequest(TypedDict, total=False):
    id: str
    consumer_id: str
    request_type: str
    requested_categories: List[str]
    applicable_state_code: Optional[str]
    provisional_due_at: str
    final_due_at: Optional[str]
    is_overdue: bool
    verification_status: str
    fulfillment_status: str
    created_at: str
    updated_at: str
    version: int


class RequestTask(TypedDict, total=False):
    id: str
    request_id: str
    data_system_id: str
    status: str
    outcome_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CrossBorderTransfer(TypedDict, total=False):
    id: str
    source_system_id: str
    vendor_id: str
    vendor_contract_id: str
    activity_id: str
    dest_region: str
    mechanism: str
    effective_from: str
    effective_to: str
    suspension_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only audit record (PRD §2.4): carries id + created_at only —
# NO updated_at, NO version.
class ApplicabilityEvaluation(TypedDict, total=False):
    id: str
    state_law_rule_id: str
    evaluation_run_id: str
    resident_consumer_count: int
    revenue_share_pct: float
    applies: bool
    margin_to_threshold: int
    created_at: str
