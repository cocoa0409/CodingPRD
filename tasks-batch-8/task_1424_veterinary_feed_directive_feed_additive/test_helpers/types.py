"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    INSPECTOR = "Inspector"
    VETERINARIAN = "Veterinarian"
    FEED_MILL_OPERATOR = "FeedMillOperator"
    PRODUCER = "Producer"


class VeterinarianStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class ProducerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEBARRED = "DEBARRED"


class Species(str, Enum):
    CATTLE = "CATTLE"
    SWINE = "SWINE"
    POULTRY = "POULTRY"
    SHEEP = "SHEEP"
    GOAT = "GOAT"


class ProductionClass(str, Enum):
    BEEF = "BEEF"
    DAIRY = "DAIRY"
    LAYER = "LAYER"
    BROILER = "BROILER"
    BREEDING = "BREEDING"


class VcpVerificationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class VfdAuthorizationStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_USED = "PARTIALLY_USED"
    FULLY_USED = "FULLY_USED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


class FeedOrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VALIDATED = "VALIDATED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class FeedShipmentStatus(str, Enum):
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    RETURNED = "RETURNED"
    REJECTED_AT_RECEIPT = "REJECTED_AT_RECEIPT"


class WithdrawalPlanStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    VIOLATED = "VIOLATED"


class DistributorAcknowledgmentStatus(str, Enum):
    PENDING = "PENDING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    LAPSED = "LAPSED"


class ResidueCaseStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    CONFIRMED_VIOLATION = "CONFIRMED_VIOLATION"
    DISMISSED = "DISMISSED"


class SeverityTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class AuditBundleStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETE = "COMPLETE"
    DEFICIENT = "DEFICIENT"


# All entities carry common fields (id, created_at, updated_at, version) per PRD §2.4.

class VeterinaryClinic(TypedDict, total=False):
    id: str
    name: str
    license_number: str
    state_code: str
    compliance_score: int
    audit_ready: bool
    created_at: str
    updated_at: str
    version: int


class Veterinarian(TypedDict, total=False):
    id: str
    clinic_id: str
    full_name: str
    license_number: str
    state_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Producer(TypedDict, total=False):
    id: str
    legal_name: str
    premise_id: str
    state_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AnimalGroup(TypedDict, total=False):
    id: str
    producer_id: str
    species: str
    production_class: str
    head_count: int
    average_weight_lbs: int
    earliest_market_date: str
    created_at: str
    updated_at: str
    version: int


class VfdDrug(TypedDict, total=False):
    id: str
    drug_code: str
    label_name: str
    withdrawal_hours: int
    allowed_species_classes: List[str]
    max_duration_days: int
    prohibited_extra_label: bool
    created_at: str
    updated_at: str
    version: int


class VcpVerification(TypedDict, total=False):
    id: str
    vet_id: str
    producer_id: str
    verified_on: str
    expires_on: str
    status: str
    revocation_reason: str
    created_at: str
    updated_at: str
    version: int


class VfdAuthorization(TypedDict, total=False):
    id: str
    producer_id: str
    animal_group_id: str
    vet_id: str
    drug_id: str
    authorized_animal_count: int
    remaining_animal_count: int
    feed_duration_days: int
    issued_on: str
    expiration_date: str
    extra_label_intended: bool
    status: str
    superseded_by_id: str
    created_at: str
    updated_at: str
    version: int


class FeedMill(TypedDict, total=False):
    id: str
    name: str
    fda_registration: str
    state_code: str
    pending_order_count: int
    created_at: str
    updated_at: str
    version: int


class FeedOrder(TypedDict, total=False):
    id: str
    feed_mill_id: str
    vfd_authorization_id: str
    producer_id: str
    animal_count: int
    tons_of_feed: int
    intended_use_label: str
    status: str
    rejection_reason: str
    created_at: str
    updated_at: str
    version: int


class FeedShipment(TypedDict, total=False):
    id: str
    feed_order_id: str
    tons_shipped: int
    shipped_at: str
    delivered_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WithdrawalPlan(TypedDict, total=False):
    id: str
    feed_order_id: str
    provisional_market_date: str
    final_market_date: str
    withdrawal_window_hours: int
    last_feed_consumed_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DistributorAcknowledgment(TypedDict, total=False):
    id: str
    feed_mill_id: str
    distributor_name: str
    acknowledged_at: str
    covers_drug_id: str
    statement_text: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ResidueCase(TypedDict, total=False):
    id: str
    producer_id: str
    feed_order_id: str
    detected_at: str
    residue_ppb: Optional[int]
    severity_tier: str
    tolerance_ppb: Optional[int]
    investigator_id: str
    status: str
    penalty_score_deduction: int
    created_at: str
    updated_at: str
    version: int


class AuditBundle(TypedDict, total=False):
    id: str
    producer_id: str
    opened_at: str
    window_start: str
    window_end: str
    required_record_count: int
    produced_record_count: int
    status: str
    created_at: str
    updated_at: str
    version: int
