"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    NETWORK_MANAGER = "NetworkManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    REGULATOR = "Regulator"
    PROVIDER_REP = "ProviderRep"
    MEMBER = "Member"


class GeoClass(str, Enum):
    URBAN = "URBAN"
    SUBURBAN = "SUBURBAN"
    RURAL = "RURAL"


class Specialty(str, Enum):
    PRIMARY_CARE = "PRIMARY_CARE"
    CARDIOLOGY = "CARDIOLOGY"
    DERMATOLOGY = "DERMATOLOGY"
    BEHAVIORAL_HEALTH = "BEHAVIORAL_HEALTH"


class ProviderStatus(str, Enum):
    PENDING_LOAD = "PENDING_LOAD"
    EFFECTIVE = "EFFECTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class PanelStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ListingStatus(str, Enum):
    DRAFT = "DRAFT"
    LISTED = "LISTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    SUPPRESSED = "SUPPRESSED"
    REMOVED = "REMOVED"


class SuppressReason(str, Enum):
    NONE = "NONE"
    MANUAL = "MANUAL"
    ATTESTATION_FAILURE = "ATTESTATION_FAILURE"
    GHOST_CONFIRMED = "GHOST_CONFIRMED"
    PROVIDER_SUSPENDED = "PROVIDER_SUSPENDED"


class CycleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    OUTREACH = "OUTREACH"
    CLOSED = "CLOSED"


class RecordStatus(str, Enum):
    PENDING = "PENDING"
    ATTESTED = "ATTESTED"
    CORRECTION_REQUESTED = "CORRECTION_REQUESTED"
    NON_RESPONSIVE = "NON_RESPONSIVE"
    CANCELLED = "CANCELLED"


class ProbeStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RECORDED = "RECORDED"


class ProbeType(str, Enum):
    ROUTINE = "ROUTINE"
    URGENT = "URGENT"


class ProbeOutcome(str, Enum):
    KEPT = "KEPT"
    UNREACHABLE = "UNREACHABLE"
    NO_APPOINTMENT_OFFERED = "NO_APPOINTMENT_OFFERED"


class ProbeResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class EvaluationStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"


class OverallStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    DEFICIENT = "DEFICIENT"
    EXCUSED = "EXCUSED"


class DeficiencyStatus(str, Enum):
    OPEN = "OPEN"
    EXCUSED = "EXCUSED"
    CLOSED = "CLOSED"


class RequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SUPERSEDED = "SUPERSEDED"


class MemberStatus(str, Enum):
    ENROLLED = "ENROLLED"
    DISENROLLED = "DISENROLLED"


class ComplaintStatus(str, Enum):
    OPEN = "OPEN"
    CONFIRMED_ERROR = "CONFIRMED_ERROR"
    UNFOUNDED = "UNFOUNDED"
    CLOSED = "CLOSED"


class ComplaintErrorType(str, Enum):
    WRONG_PHONE = "WRONG_PHONE"
    WRONG_ADDRESS = "WRONG_ADDRESS"
    NOT_ACCEPTING = "NOT_ACCEPTING"
    NO_APPOINTMENT = "NO_APPOINTMENT"
    OTHER = "OTHER"


class CorrectionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


# --- Entity payloads (common_fields: id, created_at, updated_at, version) ---

class ServiceRegion(TypedDict, total=False):
    id: str
    county_fips: str
    name: str
    geo_class: str
    enrolled_member_count: int
    created_at: str
    updated_at: str
    version: int


class NetworkStandard(TypedDict, total=False):
    id: str
    specialty: str
    geo_class: str
    max_members_per_provider: int
    max_travel_minutes: int
    max_travel_miles: int
    max_wait_days_routine: int
    max_wait_days_urgent: int
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict, total=False):
    id: str
    npi: str
    legal_name: str
    specialty: str
    contract_effective_date: str
    status: str
    terminated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PracticeLocation(TypedDict, total=False):
    id: str
    provider_id: str
    region_id: str
    address_line: str
    panel_status: str
    avg_travel_minutes: int
    avg_travel_miles: int
    created_at: str
    updated_at: str
    version: int


class DirectoryListing(TypedDict, total=False):
    id: str
    provider_id: str
    location_id: str
    specialty: str
    display_name: str
    phone: str
    accepts_new_patients: bool
    office_hours_note: Optional[str]
    status: str
    suppress_reason: str
    ghost_strike_count: int
    has_confirmed_data_error: bool
    listed_at: Optional[str]
    suppressed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AttestationCycle(TypedDict, total=False):
    id: str
    cycle_label: str
    open_date: str
    due_date: str
    outreach_close_date: str
    status: str
    total_records: int
    pending_count: int
    responded_count: int
    non_responsive_count: int
    created_at: str
    updated_at: str
    version: int


class AttestationRecord(TypedDict, total=False):
    id: str
    cycle_id: str
    listing_id: str
    status: str
    outreach_attempts: int
    responded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AvailabilityProbe(TypedDict, total=False):
    id: str
    listing_id: str
    probe_type: str
    requested_date: str
    status: str
    outcome: Optional[str]
    offered_appointment_date: Optional[str]
    days_to_appointment: Optional[int]
    result: Optional[str]
    recorded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AdequacyEvaluation(TypedDict, total=False):
    id: str
    measurement_period: str
    period_start_date: str
    period_end_date: str
    status: str
    total_penalty_cents: int
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# RegionSpecialtyResult: immutable snapshot — id + created_at only (PRD §2.4).
class RegionSpecialtyResult(TypedDict, total=False):
    id: str
    evaluation_id: str
    region_id: str
    specialty: str
    member_count: int
    provider_count: int
    listing_count: int
    ratio_members_per_provider: Optional[float]
    ratio_ok: bool
    counted_location_count: int
    compliant_location_count: int
    time_distance_compliant: bool
    probed_listing_count: int
    mean_wait_days: Optional[float]
    p90_wait_days: Optional[float]
    wait_time_compliant: bool
    overall_status: str
    created_at: str


class DeficiencyRecord(TypedDict, total=False):
    id: str
    evaluation_id: str
    region_id: str
    specialty: str
    status: str
    opened_date: str
    closed_date: Optional[str]
    prior_closure_count: int
    accrual_window_start: str
    accrual_window_end: str
    last_accrual_cents: int
    accrued_penalty_cents: int
    reversed_penalty_cents: int
    outstanding_penalty_cents: int
    created_at: str
    updated_at: str
    version: int


class AccessPlanRequest(TypedDict, total=False):
    id: str
    deficiency_id: str
    remedy_summary: str
    excuse_start_date: str
    excuse_through_date: str
    status: str
    submission_seq: int
    decided_at: Optional[str]
    decision_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    region_id: str
    member_ref: str
    full_name: str
    enrolled_on: str
    status: str
    disenrolled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MemberComplaint(TypedDict, total=False):
    id: str
    member_id: str
    listing_id: str
    error_type: str
    error_observed_date: str
    description: str
    status: str
    filed_at: str
    confirmed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DirectoryCorrection(TypedDict, total=False):
    id: str
    listing_id: str
    complaint_id: Optional[str]
    changes: dict
    submitted_by_user_id: str
    sla_due_at: str
    is_late: bool
    status: str
    verified_at: Optional[str]
    verified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
