"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class PartyKind(str, Enum):
    LANDLORD = "LANDLORD"
    TENANT = "TENANT"
    SUBTENANT = "SUBTENANT"
    ASSIGNEE = "ASSIGNEE"


class UserRole(str, Enum):
    ASSET_MANAGER = "AssetManager"
    TENANT_REP_BROKER = "TenantRepBroker"
    LANDLORD = "Landlord"
    TENANT = "Tenant"
    SUBTENANT = "Subtenant"
    ASSIGNEE = "Assignee"


class LeaseStatus(str, Enum):
    ACTIVE = "ACTIVE"


class MeasurementStandard(str, Enum):
    METHOD_A = "METHOD_A"
    METHOD_B = "METHOD_B"


class DemisedAreaStatus(str, Enum):
    DRAFT = "DRAFT"
    CERTIFIED = "CERTIFIED"
    SUPERSEDED = "SUPERSEDED"


class TransferType(str, Enum):
    SUBLEASE = "SUBLEASE"
    ASSIGNMENT = "ASSIGNMENT"


class TransferStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CONSENT_PENDING = "CONSENT_PENDING"
    CONSENT_GRANTED = "CONSENT_GRANTED"
    CONSENT_DENIED = "CONSENT_DENIED"
    DEEMED_APPROVED = "DEEMED_APPROVED"
    DOCUMENTED = "DOCUMENTED"
    EFFECTIVE = "EFFECTIVE"
    WITHDRAWN = "WITHDRAWN"
    RESCINDED = "RESCINDED"


class ConsentDecision(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    GRANTED_WITH_CONDITIONS = "GRANTED_WITH_CONDITIONS"
    DENIED = "DENIED"
    RESCINDED = "RESCINDED"


class DenialReasonCode(str, Enum):
    INSUFFICIENT_CREDIT = "INSUFFICIENT_CREDIT"
    USE_CONFLICT = "USE_CONFLICT"
    INSUFFICIENT_MARKETING = "INSUFFICIENT_MARKETING"
    EXISTING_TENANT_SOLICITATION = "EXISTING_TENANT_SOLICITATION"


class ConditionKind(str, Enum):
    RESTORATION_REQUIRED = "RESTORATION_REQUIRED"
    ADDITIONAL_SECURITY = "ADDITIONAL_SECURITY"
    RENT_RESET_TO_MARKET = "RENT_RESET_TO_MARKET"
    RECAPTURE_RIGHT = "RECAPTURE_RIGHT"


class ConditionStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class CreditOutcome(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


class SubleaseAgreementStatus(str, Enum):
    EXECUTED = "EXECUTED"
    RECOGNIZED = "RECOGNIZED"
    TERMINATED = "TERMINATED"


class RecognitionStatus(str, Enum):
    DRAFTED = "DRAFTED"
    PARTIALLY_SIGNED = "PARTIALLY_SIGNED"
    FULLY_EXECUTED = "FULLY_EXECUTED"
    VOIDED = "VOIDED"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    VOID = "VOID"


class ResponsibleParty(str, Enum):
    TENANT = "TENANT"
    SUBTENANT_OR_ASSIGNEE = "SUBTENANT_OR_ASSIGNEE"
    SHARED = "SHARED"


class RestorationStatus(str, Enum):
    OPEN = "OPEN"
    ESCROW_POSTED = "ESCROW_POSTED"
    COMPLETED = "COMPLETED"
    WAIVED = "WAIVED"


class Signatory(str, Enum):
    LANDLORD = "LANDLORD"
    COUNTERPARTY = "COUNTERPARTY"


# All resources carry the uniform system-managed properties of PRD §2.4
# (id, created_at, updated_at, version).

class Party(TypedDict, total=False):
    id: str
    legal_name: str
    party_kind: str
    credit_rating_bps: int
    created_at: str
    updated_at: str
    version: int


class Building(TypedDict, total=False):
    id: str
    name: str
    total_rentable_sf: int
    loss_factor_bps: int
    created_at: str
    updated_at: str
    version: int


class Lease(TypedDict, total=False):
    id: str
    building_id: str
    tenant_party_id: str
    landlord_party_id: str
    base_rent_per_rsf_annual_cents: int
    leased_rsf: int
    consent_window_business_days: int
    deemed_approval_enabled: bool
    profit_share_tier1_pct_bps: int
    profit_share_tier1_threshold_annual_cents: int
    profit_share_tier2_pct_bps: int
    status: str
    cumulative_profit_share_cents: int
    open_transfer_count: int
    created_at: str
    updated_at: str
    version: int


class DemisedArea(TypedDict, total=False):
    id: str
    lease_id: str
    transfer_request_id: str
    measurement_standard: str
    usable_sf: int
    rentable_sf: int
    prorata_share_bps: int
    is_partial_floor: bool
    supersedes_id: Optional[str]
    superseded_by_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TransferRequest(TypedDict, total=False):
    id: str
    lease_id: str
    counterparty_id: str
    broker_user_id: str
    transfer_type: str
    proposed_rent_per_rsf_annual_cents: int
    term_start: str
    term_end: str
    marketing_period_days: int
    status: str
    submitted_at: Optional[str]
    consent_deadline: Optional[str]
    reminder_sent_at: Optional[str]
    consent_granted_at: Optional[str]
    liability_released: bool
    annual_rent_differential_cents: int
    effective_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConsentReview(TypedDict, total=False):
    id: str
    transfer_request_id: str
    reviewer_landlord_id: Optional[str]
    decision: str
    denial_reason_code: Optional[str]
    release_of_assignor: bool
    conditions_imposed_count: int
    decided_at: Optional[str]
    rescinded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConsentCondition(TypedDict, total=False):
    id: str
    consent_review_id: str
    condition_kind: str
    detail: str
    status: str
    responded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CreditReview(TypedDict, total=False):
    id: str
    transfer_request_id: str
    attesting_broker_user_id: Optional[str]
    reviewed_credit_rating_bps: int
    outcome: str
    minimum_pass_bps: int
    attested_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SubleaseAgreement(TypedDict, total=False):
    id: str
    transfer_request_id: str
    demised_area_id: str
    executed_rent_per_rsf_annual_cents: int
    status: str
    executed_at: str
    created_at: str
    updated_at: str
    version: int


class RecognitionAgreement(TypedDict, total=False):
    id: str
    transfer_request_id: str
    sublease_agreement_id: Optional[str]
    landlord_signed_at: Optional[str]
    counterparty_signed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict, total=False):
    id: str
    lease_id: str
    transfer_request_id: str
    period_start: str
    period_end: str
    subrent_collected_cents: int
    passthrough_rent_cents: int
    net_profit_cents: int
    landlord_share_cents: int
    tenant_share_cents: int
    status: str
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RestorationObligation(TypedDict, total=False):
    id: str
    transfer_request_id: str
    responsible_party: str
    escrow_amount_cents: int
    status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
