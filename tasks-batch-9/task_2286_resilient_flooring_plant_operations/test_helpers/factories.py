"""Payload builders.

Each factory returns a minimal-but-valid request body for one endpoint, with
`**overrides` applied last so a test can bend exactly one field. Passing
``None`` as an override value removes the key entirely, which is how tests
exercise "omitted optional" and "missing required field" paths.
"""

from typing import Any, Dict

from .constants import CLOCK_BOOT_UTC


def _apply(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(base)
    for key, value in overrides.items():
        if value is None:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# --------------------------------------------------------------------- clock
def clock_payload(current_utc: str = CLOCK_BOOT_UTC, **overrides) -> Dict[str, Any]:
    return _apply({"current_utc": current_utc}, overrides)


# -------------------------------------------------------------- distributors
def distributor_payload(**overrides) -> Dict[str, Any]:
    return _apply(
        {
            "account_code": "D-100",
            "name": "Northline Floors LLC",
            "territory_code": "US",
        },
        overrides,
    )


# ------------------------------------------------------------- raw materials
#
# The five reference materials. Their property values are what make the
# blend arithmetic of PRD 3.1 land on stable, hand-checkable figures.
RAW_MATERIAL_SPECS: Dict[str, Dict[str, Any]] = {
    "RM-RESIN": {
        "material_code": "RM-RESIN",
        "name": "Suspension PVC K67",
        "category": "VINYL_RESIN",
        "cost_per_kg_cents": 180,
        "indentation_index": 90,
        "thermal_stability_index": 85,
        "plasticizer_migration_index": 5,
        "max_phr": 100,
    },
    "RM-STAB": {
        "material_code": "RM-STAB",
        "name": "Ca-Zn Stabiliser",
        "category": "STABILIZER",
        "cost_per_kg_cents": 900,
        "indentation_index": 60,
        "thermal_stability_index": 96,
        "plasticizer_migration_index": 2,
        "max_phr": 5,
    },
    "RM-FILLER": {
        "material_code": "RM-FILLER",
        "name": "Coated Limestone F45",
        "category": "FILLER",
        "cost_per_kg_cents": 45,
        "indentation_index": 96,
        "thermal_stability_index": 92,
        "plasticizer_migration_index": 1,
        "max_phr": 400,
    },
    "RM-SOFT": {
        "material_code": "RM-SOFT",
        "name": "DOTP Plasticiser",
        "category": "PLASTICIZER",
        "cost_per_kg_cents": 300,
        "indentation_index": 20,
        "thermal_stability_index": 20,
        "plasticizer_migration_index": 80,
        "max_phr": 60,
    },
    "RM-CACO3": {
        "material_code": "RM-CACO3",
        "name": "Ground Calcium Carbonate",
        "category": "FILLER",
        "cost_per_kg_cents": 30,
        "indentation_index": 30,
        "thermal_stability_index": 88,
        "plasticizer_migration_index": 1,
        "max_phr": 400,
    },
}


def raw_material_payload(code: str = "RM-RESIN", **overrides) -> Dict[str, Any]:
    base = RAW_MATERIAL_SPECS.get(code)
    if base is None:
        base = dict(RAW_MATERIAL_SPECS["RM-FILLER"], material_code=code)
    return _apply(base, overrides)


def raw_material_status_payload(to_status: str, **overrides) -> Dict[str, Any]:
    return _apply({"to_status": to_status}, overrides)


def raw_material_cost_payload(cost_per_kg_cents: int, **overrides) -> Dict[str, Any]:
    return _apply({"cost_per_kg_cents": cost_per_kg_cents}, overrides)


# --------------------------------------------------------------- formulations
def formulation_payload(
    formulation_code: str = "F-MIN", **overrides
) -> Dict[str, Any]:
    return _apply({"formulation_code": formulation_code}, overrides)


def component_payload(raw_material_id: str, phr: float, **overrides) -> Dict[str, Any]:
    return _apply({"raw_material_id": raw_material_id, "phr": phr}, overrides)


def review_decision_payload(decision: str, **overrides) -> Dict[str, Any]:
    return _apply({"decision": decision}, overrides)


def revision_payload(
    formulation_code: str, expected_formulation_version: int, **overrides
) -> Dict[str, Any]:
    return _apply(
        {
            "formulation_code": formulation_code,
            "expected_formulation_version": expected_formulation_version,
        },
        overrides,
    )


# ------------------------------------------------------------ design licenses
def design_license_payload(**overrides) -> Dict[str, Any]:
    return _apply(
        {
            "license_code": "LIC-OAK",
            "licensor_name": "Nordic Decor Studio",
            "license_type": "NON_EXCLUSIVE",
            "royalty_rate_bps": 500,
            "valid_from": "2026-01-01T00:00:00Z",
            "valid_until": "2027-01-01T00:00:00Z",
            "term_volume_cap_sqm": 2000.00,
            "territory_codes": ["US", "CA"],
        },
        overrides,
    )


def license_amendment_payload(
    license_code: str, term_volume_cap_sqm: float, **overrides
) -> Dict[str, Any]:
    return _apply(
        {
            "license_code": license_code,
            "term_volume_cap_sqm": term_volume_cap_sqm,
        },
        overrides,
    )


def license_status_payload(to_status: str, **overrides) -> Dict[str, Any]:
    return _apply({"to_status": to_status}, overrides)


# ----------------------------------------------------------------- print films
def print_film_payload(license_id: str, **overrides) -> Dict[str, Any]:
    return _apply(
        {
            "design_code": "PF-OAK-1200",
            "license_id": license_id,
            "pattern_repeat_mm_length": 1200,
            "pattern_repeat_mm_width": 180,
            "registration_tolerance_mm": 0.25,
            "emboss_plate_code": "EP-OAK-A",
            "emboss_alignment_offset_mm": 0.10,
            "master_roll_sets": 1,
        },
        overrides,
    )


def print_film_status_payload(to_status: str, **overrides) -> Dict[str, Any]:
    return _apply({"to_status": to_status}, overrides)


# ---------------------------------------------------------------- product SKUs
def product_sku_payload(
    formulation_id: str, print_film_id: str, **overrides
) -> Dict[str, Any]:
    """A glue-down SKU: no profile family, so all four milling fields absent."""
    return _apply(
        {
            "sku_code": "SKU-A",
            "formulation_id": formulation_id,
            "print_film_id": print_film_id,
            "construction_type": "GLUE_DOWN",
            "wear_layer_mil": 12,
            "overall_thickness_mm": 2.50,
            "royalty_basis_price_cents_per_sqm": 2100,
        },
        overrides,
    )


def click_lock_sku_payload(
    formulation_id: str, print_film_id: str, **overrides
) -> Dict[str, Any]:
    """A waterproof click-lock SKU carrying the full milling field group."""
    return _apply(
        {
            "sku_code": "SKU-W",
            "formulation_id": formulation_id,
            "print_film_id": print_film_id,
            "construction_type": "CLICK_LOCK_SPC",
            "wear_layer_mil": 20,
            "overall_thickness_mm": 5.00,
            "royalty_basis_price_cents_per_sqm": 2600,
            "waterproof_rated": True,
            "attached_underlayment_type": "IXPE_1MM",
            "profile_family": "UNILIN_5G",
            "tongue_thickness_target_mm": 1.80,
            "tolerance_plus_mm": 0.15,
            "tolerance_minus_mm": 0.15,
            "target_lock_shear_n_per_mm": 8.00,
        },
        overrides,
    )


def commercial_status_payload(to_status: str, **overrides) -> Dict[str, Any]:
    return _apply({"to_status": to_status}, overrides)


# ----------------------------------------------------------------- press lines
def press_line_payload(**overrides) -> Dict[str, Any]:
    return _apply(
        {
            "line_code": "PL-1",
            "line_type": "CALENDER",
            "min_thickness_mm": 1.50,
            "max_thickness_mm": 8.00,
            "changeover_minutes": 60,
            "curl_control_index": 92,
        },
        overrides,
    )


def press_line_status_payload(to_status: str, **overrides) -> Dict[str, Any]:
    return _apply({"to_status": to_status}, overrides)


# ----------------------------------------------------------------- test panels
def test_panel_payload(sku_id: str, panel_code: str = "TP-A1", **overrides):
    return _apply({"panel_code": panel_code, "sku_id": sku_id}, overrides)


def test_result_payload(test_type: str, measured_value: float, **overrides):
    return _apply({"test_type": test_type, "measured_value": measured_value}, overrides)


def void_panel_payload(
    void_reason: str = "Specimen mis-cut, panel abandoned", **overrides
):
    return _apply({"void_reason": void_reason}, overrides)


# ------------------------------------------------------------- production runs
def production_run_payload(
    sku_id: str,
    press_line_id: str,
    run_code: str = "RUN-A1",
    planned_start_utc: str = "2026-08-01T01:00:00Z",
    planned_end_utc: str = "2026-08-01T09:00:00Z",
    planned_quantity_sqm: float = 1200.00,
    **overrides,
) -> Dict[str, Any]:
    return _apply(
        {
            "run_code": run_code,
            "sku_id": sku_id,
            "press_line_id": press_line_id,
            "planned_start_utc": planned_start_utc,
            "planned_end_utc": planned_end_utc,
            "planned_quantity_sqm": planned_quantity_sqm,
        },
        overrides,
    )


def run_completion_payload(
    actual_quantity_sqm: float = 1200.00, **overrides
) -> Dict[str, Any]:
    """Shop-floor measurements that make all four QC gates hold on PL-1."""
    return _apply(
        {
            "actual_quantity_sqm": actual_quantity_sqm,
            "registration_drift_mm": 0.20,
            "curl_deviation_mm": 0.10,
            "emboss_alignment_offset_mm": 0.10,
            "wear_layer_measured_mil": 12.0,
        },
        overrides,
    )


def run_abort_payload(
    abort_reason: str = "planner changed their mind after the fact", **overrides
):
    return _apply({"abort_reason": abort_reason}, overrides)


def qc_disposition_payload(to_disposition: str, **overrides) -> Dict[str, Any]:
    return _apply({"to_disposition": to_disposition}, overrides)


# ---------------------------------------------------------------------- stock
def hold_status_payload(action: str, **overrides) -> Dict[str, Any]:
    return _apply({"action": action}, overrides)


# ------------------------------------------------------------------ allocations
def allocation_payload(
    distributor_id: str,
    sku_id: str,
    allocation_code: str = "ALLOC-1",
    requested_quantity_sqm: float = 100.00,
    **overrides,
) -> Dict[str, Any]:
    return _apply(
        {
            "allocation_code": allocation_code,
            "distributor_id": distributor_id,
            "sku_id": sku_id,
            "requested_quantity_sqm": requested_quantity_sqm,
        },
        overrides,
    )


def fill_payload(expected_allocation_version: int, **overrides) -> Dict[str, Any]:
    return _apply(
        {"expected_allocation_version": expected_allocation_version}, overrides
    )


# -------------------------------------------------------------- warranty claims
def warranty_claim_payload(
    batch_id: str,
    distributor_id: str,
    claim_code: str = "WC-1",
    claim_type: str = "LOCK_FAILURE",
    claimed_area_sqm: float = 25.50,
    installed_on: str = "2026-08-05T00:00:00Z",
    reported_on: str = "2029-08-05T00:00:00Z",
    **overrides,
) -> Dict[str, Any]:
    return _apply(
        {
            "claim_code": claim_code,
            "batch_id": batch_id,
            "distributor_id": distributor_id,
            "claim_type": claim_type,
            "claimed_area_sqm": claimed_area_sqm,
            "installed_on": installed_on,
            "reported_on": reported_on,
        },
        overrides,
    )


def claim_review_payload(review_kind: str, outcome: str, **overrides):
    return _apply({"review_kind": review_kind, "outcome": outcome}, overrides)


def adjudication_payload(decision: str, **overrides) -> Dict[str, Any]:
    return _apply({"decision": decision}, overrides)
