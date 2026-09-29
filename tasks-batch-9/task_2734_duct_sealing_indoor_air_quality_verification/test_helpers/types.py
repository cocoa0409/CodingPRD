"""Payload shapes for the request bodies described in PRD sections 2 and 3.

These are `TypedDict`s with `total=False`, so they document the field names the
PRD declares without forcing a test to supply optional ones. They exist to keep
field spelling in one place: a rename here is a single-file edit.
"""

from typing import Any, Dict, List, Optional, TypedDict


class ClockPayload(TypedDict, total=False):
    to_iso8601: str


class UtilityProgramPayload(TypedDict, total=False):
    name: str
    rebate_basis: str
    rate_cents_per_cfm_reduced: int
    pct_of_invoice_bps: int
    cap_cents: int
    annual_budget_cents: int
    min_reduction_pct: float
    requires_inspector_verification: bool
    combustion_safety_required: bool


class TechnicianPayload(TypedDict, total=False):
    full_name: str
    license_number: str
    certification_status: str
    certification_expires_at: Optional[str]


class CertificationPayload(TypedDict, total=False):
    certification_status: str
    certification_expires_at: Optional[str]


class ProjectPayload(TypedDict, total=False):
    utility_program_id: Optional[str]
    address_line: str
    conditioned_floor_area_sqft: int
    gas_appliance_count: int
    invoice_amount_cents: int


class SafetyHoldPayload(TypedDict, total=False):
    safety_hold_reason: str


class ReleaseSafetyHoldPayload(TypedDict, total=False):
    release_note: str


class DuctSystemPayload(TypedDict, total=False):
    system_label: str
    total_register_count: int
    design_cfm: float
    duct_material: str
    condition_grade: str


class AsbestosScreeningPayload(TypedDict, total=False):
    asbestos_screening_result: str
    lab_reference: str


class ExcludePayload(TypedDict, total=False):
    exclusion_reason: str


class LeakageTestPayload(TypedDict, total=False):
    duct_system_id: str
    phase: str
    method: str
    window_start_at: str
    window_end_at: str


class PressurizePayload(TypedDict, total=False):
    test_pressure_pa: float
    fan_ring_config: str
    masked_register_count: int


class RecordPayload(TypedDict, total=False):
    measured_leakage_cfm: float
    ambient_temp_f: float


class ReviewPayload(TypedDict, total=False):
    decision: str
    review_note: Optional[str]


class CombustionTestPayload(TypedDict, total=False):
    appliance_label: str
    appliance_type: str
    phase: str
    spillage_seconds: int
    co_ppm_air_free: float
    draft_pressure_pa: float
    worst_case_depressurization_pa: float


class SealJobPayload(TypedDict, total=False):
    duct_system_id: str
    pre_test_id: str
    technician_id: str
    retest_of_job_id: Optional[str]
    scheduled_start_at: str
    scheduled_end_at: str
    target_leakage_cfm: float
    expected_duct_system_version: int


class MasksPayload(TypedDict, total=False):
    register_labels: List[str]


class LeakageSamplePayload(TypedDict, total=False):
    sample_seq: int
    elapsed_seconds: int
    instantaneous_leakage_cfm: float
    injection_pressure_pa: float


class PausePayload(TypedDict, total=False):
    pause_reason: str


class CompleteSealPayload(TypedDict, total=False):
    sealant_lbs_used: float


class AbortPayload(TypedDict, total=False):
    abort_reason: str


class WarrantyRegistrationPayload(TypedDict, total=False):
    homeowner_name: str
    homeowner_email: str


class VerificationReportPayload(TypedDict, total=False):
    seal_job_id: str
    post_test_id: str
    expected_seal_job_version: int


class IssuePayload(TypedDict, total=False):
    signature_note: str


class RebateClaimPayload(TypedDict, total=False):
    verification_report_id: str
    utility_program_id: str
    documentation_bundle_ref: str


class InspectorVerificationPayload(TypedDict, total=False):
    spot_check_leakage_cfm: float
    spot_check_pressure_pa: float


class ResubmitPayload(TypedDict, total=False):
    documentation_bundle_ref: str


class PayPayload(TypedDict, total=False):
    payment_reference: str


class ComfortComplaintPayload(TypedDict, total=False):
    project_id: str
    room_label: str
    complaint_type: str
    reported_by: str


class DiagnosePayload(TypedDict, total=False):
    diagnosis_code: str
    tolerance_pct: float


class BalancePayload(TypedDict, total=False):
    damper_adjustment_note: str


class AirflowReadingPayload(TypedDict, total=False):
    room_label: str
    reading_seq: int
    measured_cfm: float
    design_cfm: float
    damper_position_pct: float


#: Any decoded `data` object from the success envelope.
Entity = Dict[str, Any]
