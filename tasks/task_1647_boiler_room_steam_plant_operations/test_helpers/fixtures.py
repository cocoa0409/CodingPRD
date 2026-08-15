"""Composite setup helpers (PRD §2.4, §3).

Every helper builds preconditions from scratch using only PRD-declared
endpoints, because each test runs against a fresh server. Setup calls use the
lenient get_success_data() validator so failures surface as clear setup errors.
"""
from typing import Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_RELIEF_SETPOINT_PSI, DEFAULT_RELIEF_TOLERANCE_PCT
from .factories import (
    create_boiler_payload,
    create_chemistry_log_payload,
    create_fuel_delivery_payload,
    create_incident_payload,
    create_inspection_payload,
    create_load_dispatch_payload,
    create_log_entry_payload,
    create_operator_payload,
    create_plant_payload,
    create_steam_trap_payload,
)
from .test_users import TEST_USERS, make_operator_headers

PM = TEST_USERS["plant_manager_headers"]
INSP = TEST_USERS["inspector_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity creators
# ---------------------------------------------------------------------------

def create_plant(name: str = "Test Plant", state_code: str = "TX",
                 header_pressure_psi: float = 150) -> dict:
    resp = api_client.create_plant(
        create_plant_payload(
            name=name, state_code=state_code,
            header_pressure_psi=header_pressure_psi,
        ),
        PM,
    )
    return get_success_data(resp)


def create_boiler(plant_id: str, tag: str = "B-101",
                  rated_capacity_lb_hr: int = 30000,
                  relief_valve_setpoint_psi: float = DEFAULT_RELIEF_SETPOINT_PSI,
                  relief_valve_tolerance_pct: float = DEFAULT_RELIEF_TOLERANCE_PCT
                  ) -> dict:
    resp = api_client.create_boiler(
        plant_id,
        create_boiler_payload(
            tag=tag,
            rated_capacity_lb_hr=rated_capacity_lb_hr,
            relief_valve_setpoint_psi=relief_valve_setpoint_psi,
            relief_valve_tolerance_pct=relief_valve_tolerance_pct,
        ),
        PM,
    )
    return get_success_data(resp)


def create_operator(plant_id: str, full_name: str = "Test Operator",
                    license_class: str = "CLASS_1", license_state: str = "TX",
                    license_expires_on: str = "2027-01-01T00:00:00Z") -> dict:
    resp = api_client.create_operator(
        plant_id,
        create_operator_payload(
            full_name=full_name,
            license_class=license_class,
            license_state=license_state,
            license_expires_on=license_expires_on,
        ),
        PM,
    )
    return get_success_data(resp)


def deliver_fuel(plant_id: str, quantity_gal: float = 1000,
                 delivered_at: str = "2026-08-01T08:00:00Z",
                 supplier: str = "Acme Fuel Co") -> dict:
    resp = api_client.create_fuel_delivery(
        plant_id,
        create_fuel_delivery_payload(
            delivered_at=delivered_at, quantity_gal=quantity_gal, supplier=supplier
        ),
        PM,
    )
    return get_success_data(resp)


def set_clock(to_iso8601: str) -> None:
    get_success_data(api_client.set_clock(to_iso8601, PM))


def run_ops(plant_id: str) -> dict:
    return get_success_data(api_client.run_ops(plant_id, PM))


def get_plant(plant_id: str) -> dict:
    return get_success_data(api_client.get_plant(plant_id, PM))


def get_boiler(plant_id: str, boiler_id: str) -> dict:
    return get_success_data(api_client.get_boiler(plant_id, boiler_id, PM))


def get_operator(plant_id: str, operator_id: str) -> dict:
    return get_success_data(api_client.get_operator(plant_id, operator_id, PM))


# ---------------------------------------------------------------------------
# Tier 2: plant + people hierarchy
# ---------------------------------------------------------------------------

def setup_plant_with_operators(state_code: str = "TX", name: str = "Test Plant",
                               count: int = 2) -> Tuple[dict, list]:
    """Plant plus `count` ACTIVE CLASS_1 operators licensed in `state_code`.
    Returns (plant, [operator, ...])."""
    plant = create_plant(name=name, state_code=state_code)
    ops = [
        create_operator(
            plant["id"],
            full_name=f"Operator {i + 1}",
            license_state=state_code,
        )
        for i in range(count)
    ]
    return plant, ops


def record_chemistry_log(plant_id: str, boiler_id: str, operator_id: str,
                         recorded_at: str = "2026-08-05T08:00:00Z",
                         conductivity_boiler_umho: float = 5000,
                         conductivity_feedwater_umho: float = 1000,
                         sulfite_residual_ppm: float = 30,
                         phosphate_residual_ppm: float = 40) -> dict:
    resp = api_client.create_chemistry_log(
        plant_id,
        boiler_id,
        create_chemistry_log_payload(
            recorded_by_operator_id=operator_id,
            recorded_at=recorded_at,
            conductivity_boiler_umho=conductivity_boiler_umho,
            conductivity_feedwater_umho=conductivity_feedwater_umho,
            sulfite_residual_ppm=sulfite_residual_ppm,
            phosphate_residual_ppm=phosphate_residual_ppm,
        ),
        make_operator_headers(operator_id),
    )
    return get_success_data(resp)


def record_in_spec_chemistry(plant_id: str, boiler_id: str, operator_id: str,
                             recorded_at: str = "2026-08-05T08:00:00Z",
                             conductivity_boiler_umho: float = 5000,
                             conductivity_feedwater_umho: float = 1000) -> dict:
    """In-spec reading: default cycles 5000/1000 = 5.0, comfortably under the
    10.0 maximum."""
    return record_chemistry_log(
        plant_id, boiler_id, operator_id, recorded_at=recorded_at,
        conductivity_boiler_umho=conductivity_boiler_umho,
        conductivity_feedwater_umho=conductivity_feedwater_umho,
    )


# ---------------------------------------------------------------------------
# Tier 3: boiler lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_online_boiler(plant_id: str, operator_id: str, tag: str = "B-101",
                         rated_capacity_lb_hr: int = 30000,
                         chemistry_at: str = "2026-08-05T08:00:00Z") -> dict:
    """Boiler walked STANDBY -> WARMING -> ONLINE (in-spec chemistry present)."""
    boiler = create_boiler(plant_id, tag=tag, rated_capacity_lb_hr=rated_capacity_lb_hr)
    record_in_spec_chemistry(plant_id, boiler["id"], operator_id,
                             recorded_at=chemistry_at)
    op_headers = make_operator_headers(operator_id)
    get_success_data(api_client.warm_boiler(plant_id, boiler["id"], op_headers))
    data = get_success_data(
        api_client.bring_boiler_online(plant_id, boiler["id"], op_headers)
    )
    return data


def trip_boiler_via_incident(plant_id: str, boiler_id: str, operator_id: str,
                             severity: str = "HIGH", kind: str = "FLAME_FAILURE",
                             raised_at: str = "2026-08-05T12:00:00Z") -> dict:
    """Raise a qualifying incident that trips the boiler (PRD §3.9)."""
    resp = api_client.create_incident(
        plant_id,
        create_incident_payload(
            raised_by_operator_id=operator_id,
            severity=severity,
            kind=kind,
            triggered_boiler_id=boiler_id,
            raised_at=raised_at,
        ),
        make_operator_headers(operator_id),
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 4: log entry verification (OCC-aware)
# ---------------------------------------------------------------------------

def create_draft_log_entry(plant_id: str, boiler_id: str, recorder_id: str,
                           recorded_at: str = "2026-08-05T10:00:00Z",
                           header_pressure_reading_psi: float = 150,
                           steam_generated_lb: float = 1000,
                           fuel_burned_gal: float = 8,
                           feedwater_intake_gal: float = 130,
                           blowdown_gal: float = 10) -> dict:
    resp = api_client.create_log_entry(
        plant_id,
        boiler_id,
        create_log_entry_payload(
            recorded_by_operator_id=recorder_id,
            recorded_at=recorded_at,
            header_pressure_reading_psi=header_pressure_reading_psi,
            steam_generated_lb=steam_generated_lb,
            fuel_burned_gal=fuel_burned_gal,
            feedwater_intake_gal=feedwater_intake_gal,
            blowdown_gal=blowdown_gal,
        ),
        make_operator_headers(recorder_id),
    )
    return get_success_data(resp)


def verify_entry(plant_id: str, boiler_id: str, entry_id: str,
                 verifier_id: str) -> dict:
    """Verify a DRAFT entry with the boiler's current version (OCC-fresh).
    Segregation of duties: verifier must differ from the recorder."""
    boiler = get_boiler(plant_id, boiler_id)
    resp = api_client.verify_log_entry(
        plant_id, boiler_id, entry_id, boiler["version"],
        make_operator_headers(verifier_id),
    )
    return get_success_data(resp)


def create_and_verify_log_entry(plant_id: str, boiler_id: str, recorder_id: str,
                                verifier_id: str, **entry_overrides) -> dict:
    entry = create_draft_log_entry(
        plant_id, boiler_id, recorder_id, **entry_overrides
    )
    return verify_entry(plant_id, boiler_id, entry["id"], verifier_id)


# ---------------------------------------------------------------------------
# Tier 5: inspections
# ---------------------------------------------------------------------------

def schedule_inspection(plant_id: str, boiler_id: str,
                        inspection_kind: str = "ANNUAL_EXTERNAL",
                        scheduled_on: str = "2026-08-10T08:00:00Z",
                        inspector_name: str = "Inspector A",
                        inspector_license_no: str = "LIC-1",
                        relief_valve_lift_pressure_psi: Optional[float] = None) -> dict:
    payload = create_inspection_payload(
        inspection_kind=inspection_kind,
        scheduled_on=scheduled_on,
        inspector_name=inspector_name,
        inspector_license_no=inspector_license_no,
    )
    if relief_valve_lift_pressure_psi is not None:
        payload["relief_valve_lift_pressure_psi"] = relief_valve_lift_pressure_psi
    resp = api_client.create_inspection(plant_id, boiler_id, payload, INSP)
    return get_success_data(resp)


def record_outcome(plant_id: str, boiler_id: str, inspection_id: str,
                   outcome: str, certificate_number: Optional[str] = None,
                   certificate_expires_on: Optional[str] = None,
                   relief_valve_lift_pressure_psi: Optional[float] = None) -> dict:
    """Record an inspection outcome with a fresh OCC version read."""
    inspection = get_success_data(
        api_client.get_inspection(plant_id, boiler_id, inspection_id, PM)
    )
    payload = {
        "outcome": outcome,
        "expected_inspection_version": inspection["version"],
    }
    if certificate_number is not None:
        payload["certificate_number"] = certificate_number
    if certificate_expires_on is not None:
        payload["certificate_expires_on"] = certificate_expires_on
    if relief_valve_lift_pressure_psi is not None:
        payload["relief_valve_lift_pressure_psi"] = relief_valve_lift_pressure_psi
    resp = api_client.record_inspection_outcome(
        plant_id, boiler_id, inspection_id, payload, INSP
    )
    return get_success_data(resp)


def record_passed_annual(plant_id: str, boiler_id: str,
                         certificate_expires_on: str,
                         inspection_kind: str = "ANNUAL_EXTERNAL",
                         scheduled_on: str = "2026-08-01T08:00:00Z",
                         certificate_number: str = "CERT-1") -> dict:
    """Schedule + record PASSED on an annual inspection."""
    inspection = schedule_inspection(
        plant_id, boiler_id, inspection_kind=inspection_kind,
        scheduled_on=scheduled_on,
    )
    return record_outcome(
        plant_id, boiler_id, inspection["id"], "PASSED",
        certificate_number=certificate_number,
        certificate_expires_on=certificate_expires_on,
    )


# ---------------------------------------------------------------------------
# Tier 6: dispatch
# ---------------------------------------------------------------------------

def create_dispatch(plant_id: str, boiler_ids: list,
                    window_start_at: str = "2026-08-10T00:00:00Z",
                    window_end_at: str = "2026-08-10T08:00:00Z",
                    target_steam_lb_hr: int = 20000) -> dict:
    resp = api_client.create_load_dispatch(
        plant_id,
        create_load_dispatch_payload(
            window_start_at=window_start_at,
            window_end_at=window_end_at,
            target_steam_lb_hr=target_steam_lb_hr,
            assigned_boiler_ids=boiler_ids,
        ),
        PM,
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 7: steam traps
# ---------------------------------------------------------------------------

def create_steam_trap(plant_id: str, tag: str = "ST-207", location: str = "HDR-A",
                      orifice_diameter_in: float = 0.25,
                      design_pressure_psi: float = 144) -> dict:
    resp = api_client.create_steam_trap(
        plant_id,
        create_steam_trap_payload(
            tag=tag, location=location,
            orifice_diameter_in=orifice_diameter_in,
            design_pressure_psi=design_pressure_psi,
        ),
        PM,
    )
    return get_success_data(resp)


def create_leaking_trap(plant_id: str, operator_id: str, tag: str = "ST-207",
                        orifice_diameter_in: float = 0.25,
                        design_pressure_psi: float = 144) -> dict:
    """Trap surveyed LEAKING so its leak rate is computed (PRD §3.7)."""
    trap = create_steam_trap(
        plant_id, tag=tag, orifice_diameter_in=orifice_diameter_in,
        design_pressure_psi=design_pressure_psi,
    )
    data = get_success_data(
        api_client.survey_steam_trap(
            plant_id, trap["id"], "LEAKING", make_operator_headers(operator_id)
        )
    )
    return data
