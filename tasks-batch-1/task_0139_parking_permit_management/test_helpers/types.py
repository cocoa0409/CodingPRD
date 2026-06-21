"""Domain types: entity TypedDicts, status enums, role enum.

All structures follow the Parking & Permit Management PRD. Entities carrying the
full common field set expose id + created_at + updated_at + version; PlateRead is
the sole append-only resource and carries only id + created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    FACILITY_ADMIN = "FacilityAdmin"
    MOTORIST = "Motorist"
    MERCHANT = "Merchant"
    ENFORCEMENT_OFFICER = "EnforcementOfficer"


# ---------------------------------------------------------------------------
# Status / enum value sets
# ---------------------------------------------------------------------------
class GateMode(str, Enum):
    PERMIT_OR_TRANSIENT = "PERMIT_OR_TRANSIENT"
    PERMIT_ONLY = "PERMIT_ONLY"
    CLOSED = "CLOSED"


class ZoneType(str, Enum):
    TRANSIENT = "TRANSIENT"
    PERMIT = "PERMIT"
    MIXED = "MIXED"


class SpaceStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class EventPricingStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


class PermitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


class WaitlistStatus(str, Enum):
    WAITING = "WAITING"
    PROMOTED = "PROMOTED"
    CANCELLED = "CANCELLED"


class SessionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    VOIDED = "VOIDED"


class SessionKind(str, Enum):
    PERMIT = "PERMIT"
    TRANSIENT = "TRANSIENT"


class DiscountKind(str, Enum):
    FLAT_CENTS = "FLAT_CENTS"
    PERCENT = "PERCENT"
    FREE_HOURS = "FREE_HOURS"


class ValidationStatus(str, Enum):
    ISSUED = "ISSUED"
    REDEEMED = "REDEEMED"


class ViolationCode(str, Enum):
    NO_PERMIT = "NO_PERMIT"
    EXPIRED_PERMIT = "EXPIRED_PERMIT"
    WRONG_ZONE = "WRONG_ZONE"
    OVERSTAY = "OVERSTAY"


class CitationStatus(str, Enum):
    ISSUED = "ISSUED"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"
    PAID = "PAID"


class AppealStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


class EnforcementOutcome(str, Enum):
    COMPLIANT = "COMPLIANT"
    VIOLATION_NO_PERMIT = "VIOLATION_NO_PERMIT"
    VIOLATION_EXPIRED_PERMIT = "VIOLATION_EXPIRED_PERMIT"
    VIOLATION_WRONG_ZONE = "VIOLATION_WRONG_ZONE"


# ---------------------------------------------------------------------------
# Entity TypedDicts (common_fields: true unless noted)
# ---------------------------------------------------------------------------
class Garage(TypedDict):
    id: str
    name: str
    timezone: str
    total_space_count: int
    occupied_count: int
    gate_mode: str
    created_at: str
    updated_at: str
    version: int


class Zone(TypedDict):
    id: str
    garage_id: str
    code: str
    zone_type: str
    permit_capacity: int
    permits_active_count: int
    rate_plan_id: str
    created_at: str
    updated_at: str
    version: int


class Space(TypedDict):
    id: str
    zone_id: str
    label: str
    status: str
    is_occupied: bool
    created_at: str
    updated_at: str
    version: int


class RatePlan(TypedDict):
    id: str
    name: str
    hourly_cents: int
    daily_cap_cents: int
    monthly_permit_cents: int
    grace_minutes: int
    created_at: str
    updated_at: str
    version: int


class EventPricing(TypedDict):
    id: str
    garage_id: str
    name: str
    window_start_utc: str
    window_end_utc: str
    flat_surcharge_cents: int
    multiplier: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    zone_id: str
    motorist_id: str
    plate: str
    status: str
    valid_from_utc: Optional[str]
    valid_until_utc: Optional[str]
    monthly_fee_charged_cents: int
    created_at: str
    updated_at: str
    version: int


class PermitWaitlistEntry(TypedDict):
    id: str
    zone_id: str
    motorist_id: str
    plate: str
    status: str
    sequence: int
    promoted_permit_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Motorist(TypedDict):
    id: str
    full_name: str
    email: str
    default_plate: str
    outstanding_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class AccessSession(TypedDict):
    id: str
    garage_id: str
    space_id: Optional[str]
    permit_id: Optional[str]
    plate: str
    entry_at_utc: str
    exit_at_utc: Optional[str]
    status: str
    session_kind: str
    gross_charge_cents: int
    validation_id: Optional[str]
    net_charge_cents: int
    created_at: str
    updated_at: str
    version: int


class Validation(TypedDict):
    id: str
    garage_id: str
    merchant_id: str
    discount_kind: str
    discount_value: int
    status: str
    expires_at_utc: str
    created_at: str
    updated_at: str
    version: int


class Merchant(TypedDict):
    id: str
    garage_id: str
    name: str
    validation_budget_cents: int
    created_at: str
    updated_at: str
    version: int


class Citation(TypedDict):
    id: str
    garage_id: str
    plate: str
    motorist_id: Optional[str]
    plate_read_id: str
    violation_code: str
    base_fine_cents: int
    amount_due_cents: int
    prior_citation_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    citation_id: str
    motorist_id: str
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, carries ONLY id + created_at.
class PlateRead(TypedDict):
    id: str
    garage_id: str
    plate: str
    zone_id: str
    read_at_utc: str
    enforcement_outcome: str
    matched_permit_id: Optional[str]
    created_at: str
