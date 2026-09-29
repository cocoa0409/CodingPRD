"""Valid-by-default request payload builders.

Each builder returns a payload that satisfies every schema rule in the PRD, so a
test only names the field it wants to bend. Keyword overrides are merged last;
passing ``None`` explicitly keeps the key with a null value, while
``omit=("field",)`` removes a key entirely so the server-side default applies.
"""

from typing import Any, Dict, Iterable, List, Optional


def _merge(base: Dict[str, Any], omit: Optional[Iterable[str]], overrides: Dict[str, Any]):
    payload = dict(base)
    for key in omit or ():
        payload.pop(key, None)
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Catalogs
# ---------------------------------------------------------------------------


def material_spec_payload(
    omit: Optional[Iterable[str]] = None, **overrides: Any
) -> Dict[str, Any]:
    """Stainless 316L: AWWA/NSF61/ASME-U capable, rated to 300 psig, cost_index 1.10."""
    return _merge(
        {
            "code": "MAT-316L",
            "max_chloride_ppm": 200.0,
            "max_temp_c": 80.0,
            "max_pressure_psig": 300,
            "ph_min": 4.0,
            "ph_max": 11.0,
            "asme_u_capable": True,
            "nsf61_certified": True,
            "awwa_compliant": True,
            "cost_index": 1.10,
            "service_classes_allowed": ["NEUTRAL", "CHLORINATED", "CAUSTIC"],
        },
        omit,
        overrides,
    )


def pvc_material_spec_payload(
    omit: Optional[Iterable[str]] = None, **overrides: Any
) -> Dict[str, Any]:
    """Unplasticised PVC: only 150 psig and not AWWA compliant."""
    return _merge(
        {
            "code": "MAT-PVC-U",
            "max_chloride_ppm": 30000.0,
            "max_temp_c": 55.0,
            "max_pressure_psig": 150,
            "ph_min": 2.0,
            "ph_max": 12.0,
            "asme_u_capable": False,
            "nsf61_certified": True,
            "awwa_compliant": False,
            "cost_index": 1.00,
            "service_classes_allowed": ["NEUTRAL", "CHLORINATED", "ACIDIC"],
        },
        omit,
        overrides,
    )


def filtration_technology_payload(
    omit: Optional[Iterable[str]] = None, **overrides: Any
) -> Dict[str, Any]:
    """Submerged microfiltration rack, AWWA stamped, 900 sf per mgd."""
    return _merge(
        {
            "code": "TECH-FILT-A",
            "name": "Submerged MF membrane rack",
            "role": "FILTRATION",
            "max_feed_turbidity_ntu": 50.0,
            "max_feed_tds_mg_l": 3000.0,
            "min_design_flow_mgd": 0.500,
            "max_design_flow_mgd": 20.000,
            "unit_capex_cents_per_mgd": 40000000,
            "energy_kwh_per_mg": 250.0,
            "footprint_sf_per_mgd": 900.0,
            "requires_code_stamp": "AWWA",
            "chemical_service_class": "NEUTRAL",
            "consumable_item_code": "MF-ELEM-8",
            "status": "ACTIVE",
        },
        omit,
        overrides,
    )


def disinfection_technology_payload(
    omit: Optional[Iterable[str]] = None, **overrides: Any
) -> Dict[str, Any]:
    """Closed-vessel UV reactor train, no code stamp, 200 sf per mgd."""
    return _merge(
        {
            "code": "TECH-DIS-A",
            "name": "Closed-vessel UV reactor train",
            "role": "DISINFECTION",
            "max_feed_turbidity_ntu": 50.0,
            "max_feed_tds_mg_l": 3000.0,
            "min_design_flow_mgd": 0.500,
            "max_design_flow_mgd": 20.000,
            "unit_capex_cents_per_mgd": 12000000,
            "energy_kwh_per_mg": 90.0,
            "footprint_sf_per_mgd": 200.0,
            "requires_code_stamp": "NONE",
            "chemical_service_class": "CHLORINATED",
            "consumable_item_code": "UV-LAMP-40",
            "status": "ACTIVE",
        },
        omit,
        overrides,
    )


def test_bay_payload(
    omit: Optional[Iterable[str]] = None, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "bay_code": "BAY-1",
            "max_skid_footprint_sf": 6000.0,
            "changeover_buffer_minutes": 120,
            "crane_capacity_tons": 40.0,
            "status": "AVAILABLE",
        },
        omit,
        overrides,
    )


# ---------------------------------------------------------------------------
# Projects and scoping
# ---------------------------------------------------------------------------


def project_payload(
    omit: Optional[Iterable[str]] = None, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "name": "Northgate WTP Membrane Upgrade",
            "owner_agency_name": "City of Northgate",
            "procurement_type": "MUNICIPAL_BID",
            "bid_due_at": "2026-09-15T00:00:00.000Z",
            "guarantee_deadline_at": "2027-06-30T00:00:00.000Z",
            "footprint_allowance_sf_per_stage": 6000.0,
        },
        omit,
        overrides,
    )


def influent_profile_payload(
    omit: Optional[Iterable[str]] = None, **overrides: Any
) -> Dict[str, Any]:
    """4.000 mgd at peak factor 1.500, well inside the TECH-FILT-A envelope."""
    return _merge(
        {
            "sample_label": "RAW-2026-07",
            "design_flow_mgd": 4.000,
            "peak_factor": 1.500,
            "turbidity_ntu": 12.0,
            "tds_mg_l": 800.0,
            "toc_mg_l": 3.2,
            "chloride_mg_l": 150.0,
            "temperature_c": 22.0,
            "ph": 7.4,
        },
        omit,
        overrides,
    )


def turbidity_objective_payload(
    omit: Optional[Iterable[str]] = None, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "parameter": "TURBIDITY_NTU",
            "limit_value": 0.300,
            "basis": "MAX_DAY",
            "regulatory_driver": "40 CFR 141.73 SWTR",
        },
        omit,
        overrides,
    )


def ecoli_objective_payload(
    omit: Optional[Iterable[str]] = None, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "parameter": "ECOLI_CFU_100ML",
            "limit_value": 1.000,
            "basis": "MONTHLY_AVERAGE",
            "regulatory_driver": "40 CFR 141.63 TCR",
        },
        omit,
        overrides,
    )


# ---------------------------------------------------------------------------
# Equipment packages
# ---------------------------------------------------------------------------


def equipment_package_payload(
    material_spec_id: str, omit: Optional[Iterable[str]] = None, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "material_spec_id": material_spec_id,
            "tag_number": "F-100",
            "design_pressure_psig": 150,
            "design_temp_c": 30.0,
        },
        omit,
        overrides,
    )


# ---------------------------------------------------------------------------
# Or-Equal submittals
# ---------------------------------------------------------------------------


def or_equal_submittal_payload(
    project_id: str, omit: Optional[Iterable[str]] = None, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "project_id": project_id,
            "spec_section": "11 21 13",
            "named_basis_of_design": "Acme MF-6",
        },
        omit,
        overrides,
    )


def spec_deviation_payload(
    expected_version: int,
    severity: str = "MODERATE",
    omit: Optional[Iterable[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "spec_paragraph": "2.03.B",
            "severity": severity,
            "description": "Rack frame alloy differs from named basis",
            "expected_or_equal_submittal_version": expected_version,
        },
        omit,
        overrides,
    )


# ---------------------------------------------------------------------------
# Shop floor
# ---------------------------------------------------------------------------


def milestone_payload(
    dimension: str, to_state: str, omit: Optional[Iterable[str]] = None, **overrides: Any
) -> Dict[str, Any]:
    return _merge({"dimension": dimension, "to_state": to_state}, omit, overrides)


def fat_run_payload(
    skid_id: str,
    test_bay_id: str,
    expected_skid_version: int,
    start_at: str = "2026-08-10T08:00:00.000Z",
    end_at: str = "2026-08-10T16:00:00.000Z",
    omit: Optional[Iterable[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "skid_id": skid_id,
            "test_bay_id": test_bay_id,
            "scheduled_start_at": start_at,
            "scheduled_end_at": end_at,
            "expected_skid_version": expected_skid_version,
        },
        omit,
        overrides,
    )


# ---------------------------------------------------------------------------
# Commissioning
# ---------------------------------------------------------------------------


def performance_demo_payload(
    project_id: str,
    skid_id: str,
    readings: Optional[List[Dict[str, Any]]] = None,
    start_at: str = "2026-08-20T00:00:00.000Z",
    end_at: str = "2026-08-27T00:00:00.000Z",
    omit: Optional[Iterable[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "project_id": project_id,
            "skid_id": skid_id,
            "window_start_at": start_at,
            "window_end_at": end_at,
            "readings": readings
            if readings is not None
            else [{"parameter": "TURBIDITY_NTU", "measured_value": 0.250}],
        },
        omit,
        overrides,
    )


# ---------------------------------------------------------------------------
# Service agreements and draws
# ---------------------------------------------------------------------------


def service_agreement_payload(
    omit: Optional[Iterable[str]] = None, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "term_months": 60,
            "annual_fee_cents": 4800000,
            "reserve_funded_cents": 12200000,
            "membrane_installed_at": "2026-08-01T00:00:00.000Z",
        },
        omit,
        overrides,
    )


def consumable_draw_payload(
    expected_version: int,
    draw_type: str = "CONSUMABLE",
    quantity: int = 3,
    catalog_unit_cost_cents: int = 500000,
    invoiced_unit_cost_cents: int = 480000,
    omit: Optional[Iterable[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "draw_type": draw_type,
            "item_code": "MF-ELEM-8",
            "quantity": quantity,
            "catalog_unit_cost_cents": catalog_unit_cost_cents,
            "invoiced_unit_cost_cents": invoiced_unit_cost_cents,
            "expected_service_agreement_version": expected_version,
        },
        omit,
        overrides,
    )
