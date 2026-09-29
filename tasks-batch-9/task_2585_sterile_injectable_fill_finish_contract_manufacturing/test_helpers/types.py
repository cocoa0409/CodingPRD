"""Shapes of the persisted resources and the enum vocabularies they carry.

Every resource of PRD 2.4 carries a server-minted `id` and a `created_at`.
Fourteen of the fifteen additionally carry `updated_at` and an integer
`version`; the Qualified-Person release decision is the single append-only
exception and its TypedDict below therefore declares neither field.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

try:  # pragma: no cover - typing_extensions is present on modern runners
    from typing import TypedDict
except ImportError:  # pragma: no cover
    from typing_extensions import TypedDict  # type: ignore

Json = Dict[str, Any]
Headers = Dict[str, str]


# ---------------------------------------------------------------------------
# Enum vocabularies (PRD 3.1 - 3.9)
# ---------------------------------------------------------------------------
class ProjectStatus:
    INTAKE = "INTAKE"
    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"


class TechTransferStage:
    NOT_STARTED = "NOT_STARTED"
    GAP_ASSESSMENT = "GAP_ASSESSMENT"
    ENGINEERING_RUN = "ENGINEERING_RUN"
    COMPLETE = "COMPLETE"

    ORDER = (NOT_STARTED, GAP_ASSESSMENT, ENGINEERING_RUN, COMPLETE)


class AnalyticalTransferStatus:
    NOT_STARTED = "NOT_STARTED"
    IN_TRANSFER = "IN_TRANSFER"
    VALIDATED = "VALIDATED"

    ORDER = (NOT_STARTED, IN_TRANSFER, VALIDATED)


class DosageForm:
    VIAL = "VIAL"
    PRESYRINGE = "PRESYRINGE"


class SuiteGrade:
    A = "A"
    B = "B"
    C = "C"


class AsepticQualificationStatus:
    NOT_QUALIFIED = "NOT_QUALIFIED"
    QUALIFIED = "QUALIFIED"
    INVALIDATED = "INVALIDATED"


class CleaningValidationStatus:
    NOT_VALIDATED = "NOT_VALIDATED"
    VALIDATED = "VALIDATED"
    FAILED = "FAILED"


class SuitePosture:
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class MediaFillStatus:
    SCHEDULED = "SCHEDULED"
    INCUBATING = "INCUBATING"
    PASSED = "PASSED"
    INVESTIGATION_REQUIRED = "INVESTIGATION_REQUIRED"
    FAILED = "FAILED"


class MediaFillOutcomeReason:
    ZERO_CONTAMINANT_PASS = "ZERO_CONTAMINANT_PASS"
    SINGLE_UNIT_INVESTIGATION = "SINGLE_UNIT_INVESTIGATION"
    MULTI_UNIT_FAILURE = "MULTI_UNIT_FAILURE"
    ADJUDICATED_PASS = "ADJUDICATED_PASS"
    ADJUDICATED_FAILURE = "ADJUDICATED_FAILURE"


class QualificationType:
    GOWNING = "GOWNING"
    ASEPTIC_INTERVENTION = "ASEPTIC_INTERVENTION"
    VISUAL_INSPECTION = "VISUAL_INSPECTION"


class QualificationStatus:
    PENDING = "PENDING"
    QUALIFIED = "QUALIFIED"
    LAPSED = "LAPSED"
    REVOKED = "REVOKED"


class ComponentType:
    VIAL = "VIAL"
    STOPPER = "STOPPER"
    SYRINGE = "SYRINGE"
    PLUNGER = "PLUNGER"


class ComponentLotStatus:
    QUARANTINE = "QUARANTINE"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    EXHAUSTED = "EXHAUSTED"


class SterilizationValidationStatus:
    PENDING = "PENDING"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"


class ReservationStatus:
    RESERVED = "RESERVED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class ReleasedReason:
    BATCH_CANCELLED = "BATCH_CANCELLED"
    SUITE_FREEZE_SUSPENSION = "SUITE_FREEZE_SUSPENSION"


class ProductionStatus:
    SCHEDULED = "SCHEDULED"
    SETUP = "SETUP"
    FILLING = "FILLING"
    FILLED = "FILLED"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"

    # PRD 3.5: the batches that hold a claim on a suite and on a unit budget.
    LIVE = (SCHEDULED, SETUP, FILLING, FILLED)


class QualityStatus:
    PENDING = "PENDING"
    IN_PROCESS_REVIEW = "IN_PROCESS_REVIEW"
    BR_REVIEW = "BR_REVIEW"
    QP_REVIEW = "QP_REVIEW"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"
    QUARANTINED = "QUARANTINED"


class CheckType:
    FILL_WEIGHT = "FILL_WEIGHT"
    CCI = "CCI"
    VISUAL_INSPECTION = "VISUAL_INSPECTION"

    REQUIRED = (FILL_WEIGHT, CCI, VISUAL_INSPECTION)


class CheckResult:
    PASS = "PASS"
    ALERT = "ALERT"
    FAIL = "FAIL"


class SampleType:
    VIABLE_AIR = "VIABLE_AIR"
    SURFACE = "SURFACE"
    PERSONNEL_GLOVE = "PERSONNEL_GLOVE"


class EmClassification:
    WITHIN_LIMIT = "WITHIN_LIMIT"
    ALERT = "ALERT"
    ACTION = "ACTION"


class InvestigationStatus:
    NOT_REQUIRED = "NOT_REQUIRED"
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    CLOSED = "CLOSED"


class DeviationStatus:
    OPEN = "OPEN"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    CAPA_PENDING = "CAPA_PENDING"
    CLOSED = "CLOSED"


class DeviationClassification:
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class CapaOutcome:
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class BrReviewStatus:
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE_WITH_FINDINGS = "COMPLETE_WITH_FINDINGS"
    CLOSED = "CLOSED"


class QpDecision:
    RELEASE = "RELEASE"
    REJECT = "REJECT"
    QUARANTINE = "QUARANTINE"


class AuditKind:
    CLIENT_AUDIT = "CLIENT_AUDIT"
    INSPECTION_READINESS = "INSPECTION_READINESS"


class AuditStatus:
    REQUESTED = "REQUESTED"
    HOSTED = "HOSTED"
    DEFERRED = "DEFERRED"


class AuditOutcome:
    HOSTED = "HOSTED"
    DEFERRED = "DEFERRED"


class ReadinessVariant:
    INTAKE_FORECAST = "INTAKE_FORECAST"
    GMP_AUDIT = "GMP_AUDIT"


class SterilizationOutcome:
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"


class MediaFillAdjudication:
    PASSED = "PASSED"
    FAILED = "FAILED"


# ---------------------------------------------------------------------------
# Common audit stamps (PRD 2.4)
# ---------------------------------------------------------------------------
class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Resource shapes
# ---------------------------------------------------------------------------
class ClientProject(CommonFields, total=False):
    client_name: str
    molecule_name: str
    dosage_form: str
    primary_suite_id: str
    target_fill_weight_mg: int
    historical_reject_rate_ppm: int
    reserved_unit_budget: int
    status: str
    tech_transfer_stage: str
    analytical_method_transfer_status: str
    committed_demand_units: int
    open_deviation_risk_total: int
    last_client_audit_finding_count: int


class FillingSuite(CommonFields, total=False):
    suite_code: str
    grade: str
    changeover_minutes_same_product: int
    changeover_minutes_product_change: int
    max_committed_minutes: int
    aseptic_qualification_status: str
    cleaning_validation_status: str
    media_fill_valid_until: Optional[str]
    last_cleaned_molecule: Optional[str]
    committed_minutes: int
    open_action_excursion_count: int
    qualified_operator_count: int
    posture: str


class MediaFill(CommonFields, total=False):
    suite_id: str
    scheduled_run_date: str
    status: str
    units_filled: Optional[int]
    contaminated_units: Optional[int]
    participating_operator_names: List[str]
    outcome_reason: Optional[str]
    read_at: Optional[str]
    adjudication_rationale: Optional[str]


class PersonnelQualification(CommonFields, total=False):
    operator_name: str
    suite_id: str
    qualification_type: str
    expires_on: str
    media_fill_id: Optional[str]
    status: str
    qualified_at: Optional[str]
    revoke_reason: Optional[str]


class ComponentLot(CommonFields, total=False):
    client_project_id: str
    component_type: str
    lot_code: str
    quantity_received: int
    quantity_available: int
    sterilization_expiry: str
    status: str
    sterilization_validation_status: str
    f0_minutes: Optional[float]


class BatchOrder(CommonFields, total=False):
    client_project_id: str
    suite_id: str
    lead_operator_qualification_id: str
    batch_number: str
    planned_start: str
    planned_end: str
    target_fill_units: int
    production_status: str
    quality_status: str
    changeover_minutes_applied: int
    component_demand_units: int
    filled_unit_count: Optional[int]
    quarantined_unit_count: int
    provisional_releasable_units: Optional[int]
    final_releasable_units: Optional[int]
    release_fee_cents: Optional[int]
    cancellation_reason: Optional[str]


class ComponentReservation(CommonFields, total=False):
    batch_order_id: str
    component_lot_id: str
    quantity_reserved: int
    status: str
    released_reason: Optional[str]


class InProcessCheck(CommonFields, total=False):
    batch_order_id: str
    check_type: str
    sample_size: int
    reject_unit_count: int
    destructive_sample_units: int
    measured_fill_weights_mg: List[float]
    result: str
    max_absolute_deviation_pct: float


class EmSample(CommonFields, total=False):
    suite_id: str
    batch_order_id: Optional[str]
    sample_type: str
    cfu_count: int
    alert_limit: int
    action_limit: int
    classification: str
    investigation_status: str
    risk_index: int
    investigator_note: Optional[str]
    root_cause: Optional[str]


class Deviation(CommonFields, total=False):
    batch_order_id: str
    em_sample_id: Optional[str]
    summary: str
    status: str
    classification: Optional[str]
    classification_rationale: Optional[str]
    risk_score: int
    capa_rejection_count: int
    capa_summary: Optional[str]
    opened_by_user_id: str
    decision_note: Optional[str]


class BatchRecordReview(CommonFields, total=False):
    batch_order_id: str
    status: str
    reviewer_user_id: str
    open_findings_count: int
    findings_note: Optional[str]
    closed_at: Optional[str]


class AuditEngagement(CommonFields, total=False):
    client_project_id: str
    audit_kind: str
    requested_window_start: str
    status: str
    finding_count: int
    hosted_at: Optional[str]


class QpReleaseDecision(TypedDict, total=False):
    """PRD 2.4: append-only, so `id` and `created_at` and nothing else."""

    id: str
    created_at: str
    batch_order_id: str
    qp_user_id: str
    decision: str
    rationale: str
    released_unit_count: int
    fee_cents: int


# ---------------------------------------------------------------------------
# Computed reads (PRD 3.9)
# ---------------------------------------------------------------------------
class ReadinessAssessment(TypedDict, total=False):
    client_project_id: str
    variant: str
    readiness_score: int
    tech_points: int
    analytical_points: int
    aseptic_points: int
    operator_points: int
    counted_operator_count: int
    assessed_at: str


class UnitAccounting(TypedDict, total=False):
    batch_order_id: str
    filled_unit_count: int
    expected_reject_units: int
    actual_visual_reject_units: int
    destructive_total_units: int
    quarantined_unit_count: int
    provisional_releasable_units: int
    final_releasable_units: int
    variant_delta_units: int


class ClockState(TypedDict, total=False):
    current_utc: str
    lapsed_qualification_count: int
    expired_component_lot_count: int
