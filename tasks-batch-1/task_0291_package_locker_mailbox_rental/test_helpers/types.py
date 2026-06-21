"""Domain types: entity TypedDicts, status enums, and the role enum.

Field names mirror the PRD exactly. Entities that the PRD declares append-only
(AuthorizedRecipient, LedgerEntry) omit updated_at and version intentionally.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    FACILITY_OPERATOR = "FacilityOperator"
    CUSTOMER = "Customer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class LockerStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OCCUPIED = "OCCUPIED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class MailboxStatus(str, Enum):
    VACANT = "VACANT"
    RENTED = "RENTED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class Form1583Status(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class RentalAgreementStatus(str, Enum):
    PENDING_AUTH = "PENDING_AUTH"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"
    ABANDONED = "ABANDONED"


class PackageStatus(str, Enum):
    RECEIVED = "RECEIVED"
    NOTIFIED = "NOTIFIED"
    PICKED_UP = "PICKED_UP"
    FORWARDED = "FORWARDED"
    RETURNED = "RETURNED"
    ABANDONED = "ABANDONED"


class MailItemStatus(str, Enum):
    STORED = "STORED"
    SCANNED = "SCANNED"
    FORWARDED = "FORWARDED"
    SHREDDED = "SHREDDED"


class ForwardingRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ON_HOLD = "ON_HOLD"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    SETTLED = "SETTLED"
    WRITTEN_OFF = "WRITTEN_OFF"


class PaymentStatus(str, Enum):
    CAPTURED = "CAPTURED"


# ---------------------------------------------------------------------------
# Enum value lists (for membership assertions)
# ---------------------------------------------------------------------------
LOCKER_SIZE_TIERS = ["SMALL", "MEDIUM", "LARGE", "XL"]
MAILBOX_SIZE_TIERS = ["SMALL", "MEDIUM", "LARGE"]
PACKAGE_SIZE_TIERS = ["SMALL", "MEDIUM", "LARGE", "XL"]
CARRIERS = ["USPS", "UPS", "FEDEX", "AMAZON", "OTHER"]
PRIMARY_ID_TYPES = ["PASSPORT", "DRIVERS_LICENSE", "STATE_ID"]
ADDRESS_PROOF_TYPES = ["LEASE", "UTILITY_BILL", "VEHICLE_REG"]
RECIPIENT_RELATIONSHIPS = ["SELF", "FAMILY", "BUSINESS", "MINOR"]
MAIL_CLASSES = ["FIRST_CLASS", "MARKETING", "CERTIFIED", "PARCEL"]
FORWARDING_KINDS = ["FORWARD", "SCAN"]
LEDGER_KINDS = ["CHARGE", "CREDIT"]
LEDGER_REASONS = ["RENTAL", "OVERSIZE", "OVERSTAY", "FORWARDING", "PRORATED_REFUND", "WRITE_OFF"]
PAYMENT_METHODS = ["CARD_AUTOPAY", "CARD_MANUAL", "CASH"]


# ---------------------------------------------------------------------------
# Entity TypedDicts (common_fields: true -> id, created_at, updated_at, version)
# ---------------------------------------------------------------------------
class Facility(TypedDict):
    id: str
    name: str
    time_zone: str
    current_utc: str
    total_locker_count: int
    available_locker_count: int
    created_at: str
    updated_at: str
    version: int


class LockerUnit(TypedDict):
    id: str
    facility_id: str
    label: str
    size_tier: str
    status: str
    current_package_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MailboxUnit(TypedDict):
    id: str
    facility_id: str
    box_number: str
    size_tier: str
    monthly_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    facility_id: str
    full_name: str
    email: str
    phone: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Form1583(TypedDict):
    id: str
    facility_id: str
    customer_id: str
    primary_id_type: str
    address_proof_type: str
    status: str
    submission_count: int
    verified_at: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RentalAgreement(TypedDict):
    id: str
    facility_id: str
    customer_id: str
    mailbox_unit_id: str
    form_1583_id: str
    term_months: int
    monthly_fee_cents: int
    term_start: Optional[str]
    term_end: Optional[str]
    autopay_enabled: bool
    status: str
    renewal_count: int
    created_at: str
    updated_at: str
    version: int


class Package(TypedDict):
    id: str
    facility_id: str
    rental_agreement_id: str
    locker_unit_id: Optional[str]
    carrier: str
    size_tier: str
    longest_dim_cm: int
    weight_g: int
    pickup_code: str
    notified_at: Optional[str]
    resolved_at: Optional[str]
    oversize_fee_cents: int
    overstay_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MailItem(TypedDict):
    id: str
    facility_id: str
    rental_agreement_id: str
    mail_class: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ForwardingRequest(TypedDict):
    id: str
    facility_id: str
    mail_item_id: str
    kind: str
    destination_address: Optional[str]
    fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    facility_id: str
    rental_agreement_id: str
    charges_total_cents: int
    credits_total_cents: int
    payments_total_cents: int
    balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    facility_id: str
    invoice_id: str
    amount_cents: int
    method: str
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entities (common_fields: false -> id + created_at only)
# ---------------------------------------------------------------------------
class AuthorizedRecipient(TypedDict):
    id: str
    form_1583_id: str
    recipient_name: str
    relationship: str
    created_at: str


class LedgerEntry(TypedDict):
    id: str
    invoice_id: str
    kind: str
    reason: str
    amount_cents: int
    source_ref: str
    created_at: str
