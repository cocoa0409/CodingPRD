"""Domain types for the Commercial Fitness Equipment Manufacturing API.

Entity TypedDicts, status enumerations and the role enumeration, all named
exactly as the PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles (PRD §2.1) ──────────────────────────────────────────────────────

class UserRole(str, Enum):
    PRODUCT_ENGINEER = "ProductEngineer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    ORDER_PLANNER = "OrderPlanner"
    FACILITY_MANAGER = "FacilityManager"
    SERVICE_PARTNER_TECH = "ServicePartnerTech"
    SERVICE_OPS_ADMIN = "ServiceOpsAdmin"


# ─── Enumerations shared across resources ──────────────────────────────────

class EquipmentCategory(str, Enum):
    CARDIO = "CARDIO"
    STRENGTH = "STRENGTH"
    CONNECTED = "CONNECTED"


class DutyClass(str, Enum):
    LIGHT_COMMERCIAL = "LIGHT_COMMERCIAL"
    FULL_COMMERCIAL = "FULL_COMMERCIAL"
    INSTITUTIONAL = "INSTITUTIONAL"


class FinishCode(str, Enum):
    GRAPHITE = "GRAPHITE"
    ARCTIC_WHITE = "ARCTIC_WHITE"
    CLUB_RED = "CLUB_RED"
    CUSTOM_BRAND_DECAL = "CUSTOM_BRAND_DECAL"
    PREMIUM_UPHOLSTERY = "PREMIUM_UPHOLSTERY"


class ConsolePlatform(str, Enum):
    CONSOLE_T1 = "CONSOLE_T1"
    CONSOLE_T2 = "CONSOLE_T2"
    CONSOLE_X = "CONSOLE_X"


class FreightZone(str, Enum):
    Z1 = "Z1"
    Z2 = "Z2"
    Z3 = "Z3"
    Z4 = "Z4"


class Weekday(str, Enum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"
    SAT = "SAT"
    SUN = "SUN"


class Region(str, Enum):
    R_NORTH = "R_NORTH"
    R_SOUTH = "R_SOUTH"
    R_EAST = "R_EAST"
    R_WEST = "R_WEST"


class ServiceTier(str, Enum):
    BASIC = "BASIC"
    PRO = "PRO"
    PLATINUM = "PLATINUM"


class ConditionGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"


# ─── Status machines ───────────────────────────────────────────────────────

class ModelLifecycleStatus(str, Enum):
    PRE_RELEASE = "PRE_RELEASE"
    ACTIVE = "ACTIVE"
    SUNSET = "SUNSET"
    OBSOLETE = "OBSOLETE"


class RevisionStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_TESTING = "IN_TESTING"
    TEST_FAILED = "TEST_FAILED"
    QUALIFIED = "QUALIFIED"
    RELEASED = "RELEASED"
    SUNSET_ANNOUNCED = "SUNSET_ANNOUNCED"
    OBSOLETE = "OBSOLETE"
    SUPERSEDED = "SUPERSEDED"


class TestRunStatus(str, Enum):
    RESERVED = "RESERVED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class TestRunOutcome(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class FirmwareReleaseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class CertStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CERTIFIED = "CERTIFIED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"


class FacilityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class OrderConfigStatus(str, Enum):
    CONFIGURING = "CONFIGURING"
    CONFIRMED = "CONFIRMED"


class OrderFulfillmentStatus(str, Enum):
    PENDING = "PENDING"
    IN_PRODUCTION = "IN_PRODUCTION"
    STAGED = "STAGED"
    INSTALLING = "INSTALLING"
    INSTALLED = "INSTALLED"


class OrderBillingStatus(str, Enum):
    UNQUOTED = "UNQUOTED"
    QUOTED = "QUOTED"
    INVOICED = "INVOICED"
    SETTLED = "SETTLED"


class PriceVariant(str, Enum):
    NONE = "NONE"
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class OrderLineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class CoverageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OVER_COMMITTED = "OVER_COMMITTED"


class InstallJobStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ON_SITE = "ON_SITE"
    PUNCH_LIST = "PUNCH_LIST"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class AssetStatus(str, Enum):
    BUILT = "BUILT"
    IN_SERVICE = "IN_SERVICE"
    TRADE_IN_RETURNED = "TRADE_IN_RETURNED"
    REFURB_INTAKE = "REFURB_INTAKE"
    REFURB_CERTIFIED = "REFURB_CERTIFIED"
    RESOLD = "RESOLD"
    SCRAPPED = "SCRAPPED"


class ConnectivitySupportStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    SUPPORTED = "SUPPORTED"
    SUNSET_TRACKED = "SUNSET_TRACKED"
    SUPPORT_GAP = "SUPPORT_GAP"
    FIRMWARE_REVOKED = "FIRMWARE_REVOKED"


class PMProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    NEEDS_REVISION = "NEEDS_REVISION"
    TERMINATED = "TERMINATED"


class NeedsRevisionReason(str, Enum):
    CONSOLE_SUPPORT_LOST = "CONSOLE_SUPPORT_LOST"
    FIRMWARE_REVOKED = "FIRMWARE_REVOKED"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ON_HOLD = "ON_HOLD"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class HeldReason(str, Enum):
    PROGRAM_NEEDS_REVISION = "PROGRAM_NEEDS_REVISION"


# ─── Entity shapes ─────────────────────────────────────────────────────────
# Every persisted resource in this API carries id, created_at, updated_at and
# version (PRD §2.5) — all fourteen resource types, without exception.

class EquipmentModel(TypedDict):
    id: str
    name: str
    category: str
    duty_class: str
    unit_list_price_cents: int
    shipping_weight_kg: float
    allowed_finish_codes: List[str]
    console_platform: Optional[str]
    supersedes_model_id: Optional[str]
    connected: bool
    lifecycle_status: str
    released_revision_count: int
    created_at: str
    updated_at: str
    version: int


class ModelRevision(TypedDict):
    id: str
    equipment_model_id: str
    revision_code: str
    target_cycle_count: int
    firmware_baseline_version: Optional[str]
    status: str
    min_required_cycles: int
    rework_count: int
    verified_cycle_count: int
    projected_cycle_count: int
    qualified_at: Optional[str]
    released_at: Optional[str]
    sunset_announced_at: Optional[str]
    firmware_support_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DurabilityTestRig(TypedDict):
    id: str
    name: str
    parallel_station_count: int
    supported_duty_classes: List[str]
    occupied_station_count: int
    created_at: str
    updated_at: str
    version: int


class DurabilityTestRun(TypedDict):
    id: str
    model_revision_id: str
    test_rig_id: str
    window_start: str
    window_end: str
    target_cycles: int
    status: str
    outcome: str
    achieved_cycles: int
    failure_cycle_count: Optional[int]
    superseded_by_rework: bool
    created_at: str
    updated_at: str
    version: int


class FirmwareRelease(TypedDict):
    id: str
    version_string: str
    console_platform: str
    mandatory_security: bool
    status: str
    certified_revision_count: int
    withdrawn_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FirmwareCertification(TypedDict):
    id: str
    firmware_release_id: str
    model_revision_id: str
    test_report_ref: str
    cert_status: str
    submitted_by_user_id: str
    certified_by_user_id: Optional[str]
    certified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Facility(TypedDict):
    id: str
    account_name: str
    freight_zone: str
    credit_limit_cents: int
    install_blackout_weekdays: List[str]
    status: str
    open_order_exposure_cents: int
    tradein_credit_granted_cents: int
    tradein_credit_applied_cents: int
    tradein_credit_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    facility_id: str
    requested_install_window_start: str
    requested_install_window_end: str
    config_status: str
    fulfillment_status: str
    billing_status: str
    line_subtotal_cents: int
    chargeable_weight_kg: float
    install_amount_cents: int
    volume_discount_cents: int
    freight_cents: int
    punch_list_credit_cents: int
    quoted_total_cents: int
    final_total_cents: Optional[int]
    tradein_credit_applied_cents: int
    amount_due_cents: Optional[int]
    price_variant_applied: str
    quoted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    model_revision_id: str
    quantity: int
    finish_codes: List[str]
    layout_zone_label: str
    status: str
    unit_price_cents: int
    extended_price_cents: int
    assets_minted_count: int
    created_at: str
    updated_at: str
    version: int


class ServicePartner(TypedDict):
    id: str
    name: str
    region: str
    certified_categories: List[str]
    certified_technician_count: int
    certified_hours_capacity: float
    training_current_until: str
    committed_hours: float
    coverage_status: str
    spare_stock_received_units: int
    spare_stock_reserved_units: int
    spare_stock_consumed_units: int
    spare_stock_on_hand_units: int
    created_at: str
    updated_at: str
    version: int


class InstallJob(TypedDict):
    id: str
    order_id: str
    service_partner_id: str
    window_start: str
    window_end: str
    estimated_labor_hours: float
    travel_buffer_minutes: int
    status: str
    actual_labor_hours: Optional[float]
    punch_list_open_count: int
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SerializedAsset(TypedDict):
    id: str
    model_revision_id: str
    facility_id: str
    order_line_id: str
    sequence_no: int
    serial_number: str
    status: str
    installed_firmware_release_id: Optional[str]
    warranty_starts_at: Optional[str]
    warranty_expires_at: Optional[str]
    firmware_support_expires_at: Optional[str]
    support_gap_days: int
    connectivity_support_status: str
    annual_usage_hours: Optional[float]
    service_history_count: int
    accrued_service_labor_hours: float
    declared_condition_grade: Optional[str]
    trade_in_valuation_cents: Optional[int]
    refurb_grade: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PMProgram(TypedDict):
    id: str
    facility_id: str
    service_partner_id: str
    tier: str
    visit_interval_days: int
    status: str
    covered_asset_count: int
    annual_labor_hours_committed: float
    needs_revision_reason: Optional[str]
    last_revised_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MaintenanceVisit(TypedDict):
    id: str
    pm_program_id: str
    serialized_asset_id: str
    scheduled_date: str
    reserved_units: int
    status: str
    labor_hours: Optional[float]
    held_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
