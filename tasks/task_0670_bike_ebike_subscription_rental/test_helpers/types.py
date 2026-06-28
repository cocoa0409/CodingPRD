"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entity model and lifecycle definitions.
"""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    SUBSCRIBER = "Subscriber"
    FLEET_MANAGER = "FleetManager"
    FIELD_TECH = "FieldTech"
    OPS_ADMIN = "OpsAdmin"
    ANONYMOUS = "Anonymous"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class ModelClass(str, Enum):
    STANDARD = "STANDARD"
    EBIKE = "EBIKE"
    CARGO_EBIKE = "CARGO_EBIKE"


class BikeModelStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class AccountType(str, Enum):
    SUBSCRIBER = "SUBSCRIBER"
    FLEET = "FLEET"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RentalMode(str, Enum):
    MONTHLY = "MONTHLY"
    DAILY = "DAILY"


class RentalLifecycleStatus(str, Enum):
    RESERVED = "RESERVED"
    DELIVERED = "DELIVERED"
    ACTIVE = "ACTIVE"
    IN_SERVICE = "IN_SERVICE"
    RETURN_REQUESTED = "RETURN_REQUESTED"
    RETURNED = "RETURNED"
    BOUGHT_OUT = "BOUGHT_OUT"
    CANCELLED = "CANCELLED"


class RentalBillingStatus(str, Enum):
    DEPOSIT_HELD = "DEPOSIT_HELD"
    BILLING_ACTIVE = "BILLING_ACTIVE"
    SETTLED = "SETTLED"
    WRITTEN_OFF = "WRITTEN_OFF"


class DeliveryType(str, Enum):
    INITIAL = "INITIAL"
    SWAP = "SWAP"
    PICKUP = "PICKUP"


class DeliveryStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class IssueType(str, Enum):
    FLAT_TIRE = "FLAT_TIRE"
    BRAKE = "BRAKE"
    BATTERY = "BATTERY"
    MOTOR = "MOTOR"
    OTHER = "OTHER"


class Severity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class ServiceTicketStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"
    CLOSED = "CLOSED"


class BikeCondition(str, Enum):
    GOOD = "GOOD"
    WORN = "WORN"
    DAMAGED = "DAMAGED"


class ClaimType(str, Enum):
    THEFT = "THEFT"
    DAMAGE = "DAMAGE"


class CoverageClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CLOSED = "CLOSED"


class BuyoutOfferStatus(str, Enum):
    QUOTED = "QUOTED"
    ACCEPTED = "ACCEPTED"


class FleetInvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"


class BikeStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    OUT = "OUT"
    SERVICING = "SERVICING"
    RETIRED = "RETIRED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------
# common_fields: true — carry id + created_at + updated_at + version
class BikeModel(TypedDict):
    id: str
    name: str
    model_class: str
    monthly_fee_cents: int
    daily_rate_cents: int
    purchase_price_cents: int
    deposit_cents: int
    fleet_size: int
    total_bikes: int
    available_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict):
    id: str
    account_type: str
    display_name: str
    email: str
    rental_cap: int
    wallet_credit_cents: int
    outstanding_balance_cents: int
    active_rental_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RentalAgreement(TypedDict):
    id: str
    account_id: str
    bike_id: str
    model_id: str
    rental_mode: str
    lifecycle_status: str
    billing_status: str
    reserved_at_clock: str
    activated_at_clock: Optional[str]
    return_due_clock: str
    returned_at_clock: Optional[str]
    deposit_cents: int
    completed_cycles: int
    accrued_charge_cents: int
    expected_model_version: int
    created_at: str
    updated_at: str
    version: int


class Delivery(TypedDict):
    id: str
    rental_id: str
    delivery_type: str
    address: str
    window_start_clock: str
    window_end_clock: str
    swap_to_bike_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceTicket(TypedDict):
    id: str
    rental_id: str
    issue_type: str
    severity: str
    description: str
    status: str
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CoverageClaim(TypedDict):
    id: str
    rental_id: str
    claim_type: str
    incident_clock: str
    claimed_amount_cents: int
    status: str
    approved_payout_cents: int
    created_at: str
    updated_at: str
    version: int


class BuyoutOffer(TypedDict):
    id: str
    rental_id: str
    quoted_price_cents: int
    equity_credit_cents: int
    status: str
    expires_at_clock: str
    created_at: str
    updated_at: str
    version: int


class FleetInvoice(TypedDict):
    id: str
    account_id: str
    cycle_index: int
    line_count: int
    gross_amount_cents: int
    discount_cents: int
    amount_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Bike(TypedDict):
    id: str
    model_id: str
    serial_number: str
    bike_status: str
    current_rental_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, carries ONLY id + created_at (no updated_at, no version)
class InspectionReport(TypedDict):
    id: str
    rental_id: str
    bike_condition: str
    damage_charge_cents: int
    cleaning_fee_cents: int
    late_fee_cents: int
    total_assessed_cents: int
    deposit_applied_cents: int
    deposit_refund_cents: int
    overflow_billed_cents: int
    created_at: str
