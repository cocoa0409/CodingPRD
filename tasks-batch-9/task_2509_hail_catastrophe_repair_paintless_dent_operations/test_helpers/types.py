"""Domain types for the Hail Catastrophe PDR Ops API.

Status enumerations, role enumeration and entity TypedDicts, all named exactly
as the PRD names them.

Per PRD §2.5 every resource carries `id` and `created_at`; most also carry
`updated_at` and `version`.  Permit, DamageLine and QualityInspection are the
three exceptions and carry **only** `id` and `created_at` — their TypedDicts
below deliberately omit `updated_at` and `version`.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Role enumeration (PRD §2.1) ──────────────────────────────────────────────

class UserRole(str, Enum):
    CATASTROPHE_DIRECTOR = "CatastropheDirector"
    PERMIT_OFFICER = "PermitOfficer"
    CREW_COORDINATOR = "CrewCoordinator"
    INTAKE_ADVISOR = "IntakeAdvisor"
    SHOP_ESTIMATOR = "ShopEstimator"
    PDR_TECHNICIAN = "PdrTechnician"
    QUALITY_INSPECTOR = "QualityInspector"
    INSURER_ADJUSTER = "InsurerAdjuster"
    BILLING_COORDINATOR = "BillingCoordinator"


# ─── Status enumerations ──────────────────────────────────────────────────────

class StormEventStatus(str, Enum):
    EVALUATING = "EVALUATING"
    TARGETED = "TARGETED"
    DECLINED = "DECLINED"
    ACTIVE = "ACTIVE"
    DEMOBILIZING = "DEMOBILIZING"
    CLOSED = "CLOSED"


class SwathConfidence(str, Enum):
    MODELED = "MODELED"
    GROUND_TRUTHED = "GROUND_TRUTHED"


class StormEventDecision(str, Enum):
    TARGET = "TARGET"
    DECLINE = "DECLINE"


class FacilityStatus(str, Enum):
    SETUP = "SETUP"
    COMMISSIONED = "COMMISSIONED"
    SUSPENDED = "SUSPENDED"
    DEMOBILIZED = "DEMOBILIZED"


class FacilityPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class PayModel(str, Enum):
    FLAT = "FLAT"
    POOLED = "POOLED"


class PermitType(str, Enum):
    TEMP_BUSINESS_LICENSE = "TEMP_BUSINESS_LICENSE"
    ZONING_USE = "ZONING_USE"
    FIRE_OCCUPANCY = "FIRE_OCCUPANCY"
    SIGNAGE = "SIGNAGE"


class PermitStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class PermitDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


class SkillTier(str, Enum):
    APPRENTICE = "APPRENTICE"
    JOURNEYMAN = "JOURNEYMAN"
    MASTER = "MASTER"


class DeploymentState(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEPLOYED = "DEPLOYED"


class CrewDeploymentStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    ON_SITE = "ON_SITE"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"


class RateAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class VehicleRepairStatus(str, Enum):
    INTAKE = "INTAKE"
    ESTIMATED = "ESTIMATED"
    TRIAGED = "TRIAGED"
    IN_REPAIR = "IN_REPAIR"
    QC_PENDING = "QC_PENDING"
    QC_FAILED = "QC_FAILED"
    READY = "READY"
    TOTAL_LOSS_PENDING = "TOTAL_LOSS_PENDING"
    RELEASED = "RELEASED"
    TOWED_OUT = "TOWED_OUT"


class VehicleBillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    AUTHORIZED = "AUTHORIZED"
    BILLED = "BILLED"
    PAID = "PAID"


class BillingAction(str, Enum):
    AUTHORIZE = "AUTHORIZE"
    VOID_AUTHORIZATION = "VOID_AUTHORIZATION"
    SUBMIT_BILL = "SUBMIT_BILL"
    SETTLE = "SETTLE"


class TriageDisposition(str, Enum):
    PDR_REPAIR = "PDR_REPAIR"
    CONVENTIONAL = "CONVENTIONAL"
    TOTAL_LOSS = "TOTAL_LOSS"


class PanelCode(str, Enum):
    HOOD = "HOOD"
    ROOF = "ROOF"
    DECK_LID = "DECK_LID"
    LEFT_FENDER = "LEFT_FENDER"
    RIGHT_FENDER = "RIGHT_FENDER"
    LEFT_FRONT_DOOR = "LEFT_FRONT_DOOR"
    RIGHT_FRONT_DOOR = "RIGHT_FRONT_DOOR"
    LEFT_REAR_DOOR = "LEFT_REAR_DOOR"
    RIGHT_REAR_DOOR = "RIGHT_REAR_DOOR"
    LEFT_QUARTER = "LEFT_QUARTER"
    RIGHT_QUARTER = "RIGHT_QUARTER"


class DentSizeClass(str, Enum):
    DIME = "DIME"
    NICKEL = "NICKEL"
    QUARTER = "QUARTER"
    HALF_DOLLAR = "HALF_DOLLAR"


class RoutedTo(str, Enum):
    PDR = "PDR"
    CONVENTIONAL = "CONVENTIONAL"


class WorkTicketStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    VOIDED = "VOIDED"


class SupplementStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    AUTO_APPROVED = "AUTO_APPROVED"
    APPROVED = "APPROVED"
    COUNTERED = "COUNTERED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class SupplementReasonCode(str, Enum):
    HIDDEN_DAMAGE = "HIDDEN_DAMAGE"
    ADDITIONAL_PANEL = "ADDITIONAL_PANEL"
    R_AND_I_ADDITION = "R_AND_I_ADDITION"
    PARTS_PRICE_CHANGE = "PARTS_PRICE_CHANGE"


class SupplementReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    COUNTER = "COUNTER"
    DENY = "DENY"


class SupplementReviseAction(str, Enum):
    REVISE = "REVISE"
    WITHDRAW = "WITHDRAW"


class InspectionResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


# ─── The eight non-terminal repair states (PRD §2.6) ──────────────────────────

NON_TERMINAL_REPAIR_STATES = [
    VehicleRepairStatus.INTAKE.value,
    VehicleRepairStatus.ESTIMATED.value,
    VehicleRepairStatus.TRIAGED.value,
    VehicleRepairStatus.IN_REPAIR.value,
    VehicleRepairStatus.QC_PENDING.value,
    VehicleRepairStatus.QC_FAILED.value,
    VehicleRepairStatus.READY.value,
    VehicleRepairStatus.TOTAL_LOSS_PENDING.value,
]

TERMINAL_REPAIR_STATES = [
    VehicleRepairStatus.RELEASED.value,
    VehicleRepairStatus.TOWED_OUT.value,
]

REQUIRED_PERMIT_TYPES = [
    PermitType.TEMP_BUSINESS_LICENSE.value,
    PermitType.ZONING_USE.value,
]


# ─── Entity TypedDicts ────────────────────────────────────────────────────────

class StormEvent(TypedDict):
    id: str
    name: str
    region_state_code: str
    max_hail_size_mm: int
    swath_area_km2: int
    swath_confidence: str
    vehicle_population_estimate: int
    competitor_shop_count: int
    first_hail_at: str
    targeting_score: int
    status: str
    demobilized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Facility(TypedDict):
    id: str
    storm_event_id: str
    name: str
    state_code: str
    address: str
    staging_slot_count: int
    pay_model: str
    status: str
    posture: str
    staging_slots_occupied: int
    staging_slots_free: int
    staging_occupancy_ratio: float
    warranty_counter: int
    commissioned_at: Optional[str]
    billable_accrued_cents: int
    absorbed_rental_cents: int
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    """PRD §2.5: Permit carries only `id` and `created_at` — no `updated_at`
    and no `version`."""
    id: str
    facility_id: str
    permit_type: str
    issuing_jurisdiction: str
    status: str
    valid_from: Optional[str]
    valid_to: Optional[str]
    decided_at: Optional[str]
    created_at: str


class Technician(TypedDict):
    id: str
    full_name: str
    home_state_code: str
    license_state_code: str
    license_expires_at: str
    skill_tier: str
    flat_split_pct: float
    deployment_state: str
    accrued_pay_cents: int
    approved_ticket_count: int
    created_at: str
    updated_at: str
    version: int


class HousingUnit(TypedDict):
    id: str
    facility_id: str
    label: str
    bed_count: int
    nightly_rate_cents: int
    occupied_beds: int
    bed_nights_committed: int
    created_at: str
    updated_at: str
    version: int


class CrewDeployment(TypedDict):
    id: str
    technician_id: str
    facility_id: str
    housing_unit_id: Optional[str]
    start_date: str
    end_date: str
    actual_end_date: Optional[str]
    effective_end_date: str
    pay_split_pct_snapshot: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Insurer(TypedDict):
    id: str
    name: str
    naic_code: str
    direct_bill_enabled: bool
    outstanding_direct_bill_cents: int
    settled_cents: int
    active_rate_agreement_count: int
    created_at: str
    updated_at: str
    version: int


class RateAgreement(TypedDict):
    id: str
    insurer_id: str
    storm_event_id: str
    effective_from: str
    matrix_rate_dime_cents: int
    matrix_rate_nickel_cents: int
    matrix_rate_quarter_cents: int
    matrix_rate_half_dollar_cents: int
    labor_rate_cents_per_hour: int
    panel_cap_cents: int
    admin_fee_pct: float
    admin_fee_cap_cents: int
    supplement_auto_approve_pct: float
    rental_cap_days: int
    rental_daily_rate_cents: int
    status: str
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    facility_id: str
    insurer_id: str
    vin: str
    model_year: int
    make: str
    model: str
    acv_cents: int
    owner_name: str
    rental_required: bool
    repair_status: str
    billing_status: str
    pinned_rate_agreement_id: Optional[str]
    matrix_variant_total_cents: Optional[int]
    conventional_variant_total_cents: Optional[int]
    pdr_feasible: bool
    triage_disposition: Optional[str]
    approved_repair_cents: int
    approved_supplement_cents: int
    admin_fee_cents: int
    gross_billable_cents: int
    discount_cents: int
    net_billable_cents: int
    rework_count: int
    rental_opened_at: Optional[str]
    rental_closed_at: Optional[str]
    rental_days_billed: int
    shop_absorbed_rental_cents: int
    released_at: Optional[str]
    warranty_number: Optional[str]
    warranty_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DamageLine(TypedDict):
    """PRD §2.5: DamageLine carries only `id` and `created_at` — no
    `updated_at` and no `version`."""
    id: str
    vehicle_id: str
    panel_code: str
    dent_count: int
    dent_size_class: str
    aluminum: bool
    r_and_i_hours: float
    oversize_dent_count: int
    conventional_labor_hours: float
    conventional_paint_materials_cents: int
    pdr_line_cents: Optional[int]
    conventional_line_cents: Optional[int]
    capped: bool
    routed_to: Optional[str]
    created_at: str


class WorkTicket(TypedDict):
    id: str
    vehicle_id: str
    technician_id: str
    labor_units: float
    dents_repaired: int
    panels_worked: int
    status: str
    payable_flat_cents: int
    payable_pooled_cents: int
    payable_cents: int
    pay_model_applied: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Supplement(TypedDict):
    id: str
    vehicle_id: str
    rate_agreement_id: Optional[str]
    supersedes_supplement_id: Optional[str]
    reason_code: str
    requested_amount_cents: int
    approved_amount_cents: int
    counter_amount_cents: Optional[int]
    round_index: int
    status: str
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QualityInspection(TypedDict):
    """PRD §2.5: QualityInspection carries only `id` and `created_at` — no
    `updated_at` and no `version`."""
    id: str
    vehicle_id: str
    inspector_technician_id: str
    result: str
    defect_panel_codes: List[str]
    rework_index: int
    inspected_at: str
    created_at: str


class ThroughputSummary(TypedDict):
    staging_slot_count: int
    staging_slots_occupied: int
    staging_slots_free: int
    staging_occupancy_ratio: float
    posture: str
    open_vehicle_count: int
    vehicles_in_repair: int
    vehicles_ready: int
    released_count: int
    on_site_technician_count: int
    projected_days_to_clear: int
    billable_accrued_cents: int
    absorbed_rental_cents: int
