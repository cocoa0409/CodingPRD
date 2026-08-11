"""Domain types: entity TypedDicts, status enums, role enum.

PRD references: common fields in PRD section "Common Resource Properties";
MedAdminEvent is the single append-only exception carrying only id and
created_at.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class HomeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class CompliancePosture(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    PROVISIONAL = "PROVISIONAL"
    CRITICAL = "CRITICAL"


class IndividualStatus(str, Enum):
    APPLICANT = "APPLICANT"
    ENROLLED = "ENROLLED"
    DISCHARGED = "DISCHARGED"


class MobilityLevel(str, Enum):
    AMBULATORY = "AMBULATORY"
    ASSIST = "ASSIST"
    WHEELCHAIR = "WHEELCHAIR"


class ISPStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    AMENDMENT_DRAFT = "AMENDMENT_DRAFT"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    DISCONTINUED = "DISCONTINUED"


class ServiceCode(str, Enum):
    RES_HAB = "RES_HAB"
    DAY_PROG = "DAY_PROG"
    RESPITE = "RESPITE"
    SUPPORTED_EMPLOYMENT = "SUPPORTED_EMPLOYMENT"


class UnitType(str, Enum):
    FIFTEEN_MIN = "FIFTEEN_MIN"
    DAY = "DAY"


class AuthorizationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class StaffRole(str, Enum):
    DSP = "DSP"
    CASE_MANAGER = "CASE_MANAGER"
    QIDP = "QIDP"


class StaffStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class ShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ShiftType(str, Enum):
    DAY = "DAY"
    NIGHT = "NIGHT"


class BedAssignmentStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"


class MedicationOrderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class MedOutcome(str, Enum):
    GIVEN = "GIVEN"
    REFUSED = "REFUSED"
    HELD = "HELD"
    MISSED = "MISSED"


class BSPLevel(str, Enum):
    LEVEL_1 = "LEVEL_1"
    LEVEL_2 = "LEVEL_2"


class BSPStatus(str, Enum):
    DRAFT = "DRAFT"
    HRC_REVIEW = "HRC_REVIEW"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class IncidentCategory(str, Enum):
    MED_ERROR = "MED_ERROR"
    INJURY = "INJURY"
    ABUSE_ALLEGATION = "ABUSE_ALLEGATION"
    BEHAVIOR = "BEHAVIOR"
    ELOPEMENT = "ELOPEMENT"


class IncidentSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IncidentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_INFO = "NEEDS_INFO"
    CLOSED = "CLOSED"


class VerificationStatus(str, Enum):
    PENDING = "PENDING"
    EXCEPTION = "EXCEPTION"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    BILLED = "BILLED"


class TransportTripStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    DENIED = "DENIED"
    CORRECTED = "CORRECTED"
    PAID = "PAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    HOLD = "HOLD"
    VOIDED = "VOIDED"


class UserRole(str, Enum):
    AGENCY_ADMIN = "AgencyAdmin"
    CASE_MANAGER = "CaseManager"
    QIDP = "QIDP"
    DSP = "DSP"
    BILLING_SPECIALIST = "BillingSpecialist"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    ANY = "Any"


class Certification(str, Enum):
    MED_CERT = "MED_CERT"
    BEHAVIOR_CERT = "BEHAVIOR_CERT"
    CPR = "CPR"
    CDL = "CDL"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class ProviderAgency(TypedDict, total=False):
    id: str
    name: str
    day_staff_ratio: int
    night_staff_ratio: int
    evv_grace_minutes: int
    cash_collected_cents: int
    recoupment_balance_cents: int
    held_claims_count: int
    created_at: str
    updated_at: str
    version: int


class GroupHome(TypedDict, total=False):
    id: str
    agency_id: str
    name: str
    license_number: str
    certified_bed_count: int
    status: str
    compliance_posture: str
    current_occupancy: int
    created_at: str
    updated_at: str
    version: int


class Individual(TypedDict, total=False):
    id: str
    agency_id: str
    legal_name: str
    medicaid_id: str
    date_of_birth: str
    mobility_level: str
    status: str
    enrolled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ISP(TypedDict, total=False):
    id: str
    individual_id: str
    authored_by_staff_id: str
    plan_year_start: str
    plan_year_end: str
    goals_summary: str
    meeting_date: Optional[str]
    status: str
    amendment_count: int
    activated_at: Optional[str]
    approved_by_staff_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceAuthorization(TypedDict, total=False):
    id: str
    individual_id: str
    isp_id: str
    service_code: str
    unit_type: str
    authorized_units: int
    rate_cents: int
    span_start: str
    span_end: str
    consumed_units: int
    remaining_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict, total=False):
    id: str
    agency_id: str
    full_name: str
    staff_role: str
    certifications: List[str]
    hire_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ShiftAssignment(TypedDict, total=False):
    id: str
    home_id: str
    staff_member_id: str
    window_start: str
    window_end: str
    shift_type: str
    requires_med_pass: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class BedAssignment(TypedDict, total=False):
    id: str
    home_id: str
    bed_label: str
    individual_id: str
    move_in_date: str
    move_out_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MedicationOrder(TypedDict, total=False):
    id: str
    individual_id: str
    drug_name: str
    dosage: str
    schedule_times: List[str]
    requires_witness: bool
    start_date: str
    end_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MedAdminEvent(TypedDict, total=False):
    # Append-only MAR event: id + created_at ONLY; no updated_at, no version.
    id: str
    created_at: str
    medication_order_id: str
    administered_by_staff_id: str
    witness_staff_id: Optional[str]
    scheduled_time: str
    administered_time: Optional[str]
    outcome: str


class BehaviorSupportPlan(TypedDict, total=False):
    id: str
    individual_id: str
    authored_by_staff_id: str
    level: str
    restrictive_interventions: List[str]
    status: str
    approved_at: Optional[str]
    review_due_at: Optional[str]
    approved_by_staff_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict, total=False):
    id: str
    individual_id: str
    home_id: str
    submitted_by_staff_id: str
    category: str
    severity: str
    occurred_at: str
    discovered_at: str
    description: str
    status: str
    report_due_at: Optional[str]
    submitted_at: Optional[str]
    is_late: bool
    created_at: str
    updated_at: str
    version: int


class AllocatedUnitsEntry(TypedDict, total=False):
    authorization_id: str
    units: int


class EVVVisit(TypedDict, total=False):
    id: str
    individual_id: str
    authorization_id: str
    staff_member_id: str
    shift_id: Optional[str]
    service_date: str
    check_in_at: str
    check_out_at: str
    geo_within_radius: bool
    provisional_units: int
    final_units: Optional[int]
    verification_status: str
    billing_status: str
    billed_claim_id: Optional[str]
    allocated_units_entries: List[AllocatedUnitsEntry]
    created_at: str
    updated_at: str
    version: int


class TransportLeg(TypedDict, total=False):
    individual_id: str
    wheelchair_seat: bool
    pickup_at: str
    dropoff_at: str


class TransportTrip(TypedDict, total=False):
    id: str
    home_id: str
    vehicle_id: str
    trip_date: str
    depart_at: str
    return_at: str
    legs: List[TransportLeg]
    occupied_slots: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ClaimLine(TypedDict, total=False):
    authorization_id: str
    service_code: str
    units: int
    rate_cents: int
    amount_cents: int


class BillingClaim(TypedDict, total=False):
    id: str
    individual_id: str
    service_period_start: str
    service_period_end: str
    lines: List[ClaimLine]
    total_units: int
    total_amount_cents: int
    paid_amount_cents: Optional[int]
    posted_net_cents: Optional[int]
    submitted_by_user_id: Optional[str]
    submitted_at: Optional[str]
    denial_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
