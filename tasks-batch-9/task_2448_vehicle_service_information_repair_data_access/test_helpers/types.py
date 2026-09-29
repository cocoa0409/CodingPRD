"""Entity shapes and status vocabularies for the Vehicle Service Information Access API.

Every TypedDict mirrors the resource contract of the PRD. Resources that the PRD
declares immutable after creation (vehicle models, system areas, audit events)
carry only ``id`` and ``created_at`` — they have no ``updated_at`` and no
``version`` field at all, so those keys are deliberately absent below.
"""

from typing import Any, Dict, List, Optional, TypedDict

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


class Role:
    """The five roles the API accepts in X-User-Role."""

    PLATFORM_ADMIN = "PlatformAdmin"
    CONTENT_PUBLISHER = "ContentPublisher"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    SHOP_MANAGER = "ShopManager"
    TECHNICIAN = "Technician"

    ALL = [
        PLATFORM_ADMIN,
        CONTENT_PUBLISHER,
        COMPLIANCE_OFFICER,
        SHOP_MANAGER,
        TECHNICIAN,
    ]


# ---------------------------------------------------------------------------
# Status vocabularies
# ---------------------------------------------------------------------------


class ParityStatus:
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"


class ParityBasis:
    LIST_BASIS = "LIST_BASIS"
    EFFECTIVE_BASIS = "EFFECTIVE_BASIS"


class CoverageBasis:
    EFFECTIVE = "EFFECTIVE"
    DECLARED = "DECLARED"


class Region:
    NA = "NA"
    EU = "EU"
    APAC = "APAC"


class LicenseModel:
    SUBSCRIPTION = "SUBSCRIPTION"
    PER_VEHICLE = "PER_VEHICLE"
    EITHER = "EITHER"


class LicenseStatus:
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ShopTier:
    BASIC = "BASIC"
    PRO = "PRO"
    ENTERPRISE = "ENTERPRISE"


class IdentityStatus:
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class EntitlementModel:
    SUBSCRIPTION = "SUBSCRIPTION"
    PER_VEHICLE = "PER_VEHICLE"


class EntitlementStatus:
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    CANCELLED = "CANCELLED"


class SettlementStatus:
    UNSETTLED = "UNSETTLED"
    SETTLED = "SETTLED"


class SeatStatus:
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


class SeatRevocationReason:
    TECHNICIAN_SUSPENDED = "TECHNICIAN_SUSPENDED"
    ENTITLEMENT_CANCELLED = "ENTITLEMENT_CANCELLED"
    LICENSE_TERMINATED = "LICENSE_TERMINATED"


class ToolStatus:
    IDLE = "IDLE"
    OCCUPIED = "OCCUPIED"


class PublicationType:
    REPAIR_PROCEDURE = "REPAIR_PROCEDURE"
    TSB = "TSB"
    CALIBRATION_DOC = "CALIBRATION_DOC"


class ReviewStatus:
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"


class DistributionStatus:
    WITHHELD = "WITHHELD"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    RECALLED = "RECALLED"


class SessionStatus:
    REQUESTED = "REQUESTED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class SessionTerminationReason:
    SEAT_REVOKED = "SEAT_REVOKED"
    TECHNICIAN_SUSPENDED = "TECHNICIAN_SUSPENDED"
    ENTITLEMENT_CANCELLED = "ENTITLEMENT_CANCELLED"
    LICENSE_TERMINATED = "LICENSE_TERMINATED"


class JobType:
    IMMOBILIZER_KEY = "IMMOBILIZER_KEY"
    MODULE_FLASH = "MODULE_FLASH"
    ADAS_CALIBRATION = "ADAS_CALIBRATION"


class JobStatus:
    QUEUED = "QUEUED"
    IN_PROGRESS = "IN_PROGRESS"
    REVALIDATION_REQUIRED = "REVALIDATION_REQUIRED"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class JobAbortReason:
    SESSION_COMPLETED = "SESSION_COMPLETED"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    SESSION_TERMINATED = "SESSION_TERMINATED"
    PINNED_VERSION_SUPERSEDED = "PINNED_VERSION_SUPERSEDED"
    PINNED_VERSION_RECALLED = "PINNED_VERSION_RECALLED"


class CellState:
    COVERED = "COVERED"
    DEGRADED = "DEGRADED"
    GAP = "GAP"


class AuditEventType:
    TECHNICIAN_VERIFIED = "TECHNICIAN_VERIFIED"
    TECHNICIAN_SUSPENDED = "TECHNICIAN_SUSPENDED"
    SEAT_ASSIGNED = "SEAT_ASSIGNED"
    SEAT_REVOKED = "SEAT_REVOKED"
    SESSION_CREDENTIAL_ISSUED = "SESSION_CREDENTIAL_ISSUED"
    SESSION_COMPLETED = "SESSION_COMPLETED"
    SESSION_TERMINATED = "SESSION_TERMINATED"
    JOB_STARTED = "JOB_STARTED"
    JOB_COMPLETED = "JOB_COMPLETED"
    JOB_ABORTED = "JOB_ABORTED"
    JOB_REVALIDATION_REQUIRED = "JOB_REVALIDATION_REQUIRED"
    VERSION_PUBLISHED = "VERSION_PUBLISHED"
    VERSION_RECALLED = "VERSION_RECALLED"
    LICENSE_TERMINATED = "LICENSE_TERMINATED"
    ENTITLEMENT_SETTLED = "ENTITLEMENT_SETTLED"

    ALL = [
        TECHNICIAN_VERIFIED,
        TECHNICIAN_SUSPENDED,
        SEAT_ASSIGNED,
        SEAT_REVOKED,
        SESSION_CREDENTIAL_ISSUED,
        SESSION_COMPLETED,
        SESSION_TERMINATED,
        JOB_STARTED,
        JOB_COMPLETED,
        JOB_ABORTED,
        JOB_REVALIDATION_REQUIRED,
        VERSION_PUBLISHED,
        VERSION_RECALLED,
        LICENSE_TERMINATED,
        ENTITLEMENT_SETTLED,
    ]


class AuditSubjectEntity:
    TECHNICIAN = "Technician"
    SEAT_ASSIGNMENT = "SeatAssignment"
    GATEWAY_SESSION = "GatewaySession"
    MODULE_PROGRAMMING_JOB = "ModuleProgrammingJob"
    PUBLICATION_VERSION = "PublicationVersion"
    LICENSE = "License"
    SHOP_ENTITLEMENT = "ShopEntitlement"


class AuditActorRole:
    SYSTEM = "SYSTEM"


# ---------------------------------------------------------------------------
# Entity shapes
# ---------------------------------------------------------------------------


class Manufacturer(TypedDict):
    id: str
    name: str
    oem_code: str
    region: str
    independent_list_monthly_cents: int
    independent_covered_system_count: int
    oem_dealer_monthly_cents: int
    oem_dealer_covered_system_count: int
    parity_index: float
    parity_status: str
    created_at: str
    updated_at: str
    version: int


class VehicleModel(TypedDict):
    """Immutable catalogue row: carries only id and created_at."""

    id: str
    manufacturer_id: str
    model_code: str
    model_year: int
    created_at: str


class SystemArea(TypedDict):
    """Immutable catalogue row: carries only id and created_at."""

    id: str
    code: str
    name: str
    requires_calibration_doc: bool
    requires_security_credential: bool
    created_at: str


class License(TypedDict):
    id: str
    manufacturer_id: str
    license_model: str
    monthly_fee_cents: int
    per_vehicle_fee_cents: int
    seat_cap: int
    covered_system_area_ids: List[str]
    effective_start: str
    effective_end: str
    status: str
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Shop(TypedDict):
    id: str
    name: str
    tier: str
    funded_credit_total_cents: int
    data_credit_balance_cents: int
    gateway_fee_accrued_cents: int
    coverage_completeness_pct: float
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict):
    id: str
    shop_id: str
    full_name: str
    identity_status: str
    credential_expires_at: str
    identity_document_ref: Optional[str]
    verified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShopEntitlement(TypedDict):
    id: str
    shop_id: str
    license_id: str
    entitlement_model: str
    seats_total: int
    vin_quota: int
    window_start: str
    window_end: str
    status: str
    charged_cents: int
    settled_cents: int
    settlement_status: str
    seats_assigned: int
    seats_available: int
    created_at: str
    updated_at: str
    version: int


class SeatAssignment(TypedDict):
    id: str
    entitlement_id: str
    technician_id: str
    status: str
    revocation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DiagnosticTool(TypedDict):
    id: str
    shop_id: str
    serial_no: str
    oem_attestation_expires_at: str
    status: str
    occupied_by_session_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Publication(TypedDict):
    id: str
    vehicle_model_id: str
    system_area_id: str
    publication_type: str
    current_version_no: int
    published_version_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PublicationVersion(TypedDict):
    id: str
    publication_id: str
    version_no: int
    source_tsb_ref: str
    calibration_procedure_ref: Optional[str]
    review_status: str
    distribution_status: str
    validated_by_user_id: Optional[str]
    published_by_user_id: Optional[str]
    active_pin_count: int
    created_at: str
    updated_at: str
    version: int


class GatewaySession(TypedDict):
    id: str
    seat_assignment_id: str
    diagnostic_tool_id: str
    vin: str
    window_start: str
    window_end: str
    status: str
    credential_token: Optional[str]
    base_subtotal_cents: int
    discount_cents: int
    surcharge_cents: int
    total_access_fee_cents: int
    termination_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ModuleProgrammingJob(TypedDict):
    id: str
    session_id: str
    job_type: str
    pinned_publication_version_id: str
    status: str
    repin_count: int
    abort_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuditEvent(TypedDict):
    """Append-only trail row: carries only id and created_at."""

    id: str
    actor_role: str
    actor_user_id: Optional[str]
    subject_entity: str
    subject_id: str
    event_type: str
    detail: Optional[str]
    occurred_at: str
    created_at: str


# ---------------------------------------------------------------------------
# Computed read shapes
# ---------------------------------------------------------------------------


class ParityReport(TypedDict):
    manufacturer_id: str
    basis: str
    parity_index: float
    parity_status: str
    independent_effective_cents_per_system_day: float
    oem_effective_cents_per_system_day: float
    threshold: float


class CoverageGap(TypedDict):
    vehicle_model_id: str
    model_code: str
    system_area_id: str
    system_area_code: str
    cell_state: str


class CoverageMap(TypedDict):
    shop_id: str
    basis: str
    total_cells: int
    covered_cells: int
    degraded_cells: int
    gap_cells: int
    completeness_pct: float
    gaps: List[CoverageGap]


Payload = Dict[str, Any]
