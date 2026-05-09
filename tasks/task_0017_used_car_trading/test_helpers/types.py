"""Domain types: entity TypedDicts, status enums, role enum.

All names match the PRD verbatim. Entities whose PRD §2.4 prose excludes
``updated_at`` and ``version`` (Bid, Reservation, ExternalEvent, AuditLog)
omit those fields here so downstream assertions cannot demand fields the
implementer was correctly told not to return.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ──────────────────────────────────────────────────────────
# Roles (PRD §2.1)
# ──────────────────────────────────────────────────────────


class UserRole(str, Enum):
    SELLER = "Seller"
    BUYER = "Buyer"
    INSPECTOR = "Inspector"
    PLATFORM_ADMIN = "PlatformAdmin"


# ──────────────────────────────────────────────────────────
# Status enums (PRD §3, derived from each entity's lifecycle prose)
# ──────────────────────────────────────────────────────────


class VehicleStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ASSESSED = "ASSESSED"
    LISTED = "LISTED"
    SOLD = "SOLD"
    ARCHIVED = "ARCHIVED"


class AssessmentReportStatus(str, Enum):
    DRAFT = "DRAFT"
    ONSITE_PENDING = "ONSITE_PENDING"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class ListingStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    ACTIVE = "ACTIVE"
    RESERVED = "RESERVED"
    SOLD = "SOLD"
    DELISTED = "DELISTED"
    REJECTED = "REJECTED"


class SaleMode(str, Enum):
    AUCTION = "AUCTION"
    FIXED_PRICE = "FIXED_PRICE"


class DocCheckStatus(str, Enum):
    NOT_RUN = "NOT_RUN"
    PASS = "PASS"
    FAIL = "FAIL"


class BidStatus(str, Enum):
    LIVE = "LIVE"
    OUTBID = "OUTBID"
    WON = "WON"
    LOST = "LOST"
    CANCELLED = "CANCELLED"


class ReservationStatus(str, Enum):
    QUEUED = "QUEUED"
    HOLDING = "HOLDING"
    EXPIRED = "EXPIRED"
    CONVERTED = "CONVERTED"
    CANCELLED = "CANCELLED"


class PurchaseOrderStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    PAID = "PAID"
    AWAITING_TRANSFER = "AWAITING_TRANSFER"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"


class PaymentMethod(str, Enum):
    FULL_PAYMENT = "FULL_PAYMENT"
    LOAN = "LOAN"


class TransferCaseStatus(str, Enum):
    DOCS_PENDING = "DOCS_PENDING"
    APPOINTMENT_BOOKED = "APPOINTMENT_BOOKED"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"


class LicensePlateAction(str, Enum):
    KEEP_OLD = "KEEP_OLD"
    REASSIGN = "REASSIGN"
    NEW_NUMBER = "NEW_NUMBER"


class LoanStatus(str, Enum):
    APPLIED = "APPLIED"
    CREDIT_CHECKING = "CREDIT_CHECKING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DISBURSED = "DISBURSED"
    CANCELLED = "CANCELLED"


class LenderCode(str, Enum):
    LENDER_A = "LENDER_A"
    LENDER_B = "LENDER_B"
    LENDER_C = "LENDER_C"


class WarrantyStatus(str, Enum):
    PENDING_ACTIVATION = "PENDING_ACTIVATION"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"


class WarrantyPackage(str, Enum):
    BASIC = "BASIC"
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class WarrantyClaimStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PAID = "PAID"


class DisputeStage(str, Enum):
    SUBMITTED = "SUBMITTED"
    EVIDENCE_REVIEW = "EVIDENCE_REVIEW"
    THIRD_PARTY_INSPECTION = "THIRD_PARTY_INSPECTION"
    RESOLUTION_PROPOSED = "RESOLUTION_PROPOSED"
    CLOSED = "CLOSED"


class DisputeResolution(str, Enum):
    REFUND_FULL = "REFUND_FULL"
    REFUND_PARTIAL = "REFUND_PARTIAL"
    COMPENSATE_SELLER = "COMPENSATE_SELLER"
    NO_ACTION = "NO_ACTION"


class ComplainantRole(str, Enum):
    BUYER = "BUYER"
    SELLER = "SELLER"


class KycStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class AuditEventType(str, Enum):
    STATE_TRANSITION = "STATE_TRANSITION"
    OWNERSHIP_CHANGE = "OWNERSHIP_CHANGE"
    FINANCIAL_HOLD = "FINANCIAL_HOLD"
    FINANCIAL_RELEASE = "FINANCIAL_RELEASE"
    EXTERNAL_SYNC = "EXTERNAL_SYNC"


# ──────────────────────────────────────────────────────────
# Entity TypedDicts — common_fields: true entities carry id, created_at,
# updated_at, version. Append-only entities (Bid, Reservation, ExternalEvent,
# AuditLog) carry only id and created_at per PRD §2.4.
# ──────────────────────────────────────────────────────────


class Seller(TypedDict, total=False):
    id: str
    legal_name: str
    id_document_number: str
    phone: str
    kyc_status: str
    total_listings: int
    created_at: str
    updated_at: str
    version: int


class Buyer(TypedDict, total=False):
    id: str
    legal_name: str
    id_document_number: str
    phone: str
    deposit_balance_cents: int
    deposit_held_cents: int
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict, total=False):
    id: str
    vin: str
    make: str
    model: str
    model_year: int
    declared_mileage_km: int
    verified_mileage_km: Optional[int]
    color: str
    vehicle_status: str
    ownership_seller_id: str
    assessment_score: Optional[int]
    valuation_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class AssessmentReport(TypedDict, total=False):
    id: str
    vehicle_id: str
    vin_history_records: List[Dict[str, Any]]
    accident_count: int
    major_accident_count: int
    maintenance_count: int
    inspector_user_id: str
    onsite_findings: Optional[Dict[str, Any]]
    declared_mileage_km: Optional[int]
    mileage_discrepancy_flag: bool
    provisional_valuation_cents: Optional[int]
    final_valuation_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Listing(TypedDict, total=False):
    id: str
    vehicle_id: str
    seller_id: str
    assessment_report_id: str
    assessment_report_version: Optional[int]
    sale_mode: str
    ask_price_cents: int
    reserve_price_cents: Optional[int]
    photo_urls: List[str]
    documents_authentic_flag: bool
    doc_check_status: str
    status: str
    active_bid_id: Optional[str]
    reservation_buyer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Bid: append-only — only id + created_at per PRD §2.4
class Bid(TypedDict, total=False):
    id: str
    listing_id: str
    buyer_id: str
    amount_cents: int
    deposit_cents: int
    status: str
    placed_at: str
    created_at: str


# Reservation: append-only — only id + created_at per PRD §2.4
class Reservation(TypedDict, total=False):
    id: str
    listing_id: str
    buyer_id: str
    queue_position: int
    deposit_cents: int
    status: str
    hold_expires_at: Optional[str]
    created_at: str


class PurchaseOrder(TypedDict, total=False):
    id: str
    listing_id: str
    vehicle_id: str
    seller_id: str
    buyer_id: str
    agreed_price_cents: int
    payment_method: str
    loan_id: Optional[str]
    down_payment_cents: int
    status: str
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransferCase(TypedDict, total=False):
    id: str
    purchase_order_id: str
    required_documents: List[Dict[str, Any]]
    appointment_at: Optional[str]
    dmv_office_code: Optional[str]
    status: str
    license_plate_action: str
    new_plate_number: Optional[str]
    failure_reason: Optional[str]
    rolled_back_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict, total=False):
    id: str
    purchase_order_id: str
    buyer_id: str
    lender_code: str
    requested_principal_cents: int
    approved_principal_cents: Optional[int]
    down_payment_ratio_bp: int
    term_months: int
    monthly_payment_cents: Optional[int]
    total_interest_cents: Optional[int]
    credit_score: Optional[int]
    status: str
    disbursed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Warranty(TypedDict, total=False):
    id: str
    purchase_order_id: str
    package_code: str
    coverage_scope: List[str]
    effective_at: Optional[str]
    expires_at: Optional[str]
    status: str
    claims_count: int
    total_claim_payout_cents: int
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    warranty_id: str
    component: str
    claimed_amount_cents: int
    approved_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class DisputeCase(TypedDict, total=False):
    id: str
    purchase_order_id: str
    complainant_role: str
    complaint_text: str
    evidence_items: List[Dict[str, Any]]
    stage: str
    round_count: int
    third_party_report_url: Optional[str]
    resolution: Optional[str]
    refund_amount_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


# ExternalEvent: append-only — only id + created_at per PRD §2.4
class ExternalEvent(TypedDict, total=False):
    id: str
    source: str
    event_type: str
    idempotency_key: str
    payload: Dict[str, Any]
    processed: bool
    created_at: str


# AuditLog: append-only — only id + created_at per PRD §2.4
class AuditLog(TypedDict, total=False):
    id: str
    actor_role: str
    actor_id: str
    target_entity: str
    target_id: str
    event_type: str
    from_value: Optional[str]
    to_value: Optional[str]
    occurred_at: str
    created_at: str
