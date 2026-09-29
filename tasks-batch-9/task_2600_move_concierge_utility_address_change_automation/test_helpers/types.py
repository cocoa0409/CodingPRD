"""Typed vocabulary for the Move Concierge Utility Automation API.

Every literal string below is spelled exactly as the PRD spells it.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Actors (PRD 2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    FEED_INTEGRATOR = "FeedIntegrator"
    MOVE_OPS_AGENT = "MoveOpsAgent"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    RESIDENT = "Resident"
    PROVIDER_AGENT = "ProviderAgent"
    PARTNER_AGENT = "PartnerAgent"
    EXTERNAL_SERVICE_GATEWAY = "ExternalServiceGateway"


# ---------------------------------------------------------------------------
# Reference-data vocabulary (PRD 3.1)
# ---------------------------------------------------------------------------
class FeedStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SourceType(str, Enum):
    PROPERTY_MANAGER = "PROPERTY_MANAGER"
    MOVER = "MOVER"


class TrustTier(str, Enum):
    TIER_A = "TIER_A"
    TIER_B = "TIER_B"


class UtilityType(str, Enum):
    ELECTRIC = "ELECTRIC"
    GAS = "GAS"
    WATER = "WATER"
    INTERNET = "INTERNET"


class DepositPolicy(str, Enum):
    NONE = "NONE"
    FLAT = "FLAT"
    CREDIT_SCORE_BASED = "CREDIT_SCORE_BASED"


class ProviderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class AccountField(str, Enum):
    ACCOUNT_HOLDER_NAME = "account_holder_name"
    SERVICE_START_DATE = "service_start_date"
    SSN_LAST4 = "ssn_last4"
    PRIOR_ACCOUNT_NUMBER = "prior_account_number"
    UNIT_DESIGNATOR = "unit_designator"


class PartnerVertical(str, Enum):
    INTERNET = "INTERNET"
    INSURANCE = "INSURANCE"
    MOVERS = "MOVERS"


class PayoutModel(str, Enum):
    FLAT_BOUNTY = "FLAT_BOUNTY"
    REV_SHARE_PCT = "REV_SHARE_PCT"


class AttributionBasis(str, Enum):
    PLACEMENT_CLICK = "PLACEMENT_CLICK"
    PLACEMENT_ACCEPTANCE = "PLACEMENT_ACCEPTANCE"


class PartnerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"


# ---------------------------------------------------------------------------
# Move vocabulary (PRD 3.2, 3.9)
# ---------------------------------------------------------------------------
class MoveLifecycleStatus(str, Enum):
    INTAKE = "INTAKE"
    IDENTITY_PENDING = "IDENTITY_PENDING"
    IDENTITY_FAILED = "IDENTITY_FAILED"
    VERIFIED = "VERIFIED"
    SCHEDULING = "SCHEDULING"
    IN_SERVICE = "IN_SERVICE"
    ATTENTION_REQUIRED = "ATTENTION_REQUIRED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    DUPLICATE_MERGED = "DUPLICATE_MERGED"


class DuplicateFlag(str, Enum):
    NONE = "NONE"
    SUSPECTED = "SUSPECTED"
    DISMISSED = "DISMISSED"
    CONFIRMED_DUPLICATE = "CONFIRMED_DUPLICATE"


class BlockedReason(str, Enum):
    NONE = "NONE"
    DUPLICATE_SUSPECTED = "DUPLICATE_SUSPECTED"
    CONSENT_REVOKED = "CONSENT_REVOKED"
    PROVISION_FAILED = "PROVISION_FAILED"
    CREDIT_DECLINED = "CREDIT_DECLINED"
    FILING_REJECTED = "FILING_REJECTED"


class ConsentGate(str, Enum):
    OPEN = "OPEN"
    BLOCKED = "BLOCKED"


class DuplicateResolution(str, Enum):
    DISMISS = "DISMISS"
    RESCORE = "RESCORE"
    MERGE_INTO = "MERGE_INTO"


class ReadinessVariant(str, Enum):
    PRE_VERIFICATION = "pre_verification"
    POST_VERIFICATION = "post_verification"


# ---------------------------------------------------------------------------
# Identity vocabulary (PRD 3.3)
# ---------------------------------------------------------------------------
class VerificationMethod(str, Enum):
    KBA = "KBA"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"


class VerificationStatus(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class KbaOutcome(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"


# ---------------------------------------------------------------------------
# Service order vocabulary (PRD 3.5, 3.6)
# ---------------------------------------------------------------------------
class ProvisionStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    ACTIVE_SERVICE = "ACTIVE_SERVICE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PROVISION_FAILED = "PROVISION_FAILED"


class CreditStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING_CHECK = "PENDING_CHECK"
    CLEARED = "CLEARED"
    DEPOSIT_DUE = "DEPOSIT_DUE"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    DECLINED = "DECLINED"
    VOIDED = "VOIDED"


class OrderKind(str, Enum):
    START = "START"
    STOP = "STOP"


class OrderCancellationReason(str, Enum):
    MOVE_CANCELLED = "MOVE_CANCELLED"
    DUPLICATE_MERGED = "DUPLICATE_MERGED"


class OrderFailureReason(str, Enum):
    CREDIT_DECLINED = "CREDIT_DECLINED"


class HandoffStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    RESPONDED = "RESPONDED"
    VOIDED = "VOIDED"


class BureauName(str, Enum):
    EXPERIAN = "EXPERIAN"
    EQUIFAX = "EQUIFAX"
    TRANSUNION = "TRANSUNION"


class CreditResult(str, Enum):
    CLEAR = "CLEAR"
    DEPOSIT_REQUIRED = "DEPOSIT_REQUIRED"
    DECLINED = "DECLINED"


# ---------------------------------------------------------------------------
# Postal filing vocabulary (PRD 3.7)
# ---------------------------------------------------------------------------
class FilingStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class FilingType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    FAMILY = "FAMILY"
    BUSINESS = "BUSINESS"


class UspsOutcome(str, Enum):
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
# Consent vocabulary (PRD 3.4)
# ---------------------------------------------------------------------------
class ConsentScope(str, Enum):
    UTILITY_SETUP = "UTILITY_SETUP"
    USPS_FILING = "USPS_FILING"
    PARTNER_MARKETING = "PARTNER_MARKETING"


class ConsentSourceChannel(str, Enum):
    PM_FEED = "PM_FEED"
    WEB_PORTAL = "WEB_PORTAL"
    PHONE_ATTESTATION = "PHONE_ATTESTATION"


class ConsentState(str, Enum):
    GRANTED = "GRANTED"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


# ---------------------------------------------------------------------------
# Referral vocabulary (PRD 3.8)
# ---------------------------------------------------------------------------
class PlacementStatus(str, Enum):
    PLACED = "PLACED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    CONVERTED = "CONVERTED"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"
    VOIDED = "VOIDED"


class LedgerEntryType(str, Enum):
    ACCRUAL = "ACCRUAL"
    FEED_SOURCE_SHARE = "FEED_SOURCE_SHARE"
    ADJUSTMENT = "ADJUSTMENT"
    FEED_SOURCE_SHARE_ADJUSTMENT = "FEED_SOURCE_SHARE_ADJUSTMENT"
    REVERSAL = "REVERSAL"
    FEED_SOURCE_SHARE_REVERSAL = "FEED_SOURCE_SHARE_REVERSAL"


# ---------------------------------------------------------------------------
# Resource shapes (PRD 2.5).  Thirteen of the fourteen resource types carry
# id, created_at, updated_at and version; RevenueShareLedgerEntry carries
# only id and created_at.
# ---------------------------------------------------------------------------
class VersionedResource(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class FeedSource(VersionedResource):
    name: str
    source_type: str
    referral_revenue_share_pct: float
    dedupe_window_days: int
    trust_tier: str
    feed_status: str
    accrued_share_cents: int


class Resident(VersionedResource):
    full_name: str
    email: str
    phone_last4: str
    date_of_birth: str
    ssn_last4: str
    marketing_opt_out: bool
    opted_out_at: Optional[str]


class ServiceAddress(VersionedResource):
    line1: str
    unit: Optional[str]
    city: str
    state_code: str
    postal_code: str
    address_hash: str
    usps_deliverable: bool


class UtilityProvider(VersionedResource):
    name: str
    utility_type: str
    required_account_fields: List[str]
    deposit_policy: str
    flat_deposit_cents: int
    credit_check_required: bool
    scheduling_lead_days: int
    same_day_stop_allowed: bool
    provider_status: str


class ProviderServiceTerritory(VersionedResource):
    provider_id: str
    postal_code: str
    state_code: str
    effective_from: str
    effective_to: Optional[str]
    priority_rank: int
    is_default_carrier: bool


class MoveRecord(VersionedResource):
    resident_id: str
    feed_source_id: str
    origin_address_id: str
    destination_address_id: str
    move_date: str
    external_reference: Optional[str]
    lifecycle_status: str
    duplicate_flag: str
    duplicate_match_score: float
    duplicate_candidate_move_id: Optional[str]
    duplicate_of_move_id: Optional[str]
    reactivation_candidate_move_id: Optional[str]
    consent_gate: str
    blocked_reason: str
    readiness_score: int
    mapped_order_count: int
    unmapped_utility_types: List[str]
    verified_at: Optional[str]
    identity_attempt_count: int
    cancellation_reason: Optional[str]


class IdentityVerification(VersionedResource):
    move_id: str
    resident_id: str
    method: str
    attempt_no: int
    status: str
    kba_score: Optional[int]
    override_reason: Optional[str]
    reviewer_user_id: Optional[str]
    expires_at: Optional[str]
    decided_at: Optional[str]


class UtilityOrder(VersionedResource):
    move_id: str
    provider_id: str
    territory_id: Optional[str]
    service_address_id: str
    utility_type: str
    order_kind: str
    provision_status: str
    credit_status: str
    requested_service_date: Optional[str]
    scheduled_window_start: Optional[str]
    scheduled_window_end: Optional[str]
    account_data: Dict[str, Any]
    deposit_estimate_cents: int
    deposit_amount_cents: int
    deposit_paid_cents: int
    readiness_snapshot: Optional[int]
    confirmation_code: Optional[str]
    cancellation_reason: Optional[str]
    failure_reason: Optional[str]
    waiver_reason: Optional[str]


class CreditCheckHandoff(VersionedResource):
    utility_order_id: str
    bureau: str
    handoff_status: str
    score: Optional[int]
    result: Optional[str]
    submitted_by_user_id: str
    readiness_snapshot: Optional[int]
    responded_at: Optional[str]


class AddressChangeFiling(VersionedResource):
    move_id: str
    resident_id: str
    filing_type: str
    forward_start_date: str
    forward_end_date: str
    status: str
    submitted_by_user_id: Optional[str]
    usps_confirmation_code: Optional[str]
    reject_reason: Optional[str]
    mail_forwarding_confirmed_at: Optional[str]
    cancellation_reason: Optional[str]
    resubmit_count: int


class ReferralPartner(VersionedResource):
    name: str
    vertical: str
    payout_model: str
    bounty_cents: int
    rev_share_pct: float
    attribution_window_days: int
    attribution_basis: str
    monthly_placement_cap: int
    partner_status: str


class ReferralPlacement(VersionedResource):
    move_id: str
    partner_id: str
    vertical: str
    placement_status: str
    placed_at: str
    accepted_at: Optional[str]
    converted_at: Optional[str]
    decline_reason: Optional[str]
    reversal_reason: Optional[str]
    gross_revenue_cents: int
    settled_gross_revenue_cents: int
    attributed_share_cents: int
    feed_source_share_cents: int


class ConsentRecord(VersionedResource):
    resident_id: str
    move_id: Optional[str]
    scope: str
    source_channel: str
    consent_text_version: str
    state: str
    granted_at: str
    expires_at: Optional[str]
    revoked_at: Optional[str]
    revocation_reason: Optional[str]


class RevenueShareLedgerEntry(TypedDict):
    """Append-only and immutable: only id and created_at (PRD 2.5)."""

    id: str
    created_at: str
    placement_id: str
    move_id: str
    feed_source_id: str
    entry_type: str
    amount_cents: int
    posted_at: str


class MoveReadiness(TypedDict):
    """Shape returned by the computed readiness read (PRD 3.9)."""

    move_id: str
    variant: str
    identity_component: int
    utility_component: int
    filing_component: int
    consent_component: int
    readiness_score: int
