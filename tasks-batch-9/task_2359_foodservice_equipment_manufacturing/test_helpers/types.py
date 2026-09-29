"""Domain types for the Foodservice Equipment Manufacturing API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------


class UserRole(str, Enum):
    COMPLIANCE_ENGINEER = "ComplianceEngineer"
    LISTING_REVIEWER = "ListingReviewer"
    APPLICATION_ENGINEER = "ApplicationEngineer"
    ENGINEERING_APPROVER = "EngineeringApprover"
    CHAIN_ADMIN = "ChainAdmin"
    PRODUCTION_PLANNER = "ProductionPlanner"
    CONNECTED_OPS_ENGINEER = "ConnectedOpsEngineer"
    CHANNEL_MANAGER = "ChannelManager"
    SERVICE_PARTNER_USER = "ServicePartnerUser"
    WARRANTY_ADJUDICATOR = "WarrantyAdjudicator"
    PLATFORM_ADMIN = "PlatformAdmin"


# --------------------------------------------------------------------------
# Catalogue enums (PRD §3.1)
# --------------------------------------------------------------------------


class EquipmentCategory(str, Enum):
    FRYER = "FRYER"
    COMBI_OVEN = "COMBI_OVEN"
    GRIDDLE = "GRIDDLE"
    DISHWASHER = "DISHWASHER"
    HOLDING_CABINET = "HOLDING_CABINET"


class EnergyType(str, Enum):
    GAS = "GAS"
    ELECTRIC = "ELECTRIC"
    DUAL = "DUAL"


class ControlsPackage(str, Enum):
    STANDARD_DIAL = "STANDARD_DIAL"
    TOUCH_PRO = "TOUCH_PRO"
    CONNECT_PLUS = "CONNECT_PLUS"


class CertificationScope(str, Enum):
    SANITATION = "SANITATION"
    GAS = "GAS"
    ELECTRICAL = "ELECTRICAL"


class AgencyCode(str, Enum):
    AGENCY_ALPHA = "AGENCY_ALPHA"
    AGENCY_BETA = "AGENCY_BETA"
    AGENCY_GAMMA = "AGENCY_GAMMA"


class CertificationPosture(str, Enum):
    UNLISTED = "UNLISTED"
    PARTIAL = "PARTIAL"
    LISTED = "LISTED"
    SUSPENDED = "SUSPENDED"


class CertificationListingStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CONDITIONS_REQUESTED = "CONDITIONS_REQUESTED"
    LISTED = "LISTED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class AgencyDecision(str, Enum):
    ACKNOWLEDGE_REVIEW = "ACKNOWLEDGE_REVIEW"
    CONDITIONS = "CONDITIONS"
    GRANT = "GRANT"
    REJECT = "REJECT"
    SUSPEND = "SUSPEND"
    REINSTATE = "REINSTATE"


# --------------------------------------------------------------------------
# Chain / configuration enums (PRD §3.3, §3.5)
# --------------------------------------------------------------------------


class OptionCode(str, Enum):
    SPLIT_TANK = "SPLIT_TANK"
    HIGH_ALT = "HIGH_ALT"
    LEFT_HINGE = "LEFT_HINGE"
    ENERGY_SAVER = "ENERGY_SAVER"


class BrandingKit(str, Enum):
    NONE = "NONE"
    LOGO_BADGE = "LOGO_BADGE"
    FULL_WRAP = "FULL_WRAP"


class ChainConfigurationStatus(str, Enum):
    DRAFT = "DRAFT"
    ENG_REVIEW = "ENG_REVIEW"
    ENG_APPROVED = "ENG_APPROVED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    RELEASED = "RELEASED"
    COMPLIANCE_HOLD = "COMPLIANCE_HOLD"
    SUPERSEDED = "SUPERSEDED"


class EngineeringDecision(str, Enum):
    APPROVE = "APPROVE"
    REQUEST_REVISION = "REQUEST_REVISION"


# --------------------------------------------------------------------------
# Performance validation enums (PRD §3.4)
# --------------------------------------------------------------------------


class PerformanceValidationStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"


class ValidationFailureReason(str, Enum):
    THROUGHPUT_BELOW_TARGET = "THROUGHPUT_BELOW_TARGET"
    HOLD_TEMP_OUT_OF_TOLERANCE = "HOLD_TEMP_OUT_OF_TOLERANCE"


# --------------------------------------------------------------------------
# Programme / site order / production enums (PRD §3.6, §3.7)
# --------------------------------------------------------------------------


class ProgramType(str, Enum):
    NEW_BUILD = "NEW_BUILD"
    REMODEL = "REMODEL"


class CommitPosture(str, Enum):
    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"
    BREACHED = "BREACHED"


class FulfillmentStatus(str, Enum):
    PENDING = "PENDING"
    SCHEDULED = "SCHEDULED"
    IN_BUILD = "IN_BUILD"
    BUILT = "BUILT"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"


class CommitmentStatus(str, Enum):
    UNSCHEDULED = "UNSCHEDULED"
    COMMITTED = "COMMITTED"
    AT_RISK = "AT_RISK"
    BREACHED = "BREACHED"
    WAIVED = "WAIVED"


class FulfillmentEvent(str, Enum):
    SHIP = "SHIP"
    DELIVER = "DELIVER"


class ProductionSlotStatus(str, Enum):
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"
    IN_BUILD = "IN_BUILD"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BuildProgress(str, Enum):
    CONFIRM = "CONFIRM"
    START = "START"
    COMPLETE = "COMPLETE"


# --------------------------------------------------------------------------
# Connected fleet enums (PRD §3.8, §3.9)
# --------------------------------------------------------------------------


class ServiceTier(str, Enum):
    BASE = "BASE"
    EXTENDED_PLUS = "EXTENDED_PLUS"


class ServiceProgramStatus(str, Enum):
    PENDING_INSTALL = "PENDING_INSTALL"
    ACTIVE = "ACTIVE"
    EXTENDED = "EXTENDED"
    GRACE = "GRACE"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"


class CoverageAction(str, Enum):
    ACTIVATE = "ACTIVATE"
    EXTEND = "EXTEND"
    VOID = "VOID"


class CohortScope(str, Enum):
    CANARY = "CANARY"
    BROAD = "BROAD"


class FirmwareCampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    ROLLED_BACK = "ROLLED_BACK"


class UnitResultOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"


class CampaignDisposition(str, Enum):
    COMPLETE = "COMPLETE"
    ROLL_BACK = "ROLL_BACK"


class PartsStockingLevel(str, Enum):
    BASIC = "BASIC"
    FULL = "FULL"


class ServicePartnerStatus(str, Enum):
    APPLIED = "APPLIED"
    PROVISIONAL = "PROVISIONAL"
    AUTHORIZED = "AUTHORIZED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class PartnerAuthorizationAction(str, Enum):
    PROVISION = "PROVISION"
    AUTHORIZE = "AUTHORIZE"
    SUSPEND = "SUSPEND"
    REINSTATE = "REINSTATE"
    TERMINATE = "TERMINATE"


class TechnicianCertificationStatus(str, Enum):
    ENROLLED = "ENROLLED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class WarrantyClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REVERSED = "REVERSED"


class AdjudicationDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


# --------------------------------------------------------------------------
# Entity TypedDicts
#
# PRD §2.4: every resource type in this system carries id, created_at,
# updated_at and version.
# --------------------------------------------------------------------------


class EquipmentModel(TypedDict):
    id: str
    model_code: str
    name: str
    category: str
    energy_type: str
    base_price_cents: int
    supported_controls_packages: List[str]
    rated_throughput_units_per_hour: float
    required_scopes: List[str]
    covered_scopes: List[str]
    certification_posture: str
    created_at: str
    updated_at: str
    version: int


class CertificationListing(TypedDict):
    id: str
    equipment_model_id: str
    agency_code: str
    scopes: List[str]
    status: str
    revision: int
    conditions_note: Optional[str]
    listed_on: Optional[str]
    expires_on: Optional[str]
    submitted_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChainAccount(TypedDict):
    id: str
    account_code: str
    name: str
    contracted_unit_volume: int
    dealer_of_record: Optional[str]
    consultant_firm: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChainConfiguration(TypedDict):
    id: str
    chain_account_id: str
    equipment_model_id: str
    config_code: str
    option_codes: List[str]
    controls_package: str
    branding_kit: str
    status: str
    revision: int
    revision_note: Optional[str]
    branding_signed_off: bool
    approved_artwork_ref: Optional[str]
    indicative_unit_price_cents: int
    firm_unit_price_cents: Optional[int]
    pinned_model_version: Optional[int]
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PerformanceValidation(TypedDict):
    id: str
    chain_configuration_id: str
    menu_item_code: str
    target_throughput_units_per_hour: float
    hold_temp_target_c: float
    status: str
    attempt_count: int
    test_runs: List[dict]
    certified_throughput_units_per_hour: Optional[float]
    as_tested_throughput_units_per_hour: Optional[float]
    failure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConstructionProgram(TypedDict):
    id: str
    chain_account_id: str
    program_code: str
    program_type: str
    site_count_planned: int
    commit_posture: str
    created_at: str
    updated_at: str
    version: int


class SiteOrder(TypedDict):
    id: str
    construction_program_id: str
    chain_configuration_id: str
    site_code: str
    committed_delivery_date: str
    unit_count: int
    fulfillment_status: str
    commitment_status: str
    projected_delivery_date: Optional[str]
    slack_days: Optional[int]
    waiver_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BuildLine(TypedDict):
    id: str
    line_code: str
    plant_code: str
    daily_capacity_units: int
    supported_energy_types: List[str]
    committed_units: int
    created_at: str
    updated_at: str
    version: int


class ProductionSlot(TypedDict):
    id: str
    build_line_id: str
    site_order_id: str
    window_start: str
    window_end: str
    units: int
    status: str
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConnectedUnit(TypedDict):
    id: str
    equipment_model_id: str
    serial_number: str
    service_tier: str
    site_order_id: Optional[str]
    service_program_status: str
    firmware_version: str
    recipe_book_version: int
    fault_count_30d: int
    missed_heartbeat_count: int
    health_score: int
    coverage_start_date: Optional[str]
    coverage_end_date: Optional[str]
    grace_expires_on: Optional[str]
    reserve_initial_cents: int
    reserve_balance_cents: int
    claims_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class FirmwareCampaign(TypedDict):
    id: str
    equipment_model_id: str
    campaign_code: str
    target_firmware_version: str
    window_start: str
    window_end: str
    cohort_scope: str
    status: str
    cohort_unit_ids: List[str]
    success_count: int
    failure_count: int
    success_rate: Optional[float]
    created_at: str
    updated_at: str
    version: int


class ServicePartner(TypedDict):
    id: str
    partner_code: str
    name: str
    region_code: str
    parts_stocking_level: str
    status: str
    authorized_model_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class TechnicianCertification(TypedDict):
    id: str
    service_partner_id: str
    equipment_model_id: str
    technician_code: str
    training_hours: float
    status: str
    exam_score: Optional[float]
    certified_on: Optional[str]
    expires_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    connected_unit_id: str
    service_partner_id: str
    technician_certification_id: str
    claim_code: str
    parts_cost_cents: int
    labor_hours: float
    status: str
    coinsurance_pct: Optional[float]
    adjudicated_amount_cents: Optional[int]
    denial_reason: Optional[str]
    reversal_reason: Optional[str]
    adjudicated_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
