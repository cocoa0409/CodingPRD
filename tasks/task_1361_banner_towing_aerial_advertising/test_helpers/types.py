"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entity model. WeatherAssessment and ProofOfFlight are
immutable evidentiary records: they carry only id + created_at (no updated_at,
no version) per PRD §2.4.
"""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CLIENT = "Client"
    DISPATCHER = "Dispatcher"
    PILOT = "Pilot"
    GROUND_CREW_LEAD = "GroundCrewLead"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    FINANCE_OFFICER = "FinanceOfficer"


# ---------------------------------------------------------------------------
# Status / enum declarations (PRD §3)
# ---------------------------------------------------------------------------

class BaseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class AircraftModel(str, Enum):
    CITABRIA = "CITABRIA"
    SUPER_CUB = "SUPER_CUB"
    PAWNEE = "PAWNEE"


class AircraftStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"


class TowEndorsementLevel(str, Enum):
    TRAINEE = "TRAINEE"
    STANDARD = "STANDARD"
    STADIUM_QUALIFIED = "STADIUM_QUALIFIED"


class PilotStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    INACTIVE = "INACTIVE"


class RouteKind(str, Enum):
    BEACH = "BEACH"
    STADIUM = "STADIUM"
    FESTIVAL = "FESTIVAL"
    PARADE = "PARADE"


class RouteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    BOOKED = "BOOKED"
    IN_FLIGHT = "IN_FLIGHT"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class AirspaceApprovalStatus(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class TFRStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    CANCELLED = "CANCELLED"


class BannerStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_FABRICATION = "IN_FABRICATION"
    READY = "READY"
    RETIRED = "RETIRED"


class BannerRevisionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"


class FlightSlotStatus(str, Enum):
    DRAFT = "DRAFT"
    BOOKED = "BOOKED"
    SCHEDULED = "SCHEDULED"
    WEATHER_HOLD = "WEATHER_HOLD"
    FLOWN = "FLOWN"
    CANCELLED_CLIENT = "CANCELLED_CLIENT"
    CANCELLED_WEATHER = "CANCELLED_WEATHER"
    CANCELLED_TFR = "CANCELLED_TFR"


class WeatherVerdict(str, Enum):
    GO = "GO"
    MARGINAL = "MARGINAL"
    NO_GO = "NO_GO"


class PickupTechnique(str, Enum):
    GROUND_PICKUP = "GROUND_PICKUP"
    AERIAL_PICKUP = "AERIAL_PICKUP"


class PickupOutcome(str, Enum):
    CLEAN = "CLEAN"
    RETRIED = "RETRIED"
    FAILED = "FAILED"


class MakeGoodCreditStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_APPLIED = "PARTIALLY_APPLIED"
    FULLY_APPLIED = "FULLY_APPLIED"
    EXPIRED = "EXPIRED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


# ---------------------------------------------------------------------------
# Entity TypedDicts — common_fields entities carry id, created_at,
# updated_at, version (PRD §2.4)
# ---------------------------------------------------------------------------

class Base(TypedDict):
    id: str
    code: str
    name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Aircraft(TypedDict):
    id: str
    base_id: str
    tail_number: str
    model: str
    max_tow_weight_lbs: int
    hourly_rate_cents: int
    status: str
    season_hours_flown: float
    created_at: str
    updated_at: str
    version: int


class Pilot(TypedDict):
    id: str
    base_id: str
    full_name: str
    certificate_number: str
    tow_endorsement_level: str
    status: str
    season_hours_flown: float
    season_pickup_failure_count: int
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict):
    id: str
    code: str
    kind: str
    base_id: str
    length_nm: float
    min_banner_length_ft: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict):
    id: str
    legal_name: str
    billing_email: str
    credit_hold: bool
    outstanding_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Campaign(TypedDict):
    id: str
    client_id: str
    name: str
    status: str
    booked_flight_count: int
    flown_flight_count: int
    cancelled_weather_count: int
    unapplied_make_good_cents: int
    created_at: str
    updated_at: str
    version: int


class AirspaceApproval(TypedDict):
    id: str
    route_id: str
    date_local: str
    window_start_utc: str
    window_end_utc: str
    stadium_tfr_waiver: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class TFRRestriction(TypedDict):
    id: str
    route_id: str
    starts_utc: str
    ends_utc: str
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Banner(TypedDict):
    id: str
    campaign_id: str
    artwork_hash: str
    text_message: str
    banner_length_ft: int
    banner_weight_lbs: int
    current_revision_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BannerRevision(TypedDict):
    id: str
    banner_id: str
    revision_seq: int
    proposed_text: str
    proposed_artwork_hash: str
    supersedes_revision_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SeasonalCapacity(TypedDict):
    id: str
    base_id: str
    month_yyyy_mm: str
    aircraft_hour_quota: int
    hours_committed: int
    hours_remaining: int
    created_at: str
    updated_at: str
    version: int


class FlightSlot(TypedDict):
    id: str
    campaign_id: str
    route_id: str
    airspace_approval_id: str
    banner_id: str
    date_local: str
    planned_start_utc: str
    planned_duration_hours: int
    assigned_aircraft_id: Optional[str]
    assigned_pilot_id: Optional[str]
    supersedes_slot_id: Optional[str]
    consumed_make_good_credit_id: Optional[str]
    status: str
    weather_hold_count: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable evidentiary record, id + created_at only
class WeatherAssessment(TypedDict):
    id: str
    slot_id: str
    assessed_at_utc: str
    ceiling_ft: int
    visibility_sm: float
    wind_kts: int
    verdict: str
    assessed_by_pilot_id: str
    created_at: str


class FlightLog(TypedDict):
    id: str
    slot_id: str
    aircraft_id: str
    pilot_id: str
    hobbs_out: float
    hobbs_in: float
    hobbs_hours: float
    pickup_technique: str
    pickup_outcome: str
    tow_field_notes: str
    filed_at_utc: str
    created_at: str
    updated_at: str
    version: int


class MakeGoodCredit(TypedDict):
    id: str
    campaign_id: str
    source_slot_id: str
    original_cents: int
    remaining_cents: int
    expires_on_local: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable evidentiary record, id + created_at only
class ProofOfFlight(TypedDict):
    id: str
    slot_id: str
    gps_track_digest: str
    photo_hash: str
    pilot_attestation: bool
    submitted_at_utc: str
    finalized: bool
    created_at: str


class Invoice(TypedDict):
    id: str
    campaign_id: str
    period_yyyy_mm: str
    flight_subtotal_cents: int
    cancellation_penalty_cents: int
    make_good_applied_cents: int
    total_cents: int
    balance_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
