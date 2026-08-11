"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    OWNER = "Owner"
    VETERINARIAN = "Veterinarian"
    PHARMACIST = "Pharmacist"
    PHARMACY_TECH = "PharmacyTech"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    INSURANCE_ADJUSTER = "InsuranceAdjuster"
    PHARMACY_ADMIN = "PharmacyAdmin"


class OwnerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PetStatus(str, Enum):
    ALIVE = "ALIVE"
    DECEASED = "DECEASED"


class PetSpecies(str, Enum):
    DOG = "DOG"
    CAT = "CAT"
    BIRD = "BIRD"
    REPTILE = "REPTILE"
    OTHER = "OTHER"


class VeterinarianStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class DrugSchedule(str, Enum):
    NON_CONTROLLED = "NON_CONTROLLED"
    C_II = "C_II"
    C_III = "C_III"
    C_IV = "C_IV"
    C_V = "C_V"


class CatalogStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class DosageForm(str, Enum):
    SUSPENSION = "SUSPENSION"
    CAPSULE = "CAPSULE"
    CHEW = "CHEW"
    TOPICAL = "TOPICAL"
    INJECTABLE = "INJECTABLE"


class PrescriptionStatus(str, Enum):
    RECEIVED = "RECEIVED"
    VET_VERIFICATION_PENDING = "VET_VERIFICATION_PENDING"
    CLARIFICATION_REQUESTED = "CLARIFICATION_REQUESTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    EXHAUSTED = "EXHAUSTED"


class CompoundOrderStatus(str, Enum):
    CREATED = "CREATED"
    ALLOCATED = "ALLOCATED"
    COMPOUNDING = "COMPOUNDING"
    FLAVORING = "FLAVORING"
    REWORK = "REWORK"
    QA_PENDING = "QA_PENDING"
    READY_TO_DISPATCH = "READY_TO_DISPATCH"
    RECALL_HOLD = "RECALL_HOLD"
    DISPENSED = "DISPENSED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class PaidVia(str, Enum):
    CARD = "CARD"
    WELLNESS_CREDIT = "WELLNESS_CREDIT"


class LotStatus(str, Enum):
    ACTIVE = "ACTIVE"
    QUARANTINED = "QUARANTINED"
    RECALLED = "RECALLED"
    EXPIRED = "EXPIRED"
    EXHAUSTED = "EXHAUSTED"


class LotAllocationStatus(str, Enum):
    RESERVED = "RESERVED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"
    WASTED = "WASTED"


class BenchStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MAINTENANCE = "MAINTENANCE"


class BenchReservationStatus(str, Enum):
    BOOKED = "BOOKED"
    IN_USE = "IN_USE"
    COMPLETED = "COMPLETED"
    RELEASED = "RELEASED"


class TransitStatus(str, Enum):
    LABEL_CREATED = "LABEL_CREATED"
    PICKED_UP = "PICKED_UP"
    IN_TRANSIT = "IN_TRANSIT"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    DELIVERY_EXCEPTION = "DELIVERY_EXCEPTION"
    RETURNED_TO_PHARMACY = "RETURNED_TO_PHARMACY"
    QUARANTINED = "QUARANTINED"


class ColdChainStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    COMPLIANT = "COMPLIANT"
    EXCURSION_WATCH = "EXCURSION_WATCH"
    EXCURSION_BREACH = "EXCURSION_BREACH"


class ServiceLevel(str, Enum):
    STANDARD = "STANDARD"
    EXPRESS = "EXPRESS"
    OVERNIGHT = "OVERNIGHT"


class DestinationZone(str, Enum):
    Z1 = "Z1"
    Z2 = "Z2"
    Z3 = "Z3"


class CoolerStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    CONDITIONING = "CONDITIONING"
    RETIRED = "RETIRED"


class WellnessPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class EnrollmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class PolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    APPEALED = "APPEALED"
    PAID = "PAID"


class AutoShipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class ControlledEntryType(str, Enum):
    RECEIVE = "RECEIVE"
    DISPENSE = "DISPENSE"
    WASTE = "WASTE"
    RETURN = "RETURN"
    ADJUST = "ADJUST"


class RecallScope(str, Enum):
    LOT = "LOT"
    CATALOG_ITEM = "CATALOG_ITEM"


class RecallSeverity(str, Enum):
    CLASS_I = "CLASS_I"
    CLASS_II = "CLASS_II"
    CLASS_III = "CLASS_III"


class RecallStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"


class RecallTaskStatus(str, Enum):
    PENDING = "PENDING"
    NOTIFIED = "NOTIFIED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    FAILED = "FAILED"


# --- Entity TypedDicts (common_fields entities carry id + created_at + updated_at + version) ---

class Owner(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    phone: str
    ship_to_address: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Pet(TypedDict, total=False):
    id: str
    owner_id: str
    name: str
    species: str
    weight_kg: float
    allergies: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Veterinarian(TypedDict, total=False):
    id: str
    full_name: str
    license_number: str
    dea_registration_number: Optional[str]
    practice_state: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DrugCatalogItem(TypedDict, total=False):
    id: str
    drug_name: str
    schedule: str
    requires_cold_chain: bool
    cold_chain_min_celsius: float
    cold_chain_max_celsius: float
    unit_cost_cents: int
    default_beyond_use_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Flavoring(TypedDict, total=False):
    id: str
    name: str
    allergen_tags: List[str]
    surcharge_cents: int
    compatible_species: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Formula(TypedDict, total=False):
    id: str
    drug_catalog_item_id: str
    name: str
    dosage_form: str
    strength_mg_per_ml: float
    beyond_use_days: int
    base_compounding_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Prescription(TypedDict, total=False):
    id: str
    pet_id: str
    owner_id: str
    veterinarian_id: str
    formula_id: str
    quantity: int
    days_supply: int
    refills_authorized: int
    refills_remaining: int
    directions: str
    written_date: str
    expiration_date: str
    is_controlled: bool
    schedule_snapshot: str
    status: str
    clarification_count: int
    created_at: str
    updated_at: str
    version: int


class CompoundOrder(TypedDict, total=False):
    id: str
    prescription_id: str
    owner_id: str
    flavoring_id: Optional[str]
    is_refill: bool
    fill_number: int
    supersedes_order_id: Optional[str]
    status: str
    hold_origin_state: Optional[str]
    payment_status: str
    paid_via: Optional[str]
    quantity_snapshot: int
    provisional_price_cents: int
    final_price_cents: Optional[int]
    compounding_pharmacist_id: Optional[str]
    qa_pharmacist_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict, total=False):
    id: str
    drug_catalog_item_id: str
    lot_number: str
    received_qty: int
    qty_on_hand: int
    qty_reserved: int
    qty_dispensed: int
    qty_wasted: int
    unit_cost_cents: int
    expiration_date: str
    status: str
    recall_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LotAllocation(TypedDict, total=False):
    id: str
    compound_order_id: str
    lot_id: str
    qty_allocated: int
    qty_consumed: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CompoundingBench(TypedDict, total=False):
    id: str
    bench_code: str
    supports_controlled: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class BenchReservation(TypedDict, total=False):
    id: str
    bench_id: str
    compound_order_id: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict, total=False):
    id: str
    compound_order_id: str
    cooler_asset_id: Optional[str]
    carrier: str
    service_level: str
    destination_zone: str
    transit_status: str
    cold_chain_status: str
    required_temp_min_celsius: float
    required_temp_max_celsius: float
    excursion_minutes_accumulated: int
    shipping_fee_cents: int
    last_reading_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only (PRD §2.4): only id + created_at, NO updated_at, NO version.
class TemperatureReading(TypedDict, total=False):
    id: str
    shipment_id: str
    recorded_at: str
    temp_celsius: float
    created_at: str


class CoolerAsset(TypedDict, total=False):
    id: str
    cooler_code: str
    status: str
    conditioning_available_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WellnessPlan(TypedDict, total=False):
    id: str
    name: str
    monthly_fee_cents: int
    included_refill_credits: int
    credit_value_cents: int
    discount_pct: float
    covers_controlled: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class WellnessEnrollment(TypedDict, total=False):
    id: str
    owner_id: str
    pet_id: str
    plan_id: str
    status: str
    credits_remaining: int
    credits_consumed: int
    cycle_anchor_date: str
    created_at: str
    updated_at: str
    version: int


class InsurancePolicy(TypedDict, total=False):
    id: str
    owner_id: str
    pet_id: str
    insurer_name: str
    policy_number: str
    deductible_cents: int
    deductible_met_cents: int
    coverage_pct: float
    annual_limit_cents: int
    annual_used_cents: int
    renewal_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InsuranceClaim(TypedDict, total=False):
    id: str
    policy_id: str
    compound_order_id: str
    status: str
    claimed_amount_cents: int
    estimate_cents: int
    approved_amount_cents: Optional[int]
    deductible_applied_cents: Optional[int]
    appeal_count: int
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AutoShipSchedule(TypedDict, total=False):
    id: str
    prescription_id: str
    enrollment_id: Optional[str]
    interval_days: int
    next_run_date: str
    status: str
    consecutive_failures: int
    last_fired_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only (PRD §2.4): only id + created_at, NO updated_at, NO version.
class ControlledSubstanceEntry(TypedDict, total=False):
    id: str
    lot_id: str
    compound_order_id: Optional[str]
    entry_type: str
    qty_delta: int
    running_balance: int
    recorded_by: str
    recorded_at: str
    created_at: str


class Recall(TypedDict, total=False):
    id: str
    scope: str
    lot_id: Optional[str]
    drug_catalog_item_id: Optional[str]
    reason: str
    severity: str
    status: str
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecallTask(TypedDict, total=False):
    id: str
    recall_id: str
    compound_order_id: str
    owner_id: str
    channel: str
    status: str
    created_at: str
    updated_at: str
    version: int
