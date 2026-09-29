"""Domain types for the Cruise Shore Excursions API.

Entity shapes, lifecycle enums and the role vocabulary, all taken from the PRD.

Resources that carry the mutation apparatus expose ``id``, ``created_at``,
``updated_at`` and ``version``.  The two append-only record types
(``SafetyAudit`` and ``RefundLedgerEntry``) expose only ``id`` and
``created_at``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------

class UserRole(str, Enum):
    GUEST = "Guest"
    SHORE_EXCURSION_DESK = "ShoreExcursionDesk"
    EXCURSION_MANAGER = "ExcursionManager"
    OPERATOR_VETTING_OFFICER = "OperatorVettingOfficer"
    PORT_AGENT = "PortAgent"
    RISK_OFFICER = "RiskOfficer"
    FINANCE_CONTROLLER = "FinanceController"


ALL_ROLES: List[str] = [r.value for r in UserRole]


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------

class DockingMode(str, Enum):
    ALONGSIDE = "ALONGSIDE"
    TENDER = "TENDER"


class MeetingPointZone(str, Enum):
    PIER_APRON = "PIER_APRON"
    TENDER_PONTOON = "TENDER_PONTOON"
    TERMINAL_HALL = "TERMINAL_HALL"


class PortCallStatus(str, Enum):
    PLANNED = "PLANNED"
    OPEN_FOR_SALE = "OPEN_FOR_SALE"
    IN_PORT = "IN_PORT"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class PortCallAction(str, Enum):
    OPEN_SALES = "OPEN_SALES"
    ARRIVE = "ARRIVE"
    CLOSE_ALL_ABOARD = "CLOSE_ALL_ABOARD"
    CANCEL = "CANCEL"


class TenderWavePriorityClass(str, Enum):
    EXCURSION_PRIORITY = "EXCURSION_PRIORITY"
    GENERAL = "GENERAL"


class VettingStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class VettingAction(str, Enum):
    SUBMIT = "SUBMIT"
    REQUEST_INFO = "REQUEST_INFO"
    RESUBMIT = "RESUBMIT"
    APPROVE = "APPROVE"
    SUSPEND = "SUSPEND"
    REINSTATE = "REINSTATE"
    TERMINATE = "TERMINATE"


class AuditType(str, Enum):
    INITIAL = "INITIAL"
    ANNUAL = "ANNUAL"
    INCIDENT_TRIGGERED = "INCIDENT_TRIGGERED"


class CatalogStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    PUBLISHED = "PUBLISHED"
    WITHDRAWN = "WITHDRAWN"
    ARCHIVED = "ARCHIVED"


class CatalogAction(str, Enum):
    SUBMIT_REVIEW = "SUBMIT_REVIEW"
    RETURN_TO_DRAFT = "RETURN_TO_DRAFT"
    PUBLISH = "PUBLISH"
    WITHDRAW = "WITHDRAW"
    ARCHIVE = "ARCHIVE"


class MobilityLevel(str, Enum):
    LEVEL_1 = "LEVEL_1"
    LEVEL_2 = "LEVEL_2"
    LEVEL_3 = "LEVEL_3"
    LEVEL_4 = "LEVEL_4"


class GuestMobilityLevel(str, Enum):
    WHEELCHAIR = "WHEELCHAIR"
    ASSISTED = "ASSISTED"
    FULL = "FULL"


class PriceTier(str, Enum):
    VALUE = "VALUE"
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"
    SIGNATURE = "SIGNATURE"


class MedicalCode(str, Enum):
    CARDIAC = "CARDIAC"
    RESPIRATORY = "RESPIRATORY"
    PREGNANCY = "PREGNANCY"
    MOTION_SICKNESS = "MOTION_SICKNESS"
    ALTITUDE = "ALTITUDE"


class Language(str, Enum):
    EN = "EN"
    ES = "ES"
    DE = "DE"
    FR = "FR"
    IT = "IT"
    PT = "PT"
    ZH = "ZH"


class LoyaltyTier(str, Enum):
    NONE = "NONE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class DepartureStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SELLING = "SELLING"
    CLOSED = "CLOSED"
    OPERATING = "OPERATING"
    COMPLETED = "COMPLETED"
    CANCELLED_WEATHER = "CANCELLED_WEATHER"
    CANCELLED_OPERATIONAL = "CANCELLED_OPERATIONAL"


class CancellationCause(str, Enum):
    WEATHER = "WEATHER"
    OPERATIONAL = "OPERATIONAL"


class DepartureOperation(str, Enum):
    DISPATCH = "DISPATCH"
    COMPLETE = "COMPLETE"


class TimingRiskBand(str, Enum):
    GREEN = "GREEN"
    AMBER = "AMBER"
    RED = "RED"


class SalesChannel(str, Enum):
    PRE_CRUISE = "PRE_CRUISE"
    ONBOARD = "ONBOARD"


class FulfillmentStatus(str, Enum):
    BOOKED = "BOOKED"
    TICKETED = "TICKETED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED_BY_GUEST = "CANCELLED_BY_GUEST"
    CANCELLED_BY_LINE = "CANCELLED_BY_LINE"


class FulfillmentAction(str, Enum):
    TICKET = "TICKET"
    CHECK_IN = "CHECK_IN"
    MARK_NO_SHOW = "MARK_NO_SHOW"


class FinancialStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    CHARGED = "CHARGED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"
    RETAINED = "RETAINED"
    VOIDED = "VOIDED"


class AlternativeOfferStatus(str, Enum):
    NONE = "NONE"
    OFFERED = "OFFERED"
    EXPIRED = "EXPIRED"


class LedgerEntryKind(str, Enum):
    REFUND = "REFUND"
    AUTH_VOID = "AUTH_VOID"
    GOODWILL_CREDIT = "GOODWILL_CREDIT"
    REPATRIATION_ALLOWANCE = "REPATRIATION_ALLOWANCE"
    RETENTION = "RETENTION"


class LedgerBasis(str, Enum):
    GUEST_INITIATED = "GUEST_INITIATED"
    LINE_CANCELLED_WEATHER = "LINE_CANCELLED_WEATHER"
    LINE_CANCELLED_OPERATIONAL = "LINE_CANCELLED_OPERATIONAL"
    NO_SHOW = "NO_SHOW"
    RETURN_GUARANTEE_BREACH = "RETURN_GUARANTEE_BREACH"


class IncidentCategory(str, Enum):
    INJURY = "INJURY"
    MEDICAL = "MEDICAL"
    PROPERTY_LOSS = "PROPERTY_LOSS"
    LEFT_BEHIND = "LEFT_BEHIND"
    SERVICE_FAILURE = "SERVICE_FAILURE"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class IncidentStatus(str, Enum):
    FILED = "FILED"
    CLAIM_OPENED = "CLAIM_OPENED"
    CLOSED_NO_CLAIM = "CLOSED_NO_CLAIM"
    CLOSED_UPHELD = "CLOSED_UPHELD"
    CLOSED_DENIED = "CLOSED_DENIED"


class ClaimBasisCode(str, Enum):
    NEGLIGENCE = "NEGLIGENCE"
    EQUIPMENT_FAILURE = "EQUIPMENT_FAILURE"
    GUIDE_CONDUCT = "GUIDE_CONDUCT"
    ROUTE_DEVIATION = "ROUTE_DEVIATION"
    MEDICAL_RESPONSE = "MEDICAL_RESPONSE"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_OPERATOR_REVIEW = "UNDER_OPERATOR_REVIEW"
    DISPUTED = "DISPUTED"
    ADJUDICATED_UPHELD = "ADJUDICATED_UPHELD"
    ADJUDICATED_DENIED = "ADJUDICATED_DENIED"
    SETTLED = "SETTLED"


class ClaimAction(str, Enum):
    SEND_TO_OPERATOR = "SEND_TO_OPERATOR"
    RECORD_DISPUTE = "RECORD_DISPUTE"
    ADJUDICATE_UPHELD = "ADJUDICATE_UPHELD"
    ADJUDICATE_DENIED = "ADJUDICATE_DENIED"


class StatementBasis(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class StatementStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    ADJUSTED = "ADJUSTED"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class StatementAction(str, Enum):
    ISSUE = "ISSUE"
    DISPUTE = "DISPUTE"
    ADJUST = "ADJUST"
    SETTLE = "SETTLE"


# --------------------------------------------------------------------------
# Entity shapes
# --------------------------------------------------------------------------

class Port(TypedDict):
    id: str
    port_code: str
    name: str
    country_code: str
    docking_mode: str
    risk_buffer_minutes: int
    tender_egress_minutes: int
    created_at: str
    updated_at: str
    version: int


class MeetingPoint(TypedDict):
    id: str
    port_id: str
    name: str
    zone: str
    max_concurrent_groups: int
    slot_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class PortCall(TypedDict):
    id: str
    port_id: str
    voyage_code: str
    ship_code: str
    arrival_utc: str
    all_aboard_utc: str
    departure_utc: str
    delay_minutes: int
    effective_arrival_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TenderWave(TypedDict):
    id: str
    port_call_id: str
    wave_index: int
    window_start_utc: str
    window_end_utc: str
    guest_capacity: int
    priority_class: str
    assigned_guest_count: int
    assigned_departure_count: int
    created_at: str
    updated_at: str
    version: int


class TourOperator(TypedDict):
    id: str
    port_id: str
    legal_name: str
    contact_email: str
    insurance_expiry_date: str
    insurance_liability_limit_cents: int
    commission_rate_bps: int
    vetting_status: str
    vetting_cycle_count: int
    safety_score: int
    reliability_strikes: int
    liability_reserve_cents: int
    latest_audit_auditor_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SafetyAudit(TypedDict):
    """Append-only: carries only id and created_at — no updated_at, no version."""
    id: str
    created_at: str
    operator_id: str
    audit_type: str
    conducted_on: str
    raw_score: int
    critical_finding_count: int
    auditor_user_id: str


class Excursion(TypedDict):
    id: str
    port_id: str
    operator_id: str
    alternative_excursion_id: Optional[str]
    title: str
    duration_minutes: int
    min_age: int
    max_age: Optional[int]
    mobility_level: str
    medical_warning_codes: List[str]
    languages: List[str]
    base_price_cents: int
    price_tier: str
    is_line_operated: bool
    return_guarantee: bool
    catalog_status: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExcursionDeparture(TypedDict):
    id: str
    excursion_id: str
    port_call_id: str
    meeting_point_id: str
    tender_wave_id: Optional[str]
    meeting_time_utc: str
    dispatch_dwell_minutes: int
    total_capacity: int
    precruise_allocation: int
    onboard_allocation: int
    precruise_sold_seats: int
    onboard_sold_seats: int
    seats_available_total: int
    effective_precruise_available: int
    effective_onboard_available: int
    status: str
    cancellation_cause: Optional[str]
    projected_return_scheduled_utc: str
    projected_return_actual_utc: str
    slack_minutes_scheduled: int
    slack_minutes_actual: int
    timing_risk_band_scheduled: str
    timing_risk_band_actual: str
    return_guarantee_eligible: bool
    actual_return_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Guest(TypedDict):
    id: str
    full_name: str
    birth_date: str
    voyage_code: str
    mobility_level: str
    language_pref: str
    medical_flags: List[str]
    loyalty_tier: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    departure_id: str
    guest_id: str
    alternative_departure_id: Optional[str]
    party_size: int
    channel: str
    language_choice: str
    medical_warning_acknowledged: bool
    age_at_meeting: int
    per_guest_price_cents: int
    quoted_total_cents: int
    service_fee_cents: int
    charge_total_cents: int
    refunded_cents: int
    retained_cents: int
    goodwill_credit_cents: int
    commission_accrued_cents: int
    fulfillment_status: str
    financial_status: str
    alternative_offer_status: str
    return_guarantee_honored: bool
    created_at: str
    updated_at: str
    version: int


class RefundLedgerEntry(TypedDict):
    """Append-only: carries only id and created_at — no updated_at, no version."""
    id: str
    created_at: str
    booking_id: str
    entry_kind: str
    amount_cents: int
    refund_pct_bps: int
    basis: str
    reason_code: str


class GuestIncident(TypedDict):
    id: str
    booking_id: str
    category: str
    severity: str
    occurred_utc: str
    narrative: str
    filed_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LiabilityClaim(TypedDict):
    id: str
    incident_id: str
    operator_id: str
    port_call_id: str
    claimed_amount_cents: int
    basis_code: str
    status: str
    dispute_round_count: int
    liability_share_bps: int
    settlement_amount_cents: int
    operator_charge_cents: int
    submitted_by_user_id: str
    adjudicated_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommissionStatement(TypedDict):
    id: str
    operator_id: str
    port_call_id: str
    basis: str
    status: str
    gross_ticket_cents: int
    refunds_cents: int
    port_fee_cents: int
    line_commission_cents: int
    claim_offset_cents: int
    operational_penalty_cents: int
    payable_pre_rebate_cents: int
    rebate_bps: int
    rebate_cents: int
    adjustment_cents: int
    operator_payable_cents: int
    booking_line_count: int
    issued_at: Optional[str]
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
