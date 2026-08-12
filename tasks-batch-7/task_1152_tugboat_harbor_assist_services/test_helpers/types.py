"""Domain types: entity TypedDicts, status enums, role enum for the Tugboat Harbor Assist API."""
from enum import Enum
from typing import TypedDict, Optional


# ─── Status / enum types ──────────────────────────────


class TugOperationalStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESTRICTED = "RESTRICTED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class LicenseClass(str, Enum):
    CLASS_I = "CLASS_I"
    CLASS_II = "CLASS_II"
    CLASS_III = "CLASS_III"


class CrewRole(str, Enum):
    CAPTAIN = "CAPTAIN"
    MATE = "MATE"
    ENGINEER = "ENGINEER"
    DECKHAND = "DECKHAND"


class ManeuverType(str, Enum):
    DOCKING = "DOCKING"
    UNDOCKING = "UNDOCKING"
    SHIFTING = "SHIFTING"
    ESCORT = "ESCORT"
    TOWAGE = "TOWAGE"


class JobOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    DISPATCHED = "DISPATCHED"
    ON_HOLD = "ON_HOLD"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    INVOICED = "INVOICED"
    CANCELLED = "CANCELLED"


class TugAssignmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    SUPERSEDED = "SUPERSEDED"


class PilotBookingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    BOARDED = "BOARDED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class InspectionItem(str, Enum):
    TOWING_HOOK = "TOWING_HOOK"
    TOW_LINE = "TOW_LINE"
    WINCH = "WINCH"
    BITTS = "BITTS"


class InspectionOutcome(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"


class IncidentType(str, Enum):
    GEAR_FAILURE = "GEAR_FAILURE"
    CONTACT_DAMAGE = "CONTACT_DAMAGE"
    POLLUTION = "POLLUTION"
    PERSONAL_INJURY = "PERSONAL_INJURY"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    RESOLVED = "RESOLVED"


class RestrictionType(str, Enum):
    WIND = "WIND"
    CURRENT = "CURRENT"
    VISIBILITY = "VISIBILITY"


class WeatherRestrictionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"


class InvoiceStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    VOID = "VOID"


class InvoiceVariantBasis(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTUAL = "ACTUAL"


class LiabilityVariant(str, Enum):
    PER_INCIDENT = "PER_INCIDENT"
    PER_VOYAGE = "PER_VOYAGE"


class DamageClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ACCEPTED = "ACCEPTED"
    DENIED = "DENIED"
    SETTLED = "SETTLED"


class UserRole(str, Enum):
    PORT_ADMIN = "PortAdmin"
    VESSEL_AGENT = "VesselAgent"
    PORT_DISPATCHER = "PortDispatcher"
    PILOT = "Pilot"
    TUG_CAPTAIN = "TugCaptain"
    MARINE_SURVEYOR = "MarineSurveyor"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"


# ─── Entity TypedDicts ────────────────────────────────
# Entities carrying common_fields have id, created_at, updated_at, version.
# GearInspection (append-only log) carries only id and created_at.


class Vessel(TypedDict, total=False):
    id: str
    name: str
    imo_number: str
    deadweight_tonnage: int
    loa_meters: float
    outstanding_billed_cents: int
    created_at: str
    updated_at: str
    version: int


class Tug(TypedDict, total=False):
    id: str
    name: str
    bollard_pull_tons: float
    horsepower: int
    hourly_rate_cents: int
    insured_value_cents: int
    home_port: Optional[str]
    operational_status: str
    created_at: str
    updated_at: str
    version: int


class Pilot(TypedDict, total=False):
    id: str
    name: str
    license_class: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class CrewMember(TypedDict, total=False):
    id: str
    full_name: str
    crew_role: str
    max_watch_hours: int
    created_at: str
    updated_at: str
    version: int


class TariffRate(TypedDict, total=False):
    id: str
    tariff_code: str
    maneuver_type: str
    base_fee_cents: int
    free_standby_minutes: int
    standby_block_minutes: int
    standby_block_rate_cents: int
    weather_surcharge_pct: float
    effective_from: str
    effective_to: str
    created_at: str
    updated_at: str
    version: int


class JobOrder(TypedDict, total=False):
    id: str
    vessel_id: str
    tariff_rate_id: str
    maneuver_type: str
    scheduled_start: str
    scheduled_end: str
    required_bollard_pull_tons: float
    actual_start: Optional[str]
    actual_end: Optional[str]
    had_weather_hold: bool
    needs_reassignment: bool
    cancel_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TugAssignment(TypedDict, total=False):
    id: str
    job_order_id: str
    tug_id: str
    window_start: str
    window_end: str
    participated: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class PilotBooking(TypedDict, total=False):
    id: str
    job_order_id: str
    pilot_id: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WatchRotation(TypedDict, total=False):
    id: str
    tug_assignment_id: str
    crew_member_id: str
    watch_start: str
    watch_end: str
    created_at: str
    updated_at: str
    version: int


class GearInspection(TypedDict, total=False):
    # Append-only log entry — carries only id and created_at, no updated_at, no version.
    id: str
    tug_id: str
    inspection_item: str
    outcome: str
    inspected_at: str
    next_due_at: str
    deficiency_notes: Optional[str]
    created_at: str


class Incident(TypedDict, total=False):
    id: str
    tug_id: str
    job_order_id: Optional[str]
    incident_type: str
    severity: str
    occurred_at: str
    description: str
    resolution_notes: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WeatherRestriction(TypedDict, total=False):
    id: str
    restriction_type: str
    threshold_value: float
    port_area: str
    effective_start: str
    effective_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    job_order_id: str
    status: str
    variant_basis: str
    base_fee_cents: int
    tug_hire_cents: int
    standby_minutes: int
    standby_cents: int
    weather_surcharge_cents: int
    total_cents: int
    created_at: str
    updated_at: str
    version: int


class DamageClaim(TypedDict, total=False):
    id: str
    incident_id: str
    vessel_id: str
    claimed_amount_cents: int
    liability_variant: str
    liability_cap_cents: int
    deductible_cents: int
    payout_cents: int
    reviewer_notes: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
