"""Domain types: entity TypedDicts, status enums, role enum for traveling exhibit tours."""
from enum import Enum
from typing import TypedDict, Optional, List, Any


class TourStatus(str, Enum):
    DRAFT = "DRAFT"
    BOOKING = "BOOKING"
    ON_TOUR = "ON_TOUR"
    IN_REFURBISHMENT = "IN_REFURBISHMENT"
    RETIRED = "RETIRED"


class TourStopStatus(str, Enum):
    TENTATIVE = "TENTATIVE"
    CONTRACTED = "CONTRACTED"
    INSTALLING = "INSTALLING"
    OPEN = "OPEN"
    TEARDOWN = "TEARDOWN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    SIGNED = "SIGNED"
    FINALIZED = "FINALIZED"


class CrateLocation(str, Enum):
    AT_ORIGIN = "AT_ORIGIN"
    IN_TRANSIT = "IN_TRANSIT"
    AT_VENUE = "AT_VENUE"
    IN_REFURBISHMENT = "IN_REFURBISHMENT"


class ShipmentStatus(str, Enum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    DAMAGE_HOLD = "DAMAGE_HOLD"
    CLEARED = "CLEARED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    DISPUTED = "DISPUTED"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"


class KitStatus(str, Enum):
    PLANNED = "PLANNED"
    PRODUCED = "PRODUCED"
    DELIVERED = "DELIVERED"
    RETIRED = "RETIRED"


class CertificateStatus(str, Enum):
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    VOID = "VOID"


class ReportPhase(str, Enum):
    UNPACK = "UNPACK"
    PACK = "PACK"


class UserRole(str, Enum):
    TOUR_MANAGER = "TourManager"
    VENUE_REGISTRAR = "VenueRegistrar"
    REGISTRAR = "Registrar"
    SHIPPER = "Shipper"
    INSURER = "Insurer"


# All entities carry common fields: id, created_at, updated_at, version (PRD §2.5).

class Tour(TypedDict, total=False):
    id: str
    title: str
    exhibit_code: str
    crate_count: int
    declared_value_cents: int
    refurbishment_gap_days: int
    status: str
    total_billed_cents: int
    total_collected_cents: int
    total_waived_cents: int
    created_at: str
    updated_at: str
    version: int


class Venue(TypedDict, total=False):
    id: str
    name: str
    city: str
    climate_controlled: bool
    max_gallery_sqm: int
    local_sponsorship_cap_cents: int
    created_at: str
    updated_at: str
    version: int


class TourStop(TypedDict, total=False):
    id: str
    tour_id: str
    venue_id: str
    seq: int
    install_start: str
    open_date: str
    close_date: str
    teardown_end: str
    projected_attendance: int
    actual_attendance: Optional[int]
    status: str
    supervision_required: bool
    created_at: str
    updated_at: str
    version: int


class ParticipationContract(TypedDict, total=False):
    id: str
    tour_stop_id: str
    base_fee_cents: int
    sponsorship_credit_cents: int
    status: str
    provisional_fee_cents: Optional[int]
    final_fee_cents: Optional[int]
    amount_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class Crate(TypedDict, total=False):
    id: str
    tour_id: str
    crate_label: str
    contents_value_cents: int
    location_status: str
    current_stop_id: Optional[str]
    condition_score: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict, total=False):
    id: str
    tour_id: str
    origin_stop_id: Optional[str]
    destination_stop_id: str
    depart_at: str
    arrive_at: str
    carrier_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ConditionReport(TypedDict, total=False):
    id: str
    shipment_id: str
    crate_id: str
    inspector_name: str
    phase: str
    surface_score: int
    structural_score: int
    seal_intact: bool
    status: str
    composite_score: Optional[int]
    created_at: str
    updated_at: str
    version: int


class DamageClaim(TypedDict, total=False):
    id: str
    shipment_id: str
    condition_report_id: str
    claimed_amount_cents: int
    line_items: List[Any]
    status: str
    assessed_payout_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class MarketingKit(TypedDict, total=False):
    id: str
    tour_stop_id: str
    language_count: int
    sponsor_logo_slots: int
    press_release_sent: bool
    status: str
    production_cost_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class InsuranceCertificate(TypedDict, total=False):
    id: str
    tour_id: str
    tour_stop_id: str
    insurer_name: str
    coverage_cents: int
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int
