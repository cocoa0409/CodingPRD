"""Domain types for the Residential Parking Permit Zone API.

Entity TypedDicts, status enums, and the role enum. Every entity in this
domain carries the common fields id, created_at, updated_at, and version.
Generic envelope types live in the framework and are not redefined here.
"""
from enum import Enum
from typing import TypedDict, Optional


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    RESIDENT = "Resident"
    PARKING_CLERK = "ParkingClerk"
    PERMIT_SUPERVISOR = "PermitSupervisor"
    ENFORCEMENT_OFFICER = "EnforcementOfficer"
    ANONYMOUS = "Anonymous"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class ZoneStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class HouseholdStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ProofStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    EXPIRED = "EXPIRED"


class VehicleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class ProofSubmissionStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class PermitApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    WAITLISTED = "WAITLISTED"
    DENIED = "DENIED"


class PermitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RENEWAL_PENDING = "RENEWAL_PENDING"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    TRANSFERRED = "TRANSFERRED"
    REFUNDED = "REFUNDED"


class VisitorPassStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class PassType(str, Enum):
    GUEST_DAILY = "GUEST_DAILY"
    TEMPORARY = "TEMPORARY"


class WaitlistEntryStatus(str, Enum):
    WAITING = "WAITING"
    PROMOTED = "PROMOTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class CitationStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


class ViolationType(str, Enum):
    NO_PERMIT = "NO_PERMIT"
    EXPIRED_PERMIT = "EXPIRED_PERMIT"
    ZONE_VIOLATION = "ZONE_VIOLATION"


class FineVariant(str, Enum):
    STANDARD = "STANDARD"
    REPEAT_OFFENDER = "REPEAT_OFFENDER"


class RefundType(str, Enum):
    VOLUNTARY = "VOLUNTARY"
    ADMINISTRATIVE = "ADMINISTRATIVE"


class DocumentType(str, Enum):
    LEASE = "LEASE"
    UTILITY_BILL = "UTILITY_BILL"
    DEED = "DEED"
    ID_CARD = "ID_CARD"


class ComplaintStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"
    ESCALATED = "ESCALATED"


class ComplaintType(str, Enum):
    ILLEGAL_PARKING = "ILLEGAL_PARKING"
    PERMIT_ABUSE = "PERMIT_ABUSE"
    SIGNAGE = "SIGNAGE"
    OTHER = "OTHER"


# --------------------------------------------------------------------------
# Entity TypedDicts (all carry id/created_at/updated_at/version)
# --------------------------------------------------------------------------
class Zone(TypedDict):
    id: str
    name: str
    zone_code: str
    permit_capacity: int
    max_permits_per_household: int
    guest_pass_daily_limit: int
    permit_annual_fee_cents: int
    visitor_pass_fee_cents: int
    status: str
    active_permit_count: int
    waitlist_count: int
    fees_collected_cents: int
    fees_refunded_cents: int
    created_at: str
    updated_at: str
    version: int


class Household(TypedDict):
    id: str
    zone_id: str
    unit_address: str
    resident_name: str
    contact_email: str
    status: str
    proof_status: str
    proof_verified_at: Optional[str]
    proof_expires_at: Optional[str]
    active_permit_count: int
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    household_id: str
    license_plate: str
    make: str
    model: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ProofSubmission(TypedDict):
    id: str
    household_id: str
    document_type: str
    status: str
    reviewer_user_id: Optional[str]
    verified_at: Optional[str]
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PermitApplication(TypedDict):
    id: str
    zone_id: str
    household_id: str
    vehicle_id: str
    status: str
    reviewer_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    denial_reason: Optional[str]
    permit_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    application_id: str
    zone_id: str
    household_id: str
    vehicle_id: str
    permit_number: str
    license_plate: str
    status: str
    issued_at: str
    expires_at: str
    fee_paid_cents: int
    refund_amount_cents: int
    refund_type: Optional[str]
    upheld_citation_count: int
    transferred_to_permit_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VisitorPass(TypedDict):
    id: str
    household_id: str
    permit_id: str
    pass_type: str
    guest_plate: str
    valid_from: str
    valid_until: str
    status: str
    fee_charged_cents: int
    created_at: str
    updated_at: str
    version: int


class WaitlistEntry(TypedDict):
    id: str
    zone_id: str
    application_id: str
    household_id: str
    position: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Citation(TypedDict):
    id: str
    zone_id: str
    permit_id: Optional[str]
    license_plate: str
    violation_type: str
    fine_amount_cents: int
    fine_variant: str
    prior_upheld_count: int
    status: str
    issuing_officer_id: str
    adjudicator_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict):
    id: str
    zone_id: str
    complaint_type: str
    target_plate: Optional[str]
    description: str
    status: str
    resolution_note: Optional[str]
    created_citation_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
