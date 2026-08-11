"""Domain types for the Animal Rescue & Foster/Transport Network API.

Status enums, role enum and entity TypedDicts. Every entity in this system
carries `id`, `created_at`, `updated_at` and `version` (PRD 2.4).
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    INTAKE_OFFICER = "IntakeOfficer"
    FOSTER_COORDINATOR = "FosterCoordinator"
    ADOPTION_COUNSELOR = "AdoptionCounselor"
    TRANSPORT_DISPATCHER = "TransportDispatcher"
    DRIVER = "Driver"
    VETERINARIAN = "Veterinarian"
    FINANCE_OFFICER = "FinanceOfficer"
    FOSTER_PARENT = "FosterParent"
    ADOPTER = "Adopter"
    PARTNER_RESCUE = "PartnerRescue"


# --------------------------------------------------------------------------
# Status axes
# --------------------------------------------------------------------------
class FreezeStatus(str, Enum):
    UNFROZEN = "UNFROZEN"
    FROZEN = "FROZEN"


class AnimalLifecycleStatus(str, Enum):
    PRE_INTAKE = "PRE_INTAKE"
    IN_CUSTODY = "IN_CUSTODY"
    IN_TRANSIT = "IN_TRANSIT"
    STRANDED = "STRANDED"
    OUTCOME_CLOSED = "OUTCOME_CLOSED"


class AlterationStatus(str, Enum):
    NOT_ALTERED = "NOT_ALTERED"
    ALTERED = "ALTERED"
    DEFERRED_DEPOSIT = "DEFERRED_DEPOSIT"


class IntakeRecordStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    VOIDED = "VOIDED"


class HoldClockStatus(str, Enum):
    HOLD_ACTIVE = "HOLD_ACTIVE"
    HOLD_EXPIRED = "HOLD_EXPIRED"


class HoldRecordStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class LitterTransportBasis(str, Enum):
    GROUPED = "GROUPED"
    SPLIT_APPROVED = "SPLIT_APPROVED"


class FosterApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"


class HomeCheckStatus(str, Enum):
    NOT_SCHEDULED = "NOT_SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    LAPSED = "LAPSED"


class FosterHomeCapacityStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"


class FosterPlacementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"
    TRANSFERRED = "TRANSFERRED"
    CONVERTED_TO_ADOPTION = "CONVERTED_TO_ADOPTION"


class PlacementEndReason(str, Enum):
    RETURNED_TO_SHELTER = "RETURNED_TO_SHELTER"
    CANCELLED_BEFORE_START = "CANCELLED_BEFORE_START"
    TRANSFERRED_OUT = "TRANSFERRED_OUT"
    ADOPTED = "ADOPTED"
    ANIMAL_OUTCOME_CLOSED = "ANIMAL_OUTCOME_CLOSED"


class MedicalRecordStatus(str, Enum):
    ORDERED = "ORDERED"
    COMPLETED = "COMPLETED"


class HealthCertificateStatus(str, Enum):
    VALID = "VALID"
    EXPIRED = "EXPIRED"


class TransportRunStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"
    CANCELLED = "CANCELLED"


class TransportLegStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DEPARTED = "DEPARTED"
    ARRIVED = "ARRIVED"
    ABORTED = "ABORTED"
    INVALIDATED = "INVALIDATED"


class ManifestEntryStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    LOADED = "LOADED"
    DELIVERED = "DELIVERED"
    BUMPED = "BUMPED"
    STRANDED = "STRANDED"


class AdoptionApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    AUTO_DECLINED = "AUTO_DECLINED"
    FINALIZED = "FINALIZED"


class DeclineReason(str, Enum):
    COUNSELOR_DECISION = "COUNSELOR_DECISION"
    SUPERSEDED_BY_FINALIZED_SIBLING = "SUPERSEDED_BY_FINALIZED_SIBLING"


class AdoptionStatus(str, Enum):
    FINALIZED = "FINALIZED"
    RETURNED = "RETURNED"


class AdoptionFeeStatus(str, Enum):
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    REFUNDED_PARTIAL = "REFUNDED_PARTIAL"
    REFUNDED_FULL = "REFUNDED_FULL"


class WaiverKind(str, Enum):
    NONE = "NONE"
    SENIOR = "SENIOR"
    LONG_STAY = "LONG_STAY"


class ContributionStatus(str, Enum):
    RECEIVED = "RECEIVED"
    PARTIALLY_APPLIED = "PARTIALLY_APPLIED"
    FULLY_APPLIED = "FULLY_APPLIED"
    RELEASED = "RELEASED"


class PartnerCommitmentStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_DRAWN = "PARTIALLY_DRAWN"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"


# --------------------------------------------------------------------------
# Input enumerations (PRD 2.9)
# --------------------------------------------------------------------------
class OrgType(str, Enum):
    SHELTER = "SHELTER"
    PARTNER_RESCUE = "PARTNER_RESCUE"


class Methodology(str, Enum):
    SAC = "SAC"
    ASILOMAR = "ASILOMAR"


class HousingType(str, Enum):
    APARTMENT = "APARTMENT"
    CONDO = "CONDO"
    HOUSE = "HOUSE"
    FARM = "FARM"


class Species(str, Enum):
    DOG = "DOG"
    CAT = "CAT"
    OTHER = "OTHER"


class SizeClass(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class Temperament(str, Enum):
    SOCIAL = "SOCIAL"
    REACTIVE = "REACTIVE"
    UNKNOWN = "UNKNOWN"


class IntakeType(str, Enum):
    STRAY = "STRAY"
    OWNER_SURRENDER = "OWNER_SURRENDER"
    CONFISCATE = "CONFISCATE"
    TRANSFER_IN = "TRANSFER_IN"
    RETURN = "RETURN"


class ImpoundBillingBasis(str, Enum):
    CALENDAR_DAY = "CALENDAR_DAY"
    OVERNIGHT = "OVERNIGHT"


class HoldType(str, Enum):
    MEDICAL = "MEDICAL"
    BEHAVIORAL = "BEHAVIORAL"
    LEGAL = "LEGAL"


class CountBasis(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    NURSING_UNIT = "NURSING_UNIT"


class ProcedureType(str, Enum):
    EXAM = "EXAM"
    VACCINE_RABIES = "VACCINE_RABIES"
    SPAY_NEUTER = "SPAY_NEUTER"
    TREATMENT = "TREATMENT"


class ExpenseCategory(str, Enum):
    MEDICAL = "MEDICAL"
    SPAY_NEUTER = "SPAY_NEUTER"
    VACCINE = "VACCINE"


class RunType(str, Enum):
    RESCUE_LEG = "RESCUE_LEG"
    RELAY = "RELAY"


class RunPurpose(str, Enum):
    INTAKE_TRANSPORT = "INTAKE_TRANSPORT"
    TRANSFER_OUT = "TRANSFER_OUT"


class SpeciesPolicy(str, Enum):
    DOGS_ONLY = "DOGS_ONLY"
    CATS_ONLY = "CATS_ONLY"
    MIXED_SEGREGATED = "MIXED_SEGREGATED"
    ANY = "ANY"


class CreditApplicationOrder(str, Enum):
    CREDIT_FIRST = "CREDIT_FIRST"
    WAIVER_FIRST = "WAIVER_FIRST"


class RefundBasis(str, Enum):
    FEE_PAID = "FEE_PAID"
    FEE_ASSESSED = "FEE_ASSESSED"


class DepositBasis(str, Enum):
    FLAT = "FLAT"
    AGE_SCALED = "AGE_SCALED"


class OutcomeType(str, Enum):
    ADOPTION = "ADOPTION"
    FOSTER_TO_ADOPT = "FOSTER_TO_ADOPT"
    TRANSFER_OUT = "TRANSFER_OUT"
    RETURN_TO_OWNER = "RETURN_TO_OWNER"
    EUTHANASIA_MEDICAL = "EUTHANASIA_MEDICAL"
    EUTHANASIA_BEHAVIORAL = "EUTHANASIA_BEHAVIORAL"
    EUTHANASIA_OWNER_REQUESTED = "EUTHANASIA_OWNER_REQUESTED"
    DIED_IN_CARE = "DIED_IN_CARE"
    LOST_IN_CARE = "LOST_IN_CARE"


class DesignatedProgram(str, Enum):
    NONE = "NONE"
    ADOPTION_FEE_ASSISTANCE = "ADOPTION_FEE_ASSISTANCE"
    TRANSPORT_FUND = "TRANSPORT_FUND"
    MEDICAL_FUND = "MEDICAL_FUND"


class RestrictionCategory(str, Enum):
    UNRESTRICTED = "UNRESTRICTED"
    MEDICAL = "MEDICAL"
    SPAY_NEUTER = "SPAY_NEUTER"
    VACCINE = "VACCINE"
    TRANSPORT = "TRANSPORT"


LIVE_OUTCOME_TYPES = [
    OutcomeType.ADOPTION.value,
    OutcomeType.FOSTER_TO_ADOPT.value,
    OutcomeType.TRANSFER_OUT.value,
    OutcomeType.RETURN_TO_OWNER.value,
]

NON_LIVE_OUTCOME_TYPES = [
    OutcomeType.EUTHANASIA_MEDICAL.value,
    OutcomeType.EUTHANASIA_BEHAVIORAL.value,
    OutcomeType.EUTHANASIA_OWNER_REQUESTED.value,
    OutcomeType.DIED_IN_CARE.value,
    OutcomeType.LOST_IN_CARE.value,
]


# --------------------------------------------------------------------------
# Entity shapes (every entity carries id/created_at/updated_at/version)
# --------------------------------------------------------------------------
class Organization(TypedDict):
    id: str
    name: str
    org_type: str
    state_code: str
    default_methodology: str
    records_freeze_active: bool
    records_freeze_reason: Optional[str]
    freeze_status: str
    unrestricted_balance_cents: int
    restricted_balance_cents: int
    open_commitment_slots_total: int
    created_at: str
    updated_at: str
    version: int


class Person(TypedDict):
    id: str
    full_name: str
    email: str
    youngest_child_age_years: int
    resident_cat_count: int
    resident_dog_count: int
    housing_type: str
    has_fenced_yard: bool
    hardship_certified: bool
    driver_license_number: Optional[str]
    reclaim_history_count: int
    created_at: str
    updated_at: str
    version: int


class Animal(TypedDict):
    id: str
    name: str
    species: str
    size_class: str
    weight_lb: float
    date_of_birth: str
    temperament: str
    microchip_id: Optional[str]
    identifiable: bool
    litter_id: Optional[str]
    current_organization_id: str
    current_foster_home_id: Optional[str]
    current_intake_record_id: Optional[str]
    current_hub_code: Optional[str]
    lifecycle_status: str
    alteration_status: str
    rabies_vaccinated_at: Optional[str]
    restriction_no_children_under_years: int
    restriction_no_cats: bool
    restriction_no_dogs: bool
    restriction_requires_fenced_yard: bool
    restriction_housing_types_excluded: List[str]
    age_weeks: int
    age_months: int
    length_of_stay_days: int
    created_at: str
    updated_at: str
    version: int


class Litter(TypedDict):
    id: str
    label: str
    dam_animal_id: Optional[str]
    transport_basis: str
    member_count: int
    split_approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IntakeRecord(TypedDict):
    id: str
    animal_id: str
    intake_type: str
    intake_datetime: str
    source_person_id: Optional[str]
    impound_billing_basis: str
    identifiable_at_intake: bool
    hold_days: int
    hold_expires_at: str
    hold_status: str
    status: str
    reclaim_base_fee_cents: Optional[int]
    impound_billable_days: Optional[int]
    impound_subtotal_cents: Optional[int]
    repeat_offense_multiplier: Optional[float]
    hardship_waiver_cents: Optional[int]
    reclaim_total_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class HoldRecord(TypedDict):
    id: str
    animal_id: str
    hold_type: str
    reason: str
    status: str
    released_at: Optional[str]
    released_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FosterHome(TypedDict):
    id: str
    person_id: str
    label: str
    max_headcount: int
    dog_slot_capacity: int
    cat_slot_capacity: int
    accepts_cats: bool
    min_child_age_years: int
    has_fenced_yard: bool
    consumed_dog_slots: int
    consumed_cat_slots: int
    consumed_headcount: int
    capacity_status: str
    created_at: str
    updated_at: str
    version: int


class FosterApplication(TypedDict):
    id: str
    person_id: str
    foster_home_id: str
    species_requested: str
    application_status: str
    home_check_status: str
    home_check_passed_at: Optional[str]
    home_check_expires_at: Optional[str]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FosterPlacement(TypedDict):
    id: str
    animal_id: str
    foster_home_id: str
    foster_application_id: str
    litter_id: Optional[str]
    count_basis: str
    slot_consumption: int
    headcount_consumption: int
    status: str
    started_at: Optional[str]
    ended_at: Optional[str]
    end_reason: Optional[str]
    predecessor_placement_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MedicalRecord(TypedDict):
    id: str
    animal_id: str
    procedure_type: str
    expense_category: str
    cost_cents: int
    scheduled_at: str
    funding_required: bool
    status: str
    completed_at: Optional[str]
    funded_contribution_ids: List[str]
    funded_amount_cents: int
    admin_overhead_cents: int
    created_at: str
    updated_at: str
    version: int


class HealthCertificate(TypedDict):
    id: str
    animal_id: str
    issued_at: str
    destination_state: str
    vet_license_number: str
    window_days: int
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TransportRun(TypedDict):
    id: str
    origin_organization_id: str
    run_type: str
    purpose: str
    origin_hub_code: str
    destination_hub_code: str
    partner_commitment_id: Optional[str]
    slots_drawn: int
    status: str
    started_at: Optional[str]
    aborted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransportLeg(TypedDict):
    id: str
    transport_run_id: str
    driver_person_id: str
    sequence_no: int
    origin_hub_code: str
    destination_hub_code: str
    scheduled_depart_at: str
    scheduled_arrive_at: str
    crate_capacity_units: int
    weight_capacity_lb: float
    crosses_state_line: bool
    destination_state_code: Optional[str]
    species_policy: str
    used_crate_units: int
    used_weight_lb: float
    status: str
    departed_at: Optional[str]
    arrived_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ManifestEntry(TypedDict):
    id: str
    transport_leg_id: str
    animal_id: str
    crate_units: int
    is_litter_anchor: bool
    status: str
    stranded_at_hub_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AdoptionApplication(TypedDict):
    id: str
    animal_id: str
    applicant_person_id: str
    status: str
    attempt_count: int
    screened_by_user_id: Optional[str]
    screened_at: Optional[str]
    decline_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Adoption(TypedDict):
    id: str
    adoption_application_id: str
    animal_id: str
    adopter_person_id: str
    credit_application_order: str
    refund_basis: str
    deposit_basis: str
    base_fee_cents: int
    waiver_kind: str
    waiver_applied_cents: int
    sponsorship_applied_cents: int
    adopter_charged_cents: int
    residual_credit_cents: int
    alteration_deposit_cents: int
    alteration_deposit_refunded_cents: int
    adopter_paid_cents: int
    refund_issued_cents: int
    credit_restored_cents: int
    status: str
    fee_status: str
    finalized_at: str
    finalized_by_user_id: str
    returned_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OutcomeRecord(TypedDict):
    id: str
    animal_id: str
    intake_record_id: str
    adoption_id: Optional[str]
    partner_commitment_id: Optional[str]
    counterparty_person_id: Optional[str]
    outcome_type: str
    is_live_release: bool
    recorded_at: str
    reversed_at: Optional[str]
    reversal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Contribution(TypedDict):
    id: str
    donor_person_id: str
    amount_cents: int
    donor_reference: str
    designated_animal_id: Optional[str]
    designated_program: str
    restriction_category: str
    applied_cents: int
    released_cents: int
    available_cents: int
    redesignation_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PartnerCommitment(TypedDict):
    id: str
    organization_id: str
    species: str
    slots_total: int
    slots_drawn: int
    slots_released: int
    slots_open: int
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int
