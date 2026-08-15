"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow the PRD resource descriptions. CarrierLaneAssignment and
ClaimEvent are the two lightweight resources that carry only id + created_at
(no updated_at, no version).
"""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CLAIMS_CLERK = "ClaimsClerk"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    CLAIMS_MANAGER = "ClaimsManager"
    SALVAGE_COORDINATOR = "SalvageCoordinator"
    SUBROGATION_SPECIALIST = "SubrogationSpecialist"
    FINANCE_CONTROLLER = "FinanceController"


class LiabilityModel(str, Enum):
    FULL_VALUE = "FULL_VALUE"
    RELEASED_RATE = "RELEASED_RATE"
    PER_PACKAGE = "PER_PACKAGE"
    PER_POUND = "PER_POUND"


class CarrierStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class LaneStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ShipmentStatus(str, Enum):
    DELIVERED = "DELIVERED"
    CLAIMED = "CLAIMED"
    CLOSED = "CLOSED"


class CommodityClass(str, Enum):
    GENERAL = "GENERAL"
    FRAGILE = "FRAGILE"
    PERISHABLE = "PERISHABLE"
    HIGH_VALUE = "HIGH_VALUE"
    HAZMAT = "HAZMAT"


class ClaimType(str, Enum):
    LOSS = "LOSS"
    DAMAGE = "DAMAGE"
    SHORTAGE = "SHORTAGE"
    CONCEALED_DAMAGE = "CONCEALED_DAMAGE"
    DELAY = "DELAY"


class FilingStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    UNDER_REVIEW = "UNDER_REVIEW"
    OFFERED = "OFFERED"
    DECLINED = "DECLINED"
    APPEALED = "APPEALED"
    PAID = "PAID"
    CLOSED_WITH_PAYMENT = "CLOSED_WITH_PAYMENT"
    CLOSED_NO_PAYMENT = "CLOSED_NO_PAYMENT"
    WITHDRAWN = "WITHDRAWN"
    TIME_BARRED = "TIME_BARRED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PARTIAL = "PARTIAL"
    PAID_IN_FULL = "PAID_IN_FULL"
    WAIVED = "WAIVED"


class DocumentKind(str, Enum):
    BOL = "BOL"
    COMMERCIAL_INVOICE = "COMMERCIAL_INVOICE"
    PHOTO = "PHOTO"
    DELIVERY_RECEIPT = "DELIVERY_RECEIPT"
    INSPECTION_REPORT = "INSPECTION_REPORT"
    REPAIR_ESTIMATE = "REPAIR_ESTIMATE"


class VerificationStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class NegligenceFlag(str, Enum):
    NONE = "NONE"
    CARRIER_NEGLIGENT = "CARRIER_NEGLIGENT"
    SHIPPER_FAULT = "SHIPPER_FAULT"
    ACT_OF_GOD = "ACT_OF_GOD"
    THIRD_PARTY = "THIRD_PARTY"


class AssessmentState(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class DispositionKind(str, Enum):
    RETURN_TO_SHIPPER = "RETURN_TO_SHIPPER"
    AUCTION = "AUCTION"
    DESTROY = "DESTROY"
    DONATE = "DONATE"
    REPAIR_AND_RETURN = "REPAIR_AND_RETURN"


class SalvageState(str, Enum):
    SCHEDULED = "SCHEDULED"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"


class AppealDecision(str, Enum):
    PENDING = "PENDING"
    UPHOLD_DECLINE = "UPHOLD_DECLINE"
    OVERTURN = "OVERTURN"
    PARTIAL = "PARTIAL"


class AppealState(str, Enum):
    OPEN = "OPEN"
    UNDER_ESCALATION = "UNDER_ESCALATION"
    DECIDED = "DECIDED"
    CLOSED = "CLOSED"


class SettlementState(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    COUNTERED = "COUNTERED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class AuthorityTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class ResponsiblePartyKind(str, Enum):
    THIRD_PARTY_CARRIER = "THIRD_PARTY_CARRIER"
    WAREHOUSE = "WAREHOUSE"
    BROKER = "BROKER"
    SHIPPER_VENDOR = "SHIPPER_VENDOR"
    OTHER = "OTHER"


class SubrogationState(str, Enum):
    OPEN = "OPEN"
    DEMAND_SENT = "DEMAND_SENT"
    IN_LITIGATION = "IN_LITIGATION"
    SETTLED = "SETTLED"
    CLOSED_UNRECOVERABLE = "CLOSED_UNRECOVERABLE"


class ReserveState(str, Enum):
    OPEN = "OPEN"
    RELEASED = "RELEASED"
    EXHAUSTED = "EXHAUSTED"


class EventKind(str, Enum):
    FILED = "FILED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ASSESSED = "ASSESSED"
    OFFER_EXTENDED = "OFFER_EXTENDED"
    OFFER_ACCEPTED = "OFFER_ACCEPTED"
    OFFER_REJECTED = "OFFER_REJECTED"
    DECLINED = "DECLINED"
    APPEAL_OPENED = "APPEAL_OPENED"
    APPEAL_DECIDED = "APPEAL_DECIDED"
    SALVAGE_POSTED = "SALVAGE_POSTED"
    RESERVE_POSTED = "RESERVE_POSTED"
    RESERVE_RELEASED = "RESERVE_RELEASED"
    PAID_OUT = "PAID_OUT"
    SUBROGATION_OPENED = "SUBROGATION_OPENED"
    SUBROGATION_RECOVERY = "SUBROGATION_RECOVERY"
    WITHDRAWN = "WITHDRAWN"
    TIME_BARRED = "TIME_BARRED"
    ACK_LATE_FLAGGED = "ACK_LATE_FLAGGED"


class DayKind(str, Enum):
    BUSINESS = "BUSINESS"
    WEEKEND = "WEEKEND"
    HOLIDAY = "HOLIDAY"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class Carrier(TypedDict, total=False):
    id: str
    scac_code: str
    legal_name: str
    liability_model: str
    released_rate_cents_per_lb: Optional[int]
    per_package_cap_cents: Optional[int]
    per_pound_cap_cents: Optional[int]
    max_auto_settle_cents: int
    carmack_acknowledgment_days: int
    carmack_filing_days: int
    claims_filed_count: int
    claims_paid_count: int
    claim_ratio_bp: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Lane(TypedDict, total=False):
    id: str
    origin_zip3: str
    destination_zip3: str
    baseline_claim_ratio_bp: int
    shipments_count: int
    claims_count: int
    lane_claim_ratio_bp: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CarrierLaneAssignment(TypedDict, total=False):
    # Lightweight resource: id + created_at only (no updated_at / version).
    id: str
    carrier_id: str
    lane_id: str
    contracted_discount_pct: int
    effective_from: str
    effective_to: str
    created_at: str


class Shipment(TypedDict, total=False):
    id: str
    bol_number: str
    carrier_id: str
    lane_id: str
    ship_date: str
    delivery_date: str
    declared_value_cents: int
    total_weight_lbs: int
    package_count: int
    commodity_class: str
    is_concealed_damage: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    shipment_id: str
    carrier_id: str
    lane_id: str
    claim_type: str
    claimed_amount_cents: int
    filing_received_at: Optional[str]
    filing_deadline_at: Optional[str]
    acknowledgment_due_at: Optional[str]
    acknowledged_at: Optional[str]
    acknowledgment_late: bool
    liability_assessment_id: Optional[str]
    computed_liability_cents: int
    salvage_credit_cents: int
    net_exposure_cents: int
    reserve_amount_cents: int
    settlement_amount_cents: Optional[int]
    appeal_round: int
    filing_status: str
    payment_status: str
    concurrency_token: int
    created_at: str
    updated_at: str
    version: int


class ClaimDocument(TypedDict, total=False):
    id: str
    claim_id: str
    document_kind: str
    storage_uri: str
    captured_at: str
    verification_status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LiabilityAssessment(TypedDict, total=False):
    id: str
    claim_id: str
    assessed_by_user_id: str
    liability_model_applied: str
    limitation_basis_cents: int
    carrier_limit_cents: int
    lane_discount_pct: int
    computed_liability_cents: int
    negligence_flag: str
    state: str
    created_at: str
    updated_at: str
    version: int


class SalvageDisposition(TypedDict, total=False):
    id: str
    claim_id: str
    disposition_kind: str
    gross_proceeds_cents: int
    handling_cost_cents: int
    net_credit_cents: int
    scheduled_at: str
    state: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict, total=False):
    id: str
    claim_id: str
    round_number: int
    opened_by_user_id: str
    justification: str
    requested_amount_cents: int
    decision: str
    decided_amount_cents: Optional[int]
    escalated_to_user_id: Optional[str]
    state: str
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict, total=False):
    id: str
    claim_id: str
    round_number: int
    offered_by_role: str
    amount_cents: int
    authority_tier_required: str
    approved_by_user_id: Optional[str]
    state: str
    created_at: str
    updated_at: str
    version: int


class SubrogationCase(TypedDict, total=False):
    id: str
    claim_id: str
    responsible_party_kind: str
    responsible_party_name: str
    target_recovery_cents: int
    recovered_cents: int
    recovery_ratio_bp: int
    state: str
    created_at: str
    updated_at: str
    version: int


class Reserve(TypedDict, total=False):
    id: str
    claim_id: str
    amount_cents: int
    posted_by_user_id: str
    posted_at: str
    released_at: Optional[str]
    state: str
    created_at: str
    updated_at: str
    version: int


class ClaimEvent(TypedDict, total=False):
    # Append-only resource: id + created_at only (no updated_at / version).
    id: str
    claim_id: str
    event_kind: str
    actor_user_id: str
    event_at: str
    payload_json: dict
    created_at: str


class ClaimsCalendarRow(TypedDict, total=False):
    id: str
    calendar_date: str
    is_business_day: bool
    day_kind: str
    created_at: str
    updated_at: str
    version: int
