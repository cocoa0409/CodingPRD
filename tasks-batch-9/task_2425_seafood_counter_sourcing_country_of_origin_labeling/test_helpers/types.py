"""Domain types for the Seafood Counter Cool Ops API: status enums and entity shapes.

Per PRD §2.4 most records carry `id`, `created_at`, `updated_at` and `version`;
a `Species` record and an `IceBedReading` carry only `id` and `created_at`.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    CHAIN_ADMIN = "ChainAdmin"
    SEAFOOD_MANAGER = "SeafoodManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    MERCHANDISING_LEAD = "MerchandisingLead"
    SUPPLIER_REP = "SupplierRep"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class CounterPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    SUSPENDED = "SUSPENDED"


class SupplierStatus(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class LotIntakeStatus(str, Enum):
    RECEIVED = "RECEIVED"
    CASED = "CASED"
    HELD = "HELD"
    DEPLETED = "DEPLETED"
    DISPOSED = "DISPOSED"


class LotLabelStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    SAMPLED = "SAMPLED"
    VERIFIED = "VERIFIED"
    MISMATCHED = "MISMATCHED"
    RELABELED = "RELABELED"


class LotChargebackStatus(str, Enum):
    NONE = "NONE"
    ASSESSED = "ASSESSED"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class HarvestMethod(str, Enum):
    WILD_NET = "WILD_NET"
    WILD_LONGLINE = "WILD_LONGLINE"
    WILD_TRAP = "WILD_TRAP"
    AQUACULTURE_POND = "AQUACULTURE_POND"
    AQUACULTURE_PEN = "AQUACULTURE_PEN"


class ProductionMethod(str, Enum):
    WILD = "WILD"
    FARMED = "FARMED"


class CaseLabelStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    WITHDRAWN = "WITHDRAWN"


class WithdrawReason(str, Enum):
    MANUAL = "MANUAL"
    SUPERSEDED = "SUPERSEDED"
    SPECIES_MISMATCH = "SPECIES_MISMATCH"
    COLD_CHAIN_HOLD = "COLD_CHAIN_HOLD"
    CLAIM_REVOKED = "CLAIM_REVOKED"


class AdItemStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    CLOSED = "CLOSED"
    RETRACTED = "RETRACTED"
    REJECTED = "REJECTED"


class CoolReviewStatus(str, Enum):
    COOL_PENDING = "COOL_PENDING"
    COOL_CLEARED = "COOL_CLEARED"
    COOL_REJECTED = "COOL_REJECTED"


class ClaimReviewStatus(str, Enum):
    CLAIM_PENDING = "CLAIM_PENDING"
    CLAIM_CLEARED = "CLAIM_CLEARED"
    CLAIM_REJECTED = "CLAIM_REJECTED"


class RetractReason(str, Enum):
    MANUAL = "MANUAL"
    LABEL_WITHDRAWN = "LABEL_WITHDRAWN"
    CLAIM_REVOKED = "CLAIM_REVOKED"


class ExcursionStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED_RELEASED = "RESOLVED_RELEASED"
    RESOLVED_DISPOSED = "RESOLVED_DISPOSED"


class ExcursionSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class ExcursionResolution(str, Enum):
    RELEASE = "RELEASE"
    DISPOSE = "DISPOSE"


class SampleStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_LAB = "IN_LAB"
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    DISPUTED = "DISPUTED"
    VOIDED = "VOIDED"


class SimpDocumentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    DEFICIENT = "DEFICIENT"


class CertificationStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class ShrinkStatus(str, Enum):
    VALUED = "VALUED"
    CONVERSION_APPROVED = "CONVERSION_APPROVED"
    CONVERTED = "CONVERTED"
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class ShrinkReason(str, Enum):
    UNSOLD_FRESH = "UNSOLD_FRESH"
    MISLABEL_DESTRUCTION = "MISLABEL_DESTRUCTION"
    COLD_CHAIN_DISPOSAL = "COLD_CHAIN_DISPOSAL"


class ViolationStatus(str, Enum):
    OPEN = "OPEN"
    CURED = "CURED"
    EXPUNGED = "EXPUNGED"


class ViolationCategory(str, Enum):
    SPECIES_SUBSTITUTION = "SPECIES_SUBSTITUTION"
    COOL_MISSING = "COOL_MISSING"
    FROZEN_DISCLOSURE = "FROZEN_DISCLOSURE"
    SIMP_DEFICIENT = "SIMP_DEFICIENT"
    COLD_CHAIN = "COLD_CHAIN"
    UNSUBSTANTIATED_CLAIM = "UNSUBSTANTIATED_CLAIM"


# --------------------------------------------------------------------------
# Entity shapes
# --------------------------------------------------------------------------
class Counter(TypedDict):
    id: str
    store_number: str
    department_name: str
    case_slot_count: int
    posture: str
    verification_cycle_index: int
    open_excursion_count: int
    violation_points: int
    last_cycle_required_samples: int
    last_cycle_max_supplier_risk_index: float
    shrink_gross_cents: int
    shrink_net_cents: int
    recovered_conversion_cents: int
    created_at: str
    updated_at: str
    version: int


class Supplier(TypedDict):
    id: str
    name: str
    permit_number: str
    status: str
    lifetime_sample_count: int
    lifetime_mismatch_count: int
    substitution_risk_index_rolling: float
    substitution_risk_index_lifetime: float
    chargeback_assessed_total_cents: int
    chargeback_outstanding_cents: int
    chargeback_settled_cents: int
    chargeback_reversed_cents: int
    created_at: str
    updated_at: str
    version: int


# Immutable configuration data: only id + created_at (PRD §2.4).
class Species(TypedDict):
    id: str
    market_name: str
    scientific_name: str
    acceptable_market_names: List[str]
    simp_covered: bool
    high_risk_substitution: bool
    sustainability_program_eligible: bool
    created_at: str


class SupplierLot(TypedDict):
    id: str
    counter_id: str
    supplier_id: str
    species_id: str
    lot_code: str
    harvest_method: str
    production_method: str
    origin_country_code: str
    processing_country_code: Optional[str]
    previously_frozen: bool
    fresh_claim: bool
    received_weight_kg: float
    remaining_weight_kg: float
    unit_cost_cents_per_kg: int
    retail_price_cents_per_kg: int
    cooked_retail_price_cents_per_kg: int
    received_at: str
    intake_status: str
    label_status: str
    chargeback_status: str
    chargeback_assessed_cents: int
    case_slot: Optional[int]
    cased_at: Optional[str]
    vacated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CaseLabel(TypedDict):
    id: str
    lot_id: str
    certification_id: Optional[str]
    display_market_name: str
    production_method_statement: str
    origin_statement: str
    frozen_disclosure_statement: str
    sustainability_claim_text: Optional[str]
    status: str
    published_at: str
    withdraw_reason: Optional[str]
    withdrawn_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AdvertisedItem(TypedDict):
    id: str
    counter_id: str
    lot_id: str
    certification_id: Optional[str]
    headline: str
    ad_start_at: str
    ad_end_at: str
    status: str
    cool_review_status: str
    claim_review_status: str
    cool_statement: Optional[str]
    cool_reviewer_user_id: Optional[str]
    claim_reviewer_user_id: Optional[str]
    retract_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only observation: only id + created_at (PRD §2.4).
class IceBedReading(TypedDict):
    id: str
    counter_id: str
    case_slot: int
    reading_at: str
    temperature_c: float
    taken_by_user_id: str
    breach: bool
    created_at: str


class ColdChainExcursion(TypedDict):
    id: str
    counter_id: str
    case_slot: int
    started_at: str
    ended_at: str
    exposure_minutes: int
    peak_temperature_c: float
    severity: str
    status: str
    resolution: Optional[str]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VerificationSample(TypedDict):
    id: str
    lot_id: str
    sampled_weight_g: float
    cycle_index: int
    status: str
    observed_species_id: Optional[str]
    lab_reference: Optional[str]
    dispute_reason: Optional[str]
    retest_count: int
    result_recorded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SimpDocument(TypedDict):
    id: str
    lot_id: str
    harvesting_vessel_name: str
    harvest_date: str
    landing_date: str
    chain_of_custody_ref: str
    status: str
    amendment_count: int
    review_note: Optional[str]
    reviewed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SustainabilityCertification(TypedDict):
    id: str
    counter_id: str
    supplier_id: str
    species_id: str
    program_name: str
    certificate_number: str
    valid_from: str
    valid_until: str
    claim_text: str
    status: str
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShrinkEvent(TypedDict):
    id: str
    lot_id: str
    reason: str
    shrink_weight_kg: float
    conversion_requested_kg: float
    approved_conversion_kg: float
    allowance_kg: float
    cook_yield_kg: float
    provisional_value_cents: int
    final_value_cents: int
    recovery_credit_cents: int
    status: str
    posted_at: Optional[str]
    reversed_at: Optional[str]
    reversal_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplianceViolation(TypedDict):
    id: str
    counter_id: str
    lot_id: Optional[str]
    category: str
    points: int
    detail: str
    status: str
    cure_note: Optional[str]
    expunge_note: Optional[str]
    cured_at: Optional[str]
    expunged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
