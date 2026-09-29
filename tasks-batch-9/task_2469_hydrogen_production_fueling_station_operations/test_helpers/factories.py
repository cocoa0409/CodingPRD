"""Payload factories — one per entity, request-input fields only."""

from typing import Any, Dict

from .constants import TEST_DEFAULTS

_counter = {"n": 0}


def unique_suffix() -> str:
    """Monotonic suffix so code-uniqueness rules are not tripped by accident."""
    _counter["n"] += 1
    return f"{_counter['n']:04d}"


# ─── Funding agreement ────────────────────────────────────────────────────


def funding_agreement_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "agreement_code": f"FA-{unique_suffix()}",
        "funder_name": "State Hydrogen Authority",
        "min_uptime_pct": TEST_DEFAULTS["MIN_UPTIME_PCT"],
        "penalty_per_point_cents": TEST_DEFAULTS["PENALTY_PER_POINT_CENTS"],
        "initial_holdback_cents": TEST_DEFAULTS["INITIAL_HOLDBACK_CENTS"],
        "uptime_method": "NOZZLE_WEIGHTED",
    }
    defaults.update(overrides)
    return defaults


# ─── Station ──────────────────────────────────────────────────────────────


def station_payload(funding_agreement_id: str, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "funding_agreement_id": funding_agreement_id,
        "code": f"ST-{unique_suffix()}",
        "name": "Harbour Road Hydrogen Station",
        "nozzle_count": TEST_DEFAULTS["NOZZLE_COUNT"],
        "offload_bay_count": TEST_DEFAULTS["OFFLOAD_BAY_COUNT"],
        "storage_capacity_kg": TEST_DEFAULTS["STORAGE_CAPACITY_KG"],
        "reserve_floor_kg": TEST_DEFAULTS["RESERVE_FLOOR_KG"],
        "max_pressure_class": "H70",
    }
    defaults.update(overrides)
    return defaults


# ─── Pressure vessel ──────────────────────────────────────────────────────


def pressure_vessel_payload(station_id: str, **overrides: Any) -> Dict[str, Any]:
    """The station is addressed by path, so it is not repeated in the body."""
    defaults: Dict[str, Any] = {
        "bank_tier": "HIGH",
        "water_volume_l": 600.000,
        "mawp_bar": 1000.00,
        "min_residual_bar": 200.00,
        "initial_pressure_bar": 950.00,
        "next_inspection_due_date": "2027-01-01",
    }
    defaults.update(overrides)
    return defaults


def pass_inspection_payload(next_due_date: str, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"outcome": "PASS", "next_due_date": next_due_date}
    defaults.update(overrides)
    return defaults


def condemn_inspection_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"outcome": "CONDEMN"}
    defaults.update(overrides)
    return defaults


# ─── Responder certification ──────────────────────────────────────────────


def responder_certification_payload(station_id: str, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "responder_ref": f"RESP-{unique_suffix()}",
        "cert_type": "EMERGENCY_RESPONSE",
        "valid_from": "2026-01-01",
        "expires_on": "2027-01-01",
    }
    defaults.update(overrides)
    return defaults


# ─── Production asset ─────────────────────────────────────────────────────


def production_asset_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "asset_code": f"PA-{unique_suffix()}",
        "pathway": "PEM_ELECTROLYSIS",
        "nameplate_kg_per_day": 1000.000,
        "operator_org": "Delta Hydrogen Works",
    }
    defaults.update(overrides)
    return defaults


# ─── Power supply contract ────────────────────────────────────────────────


def power_supply_contract_payload(production_asset_id: str, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "production_asset_id": production_asset_id,
        "contract_code": f"PSC-{unique_suffix()}",
        "grid_ci_gco2e_per_mwh": 400.00,
        "annual_renewable_pct": 50.000,
        "hourly_matched_renewable_pct": 20.000,
        "hourly_matching_enabled": False,
        "effective_from": "2026-01-01T00:00:00Z",
        "effective_to": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


# ─── Production lot ───────────────────────────────────────────────────────


def production_lot_payload(production_asset_id: str, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "production_asset_id": production_asset_id,
        "lot_code": f"LOT-{unique_suffix()}",
        "mass_kg": 1000.000,
        "energy_consumed_kwh": 50000.000,
        "production_start_at": "2026-07-01T00:00:00Z",
        "production_end_at": "2026-07-02T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


# ─── Purity test ──────────────────────────────────────────────────────────


def purity_test_payload(production_lot_id: str, **overrides: Any) -> Dict[str, Any]:
    """A comfortably passing sample: every analyte at half its limit."""
    defaults: Dict[str, Any] = {
        "sampled_at": "2026-07-02T00:00:00Z",
        "total_hydrocarbons_ppm": 1.000,
        "water_ppm": 2.500,
        "oxygen_ppm": 2.500,
        "nitrogen_ppm": 50.000,
        "carbon_monoxide_ppm": 0.100,
        "carbon_dioxide_ppm": 1.000,
        "total_sulfur_ppm": 0.002,
        "ammonia_ppm": 0.050,
        "helium_ppm": 150.000,
    }
    defaults.update(overrides)
    return defaults


# ─── Delivery ─────────────────────────────────────────────────────────────


def tube_trailer_delivery_payload(
    station_id: str, production_lot_id: str, receiving_vessel_id: str, **overrides: Any
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "station_id": station_id,
        "production_lot_id": production_lot_id,
        "receiving_vessel_id": receiving_vessel_id,
        "mode": "TUBE_TRAILER",
        "planned_kg": 300.000,
        "window_start": "2026-08-02T00:00:00Z",
        "window_end": "2026-08-02T06:00:00Z",
        "trailer_water_volume_l": 2500.000,
        "trailer_final_pressure_bar": 210.00,
        "departed_at": "2026-08-01T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def liquid_tanker_delivery_payload(
    station_id: str, production_lot_id: str, receiving_vessel_id: str, **overrides: Any
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "station_id": station_id,
        "production_lot_id": production_lot_id,
        "receiving_vessel_id": receiving_vessel_id,
        "mode": "LIQUID_TANKER",
        "planned_kg": 200.000,
        "window_start": "2026-08-02T00:00:00Z",
        "window_end": "2026-08-02T06:00:00Z",
        "departed_at": "2026-08-01T08:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def delivery_reject_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"reject_reason": "DOCUMENTATION"}
    defaults.update(overrides)
    return defaults


def delivery_reschedule_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "window_start": "2026-08-03T00:00:00Z",
        "window_end": "2026-08-03T06:00:00Z",
    }
    defaults.update(overrides)
    return defaults


# ─── Dispense session ─────────────────────────────────────────────────────


def dispense_session_payload(
    station_id: str, expected_station_version: int, **overrides: Any
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "station_id": station_id,
        "vehicle_class": "LIGHT_DUTY",
        "target_pressure_class": "H70",
        "fill_protocol": "SAE_J2601_TABLE",
        "planned_kg": 5.000,
        "ambient_temp_c": 10.0,
        "expected_station_version": expected_station_version,
    }
    defaults.update(overrides)
    return defaults


def fuel_payload(precool_temp_achieved_c: float, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"precool_temp_achieved_c": precool_temp_achieved_c}
    defaults.update(overrides)
    return defaults


def complete_fill_payload(
    metered_kg: float,
    avg_dispense_pressure_bar: float = 700.00,
    final_pressure_bar: float = 700.00,
    **overrides: Any,
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "metered_kg": metered_kg,
        "avg_dispense_pressure_bar": avg_dispense_pressure_bar,
        "final_pressure_bar": final_pressure_bar,
    }
    defaults.update(overrides)
    return defaults


def void_meter_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"void_reason": "BILLING_DISPUTE"}
    defaults.update(overrides)
    return defaults


# ─── Safety event ─────────────────────────────────────────────────────────


def safety_event_payload(station_id: str, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "station_id": station_id,
        "kind": "OVERPRESSURE",
        "severity": "MAJOR",
        "affected_nozzle_count": 1,
        "detected_by": "SENSOR",
    }
    defaults.update(overrides)
    return defaults


def clear_safety_event_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"corrective_action": "Fitting replaced and re-tested."}
    defaults.update(overrides)
    return defaults


# ─── Incentive claim ──────────────────────────────────────────────────────


def incentive_claim_payload(station_id: str, production_lot_ids, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "station_id": station_id,
        "program": "LCFS",
        "period_start": "2026-08-01",
        "period_end": "2026-08-31",
        "production_lot_ids": list(production_lot_ids),
    }
    defaults.update(overrides)
    return defaults


def revision_note_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"revision_note": "Please restate the pathway basis."}
    defaults.update(overrides)
    return defaults


def resubmit_payload(production_lot_ids, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"production_lot_ids": list(production_lot_ids)}
    defaults.update(overrides)
    return defaults


# ─── Uptime report ────────────────────────────────────────────────────────


def uptime_report_payload(
    station_id: str,
    funding_agreement_id: str,
    expected_funding_agreement_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "station_id": station_id,
        "funding_agreement_id": funding_agreement_id,
        "period_start": "2026-07-01T00:00:00Z",
        "period_end": "2026-08-01T00:00:00Z",
        "expected_funding_agreement_version": expected_funding_agreement_version,
    }
    defaults.update(overrides)
    return defaults


def amend_report_payload(period_start: str, period_end: str, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "amend_reason": "Events cleared after finalisation now fall inside the period.",
        "period_start": period_start,
        "period_end": period_end,
    }
    defaults.update(overrides)
    return defaults


# ─── Logical clock ────────────────────────────────────────────────────────


def clock_payload(to_iso8601: str) -> Dict[str, Any]:
    return {"to_iso8601": to_iso8601}
