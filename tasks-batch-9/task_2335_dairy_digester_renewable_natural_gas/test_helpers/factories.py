"""Payload factories - one per entity, request-input fields only."""
from typing import Any, Dict


def create_dairy_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "name": "Vista Verde Dairy",
        "county": "Tulare",
        "herd_size": 3200,
        "manure_management_baseline": "LAGOON",
        "haul_distance_km": 12.0,
        "annual_nitrogen_budget_kg": 24000.000,
    }
    payload.update(overrides)
    return payload


def create_facility_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "name": "Tulare Digester 1",
        "digester_volume_m3": 6000.000,
        "hydraulic_capacity_tonnes_per_day": 500.000,
        "thermal_regime": "MESOPHILIC",
        "target_temperature_c": 38.0,
        "reserve_target_cents": 4_000_000,
        "annual_debt_service_cents": 18_000_000,
        "dscr_minimum": 1.250,
    }
    payload.update(overrides)
    return payload


def create_agreement_payload(dairy_id: str, facility_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "dairy_id": dairy_id,
        "facility_id": facility_id,
        "committed_tonnes_per_day": 180.000,
        "minimum_total_solids_pct": 6.50,
        "term_start_date": "2026-07-01",
        "term_end_date": "2027-06-30",
        "revenue_share_pct": 0.2200,
        "revenue_share_basis": "NET",
        "curtailable": True,
    }
    payload.update(overrides)
    return payload


def create_delivery_payload(agreement_id: str, ops_day_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "agreement_id": agreement_id,
        "ops_day_id": ops_day_id,
        "gross_tonnes": 150.000,
        "tare_tonnes": 0.000,
        "total_solids_pct": 8.0,
        "volatile_solids_pct_of_ts": 82.0,
    }
    payload.update(overrides)
    return payload


def create_ops_day_payload(facility_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "facility_id": facility_id,
        "ops_date": "2026-08-03",
    }
    payload.update(overrides)
    return payload


def close_ops_day_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "avg_digester_temp_c": 38.4,
        "temp_excursion_minutes": 15,
        "vfa_mg_per_l": 2400.0,
        "alkalinity_mg_per_l": 8000.0,
        "raw_biogas_scf": 196000.000,
        "raw_ch4_pct": 62.0,
        "raw_co2_pct": 36.5,
        "raw_h2s_ppm": 1800.0,
        "raw_moisture_lb_per_mmscf": 120.0,
    }
    payload.update(overrides)
    return payload


def condition_gas_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "disposition": "RECONDITION",
        "treated_ch4_pct": 96.5,
        "treated_co2_pct": 1.5,
        "treated_h2s_ppm": 3.5,
        "treated_moisture_lb_per_mmscf": 5.0,
    }
    payload.update(overrides)
    return payload


def record_separation_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "solids_capture_pct": 65.0,
        "bedding_recovery_pct": 70.0,
        "lab_total_nitrogen_mg_per_l": 1150.0,
    }
    payload.update(overrides)
    return payload


def create_interconnect_payload(facility_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "facility_id": facility_id,
        "pipeline_operator_name": "Central Valley Gas Transmission",
        "max_h2s_ppm": 4.0,
        "max_moisture_lb_per_mmscf": 7.0,
        "max_co2_pct": 2.0,
        "min_hhv_btu_per_scf": 967.00,
        "max_hourly_injection_mmbtu": 12.000,
        "ramp_buffer_minutes": 30,
        "nomination_lead_hours": 24,
    }
    payload.update(overrides)
    return payload


def create_nomination_payload(
    interconnect_id: str, ops_day_id: str, **overrides
) -> Dict[str, Any]:
    payload = {
        "interconnect_id": interconnect_id,
        "ops_day_id": ops_day_id,
        "window_start_utc": "2026-08-04T06:00:00Z",
        "window_end_utc": "2026-08-04T18:00:00Z",
        "nominated_mmbtu": 120.280,
    }
    payload.update(overrides)
    return payload


def create_pathway_payload(facility_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "facility_id": facility_id,
        "program": "LCFS",
        "pathway_code": "CA-LCFS-DDRNG-2026-01",
    }
    payload.update(overrides)
    return payload


def create_batch_payload(
    pathway_id: str, facility_id: str, expected_pathway_version: int, **overrides
) -> Dict[str, Any]:
    payload = {
        "pathway_id": pathway_id,
        "facility_id": facility_id,
        "period_start_date": "2026-08-01",
        "period_end_date": "2026-08-31",
        "expected_pathway_version": expected_pathway_version,
    }
    payload.update(overrides)
    return payload


def create_audit_payload(pathway_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "pathway_id": pathway_id,
        "audit_year": 2026,
        "verifier_body_name": "Sierra Carbon Verification LLC",
    }
    payload.update(overrides)
    return payload


def fieldwork_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "actual_pipeline_mmbtu": 120.280,
        "actual_vs_tonnes_lagoon": 9.840,
        "actual_vs_tonnes_solid_storage": 0.000,
        "actual_vs_tonnes_daily_spread": 0.000,
        "actual_haul_tonne_km": 1800.00,
        "actual_process_g_per_mj": 17.55,
    }
    payload.update(overrides)
    return payload


def create_nutrient_application_payload(
    dairy_id: str, facility_id: str, ops_day_id: str, **overrides
) -> Dict[str, Any]:
    payload = {
        "dairy_id": dairy_id,
        "facility_id": facility_id,
        "ops_day_id": ops_day_id,
        "land_unit_code": "LU-07",
        "application_start_date": "2026-08-10",
        "application_end_date": "2026-08-12",
        "solids_tonnes_applied": 2.000,
        "liquid_tonnes_applied": 2.000,
        "pan_basis": "LAB",
    }
    payload.update(overrides)
    return payload


def create_statement_payload(
    facility_id: str, expected_facility_version: int, **overrides
) -> Dict[str, Any]:
    payload = {
        "facility_id": facility_id,
        "period_start_date": "2026-08-01",
        "period_end_date": "2026-08-31",
        "gas_revenue_cents": 2_010_000,
        "expected_facility_version": expected_facility_version,
    }
    payload.update(overrides)
    return payload
