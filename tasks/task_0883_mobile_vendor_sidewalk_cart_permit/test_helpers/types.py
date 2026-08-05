"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this API carry the common fields id, created_at, updated_at, and
version (Section 2.4 of the PRD), so every TypedDict below lists them.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------- #
# Roles
# --------------------------------------------------------------------------- #
class UserRole(str, Enum):
    VENDOR = "Vendor"
    PERMIT_OFFICER = "PermitOfficer"
    HEALTH_INSPECTOR = "HealthInspector"
    ENFORCEMENT_OFFICER = "EnforcementOfficer"
    RESIDENT = "Resident"


# --------------------------------------------------------------------------- #
# Status enums
# --------------------------------------------------------------------------- #
class VendorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class InsuranceStatus(str, Enum):
    NONE = "NONE"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"


class CommissaryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CartStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    IMPOUNDED = "IMPOUNDED"
    RETIRED = "RETIRED"


class InspectionStatus(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


class ZoneStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ZoneType(str, Enum):
    PRIME = "PRIME"
    STANDARD = "STANDARD"


class SpotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    BLOCKED = "BLOCKED"


class PermitStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ISSUED = "ISSUED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class FeeVariant(str, Enum):
    NEW = "NEW"
    RENEWAL_EARLY = "RENEWAL_EARLY"
    RENEWAL_LATE = "RENEWAL_LATE"


class LotteryStatus(str, Enum):
    OPEN = "OPEN"
    DRAWN = "DRAWN"


class LotteryEntryStatus(str, Enum):
    ENTERED = "ENTERED"
    AWARDED = "AWARDED"
    WAITLISTED = "WAITLISTED"


class SpotAssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class ViolationStatus(str, Enum):
    ISSUED = "ISSUED"
    CONTESTED = "CONTESTED"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


class ImpoundStatus(str, Enum):
    HELD = "HELD"
    RELEASED = "RELEASED"
    FORFEITED = "FORFEITED"


class ComplaintStatus(str, Enum):
    OPEN = "OPEN"
    SUBSTANTIATED = "SUBSTANTIATED"
    UNFOUNDED = "UNFOUNDED"


# --------------------------------------------------------------------------- #
# Entity TypedDicts (all common_fields: true)
# --------------------------------------------------------------------------- #
class Vendor(TypedDict):
    id: str
    legal_name: str
    contact_email: str
    seniority_years: int
    status: str
    insurance_effective_at: Optional[str]
    insurance_expires_at: Optional[str]
    insurance_coverage_cents: int
    insurance_status: str
    total_charged_cents: int
    total_credited_cents: int
    balance_owed_cents: int
    compliance_score: int
    created_at: str
    updated_at: str
    version: int


class Commissary(TypedDict):
    id: str
    name: str
    health_grade: str
    license_expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Cart(TypedDict):
    id: str
    vendor_id: str
    commissary_id: str
    cart_type: str
    size_sqft: int
    inspection_status: str
    inspection_score: Optional[int]
    inspection_expires_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Zone(TypedDict):
    id: str
    name: str
    zone_type: str
    capacity_slots: int
    spacing_min_feet: int
    assigned_slots: int
    available_slots: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Spot(TypedDict):
    id: str
    zone_id: str
    label: str
    position_feet: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    vendor_id: str
    cart_id: str
    zone_id: str
    permit_type: str
    status: str
    fee_variant: Optional[str]
    fee_amount_cents: Optional[int]
    issued_at: Optional[str]
    expires_at: Optional[str]
    violation_points: int
    created_at: str
    updated_at: str
    version: int


class Lottery(TypedDict):
    id: str
    zone_id: str
    entry_fee_cents: int
    term_start_at: str
    term_end_at: str
    status: str
    awarded_count: int
    created_at: str
    updated_at: str
    version: int


class LotteryEntry(TypedDict):
    id: str
    lottery_id: str
    permit_id: str
    preferred_spot_ids: List[str]
    rank_score: Optional[int]
    awarded_spot_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SpotAssignment(TypedDict):
    id: str
    spot_id: str
    permit_id: str
    zone_id: str
    position_feet: int
    start_at: str
    end_at: str
    origin: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Violation(TypedDict):
    id: str
    permit_id: str
    violation_type: str
    description: str
    points: int
    fine_cents: int
    issuer_user_id: str
    source_complaint_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Impound(TypedDict):
    id: str
    cart_id: str
    reason: str
    impounded_at: str
    settled_at: Optional[str]
    storage_days: Optional[int]
    settlement_variant: Optional[str]
    release_fee_cents: Optional[int]
    municipal_writeoff_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict):
    id: str
    permit_id: str
    complaint_type: str
    description: str
    resolution: Optional[str]
    generated_violation_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
