"""Domain enumerations and row shapes for the hazardous waste TSDF API."""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    COMPLIANCE_MANAGER = "ComplianceManager"
    RECEIVING_CLERK = "ReceivingClerk"
    WASTE_APPROVAL_CHEMIST = "WasteApprovalChemist"
    TREATMENT_OPERATOR = "TreatmentOperator"
    REGULATORY_INSPECTOR = "RegulatoryInspector"
    GENERATOR = "Generator"


class PermitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RENEWAL_PENDING = "RENEWAL_PENDING"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class AssuranceTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class InstrumentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class GeneratorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class WasteProfileStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    SAMPLE_FAILED = "SAMPLE_FAILED"
    SAMPLE_PASSED = "SAMPLE_PASSED"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


class SampleType(str, Enum):
    FINGERPRINT = "FINGERPRINT"
    FULL = "FULL"


class SampleResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ManifestStatus(str, Enum):
    EN_ROUTE = "EN_ROUTE"
    DISCREPANT = "DISCREPANT"
    VERIFIED = "VERIFIED"
    CERTIFIED = "CERTIFIED"
    REJECTED_RETURNED = "REJECTED_RETURNED"


class LineStatus(str, Enum):
    DECLARED = "DECLARED"
    RECEIVED = "RECEIVED"
    ACCEPTED = "ACCEPTED"
    ADJUSTED = "ADJUSTED"
    RETURNED = "RETURNED"


class DiscrepancyType(str, Enum):
    NONE = "NONE"
    QUANTITY_SIGNIFICANT = "QUANTITY_SIGNIFICANT"
    COUNT_MISMATCH = "COUNT_MISMATCH"
    UNDOCUMENTED = "UNDOCUMENTED"


class CustodyState(str, Enum):
    FILLING = "FILLING"
    SEALED = "SEALED"
    STAGED = "STAGED"
    EMPTIED = "EMPTIED"
    VOIDED = "VOIDED"


class ComplianceState(str, Enum):
    COMPLIANT = "COMPLIANT"
    DEFICIENT = "DEFICIENT"
    CONDEMNED = "CONDEMNED"


class UnitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


class UnitPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class UnitType(str, Enum):
    CONTAINER_AREA = "CONTAINER_AREA"
    TANK_SYSTEM = "TANK_SYSTEM"
    TEN_DAY_TRANSFER = "TEN_DAY_TRANSFER"


class CompatibilityClass(str, Enum):
    ACID = "ACID"
    ALKALINE = "ALKALINE"
    OXIDIZER = "OXIDIZER"
    CYANIDE_BEARING = "CYANIDE_BEARING"
    WATER_REACTIVE = "WATER_REACTIVE"
    ORGANIC_SOLVENT = "ORGANIC_SOLVENT"


class TreatmentMethod(str, Enum):
    INCINERATION = "INCINERATION"
    STABILIZATION = "STABILIZATION"
    NEUTRALIZATION = "NEUTRALIZATION"
    FUEL_BLENDING = "FUEL_BLENDING"
    MACROENCAPSULATION = "MACROENCAPSULATION"


class BatchStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_TREATMENT = "IN_TREATMENT"
    TREATED = "TREATED"
    VERIFIED = "VERIFIED"
    LDR_FAILED = "LDR_FAILED"
    HELD = "HELD"
    ABORTED = "ABORTED"


class LdrResult(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


class RepairOrderStatus(str, Enum):
    OPEN = "OPEN"
    FIRST_ATTEMPTED = "FIRST_ATTEMPTED"
    DELAYED = "DELAYED"
    REPAIRED = "REPAIRED"


class FindingClass(str, Enum):
    MINOR = "MINOR"
    SIGNIFICANT = "SIGNIFICANT"
    SNC = "SNC"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    RESPONDED = "RESPONDED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


class Facility(TypedDict, total=False):
    id: str
    name: str
    epa_id: str
    permit_number: str
    permit_status: str
    permit_expires_at: str
    permitted_methods: List[str]
    max_concurrent_treatment_batches: int
    post_closure_cost_cents: int
    held_mass_kg: float
    unallocated_receipt_kg: float
    returned_mass_kg: float
    treated_residue_kg: float
    destroyed_mass_kg: float
    received_mass_kg: float
    mass_ledger_kg: float
    closure_base_cost_cents: int
    assurance_tier: str
    closure_cost_estimate_cents: int
    corrective_action_reserve_cents: int
    active_treatment_liability_cents: int
    required_assurance_cents: int
    posted_assurance_cents: int
    assurance_shortfall_cents: int
    open_snc_finding_count: int
    renewal_requested_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StorageUnit(TypedDict, total=False):
    id: str
    facility_id: str
    unit_code: str
    unit_type: str
    permitted_capacity_kg: float
    aisle_width_cm: float
    effective_aisle_width_cm: float
    aisle_free_container_capacity: int
    inspection_frequency_days: int
    allowed_compatibility_classes: List[str]
    air_emission_control_level: str
    containment_volume_l: float
    status: str
    posture: str
    closure_plan_ref: Optional[str]
    container_count: int
    stored_kg: float
    reserved_kg: float
    utilization_pct: float
    last_inspection_at: str
    inspection_overdue: bool
    created_at: str
    updated_at: str
    version: int


class Container(TypedDict, total=False):
    id: str
    manifest_line_id: str
    storage_unit_id: str
    waste_profile_id: str
    container_type: str
    capacity_kg: float
    net_weight_kg: float
    fill_ratio: float
    accumulation_start_date: str
    accumulation_days: int
    ten_day_overdue: bool
    label_waste_codes: List[str]
    label_hazard_class: str
    label_accumulation_start_marked: bool
    custody_state: str
    compliance_state: str
    last_finding_code: Optional[str]
    treatment_batch_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
