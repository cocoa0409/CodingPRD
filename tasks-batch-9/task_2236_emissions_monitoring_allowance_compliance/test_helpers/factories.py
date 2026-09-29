"""Payload factories — one per resource, client-supplied input fields only."""
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS

DEFAULTS: Dict[str, Any] = {
    "FACILITY_NAME": "Kestrel Generating Station",
    "ORISPL_CODE": "7101",
    "STATE_CODE": "OH",
    "OPERATOR_ORG": TEST_DEFAULTS["OPERATOR_ORG"],
    "PROGRAMS": ["ARP_SO2"],
    "TRUE_UP_DEADLINE_UTC": "2027-03-01T00:00:00Z",
    "UNIT_IDENTIFIER": "U1",
    "PRIMARY_FUEL": "COAL",
    "NAMEPLATE_CAPACITY_MW": 600,
    "MAX_RATED_HEAT_INPUT_MMBTU_HR": 6000,
    "CONTROL_DEVICE": "FGD",
    "SPAN_VALUE": 400.0,
    "CALIBRATION_ERROR_SPEC_PCT": 2.5,
}


def facility_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "name": DEFAULTS["FACILITY_NAME"],
        "orispl_code": DEFAULTS["ORISPL_CODE"],
        "state_code": DEFAULTS["STATE_CODE"],
        "operator_org": DEFAULTS["OPERATOR_ORG"],
        "programs": list(DEFAULTS["PROGRAMS"]),
        "true_up_deadline_utc": DEFAULTS["TRUE_UP_DEADLINE_UTC"],
    }
    payload.update(overrides)
    return payload


def unit_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "unit_identifier": DEFAULTS["UNIT_IDENTIFIER"],
        "primary_fuel": DEFAULTS["PRIMARY_FUEL"],
        "nameplate_capacity_mw": DEFAULTS["NAMEPLATE_CAPACITY_MW"],
        "max_rated_heat_input_mmbtu_hr": DEFAULTS["MAX_RATED_HEAT_INPUT_MMBTU_HR"],
        "control_device": DEFAULTS["CONTROL_DEVICE"],
    }
    payload.update(overrides)
    return payload


def monitoring_system_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "parameter": "SO2",
        "system_type": "CEM",
        "span_value": DEFAULTS["SPAN_VALUE"],
        "calibration_error_spec_pct": DEFAULTS["CALIBRATION_ERROR_SPEC_PCT"],
    }
    payload.update(overrides)
    return payload


def daily_calibration_payload(
    expected_monitoring_system_version: int,
    calibration_utc: str = "2026-04-01T00:00:00Z",
    span_reference_value: float = 360.0,
    span_measured_value: float = 368.0,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "expected_monitoring_system_version": expected_monitoring_system_version,
        "calibration_utc": calibration_utc,
        "zero_reference_value": 0.0,
        "zero_measured_value": 0.0,
        "span_reference_value": span_reference_value,
        "span_measured_value": span_measured_value,
    }
    payload.update(overrides)
    return payload


def rata_test_payload(
    window_start_utc: str = "2026-04-03T00:00:00Z",
    window_end_utc: str = "2026-04-04T00:00:00Z",
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "window_start_utc": window_start_utc,
        "window_end_utc": window_end_utc,
    }
    payload.update(overrides)
    return payload


def rata_runs_payload(pairs: List[Dict[str, float]]) -> Dict[str, Any]:
    return {"runs": [dict(p) for p in pairs]}


def fuel_sample_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "sample_utc": "2026-04-01T00:00:00Z",
        "fuel_type": "COAL",
        "lot_identifier": "LOT-A",
    }
    payload.update(overrides)
    return payload


def fuel_analysis_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "outcome": "ANALYZED",
        "gcv_btu_per_lb": 12000.0,
        "sulfur_content_pct": 1.5,
        "analysis_method": "ASTM_D5865",
    }
    payload.update(overrides)
    return payload


def quarterly_report_payload(year: int = 2026, quarter: int = 2, **overrides):
    payload = {"year": year, "quarter": quarter}
    payload.update(overrides)
    return payload


def cems_hour_payload(
    hour_begin_utc: str,
    flow_scfh: float = 8000000.0,
    co2_conc_pct: float = 12.5,
    so2_conc_ppm: Optional[float] = 220.0,
    nox_rate_lb_mmbtu: Optional[float] = 0.180,
    op_time_fraction: float = 1.0,
    **overrides,
) -> Dict[str, Any]:
    """One `CEMS_FLOW_CO2` hour: requires flow, CO2 and SO2 concentrations."""
    payload: Dict[str, Any] = {
        "hour_begin_utc": hour_begin_utc,
        "op_time_fraction": op_time_fraction,
        "heat_input_method": "CEMS_FLOW_CO2",
        "flow_scfh": flow_scfh,
        "co2_conc_pct": co2_conc_pct,
    }
    if so2_conc_ppm is not None:
        payload["so2_conc_ppm"] = so2_conc_ppm
    if nox_rate_lb_mmbtu is not None:
        payload["nox_rate_lb_mmbtu"] = nox_rate_lb_mmbtu
    payload.update(overrides)
    return payload


def appendix_d_hour_payload(
    hour_begin_utc: str,
    fuel_sample_id: str,
    fuel_flow_lbs: float = 45000.0,
    nox_rate_lb_mmbtu: Optional[float] = 0.180,
    op_time_fraction: float = 1.0,
    **overrides,
) -> Dict[str, Any]:
    """One `APPENDIX_D_FUEL` hour: requires fuel mass and an analysed sample."""
    payload: Dict[str, Any] = {
        "hour_begin_utc": hour_begin_utc,
        "op_time_fraction": op_time_fraction,
        "heat_input_method": "APPENDIX_D_FUEL",
        "fuel_flow_lbs": fuel_flow_lbs,
        "fuel_sample_id": fuel_sample_id,
    }
    if nox_rate_lb_mmbtu is not None:
        payload["nox_rate_lb_mmbtu"] = nox_rate_lb_mmbtu
    payload.update(overrides)
    return payload


def single_hour_payload(
    expected_quarterly_report_version: int, hour: Dict[str, Any]
) -> Dict[str, Any]:
    payload = {
        "expected_quarterly_report_version": expected_quarterly_report_version
    }
    payload.update(hour)
    return payload


def bulk_hours_payload(
    expected_quarterly_report_version: int, hours: List[Dict[str, Any]]
) -> Dict[str, Any]:
    return {
        "expected_quarterly_report_version": expected_quarterly_report_version,
        "hours": [dict(h) for h in hours],
    }


def permit_limit_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "pollutant": "SO2",
        "limit_value": 250.0,
        "limit_units": "LB_PER_HR",
        "averaging_basis": "ROLLING_3_HOUR",
        "effective_from_utc": "2026-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def allowance_account_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "program": "ARP_SO2",
        "compliance_year": 2026,
        "holdings_current_vintage_tons": 5.0,
        "holdings_prior_vintage_tons": 5.0,
        "holdings_next_vintage_tons": 5.0,
    }
    payload.update(overrides)
    return payload


def allowance_transaction_payload(
    expected_allowance_account_version: int,
    allowance_account_id: str,
    transaction_type: str = "PURCHASE",
    quantity_tons: float = 5.0,
    vintage_year: int = 2026,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "expected_allowance_account_version": expected_allowance_account_version,
        "allowance_account_id": allowance_account_id,
        "transaction_type": transaction_type,
        "quantity_tons": quantity_tons,
        "vintage_year": vintage_year,
    }
    payload.update(overrides)
    return payload


def control_outage_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "start_utc": "2026-04-03T00:00:00Z",
        "end_utc": "2026-04-04T00:00:00Z",
        "outage_type": "PLANNED_MAINTENANCE",
        "control_device": "FGD",
    }
    payload.update(overrides)
    return payload


def certification_payload(
    expected_quarterly_report_version: int,
    statement_text: str = TEST_DEFAULTS["CERTIFICATION_STATEMENT"],
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "expected_quarterly_report_version": expected_quarterly_report_version,
        "statement_text": statement_text,
    }
    payload.update(overrides)
    return payload
