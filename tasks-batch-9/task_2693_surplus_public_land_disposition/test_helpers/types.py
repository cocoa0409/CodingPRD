"""Entity shapes, status vocabularies and the role vocabulary of the API.

The TypedDicts mirror the fields each entity exposes. Every entity except
``NegotiationRound`` and ``ProceedsAllocation`` carries the four common system
fields ``id``, ``created_at``, ``updated_at`` and ``version``; those two carry
only ``id`` and ``created_at``, so their shapes below omit the other two.
"""

from enum import Enum
from typing import Any, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    """The eight roles the API recognises in the X-User-Role header."""

    REAL_PROPERTY_OFFICER = "RealPropertyOfficer"
    BOARD_CLERK = "BoardClerk"
    COMPLIANCE_MONITOR = "ComplianceMonitor"
    FINANCE_OFFICER = "FinanceOfficer"
    AGENCY_REPRESENTATIVE = "AgencyRepresentative"
    APPRAISER = "Appraiser"
    BIDDER = "Bidder"
    SYSTEM_ADMINISTRATOR = "SystemAdministrator"


#: Roles whose X-User-ID is an opaque operator identifier.
OPAQUE_ROLES = (
    UserRole.REAL_PROPERTY_OFFICER,
    UserRole.BOARD_CLERK,
    UserRole.COMPLIANCE_MONITOR,
    UserRole.FINANCE_OFFICER,
    UserRole.SYSTEM_ADMINISTRATOR,
)

#: Roles whose X-User-ID must resolve to a stored entity of the matching kind.
ENTITY_BACKED_ROLES = (
    UserRole.AGENCY_REPRESENTATIVE,
    UserRole.APPRAISER,
    UserRole.BIDDER,
)


# ---------------------------------------------------------------------------
# Status vocabularies
# ---------------------------------------------------------------------------


class NoticeRegistryStatus(str, Enum):
    REGISTERED = "REGISTERED"
    LAPSED = "LAPSED"


class AgencyType(str, Enum):
    STATE = "STATE"
    COUNTY = "COUNTY"
    MUNICIPAL = "MUNICIPAL"
    SCHOOL_DISTRICT = "SCHOOL_DISTRICT"
    TRANSIT = "TRANSIT"
    HOUSING_AUTHORITY = "HOUSING_AUTHORITY"
    FEDERAL = "FEDERAL"


class PreferenceCategory(str, Enum):
    AFFORDABLE_HOUSING = "AFFORDABLE_HOUSING"
    PARK_OPEN_SPACE = "PARK_OPEN_SPACE"
    SCHOOL_SITE = "SCHOOL_SITE"
    INFILL_INFRASTRUCTURE = "INFILL_INFRASTRUCTURE"
    NONE = "NONE"


class OwnershipStatus(str, Enum):
    AGENCY_OWNED = "AGENCY_OWNED"
    CONVEYED = "CONVEYED"
    REVERTED_TO_AGENCY = "REVERTED_TO_AGENCY"


class ValuationStatus(str, Enum):
    UNVALUED = "UNVALUED"
    CURRENT = "CURRENT"
    STALE = "STALE"


class TitleItemType(str, Enum):
    LIEN = "LIEN"
    ENCROACHMENT = "ENCROACHMENT"
    MISSING_ACCESS_EASEMENT = "MISSING_ACCESS_EASEMENT"
    BOUNDARY_GAP = "BOUNDARY_GAP"
    UNRECORDED_LEASE = "UNRECORDED_LEASE"


class TitleItemStatus(str, Enum):
    OPEN = "OPEN"
    CURED = "CURED"
    WAIVED_WITH_ENDORSEMENT = "WAIVED_WITH_ENDORSEMENT"
    RESERVED_AS_EASEMENT = "RESERVED_AS_EASEMENT"


class AppraisalMethod(str, Enum):
    SALES_COMPARISON = "SALES_COMPARISON"
    INCOME = "INCOME"
    COST = "COST"


class AppraisalStatus(str, Enum):
    ORDERED = "ORDERED"
    REPORTED = "REPORTED"
    CHALLENGED = "CHALLENGED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class ChallengeStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SUSTAINED = "SUSTAINED"
    DENIED = "DENIED"


class DeclarationStatus(str, Enum):
    DRAFT = "DRAFT"
    ADOPTED = "ADOPTED"
    NOTICED = "NOTICED"
    PREFERENCE_CLOSED = "PREFERENCE_CLOSED"
    NEGOTIATION_AGREED = "NEGOTIATION_AGREED"
    OFFERING_AUTHORIZED = "OFFERING_AUTHORIZED"
    CONVEYED = "CONVEYED"
    UNSUCCESSFUL = "UNSUCCESSFUL"
    WITHDRAWN = "WITHDRAWN"


class NoticeStatus(str, Enum):
    ISSUED = "ISSUED"
    DECLINED = "DECLINED"
    INTEREST_EXPRESSED = "INTEREST_EXPRESSED"
    EXPIRED = "EXPIRED"


class NoticeResponseType(str, Enum):
    DECLINE = "DECLINE"
    EXPRESS_INTEREST = "EXPRESS_INTEREST"


class NegotiationStatus(str, Enum):
    OPEN = "OPEN"
    IN_NEGOTIATION = "IN_NEGOTIATION"
    AGREED = "AGREED"
    IMPASSE = "IMPASSE"
    LAPSED = "LAPSED"


class GoodFaithStatus(str, Enum):
    UNREVIEWED = "UNREVIEWED"
    UNDER_REVIEW = "UNDER_REVIEW"
    SATISFIED = "SATISFIED"
    DEFICIENT = "DEFICIENT"


class NegotiationParty(str, Enum):
    CUSTODIAN_AGENCY = "CUSTODIAN_AGENCY"
    PREFERENCE_ENTITY = "PREFERENCE_ENTITY"


class EnvDeterminationClass(str, Enum):
    EXEMPT = "EXEMPT"
    NEGATIVE_DECLARATION = "NEGATIVE_DECLARATION"
    MITIGATED_NEG_DEC = "MITIGATED_NEG_DEC"
    FULL_EIR = "FULL_EIR"


class EnvReviewStatus(str, Enum):
    CIRCULATING = "CIRCULATING"
    RECIRCULATION_REQUIRED = "RECIRCULATION_REQUIRED"
    CERTIFIED = "CERTIFIED"


class DispositionType(str, Enum):
    COMPETITIVE_SALE = "COMPETITIVE_SALE"
    NEGOTIATED_SALE = "NEGOTIATED_SALE"
    EXCHANGE = "EXCHANGE"


class OfferingStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    EVALUATION = "EVALUATION"
    AWARDED = "AWARDED"
    FAILED_NO_QUALIFYING_BID = "FAILED_NO_QUALIFYING_BID"
    CANCELLED = "CANCELLED"
    CLOSED_CONVEYED = "CLOSED_CONVEYED"


class MinimumPriceVariant(str, Enum):
    MARKET_FLOOR = "MARKET_FLOOR"
    AFFORDABLE_HOUSING_PREFERENCE = "AFFORDABLE_HOUSING_PREFERENCE"


class BidderEntityType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    CORPORATION = "CORPORATION"
    NONPROFIT = "NONPROFIT"
    PARTNERSHIP = "PARTNERSHIP"


class DebarmentStatus(str, Enum):
    CLEAR = "CLEAR"
    DEBARRED = "DEBARRED"


class BidQualificationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    QUALIFIED = "QUALIFIED"
    DISQUALIFIED = "DISQUALIFIED"
    WINNING = "WINNING"
    BACKUP = "BACKUP"
    WITHDRAWN = "WITHDRAWN"


class BidDepositStatus(str, Enum):
    HELD = "HELD"
    RELEASED = "RELEASED"
    APPLIED = "APPLIED"


class RecordingStatus(str, Enum):
    PENDING_TITLE = "PENDING_TITLE"
    READY_TO_RECORD = "READY_TO_RECORD"
    RECORDED = "RECORDED"
    RESCINDED = "RESCINDED"


class ComplianceStatus(str, Enum):
    NOT_MONITORED = "NOT_MONITORED"
    COMPLIANT = "COMPLIANT"
    VIOLATION_NOTICED = "VIOLATION_NOTICED"
    CURED = "CURED"
    REVERTED = "REVERTED"


class GranteeKind(str, Enum):
    BIDDER = "BIDDER"
    AGENCY = "AGENCY"


class AllocationBasis(str, Enum):
    FIXED_RESERVE = "FIXED_RESERVE"
    PERCENTAGE = "PERCENTAGE"
    CHALLENGE_FORFEITURE = "CHALLENGE_FORFEITURE"


class AllocationStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


# ---------------------------------------------------------------------------
# Entity shapes
# ---------------------------------------------------------------------------


class CommonSystemFields(TypedDict, total=False):
    """The four system fields carried by every entity that is versioned."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Agency(CommonSystemFields, total=False):
    name: str
    agency_type: str
    contact_email: str
    is_preference_entity: bool
    preference_category: str
    notice_registry_status: str


class Parcel(CommonSystemFields, total=False):
    apn: str
    address: str
    acreage: float
    zoning_code: str
    book_value_cents: int
    custodian_agency_id: str
    ownership_status: str
    valuation_status: str
    open_title_item_count: int
    disposition_ready: bool


class TitleCurativeItem(CommonSystemFields, total=False):
    parcel_id: str
    item_type: str
    description: str
    cure_cost_estimate_cents: int
    status: str
    actual_cure_cost_cents: Optional[int]
    easement_purpose: Optional[str]
    easement_area_sqft: Optional[float]
    resolved_at: Optional[str]


class Appraiser(CommonSystemFields, total=False):
    name: str
    license_number: str
    license_expires_on: str
    license_status: str
    active_engagement_count: int


class Appraisal(CommonSystemFields, total=False):
    parcel_id: str
    appraiser_id: str
    method: str
    engagement_start_on: str
    engagement_end_on: str
    status: str
    appraised_value_cents: Optional[int]
    effective_date: Optional[str]
    narrative: Optional[str]
    reported_at: Optional[str]
    expires_on: Optional[str]
    accepted_at: Optional[str]
    revaluation_required: bool
    challenge_count: int


class AppraisalChallenge(CommonSystemFields, total=False):
    appraisal_id: str
    challenger_agency_id: str
    asserted_value_cents: int
    grounds: str
    status: str
    required_deposit_cents: int
    deposit_paid_cents: int
    deposit_refunded_cents: int
    deposit_forfeited_cents: int
    revised_value_cents: Optional[int]
    determined_by_user_id: Optional[str]


class SurplusDeclaration(CommonSystemFields, total=False):
    parcel_id: str
    justification: str
    intended_use_restriction: Optional[str]
    status: str
    resolution_number: Optional[str]
    adopted_by_user_id: Optional[str]
    adopted_at: Optional[str]
    notice_issued_at: Optional[str]
    notice_response_window_days: Optional[int]
    notice_response_deadline_at: Optional[str]
    authorized_disposition_type: Optional[str]
    authority_findings: Optional[str]
    reoffer_count: int
    reoffer_eligible_at: Optional[str]
    withdrawn_reason: Optional[str]
    preference_offer_count: int
    unresolved_preference_count: int


class StatutoryNotice(CommonSystemFields, total=False):
    declaration_id: str
    recipient_agency_id: str
    notice_round: int
    status: str
    issued_at: str
    response_window_days: int
    response_deadline_at: str
    responded_at: Optional[str]
    response_type: Optional[str]


class PreferenceOffer(CommonSystemFields, total=False):
    declaration_id: str
    notice_id: str
    offeror_agency_id: str
    preference_category: str
    negotiation_status: str
    good_faith_status: str
    negotiation_opened_at: str
    negotiation_deadline_at: str
    ah_minimum_price_cents: int
    agreed_price_cents: Optional[int]
    officer_round_count: int
    entity_round_count: int
    timely_response_count: int
    interim_good_faith_score: Optional[int]
    final_good_faith_score: Optional[int]
    remediation_note: Optional[str]


class NegotiationRound(TypedDict, total=False):
    """Append-only round log entry; carries only id and created_at as system fields."""

    id: str
    created_at: str
    offer_id: str
    round_number: int
    party: str
    price_offered_cents: int
    terms_summary: str
    responded_to_round_number: Optional[int]
    responded_within_days: Optional[int]
    is_timely: bool


class EnvironmentalReview(CommonSystemFields, total=False):
    declaration_id: str
    determination_class: str
    circulation_start_on: Optional[str]
    circulation_end_on: Optional[str]
    circulation_round: int
    status: str
    certified_at: Optional[str]
    recirculation_reason: Optional[str]


class DispositionOffering(CommonSystemFields, total=False):
    declaration_id: str
    offering_type: str
    bid_open_at: str
    bid_close_at: str
    status: str
    minimum_price_cents: int
    minimum_price_variant: str
    required_deposit_cents: int
    qualified_bid_count: int
    winning_bid_amount_cents: Optional[int]
    awarded_by_user_id: Optional[str]
    awarded_at: Optional[str]
    rescind_count: int
    counterparty_bidder_id: Optional[str]
    counterparty_agency_id: Optional[str]
    cancellation_reason: Optional[str]


class Bidder(CommonSystemFields, total=False):
    legal_name: str
    entity_type: str
    contact_email: str
    debarment_status: str
    debarment_reason: Optional[str]
    available_funds_cents: int
    escrow_held_cents: int
    lifetime_deposits_cents: int


class Bid(CommonSystemFields, total=False):
    offering_id: str
    bidder_id: str
    amount_cents: int
    deposit_amount_cents: int
    intended_use: Optional[str]
    qualification_status: str
    deposit_status: str
    submitted_at: str
    award_rank: Optional[int]
    disqualification_reason: Optional[str]


class Conveyance(CommonSystemFields, total=False):
    offering_id: str
    parcel_id: str
    grantee_kind: str
    grantee_bidder_id: Optional[str]
    grantee_agency_id: Optional[str]
    sale_price_cents: int
    closing_costs_cents: int
    broker_fee_cents: int
    deed_restrictions: list
    reverter_condition: str
    reverter_cure_period_days: int
    recording_status: str
    compliance_status: str
    recoverable_curative_cost_cents: int
    net_proceeds_cents: int
    allocated_proceeds_cents: int
    recorded_instrument_number: Optional[str]
    recorded_at: Optional[str]
    violation_description: Optional[str]
    violation_noticed_at: Optional[str]
    cure_deadline_at: Optional[str]
    cure_note: Optional[str]
    reverted_at: Optional[str]


class Fund(CommonSystemFields, total=False):
    name: str
    fund_code: str
    priority_rank: int
    allocation_pct: float
    fixed_reserve_cents: int
    balance_cents: int
    lifetime_credits_cents: int
    lifetime_debits_cents: int


class ProceedsAllocation(TypedDict, total=False):
    """Allocation ledger row; carries only id and created_at as system fields."""

    id: str
    created_at: str
    conveyance_id: Optional[str]
    fund_id: str
    amount_cents: int
    allocation_basis: str
    residual_included_cents: int
    status: str
    reversed_at: Optional[str]


#: Convenience alias for a decoded envelope payload of unknown entity kind.
EntityPayload = dict[str, Any]
