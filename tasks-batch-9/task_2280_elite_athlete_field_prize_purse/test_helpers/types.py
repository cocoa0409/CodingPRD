"""Domain types for the Elite Field & Prize Purse Administration API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    ELITES_DIRECTOR = "ElitesDirector"
    ATHLETE_AGENT = "AthleteAgent"
    TECHNICAL_OFFICIAL = "TechnicalOfficial"
    ANTI_DOPING_LIAISON = "AntiDopingLiaison"
    SANCTIONING_BODY = "SanctioningBody"
    FINANCE_OFFICER = "FinanceOfficer"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class RaceEditionStatus(str, Enum):
    PLANNING = "PLANNING"
    FIELD_OPEN = "FIELD_OPEN"
    FIELD_LOCKED = "FIELD_LOCKED"
    RACED = "RACED"
    RESULTS_CERTIFIED = "RESULTS_CERTIFIED"
    PURSE_SETTLED = "PURSE_SETTLED"


class InvitationStatus(str, Enum):
    DRAFT = "DRAFT"
    OFFERED = "OFFERED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"
    BREACHED = "BREACHED"


class PerformanceVerificationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class DopingTestStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COLLECTED = "COLLECTED"
    CLEARED = "CLEARED"
    ADVERSE = "ADVERSE"
    MISSED = "MISSED"


class CertificationStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CERTIFIED = "CERTIFIED"
    DISQUALIFIED = "DISQUALIFIED"


class RecordClaimStatus(str, Enum):
    NONE = "NONE"
    CLAIMED = "CLAIMED"
    SUBMITTED = "SUBMITTED"
    RATIFIED = "RATIFIED"
    REJECTED = "REJECTED"


class PrizeAwardStatus(str, Enum):
    COMPUTED = "COMPUTED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    VOID = "VOID"
    CLAWBACK_PENDING = "CLAWBACK_PENDING"


class FluidStationSlotStatus(str, Enum):
    RESERVED = "RESERVED"
    RELEASED = "RELEASED"


class RepAgentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


# --------------------------------------------------------------------------
# Value enums
# --------------------------------------------------------------------------
class Division(str, Enum):
    ELITE = "ELITE"
    SUB_ELITE = "SUB_ELITE"
    WHEELCHAIR = "WHEELCHAIR"


class Gender(str, Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"


class PurseCategory(str, Enum):
    OVERALL = "OVERALL"
    DIVISION = "DIVISION"
    MASTERS = "MASTERS"
    TIME_BONUS = "TIME_BONUS"
    RECORD_BONUS = "RECORD_BONUS"


class AirClass(str, Enum):
    ECONOMY = "ECONOMY"
    PREMIUM_ECONOMY = "PREMIUM_ECONOMY"
    BUSINESS = "BUSINESS"


class AssistanceRule(str, Enum):
    LEAD_ONLY = "LEAD_ONLY"
    FLUIDS_ALLOWED = "FLUIDS_ALLOWED"


class TestType(str, Enum):
    IN_COMPETITION = "IN_COMPETITION"
    OUT_OF_COMPETITION = "OUT_OF_COMPETITION"


class DopingOutcome(str, Enum):
    CLEARED = "CLEARED"
    ADVERSE = "ADVERSE"


class DqReason(str, Enum):
    PACER_BEYOND_RANGE = "PACER_BEYOND_RANGE"
    UNAUTHORIZED_FLUID_HANDOFF = "UNAUTHORIZED_FLUID_HANDOFF"
    COURSE_CUTTING = "COURSE_CUTTING"
    ADVERSE_ANALYTICAL_FINDING = "ADVERSE_ANALYTICAL_FINDING"
    MISSED_TEST_THRESHOLD = "MISSED_TEST_THRESHOLD"


class WithholdingVariant(str, Enum):
    NONE = "NONE"
    PER_AWARD = "PER_AWARD"
    AGGREGATED = "AGGREGATED"


class NegotiationSide(str, Enum):
    COMMITTEE = "COMMITTEE"
    AGENT = "AGENT"


class VerificationDecision(str, Enum):
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class RespondDecision(str, Enum):
    ACCEPT = "ACCEPT"
    DECLINE = "DECLINE"


class RecordDecision(str, Enum):
    RATIFIED = "RATIFIED"
    REJECTED = "REJECTED"


# --------------------------------------------------------------------------
# Entity TypedDicts
#
# PRD §2.5: RaceEdition, PurseLine, DivisionStandard, Athlete, RepAgent,
# PerformanceRecord, Invitation, PacerAssignment, FluidStationSlot,
# DopingTest, RaceResult and PrizeAward carry id/created_at/updated_at/version.
# NegotiationRound is the one exception and carries only id and created_at.
# --------------------------------------------------------------------------
class RaceEdition(TypedDict):
    id: str
    name: str
    city: str
    race_date: str
    status: str
    appearance_budget_cents: int
    appearance_committed_cents: int
    appearance_uncommitted_cents: int
    total_purse_cents: int
    purse_allocated_cents: int
    purse_unallocated_cents: int
    bonus_pool_cap_cents: int
    bonus_pool_consumed_cents: int
    course_record_male_seconds: Optional[int]
    course_record_female_seconds: Optional[int]
    course_record_wheelchair_male_seconds: Optional[int]
    course_record_wheelchair_female_seconds: Optional[int]
    offer_response_days: int
    max_negotiation_rounds: int
    masters_min_age: int
    expired_offer_count: int
    created_at: str
    updated_at: str
    version: int


class PurseLine(TypedDict):
    id: str
    race_edition_id: str
    category: str
    division: Optional[str]
    gender: str
    place: Optional[int]
    threshold_seconds: Optional[int]
    amount_cents: int
    created_at: str
    updated_at: str
    version: int


class DivisionStandard(TypedDict):
    id: str
    race_edition_id: str
    division: str
    gender: str
    max_qualifying_seconds: int
    window_months: int
    requires_chip_timing: bool
    bib_range_start: int
    bib_range_end: int
    created_at: str
    updated_at: str
    version: int


class Athlete(TypedDict):
    id: str
    full_name: str
    country_code: str
    gender: str
    birth_date: str
    tax_residency_country: str
    w8ben_on_file: bool
    treaty_withholding_bps: int
    whereabouts_filed: bool
    missed_test_count: int
    created_at: str
    updated_at: str
    version: int


class RepAgent(TypedDict):
    id: str
    agency_name: str
    license_code: str
    commission_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PerformanceRecord(TypedDict):
    id: str
    athlete_id: str
    race_name: str
    performance_date: str
    performance_seconds: int
    division: str
    chip_timed: bool
    sanctioning_ref: str
    verification_status: str
    verified_seconds: Optional[int]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invitation(TypedDict):
    id: str
    race_edition_id: str
    athlete_id: str
    agent_id: str
    qualifying_performance_id: str
    division: str
    status: str
    current_appearance_fee_cents: Optional[int]
    current_air_class: Optional[str]
    current_hotel_nights: Optional[int]
    current_ground_transport: Optional[bool]
    round_count: int
    offer_sent_at: Optional[str]
    response_deadline_at: Optional[str]
    guaranteed_commitment_cents: int
    full_exposure_cents: int
    bib_number: Optional[int]
    negotiated_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NegotiationRound(TypedDict):
    """Append-only historical fact: carries only id and created_at.

    PRD §2.5: a round has no updated_at field and no version field at all.
    """
    id: str
    invitation_id: str
    round_number: int
    side: str
    appearance_fee_cents: int
    air_class: str
    hotel_nights: int
    ground_transport: bool
    note: Optional[str]
    created_at: str


class PacerAssignment(TypedDict):
    id: str
    race_edition_id: str
    pacer_license_code: str
    pacer_name: str
    target_pace_seconds_per_km: int
    start_km: float
    end_km: float
    assistance_rule: str
    created_at: str
    updated_at: str
    version: int


class FluidStationSlot(TypedDict):
    id: str
    invitation_id: str
    station_km: float
    table_position: int
    bottle_count: int
    occupied_from: int
    occupied_to: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DopingTest(TypedDict):
    id: str
    athlete_id: str
    race_edition_id: str
    test_type: str
    window_start_at: str
    window_end_at: str
    sample_code: str
    status: str
    collected_at: Optional[str]
    collected_sample_ref: Optional[str]
    outcome_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RaceResult(TypedDict):
    id: str
    race_edition_id: str
    invitation_id: str
    athlete_id: str
    division: str
    gun_seconds: int
    net_seconds: int
    official_seconds: int
    certification_status: str
    record_claim_status: str
    dq_reason: Optional[str]
    place_overall: Optional[int]
    place_division: Optional[int]
    place_masters: Optional[int]
    tie_group_size: int
    is_masters: bool
    sanctioning_submission_ref: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PrizeAward(TypedDict):
    id: str
    race_edition_id: str
    race_result_id: str
    athlete_id: str
    category: str
    place: Optional[int]
    tie_share_count: int
    gross_amount_cents: int
    withholding_variant: str
    withholding_bps: int
    withholding_cents: int
    net_amount_cents: int
    status: str
    approved_by_user_id: Optional[str]
    paid_by_user_id: Optional[str]
    payment_reference: Optional[str]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
