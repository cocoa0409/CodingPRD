"""Domain types: entity TypedDicts, status enums, role enum for the Blood Donation Center API.

Every entity in this domain carries the full common-field quartet
(id, created_at, updated_at, version) — the PRD states there are no
immutable-after-creation entities here.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ───────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    CENTER_ADMIN = "CenterAdmin"
    INTAKE_NURSE = "IntakeNurse"
    LAB_TECHNICIAN = "LabTechnician"
    INVENTORY_MANAGER = "InventoryManager"
    DONOR = "Donor"


# ─── Enums for entity fields ─────────────────────────────────────────────────
class BloodType(str, Enum):
    O_NEG = "O_NEG"
    O_POS = "O_POS"
    A_NEG = "A_NEG"
    A_POS = "A_POS"
    B_NEG = "B_NEG"
    B_POS = "B_POS"
    AB_NEG = "AB_NEG"
    AB_POS = "AB_POS"
    UNKNOWN = "UNKNOWN"


class EligibilityStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    TEMP_DEFERRED = "TEMP_DEFERRED"
    PERM_DEFERRED = "PERM_DEFERRED"
    UNDERAGE = "UNDERAGE"


class PendingDonationType(str, Enum):
    WHOLE = "WHOLE"
    PLASMA = "PLASMA"
    PLATELET = "PLATELET"
    NONE = "NONE"


class DeferralCategory(str, Enum):
    TRAVEL = "TRAVEL"
    MEDICATION = "MEDICATION"
    HEMOGLOBIN = "HEMOGLOBIN"
    ADVERSE_REACTION = "ADVERSE_REACTION"
    INFECTIOUS_RISK = "INFECTIOUS_RISK"


class DeferralKind(str, Enum):
    TEMPORARY = "TEMPORARY"
    PERMANENT = "PERMANENT"


class DeferralStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    LIFTED = "LIFTED"


class DonationType(str, Enum):
    WHOLE = "WHOLE"
    PLASMA = "PLASMA"
    PLATELET = "PLATELET"


class SlotStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"
    CLOSED = "CLOSED"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class ScreeningOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ScreeningFailureReason(str, Enum):
    NONE = "NONE"
    HEMOGLOBIN_LOW = "HEMOGLOBIN_LOW"
    UNDERWEIGHT = "UNDERWEIGHT"
    VITALS_OUT_OF_RANGE = "VITALS_OUT_OF_RANGE"
    TRAVEL_RISK = "TRAVEL_RISK"
    MEDICATION = "MEDICATION"


class DonationStatus(str, Enum):
    COLLECTED = "COLLECTED"
    RELEASABLE = "RELEASABLE"
    DISCARDED = "DISCARDED"


class PanelOutcome(str, Enum):
    NEGATIVE = "NEGATIVE"
    POSITIVE = "POSITIVE"
    INDETERMINATE = "INDETERMINATE"


class Component(str, Enum):
    RBC = "RBC"
    PLASMA = "PLASMA"
    PLATELET = "PLATELET"
    WHOLE_BLOOD = "WHOLE_BLOOD"


class UnitStatus(str, Enum):
    QUARANTINED = "QUARANTINED"
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    ISSUED = "ISSUED"
    EXPIRED = "EXPIRED"
    DISCARDED = "DISCARDED"
    RECALLED = "RECALLED"


class ReactionSeverity(str, Enum):
    MILD = "MILD"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class RecallReason(str, Enum):
    POSITIVE_RETEST = "POSITIVE_RETEST"
    POST_DONATION_ILLNESS = "POST_DONATION_ILLNESS"
    TRAVEL_DISCLOSURE = "TRAVEL_DISCLOSURE"
    OTHER = "OTHER"


class RecallStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


# ─── Entity TypedDicts (all carry id + created_at + updated_at + version) ─────
class DonationCenter(TypedDict):
    id: str
    name: str
    region_code: str
    current_utc: str
    created_at: str
    updated_at: str
    version: int


class Donor(TypedDict):
    id: str
    center_id: str
    full_name: str
    date_of_birth: str
    weight_kg: float
    blood_type: str
    eligibility_status: str
    last_qualifying_donation_id: Optional[str]
    pending_donation_type: str
    lifetime_collected_count: int
    created_at: str
    updated_at: str
    version: int


class Deferral(TypedDict):
    id: str
    donor_id: str
    center_id: str
    category: str
    kind: str
    reason: str
    starts_at: str
    expires_at: Optional[str]
    duration_days: Optional[int]
    status: str
    source_reaction_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AppointmentSlot(TypedDict):
    id: str
    center_id: str
    donation_type: str
    starts_at: str
    ends_at: str
    capacity: int
    booked_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    donor_id: str
    slot_id: str
    center_id: str
    donation_type: str
    status: str
    booked_at: str
    created_at: str
    updated_at: str
    version: int


class HealthScreening(TypedDict):
    id: str
    appointment_id: str
    donor_id: str
    hemoglobin_g_dl: float
    systolic_bp: int
    pulse_bpm: int
    weight_kg: float
    recent_travel_risk: bool
    disqualifying_medication: bool
    outcome: str
    failure_reason: str
    created_at: str
    updated_at: str
    version: int


class Donation(TypedDict):
    id: str
    appointment_id: str
    donor_id: str
    center_id: str
    donation_type: str
    volume_ml: int
    collected_at: str
    status: str
    test_result_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TestResult(TypedDict):
    id: str
    donation_id: str
    donor_id: str
    panel_outcome: str
    resulted_at: str
    created_at: str
    updated_at: str
    version: int


class BloodUnit(TypedDict):
    id: str
    donation_id: str
    donor_id: str
    center_id: str
    component: str
    blood_type: str
    din: str
    collected_at: str
    released_at: Optional[str]
    expires_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AdverseReaction(TypedDict):
    id: str
    donation_id: str
    donor_id: str
    severity: str
    symptom: str
    occurred_at: str
    triggered_deferral_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecallEvent(TypedDict):
    id: str
    center_id: str
    donor_id: str
    reason: str
    lookback_days: int
    units_recalled_count: int
    donations_in_scope_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InventoryBucket(TypedDict):
    id: str
    center_id: str
    blood_type: str
    component: str
    available_count: int
    reserved_count: int
    created_at: str
    updated_at: str
    version: int
