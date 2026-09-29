"""Request payload builders.

Each builder produces a valid body for one write endpoint using the field names
spelled exactly as the PRD spells them, and accepts ``**overrides`` so a test
may vary one member or drop one by passing ``None`` through ``omit``.
"""

import itertools
from typing import Any, Dict, List, Optional

from .constants import PASSING_SPECTRAL_TRACE
from .types import Payload

_counter = itertools.count(1)


def unique_suffix() -> str:
    """A monotonically increasing suffix for codes that must be unique."""
    return f"{next(_counter):04d}"


def omit(payload: Payload, *field_names: str) -> Payload:
    """Return a copy of ``payload`` with the named fields removed."""
    return {k: v for k, v in payload.items() if k not in field_names}


def _merge(base: Payload, overrides: Dict[str, Any]) -> Payload:
    base.update(overrides)
    return base


# ----------------------------------------------------------------------
# Optical designs and tolerance allocations
# ----------------------------------------------------------------------
def build_optical_design_payload(**overrides: Any) -> Payload:
    """A design create body. Aperture 120.0 mm over the 450-700 nm band."""
    return _merge(
        {
            "design_code": f"OD-2540-{unique_suffix()}",
            "aperture_mm": 120.0,
            "wavelength_min_nm": 450,
            "wavelength_max_nm": 700,
            "required_rms_wavefront_waves": 0.0400,
            "tolerance_budget_waves": 0.0800,
            "transmitted_wavefront_budget_waves": 0.1050,
            "min_center_thickness_um": 5800.0,
            "min_index_homogeneity_grade": "H3",
            "max_striae_grade": "B",
            "tolerance_method": "STATISTICAL",
        },
        overrides,
    )


def build_tolerance_allocation_payload(**overrides: Any) -> Payload:
    """A tolerance allocation body: sensitivity 1.5 on a 0.0250 wave tolerance."""
    return _merge(
        {
            "contributor_type": "SURFACE_IRREGULARITY",
            "sensitivity_waves_per_unit": 1.5,
            "manufacturing_tolerance_units": 0.0250,
        },
        overrides,
    )


def build_design_revision_payload(**overrides: Any) -> Payload:
    """A revision body carrying only the OCC guard on the design's version."""
    return _merge({"expected_design_version": 1}, overrides)


# ----------------------------------------------------------------------
# Glass lots
# ----------------------------------------------------------------------
def build_glass_lot_payload(**overrides: Any) -> Payload:
    """A glass lot receipt body: twenty N-BK7 blanks graded H2 / A."""
    return _merge(
        {
            "lot_code": f"GL-2540-{unique_suffix()}",
            "glass_type": "N-BK7",
            "melt_index_nd": 1.516800,
            "total_blank_count": 20,
            "blank_center_thickness_um": 6200.0,
            "declared_index_homogeneity_grade": "H2",
            "declared_striae_grade": "A",
        },
        overrides,
    )


def build_certification_payload(**overrides: Any) -> Payload:
    """A certification body naming the measured grades and the certificate."""
    return _merge(
        {
            "measured_index_homogeneity_grade": "H3",
            "measured_striae_grade": "B",
            "certificate_reference": "CERT-2540-1",
        },
        overrides,
    )


def build_block_payload(**overrides: Any) -> Payload:
    """A lot block body naming the melt nonconformance."""
    return _merge({"block_reason": "STRIAE_NONCONFORMANCE_FOUND_IN_RETEST"}, overrides)


# ----------------------------------------------------------------------
# Work orders
# ----------------------------------------------------------------------
def build_work_order_payload(
    design_id: str, glass_lot_id: str, expected_glass_lot_version: int, **overrides: Any
) -> Payload:
    """A work order body for a two-element order under the lot version guard."""
    return _merge(
        {
            "wo_code": f"WO-2540-{unique_suffix()}",
            "design_id": design_id,
            "glass_lot_id": glass_lot_id,
            "element_count": 2,
            "expected_glass_lot_version": expected_glass_lot_version,
        },
        overrides,
    )


def build_scrap_payload(**overrides: Any) -> Payload:
    """A work order scrap body naming an operator-supplied reason."""
    return _merge({"scrap_reason": "LATENT_SUBSURFACE_DEFECT"}, overrides)


def build_cancel_work_order_payload(**overrides: Any) -> Payload:
    """A work order cancel body."""
    return _merge({"cancel_reason": "CUSTOMER_ORDER_WITHDRAWN"}, overrides)


# ----------------------------------------------------------------------
# Metrology instruments, runs and reports
# ----------------------------------------------------------------------
def build_instrument_payload(**overrides: Any) -> Payload:
    """An interferometer body with a 0.0010 wave base uncertainty."""
    return _merge(
        {
            "instrument_code": f"IF-2540-{unique_suffix()}",
            "instrument_type": "PHASE_SHIFTING_INTERFEROMETER",
            "base_uncertainty_waves": 0.0010,
            "lateral_resolution_um": 5.0,
            "calibration_interval_days": 90,
            "last_calibrated_utc": "2026-08-01T00:00:00Z",
        },
        overrides,
    )


def build_calibration_payload(**overrides: Any) -> Payload:
    """A calibration event body stamping an explicit instant."""
    return _merge({"calibrated_at_utc": "2026-08-01T00:00:00Z"}, overrides)


def build_process_run_payload(
    work_order_id: str,
    metrology_instrument_id: str,
    run_stage: str = "POLISHING",
    metrology_window_start_utc: str = "2026-08-01T08:00:00Z",
    metrology_window_end_utc: str = "2026-08-01T10:00:00Z",
    **overrides: Any,
) -> Payload:
    """A process run body booking a two-hour exclusive metrology window."""
    return _merge(
        {
            "work_order_id": work_order_id,
            "metrology_instrument_id": metrology_instrument_id,
            "run_stage": run_stage,
            "metrology_window_start_utc": metrology_window_start_utc,
            "metrology_window_end_utc": metrology_window_end_utc,
        },
        overrides,
    )


def build_complete_run_payload(
    material_removed_nm: float = 800.0, **overrides: Any
) -> Payload:
    """A run completion body recording the material removed in nanometres."""
    return _merge({"material_removed_nm": material_removed_nm}, overrides)


def build_cancel_run_payload(**overrides: Any) -> Payload:
    """A run cancellation body."""
    return _merge({"cancel_reason": "RESCHEDULED_FOR_DRIFT_STUDY"}, overrides)


def build_metrology_report_payload(
    process_run_id: str, surface_rms_waves: float = 0.0200, **overrides: Any
) -> Payload:
    """A metrology report body carrying the mandatory surface RMS figure."""
    return _merge(
        {
            "process_run_id": process_run_id,
            "surface_rms_waves": surface_rms_waves,
        },
        overrides,
    )


# ----------------------------------------------------------------------
# Coating chambers and coating runs
# ----------------------------------------------------------------------
def build_coating_chamber_payload(**overrides: Any) -> Payload:
    """A chamber registration body with two concurrent load slots."""
    return _merge(
        {
            "chamber_code": f"CH-2540-{unique_suffix()}",
            "coating_type": "AR_BROADBAND",
            "slot_capacity": 2,
        },
        overrides,
    )


def build_coating_run_payload(
    work_order_id: str,
    coating_chamber_id: str,
    window_start_utc: str = "2026-08-02T08:00:00Z",
    window_end_utc: str = "2026-08-02T12:00:00Z",
    **overrides: Any,
) -> Payload:
    """A chamber booking body loading one work order for deposition."""
    return _merge(
        {
            "work_order_id": work_order_id,
            "coating_chamber_id": coating_chamber_id,
            "coating_recipe_code": "AR-VIS-01",
            "window_start_utc": window_start_utc,
            "window_end_utc": window_end_utc,
        },
        overrides,
    )


def build_spectral_samples(*pairs: Any) -> List[Dict[str, Any]]:
    """Build a spectrophotometer trace from (wavelength_nm, reflectance_pct) pairs."""
    return [
        {"wavelength_nm": int(wavelength), "reflectance_pct": float(reflectance)}
        for wavelength, reflectance in pairs
    ]


def build_spectral_verification_payload(
    spectral_samples: Optional[List[Dict[str, Any]]] = None, **overrides: Any
) -> Payload:
    """A spectral verification body carrying the spectrophotometer trace."""
    return _merge(
        {
            "spectral_samples": (
                list(PASSING_SPECTRAL_TRACE)
                if spectral_samples is None
                else spectral_samples
            )
        },
        overrides,
    )


# ----------------------------------------------------------------------
# Assemblies, components and the alignment chain
# ----------------------------------------------------------------------
def build_assembly_payload(design_id: str, **overrides: Any) -> Payload:
    """An assembly build-record body against the design it realises."""
    return _merge(
        {
            "design_id": design_id,
            "assembly_code": f"AS-2540-{unique_suffix()}",
        },
        overrides,
    )


def build_assembly_component_payload(
    assembly_id: str,
    work_order_id: str,
    expected_assembly_version: int,
    slot_index: int = 1,
    element_wavefront_rms_waves: float = 0.0600,
    decenter_um: float = 10.0,
    tilt_arcmin: float = 1.0,
    **overrides: Any,
) -> Payload:
    """A kitting body carrying the element's as-built metrology."""
    return _merge(
        {
            "assembly_id": assembly_id,
            "work_order_id": work_order_id,
            "slot_index": slot_index,
            "decenter_um": decenter_um,
            "tilt_arcmin": tilt_arcmin,
            "element_wavefront_rms_waves": element_wavefront_rms_waves,
            "expected_assembly_version": expected_assembly_version,
        },
        overrides,
    )


def build_cement_payload(**overrides: Any) -> Payload:
    """A cementing body naming the optical cement lot used."""
    return _merge({"cement_lot_code": "CEM-A-114"}, overrides)


def build_mount_payload(**overrides: Any) -> Payload:
    """A mounting body naming the barrel or mount part number."""
    return _merge({"mount_code": "MNT-77"}, overrides)


# ----------------------------------------------------------------------
# Inspection records
# ----------------------------------------------------------------------
def build_inspection_record_payload(
    assembly_id: str,
    max_scratch_number: int = 5,
    max_dig_number: int = 3,
    particle_count_per_cm2: int = 20,
    **overrides: Any,
) -> Payload:
    """A cleanroom inspection body well inside every cosmetic limit."""
    return _merge(
        {
            "assembly_id": assembly_id,
            "max_scratch_number": max_scratch_number,
            "max_dig_number": max_dig_number,
            "particle_count_per_cm2": particle_count_per_cm2,
        },
        overrides,
    )


def build_waiver_payload(**overrides: Any) -> Payload:
    """A waiver body whose justification clears the minimum length."""
    return _merge(
        {
            "justification": (
                "Cosmetic dig outside the clear aperture, cleared by "
                "optical engineering review."
            )
        },
        overrides,
    )


# ----------------------------------------------------------------------
# Export classification
# ----------------------------------------------------------------------
def build_export_classification_payload(
    design_id: str, destination_country: str = "DE", **overrides: Any
) -> Payload:
    """An export classification body for one design and one destination."""
    return _merge(
        {
            "design_id": design_id,
            "destination_country": destination_country,
        },
        overrides,
    )


def build_license_decision_payload(
    decision: str = "APPROVED", **overrides: Any
) -> Payload:
    """A licensing authority decision body."""
    payload: Payload = {"decision": decision}
    if decision == "APPROVED":
        payload["license_number"] = "BIS-2540-001"
    return _merge(payload, overrides)


def build_revocation_payload(**overrides: Any) -> Payload:
    """A revocation body naming the mandatory reason."""
    return _merge({"revocation_reason": "END_USE_STATEMENT_FALSIFIED"}, overrides)


# ----------------------------------------------------------------------
# Documentation package
# ----------------------------------------------------------------------
def build_documentation_package_payload(assembly_id: str, **overrides: Any) -> Payload:
    """A delivery documentation package body for one assembly."""
    return _merge({"assembly_id": assembly_id}, overrides)


def build_document_payload(document_type: str, **overrides: Any) -> Payload:
    """A document attachment body naming the type and the reference."""
    return _merge(
        {
            "document_type": document_type,
            "document_reference": f"DOC-{document_type}-{unique_suffix()}",
        },
        overrides,
    )


def build_review_payload(decision: str = "APPROVED", **overrides: Any) -> Payload:
    """A documentation review body carrying the reviewer's decision."""
    return _merge({"decision": decision, "review_note": "Reviewed."}, overrides)
