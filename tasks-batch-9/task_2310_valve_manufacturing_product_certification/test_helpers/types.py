"""
Typed shapes for the Valve Manufacturing & Product Certification API.

Status vocabularies and entity field sets are transcribed from the PRD. Every
primary resource carries the common server-managed properties of §2.4 — ``id``,
``created_at``, ``updated_at`` and ``version``. The one exception is ``TestRecord``:
a test record is immutable once written and carries ``id`` and ``created_at`` only.
"""

from typing import Any, Dict, List, Optional, TypedDict


# ─── Status vocabularies ──────────────────────────────


class ModelStatus:
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    RELEASED = "RELEASED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class FoundryStatus:
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class QualificationStatus:
    PENDING = "PENDING"
    QUALIFIED = "QUALIFIED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class HeatLotStatus:
    RECEIVED = "RECEIVED"
    VERIFIED = "VERIFIED"
    RELEASED = "RELEASED"
    QUARANTINED = "QUARANTINED"
    REJECTED = "REJECTED"


class ComponentStatus:
    CREATED = "CREATED"
    ISSUED_TO_MACHINING = "ISSUED_TO_MACHINING"
    CONSUMED = "CONSUMED"
    HOLD = "HOLD"
    SCRAPPED = "SCRAPPED"
    VOIDED = "VOIDED"


class BuildStatus:
    BLANK = "BLANK"
    MACHINED = "MACHINED"
    ASSEMBLED = "ASSEMBLED"
    PACKAGED = "PACKAGED"
    SHIPPED = "SHIPPED"
    REWORK = "REWORK"


class CertStatus:
    UNCERTIFIED = "UNCERTIFIED"
    TESTS_IN_PROGRESS = "TESTS_IN_PROGRESS"
    TESTS_PASSED = "TESTS_PASSED"
    TESTS_FAILED = "TESTS_FAILED"
    CERTIFIED = "CERTIFIED"
    DECERTIFIED = "DECERTIFIED"


class ServiceStatus:
    NONE = "NONE"
    OPEN = "OPEN"
    PARTS_RESERVED = "PARTS_RESERVED"
    IN_SERVICE = "IN_SERVICE"
    SERVICED = "SERVICED"


class SizingStatus:
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class LicenseStatus:
    APPLIED = "APPLIED"
    GRANTED = "GRANTED"
    CONDITIONAL = "CONDITIONAL"
    SUSPENDED = "SUSPENDED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class AuditState:
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    CLOSED = "CLOSED"


class CompliancePosture:
    COMPLIANT = "COMPLIANT"
    CONDITIONAL = "CONDITIONAL"
    FROZEN = "FROZEN"


class OrderStatus:
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    CLARIFICATION_REQUESTED = "CLARIFICATION_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    IN_PRODUCTION = "IN_PRODUCTION"
    HELD = "HELD"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class DocPackageStatus:
    ASSEMBLING = "ASSEMBLING"
    COMPLETE = "COMPLETE"
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


class EmissionLeakClass:
    AA = "AA"
    A = "A"
    B = "B"
    C = "C"
    FAIL = "FAIL"


class TestResult:
    PASS = "PASS"
    FAIL = "FAIL"


# ─── Entity shapes ────────────────────────────────────


class CommonFields(TypedDict, total=False):
    """The server-managed properties every primary resource carries (PRD §2.4)."""

    id: str
    created_at: str
    updated_at: str
    version: int


class ValveModel(CommonFields, total=False):
    model_code: str
    valve_type: str
    pressure_class: int
    body_material_grade: str
    bore_size_mm: float
    seat_type: str
    base_break_torque_nm: float
    required_special_services: List[str]
    repair_kit_stock_qty: int
    supersedes_model_id: Optional[str]
    status: str
    spec_revision: int
    qualified_special_services: List[str]
    authored_by_user_id: str
    released_at: Optional[str]


class Foundry(CommonFields, total=False):
    foundry_code: str
    name: str
    country_code: str
    total_lot_count: int
    rejected_lot_count: int
    revoked_qualification_count: int
    quality_index: float
    status: str


class FoundryQualification(CommonFields, total=False):
    foundry_id: str
    process: str
    material_grade: str
    max_pressure_class: int
    valid_from: str
    valid_until: str
    status: str
    requalification_count: int
    qualified_by_user_id: Optional[str]


class HeatLot(CommonFields, total=False):
    foundry_id: str
    heat_number: str
    material_grade: str
    process: str
    qty_received_kg: float
    mtr_document_ref: str
    carbon_equivalent_pct: float
    impact_energy_j: float
    status: str
    qty_committed_kg: float
    qty_scrapped_kg: float
    qty_available_kg: float
    verified_by_user_id: Optional[str]
    quarantine_reason: Optional[str]


class Component(CommonFields, total=False):
    heat_lot_id: str
    target_model_id: str
    component_type: str
    net_weight_kg: float
    status: str
    pre_hold_status: Optional[str]


class ValveUnit(CommonFields, total=False):
    model_id: str
    body_component_id: str
    monogram_license_id: str
    serial_number: str
    special_services: List[str]
    engineered_order_id: Optional[str]
    build_status: str
    cert_status: str
    service_status: str
    reserved_kit_qty: int
    service_engineer_user_id: Optional[str]
    provisional_emission_leak_class: Optional[str]
    final_emission_leak_class: Optional[str]
    certified_by_user_id: Optional[str]
    certified_at: Optional[str]
    decertification_reason: Optional[str]


class TestRecord(TypedDict, total=False):
    """A TestRecord is immutable once written: it carries ``id`` and ``created_at``
    only, and has neither an ``updated_at`` field nor a ``version`` field (PRD §2.4)."""

    id: str
    created_at: str
    valve_unit_id: str
    test_type: str
    test_bench_code: str
    started_at: str
    ended_at: str
    test_pressure_bar: float
    hold_seconds: int
    result: str
    leak_rate_ppm: Optional[float]
    leak_drops: Optional[int]
    standard_ref: str
    performed_by_user_id: str
    required_pressure_bar: float
    required_hold_seconds: int


class ActuatorPackage(CommonFields, total=False):
    valve_unit_id: str
    actuator_type: str
    output_torque_nm: float
    sizing_basis: str
    supply_pressure_bar: Optional[float]
    sizing_status: str
    required_torque_nm: float
    safety_margin_pct: float
    sized_torque_nm: float
    approved_by_user_id: Optional[str]


class MonogramLicense(CommonFields, total=False):
    license_code: str
    facility_code: str
    scope_valve_types: List[str]
    lead_auditor_user_id: str
    audit_window_start: str
    audit_window_end: str
    license_status: str
    audit_state: str
    compliance_posture: str
    total_major_raised: int
    total_minor_raised: int
    closed_major_finding_count: int
    closed_minor_finding_count: int
    waived_major_finding_count: int
    open_major_finding_count: int
    open_minor_finding_count: int
    last_audit_closed_at: Optional[str]
    granted_at: Optional[str]
    conditional_expires_at: Optional[str]


class OrderDocumentEntry(TypedDict, total=False):
    doc_type: str
    doc_ref: str
    added_at: str


class EngineeredOrder(CommonFields, total=False):
    order_code: str
    model_id: str
    ordered_qty: int
    unit_price_cents: int
    customer_credit_limit_cents: int
    datasheet_break_torque_nm: float
    datasheet_torque_source: str
    requested_special_services: List[str]
    expedite_requested: bool
    status: str
    doc_package_status: str
    datasheet_revision_no: int
    clarification_round_count: int
    documents: List[OrderDocumentEntry]
    documentation_completeness_pct: float
    pinned_model_id: Optional[str]
    pinned_model_spec_revision: Optional[int]
    spec_stale: bool
    held_reason: Optional[str]
    gross_quoted_cents: int
    net_billable_cents: int
    credit_issued_cents: int
    certified_unit_count: int


Headers = Dict[str, str]
Payload = Dict[str, Any]
