"""Domain types: entity TypedDicts, status enums, role enum.

All entities carry the full common-field set (id, created_at, updated_at,
version) per the PRD common-resource-properties section.
"""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    AIRPORT_ADMIN = "AirportAdmin"
    WILDLIFE_BIOLOGIST = "WildlifeBiologist"
    ATC_CONTROLLER = "ATCController"
    REGULATOR_AGENT = "RegulatorAgent"


class HazardLevel(str, Enum):
    LOW = "LOW"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class StrikeStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    AMENDED = "AMENDED"


class CarcassIdStatus(str, Enum):
    COLLECTED = "COLLECTED"
    PENDING_ID = "PENDING_ID"
    IDENTIFIED = "IDENTIFIED"
    DISPUTED = "DISPUTED"
    RESOLVED = "RESOLVED"


class MitigationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    IN_PROGRESS = "IN_PROGRESS"
    VERIFIED = "VERIFIED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class DispersalStatus(str, Enum):
    LOGGED = "LOGGED"
    REVIEWED = "REVIEWED"
    FLAGGED = "FLAGGED"
    CLOSED = "CLOSED"


class PermitStatus(str, Enum):
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    CLOSED = "CLOSED"


class AdvisoryStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class ClosureStatus(str, Enum):
    REQUESTED = "REQUESTED"
    AUTHORIZED = "AUTHORIZED"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED_FOR_REVIEW = "SUBMITTED_FOR_REVIEW"
    RETURNED = "RETURNED"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class TrainingStatus(str, Enum):
    VALID = "VALID"
    EXPIRING_SOON = "EXPIRING_SOON"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class Guild(str, Enum):
    RAPTOR = "RAPTOR"
    WATERFOWL = "WATERFOWL"
    GULL = "GULL"
    SONGBIRD = "SONGBIRD"
    BAT = "BAT"
    MAMMAL = "MAMMAL"
    REPTILE = "REPTILE"
    OTHER = "OTHER"


class RiskTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class DamageClass(str, Enum):
    NONE = "NONE"
    MINOR = "MINOR"
    MEDIUM = "MEDIUM"
    SUBSTANTIAL = "SUBSTANTIAL"
    DESTROYED = "DESTROYED"
    UNKNOWN = "UNKNOWN"


class PhaseOfFlight(str, Enum):
    TAKEOFF = "TAKEOFF"
    CLIMB = "CLIMB"
    CRUISE = "CRUISE"
    DESCENT = "DESCENT"
    APPROACH = "APPROACH"
    LANDING = "LANDING"
    TAXI = "TAXI"
    PARKED = "PARKED"


class IdentificationMethod(str, Enum):
    VISUAL = "VISUAL"
    DNA = "DNA"
    FEATHER_SNARGE = "FEATHER_SNARGE"
    MORPHOLOGY = "MORPHOLOGY"
    PENDING = "PENDING"


class DisposalMethod(str, Enum):
    BURIED = "BURIED"
    INCINERATED = "INCINERATED"
    ARCHIVED = "ARCHIVED"
    RELEASED_TO_AGENCY = "RELEASED_TO_AGENCY"


class HabitatFeature(str, Enum):
    STANDING_WATER = "STANDING_WATER"
    VEGETATION_TALL = "VEGETATION_TALL"
    GRASSLAND = "GRASSLAND"
    WASTE_SITE = "WASTE_SITE"
    RODENT_PREY_BASE = "RODENT_PREY_BASE"
    NESTING_STRUCTURE = "NESTING_STRUCTURE"
    FOOD_SOURCE = "FOOD_SOURCE"
    ROOSTING = "ROOSTING"


class MitigationActionType(str, Enum):
    DRAINAGE = "DRAINAGE"
    MOWING = "MOWING"
    FENCING = "FENCING"
    HABITAT_REMOVAL = "HABITAT_REMOVAL"
    DETERRENT = "DETERRENT"
    EXCLUSION = "EXCLUSION"
    PREY_REDUCTION = "PREY_REDUCTION"


class DispersalMethod(str, Enum):
    PYROTECHNICS = "PYROTECHNICS"
    DISTRESS_CALLS = "DISTRESS_CALLS"
    VEHICULAR = "VEHICULAR"
    LASER = "LASER"
    DOG = "DOG"
    FALCONRY = "FALCONRY"
    LETHAL_AMMO = "LETHAL_AMMO"


class Agency(str, Enum):
    USFWS = "USFWS"
    USDA_WS = "USDA_WS"
    STATE_DNR = "STATE_DNR"


class ReasonCode(str, Enum):
    STRIKE_SPIKE = "STRIKE_SPIKE"
    MIGRATION = "MIGRATION"
    NESTING = "NESTING"
    HABITAT_CHANGE = "HABITAT_CHANGE"
    WEATHER = "WEATHER"
    OTHER = "OTHER"


class ClosureReason(str, Enum):
    CARCASS_RECOVERY = "CARCASS_RECOVERY"
    HAZARD_SWEEP = "HAZARD_SWEEP"
    STRIKE_RESPONSE = "STRIKE_RESPONSE"
    MITIGATION_WORK = "MITIGATION_WORK"
    OTHER = "OTHER"


class Airport(TypedDict, total=False):
    id: str
    icao_code: str
    name: str
    current_hazard_level: str
    hazard_level_updated_at: Optional[str]
    strikes_trailing_12m: int
    strikes_trailing_12m_high_risk: int
    annual_plan_cycle_year: int
    created_at: str
    updated_at: str
    version: int


class WildlifeBiologist(TypedDict, total=False):
    id: str
    full_name: str
    certification_id: str
    airport_id: str
    is_senior: bool
    active: bool
    created_at: str
    updated_at: str
    version: int


class ATCController(TypedDict, total=False):
    id: str
    full_name: str
    facility_id: str
    airport_id: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class RegulatorAgent(TypedDict, total=False):
    id: str
    full_name: str
    agency: str
    badge_number: str
    created_at: str
    updated_at: str
    version: int


class Species(TypedDict, total=False):
    id: str
    common_name: str
    scientific_name: str
    guild: str
    risk_tier: str
    body_mass_g: float
    is_protected_federally: bool
    created_at: str
    updated_at: str
    version: int


class WildlifeStrikeReport(TypedDict, total=False):
    id: str
    airport_id: str
    reporter_biologist_id: str
    strike_at: str
    runway_designator: str
    aircraft_registration: str
    species_id: str
    status: str
    damage_class: str
    phase_of_flight: str
    altitude_ft_agl: int
    strike_count_animals: int
    carcass_present: bool
    confirmed_by_biologist_id: Optional[str]
    confirmation_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CarcassRecord(TypedDict, total=False):
    id: str
    strike_report_id: str
    species_id_at_collection: str
    species_id_final: Optional[str]
    identification_method: str
    identification_status: str
    identified_by_biologist_id: Optional[str]
    identified_at: Optional[str]
    disposal_method: str
    created_at: str
    updated_at: str
    version: int


class HabitatAssessment(TypedDict, total=False):
    id: str
    airport_id: str
    assessed_by_biologist_id: str
    assessed_at: str
    habitat_feature: str
    attractiveness_score: int
    severity_score: int
    composite_score: int
    created_at: str
    updated_at: str
    version: int


class MitigationAction(TypedDict, total=False):
    id: str
    habitat_assessment_id: str
    action_type: str
    status: str
    proposed_by_biologist_id: str
    reviewed_by_biologist_id: Optional[str]
    target_completion_date: str
    completed_at: Optional[str]
    effectiveness_rating: Optional[int]
    created_at: str
    updated_at: str
    version: int


class DispersalActivity(TypedDict, total=False):
    id: str
    airport_id: str
    performed_by_biologist_id: str
    performed_at: str
    method: str
    species_id: str
    animals_dispersed: int
    animals_taken_lethal: int
    take_permit_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TakePermit(TypedDict, total=False):
    id: str
    airport_id: str
    species_id: str
    issued_by_regulator_id: str
    permit_number: str
    authorized_take_total: int
    take_consumed: int
    valid_from: str
    valid_to: str
    status: str
    annual_report_submitted: bool
    created_at: str
    updated_at: str
    version: int


class OperationalAdvisory(TypedDict, total=False):
    id: str
    airport_id: str
    issued_by_biologist_id: str
    issued_at: str
    effective_from: str
    effective_to: str
    hazard_level: str
    status: str
    reason_code: str
    supersedes_advisory_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RunwayClosure(TypedDict, total=False):
    id: str
    airport_id: str
    runway_designator: str
    requested_by_biologist_id: str
    authorized_by_controller_id: Optional[str]
    closure_start: str
    closure_end: str
    actual_released_at: Optional[str]
    status: str
    reason: str
    created_at: str
    updated_at: str
    version: int


class AnnualPlan(TypedDict, total=False):
    id: str
    airport_id: str
    plan_year: int
    status: str
    submitted_at: Optional[str]
    approved_by_regulator_id: Optional[str]
    published_at: Optional[str]
    version_note: str
    created_at: str
    updated_at: str
    version: int


class TrainingRecord(TypedDict, total=False):
    id: str
    biologist_id: str
    course_code: str
    completed_at: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int
