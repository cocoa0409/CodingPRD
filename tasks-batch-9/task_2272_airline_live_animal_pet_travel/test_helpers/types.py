"""Typed shapes for the live animal / pet travel acceptance service.

Every TypedDict mirrors the response body that the PRD promises for the
corresponding resource.  Per PRD §2.4 every resource carries ``id`` and
``created_at``; the thirteen versioned resources additionally carry
``updated_at`` and ``version``.  ``WelfareCheck`` is the single append-only
event resource and therefore deliberately omits both.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, TypedDict

# ---------------------------------------------------------------------------
# Role vocabulary (PRD §2.1)
# ---------------------------------------------------------------------------

RoleName = Literal[
    "ProgramAdmin",
    "ReservationsAgent",
    "AcceptanceAgent",
    "VeterinaryReviewer",
    "ComplianceOfficer",
]

# ---------------------------------------------------------------------------
# Enumerations (PRD §3)
# ---------------------------------------------------------------------------

AcceptanceClass = Literal["ACCEPTED_ALL_ROUTINGS", "CARGO_ONLY", "EMBARGOED_SPECIES"]
SpeciesStatus = Literal["ACTIVE", "RETIRED"]

BreedRestrictionType = Literal["SNUB_NOSED", "BANNED", "CARGO_ONLY", "WEIGHT_CAPPED"]
BreedRestrictionStatus = Literal["ACTIVE", "WITHDRAWN"]

DocumentType = Literal[
    "HEALTH_CERTIFICATE",
    "RABIES_VACCINATION",
    "IMPORT_PERMIT",
    "PARASITE_TREATMENT",
]
DestinationRequirementStatus = Literal["ACTIVE", "SUPERSEDED"]

StationStatus = Literal["ACCEPTING", "SUSPENDED"]

EmbargoDirection = Literal["ORIGIN", "DESTINATION"]
EmbargoRuleStatus = Literal["ACTIVE", "SUPERSEDED"]

RoutingType = Literal["CABIN", "CHECKED", "CARGO"]

FlightLegStatus = Literal["SCHEDULED", "DELAYED", "CANCELLED", "DEPARTED", "ARRIVED"]
LegPosture = Literal["OPEN", "RESTRICTED", "EMBARGOED", "CLOSED"]

BookingStatus = Literal[
    "PENDING",
    "CONFIRMED",
    "HOLD_PARTIAL",
    "REBOOK_REQUIRED",
    "IN_TRANSIT",
    "COMPLETED",
    "INTERRUPTED",
    "CANCELLED",
]
ComplianceStatus = Literal["UNVERIFIED", "IN_REVIEW", "VERIFIED", "DEFICIENT", "EXPIRED"]

AnimalKind = Literal["PET", "SERVICE_ANIMAL"]
AnimalStatus = Literal[
    "DRAFT",
    "SCREENED",
    "TRAVEL_READY",
    "IN_TRANSIT",
    "DELIVERED",
    "DENIED",
    "DECEASED",
]
ContainerComplianceState = Literal["UNEVALUATED", "COMPLIANT", "DEFICIENT"]
DeficiencyCode = Literal[
    "HEIGHT", "LENGTH", "VENT_PCT", "VENT_SIDES", "GROSS_WEIGHT", "CABIN_DIM", "WHEELS"
]

SegmentStatus = Literal["RESERVED", "ACCEPTED", "COMPLETED", "RELEASED", "OFFLOADED"]
FeeVariant = Literal["PROVISIONAL_AT_RESERVATION", "FINAL_AT_ACCEPTANCE"]

HealthDocumentStatus = Literal[
    "SUBMITTED", "UNDER_REVIEW", "VERIFIED", "REJECTED", "EXPIRED"
]

AllocationStatus = Literal["RESERVED", "OCCUPIED", "RELEASED"]

WelfareCheckType = Literal["WATER", "FEED", "VISUAL", "SANITATION"]
WelfareCheckOutcome = Literal["NORMAL", "CONCERN"]

IncidentType = Literal["INJURY", "LOSS", "DEATH"]
IncidentStatus = Literal["REPORTED", "INVESTIGATING", "REGULATOR_DISCLOSED", "CLOSED"]
VeterinaryFinding = Literal[
    "CARRIER_ATTRIBUTABLE", "PRE_EXISTING_CONDITION", "INDETERMINATE"
]


# ---------------------------------------------------------------------------
# Envelope (PRD §2.2)
# ---------------------------------------------------------------------------


class ResponseMeta(TypedDict, total=False):
    api_request_id: str
    api_request_timestamp: str
    total_count: int
    has_more: bool
    limit: int
    offset: int


class ErrorPayload(TypedDict, total=False):
    error_id: str
    message: str
    details: Optional[Dict[str, Any]]


# ---------------------------------------------------------------------------
# Versioned resources (PRD §2.4)
# ---------------------------------------------------------------------------


class VersionedResource(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class SpeciesProfile(VersionedResource, total=False):
    species_code: str
    common_name: str
    acceptance_class: AcceptanceClass
    max_cabin_weight_kg: float
    min_age_weeks: int
    requires_veterinary_review: bool
    breed_restriction_count: int
    status: SpeciesStatus


class BreedRestriction(VersionedResource, total=False):
    species_profile_id: str
    breed_name: str
    restriction_type: BreedRestrictionType
    max_weight_kg: Optional[float]
    status: BreedRestrictionStatus


class DestinationRequirement(VersionedResource, total=False):
    species_profile_id: str
    destination_country_code: str
    document_type: DocumentType
    max_age_days_at_arrival: int
    mandatory: bool
    status: DestinationRequirementStatus


class ContainerModel(VersionedResource, total=False):
    model_code: str
    interior_height_cm: float
    interior_length_cm: float
    interior_width_cm: float
    tare_weight_kg: float
    ventilation_area_pct: float
    ventilated_side_count: int
    wheels_removable: bool
    cabin_eligible: bool


class Station(VersionedResource, total=False):
    iata_code: str
    country_code: str
    kennel_bay_count: int
    reserved_bay_count: int
    status: StationStatus


class TemperatureEmbargoRule(VersionedResource, total=False):
    station_id: str
    direction: EmbargoDirection
    season_start_month_day: str
    season_end_month_day: str
    forecast_high_limit_c: float
    forecast_low_limit_c: float
    applies_to_routings: List[RoutingType]
    status: EmbargoRuleStatus


class FlightLeg(VersionedResource, total=False):
    flight_number: str
    origin_station_id: str
    destination_station_id: str
    scheduled_departure_utc: str
    scheduled_arrival_utc: str
    block_minutes: int
    cabin_animal_limit: int
    checked_animal_limit: int
    cargo_animal_limit: int
    forecast_high_c: float
    forecast_low_c: float
    booked_cabin_count: int
    booked_checked_count: int
    booked_cargo_count: int
    governing_embargo_rule_id: Optional[str]
    posture: LegPosture
    status: FlightLegStatus


class Reservation(VersionedResource, total=False):
    passenger_name: str
    contact_email: str
    routing_type: RoutingType
    is_service_animal_booking: bool
    booked_by_agent_id: str
    booking_status: BookingStatus
    compliance_status: ComplianceStatus
    animal_count: int
    irops_fee_total: int
    subtotal_amount: int
    loyalty_tier_pct: float
    loyalty_discount_amount: int
    refunded_amount: int
    net_payable_amount: int


class AnimalRecord(VersionedResource, total=False):
    reservation_id: str
    species_profile_id: str
    container_model_id: str
    animal_name: str
    breed_name: str
    animal_kind: AnimalKind
    declared_weight_kg: float
    measured_weight_kg: Optional[float]
    chargeable_weight_kg: int
    height_at_shoulder_cm: float
    length_nose_to_tail_cm: float
    age_weeks: int
    behavior_attestation_on_file: bool
    container_compliance_state: ContainerComplianceState
    deficiency_codes: List[DeficiencyCode]
    status: AnimalStatus


class SegmentAssignment(VersionedResource, total=False):
    animal_record_id: str
    flight_leg_id: str
    sequence_index: int
    routing_type: RoutingType
    segment_fee_amount: int
    fee_variant: FeeVariant
    connection_minutes: Optional[int]
    required_welfare_check_count: int
    completed_welfare_check_count: int
    status: SegmentStatus


class HealthDocument(VersionedResource, total=False):
    animal_record_id: str
    document_type: DocumentType
    issuing_country_code: str
    issued_at: str
    expires_at: str
    revision_count: int
    reviewed_by_user_id: Optional[str]
    status: HealthDocumentStatus


class KennelAllocation(VersionedResource, total=False):
    station_id: str
    animal_record_id: str
    bay_count: int
    occupancy_start_utc: str
    occupancy_end_utc: str
    feeding_interval_minutes: int
    status: AllocationStatus


class AnimalIncident(VersionedResource, total=False):
    animal_record_id: str
    segment_assignment_id: Optional[str]
    incident_type: IncidentType
    discovered_at_utc: str
    preliminary_severity_score: int
    adjudicated_severity_score: Optional[int]
    veterinary_finding: Optional[VeterinaryFinding]
    disclosure_required: bool
    disclosure_deadline_utc: Optional[str]
    disclosed_at_utc: Optional[str]
    disclosure_on_time: Optional[bool]
    reported_by_user_id: str
    investigated_by_user_id: Optional[str]
    closed_by_user_id: Optional[str]
    status: IncidentStatus


# ---------------------------------------------------------------------------
# The single append-only event resource (PRD §2.4)
# ---------------------------------------------------------------------------


class WelfareCheck(TypedDict, total=False):
    """A welfare check carries only ``id`` and ``created_at``.

    PRD §2.4: "A ``WelfareCheck`` is an append-only event: it carries only
    ``id`` and ``created_at``."  No ``updated_at``, no ``version``.
    """

    id: str
    created_at: str
    segment_assignment_id: str
    check_type: WelfareCheckType
    recorded_at_utc: str
    outcome: WelfareCheckOutcome
    notes: Optional[str]
    performed_by_user_id: str


# ---------------------------------------------------------------------------
# Computed reads (PRD §3.8)
# ---------------------------------------------------------------------------


class ChargeSummary(TypedDict, total=False):
    reservation_id: str
    irops_fee_total: int
    subtotal_amount: int
    loyalty_tier_pct: float
    loyalty_discount_amount: int
    refunded_amount: int
    net_payable_amount: int
    invariant_holds: bool


class IropsCareSweep(TypedDict, total=False):
    flight_leg_id: str
    affected_animal_count: int
    irops_fee_per_animal: int
    total_fee_charged: int


class LogicalClock(TypedDict, total=False):
    current_utc: str


__all__ = [
    "RoleName",
    "AcceptanceClass",
    "SpeciesStatus",
    "BreedRestrictionType",
    "BreedRestrictionStatus",
    "DocumentType",
    "DestinationRequirementStatus",
    "StationStatus",
    "EmbargoDirection",
    "EmbargoRuleStatus",
    "RoutingType",
    "FlightLegStatus",
    "LegPosture",
    "BookingStatus",
    "ComplianceStatus",
    "AnimalKind",
    "AnimalStatus",
    "ContainerComplianceState",
    "DeficiencyCode",
    "SegmentStatus",
    "FeeVariant",
    "HealthDocumentStatus",
    "AllocationStatus",
    "WelfareCheckType",
    "WelfareCheckOutcome",
    "IncidentType",
    "IncidentStatus",
    "VeterinaryFinding",
    "ResponseMeta",
    "ErrorPayload",
    "VersionedResource",
    "SpeciesProfile",
    "BreedRestriction",
    "DestinationRequirement",
    "ContainerModel",
    "Station",
    "TemperatureEmbargoRule",
    "FlightLeg",
    "Reservation",
    "AnimalRecord",
    "SegmentAssignment",
    "HealthDocument",
    "KennelAllocation",
    "AnimalIncident",
    "WelfareCheck",
    "ChargeSummary",
    "IropsCareSweep",
    "LogicalClock",
]
