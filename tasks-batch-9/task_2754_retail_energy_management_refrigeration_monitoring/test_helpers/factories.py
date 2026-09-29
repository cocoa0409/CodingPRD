"""Payload factories, one per resource, carrying only input fields."""

DEFAULTS = {
    "STORE_CODE": "STR-001",
    "CLIMATE_ZONE": "MIXED",
    "STORE_FORMAT": "SUPERCENTER",
    "FLOOR_AREA_SQFT": 120000,
    "UTILITY_NAME": "Statewide Power",
    "RATE_SCHEDULE_CODE": "GS-3",
    "CANDIDATE_RATE_SCHEDULE_CODE": "GS-9",
    "CAPEX_USD": 240240.00,
    "PROJECTED_ANNUAL_SAVINGS_KWH": 520000.00,
}


def create_store_payload(**overrides) -> dict:
    payload = {
        "code": DEFAULTS["STORE_CODE"],
        "climate_zone": DEFAULTS["CLIMATE_ZONE"],
        "store_format": DEFAULTS["STORE_FORMAT"],
        "floor_area_sqft": DEFAULTS["FLOOR_AREA_SQFT"],
    }
    payload.update(overrides)
    return payload


def create_setpoint_standard_payload(**overrides) -> dict:
    payload = {
        "climate_zone": DEFAULTS["CLIMATE_ZONE"],
        "store_format": DEFAULTS["STORE_FORMAT"],
        "season": "SUMMER",
        "cooling_setpoint_f": 74.0,
        "heating_setpoint_f": 68.0,
        "deadband_f": 2.0,
        "lighting_lux_target": 750,
    }
    payload.update(overrides)
    return payload


def commission_bms_payload(standard_id: str, expected_store_version: int, **overrides) -> dict:
    payload = {
        "standard_id": standard_id,
        "expected_store_version": expected_store_version,
    }
    payload.update(overrides)
    return payload


def create_utility_account_payload(**overrides) -> dict:
    payload = {
        "utility_name": DEFAULTS["UTILITY_NAME"],
        "rate_schedule_code": DEFAULTS["RATE_SCHEDULE_CODE"],
        "rate_family": "TOU_DEMAND",
        "demand_charge_per_kw": 14.50,
        "rate_on_peak": 0.1450,
        "rate_off_peak": 0.0800,
    }
    payload.update(overrides)
    return payload


def candidate_tariff_fields(
    rate_schedule_code: str = DEFAULTS["CANDIDATE_RATE_SCHEDULE_CODE"],
    rate_family: str = "TOU_DEMAND",
    demand_charge_per_kw: float = 11.00,
    rate_on_peak: float = 0.1100,
    rate_off_peak: float = 0.0700,
) -> dict:
    """The five optional candidate-tariff inputs of a utility account."""
    return {
        "candidate_rate_schedule_code": rate_schedule_code,
        "candidate_rate_family": rate_family,
        "candidate_demand_charge_per_kw": demand_charge_per_kw,
        "candidate_rate_on_peak": rate_on_peak,
        "candidate_rate_off_peak": rate_off_peak,
    }


def demand_interval(
    interval_start_iso: str,
    kw_demand: float,
    is_on_peak: bool = True,
    **overrides,
) -> dict:
    element = {
        "interval_start_iso": interval_start_iso,
        "kw_demand": kw_demand,
        "is_on_peak": is_on_peak,
    }
    element.update(overrides)
    return element


def ingest_intervals_payload(intervals: list) -> dict:
    return {"intervals": intervals}


def create_utility_bill_payload(**overrides) -> dict:
    payload = {
        "period_start_iso": "2026-06-01T00:00:00Z",
        "period_end_iso": "2026-07-01T00:00:00Z",
        "on_peak_kwh": 144000,
        "off_peak_kwh": 216000,
        "billed_kwh": 360000,
        "billed_peak_kw": 1200.0,
        "billed_amount_usd": 58208.15,
    }
    payload.update(overrides)
    return payload


def create_demand_response_event_payload(**overrides) -> dict:
    payload = {
        "program_code": "DR-A",
        "curtailment_start_iso": "2026-08-20T14:00:00Z",
        "curtailment_end_iso": "2026-08-20T16:00:00Z",
        "target_reduction_kw": 200.0,
    }
    payload.update(overrides)
    return payload


def create_refrigeration_case_payload(**overrides) -> dict:
    payload = {
        "case_code": "CASE-001",
        "case_type": "MEDIUM_TEMP",
        "product_class": "DAIRY",
        "alarm_high_f": 41.0,
        "alarm_low_f": 28.0,
        "product_value_usd": 3000.00,
    }
    payload.update(overrides)
    return payload


def reading_payload(temp_f: float, reading_iso: str, **overrides) -> dict:
    payload = {"temp_f": temp_f, "reading_iso": reading_iso}
    payload.update(overrides)
    return payload


def monitoring_state_payload(target_state: str) -> dict:
    return {"target_state": target_state}


def document_disposition_payload(disposition: str, corrective_action_note: str) -> dict:
    return {
        "disposition": disposition,
        "corrective_action_note": corrective_action_note,
    }


def create_lighting_override_payload(**overrides) -> dict:
    payload = {
        "zone": "SALES_FLOOR",
        "override_type": "SCHEDULE_EXTEND",
        "start_iso": "2026-08-01T00:00:00Z",
        "end_iso": "2026-08-01T08:00:00Z",
        "zone_load_kw": 37.5,
        "requested_reason": "inventory count running late",
    }
    payload.update(overrides)
    return payload


def create_fault_diagnostic_payload(**overrides) -> dict:
    payload = {
        "equipment_ref": "RACK-01",
        "equipment_class": "REFRIGERATION",
        "fault_code": "SUCTION-HI",
        "severity": "MINOR",
        "occurrence_count": 2,
        "affected_load_kw": 20.0,
    }
    payload.update(overrides)
    return payload


def triage_payload(outcome: str) -> dict:
    return {"outcome": outcome}


def schedule_work_order_payload(scheduled_start_iso: str, scheduled_end_iso: str) -> dict:
    return {
        "scheduled_start_iso": scheduled_start_iso,
        "scheduled_end_iso": scheduled_end_iso,
    }


def complete_work_order_payload(completion_note: str = "compressor replaced") -> dict:
    return {"completion_note": completion_note}


def create_retrofit_project_payload(**overrides) -> dict:
    payload = {
        "measure_type": "LED_RETROFIT",
        "capex_usd": DEFAULTS["CAPEX_USD"],
        "projected_annual_savings_kwh": DEFAULTS["PROJECTED_ANNUAL_SAVINGS_KWH"],
    }
    payload.update(overrides)
    return payload


def approve_retrofit_payload(decision: str = "APPROVE") -> dict:
    return {"decision": decision}


def submit_measurement_payload(**overrides) -> dict:
    payload = {
        "install_completed_iso": "2026-05-01T00:00:00Z",
        "baseline_period_kwh": 300000.00,
        "post_period_kwh": 220000.00,
        "mv_period_days": 90,
    }
    payload.update(overrides)
    return payload


def revoke_verification_payload(revocation_reason: str = "meter calibration error") -> dict:
    return {"revocation_reason": revocation_reason}


def tariff_switch_payload(effective_from_iso: str, expected_utility_account_version: int) -> dict:
    return {
        "effective_from_iso": effective_from_iso,
        "expected_utility_account_version": expected_utility_account_version,
    }


def dispute_payload(dispute_reason: str = "metered demand disagrees with the invoice") -> dict:
    return {"dispute_reason": dispute_reason}


def adjustment_payload(adjusted_amount_usd: float) -> dict:
    return {"adjusted_amount_usd": adjusted_amount_usd}


def reversal_payload(reversal_reason: str = "utility recalculation") -> dict:
    return {"reversal_reason": reversal_reason}
