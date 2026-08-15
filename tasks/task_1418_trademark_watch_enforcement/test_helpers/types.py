"""Domain types: entity TypedDicts, status enums, role enum.

All resources carry the common system-managed fields id, created_at,
updated_at, and version per the PRD's common-resource-properties section.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PARALEGAL = "Paralegal"
    ASSOCIATE_ATTORNEY = "AssociateAttorney"
    PARTNER_ATTORNEY = "PartnerAttorney"
    CLIENT_CONTACT = "ClientContact"
    WATCH_SERVICE = "WatchService"


class TrademarkRecordStatus(str, Enum):
    APPLICATION_PENDING = "APPLICATION_PENDING"
    PUBLISHED = "PUBLISHED"
    REGISTERED = "REGISTERED"
    UNDER_CHALLENGE = "UNDER_CHALLENGE"
    MAINTENANCE_DUE = "MAINTENANCE_DUE"
    CANCELLED = "CANCELLED"


class WatchAlertStatus(str, Enum):
    NEW = "NEW"
    TRIAGED = "TRIAGED"
    UNDER_ASSESSMENT = "UNDER_ASSESSMENT"
    MONITORING = "MONITORING"
    ESCALATED = "ESCALATED"
    DISMISSED = "DISMISSED"


class Tier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class EnforcementMatterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"


class MatterType(str, Enum):
    OPPOSITION = "OPPOSITION"
    CANCELLATION = "CANCELLATION"
    INFRINGEMENT = "INFRINGEMENT"
    COUNTERFEIT = "COUNTERFEIT"


class MatterPosture(str, Enum):
    NORMAL = "NORMAL"
    JEOPARDY = "JEOPARDY"


class ResolutionOutcome(str, Enum):
    FAVORABLE = "FAVORABLE"
    ADVERSE = "ADVERSE"
    SETTLED = "SETTLED"


class DeadlineStatus(str, Enum):
    DOCKETED = "DOCKETED"
    PENDING = "PENDING"
    EXTENDED = "EXTENDED"
    SATISFIED = "SATISFIED"
    MISSED = "MISSED"


class DeadlineType(str, Enum):
    OPPOSITION_WINDOW = "OPPOSITION_WINDOW"
    RESPONSE_DUE = "RESPONSE_DUE"
    OFFICE_ACTION = "OFFICE_ACTION"
    RENEWAL = "RENEWAL"
    CUSTOM = "CUSTOM"


class ComputationVariant(str, Enum):
    CALENDAR_ROLL_FORWARD = "CALENDAR_ROLL_FORWARD"
    BUSINESS_DAY_COUNT = "BUSINESS_DAY_COUNT"


class LetterStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    ISSUED = "ISSUED"
    NEGOTIATING = "NEGOTIATING"
    COMPLIED = "COMPLIED"
    REFUSED = "REFUSED"
    ESCALATED_LITIGATION = "ESCALATED_LITIGATION"
    VOID = "VOID"


class DemandType(str, Enum):
    CEASE_USE = "CEASE_USE"
    CANCEL_REGISTRATION = "CANCEL_REGISTRATION"
    DELIST_MARKETPLACE = "DELIST_MARKETPLACE"


class LetterDecision(str, Enum):
    APPROVED = "APPROVED"
    SENT_BACK = "SENT_BACK"


class ResponseOutcome(str, Enum):
    COMPLIED = "COMPLIED"
    REFUSED = "REFUSED"
    NEGOTIATION_STARTED = "NEGOTIATION_STARTED"


class TakedownStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    REJECTED = "REJECTED"
    APPEALED = "APPEALED"
    REMOVED = "REMOVED"
    REINSTATED = "REINSTATED"


class Platform(str, Enum):
    AMAZON = "AMAZON"
    EBAY = "EBAY"
    ALIBABA = "ALIBABA"
    META = "META"
    DOMAIN_REGISTRAR = "DOMAIN_REGISTRAR"


class TakedownBasis(str, Enum):
    TRADEMARK = "TRADEMARK"
    COUNTERFEIT = "COUNTERFEIT"


class PlatformOutcome(str, Enum):
    REMOVED = "REMOVED"
    REJECTED = "REJECTED"
    REINSTATED = "REINSTATED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    EXECUTED = "EXECUTED"
    MONITORING = "MONITORING"
    BREACH_ALLEGED = "BREACH_ALLEGED"
    CURE_PERIOD = "CURE_PERIOD"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"


class CureAction(str, Enum):
    GRANT = "GRANT"
    CONFIRM_CURED = "CONFIRM_CURED"


class EvidenceStatus(str, Enum):
    COLLECTED = "COLLECTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class SpecimenType(str, Enum):
    LABEL = "LABEL"
    SCREENSHOT = "SCREENSHOT"
    PACKAGING = "PACKAGING"
    ADVERTISING = "ADVERTISING"


class MaintenanceStatus(str, Enum):
    PREPARED = "PREPARED"
    SUBMITTED = "SUBMITTED"
    LATE_FILED = "LATE_FILED"
    ACCEPTED = "ACCEPTED"
    REJECTED_OFFICE = "REJECTED_OFFICE"


class FilingType(str, Enum):
    SECTION_8 = "SECTION_8"
    RENEWAL = "RENEWAL"


class OfficeDecision(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ClearanceStatus(str, Enum):
    OPEN = "OPEN"
    CLEARED = "CLEARED"
    BLOCKED = "BLOCKED"


class HitSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    IDENTICAL = "IDENTICAL"


class HitDisposition(str, Enum):
    OPEN = "OPEN"
    WAIVED = "WAIVED"
    BLOCKING = "BLOCKING"


class RecordationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    RENEWED = "RENEWED"
    REVOKED = "REVOKED"


class CustomsAuthority(str, Enum):
    US_CBP = "US_CBP"
    EU_TAXUD = "EU_TAXUD"
    CN_GACC = "CN_GACC"


class ReferralStatus(str, Enum):
    DRAFT = "DRAFT"
    REFERRED = "REFERRED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class ReferralChannel(str, Enum):
    LAW_ENFORCEMENT = "LAW_ENFORCEMENT"
    CUSTOMS_SEIZE = "CUSTOMS_SEIZE"
    PLATFORM_ESCROW = "PLATFORM_ESCROW"


class AlertSource(str, Enum):
    WATCH_SERVICE = "WATCH_SERVICE"
    MANUAL = "MANUAL"
    MARKETPLACE_SWEEP = "MARKETPLACE_SWEEP"


class EscalationLevel(str, Enum):
    STANDARD = "STANDARD"
    URGENT = "URGENT"


class WatchPosture(str, Enum):
    STANDARD = "STANDARD"
    ELEVATED = "ELEVATED"


class Client(TypedDict, total=False):
    id: str
    name: str
    industry: str
    enforcement_budget_cents: int
    budget_spent_cents: int
    budget_remaining_cents: int
    exposure_index: int
    watch_posture: str
    created_at: str
    updated_at: str
    version: int


class TrademarkRecord(TypedDict, total=False):
    id: str
    client_id: str
    mark_text: str
    mark_type: str
    jurisdiction: str
    nice_classes: List[int]
    application_number: str
    status: str
    publication_date: Optional[str]
    registration_date: Optional[str]
    opposition_due_at: Optional[str]
    verified_evidence_count: int
    maintenance_window_open: Optional[str]
    maintenance_window_close: Optional[str]
    maintenance_grace_close: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WatchAlert(TypedDict, total=False):
    id: str
    trademark_record_id: str
    source: str
    conflicting_mark_text: str
    conflicting_owner: str
    conflicting_classes: List[int]
    similarity_mark: int
    similarity_goods: int
    similarity_channels: int
    provisional_score: float
    provisional_tier: str
    final_score: Optional[float]
    final_tier: Optional[str]
    assessment_round: int
    escalation_level: str
    confirmed_counterfeit_count: int
    referral_auto_created: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class EnforcementMatter(TypedDict, total=False):
    id: str
    client_id: str
    trademark_record_id: str
    watch_alert_id: str
    matter_type: str
    status: str
    posture: str
    resolution_outcome: Optional[str]
    accrued_fees_cents: int
    open_deadline_count: int
    created_at: str
    updated_at: str
    version: int


class Deadline(TypedDict, total=False):
    id: str
    enforcement_matter_id: str
    deadline_type: str
    statutory_basis: str
    basis_date: str
    offset_days: int
    computation_variant: str
    computed_due_at: str
    extension_count: int
    max_extensions: int
    docketed_by_user_id: str
    verified_by_user_id: Optional[str]
    satisfied_at: Optional[str]
    satisfied_late: bool
    requires_partner_review: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class CeaseDesistLetter(TypedDict, total=False):
    id: str
    enforcement_matter_id: str
    demand_type: str
    recipient_name: str
    recipient_address: str
    response_due_days: int
    settlement_amount_cents: Optional[int]
    installment_count: int
    drafted_by_user_id: str
    approved_by_user_id: Optional[str]
    issued_at: Optional[str]
    response_due_at: Optional[str]
    reissue_count: int
    installment_schedule: Optional[List[int]]
    status: str
    created_at: str
    updated_at: str
    version: int


class TakedownFiling(TypedDict, total=False):
    id: str
    watch_alert_id: str
    platform: str
    listing_url: str
    basis: str
    fee_cents: int
    appeal_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CoexistenceAgreement(TypedDict, total=False):
    id: str
    trademark_record_id: str
    enforcement_matter_id: Optional[str]
    counterparty_name: str
    territory_codes: List[str]
    effective_start: str
    effective_end: str
    cure_period_days: int
    round_count: int
    current_terms_text: Optional[str]
    breach_claimed_at: Optional[str]
    cure_deadline: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class UseEvidenceItem(TypedDict, total=False):
    id: str
    trademark_record_id: str
    nice_class: int
    specimen_type: str
    specimen_date: str
    collected_by_user_id: str
    verified_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MaintenanceFiling(TypedDict, total=False):
    id: str
    trademark_record_id: str
    filing_type: str
    evidence_item_ids: List[str]
    fee_base_cents: int
    fee_surcharge_cents: int
    late_fee_cents: int
    fee_total_cents: int
    is_late: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ClearanceSearch(TypedDict, total=False):
    id: str
    client_id: str
    proposed_mark: str
    proposed_classes: List[int]
    conflict_hits: List[Dict[str, Any]]
    unresolved_hit_count: int
    risk_rating: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CustomsRecordation(TypedDict, total=False):
    id: str
    trademark_record_id: str
    customs_authority: str
    recordation_number: str
    term_start: str
    term_end: str
    supersedes_recordation_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CounterfeitReferral(TypedDict, total=False):
    id: str
    watch_alert_id: str
    enforcement_matter_id: Optional[str]
    referral_channel: str
    seizure_lines: List[Dict[str, int]]
    estimated_damages_cents: int
    auto_created: bool
    status: str
    created_at: str
    updated_at: str
    version: int
