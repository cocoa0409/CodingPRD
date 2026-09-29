"""Domain types for the resort-fee disclosure compliance API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import Dict, List, Optional, TypedDict


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    REVENUE_MANAGER = "RevenueManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    REGULATORY_LIAISON = "RegulatoryLiaison"
    CHANNEL_OPERATOR = "ChannelOperator"
    GUEST_SERVICES_AGENT = "GuestServicesAgent"
    GUEST = "Guest"


class Taxability(str, Enum):
    TAXABLE = "TAXABLE"
    EXEMPT = "EXEMPT"
    TAXABLE_IF_MANDATORY = "TAXABLE_IF_MANDATORY"


class PropertyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class DisclosurePosture(str, Enum):
    COMPLIANT = "COMPLIANT"
    AT_RISK = "AT_RISK"
    NON_COMPLIANT = "NON_COMPLIANT"


class ChannelType(str, Enum):
    OWNED_WEB = "OWNED_WEB"
    OWNED_APP = "OWNED_APP"
    OTA = "OTA"
    GDS = "GDS"
    METASEARCH = "METASEARCH"
    VOICE = "VOICE"


class FeeProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class FeeClassification(str, Enum):
    MANDATORY = "MANDATORY"
    OPTIONAL = "OPTIONAL"
    CONDITIONAL = "CONDITIONAL"


class FeeBasis(str, Enum):
    PER_NIGHT = "PER_NIGHT"
    PER_STAY = "PER_STAY"
    PER_PERSON_PER_NIGHT = "PER_PERSON_PER_NIGHT"
    PERCENT_OF_ROOM = "PERCENT_OF_ROOM"


class DisclosurePlacement(str, Enum):
    FIRST_QUOTE = "FIRST_QUOTE"
    RATE_DETAILS = "RATE_DETAILS"
    CHECKOUT = "CHECKOUT"
    CONFIRMATION_ONLY = "CONFIRMATION_ONLY"
    ABSENT = "ABSENT"


class ProfileStatus(str, Enum):
    DRAFT = "DRAFT"
    DEPLOYED = "DEPLOYED"
    FLAGGED = "FLAGGED"
    REMEDIATED = "REMEDIATED"
    RETIRED = "RETIRED"


class StayStatus(str, Enum):
    QUOTED = "QUOTED"
    CONFIRMED = "CONFIRMED"
    IN_HOUSE = "IN_HOUSE"
    CHECKED_OUT = "CHECKED_OUT"


class DisclosureStatus(str, Enum):
    PENDING_AUDIT = "PENDING_AUDIT"
    DISCLOSED = "DISCLOSED"
    DISPUTED = "DISPUTED"
    UNDISCLOSED_CONFIRMED = "UNDISCLOSED_CONFIRMED"
    CURED = "CURED"


class FolioStatus(str, Enum):
    OPEN = "OPEN"
    ITEMIZED = "ITEMIZED"
    POSTED = "POSTED"
    ADJUSTED = "ADJUSTED"
    CLOSED = "CLOSED"


class FolioLineType(str, Enum):
    ROOM = "ROOM"
    MANDATORY_FEE = "MANDATORY_FEE"
    OPTIONAL_FEE = "OPTIONAL_FEE"
    FEE_CREDIT = "FEE_CREDIT"
    FEE_REBILL = "FEE_REBILL"
    COMPLAINT_REFUND = "COMPLAINT_REFUND"


class TaxabilityDetermination(str, Enum):
    TAXABLE = "TAXABLE"
    EXEMPT = "EXEMPT"
    TAXABLE_IF_MANDATORY_APPLIED = "TAXABLE_IF_MANDATORY_APPLIED"
    TAXABLE_IF_MANDATORY_WAIVED = "TAXABLE_IF_MANDATORY_WAIVED"


class OptOutStatus(str, Enum):
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class DenialReasonCode(str, Enum):
    NOT_AVOIDABLE = "NOT_AVOIDABLE"
    SERVICE_ALREADY_CONSUMED = "SERVICE_ALREADY_CONSUMED"
    POLICY_EXCEPTION_DENIED = "POLICY_EXCEPTION_DENIED"


class ComplaintReason(str, Enum):
    NOT_DISCLOSED = "NOT_DISCLOSED"
    MISSTATED_AMOUNT = "MISSTATED_AMOUNT"
    MANDATORY_NOT_AVOIDABLE = "MANDATORY_NOT_AVOIDABLE"
    TOTAL_NOT_SHOWN = "TOTAL_NOT_SHOWN"


class ComplaintStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    SUBSTANTIATED = "SUBSTANTIATED"
    UNSUBSTANTIATED = "UNSUBSTANTIATED"
    REFUNDED = "REFUNDED"


class RefundVariant(str, Enum):
    FULL_FEE_REFUND = "FULL_FEE_REFUND"
    DISCLOSURE_GAP_DIFFERENTIAL = "DISCLOSURE_GAP_DIFFERENTIAL"


class DismissalReasonCode(str, Enum):
    DISCLOSURE_EVIDENCED = "DISCLOSURE_EVIDENCED"
    GUEST_ACKNOWLEDGED_AT_CHECK_IN = "GUEST_ACKNOWLEDGED_AT_CHECK_IN"
    DUPLICATE_COMPLAINT = "DUPLICATE_COMPLAINT"


class InquiryStatus(str, Enum):
    RECEIVED = "RECEIVED"
    RESPONSE_DRAFTED = "RESPONSE_DRAFTED"
    RESPONSE_SUBMITTED = "RESPONSE_SUBMITTED"
    REMEDIATION_REQUIRED = "REMEDIATION_REQUIRED"
    REMEDIATION_SUBMITTED = "REMEDIATION_SUBMITTED"
    ACCEPTED = "ACCEPTED"
    WITHDRAWN = "WITHDRAWN"


class RollInScenario(str, Enum):
    STATUS_QUO = "STATUS_QUO"
    PARTIAL_ROLL_IN = "PARTIAL_ROLL_IN"
    FULL_ROLL_IN = "FULL_ROLL_IN"


class RollInVariant(str, Enum):
    RATE_PARITY = "RATE_PARITY"
    TAX_ABSORBED = "TAX_ABSORBED"


# --------------------------------------------------------------------------
# Entity TypedDicts
#
# Thirteen entities carry the full id / created_at / updated_at / version
# quartet. FolioLine and RevenueImpactModel carry only id and created_at.
# --------------------------------------------------------------------------
class Jurisdiction(TypedDict):
    id: str
    code: str
    name: str
    occupancy_tax_rate_bps: int
    first_quote_total_required: bool
    itemization_required_on_folio: bool
    mandatory_fee_ban: bool
    opt_out_mandate: bool
    created_at: str
    updated_at: str
    version: int


class TaxabilityRule(TypedDict):
    id: str
    jurisdiction_id: str
    fee_code: str
    taxability: str
    tax_rate_bps: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict):
    id: str
    jurisdiction_id: str
    name: str
    brand_code: str
    base_room_rate_cents: int
    status: str
    min_channel_disclosure_score: Optional[int]
    disclosure_posture: str
    open_disclosure_obligation_count: int
    published_fee_program_count: int
    aggregate_disclosure_gap_cents: int
    created_at: str
    updated_at: str
    version: int


class DisclosureSummary(TypedDict):
    property_id: str
    disclosure_posture: str
    min_channel_disclosure_score: Optional[int]
    open_disclosure_obligation_count: int
    deployed_profile_count: int
    flagged_profile_count: int
    published_fee_program_count: int
    total_mandatory_fee_cents_per_night: int
    aggregate_disclosure_gap_cents: int


class Channel(TypedDict):
    id: str
    name: str
    channel_type: str
    supports_total_price_display: bool
    supports_itemization: bool
    created_at: str
    updated_at: str
    version: int


class FeeProgram(TypedDict):
    id: str
    property_id: str
    supersedes_program_id: Optional[str]
    version_label: str
    effective_from: str
    effective_to: str
    status: str
    authored_by_user_id: str
    attested_by_user_id: Optional[str]
    attestation_note: Optional[str]
    published_at: Optional[str]
    fee_count: int
    mandatory_fee_count: int
    total_mandatory_fee_cents_per_night: int
    inclusion_coverage_ratio: float
    created_at: str
    updated_at: str
    version: int


class Fee(TypedDict):
    id: str
    fee_program_id: str
    code: str
    label: str
    classification: str
    basis: str
    amount_cents: Optional[int]
    percent_bps: Optional[int]
    avoidable: bool
    opt_out_window_hours: Optional[int]
    disclosure_text: str
    inclusion_count: int
    inclusion_value_cents: int
    created_at: str
    updated_at: str
    version: int


class FeeInclusion(TypedDict):
    id: str
    fee_id: str
    service_code: str
    service_label: str
    retail_value_cents: int
    units: int
    included_value_cents: int
    created_at: str
    updated_at: str
    version: int


class ChannelDisclosureProfile(TypedDict):
    id: str
    property_id: str
    channel_id: str
    fee_program_id: str
    first_quote_shows_total: bool
    itemized_at_first_quote: bool
    disclosure_placement: str
    deployed_from: str
    deployed_to: str
    status: str
    disclosure_score: int
    confirmed_undisclosed_count: int
    remediation_round: int
    last_audited_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    property_id: str
    channel_id: str
    channel_disclosure_profile_id: str
    fee_program_id: str
    arrival_date: str
    nights: int
    guests: int
    room_rate_cents: int
    disclosed_fee_amounts: Dict[str, int]
    quoted_room_total_cents: int
    quoted_mandatory_fee_cents: int
    quoted_tax_cents: int
    quoted_total_cents: int
    quote_disclosure_gap_cents: int
    folio_fee_total_cents: int
    folio_total_cents: int
    quote_folio_variance_cents: int
    guest_out_of_pocket_cents: int
    stay_status: str
    disclosure_status: str
    created_at: str
    updated_at: str
    version: int


class Folio(TypedDict):
    id: str
    booking_id: str
    status: str
    line_count: int
    charges_subtotal_cents: int
    credits_total_cents: int
    tax_total_cents: int
    folio_total_cents: int
    itemization_complete: bool
    posted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FolioLine(TypedDict):
    """Append-only ledger entry: carries only id and created_at."""
    id: str
    folio_id: str
    fee_id: Optional[str]
    jurisdiction_id: str
    line_type: str
    fee_code: Optional[str]
    description: str
    amount_cents: int
    taxability_determination: str
    tax_rate_bps: int
    tax_cents: int
    sequence_no: int
    created_at: str


class OptOutRequest(TypedDict):
    id: str
    booking_id: str
    fee_id: str
    status: str
    requested_hours_before_arrival: int
    credit_cents: int
    tax_credit_cents: int
    credit_line_sequence_no: Optional[int]
    denial_reason_code: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GuestComplaint(TypedDict):
    id: str
    booking_id: str
    folio_line_id: str
    complaint_reason: str
    narrative: str
    status: str
    refund_variant: Optional[str]
    disputed_amount_cents: int
    disclosed_amount_cents: int
    refund_entitlement_cents: int
    refunded_amount_cents: int
    dismissal_reason_code: Optional[str]
    investigated_by_user_id: Optional[str]
    adjudicated_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RegulatorInquiry(TypedDict):
    id: str
    jurisdiction_id: str
    property_id: str
    docket_number: str
    channel_scope: List[str]
    response_due_at: str
    status: str
    response_summary: Optional[str]
    remediation_directive: Optional[str]
    remediation_summary: Optional[str]
    rejection_reason: Optional[str]
    withdrawal_reason: Optional[str]
    drafted_by_user_id: Optional[str]
    submitted_by_user_id: Optional[str]
    flagged_profile_ids: List[str]
    remediation_round: int
    exposure_cents: int
    created_at: str
    updated_at: str
    version: int


class RevenueImpactModel(TypedDict):
    """Immutable model snapshot: carries only id and created_at."""
    id: str
    property_id: str
    fee_program_id: str
    scenario: str
    variant: str
    roll_in_fee_codes: List[str]
    baseline_adr_cents: int
    baseline_commission_cents: int
    baseline_tax_cents: int
    baseline_guest_total_cents: int
    baseline_net_revenue_cents: int
    modeled_adr_cents: int
    applied_commission_bps: int
    modeled_commission_cents: int
    modeled_tax_cents: int
    modeled_guest_total_cents: int
    modeled_net_revenue_cents: int
    modeled_adr_delta_cents: int
    modeled_commission_delta_cents: int
    modeled_tax_delta_cents: int
    modeled_guest_total_delta_cents: int
    modeled_net_revenue_delta_cents: int
    created_at: str


FULL_AUDIT_ENTITIES = (
    "Jurisdiction", "TaxabilityRule", "Property", "Channel", "FeeProgram",
    "Fee", "FeeInclusion", "ChannelDisclosureProfile", "Booking", "Folio",
    "OptOutRequest", "GuestComplaint", "RegulatorInquiry",
)
APPEND_ONLY_ENTITIES = ("FolioLine", "RevenueImpactModel")
