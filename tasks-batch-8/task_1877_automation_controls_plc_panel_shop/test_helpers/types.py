"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PROJECT_MANAGER = "ProjectManager"
    QA_MANAGER = "QAManager"
    DESIGN_ENGINEER = "DesignEngineer"
    SHOP_LEAD = "ShopLead"
    TEST_TECHNICIAN = "TestTechnician"
    CONTROLS_ENGINEER = "ControlsEngineer"
    FIELD_ENGINEER = "FieldEngineer"
    SHIPPING_CLERK = "ShippingClerk"
    CUSTOMER = "Customer"


class JobStatus(str, Enum):
    OPEN = "OPEN"
    DESIGN = "DESIGN"
    PROCUREMENT = "PROCUREMENT"
    BUILD = "BUILD"
    TEST = "TEST"
    READY_TO_SHIP = "READY_TO_SHIP"
    SHIPPED = "SHIPPED"
    COMMISSIONED = "COMMISSIONED"
    CLOSED = "CLOSED"
    ON_HOLD = "ON_HOLD"


class PanelStatus(str, Enum):
    DESIGN = "DESIGN"
    DESIGN_REVIEW = "DESIGN_REVIEW"
    DESIGN_APPROVED = "DESIGN_APPROVED"
    PROCUREMENT = "PROCUREMENT"
    WIRING = "WIRING"
    POINT_TO_POINT = "POINT_TO_POINT"
    TEST_PASSED = "TEST_PASSED"
    TEST_FAILED = "TEST_FAILED"
    READY_FOR_LABEL = "READY_FOR_LABEL"
    LABELED = "LABELED"
    SHIPPED = "SHIPPED"
    COMMISSIONED = "COMMISSIONED"


class ComponentClass(str, Enum):
    DISCONNECT = "DISCONNECT"
    BRANCH_PROTECTIVE = "BRANCH_PROTECTIVE"
    CONTACTOR = "CONTACTOR"
    OVERLOAD = "OVERLOAD"
    CONTROL_POWER = "CONTROL_POWER"
    PLC_IO = "PLC_IO"
    TERMINAL = "TERMINAL"
    WIRE_DUCT = "WIRE_DUCT"
    PILOT_DEVICE = "PILOT_DEVICE"
    POWER_SUPPLY = "POWER_SUPPLY"


class LineStatus(str, Enum):
    PENDING = "PENDING"
    ORDERED = "ORDERED"
    RECEIVED = "RECEIVED"
    SUBSTITUTED = "SUBSTITUTED"


class SubstitutionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    COUNTERED = "COUNTERED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class TestPointResult(str, Enum):
    UNTESTED = "UNTESTED"
    PASS = "PASS"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"


class TestSessionStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class ProgramVersionStatus(str, Enum):
    DRAFT = "DRAFT"
    RELEASED = "RELEASED"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"


class StartupSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class SupportMode(str, Enum):
    ONSITE = "ONSITE"
    REMOTE = "REMOTE"


class ChangeOrderStatus(str, Enum):
    PROPOSED = "PROPOSED"
    REVISED = "REVISED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    SUPERSEDED = "SUPERSEDED"


class WarrantyClaimStatus(str, Enum):
    FILED = "FILED"
    TRIAGED = "TRIAGED"
    ACCEPTED = "ACCEPTED"
    DENIED = "DENIED"
    SETTLED = "SETTLED"
    CLOSED = "CLOSED"


class AsBuiltStatus(str, Enum):
    INCOMPLETE = "INCOMPLETE"
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    RELEASED = "RELEASED"


class WarrantyLaborTier(str, Enum):
    TIER_LOCAL = "TIER_LOCAL"
    TIER_REGIONAL = "TIER_REGIONAL"
    TIER_NATIONAL = "TIER_NATIONAL"


class EnclosureRating(str, Enum):
    NEMA_1 = "NEMA_1"
    NEMA_12 = "NEMA_12"
    NEMA_4 = "NEMA_4"
    NEMA_4X = "NEMA_4X"


class ExpectedSignal(str, Enum):
    CONTINUITY = "CONTINUITY"
    VOLTAGE_24VDC = "VOLTAGE_24VDC"
    VOLTAGE_120VAC = "VOLTAGE_120VAC"
    ANALOG_4_20MA = "ANALOG_4_20MA"
    ISOLATION = "ISOLATION"


# --- Entity TypedDicts (common fields per PRD §2.4) ---


class Customer(TypedDict, total=False):
    id: str
    company_name: str
    site_state_code: str
    credit_hold: bool
    warranty_labor_tier: str
    created_at: str
    updated_at: str
    version: int


class Job(TypedDict, total=False):
    id: str
    customer_id: str
    job_number: str
    status: str
    quoted_price_cents: int
    approved_co_delta_cents: int
    contract_price_cents: int
    warranty_months: int
    warranty_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Panel(TypedDict, total=False):
    id: str
    job_id: str
    panel_tag: str
    status: str
    enclosure_rating: str
    design_engineer_id: str
    sccr_rating_ka: int
    label_serial: Optional[str]
    shipped_at: Optional[str]
    commissioned_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Component(TypedDict, total=False):
    id: str
    part_number: str
    component_class: str
    unit_cost_cents: int
    lead_time_days: int
    sccr_ka: Optional[int]
    heat_dissipation_w: float
    active: bool
    created_at: str
    updated_at: str
    version: int


class PanelComponent(TypedDict, total=False):
    id: str
    panel_id: str
    component_id: str
    quantity: int
    line_status: str
    substituted_for_id: Optional[str]
    extended_cost_cents: int
    unit_cost_snapshot_cents: int
    created_at: str
    updated_at: str
    version: int


class SubstitutionRequest(TypedDict, total=False):
    id: str
    panel_id: str
    original_line_id: str
    proposed_component_id: str
    status: str
    reason: str
    requested_by_id: str
    lead_time_delta_days: Optional[int]
    sccr_impact_ka: Optional[int]
    created_at: str
    updated_at: str
    version: int


# TestPoint carries id + created_at only (PRD §2.4) — NO updated_at, NO version.
class TestPoint(TypedDict, total=False):
    id: str
    panel_id: str
    point_label: str
    expected_signal: str
    sequence_no: int
    result: str
    created_at: str


class TestSession(TypedDict, total=False):
    id: str
    panel_id: str
    technician_id: str
    status: str
    started_at: str
    completed_at: Optional[str]
    pass_count: int
    fail_count: int
    created_at: str
    updated_at: str
    version: int


# ProgramVersion carries id + created_at only (PRD §2.4) — NO updated_at, NO version.
class ProgramVersion(TypedDict, total=False):
    id: str
    panel_id: str
    version_tag: str
    status: str
    content_hash: str
    site_backup_taken: bool
    released_at: Optional[str]
    created_at: str


class StartupSession(TypedDict, total=False):
    id: str
    panel_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    remote_access_granted: bool
    support_mode: str
    engineer_id: str
    labor_hours: float
    billable_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ChangeOrder(TypedDict, total=False):
    id: str
    job_id: str
    co_number: int
    status: str
    description: str
    price_delta_cents: int
    discount_pct: float
    computed_delta_cents: int
    requested_by_id: str
    supersedes_co_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    job_id: str
    panel_id: str
    status: str
    defect_description: str
    filed_at: str
    claimed_labor_hours: float
    provisional_liability_cents: Optional[int]
    final_liability_cents: Optional[int]
    liability_delta_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class AsBuiltPackage(TypedDict, total=False):
    id: str
    panel_id: str
    status: str
    has_wiring_diagram: bool
    has_program_archive: bool
    has_test_report: bool
    has_ul_label_photo: bool
    completeness_pct: int
    created_at: str
    updated_at: str
    version: int
