"""Domain assertion helpers for the precision optics manufacturing API.

These wrap the repeated shapes of the PRD's numeric and ledger rules so that a
test reads as the rule it is checking. Numeric comparisons use the decimal
scale the PRD pins for the field concerned.
"""

import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional, Sequence

import pytest

from .constants import (
    CEMENT_DERATE_HIGH_THRESHOLD,
    CEMENT_DERATE_HIGH_WAVES,
    CEMENT_DERATE_LOW_WAVES,
    CEMENT_DERATE_MID_THRESHOLD,
    CEMENT_DERATE_MID_WAVES,
    DECENTER_SENSITIVITY_WAVES_PER_UM,
    TILT_SENSITIVITY_WAVES_PER_ARCMIN,
    TOL_TWO_DP,
    TOL_UNCERTAINTY,
    TOL_WAVEFRONT,
)


# ----------------------------------------------------------------------
# Rounding, mirroring the PRD's "round half up, halves away from zero"
# ----------------------------------------------------------------------
def round_half_up(value: float, decimals: int) -> float:
    """Round on the exact decimal value with halves carried away from zero."""
    quantum = Decimal(1).scaleb(-decimals)
    return float(Decimal(repr(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def assert_wavefront_value(actual: Any, expected: float, label: str) -> None:
    """Assert a four-decimal wavefront figure."""
    assert actual is not None, f"{label} must not be null, expected {expected}"
    assert actual == pytest.approx(expected, abs=TOL_WAVEFRONT), (
        f"{label} must be {expected:.4f} waves, got {actual}"
    )


def assert_uncertainty_value(actual: Any, expected: float, label: str) -> None:
    """Assert a six-decimal instrument uncertainty figure."""
    assert actual is not None, f"{label} must not be null, expected {expected}"
    assert actual == pytest.approx(expected, abs=TOL_UNCERTAINTY), (
        f"{label} must be {expected:.6f} waves, got {actual}"
    )


def assert_two_dp_value(actual: Any, expected: float, label: str) -> None:
    """Assert a two-decimal figure such as a figure of merit or completeness."""
    assert actual is not None, f"{label} must not be null, expected {expected}"
    assert actual == pytest.approx(expected, abs=TOL_TWO_DP), (
        f"{label} must be {expected:.2f}, got {actual}"
    )


# ----------------------------------------------------------------------
# Glass lot ledger
# ----------------------------------------------------------------------
def assert_blank_ledger(
    lot: Dict[str, Any],
    reserved: int,
    consumed: int,
    scrapped: int,
    available: int,
    total: Optional[int] = None,
) -> None:
    """Assert all four blank counters and the conservation invariant."""
    assert lot["reserved_blank_count"] == reserved, (
        f"reserved_blank_count must be {reserved}, got {lot['reserved_blank_count']}"
    )
    assert lot["consumed_blank_count"] == consumed, (
        f"consumed_blank_count must be {consumed}, got {lot['consumed_blank_count']}"
    )
    assert lot["scrapped_blank_count"] == scrapped, (
        f"scrapped_blank_count must be {scrapped}, got {lot['scrapped_blank_count']}"
    )
    assert lot["available_blank_count"] == available, (
        f"available_blank_count must be {available}, got {lot['available_blank_count']}"
    )
    if total is not None:
        assert lot["total_blank_count"] == total, (
            f"total_blank_count must be {total}, got {lot['total_blank_count']}"
        )
    assert_blank_conservation(lot)


def assert_blank_conservation(lot: Dict[str, Any]) -> None:
    """total_blank_count equals available plus reserved plus consumed plus scrapped."""
    parts = (
        lot["available_blank_count"]
        + lot["reserved_blank_count"]
        + lot["consumed_blank_count"]
        + lot["scrapped_blank_count"]
    )
    assert lot["total_blank_count"] == parts, (
        "total_blank_count must equal available plus reserved plus consumed plus "
        f"scrapped, got {lot['total_blank_count']} against {parts}"
    )


def expected_spare_blank_count(element_count: int) -> int:
    """The larger of one blank and a quarter of element_count rounded up."""
    return max(1, math.ceil(element_count / 4))


def expected_reserved_blank_count(element_count: int) -> int:
    """element_count plus the spare term."""
    return element_count + expected_spare_blank_count(element_count)


# ----------------------------------------------------------------------
# Work order dimensions and removal ledger
# ----------------------------------------------------------------------
def assert_work_order_dimensions(
    work_order: Dict[str, Any], process_status: str, compliance_status: str
) -> None:
    """Assert both independent state dimensions of a work order at once."""
    assert work_order["process_status"] == process_status, (
        f"process_status must be {process_status}, got {work_order['process_status']}"
    )
    assert work_order["compliance_status"] == compliance_status, (
        "compliance_status must be "
        f"{compliance_status}, got {work_order['compliance_status']}"
    )


def assert_removal_ledger(
    work_order: Dict[str, Any],
    cumulative_removal_nm: float,
    remaining_center_thickness_um: float,
    figuring_iteration_count: int,
) -> None:
    """Assert the exact cumulative removal and the derived remaining thickness."""
    assert work_order["cumulative_removal_nm"] == pytest.approx(
        cumulative_removal_nm, abs=1e-6
    ), (
        f"cumulative_removal_nm must be {cumulative_removal_nm}, "
        f"got {work_order['cumulative_removal_nm']}"
    )
    assert_wavefront_value(
        work_order["remaining_center_thickness_um"],
        remaining_center_thickness_um,
        "remaining_center_thickness_um",
    )
    assert work_order["figuring_iteration_count"] == figuring_iteration_count, (
        f"figuring_iteration_count must be {figuring_iteration_count}, "
        f"got {work_order['figuring_iteration_count']}"
    )


# ----------------------------------------------------------------------
# Tolerance stack
# ----------------------------------------------------------------------
def assert_tolerance_stack(
    design: Dict[str, Any],
    rss_stack_waves: float,
    worst_case_stack_waves: float,
    governing_stack_waves: float,
    tolerance_verdict: str,
) -> None:
    """Assert both stack variants, the governing figure and the verdict."""
    assert_wavefront_value(design["rss_stack_waves"], rss_stack_waves, "rss_stack_waves")
    assert_wavefront_value(
        design["worst_case_stack_waves"],
        worst_case_stack_waves,
        "worst_case_stack_waves",
    )
    assert_wavefront_value(
        design["governing_stack_waves"], governing_stack_waves, "governing_stack_waves"
    )
    assert_wavefront_value(
        design["allocated_tolerance_waves"],
        governing_stack_waves,
        "allocated_tolerance_waves",
    )
    assert design["tolerance_verdict"] == tolerance_verdict, (
        f"tolerance_verdict must be {tolerance_verdict}, "
        f"got {design['tolerance_verdict']}"
    )


def assert_stack_outputs_null(design: Dict[str, Any]) -> None:
    """All four computed stack outputs are null before any analysis has run."""
    for field in (
        "rss_stack_waves",
        "worst_case_stack_waves",
        "governing_stack_waves",
        "allocated_tolerance_waves",
    ):
        assert design[field] is None, f"{field} must be null, got {design[field]}"


# ----------------------------------------------------------------------
# Instrument capability and booking
# ----------------------------------------------------------------------
def assert_instrument_drift(
    instrument: Dict[str, Any],
    days_since_calibration: int,
    effective_uncertainty_waves: float,
    instrument_status: str,
) -> None:
    """Assert the three clock-derived station properties."""
    assert instrument["days_since_calibration"] == days_since_calibration, (
        f"days_since_calibration must be {days_since_calibration}, "
        f"got {instrument['days_since_calibration']}"
    )
    assert_uncertainty_value(
        instrument["effective_uncertainty_waves"],
        effective_uncertainty_waves,
        "effective_uncertainty_waves",
    )
    assert instrument["instrument_status"] == instrument_status, (
        f"instrument_status must be {instrument_status}, "
        f"got {instrument['instrument_status']}"
    )


def assert_booked_minutes(instrument: Dict[str, Any], booked_minutes_total: int) -> None:
    """Assert the station's capacity meter."""
    assert instrument["booked_minutes_total"] == booked_minutes_total, (
        f"booked_minutes_total must be {booked_minutes_total}, "
        f"got {instrument['booked_minutes_total']}"
    )


def expected_capability_ratio(
    effective_uncertainty_waves: float, tolerance_budget_waves: float
) -> float:
    """Four times the effective uncertainty divided by the tolerance budget."""
    return round_half_up(
        4.0 * effective_uncertainty_waves / tolerance_budget_waves, 4
    )


# ----------------------------------------------------------------------
# Spectral verification
# ----------------------------------------------------------------------
def assert_spectral_outputs(
    coating_run: Dict[str, Any],
    in_band_sample_count: int,
    band_average_reflectance_pct: float,
    worst_point_reflectance_pct: float,
    spectral_verdict: str,
) -> None:
    """Assert the in-band count, both aggregates and the conjoined verdict."""
    assert coating_run["in_band_sample_count"] == in_band_sample_count, (
        f"in_band_sample_count must be {in_band_sample_count}, "
        f"got {coating_run['in_band_sample_count']}"
    )
    assert_wavefront_value(
        coating_run["band_average_reflectance_pct"],
        band_average_reflectance_pct,
        "band_average_reflectance_pct",
    )
    assert_wavefront_value(
        coating_run["worst_point_reflectance_pct"],
        worst_point_reflectance_pct,
        "worst_point_reflectance_pct",
    )
    assert coating_run["spectral_verdict"] == spectral_verdict, (
        f"spectral_verdict must be {spectral_verdict}, "
        f"got {coating_run['spectral_verdict']}"
    )


def assert_spectral_outputs_cleared(coating_run: Dict[str, Any]) -> None:
    """Assert the reset spectral outputs of a freshly loaded coating run."""
    assert coating_run["spectral_samples"] == [], (
        f"spectral_samples must be an empty array, got {coating_run['spectral_samples']}"
    )
    assert coating_run["in_band_sample_count"] == 0, (
        "in_band_sample_count must be zero, got "
        f"{coating_run['in_band_sample_count']}"
    )
    assert coating_run["band_average_reflectance_pct"] is None, (
        "band_average_reflectance_pct must be null, got "
        f"{coating_run['band_average_reflectance_pct']}"
    )
    assert coating_run["worst_point_reflectance_pct"] is None, (
        "worst_point_reflectance_pct must be null, got "
        f"{coating_run['worst_point_reflectance_pct']}"
    )
    assert coating_run["spectral_verdict"] == "PENDING", (
        f"spectral_verdict must be PENDING, got {coating_run['spectral_verdict']}"
    )


# ----------------------------------------------------------------------
# Assembly wavefront roll-up
# ----------------------------------------------------------------------
def assert_wavefront_rollup(
    assembly: Dict[str, Any],
    element_rss_waves: float,
    centration_error_waves: float,
    subtotal_waves: float,
    cement_derate_waves: float,
    total_transmitted_wavefront_waves: float,
) -> None:
    """Assert all five pinned roll-up outputs of an assembly."""
    assert_wavefront_value(
        assembly["element_rss_waves"], element_rss_waves, "element_rss_waves"
    )
    assert_wavefront_value(
        assembly["centration_error_waves"],
        centration_error_waves,
        "centration_error_waves",
    )
    assert_wavefront_value(assembly["subtotal_waves"], subtotal_waves, "subtotal_waves")
    assert_wavefront_value(
        assembly["cement_derate_waves"], cement_derate_waves, "cement_derate_waves"
    )
    assert_wavefront_value(
        assembly["total_transmitted_wavefront_waves"],
        total_transmitted_wavefront_waves,
        "total_transmitted_wavefront_waves",
    )


def assert_wavefront_rollup_null(assembly: Dict[str, Any]) -> None:
    """All five roll-up outputs are null before the first alignment pass."""
    for field in (
        "element_rss_waves",
        "centration_error_waves",
        "subtotal_waves",
        "cement_derate_waves",
        "total_transmitted_wavefront_waves",
    ):
        assert assembly[field] is None, f"{field} must be null, got {assembly[field]}"


def expected_cement_derate(subtotal_waves: float) -> float:
    """The tier selected from the subtotal, never from the final total."""
    if subtotal_waves < CEMENT_DERATE_MID_THRESHOLD:
        return CEMENT_DERATE_LOW_WAVES
    if subtotal_waves < CEMENT_DERATE_HIGH_THRESHOLD:
        return CEMENT_DERATE_MID_WAVES
    return CEMENT_DERATE_HIGH_WAVES


def expected_rollup(components: Sequence[Dict[str, float]]) -> Dict[str, float]:
    """Compute the four pinned roll-up steps over a set of active components."""
    element_rss = round_half_up(
        math.sqrt(
            sum(float(c["element_wavefront_rms_waves"]) ** 2 for c in components)
        ),
        4,
    )
    centration_sum = 0.0
    for component in components:
        decenter_term = (
            float(component["decenter_um"]) * DECENTER_SENSITIVITY_WAVES_PER_UM
        )
        tilt_term = (
            float(component["tilt_arcmin"]) * TILT_SENSITIVITY_WAVES_PER_ARCMIN
        )
        centration_sum += decenter_term**2 + tilt_term**2
    centration = round_half_up(math.sqrt(centration_sum), 4)
    subtotal = round_half_up(element_rss + centration, 4)
    derate = expected_cement_derate(subtotal)
    total = round_half_up(subtotal + derate, 4)
    return {
        "element_rss_waves": element_rss,
        "centration_error_waves": centration,
        "subtotal_waves": subtotal,
        "cement_derate_waves": derate,
        "total_transmitted_wavefront_waves": total,
    }


# ----------------------------------------------------------------------
# Release readiness projection
# ----------------------------------------------------------------------
def assert_readiness_gates(
    readiness: Dict[str, Any],
    inspection_ok: bool,
    export_ok: bool,
    documentation_ok: bool,
    wavefront_ok: bool,
    blocking_error_id: Optional[str],
) -> None:
    """Assert the four separately reported gate booleans and the blocking code."""
    assert readiness["inspection_ok"] is inspection_ok, (
        f"inspection_ok must be {inspection_ok}, got {readiness['inspection_ok']}"
    )
    assert readiness["export_ok"] is export_ok, (
        f"export_ok must be {export_ok}, got {readiness['export_ok']}"
    )
    assert readiness["documentation_ok"] is documentation_ok, (
        f"documentation_ok must be {documentation_ok}, "
        f"got {readiness['documentation_ok']}"
    )
    assert readiness["wavefront_ok"] is wavefront_ok, (
        f"wavefront_ok must be {wavefront_ok}, got {readiness['wavefront_ok']}"
    )
    assert readiness["blocking_error_id"] == blocking_error_id, (
        f"blocking_error_id must be {blocking_error_id}, "
        f"got {readiness['blocking_error_id']}"
    )


# ----------------------------------------------------------------------
# Documentation package completeness
# ----------------------------------------------------------------------
def assert_package_documents(
    package: Dict[str, Any],
    required_document_types: Sequence[str],
    present_document_types: Sequence[str],
    missing_document_types: Sequence[str],
    completeness_pct: float,
) -> None:
    """Assert the derived required set, both projections and the completeness."""
    assert list(package["required_document_types"]) == list(required_document_types), (
        f"required_document_types must be {list(required_document_types)}, "
        f"got {package['required_document_types']}"
    )
    assert list(package["present_document_types"]) == list(present_document_types), (
        f"present_document_types must be {list(present_document_types)}, "
        f"got {package['present_document_types']}"
    )
    assert list(package["missing_document_types"]) == list(missing_document_types), (
        f"missing_document_types must be {list(missing_document_types)}, "
        f"got {package['missing_document_types']}"
    )
    assert_two_dp_value(package["completeness_pct"], completeness_pct, "completeness_pct")


# ----------------------------------------------------------------------
# Ordering and listing helpers
# ----------------------------------------------------------------------
def ids_of(rows: Sequence[Dict[str, Any]]) -> List[str]:
    """Extract the ``id`` of every row in a listing, in the order returned."""
    return [row["id"] for row in rows]


def assert_row_ids(
    rows: Sequence[Dict[str, Any]], expected_ids: Sequence[str], label: str
) -> None:
    """Assert a listing returns exactly these ids in exactly this order."""
    assert ids_of(rows) == list(expected_ids), (
        f"{label} must return {list(expected_ids)} in that order, got {ids_of(rows)}"
    )


def assert_created_at_ascending(rows: Sequence[Dict[str, Any]], label: str) -> None:
    """Assert a listing is ordered by created_at ascending."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), (
        f"{label} must be ordered by created_at ascending, got {stamps}"
    )


def assert_version(entity: Dict[str, Any], version: int, label: str) -> None:
    """Assert an entity's optimistic-concurrency version counter."""
    assert entity["version"] == version, (
        f"{label} version must be {version}, got {entity['version']}"
    )


def assert_null_fields(entity: Dict[str, Any], *field_names: str) -> None:
    """Assert every named field is null."""
    for field in field_names:
        assert entity[field] is None, f"{field} must be null, got {entity[field]}"


def error_id_of(response: Any) -> Optional[str]:
    """The ``error_id`` an error envelope carries, or None for a success body."""
    body = response.json()
    data = body.get("data") or {}
    if isinstance(data, dict):
        return data.get("error_id")
    return None
