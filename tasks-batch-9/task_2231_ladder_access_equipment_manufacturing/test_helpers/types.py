"""Domain types: entity TypedDicts, status enums and the role enum (PRD §2, §3)."""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    DESIGN_ENGINEER = "DesignEngineer"
    DESIGN_APPROVER = "DesignApprover"
    TEST_LAB_TECHNICIAN = "TestLabTechnician"
    PRODUCTION_SUPERVISOR = "ProductionSupervisor"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CERTIFICATION_BODY = "CertificationBody"
    CONSUMER = "Consumer"
    SAFETY_DIRECTOR = "SafetyDirector"
    SYSTEM_OPERATOR = "SystemOperator"


# ---------------------------------------------------------------------------
# Product enums (PRD §3.1, §2.7)
# ---------------------------------------------------------------------------
class ProductType(str, Enum):
    STEP_LADDER = "STEP_LADDER"
    EXTENSION_LADDER = "EXTENSION_LADDER"
    PLATFORM_LADDER = "PLATFORM_LADDER"
    ARTICULATED_LADDER = "ARTICULATED_LADDER"
    MOBILE_SCAFFOLD_TOWER = "MOBILE_SCAFFOLD_TOWER"


class Material(str, Enum):
    ALUMINUM_EXTRUSION = "ALUMINUM_EXTRUSION"
    FIBERGLASS_PULTRUSION = "FIBERGLASS_PULTRUSION"
    STEEL = "STEEL"


class DutyRating(str, Enum):
    TYPE_III = "TYPE_III"
    TYPE_II = "TYPE_II"
    TYPE_I = "TYPE_I"
    TYPE_IA = "TYPE_IA"
    TYPE_IAA = "TYPE_IAA"


class DesignStatus(str, Enum):
    DRAFT = "DRAFT"
    DESIGN_FROZEN = "DESIGN_FROZEN"
    DESIGN_OBSOLETE = "DESIGN_OBSOLETE"


class MarketStatus(str, Enum):
    NOT_RELEASED = "NOT_RELEASED"
    RETAIL_RELEASED = "RETAIL_RELEASED"
    STOP_SHIP = "STOP_SHIP"
    RECALLED = "RECALLED"


class StopShipReasonCode(str, Enum):
    LOT_QUARANTINE = "LOT_QUARANTINE"
    FIELD_INCIDENT_REVIEW = "FIELD_INCIDENT_REVIEW"
    LISTING_SUSPENDED = "LISTING_SUSPENDED"


class RetentionAnchorSource(str, Enum):
    LOT_RELEASE = "LOT_RELEASE"
    INCIDENT_CLOSURE = "INCIDENT_CLOSURE"
    RECALL = "RECALL"
    DESIGN_FREEZE = "DESIGN_FREEZE"


# ---------------------------------------------------------------------------
# Design revision enums (PRD §3.2)
# ---------------------------------------------------------------------------
class DesignRevisionStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class JointType(str, Enum):
    RIVETED = "RIVETED"
    BONDED = "BONDED"
    WELDED = "WELDED"


class ReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    REQUEST_CHANGES = "REQUEST_CHANGES"


# ---------------------------------------------------------------------------
# Product document enums (PRD §3.3)
# ---------------------------------------------------------------------------
class DocKind(str, Enum):
    DUTY_RATING_LABEL = "DUTY_RATING_LABEL"
    WARNING_LABEL = "WARNING_LABEL"
    INSTRUCTION_LABEL = "INSTRUCTION_LABEL"
    CERT_MARK_LABEL = "CERT_MARK_LABEL"
    RETAIL_CARTON = "RETAIL_CARTON"
    ASSEMBLY_INSTRUCTION_SHEET = "ASSEMBLY_INSTRUCTION_SHEET"
    CONSUMER_SAFETY_SHEET = "CONSUMER_SAFETY_SHEET"


class PlacementZone(str, Enum):
    SIDE_RAIL_UPPER = "SIDE_RAIL_UPPER"
    SIDE_RAIL_LOWER = "SIDE_RAIL_LOWER"
    TOP_CAP = "TOP_CAP"
    BACK_RAIL = "BACK_RAIL"


class DocumentStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


LABEL_DOC_KINDS = [
    DocKind.DUTY_RATING_LABEL.value,
    DocKind.WARNING_LABEL.value,
    DocKind.INSTRUCTION_LABEL.value,
    DocKind.CERT_MARK_LABEL.value,
]

PACKAGING_DOC_KINDS = [
    DocKind.RETAIL_CARTON.value,
    DocKind.ASSEMBLY_INSTRUCTION_SHEET.value,
    DocKind.CONSUMER_SAFETY_SHEET.value,
]


# ---------------------------------------------------------------------------
# Lab enums (PRD §3.4)
# ---------------------------------------------------------------------------
class ReservationStatus(str, Enum):
    HELD = "HELD"
    CONSUMED = "CONSUMED"
    CANCELLED = "CANCELLED"


class CampaignPurpose(str, Enum):
    DESIGN_QUALIFICATION = "DESIGN_QUALIFICATION"
    CERTIFICATION_LISTING = "CERTIFICATION_LISTING"
    PERIODIC_AUDIT = "PERIODIC_AUDIT"
    INCIDENT_INVESTIGATION = "INCIDENT_INVESTIGATION"


class CampaignStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class EscalationTier(str, Enum):
    TIER_0 = "TIER_0"
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class TestCode(str, Enum):
    STATIC_VERTICAL = "STATIC_VERTICAL"
    RAIL_BENDING = "RAIL_BENDING"
    SLIP_RESISTANCE = "SLIP_RESISTANCE"
    HINGE_CYCLE = "HINGE_CYCLE"
    ELECTRICAL_LEAKAGE = "ELECTRICAL_LEAKAGE"
    RIVET_SHEAR = "RIVET_SHEAR"


class LoadTestOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class FailureReasonCode(str, Enum):
    LOAD_BELOW_REQUIRED = "LOAD_BELOW_REQUIRED"
    DEFLECTION_EXCEEDED = "DEFLECTION_EXCEEDED"
    PERMANENT_SET_EXCEEDED = "PERMANENT_SET_EXCEEDED"


# ---------------------------------------------------------------------------
# Production lot enums (PRD §3.6)
# ---------------------------------------------------------------------------
class LotStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROCESS = "IN_PROCESS"
    RELEASED = "RELEASED"
    QUARANTINED = "QUARANTINED"
    SCRAPPED = "SCRAPPED"


class QuarantineReasonCode(str, Enum):
    JOINT_INTEGRITY = "JOINT_INTEGRITY"
    LABEL_DEFECT = "LABEL_DEFECT"
    AUDIT_FAILURE = "AUDIT_FAILURE"
    FIELD_INCIDENT = "FIELD_INCIDENT"


class Disposition(str, Enum):
    RELEASE = "RELEASE"
    SCRAP = "SCRAP"


class JointSampleResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


# ---------------------------------------------------------------------------
# Listing enums (PRD §3.5)
# ---------------------------------------------------------------------------
class StandardCode(str, Enum):
    ANSI_ASC_A14_2 = "ANSI_ASC_A14_2"
    ANSI_ASC_A14_5 = "ANSI_ASC_A14_5"
    EN_131_2 = "EN_131_2"
    CSA_Z11 = "CSA_Z11"


class ListingStatus(str, Enum):
    APPLIED = "APPLIED"
    LISTED = "LISTED"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"


class SuspensionReason(str, Enum):
    AUDIT_FAILURE = "AUDIT_FAILURE"
    STOP_SHIP_CASCADE = "STOP_SHIP_CASCADE"
    BODY_REQUEST = "BODY_REQUEST"


# ---------------------------------------------------------------------------
# Consumer / incident / recall enums (PRD §3.8, §3.9)
# ---------------------------------------------------------------------------
class PurchaseChannel(str, Enum):
    BIG_BOX_RETAIL = "BIG_BOX_RETAIL"
    PRO_DEALER = "PRO_DEALER"
    ONLINE = "ONLINE"


class RegistrationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    NOTIFIED = "NOTIFIED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class IncidentType(str, Enum):
    RAIL_FRACTURE = "RAIL_FRACTURE"
    RUNG_SEPARATION = "RUNG_SEPARATION"
    HINGE_FAILURE = "HINGE_FAILURE"
    SLIP_FALL = "SLIP_FALL"
    LABEL_ILLEGIBLE = "LABEL_ILLEGIBLE"


class InjurySeverity(str, Enum):
    NONE = "NONE"
    MINOR = "MINOR"
    HOSPITALIZATION = "HOSPITALIZATION"
    FATALITY = "FATALITY"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    ROOT_CAUSE_IDENTIFIED = "ROOT_CAUSE_IDENTIFIED"
    CAPA_OPENED = "CAPA_OPENED"
    NOT_SUBSTANTIATED = "NOT_SUBSTANTIATED"
    CLOSED = "CLOSED"


class IncidentFinding(str, Enum):
    NOT_SUBSTANTIATED = "NOT_SUBSTANTIATED"
    ROOT_CAUSE_IDENTIFIED = "ROOT_CAUSE_IDENTIFIED"


class RootCauseCode(str, Enum):
    RIVET_SHEAR_MARGIN = "RIVET_SHEAR_MARGIN"
    RAIL_SECTION_MODULUS = "RAIL_SECTION_MODULUS"
    LABEL_ADHESION = "LABEL_ADHESION"
    HINGE_STOP_GEOMETRY = "HINGE_STOP_GEOMETRY"
    CONSUMER_MISUSE = "CONSUMER_MISUSE"


class CorrectiveActionStatus(str, Enum):
    OPEN = "OPEN"
    VERIFIED = "VERIFIED"
    SUPERSEDED = "SUPERSEDED"


class RemedyType(str, Enum):
    REPAIR_KIT = "REPAIR_KIT"
    REPLACEMENT = "REPLACEMENT"
    REFUND = "REFUND"


class RecallStatus(str, Enum):
    DRAFT = "DRAFT"
    ANNOUNCED = "ANNOUNCED"
    IN_PROGRESS = "IN_PROGRESS"
    CLOSED = "CLOSED"


# ---------------------------------------------------------------------------
# Entity shapes
# ---------------------------------------------------------------------------
# Resources carrying id + created_at + updated_at + version (PRD §2.4).
class Product(TypedDict):
    id: str
    model_code: str
    product_type: str
    material: str
    duty_rating: str
    working_length_ft: float
    retail_sku: str
    rated_load_lb: int
    safety_factor: float
    required_test_load_lb: float
    required_pull_force_lbf: float
    max_allowed_deflection_in: float
    design_status: str
    market_status: str
    design_frozen_at: Optional[str]
    frozen_revision_id: Optional[str]
    market_status_changed_at: Optional[str]
    stop_ship_reason_code: Optional[str]
    held_registration_count: int
    risk_score_gross: float
    risk_score_mitigated: float
    dhf_retention_until: Optional[str]
    retention_anchor_source: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DesignRevision(TypedDict):
    id: str
    product_id: str
    revision_label: str
    joint_type: str
    structural_margin_pct: float
    rail_section_modulus_in3: float
    supersedes_revision_id: Optional[str]
    status: str
    review_round: int
    submitted_by_user_id: Optional[str]
    reviewed_by_user_id: Optional[str]
    reviewer_notes: Optional[str]
    superseded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProductDocument(TypedDict):
    id: str
    product_id: str
    doc_kind: str
    document_version: str
    text_digest: str
    placement_zone: Optional[str]
    pictogram_count: int
    includes_assembly_instructions: bool
    status: str
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TestBench(TypedDict):
    id: str
    bench_code: str
    max_load_capacity_lb: float
    cooldown_minutes: int
    reserved_minutes_total: int
    created_at: str
    updated_at: str
    version: int


class BenchReservation(TypedDict):
    id: str
    test_bench_id: str
    test_campaign_id: str
    start_at: str
    end_at: str
    duration_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TestCampaign(TypedDict):
    id: str
    product_id: str
    design_revision_id: str
    listing_record_id: Optional[str]
    sampled_lot_id: Optional[str]
    purpose: str
    status: str
    sample_window_start: Optional[str]
    sample_window_end: Optional[str]
    audit_sample_size: Optional[int]
    escalation_tier: Optional[str]
    prior_failure_rate_pct: Optional[float]
    load_test_count: int
    failed_test_count: int
    started_at: Optional[str]
    concluded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProductionLot(TypedDict):
    id: str
    product_id: str
    design_revision_id: str
    lot_code: str
    planned_units: int
    produced_units: int
    units_wip: int
    units_quarantined: int
    units_released: int
    units_scrapped: int
    extrusion_heat_number: Optional[str]
    pultrusion_batch_id: Optional[str]
    status: str
    joint_sample_count: int
    joint_fail_count: int
    required_joint_sample_count: int
    conformance_index: Optional[float]
    released_at: Optional[str]
    quarantine_reason_code: Optional[str]
    disposition: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ListingBody(TypedDict):
    id: str
    body_code: str
    accredited_standards: List[str]
    audit_interval_days: int
    created_at: str
    updated_at: str
    version: int


class ListingRecord(TypedDict):
    id: str
    product_id: str
    listing_body_id: str
    standard_code: str
    status: str
    listed_at: Optional[str]
    audit_due_at: Optional[str]
    listing_expires_at: Optional[str]
    suspended_at: Optional[str]
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConsumerRegistration(TypedDict):
    id: str
    production_lot_id: str
    consumer_email: str
    purchase_channel: str
    purchase_date: str
    serial_suffix: str
    registration_status: str
    hold_flag: bool
    recall_event_id: Optional[str]
    notified_at: Optional[str]
    acknowledged_at: Optional[str]
    remedy_choice: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FieldIncident(TypedDict):
    id: str
    product_id: str
    production_lot_id: Optional[str]
    consumer_registration_id: Optional[str]
    incident_type: str
    injury_severity: str
    occurred_at: str
    narrative: str
    status: str
    requires_capa: bool
    incident_points: Optional[float]
    finding: Optional[str]
    root_cause_code: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CorrectiveAction(TypedDict):
    id: str
    field_incident_id: str
    design_revision_id: Optional[str]
    supersedes_action_id: Optional[str]
    action_summary: str
    status: str
    authored_by_user_id: str
    verified_by_user_id: Optional[str]
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecallEvent(TypedDict):
    id: str
    product_id: str
    remedy_type: str
    affected_revision_ids: List[str]
    hazard_description: str
    status: str
    exposure_units_shipped_basis: Optional[int]
    exposure_units_registered_basis: Optional[int]
    notification_coverage_pct: Optional[float]
    units_remedied: Optional[int]
    units_outstanding: Optional[int]
    announced_at: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only measurement records: only id and created_at, no updated_at and no
# version (PRD §2.4).
class LoadTest(TypedDict):
    id: str
    test_campaign_id: str
    test_code: str
    applied_load_lb: float
    measured_deflection_in: float
    permanent_set_in: float
    outcome: str
    failure_reason_code: Optional[str]
    created_at: str


class JointIntegritySample(TypedDict):
    id: str
    production_lot_id: str
    sample_seq: int
    pull_force_lbf: float
    required_pull_force_lbf: float
    result: str
    margin_pct: int
    created_at: str


class LiabilityDossier(TypedDict):
    product_id: str
    model_code: str
    design_history_revision_count: int
    approved_document_kinds: List[str]
    passed_campaign_count: int
    released_lot_count: int
    open_incident_count: int
    risk_score_gross: float
    risk_score_mitigated: float
    dhf_retention_until: Optional[str]
    retention_anchor_source: Optional[str]
