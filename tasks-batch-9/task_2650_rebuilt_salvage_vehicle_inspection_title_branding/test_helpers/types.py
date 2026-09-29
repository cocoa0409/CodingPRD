"""Domain types: entity TypedDicts, status enums and the role enum."""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    STATE_TITLE_CLERK = "StateTitleClerk"
    INSURER_ADJUSTER = "InsurerAdjuster"
    REBUILDER = "Rebuilder"
    INSPECTOR = "Inspector"
    HEARING_OFFICER = "HearingOfficer"
    FRAUD_INVESTIGATOR = "FraudInvestigator"


ALL_ROLES = tuple(r.value for r in UserRole)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class BodyClass(str, Enum):
    SEDAN = "SEDAN"
    SUV = "SUV"
    TRUCK = "TRUCK"
    MOTORCYCLE = "MOTORCYCLE"
    TRAILER = "TRAILER"


class FraudHold(str, Enum):
    NONE = "NONE"
    UNDER_REFERRAL = "UNDER_REFERRAL"
    CONFIRMED = "CONFIRMED"


class BrandCode(str, Enum):
    NONE = "NONE"
    SALVAGE = "SALVAGE"
    REBUILT = "REBUILT"
    FLOOD = "FLOOD"
    NON_REPAIRABLE = "NON_REPAIRABLE"


class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class LicenseAction(str, Enum):
    PROBATION = "PROBATION"
    CLEAR_PROBATION = "CLEAR_PROBATION"
    SUSPEND = "SUSPEND"
    REINSTATE = "REINSTATE"
    REVOKE = "REVOKE"


class CredentialStatus(str, Enum):
    CURRENT = "CURRENT"
    EXPIRED = "EXPIRED"


class InspectorCertification(str, Enum):
    STRUCTURAL = "STRUCTURAL"
    FLOOD = "FLOOD"
    THEFT_RECOVERY = "THEFT_RECOVERY"


class DamageBasisCode(str, Enum):
    GROSS_ESTIMATE = "GROSS_ESTIMATE"
    NET_OF_SALVAGE = "NET_OF_SALVAGE"


class DamageType(str, Enum):
    COLLISION = "COLLISION"
    FLOOD = "FLOOD"
    HAIL = "HAIL"
    THEFT_RECOVERY = "THEFT_RECOVERY"
    FIRE = "FIRE"


class TitleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    VOID = "VOID"
    SURRENDERED = "SURRENDERED"


class RecognitionState(str, Enum):
    NOT_SUBMITTED = "NOT_SUBMITTED"
    RECOGNITION_PENDING = "RECOGNITION_PENDING"
    RECOGNIZED = "RECOGNIZED"
    DOWNGRADED = "DOWNGRADED"
    STALE = "STALE"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    DOCS_UNDER_REVIEW = "DOCS_UNDER_REVIEW"
    DOCS_ACCEPTED = "DOCS_ACCEPTED"
    SCHEDULED = "SCHEDULED"
    IN_INSPECTION = "IN_INSPECTION"
    PASSED = "PASSED"
    FAILED = "FAILED"
    APPEAL_PENDING = "APPEAL_PENDING"
    TITLE_ISSUED = "TITLE_ISSUED"
    DENIED_FINAL = "DENIED_FINAL"
    WITHDRAWN = "WITHDRAWN"
    VOID_FRAUD = "VOID_FRAUD"


APPLICATION_TERMINAL_STATES = (
    ApplicationStatus.TITLE_ISSUED.value,
    ApplicationStatus.DENIED_FINAL.value,
    ApplicationStatus.WITHDRAWN.value,
    ApplicationStatus.VOID_FRAUD.value,
)


class DocsReviewDecision(str, Enum):
    OPEN = "OPEN"
    ACCEPT = "ACCEPT"
    RETURN = "RETURN"


class DocType(str, Enum):
    RECEIPT = "RECEIPT"
    PHOTOGRAPH = "PHOTOGRAPH"
    PARTS_INVOICE = "PARTS_INVOICE"
    DONOR_CERTIFICATE = "DONOR_CERTIFICATE"


class PartClass(str, Enum):
    STRUCTURAL = "STRUCTURAL"
    RESTRAINT = "RESTRAINT"
    POWERTRAIN = "POWERTRAIN"
    BODY_PANEL = "BODY_PANEL"
    GLAZING = "GLAZING"
    LIGHTING = "LIGHTING"
    WHEEL = "WHEEL"
    PHOTO_SET = "PHOTO_SET"


class PhotoViewCode(str, Enum):
    FRONT = "FRONT"
    REAR = "REAR"
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    VIN_PLATE = "VIN_PLATE"
    ENGINE_BAY = "ENGINE_BAY"


class PartSourceType(str, Enum):
    NEW = "NEW"
    USED_DONOR = "USED_DONOR"
    RECYCLER = "RECYCLER"
    OWNER_SUPPLIED = "OWNER_SUPPLIED"


class PartsDocumentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class RejectionReason(str, Enum):
    STOLEN_COMPONENT = "STOLEN_COMPONENT"
    UNTRACEABLE_SOURCE = "UNTRACEABLE_SOURCE"
    ILLEGIBLE = "ILLEGIBLE"
    DUPLICATE = "DUPLICATE"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED_PASS = "COMPLETED_PASS"
    COMPLETED_FAIL = "COMPLETED_FAIL"
    CANCELLED = "CANCELLED"


class InspectionResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class CheckpointOutcome(str, Enum):
    PASS = "PASS"
    MARGINAL = "MARGINAL"
    FAIL = "FAIL"


class CancellationReason(str, Enum):
    RESCHEDULED = "RESCHEDULED"
    FRAUD_HOLD = "FRAUD_HOLD"
    APPLICATION_VOIDED = "APPLICATION_VOIDED"
    CLERK_REQUEST = "CLERK_REQUEST"


class FindingCategory(str, Enum):
    STOLEN_COMPONENT = "STOLEN_COMPONENT"
    VIN_ALTERATION = "VIN_ALTERATION"
    STRUCTURAL_INADEQUACY = "STRUCTURAL_INADEQUACY"
    ODOMETER_DISCREPANCY = "ODOMETER_DISCREPANCY"
    DOCUMENTATION_GAP = "DOCUMENTATION_GAP"


class FindingSeverity(str, Enum):
    ADVISORY = "ADVISORY"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class AppealGrounds(str, Enum):
    SCORING_ERROR = "SCORING_ERROR"
    PART_TRACEABILITY_DISPUTE = "PART_TRACEABILITY_DISPUTE"
    PROCEDURAL_DEFECT = "PROCEDURAL_DEFECT"


class AppealStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    REMANDED = "REMANDED"


class AppealDecision(str, Enum):
    GRANT = "GRANT"
    DENY = "DENY"
    REMAND = "REMAND"


class ReferralType(str, Enum):
    ODOMETER = "ODOMETER"
    IDENTITY_TAMPERING = "IDENTITY_TAMPERING"
    DOCUMENT_FORGERY = "DOCUMENT_FORGERY"


class ReferralOrigin(str, Enum):
    AUTO_CASCADE = "AUTO_CASCADE"
    MANUAL = "MANUAL"


class ReferralStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    SUBSTANTIATED = "SUBSTANTIATED"
    UNSUBSTANTIATED = "UNSUBSTANTIATED"


class ReferralOutcome(str, Enum):
    SUBSTANTIATED = "SUBSTANTIATED"
    UNSUBSTANTIATED = "UNSUBSTANTIATED"


class RecognitionRequestStatus(str, Enum):
    PENDING = "PENDING"
    DECIDED = "DECIDED"
    SUPERSEDED = "SUPERSEDED"


class RecognitionOutcome(str, Enum):
    RECOGNIZED = "RECOGNIZED"
    DOWNGRADED = "DOWNGRADED"
    REJECTED = "REJECTED"


class OdometerFlag(str, Enum):
    OK = "OK"
    ROLLBACK_SUSPECTED = "ROLLBACK_SUSPECTED"


class TransferStatus(str, Enum):
    RECORDED = "RECORDED"
    VOID = "VOID"


# ---------------------------------------------------------------------------
# Entities that carry id + created_at + updated_at + version
# ---------------------------------------------------------------------------
class Vehicle(TypedDict):
    id: str
    vin: str
    model_year: int
    make: str
    model: str
    body_class: str
    fraud_hold: str
    active_brand_code: str
    brand_history: List[str]
    open_application_count: int
    last_odometer_miles: Optional[int]
    registered_state_code: str
    created_at: str
    updated_at: str
    version: int


class Rebuilder(TypedDict):
    id: str
    legal_name: str
    license_number: str
    license_status: str
    license_expires_at: str
    bond_amount_cents: int
    fees_deposited_cents: int
    fee_balance_cents: int
    escrowed_fee_total_cents: int
    fees_consumed_cents: int
    open_referral_count: int
    substantiated_referral_count: int
    applications_titled_count: int
    recordkeeping_score_rolling: float
    recordkeeping_score_lifetime: float
    suspended_by_user_id: Optional[str]
    last_license_action_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Inspector(TypedDict):
    id: str
    full_name: str
    badge_number: str
    credential_expires_at: str
    credential_status: str
    certifications: List[str]
    scheduled_inspection_count: int
    home_state_code: str
    created_at: str
    updated_at: str
    version: int


class InspectionStation(TypedDict):
    id: str
    station_code: str
    bay_count: int
    supports_flood: bool
    address_state_code: str
    scheduled_occupancy_count: int
    created_at: str
    updated_at: str
    version: int


class TitleRecord(TypedDict):
    id: str
    vehicle_id: str
    predecessor_title_id: Optional[str]
    source_damage_report_id: Optional[str]
    brand_code: str
    brand_history: List[str]
    status: str
    recognition_state: str
    issuing_state_code: str
    issued_at: str
    is_current: bool
    transfer_sequence: int
    odometer_at_issue_miles: Optional[int]
    owner_name: str
    brand_severity: int
    created_at: str
    updated_at: str
    version: int


class RebuiltApplication(TypedDict):
    id: str
    vehicle_id: str
    rebuilder_id: str
    salvage_title_id: str
    status: str
    expedite_requested: bool
    declared_repair_cost_cents: int
    documented_parts_cost_cents: int
    documentation_completeness_pct: float
    photo_view_count: int
    assessed_fee_cents: int
    total_program_charge_cents: int
    fee_escrowed_cents: int
    attempts_completed: int
    attempt_limit: int
    last_inspection_result: Optional[str]
    withdrawn_reason: Optional[str]
    terminal_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PartsDocument(TypedDict):
    id: str
    application_id: str
    donor_title_id: Optional[str]
    verified_by_inspector_id: Optional[str]
    doc_type: str
    part_class: str
    photo_view_code: Optional[str]
    source_type: str
    vendor_name: Optional[str]
    amount_cents: int
    part_serial_number: Optional[str]
    donor_vin: Optional[str]
    status: str
    rejection_reason: Optional[str]
    traceable: bool
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    application_id: str
    inspector_id: str
    station_id: str
    attempt_no: int
    scheduled_start_at: str
    scheduled_end_at: str
    effective_end_at: str
    status: str
    result: Optional[str]
    adequacy_score: Optional[float]
    checkpoint_results: List[dict]
    blocking_findings_count: int
    forced_fail: bool
    vin_plate_reading: Optional[str]
    vin_verified: bool
    started_at: Optional[str]
    completed_at: Optional[str]
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    inspection_id: str
    grounds: str
    narrative: str
    status: str
    filed_at: str
    decided_at: Optional[str]
    hearing_officer_user_id: Optional[str]
    remand_count: int
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FraudReferral(TypedDict):
    id: str
    vehicle_id: str
    application_id: Optional[str]
    inspection_id: Optional[str]
    referral_type: str
    origin: str
    status: str
    evidence_summary: str
    opened_by_user_id: str
    investigator_user_id: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InterstateRecognitionRequest(TypedDict):
    id: str
    title_record_id: str
    requesting_state_code: str
    submitted_brand_code: str
    mapped_brand_code: Optional[str]
    outcome: Optional[str]
    status: str
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TitleTransfer(TypedDict):
    id: str
    from_title_id: str
    to_title_id: str
    buyer_name: str
    transfer_effective_at: str
    odometer_reading_miles: int
    odometer_flag: str
    carried_brand_code: str
    sale_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only records: id + created_at only (no updated_at, no version)
# ---------------------------------------------------------------------------
class InsurerDamageReport(TypedDict):
    id: str
    vehicle_id: str
    insurer_name: str
    claim_number: str
    basis_code: str
    acv_cents: int
    repair_estimate_cents: int
    salvage_retention_cents: int
    damage_type: str
    flood_water_depth_cm: int
    odometer_reading_miles: int
    report_effective_at: str
    total_loss_declared: bool
    damage_ratio: float
    recommended_brand_code: str
    created_at: str


class InspectionFinding(TypedDict):
    id: str
    inspection_id: str
    parts_document_id: Optional[str]
    category: str
    severity: str
    description: str
    blocking: bool
    resolved: bool
    recorded_by_inspector_id: str
    created_at: str


APPEND_ONLY_ENTITIES = ("InsurerDamageReport", "InspectionFinding")
