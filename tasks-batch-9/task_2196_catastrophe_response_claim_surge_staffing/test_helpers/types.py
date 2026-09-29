"""Domain types for the Catastrophe Response & Claim Surge Staffing API.

Entity TypedDicts, status enums and the role enum, derived from the PRD.

Two collections are immutable once written (the reserve ledger and loss-estimate
snapshots): they carry ``id`` and ``created_at`` only, and their TypedDicts
deliberately omit ``updated_at`` and ``version``.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    CATASTROPHE_MANAGER = "CatastropheManager"
    DEPLOYMENT_COORDINATOR = "DeploymentCoordinator"
    CLAIMS_EXAMINER = "ClaimsExaminer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    ADJUSTER = "Adjuster"
    VENDOR_COORDINATOR = "VendorCoordinator"


ALL_ROLES = [r.value for r in UserRole]


# --------------------------------------------------------------------------
# CatastropheEvent
# --------------------------------------------------------------------------
class EventStatus(str, Enum):
    MONITORING = "MONITORING"
    DECLARED = "DECLARED"
    SURGE_ACTIVE = "SURGE_ACTIVE"
    DEMOBILIZING = "DEMOBILIZING"
    CLOSED = "CLOSED"


class EventPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class PerilType(str, Enum):
    HURRICANE = "HURRICANE"
    WILDFIRE = "WILDFIRE"
    HAIL = "HAIL"
    FLOOD = "FLOOD"
    WINTER_STORM = "WINTER_STORM"
    EARTHQUAKE = "EARTHQUAKE"


class CatastropheEvent(TypedDict):
    id: str
    cat_code: str
    peril_type: str
    jurisdiction_state: str
    event_start_utc: str
    exposure_count: int
    avg_insured_value: float
    expected_severity_index: float
    status: str
    posture: str
    declared_at_utc: Optional[str]
    open_claim_count: int
    case_reserve_total: float
    paid_total: float
    incurred_total: float
    housing_committed_cost: float
    deployment_settled_cost: float
    gross_loss_estimate: float
    moratorium_active: bool
    surge_adjuster_count: int
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# RegulatoryBulletin
# --------------------------------------------------------------------------
class BulletinStatus(str, Enum):
    DRAFT = "DRAFT"
    EFFECTIVE = "EFFECTIVE"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class BulletinType(str, Enum):
    CANCELLATION_MORATORIUM = "CANCELLATION_MORATORIUM"
    CLAIM_DEADLINE_EXTENSION = "CLAIM_DEADLINE_EXTENSION"
    ADVANCE_PAYMENT_MANDATE = "ADVANCE_PAYMENT_MANDATE"
    ADJUSTER_LICENSE_WAIVER = "ADJUSTER_LICENSE_WAIVER"


class RegulatoryBulletin(TypedDict):
    id: str
    event_id: str
    bulletin_number: str
    jurisdiction_state: str
    bulletin_type: str
    status: str
    effective_from: str
    effective_to: str
    mandated_advance_pct: float
    deadline_extension_days: int
    activated_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Adjuster
# --------------------------------------------------------------------------
class EmploymentType(str, Enum):
    STAFF = "STAFF"
    INDEPENDENT = "INDEPENDENT"


class CredentialStatus(str, Enum):
    VALID = "VALID"
    EXPIRING = "EXPIRING"
    EXPIRED = "EXPIRED"
    WAIVED = "WAIVED"


class DeploymentAxisStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEPLOYED = "DEPLOYED"
    RESTING = "RESTING"
    UNAVAILABLE = "UNAVAILABLE"


class Adjuster(TypedDict):
    id: str
    full_name: str
    employment_type: str
    home_state: str
    licensed_states: List[str]
    license_expiry_utc: str
    credential_status: str
    deployment_status: str
    desk_certified: bool
    aerial_certified: bool
    max_open_claims: int
    open_assignment_count: int
    daily_rate: float
    per_diem_rate: float
    surge_capacity_score: float
    cumulative_deployed_hours: float
    last_demobilized_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# HousingBlock
# --------------------------------------------------------------------------
class HousingBlockStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    RELEASED = "RELEASED"


class HousingBlock(TypedDict):
    id: str
    event_id: str
    hotel_name: str
    city: str
    rooms_total: int
    rooms_occupied: int
    rooms_available: int
    nightly_rate: float
    block_start_date: str
    block_end_date: str
    block_night_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Deployment
# --------------------------------------------------------------------------
class DeploymentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    ON_SITE = "ON_SITE"
    DEMOBILIZED = "DEMOBILIZED"
    CANCELLED = "CANCELLED"


class RoleType(str, Enum):
    FIELD = "FIELD"
    DESK = "DESK"
    AERIAL = "AERIAL"


class SurgePremiumTier(str, Enum):
    TIER_NONE = "TIER_NONE"
    TIER_MID = "TIER_MID"
    TIER_HIGH = "TIER_HIGH"


class SelectionReason(str, Enum):
    EXPLICIT_ADJUSTER = "EXPLICIT_ADJUSTER"
    SELECTOR_RANKED = "SELECTOR_RANKED"
    EXPLICIT_VENDOR = "EXPLICIT_VENDOR"


class Deployment(TypedDict):
    id: str
    event_id: str
    adjuster_id: Optional[str]
    housing_block_id: Optional[str]
    role_type: str
    window_start_utc: str
    window_end_utc: str
    rooms_reserved: int
    status: str
    selection_reason: str
    provisional_cost: float
    final_settled_cost: float
    surge_premium_tier: Optional[str]
    demobilized_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Claim
# --------------------------------------------------------------------------
class HandlingStatus(str, Enum):
    INTAKE = "INTAKE"
    TRIAGED = "TRIAGED"
    INSPECTION_PENDING = "INSPECTION_PENDING"
    INSPECTED = "INSPECTED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"
    TRANSFERRED = "TRANSFERRED"


class PaymentStatus(str, Enum):
    NONE = "NONE"
    ADVANCE_ISSUED = "ADVANCE_ISSUED"
    PARTIAL_PAID = "PARTIAL_PAID"
    SETTLED = "SETTLED"


class TriageTier(str, Enum):
    FAST_TRACK = "FAST_TRACK"
    STANDARD = "STANDARD"
    COMPLEX = "COMPLEX"
    CAT_SEVERE = "CAT_SEVERE"


class InspectionMode(str, Enum):
    FIELD = "FIELD"
    DESK = "DESK"
    AERIAL = "AERIAL"


class AccessStatus(str, Enum):
    ACCESSIBLE = "ACCESSIBLE"
    INACCESSIBLE = "INACCESSIBLE"
    RESTRICTED = "RESTRICTED"


class CoverageCode(str, Enum):
    DWELLING = "DWELLING"
    CONTENTS = "CONTENTS"
    ALE = "ALE"
    OTHER_STRUCTURES = "OTHER_STRUCTURES"


class CoverageLine(TypedDict):
    coverage_code: str
    limit_amount: float
    deductible_amount: float
    estimated_damage_amount: float


class Claim(TypedDict):
    id: str
    event_id: Optional[str]
    policy_number: str
    loss_state: str
    loss_date_utc: str
    reported_at_utc: str
    reported_loss_amount: float
    coverage_lines: List[Dict[str, Any]]
    access_status: str
    handling_status: str
    payment_status: str
    severity_score: float
    triage_tier: Optional[str]
    inspection_mode: Optional[str]
    advance_cap: float
    advance_paid_total: float
    case_reserve: float
    paid_amount: float
    verified_damage_amount: Optional[float]
    deadline_utc: Optional[str]
    reopen_count: int
    closing_examiner_user_id: Optional[str]
    advance_issuing_examiner_user_id: Optional[str]
    transfer_batch_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# InspectionAssignment
# --------------------------------------------------------------------------
class AssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    NO_ACCESS = "NO_ACCESS"
    CANCELLED = "CANCELLED"


class InspectionAssignment(TypedDict):
    id: str
    claim_id: str
    adjuster_id: Optional[str]
    deployment_id: Optional[str]
    mode: str
    window_start_utc: str
    window_end_utc: str
    status: str
    verified_damage_amount: Optional[float]
    report_submitted_at_utc: Optional[str]
    selection_reason: str
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# AdvancePayment
# --------------------------------------------------------------------------
class AdvanceStatus(str, Enum):
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


class AdvanceBasis(str, Enum):
    ALE_MANDATE = "ALE_MANDATE"
    STRUCTURE_PARTIAL = "STRUCTURE_PARTIAL"
    CONTENTS_PARTIAL = "CONTENTS_PARTIAL"


class AdvancePayment(TypedDict):
    id: str
    claim_id: str
    reserve_entry_id: Optional[str]
    requested_amount: float
    amount: float
    basis: str
    status: str
    void_reason: Optional[str]
    voided_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# ReserveEntry — immutable: id + created_at only
# --------------------------------------------------------------------------
class ReserveEntryType(str, Enum):
    INITIAL_CASE = "INITIAL_CASE"
    REVISION = "REVISION"
    PAYMENT = "PAYMENT"
    REVERSAL = "REVERSAL"


class ReserveEntry(TypedDict):
    id: str
    event_id: str
    claim_id: str
    reverses_entry_id: Optional[str]
    entry_type: str
    delta_case_reserve: float
    delta_paid: float
    sequence_no: int
    effective_utc: str
    memo: Optional[str]
    created_at: str


# --------------------------------------------------------------------------
# VendorFirm / VendorAssignment
# --------------------------------------------------------------------------
class VendorFirmStatus(str, Enum):
    NETWORK_INACTIVE = "NETWORK_INACTIVE"
    ACTIVATED = "ACTIVATED"
    CAPACITY_HOLD = "CAPACITY_HOLD"
    SUSPENDED = "SUSPENDED"


class VendorType(str, Enum):
    MITIGATION = "MITIGATION"
    TARP = "TARP"
    TREE_REMOVAL = "TREE_REMOVAL"
    CONTRACTOR = "CONTRACTOR"


class VendorFirm(TypedDict):
    id: str
    firm_name: str
    vendor_type: str
    service_states: List[str]
    status: str
    activated_for_event_id: Optional[str]
    max_concurrent_jobs: int
    open_job_count: int
    performance_score: float
    created_at: str
    updated_at: str
    version: int


class VendorAssignmentStatus(str, Enum):
    DISPATCHED = "DISPATCHED"
    ACCEPTED = "ACCEPTED"
    COMPLETED = "COMPLETED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"


class VendorAssignment(TypedDict):
    id: str
    claim_id: str
    vendor_firm_id: Optional[str]
    scope_amount: float
    status: str
    dispatched_at_utc: str
    selection_reason: str
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# LossEstimateSnapshot — immutable: id + created_at only
# --------------------------------------------------------------------------
class EstimateMethod(str, Enum):
    EXPOSURE_BASED = "EXPOSURE_BASED"
    INCURRED_DEVELOPMENT = "INCURRED_DEVELOPMENT"


class LossEstimateSnapshot(TypedDict):
    id: str
    event_id: str
    method: str
    gross_estimate: float
    ibnr_component: float
    reported_component: float
    input_reserve_sequence_high_water: int
    stale: bool
    computed_at_utc: str
    created_at: str


# --------------------------------------------------------------------------
# FileTransferBatch
# --------------------------------------------------------------------------
class BatchStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class FileTransferBatch(TypedDict):
    id: str
    event_id: str
    target_unit: str
    status: str
    claim_count: int
    blocking_claim_count: int
    submitted_at_utc: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
