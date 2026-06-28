"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entity model and state machines. The generic response
envelope types live in the framework, not here.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ──────────────────────────────────────────────────────────

class PropertyPosture(str, Enum):
    OPEN = "OPEN"
    TESTING = "TESTING"
    MITIGATION_REQUIRED = "MITIGATION_REQUIRED"
    MITIGATING = "MITIGATING"
    CLEARED = "CLEARED"


class FoundationType(str, Enum):
    SLAB = "SLAB"
    BASEMENT = "BASEMENT"
    CRAWLSPACE = "CRAWLSPACE"


class InspectorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CrewStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RadonTestKind(str, Enum):
    SHORT_TERM_48HR = "SHORT_TERM_48HR"
    CONTINUOUS_MONITOR = "CONTINUOUS_MONITOR"


class RadonTestPurpose(str, Enum):
    INITIAL = "INITIAL"
    POST_MITIGATION = "POST_MITIGATION"
    RECURRING = "RECURRING"


class RadonTestStatus(str, Enum):
    PLACED = "PLACED"
    RETRIEVED = "RETRIEVED"
    RESULT_READY = "RESULT_READY"
    VOIDED = "VOIDED"


class ActionOutcome(str, Enum):
    NO_ACTION = "NO_ACTION"
    ACTION_RECOMMENDED = "ACTION_RECOMMENDED"


class MitigationJobStatus(str, Enum):
    DESIGN = "DESIGN"
    QUOTED = "QUOTED"
    SCHEDULED = "SCHEDULED"
    INSTALLED = "INSTALLED"
    RETEST_PENDING = "RETEST_PENDING"
    CLEARED = "CLEARED"
    REWORK = "REWORK"
    CANCELLED = "CANCELLED"


class SystemDesign(str, Enum):
    SUB_SLAB_DEPRESSURIZATION = "SUB_SLAB_DEPRESSURIZATION"
    SUB_MEMBRANE_DEPRESSURIZATION = "SUB_MEMBRANE_DEPRESSURIZATION"


class PermitStatus(str, Enum):
    ISSUED = "ISSUED"
    CLOSED = "CLOSED"
    REVOKED = "REVOKED"


class WarrantyCoverageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class WarrantyClaimStatus(str, Enum):
    NONE = "NONE"
    CLAIM_OPEN = "CLAIM_OPEN"
    CLAIM_RESOLVED = "CLAIM_RESOLVED"


class RefundMethod(str, Enum):
    STRAIGHT_LINE = "STRAIGHT_LINE"
    STEP_TIER = "STEP_TIER"


class RetestScheduleStatus(str, Enum):
    ARMED = "ARMED"
    PAUSED = "PAUSED"
    ENDED = "ENDED"


class PaymentKind(str, Enum):
    DEPOSIT = "DEPOSIT"
    BALANCE = "BALANCE"
    REFUND = "REFUND"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    INSPECTOR = "Inspector"
    MITIGATION_DESIGNER = "MitigationDesigner"
    CREW_LEAD = "CrewLead"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CLIENT_CONTACT = "ClientContact"


# ─── Entity TypedDicts ─────────────────────────────────────────────────────
# Entities with the common field set carry id + created_at + updated_at + version.
# PaymentRecord (append-only ledger) carries only id + created_at.

class Property(TypedDict):
    id: str
    address_line: str
    foundation_type: str
    floor_area_sqft: int
    is_real_estate_transaction: bool
    closing_deadline_utc: Optional[str]
    posture: str
    latest_result_pci_l: Optional[float]
    open_test_count: int
    created_at: str
    updated_at: str
    version: int


class Inspector(TypedDict):
    id: str
    full_name: str
    nrpp_license_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MitigationCrew(TypedDict):
    id: str
    crew_name: str
    max_jobs_per_day: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RadonTest(TypedDict):
    id: str
    property_id: str
    inspector_id: str
    test_kind: str
    purpose: str
    mitigation_job_id: Optional[str]
    placement_start_utc: str
    placement_window_hours: int
    hourly_readings: Optional[List[float]]
    lab_integrated_pci_l: Optional[float]
    result_pci_l: Optional[float]
    action_outcome: Optional[str]
    warmup_hours_dropped: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MitigationJob(TypedDict):
    id: str
    property_id: str
    triggering_test_id: str
    crew_id: Optional[str]
    system_design: str
    num_suction_points: int
    has_sump_pump: bool
    is_rush: bool
    warranty_term_days: int
    warranty_guarantee_ceiling_pci_l: float
    warranty_refund_method: str
    retest_interval_days: int
    quote_subtotal_cents: Optional[int]
    rush_surcharge_cents: int
    quote_total_cents: Optional[int]
    deposit_required_cents: Optional[int]
    deposit_paid_cents: int
    balance_paid_cents: int
    permit_id: Optional[str]
    install_start_utc: Optional[str]
    install_end_utc: Optional[str]
    retest_passed: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    mitigation_job_id: str
    jurisdiction_code: str
    permit_number: str
    issued_at_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Warranty(TypedDict):
    id: str
    mitigation_job_id: str
    property_id: str
    covered_system_price_cents: int
    term_days: int
    started_at_utc: str
    guarantee_ceiling_pci_l: float
    refund_method: str
    refund_paid_cents: int
    coverage_status: str
    claim_status: str
    created_at: str
    updated_at: str
    version: int


class RetestSchedule(TypedDict):
    id: str
    warranty_id: str
    property_id: str
    interval_days: int
    next_due_utc: str
    last_fired_utc: Optional[str]
    fired_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only ledger entry: id + created_at only, NO updated_at, NO version.
class PaymentRecord(TypedDict):
    id: str
    mitigation_job_id: str
    kind: str
    amount_cents: int
    recorded_at_utc: str
    created_at: str


class ClockState(TypedDict):
    id: str
    current_utc: str
    created_at: str
