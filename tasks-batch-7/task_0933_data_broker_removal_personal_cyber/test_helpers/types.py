"""Domain types: entity TypedDicts, status enums, role enum.

Every name here is taken from the PRD's own vocabulary.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PRIVACY_AGENT = "PrivacyAgent"
    ACCOUNT_OWNER = "AccountOwner"
    MEMBER = "Member"
    AUDITOR = "Auditor"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------

class PlanTier(str, Enum):
    SOLO = "SOLO"
    FAMILY = "FAMILY"
    FAMILY_PLUS = "FAMILY_PLUS"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class HoldState(str, Enum):
    HOLD_ON = "HOLD_ON"
    HOLD_OFF = "HOLD_OFF"


class MemberStatus(str, Enum):
    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class AuthorizationStatus(str, Enum):
    GRANTED = "GRANTED"
    REVOKED = "REVOKED"


class RoleInFamily(str, Enum):
    PRIMARY = "PRIMARY"
    ADULT = "ADULT"
    MINOR = "MINOR"


class MonitoredProfileStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    RETIRED = "RETIRED"


class HygieneBand(str, Enum):
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"
    CRITICAL = "CRITICAL"


class IdentifierType(str, Enum):
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    USERNAME = "USERNAME"
    SSN_LAST4 = "SSN_LAST4"
    ADDRESS = "ADDRESS"


class OptOutMethod(str, Enum):
    WEB_FORM = "WEB_FORM"
    EMAIL = "EMAIL"
    POSTAL = "POSTAL"
    PHONE = "PHONE"


class Jurisdiction(str, Enum):
    US_CA = "US_CA"
    US_VA = "US_VA"
    EU = "EU"
    OTHER = "OTHER"


class BrokerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class DocumentType(str, Enum):
    PASSPORT = "PASSPORT"
    DRIVERS_LICENSE = "DRIVERS_LICENSE"
    STATE_ID = "STATE_ID"
    UTILITY_BILL = "UTILITY_BILL"


class IdentityDocumentStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class EffectiveStatus(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"


class ScanKind(str, Enum):
    INITIAL = "INITIAL"
    RECURRING = "RECURRING"


class ScanRunStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ExposureKind(str, Enum):
    PEOPLE_SEARCH = "PEOPLE_SEARCH"
    MARKETING_LIST = "MARKETING_LIST"
    CREDIT_HEADER = "CREDIT_HEADER"
    PUBLIC_RECORD = "PUBLIC_RECORD"


class ExposureStatus(str, Enum):
    FOUND = "FOUND"
    SUPPRESSED = "SUPPRESSED"
    REAPPEARED = "REAPPEARED"
    RE_SUPPRESSED = "RE_SUPPRESSED"


class RemovalRequestStatus(str, Enum):
    DRAFTED = "DRAFTED"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    ESCALATED = "ESCALATED"
    VOIDED = "VOIDED"


class DeadlineVariant(str, Enum):
    BASE = "BASE"
    ESCALATED_RESUBMISSION = "ESCALATED_RESUBMISSION"


class RecordType(str, Enum):
    EMAIL_ADDRESS = "EMAIL_ADDRESS"
    PHONE_NUMBER = "PHONE_NUMBER"
    PHYSICAL_ADDRESS = "PHYSICAL_ADDRESS"
    PASSWORD_HASH = "PASSWORD_HASH"
    FINANCIAL_ACCOUNT = "FINANCIAL_ACCOUNT"
    SSN = "SSN"


class AlertSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AlertStatus(str, Enum):
    NEW = "NEW"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


class FindingType(str, Enum):
    BREACHED_PASSWORD = "BREACHED_PASSWORD"
    WEAK_PASSWORD = "WEAK_PASSWORD"
    REUSED_PASSWORD = "REUSED_PASSWORD"
    STALE_PASSWORD = "STALE_PASSWORD"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    REMEDIATED = "REMEDIATED"


class AddOnType(str, Enum):
    VPN = "VPN"
    DEVICE_PROTECTION = "DEVICE_PROTECTION"


class AddOnStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class DeviceSeatStatus(str, Enum):
    BOUND = "BOUND"
    RELEASED = "RELEASED"
    VOIDED = "VOIDED"


class BillingCycleStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ResourceType(str, Enum):
    PROFILE = "PROFILE"
    SCAN = "SCAN"
    REMOVAL = "REMOVAL"


class EntryType(str, Enum):
    GRANT = "GRANT"
    CONSUME = "CONSUME"
    RELEASE = "RELEASE"


class ReasonCode(str, Enum):
    CYCLE_GRANT = "CYCLE_GRANT"
    PROFILE_ACTIVATED = "PROFILE_ACTIVATED"
    PROFILE_RETIRED = "PROFILE_RETIRED"
    SCAN_QUEUED = "SCAN_QUEUED"
    SCAN_CANCELLED = "SCAN_CANCELLED"
    SCAN_ABANDONED = "SCAN_ABANDONED"
    REMOVAL_DRAFTED = "REMOVAL_DRAFTED"
    REMOVAL_VOIDED = "REMOVAL_VOIDED"
    AUTHORIZATION_REVOKED = "AUTHORIZATION_REVOKED"


class ChangeKind(str, Enum):
    UPGRADE = "UPGRADE"
    DOWNGRADE = "DOWNGRADE"


class ComplianceScope(str, Enum):
    LIFETIME = "LIFETIME"
    CURRENT_WINDOW = "CURRENT_WINDOW"


class AuthorizationAction(str, Enum):
    GRANT = "GRANT"
    REVOKE = "REVOKE"


# --------------------------------------------------------------------------
# Entity shapes.  Resources carrying id + created_at + updated_at + version
# are the norm; the two exceptions (identifier, ledger entry) are called out
# in the PRD and carry only id + created_at.
# --------------------------------------------------------------------------

class Plan(TypedDict):
    id: str
    tier: str
    name: str
    monthly_fee_cents: int
    max_members: int
    profile_quota_per_cycle: int
    scan_quota_per_cycle: int
    removal_quota_per_cycle: int
    per_member_removal_subcap: int
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict):
    id: str
    plan_id: str
    primary_member_id: str
    status: str
    legal_hold: bool
    legal_hold_set_at: Optional[str]
    suspended_at: Optional[str]
    cancelled_at: Optional[str]
    profile_units_granted: int
    profile_units_consumed: int
    profile_units_released: int
    profile_units_remaining: int
    scan_units_granted: int
    scan_units_consumed: int
    scan_units_released: int
    scan_units_remaining: int
    removal_units_granted: int
    removal_units_consumed: int
    removal_units_released: int
    removal_units_remaining: int
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    account_id: str
    email: str
    full_name: str
    role_in_family: str
    is_primary: bool
    status: str
    authorization_status: str
    invitation_token: Optional[str]
    activated_at: Optional[str]
    authorization_revoked_at: Optional[str]
    removal_units_consumed_this_cycle: int
    created_at: str
    updated_at: str
    version: int


class MonitoredProfile(TypedDict):
    id: str
    member_id: str
    full_name: str
    date_of_birth: str
    primary_address: str
    rescan_cadence_days: int
    two_factor_attested: bool
    status: str
    activated_at: Optional[str]
    retired_at: Optional[str]
    last_completed_scan_at: Optional[str]
    open_exposure_count: int
    suppressed_exposure_count: int
    hygiene_score: float
    hygiene_band: str
    created_at: str
    updated_at: str
    version: int


class Identifier(TypedDict):
    """Immutable — carries only id and created_at (PRD §2.4)."""
    id: str
    profile_id: str
    identifier_type: str
    identifier_value: str
    created_at: str


class Broker(TypedDict):
    id: str
    name: str
    opt_out_method: str
    jurisdiction: str
    response_window_days: int
    requires_identity_verification: bool
    status: str
    retired_at: Optional[str]
    reappearance_count: int
    expired_request_count: int
    rejected_request_count: int
    on_time_completion_count: int
    compliance_score: int
    created_at: str
    updated_at: str
    version: int


class IdentityDocument(TypedDict):
    id: str
    member_id: str
    document_type: str
    document_reference: str
    expires_at: str
    status: str
    verified_at: Optional[str]
    rejection_reason_code: Optional[str]
    effective_status: str
    created_at: str
    updated_at: str
    version: int


class ScanRun(TypedDict):
    id: str
    profile_id: str
    kind: str
    status: str
    retry_count: int
    started_at: Optional[str]
    completed_at: Optional[str]
    failure_reason: Optional[str]
    entitlement_units_held: int
    findings_count: int
    new_exposure_count: int
    reappearance_hit_count: int
    created_at: str
    updated_at: str
    version: int


class ExposureRecord(TypedDict):
    id: str
    profile_id: str
    broker_id: str
    discovered_by_scan_id: str
    exposure_kind: str
    source_url: str
    status: str
    first_found_at: str
    last_seen_at: str
    last_suppressed_at: Optional[str]
    suppression_count: int
    reappearance_count: int
    fee_exempt: bool
    created_at: str
    updated_at: str
    version: int


class RemovalRequest(TypedDict):
    id: str
    exposure_id: str
    broker_id: str
    member_id: str
    status: str
    submitted_at: Optional[str]
    acknowledged_at: Optional[str]
    closed_at: Optional[str]
    sla_deadline_at: Optional[str]
    effective_window_days: Optional[int]
    deadline_variant: Optional[str]
    submitted_by_agent_id: Optional[str]
    completed_by_agent_id: Optional[str]
    broker_reference: Optional[str]
    rejection_reason_code: Optional[str]
    escalation_count: int
    entitlement_units_consumed: int
    entitlement_units_released: int
    on_time: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class BreachEvent(TypedDict):
    id: str
    name: str
    breach_date: str
    disclosed_at: str
    record_types: List[str]
    base_severity_points: int
    ingest_count: int
    alert_count: int
    created_at: str
    updated_at: str
    version: int


class BreachAlert(TypedDict):
    id: str
    breach_event_id: str
    identifier_id: str
    member_id: str
    severity: str
    severity_points: int
    status: str
    acknowledged_at: Optional[str]
    resolved_at: Optional[str]
    escalation_count: int
    created_at: str
    updated_at: str
    version: int


class CredentialFinding(TypedDict):
    id: str
    profile_id: str
    finding_type: str
    detail: str
    status: str
    weight: int
    remediated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AddOnSubscription(TypedDict):
    id: str
    account_id: str
    addon_type: str
    seats_total: int
    per_seat_fee_cents: int
    status: str
    suspended_at: Optional[str]
    prorated_charge_cents: int
    seats_bound: int
    seats_available: int
    created_at: str
    updated_at: str
    version: int


class DeviceSeat(TypedDict):
    id: str
    addon_id: str
    member_id: str
    device_label: str
    status: str
    bound_at: Optional[str]
    released_at: Optional[str]
    voided_at: Optional[str]
    bind_count: int
    rebind_eligible_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BillingCycle(TypedDict):
    id: str
    account_id: str
    cycle_seq: int
    starts_at: str
    ends_at: str
    status: str
    base_charge_cents: int
    proration_charge_cents: int
    proration_credit_cents: int
    addon_charge_cents: int
    addon_credit_cents: int
    pre_discount_total_cents: int
    loyalty_discount_cents: int
    total_charged_cents: int
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EntitlementLedgerEntry(TypedDict):
    """Append-only — carries only id and created_at (PRD §2.4)."""
    id: str
    account_id: str
    member_id: Optional[str]
    cycle_id: str
    resource_type: str
    entry_type: str
    amount: int
    signed_amount: int
    reason_code: str
    source_reference: str
    created_at: str
