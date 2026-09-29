"""Request-payload builders.

Each builder returns a payload that is valid on its own and accepts `**overrides`
so a test can perturb exactly the one field it is about. Optional fields are
omitted unless a caller names them, so that "omitted optional inputs take their
declared defaults" stays observable.
"""

import itertools
from typing import Any, Dict, List

from .constants import (
    APPLIANCE_ATMOSPHERIC_WATER_HEATER,
    COMPLAINT_TOO_COLD,
    DECISION_ACCEPT,
    DIAG_DAMPER_MISADJUSTED,
    GRADE_B,
    MATERIAL_SHEET_METAL,
    METHOD_DUCT_BLASTER,
    PHASE_POST,
    PHASE_PRE,
    REBATE_BASIS_PER_CFM,
    RING_2,
    SCREENING_CLEARED,
)


def _merge(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides; a value of `None` removes the key entirely.

    Removal matters for the "required field missing" and "optional field omitted"
    translations, which must not send a literal null where the PRD means absent.
    """
    out = dict(payload)
    for key, value in overrides.items():
        if value is _OMIT:
            out.pop(key, None)
        else:
            out[key] = value
    return out


class _Omit:
    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "OMIT"


#: Sentinel: pass `field=OMIT` to leave a field out of the payload altogether.
OMIT = _Omit()
_OMIT = OMIT


# ---------------------------------------------------------------------------
# Instants on the logical clock
# ---------------------------------------------------------------------------
def utc(
    year: int = 2026,
    month: int = 8,
    day: int = 1,
    hour: int = 0,
    minute: int = 0,
    second: int = 0,
) -> str:
    """An ISO 8601 UTC instant in the shape the PRD accepts as input."""
    return f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}Z"


def stamp(
    year: int = 2026,
    month: int = 8,
    day: int = 1,
    hour: int = 0,
    minute: int = 0,
    second: int = 0,
) -> str:
    """The same instant as the server renders it, with three fractional digits."""
    return (
        f"{year:04d}-{month:02d}-{day:02d}T"
        f"{hour:02d}:{minute:02d}:{second:02d}.000Z"
    )


# ---------------------------------------------------------------------------
# Program, technician, project
# ---------------------------------------------------------------------------
def utility_program_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "name": "Metro Gas Duct Seal 2026",
            "rebate_basis": REBATE_BASIS_PER_CFM,
            "rate_cents_per_cfm_reduced": 1200,
            "pct_of_invoice_bps": 3000,
            "cap_cents": 500000,
            "annual_budget_cents": 5000000,
            "min_reduction_pct": 80.00,
            "requires_inspector_verification": True,
            "combustion_safety_required": True,
        },
        overrides,
    )


#: PRD 3.1 requires `license_number` to be unique across all technician rows, so
#: the default payload mints a fresh licence on every call. A test that needs a
#: specific licence still passes `license_number=` explicitly.
_license_counter = itertools.count(4417)


def technician_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "full_name": "Dana Ruiz",
            "license_number": f"AS-{next(_license_counter)}",
            "certification_status": "ACTIVE",
            "certification_expires_at": utc(2027, 6, 30),
        },
        overrides,
    )


def certification_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "certification_status": "ACTIVE",
            "certification_expires_at": utc(2027, 6, 30),
        },
        overrides,
    )


def project_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "address_line": "18 Larkspur Ln",
            "conditioned_floor_area_sqft": 2000,
            "gas_appliance_count": 1,
            "invoice_amount_cents": 480000,
        },
        overrides,
    )


def safety_hold_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"safety_hold_reason": "homeowner reported flue odor"}, overrides)


def release_safety_hold_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"release_note": "combustion safety re-established"}, overrides)


# ---------------------------------------------------------------------------
# Duct systems
# ---------------------------------------------------------------------------
def duct_system_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "system_label": "AHU-1",
            "total_register_count": 9,
            "design_cfm": 1200.0,
            "duct_material": MATERIAL_SHEET_METAL,
            "condition_grade": GRADE_B,
        },
        overrides,
    )


def asbestos_screening_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"asbestos_screening_result": SCREENING_CLEARED, "lab_reference": "LAB-1001"},
        overrides,
    )


def exclude_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"exclusion_reason": "STRUCTURAL_DAMAGE"}, overrides)


# ---------------------------------------------------------------------------
# Leakage measurements
# ---------------------------------------------------------------------------
def leakage_test_payload(duct_system_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "duct_system_id": duct_system_id,
            "phase": PHASE_PRE,
            "method": METHOD_DUCT_BLASTER,
            "window_start_at": utc(2026, 8, 1, 13, 0),
            "window_end_at": utc(2026, 8, 1, 15, 0),
        },
        overrides,
    )


def post_leakage_test_payload(duct_system_id: str, **overrides: Any) -> Dict[str, Any]:
    return leakage_test_payload(
        duct_system_id,
        **_merge(
            {
                "phase": PHASE_POST,
                "window_start_at": utc(2026, 8, 2, 19, 0),
                "window_end_at": utc(2026, 8, 2, 20, 0),
            },
            overrides,
        ),
    )


def pressurize_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "test_pressure_pa": 25.0,
            "fan_ring_config": RING_2,
            "masked_register_count": 9,
        },
        overrides,
    )


def record_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"measured_leakage_cfm": 300.0, "ambient_temp_f": 78.0}, overrides)


def review_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"decision": DECISION_ACCEPT}, overrides)


# ---------------------------------------------------------------------------
# Combustion tests
# ---------------------------------------------------------------------------
def combustion_test_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "appliance_label": "WH-1",
            "appliance_type": APPLIANCE_ATMOSPHERIC_WATER_HEATER,
            "phase": PHASE_PRE,
            "spillage_seconds": 12,
            "co_ppm_air_free": 18.0,
            "draft_pressure_pa": 2.5,
            "worst_case_depressurization_pa": 3.0,
        },
        overrides,
    )


def post_combustion_test_payload(**overrides: Any) -> Dict[str, Any]:
    return combustion_test_payload(
        **_merge(
            {
                "phase": PHASE_POST,
                "spillage_seconds": 8,
                "co_ppm_air_free": 14.0,
                "draft_pressure_pa": 2.7,
                "worst_case_depressurization_pa": 2.8,
            },
            overrides,
        )
    )


# ---------------------------------------------------------------------------
# Sealing runs
# ---------------------------------------------------------------------------
def seal_job_payload(
    duct_system_id: str,
    pre_test_id: str,
    technician_id: str,
    expected_duct_system_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "duct_system_id": duct_system_id,
            "pre_test_id": pre_test_id,
            "technician_id": technician_id,
            "scheduled_start_at": utc(2026, 8, 2, 13, 0),
            "scheduled_end_at": utc(2026, 8, 2, 18, 0),
            "target_leakage_cfm": 60.0,
            "expected_duct_system_version": expected_duct_system_version,
        },
        overrides,
    )


def register_labels(count: int, prefix: str = "R") -> List[str]:
    """`["R1", "R2", ...]` — one label per register that must be masked."""
    return [f"{prefix}{i}" for i in range(1, count + 1)]


def masks_payload(labels: List[str]) -> Dict[str, Any]:
    return {"register_labels": list(labels)}


def leakage_sample_payload(
    sample_seq: int,
    instantaneous_leakage_cfm: float,
    elapsed_seconds: int,
    injection_pressure_pa: float = 700.0,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "sample_seq": sample_seq,
            "elapsed_seconds": elapsed_seconds,
            "instantaneous_leakage_cfm": instantaneous_leakage_cfm,
            "injection_pressure_pa": injection_pressure_pa,
        },
        overrides,
    )


def pause_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"pause_reason": "compressor cool-down"}, overrides)


def complete_seal_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"sealant_lbs_used": 3.2}, overrides)


def abort_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"abort_reason": "homeowner stopped work mid-run"}, overrides)


def warranty_registration_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"homeowner_name": "Priya Raman", "homeowner_email": "priya@example.com"},
        overrides,
    )


# ---------------------------------------------------------------------------
# Verification reports and rebate claims
# ---------------------------------------------------------------------------
def verification_report_payload(
    seal_job_id: str, post_test_id: str, expected_seal_job_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "seal_job_id": seal_job_id,
            "post_test_id": post_test_id,
            "expected_seal_job_version": expected_seal_job_version,
        },
        overrides,
    )


def issue_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"signature_note": "guarantee verified"}, overrides)


def rebate_claim_payload(
    verification_report_id: str, utility_program_id: str, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "verification_report_id": verification_report_id,
            "utility_program_id": utility_program_id,
            "documentation_bundle_ref": "BUNDLE-77",
        },
        overrides,
    )


def inspector_verification_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"spot_check_leakage_cfm": 57.0, "spot_check_pressure_pa": 25.0}, overrides
    )


def resubmit_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"documentation_bundle_ref": "BUNDLE-77-REV2"}, overrides)


def pay_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"payment_reference": "ACH-90211"}, overrides)


# ---------------------------------------------------------------------------
# Comfort complaints
# ---------------------------------------------------------------------------
def comfort_complaint_payload(project_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "project_id": project_id,
            "room_label": "Living Room",
            "complaint_type": COMPLAINT_TOO_COLD,
            "reported_by": "Priya Raman",
        },
        overrides,
    )


def diagnose_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"diagnosis_code": DIAG_DAMPER_MISADJUSTED, "tolerance_pct": 10.00}, overrides
    )


def balance_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"damper_adjustment_note": "opened the living-room branch damper"}, overrides
    )


def airflow_reading_payload(
    room_label: str,
    reading_seq: int,
    measured_cfm: float,
    design_cfm: float = 120.0,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "room_label": room_label,
            "reading_seq": reading_seq,
            "measured_cfm": measured_cfm,
            "design_cfm": design_cfm,
            "damper_position_pct": 60.0,
        },
        overrides,
    )
