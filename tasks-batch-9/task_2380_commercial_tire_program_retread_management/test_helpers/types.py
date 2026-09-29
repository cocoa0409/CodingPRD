"""Domain types for the Commercial Tire Program & Retread Management API.

Status enums, role enum and entity TypedDicts, all named exactly as the PRD
names them. Two resources — the tire survey and the casing credit ledger entry —
are append-only observations and carry only ``id`` and ``created_at``; their
TypedDicts deliberately omit ``updated_at`` and ``version``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------

class UserRole(str, Enum):
    DEALER_ADMIN = "DealerAdmin"
    FLEET_MANAGER = "FleetManager"
    TIRE_TECHNICIAN = "TireTechnician"
    CASING_INSPECTOR = "CasingInspector"
    PLANT_SCHEDULER = "PlantScheduler"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    BILLING_CLERK = "BillingClerk"
    DISPATCH_COORDINATOR = "DispatchCoordinator"


ALL_ROLE_NAMES = [r.value for r in UserRole]


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------

class FleetAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AccountType(str, Enum):
    SINGLE_LOCATION = "SINGLE_LOCATION"
    NATIONAL_ACCOUNT = "NATIONAL_ACCOUNT"


class BillingMode(str, Enum):
    DIRECT = "DIRECT"
    CROSS_LOCATION = "CROSS_LOCATION"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class WheelPosition(str, Enum):
    STEER = "STEER"
    DRIVE = "DRIVE"
    TRAILER = "TRAILER"


class VehicleType(str, Enum):
    TRACTOR = "TRACTOR"
    TRAILER = "TRAILER"
    STRAIGHT_TRUCK = "STRAIGHT_TRUCK"


class VehicleStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class CasingStatus(str, Enum):
    ON_WHEEL = "ON_WHEEL"
    COLLECTED = "COLLECTED"
    INSPECTED = "INSPECTED"
    REJECTED = "REJECTED"
    RETREAD_QUEUED = "RETREAD_QUEUED"
    IN_RETREAD = "IN_RETREAD"
    RETREADED = "RETREADED"
    SCRAPPED = "SCRAPPED"


class InspectionGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    REJECT = "REJECT"


class TireAssetStatus(str, Enum):
    IN_INVENTORY = "IN_INVENTORY"
    MOUNTED = "MOUNTED"
    PULL_FLAGGED = "PULL_FLAGGED"
    PULLED = "PULLED"
    SCRAPPED = "SCRAPPED"


class SurveyFindingCode(str, Enum):
    TREAD_BELOW_MIN = "TREAD_BELOW_MIN"
    TREAD_AT_PULL_POINT = "TREAD_AT_PULL_POINT"
    PRESSURE_DEVIATION = "PRESSURE_DEVIATION"
    COMPLIANT = "COMPLIANT"


class CreditEntryType(str, Enum):
    ACCRUAL = "ACCRUAL"
    REVERSAL = "REVERSAL"
    ADJUSTMENT = "ADJUSTMENT"
    APPLICATION = "APPLICATION"
    EXPIRY = "EXPIRY"


class CreditSourceEntityType(str, Enum):
    CASING = "CASING"
    RETREAD_JOB = "RETREAD_JOB"
    SCRAP_MANIFEST = "SCRAP_MANIFEST"
    CROSS_LOCATION_INVOICE = "CROSS_LOCATION_INVOICE"


class RetreadLineStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DOWN = "DOWN"


class RetreadJobStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PRODUCTION = "IN_PRODUCTION"
    COMPLETED = "COMPLETED"
    FAILED_CURE = "FAILED_CURE"
    CANCELLED = "CANCELLED"


class CureFailureReason(str, Enum):
    CURE_DEFECT = "CURE_DEFECT"
    LINE_FAULT = "LINE_FAULT"
    CASING_FAILURE = "CASING_FAILURE"


class CertificationLevel(str, Enum):
    LEVEL_1 = "LEVEL_1"
    LEVEL_2 = "LEVEL_2"
    TIA_CERTIFIED = "TIA_CERTIFIED"


class TechnicianStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_CALL = "ON_CALL"
    OFF_DUTY = "OFF_DUTY"


class CallPriority(str, Enum):
    NORMAL = "NORMAL"
    EMERGENCY = "EMERGENCY"


class DispatchStatus(str, Enum):
    OPEN = "OPEN"
    DISPATCHED = "DISPATCHED"
    ON_SITE = "ON_SITE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    BILLED_TO_NATIONAL = "BILLED_TO_NATIONAL"
    SETTLED = "SETTLED"
    NON_BILLABLE = "NON_BILLABLE"


class ManifestStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    TRANSPORTED = "TRANSPORTED"
    CERTIFIED_DESTROYED = "CERTIFIED_DESTROYED"
    VOIDED = "VOIDED"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"


class CostPerMileVariant(str, Enum):
    HISTORICAL_ACTUAL = "HISTORICAL_ACTUAL"
    FORWARD_PROJECTED = "FORWARD_PROJECTED"


# --------------------------------------------------------------------------
# Entity TypedDicts — full common set (id, created_at, updated_at, version)
# --------------------------------------------------------------------------

class ServiceLocation(TypedDict):
    id: str
    name: str
    location_code: str
    state_code: str
    road_service_response_minutes_committed: int
    scrap_permit_number: str
    scrap_permit_expires_on: str
    is_retread_plant: bool
    casings_in_holding_count: int
    created_at: str
    updated_at: str
    version: int


class FleetAccount(TypedDict):
    id: str
    name: str
    account_type: str
    home_location_id: str
    billing_mode: str
    status: str
    status_reason: Optional[str]
    casing_credit_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class NationalAgreement(TypedDict):
    id: str
    fleet_account_id: str
    agreement_code: str
    effective_from: str
    effective_to: str
    tier_discount_pct: float
    casing_credit_rate_cents: int
    emergency_response_minutes: int
    emergency_labor_rate_cents_per_hour: int
    status: str
    activated_at: Optional[str]
    terminated_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TirePolicy(TypedDict):
    id: str
    fleet_account_id: str
    position: str
    target_pressure_psi: int
    pressure_tolerance_pct: float
    min_tread_depth_32nds: int
    pull_point_32nds: int
    max_retread_count: int
    approved_brands: List[str]
    new_tire_tread_depth_32nds: int
    casing_spec_code: str
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    fleet_account_id: str
    unit_number: str
    vehicle_type: str
    current_odometer_miles: int
    last_odometer_reading_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Casing(TypedDict):
    id: str
    fleet_account_id: str
    casing_serial: str
    brand: str
    casing_spec_code: str
    intended_position: str
    scrap_weight_lbs: int
    retread_count: int
    status: str
    inspection_grade: Optional[str]
    inspected_by_user_id: Optional[str]
    collected_at_location_id: Optional[str]
    scrap_manifest_id: Optional[str]
    rejection_reason: Optional[str]
    provisional_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class TireAsset(TypedDict):
    id: str
    fleet_account_id: str
    casing_id: str
    brand: str
    cost_basis_cents: int
    status: str
    vehicle_id: Optional[str]
    position: Optional[str]
    mounted_at: Optional[str]
    odometer_at_mount: Optional[int]
    tread_depth_at_mount_32nds: Optional[int]
    current_tread_depth_32nds: Optional[int]
    accumulated_miles: int
    pull_reason: Optional[str]
    replaced_tire_asset_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RetreadLine(TypedDict):
    id: str
    service_location_id: str
    line_code: str
    cure_cooldown_minutes: int
    status: str
    booked_minutes: int
    created_at: str
    updated_at: str
    version: int


class RetreadJob(TypedDict):
    id: str
    casing_id: str
    retread_line_id: str
    tread_design_code: str
    scheduled_start_at: str
    scheduled_end_at: str
    slot_minutes: int
    status: str
    grade_at_scheduling: Optional[str]
    retread_count_at_scheduling: Optional[int]
    reschedule_count: int
    started_at: Optional[str]
    completed_at: Optional[str]
    warranty_months: Optional[int]
    warranty_expires_on: Optional[str]
    produced_tire_asset_id: Optional[str]
    failure_reason: Optional[str]
    note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict):
    id: str
    service_location_id: str
    name: str
    certification_level: str
    status: str
    completed_call_count: int
    created_at: str
    updated_at: str
    version: int


class RoadServiceCall(TypedDict):
    id: str
    fleet_account_id: str
    vehicle_id: str
    service_location_id: str
    priority: str
    complaint: str
    reported_at: str
    dispatch_status: str
    billing_status: str
    technician_id: Optional[str]
    dispatched_at: Optional[str]
    dispatch_miles: Optional[int]
    arrived_at: Optional[str]
    committed_response_minutes: Optional[int]
    actual_response_minutes: Optional[int]
    sla_met: Optional[bool]
    closed_at: Optional[str]
    labor_hours: Optional[float]
    gross_cents: Optional[int]
    sla_credit_cents: Optional[int]
    invoice_total_cents: Optional[int]
    cross_location_invoice_id: Optional[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScrapManifest(TypedDict):
    id: str
    service_location_id: str
    manifest_number: str
    hauler_permit_number: str
    hauler_capacity_lbs: int
    status: str
    tire_count: int
    total_weight_lbs: int
    signed_by_user_id: Optional[str]
    signed_at: Optional[str]
    transported_at: Optional[str]
    hauler_vehicle_id: Optional[str]
    certified_by_user_id: Optional[str]
    certified_at: Optional[str]
    destruction_facility_code: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CrossLocationInvoice(TypedDict):
    id: str
    fleet_account_id: str
    national_agreement_id: str
    billing_period_start: str
    billing_period_end: str
    status: str
    line_count: int
    subtotal_cents: int
    discount_cents: int
    net_before_credit_cents: int
    credit_applied_cents: int
    total_cents: int
    paid_amount_cents: Optional[int]
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Append-only observations — ONLY id + created_at, no updated_at, no version
# --------------------------------------------------------------------------

class TireSurvey(TypedDict):
    id: str
    tire_asset_id: str
    surveyed_at: str
    pressure_psi: float
    tread_depth_32nds: int
    odometer_miles: int
    pressure_deviation_pct: float
    finding_code: str
    pull_recommended: bool
    surveyed_by_user_id: str
    created_at: str


class CasingCreditEntry(TypedDict):
    id: str
    fleet_account_id: str
    casing_id: Optional[str]
    entry_type: str
    amount_cents: int
    source_entity_type: str
    source_entity_id: str
    posted_at: str
    memo: str
    created_at: str
