"""
Enumeration values and response shapes for the Supermarket Refrigerant Leak
Compliance API.

Two families of entity live behind this API. Most carry the full common-field
set of §2.5 — `id`, `created_at`, `updated_at`, `version`. `RepairAttempt` and
`VerificationTest` are append-only evidence rows and carry only `id` and
`created_at`; their shapes below therefore deliberately omit `updated_at` and
`version`, and no test may look for either field on them.
"""

from typing import List, Optional

try:  # pragma: no cover - typing shim for older interpreters
    from typing import TypedDict
except ImportError:  # pragma: no cover
    from typing_extensions import TypedDict


# ─── Roles (§2.1) ─────────────────────────────────────────────────────

ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_COMPLIANCE_MANAGER = "ComplianceManager"
ROLE_TECHNICIAN = "Technician"
ROLE_STORE_MANAGER = "StoreManager"
ROLE_REGULATOR = "Regulator"

ALL_ROLES = [
    ROLE_PLATFORM_ADMIN,
    ROLE_COMPLIANCE_MANAGER,
    ROLE_TECHNICIAN,
    ROLE_STORE_MANAGER,
    ROLE_REGULATOR,
]

# ─── Store (§3.1) ─────────────────────────────────────────────────────

REGION_WEST = "WEST"
REGION_MIDWEST = "MIDWEST"
REGION_SOUTH = "SOUTH"
REGION_NORTHEAST = "NORTHEAST"

POSTURE_COMPLIANT = "COMPLIANT"
POSTURE_AT_RISK = "AT_RISK"
POSTURE_NON_COMPLIANT = "NON_COMPLIANT"

# ─── RefrigerantType (§3.1) ───────────────────────────────────────────

PRESSURE_LOW = "LOW"
PRESSURE_HIGH = "HIGH"
PRESSURE_VERY_HIGH = "VERY_HIGH"

ODS_CFC = "CFC"
ODS_HCFC = "HCFC"
ODS_HFC = "HFC"
ODS_HFO = "HFO"
ODS_NATURAL = "NATURAL"

PHASEDOWN_ALLOWED = "ALLOWED"
PHASEDOWN_RESTRICTED_NEW_EQUIPMENT = "RESTRICTED_NEW_EQUIPMENT"
PHASEDOWN_PROHIBITED = "PROHIBITED"

# ─── RefrigerantSystem (§3.1) ─────────────────────────────────────────

CATEGORY_COMMERCIAL_REFRIGERATION = "COMMERCIAL_REFRIGERATION"
CATEGORY_INDUSTRIAL_PROCESS_REFRIGERATION = "INDUSTRIAL_PROCESS_REFRIGERATION"
CATEGORY_COMFORT_COOLING = "COMFORT_COOLING"

METHOD_ROLLING_AVERAGE = "ROLLING_AVERAGE"
METHOD_ANNUALIZING = "ANNUALIZING"

APPLICABILITY_REGULATED = "REGULATED"
APPLICABILITY_EXEMPT = "EXEMPT"

CERT_TYPE_I = "TYPE_I"
CERT_TYPE_II = "TYPE_II"
CERT_TYPE_III = "TYPE_III"
CERT_UNIVERSAL = "UNIVERSAL"

SYSTEM_ACTIVE = "ACTIVE"
SYSTEM_RETIRED = "RETIRED"

STATE_COMPLIANT = "COMPLIANT"
STATE_LEAK_OPEN = "LEAK_OPEN"
STATE_CHRONIC_EXCEEDANCE = "CHRONIC_EXCEEDANCE"
STATE_RETROFIT_MANDATED = "RETROFIT_MANDATED"
STATE_RETIRED_EXEMPT = "RETIRED_EXEMPT"

# ─── Technician and RecoveryEquipment (§3.2) ──────────────────────────

TECHNICIAN_ACTIVE = "ACTIVE"
TECHNICIAN_SUSPENDED = "SUSPENDED"

EQUIPMENT_CERTIFIED = "CERTIFIED"
EQUIPMENT_VERIFICATION_OVERDUE = "VERIFICATION_OVERDUE"

# ─── Cylinder (§3.2) ──────────────────────────────────────────────────

DISPOSITION_VIRGIN = "VIRGIN"
DISPOSITION_RECOVERED = "RECOVERED"
DISPOSITION_SENT_FOR_RECLAIM = "SENT_FOR_RECLAIM"
DISPOSITION_RECLAIMED = "RECLAIMED"

# ─── ServiceRecord (§3.3) ─────────────────────────────────────────────

SERVICE_ADD_REFRIGERANT = "ADD_REFRIGERANT"
SERVICE_RECOVER_REFRIGERANT = "RECOVER_REFRIGERANT"
SERVICE_LEAK_REPAIR = "LEAK_REPAIR"
SERVICE_RETROFIT_CONVERSION = "RETROFIT_CONVERSION"
SERVICE_ROUTINE_MAINTENANCE = "ROUTINE_MAINTENANCE"

# ─── LeakEvent (§3.5) ─────────────────────────────────────────────────

DETECTION_LEAK_RATE_CALCULATION = "LEAK_RATE_CALCULATION"
DETECTION_MANUAL_INSPECTION = "MANUAL_INSPECTION"
DETECTION_AUTOMATED_MONITORING = "AUTOMATED_MONITORING"

EVENT_OPEN = "OPEN"
EVENT_VERIFICATION_PENDING = "VERIFICATION_PENDING"
EVENT_FOLLOWUP_PENDING = "FOLLOWUP_PENDING"
EVENT_VERIFICATION_FAILED = "VERIFICATION_FAILED"
EVENT_REPAIR_OVERDUE = "REPAIR_OVERDUE"
EVENT_VERIFICATION_OVERDUE = "VERIFICATION_OVERDUE"
EVENT_RETROFIT_MANDATED = "RETROFIT_MANDATED"
EVENT_VERIFIED_CLOSED = "VERIFIED_CLOSED"
EVENT_VOIDED = "VOIDED"

# ─── RepairAttempt and VerificationTest (§3.5) ────────────────────────

ATTEMPT_AWAITING_VERIFICATION = "AWAITING_VERIFICATION"
ATTEMPT_VERIFIED = "VERIFIED"
ATTEMPT_FAILED_VERIFICATION = "FAILED_VERIFICATION"
ATTEMPT_SUPERSEDED = "SUPERSEDED"

RESULT_PASS = "PASS"
RESULT_FAIL = "FAIL"

SEQUENCE_INITIAL = "INITIAL_VERIFICATION"
SEQUENCE_FOLLOWUP = "FOLLOWUP_VERIFICATION"

# ─── ExtensionRequest (§3.6) ──────────────────────────────────────────

REASON_PARTS_UNAVAILABLE = "PARTS_UNAVAILABLE"
REASON_INDUSTRIAL_PROCESS_SHUTDOWN_REQUIRED = "INDUSTRIAL_PROCESS_SHUTDOWN_REQUIRED"
REASON_PERMIT_PENDING = "PERMIT_PENDING"
REASON_SUPPLY_CHAIN_DELAY = "SUPPLY_CHAIN_DELAY"

EXTENSION_PENDING = "PENDING"
EXTENSION_APPROVED = "APPROVED"
EXTENSION_DENIED = "DENIED"
EXTENSION_EXPIRED = "EXPIRED"
EXTENSION_REVOKED = "REVOKED"

DECISION_APPROVE = "APPROVE"
DECISION_DENY = "DENY"

# ─── RetrofitPlan (§3.7) ──────────────────────────────────────────────

PLAN_RETROFIT = "RETROFIT"
PLAN_RETIRE = "RETIRE"

PLAN_DRAFT = "DRAFT"
PLAN_SUBMITTED = "SUBMITTED"
PLAN_APPROVED = "APPROVED"
PLAN_REJECTED = "REJECTED"
PLAN_IN_PROGRESS = "IN_PROGRESS"
PLAN_COMPLETED = "COMPLETED"
PLAN_SUPERSEDED = "SUPERSEDED"

COMPAT_COMPATIBLE = "COMPATIBLE"
COMPAT_CONDITIONALLY_COMPATIBLE = "CONDITIONALLY_COMPATIBLE"
COMPAT_INCOMPATIBLE = "INCOMPATIBLE"

PLAN_DECISION_APPROVE = "APPROVE"
PLAN_DECISION_REJECT = "REJECT"

# ─── RegulatoryReport (§3.9) ──────────────────────────────────────────

REPORT_ANNUAL_LEAK_RATE = "ANNUAL_LEAK_RATE"
REPORT_CHRONIC_LEAKER_NOTIFICATION = "CHRONIC_LEAKER_NOTIFICATION"
REPORT_RETROFIT_NOTIFICATION = "RETROFIT_NOTIFICATION"

LEAKED_CHARGE_BASED = "CHARGE_BASED"
LEAKED_BALANCE_BASED = "BALANCE_BASED"

REPORT_DRAFT = "DRAFT"
REPORT_SUBMITTED = "SUBMITTED"
REPORT_ACCEPTED = "ACCEPTED"
REPORT_REJECTED = "REJECTED"

REPORT_DECISION_ACCEPT = "ACCEPT"
REPORT_DECISION_REJECT = "REJECT"

# ─── Inspection (§3.9) ────────────────────────────────────────────────

SEVERITY_MINOR = "MINOR"
SEVERITY_MODERATE = "MODERATE"
SEVERITY_MAJOR = "MAJOR"

INSPECTION_OPEN = "OPEN"
INSPECTION_RESPONDED = "RESPONDED"
INSPECTION_ESCALATED = "ESCALATED"
INSPECTION_CLOSED = "CLOSED"


# ─── Response shapes ──────────────────────────────────────────────────
#
# The two families of §2.5 are expressed as two different bases: entities that
# are updatable carry `updated_at` and `version`, append-only evidence rows do
# not.


class CommonFields(TypedDict):
    """`id`, `created_at`, `updated_at` and `version` (§2.5)."""

    id: str
    created_at: str
    updated_at: str
    version: int


class AppendOnlyFields(TypedDict):
    """`id` and `created_at` only — no `updated_at`, no `version` (§2.5)."""

    id: str
    created_at: str


class Store(CommonFields, total=False):
    name: str
    store_code: str
    state_code: str
    region: str
    compliance_status: str
    total_regulated_charge_lbs: float
    regulated_system_count: int
    open_leak_event_count: int
    overdue_leak_event_count: int
    mandated_retrofit_count: int
    chronic_leaker_flag: bool
    vented_loss_lbs: float
    penalty_exposure_total_usd: float


class RefrigerantType(CommonFields, total=False):
    name: str
    gwp: int
    pressure_class: str
    ods_class: str
    phasedown_status: str


class RefrigerantSystem(CommonFields, total=False):
    store_id: str
    refrigerant_type_id: str
    replaced_by_system_id: Optional[str]
    system_category: str
    full_charge_lbs: float
    initial_charge_lbs: float
    current_charge_lbs: float
    installed_on: str
    leak_rate_method: str
    leak_rate_pct: float
    leak_rate_baseline_at: str
    applicability: str
    threshold_pct: float
    required_certification_type: str
    exceedance_count_12mo: int
    operational_status: str
    compliance_state: str
    retrofit_due_on: Optional[str]
    retired_on: Optional[str]


class Technician(CommonFields, total=False):
    full_name: str
    epa_certification_number: str
    certification_type: str
    certification_expires_on: str
    status: str
    suspension_reason_code: Optional[str]
    repair_attempt_count: int


class RecoveryEquipment(CommonFields, total=False):
    store_id: str
    assigned_technician_id: str
    equipment_serial: str
    certified_to_standard: str
    certified_for_pressure_class: str
    last_verification_on: str
    status: str


class Cylinder(CommonFields, total=False):
    store_id: str
    refrigerant_type_id: str
    cylinder_serial: str
    nominal_capacity_lbs: float
    initial_contents_lbs: float
    current_contents_lbs: float
    shipped_for_reclaim_lbs: float
    fill_limit_lbs: float
    disposition: str
    shipped_on: Optional[str]
    reclaimer_name: Optional[str]
    reclaim_certificate_number: Optional[str]
    reclaimed_quantity_lbs: Optional[float]
    purity_verified: bool
    reclaim_issued_on: Optional[str]


class ServiceRecord(CommonFields, total=False):
    system_id: str
    technician_id: str
    recovery_equipment_id: str
    cylinder_id: Optional[str]
    leak_event_id: Optional[str]
    service_type: str
    refrigerant_added_lbs: float
    refrigerant_recovered_lbs: float
    refrigerant_lost_lbs: float
    performed_at: str
    duration_minutes: int
    occupies_until: str
    equipment_released_at: str
    system_charge_after_lbs: float
    leak_rate_pct_after: float
    retention_until: str
    voided: bool
    voided_at: Optional[str]
    void_reason_code: Optional[str]


class LeakEvent(CommonFields, total=False):
    system_id: str
    triggering_service_record_id: Optional[str]
    detected_at: str
    detection_method: str
    leak_rate_pct_at_detection: Optional[float]
    threshold_pct_applied: Optional[float]
    initial_repair_deadline: str
    repair_deadline: str
    verification_deadline: Optional[str]
    extension_days_granted_total: int
    extension_days_remaining: int
    repair_attempt_count: int
    failed_verification_count: int
    last_repair_completed_at: Optional[str]
    late_repair_flag: bool
    status: str
    closed_at: Optional[str]


class RepairAttempt(AppendOnlyFields, total=False):
    """Append-only: no `updated_at`, no `version`, no update endpoint."""

    leak_event_id: str
    technician_id: str
    recovery_equipment_id: str
    attempt_number: int
    repair_method_code: str
    repair_completed_at: str
    was_late: bool
    outcome: str


class VerificationTest(AppendOnlyFields, total=False):
    """Append-only: no `updated_at`, no `version`, no update endpoint."""

    leak_event_id: str
    repair_attempt_id: str
    technician_id: str
    test_method_code: str
    performed_at: str
    result: str
    measured_leak_rate_pct: Optional[float]
    test_sequence: str
    was_late: bool


class ExtensionRequest(CommonFields, total=False):
    leak_event_id: str
    reason_code: str
    requested_days: int
    justification: str
    granted_days: Optional[int]
    requested_at: str
    expires_at: str
    decided_at: Optional[str]
    revoked_at: Optional[str]
    revocation_reason_code: Optional[str]
    deadline_before: str
    deadline_after: Optional[str]
    status: str


class RetrofitPlan(CommonFields, total=False):
    system_id: str
    target_refrigerant_type_id: Optional[str]
    plan_type: str
    due_on: str
    estimated_cost_usd: float
    gwp_reduction_pct: float
    compatibility_score: float
    compatibility_result: str
    mandated: bool
    submitted_at: Optional[str]
    submission_count: int
    decided_at: Optional[str]
    rejection_reason_code: Optional[str]
    completed_at: Optional[str]
    status: str


class RegulatoryReport(CommonFields, total=False):
    store_id: str
    report_type: str
    period_start: str
    period_end: str
    leaked_lbs_method: str
    total_leaked_lbs: float
    included_system_count: int
    due_on: str
    submitted_at: Optional[str]
    submission_count: int
    days_late: int
    base_assessment_usd: float
    administrative_surcharge_usd: float
    late_filing_assessment_usd: float
    decided_at: Optional[str]
    rejection_reason_code: Optional[str]
    status: str


class Citation(TypedDict, total=False):
    citation_code: str
    severity: str
    violation_days: int


class Inspection(CommonFields, total=False):
    store_id: str
    inspector_name: str
    citations: List[Citation]
    opened_by_user_id: str
    opened_at: str
    response_deadline: str
    chronic_multiplier_applied: float
    penalty_exposure_usd: float
    capped: bool
    responded_at: Optional[str]
    response_summary: Optional[str]
    corrective_action_code: Optional[str]
    escalated_at: Optional[str]
    closed_at: Optional[str]
    closed_by_user_id: Optional[str]
    closure_note: Optional[str]
    status: str


class LeakRateProjection(TypedDict, total=False):
    """The read-only projection of §3.4 — it persists nothing."""

    system_id: str
    method: str
    leak_rate_pct: float
    refrigerant_added_lbs_in_window: float
    window_start: str
    window_end: str
    threshold_pct: float
    would_trigger_leak_event: bool


class ComplianceRun(TypedDict, total=False):
    """The sweep report of §3.6."""

    swept_repair_overdue_leak_event_ids: List[str]
    swept_verification_overdue_leak_event_ids: List[str]
    expired_extension_request_ids: List[str]
    overdue_equipment_ids: List[str]
    escalated_inspection_ids: List[str]
    stores_recomputed_count: int
    as_of: str


class ClockState(TypedDict, total=False):
    current_utc: str
    previous_utc: str


#: Entities whose rows are append-only evidence and therefore carry neither
#: `updated_at` nor `version`.
APPEND_ONLY_ENTITIES = ("RepairAttempt", "VerificationTest")
