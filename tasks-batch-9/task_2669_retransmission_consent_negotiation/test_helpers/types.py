"""Domain types for the Retransmission Consent Negotiation API.

Status enumerations, role enumeration and entity shapes as declared by the PRD.
"""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    CARRIAGE_ADMIN = "CarriageAdmin"
    STATION_GROUP_NEGOTIATOR = "StationGroupNegotiator"
    GROUP_COUNSEL = "GroupCounsel"
    DISTRIBUTOR_REP = "DistributorRep"
    NETWORK_REPRESENTATIVE = "NetworkRepresentative"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


class NetworkAffiliation(str, Enum):
    ABC = "ABC"
    CBS = "CBS"
    NBC = "NBC"
    FOX = "FOX"
    CW = "CW"
    INDEPENDENT = "INDEPENDENT"


class AffiliationAgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class DistributorType(str, Enum):
    CABLE = "CABLE"
    DBS = "DBS"
    TELCO = "TELCO"
    VMVPD = "VMVPD"


class SubscriberMeasurementMethod(str, Enum):
    BILLED_HOUSEHOLDS = "BILLED_HOUSEHOLDS"
    WEIGHTED_STREAMING_DEVICES = "WEIGHTED_STREAMING_DEVICES"
    AVERAGE_MONTHLY_UNIQUE = "AVERAGE_MONTHLY_UNIQUE"


class Tier(str, Enum):
    BROADCAST_BASIC = "BROADCAST_BASIC"
    EXPANDED_BASIC = "EXPANDED_BASIC"
    DIGITAL_TIER = "DIGITAL_TIER"


class ElectionType(str, Enum):
    MUST_CARRY = "MUST_CARRY"
    RETRANS_CONSENT = "RETRANS_CONSENT"


class CarriageElectionStatus(str, Enum):
    DRAFT = "DRAFT"
    NEGOTIATING = "NEGOTIATING"
    ELECTION_EFFECTIVE = "ELECTION_EFFECTIVE"
    CONSENT_GRANTED = "CONSENT_GRANTED"
    ELECTION_LAPSED = "ELECTION_LAPSED"


class NegotiationStatus(str, Enum):
    OPEN = "OPEN"
    AWAITING_DISTRIBUTOR_RESPONSE = "AWAITING_DISTRIBUTOR_RESPONSE"
    AWAITING_STATION_OFFER = "AWAITING_STATION_OFFER"
    IMPASSE = "IMPASSE"
    CONSENTED = "CONSENTED"
    CANCELLED = "CANCELLED"


class NoticeComplianceStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    NOTICE_PENDING = "NOTICE_PENDING"
    NOTICE_SERVED = "NOTICE_SERVED"
    NOTICE_DEFICIENT = "NOTICE_DEFICIENT"


class OfferedBy(str, Enum):
    STATION_GROUP = "STATION_GROUP"
    DISTRIBUTOR = "DISTRIBUTOR"


class OfferStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class GoodFaithEventType(str, Enum):
    MEETING_HELD = "MEETING_HELD"
    PROPOSAL_EXCHANGED = "PROPOSAL_EXCHANGED"
    INFORMATION_REQUEST = "INFORMATION_REQUEST"
    INFORMATION_RESPONSE = "INFORMATION_RESPONSE"
    DELAY_OBJECTION = "DELAY_OBJECTION"


class SubscriberReportStatus(str, Enum):
    REPORTED = "REPORTED"
    UNDER_AUDIT = "UNDER_AUDIT"
    ADJUSTED = "ADJUSTED"
    ACCEPTED = "ACCEPTED"


class AuditFindingStatus(str, Enum):
    OPEN = "OPEN"
    SUBSTANTIATED = "SUBSTANTIATED"
    DISMISSED = "DISMISSED"


class ExecutionStatus(str, Enum):
    PENDING_EXECUTION = "PENDING_EXECUTION"
    EXECUTED = "EXECUTED"
    EXPIRED = "EXPIRED"


class NetworkApprovalStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING_NETWORK = "PENDING_NETWORK"
    NETWORK_APPROVED = "NETWORK_APPROVED"
    NETWORK_REJECTED = "NETWORK_REJECTED"


class InterimExtensionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    SUPERSEDED = "SUPERSEDED"


class ExtensionRateBasis(str, Enum):
    PRIOR_RATE = "PRIOR_RATE"
    LAST_STATION_OFFER = "LAST_STATION_OFFER"
    MIDPOINT = "MIDPOINT"


class DisputedTerm(str, Enum):
    DIGITAL = "DIGITAL"
    OUT_OF_HOME = "OUT_OF_HOME"
    STREAMING = "STREAMING"


class RightsDisputeStatus(str, Enum):
    RAISED = "RAISED"
    IN_MEDIATION = "IN_MEDIATION"
    RESOLVED_INCLUDED = "RESOLVED_INCLUDED"
    RESOLVED_EXCLUDED = "RESOLVED_EXCLUDED"


class NoticeChannel(str, Enum):
    ON_AIR_CRAWL = "ON_AIR_CRAWL"
    BILL_INSERT = "BILL_INSERT"
    EMAIL = "EMAIL"
    WEBSITE = "WEBSITE"


class BlackoutNoticeStatus(str, Enum):
    SERVED = "SERVED"
    SUPERSEDED = "SUPERSEDED"


class FeeSettlementStatus(str, Enum):
    ISSUED = "ISSUED"
    TRUED_UP = "TRUED_UP"
    VOIDED = "VOIDED"


class BasisVariant(str, Enum):
    AS_REPORTED = "AS_REPORTED"
    AUDITED = "AUDITED"


class Station(TypedDict):
    id: str
    call_sign: str
    market_code: str
    dma_rank: int
    market_tv_households: int
    network_affiliation: str
    filed_election_count: int
    created_at: str
    updated_at: str
    version: int


class AffiliationAgreement(TypedDict):
    id: str
    station_id: str
    network_name: str
    term_end_utc: str
    reverse_comp_floor_per_sub_cents: int
    split_premium_bp: int
    digital_rights_grantable: bool
    ooh_rights_grantable: bool
    streaming_rights_grantable: bool
    permitted_tiers: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Distributor(TypedDict):
    id: str
    name: str
    distributor_type: str
    subscriber_measurement_method: str
    video_household_count: int
    required_blackout_notice_days: int
    open_true_up_count: int
    created_at: str
    updated_at: str
    version: int


class CarriageElection(TypedDict):
    id: str
    station_id: str
    distributor_id: str
    cycle_label: str
    election_type: str
    requested_tier: str
    incumbent_expiry_utc: str
    incumbent_rate_per_sub_cents: int
    status: str
    filed_at_utc: Optional[str]
    withdrawal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Negotiation(TypedDict):
    id: str
    election_id: str
    status: str
    round_number: int
    station_offer_count: int
    distributor_offer_count: int
    good_faith_meeting_count: int
    impasse_declared_at_utc: Optional[str]
    blackout_notice_deadline_utc: Optional[str]
    notice_compliance_status: str
    created_at: str
    updated_at: str
    version: int


class Offer(TypedDict):
    id: str
    negotiation_id: str
    offered_by: str
    round_number: int
    base_rate_per_sub_cents: int
    escalator_bp_per_year: int
    term_months: int
    tier: str
    penetration_commitment_bp: int
    includes_digital_rights: bool
    includes_ooh_rights: bool
    includes_streaming_rights: bool
    subscriber_report_id: str
    projection_basis_subscribers: int
    year_rate_schedule_compound_cents: List[int]
    projected_total_fee_cents: int
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GoodFaithLog(TypedDict):
    """Append-only conduct record: carries only id and created_at."""

    id: str
    negotiation_id: str
    event_type: str
    occurred_at_utc: str
    summary: str
    actor_role: str
    sequence_index: int
    created_at: str


class SubscriberReport(TypedDict):
    id: str
    station_id: str
    distributor_id: str
    period_label: str
    period_start_utc: str
    period_end_utc: str
    reported_subscriber_count: int
    excluded_free_trial_count: int
    measurement_method_snapshot: str
    audit_adjustment_subscribers: int
    adjusted_subscriber_count: int
    billable_subscriber_basis: int
    as_reported_basis: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditFinding(TypedDict):
    id: str
    subscriber_report_id: str
    adjustment_subscribers: int
    basis_note: str
    status: str
    resolution_note: Optional[str]
    opened_at_utc: str
    created_at: str
    updated_at: str
    version: int


class CarriageAgreement(TypedDict):
    id: str
    negotiation_id: str
    accepted_offer_id: str
    effective_start_utc: str
    effective_end_utc: str
    execution_status: str
    network_approval_status: str
    accepted_by_user_id: str
    executed_by_user_id: Optional[str]
    granted_rights_scope: List[str]
    rights_credit_bp_total: int
    contract_year_rate_schedule_cents: List[int]
    current_year_rate_per_sub_cents: int
    consumed_extension_days: int
    lifetime_gross_fee_cents: int
    lifetime_net_retained_cents: int
    created_at: str
    updated_at: str
    version: int


class InterimExtension(TypedDict):
    id: str
    agreement_id: str
    extension_days: int
    extension_start_utc: str
    extension_end_utc: str
    extension_rate_basis: str
    effective_rate_per_sub_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RightsDispute(TypedDict):
    id: str
    agreement_id: str
    disputed_term: str
    claimed_definition: str
    raised_by: str
    status: str
    credit_bp_applied: int
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BlackoutNotice(TypedDict):
    id: str
    negotiation_id: str
    subscriber_notice_count: int
    notice_channel: str
    served_at_utc: str
    required_notice_days_snapshot: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FeeSettlement(TypedDict):
    id: str
    agreement_id: str
    subscriber_report_id: str
    period_label: str
    period_start_utc: str
    period_end_utc: str
    contract_year_index: int
    rate_per_sub_cents: int
    basis_variant: str
    billable_subscriber_basis_snapshot: int
    gross_fee_cents: int
    rights_credit_cents: int
    reverse_comp_split_bp: int
    reverse_comp_cents: int
    actual_penetration_bp: int
    penetration_shortfall_bp: int
    penetration_penalty_cents: int
    net_retained_cents: int
    true_up_required: bool
    issued_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int
