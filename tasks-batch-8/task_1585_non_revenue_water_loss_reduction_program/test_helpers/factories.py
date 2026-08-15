"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    # DMA
    "DMA_CODE": "DMA-0001",
    "DMA_NAME": "Test District",
    "CONNECTION_COUNT": 5000,
    "MAINS_LENGTH_KM": 120.0,
    "TARGET_NRW_PCT": 20.0,
    # Water balance period (a 90-day window: 2026-01-01 .. 2026-04-01)
    "PERIOD_START": "2026-01-01T00:00:00Z",
    "PERIOD_END": "2026-04-01T00:00:00Z",
    "SYSTEM_INPUT_VOLUME_M3": 1_000_000,
    "BILLED_AUTHORIZED_M3": 720_000,
    "UNBILLED_AUTHORIZED_M3": 40_000,
    "UNAUTHORIZED_CONSUMPTION_M3": 15_000,
    "METERING_INACCURACY_M3": 25_000,
    # Night flow
    "WINDOW_START": "2026-08-02T01:00:00Z",
    "WINDOW_END": "2026-08-02T04:00:00Z",
    "MEASURED_MNF_LPS": 6.0,
    "EXPECTED_LEGITIMATE_NIGHT_USE_LPS": 2.0,
    # Leak survey — planned_start equals the initial clock reading so that
    # starting field work is immediately permitted (PRD §3.3).
    "SURVEY_PLANNED_START": "2026-08-01T00:00:00Z",
    "SURVEY_PLANNED_END": "2026-08-10T00:00:00Z",
    "SURVEY_METHOD": "ACOUSTIC",
    "CREW_LEAD_USER_ID": "fs-1",
    "COVERAGE_PCT": 80.0,
    # Leak
    "LOCATION_DESCRIPTION": "Main & 1st",
    "ESTIMATED_LOSS_LPS": 1.0,
    "DETECTED_AT": "2026-08-02T04:00:00Z",
    "REPAIR_COST_ESTIMATE": 4000,
    "ACTUAL_REPAIR_COST": 3800,
    # Customer meter
    "SERIAL_NUMBER": "SN-0001",
    "SIZE_MM": 15,
    "INSTALLED_AT": "2022-01-01T00:00:00Z",
    # Meter accuracy test
    "TESTED_AT": "2026-08-01T10:00:00Z",
    "FLOW_RATE_LPS": 0.5,
    "REGISTERED_VOLUME_M3": 99.0,
    "REFERENCE_VOLUME_M3": 100.0,
    # Unauthorized-consumption case
    "SERVICE_LOCATION_REF": "LOC-0001",
    "OPENED_AT": "2026-08-01T00:00:00Z",
    "ESTIMATED_LOSS_M3": 1200,
    "PROPOSED_ADJUSTMENT_AMOUNT": 5000,
    # Pressure project
    "PROJECT_NAME": "PRV Project",
    "PROJECT_PLANNED_START": "2026-08-01T00:00:00Z",
    "PROJECT_PLANNED_END": "2026-09-01T00:00:00Z",
    "BASELINE_PRESSURE_M": 60.0,
    "TARGET_PRESSURE_M": 42.0,
    "MEASURED_PRESSURE_M": 42.0,
    # Intervention proposal
    "KIND": "LEAK_REPAIR_PROGRAM",
    "CAPITAL_COST": 1271281.68,
    "ANNUAL_OM_COST": 10000,
    "EXPECTED_VOLUME_SAVED_M3_PER_YEAR": 100000,
    # Benchmark report
    "REPORTING_YEAR": 2026,
    "REPORTING_PERIOD_START": "2026-01-01T00:00:00Z",
    "REPORTING_PERIOD_END": "2026-12-31T00:00:00Z",
}


def create_dma_payload(**overrides) -> dict:
    defaults = {
        "code": DEFAULTS["DMA_CODE"],
        "name": DEFAULTS["DMA_NAME"],
        "connection_count": DEFAULTS["CONNECTION_COUNT"],
        "mains_length_km": DEFAULTS["MAINS_LENGTH_KM"],
        "target_nrw_pct": DEFAULTS["TARGET_NRW_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_water_balance_period_payload(dma_id, expected_dma_version, **overrides) -> dict:
    defaults = {
        "dma_id": dma_id,
        "period_start": DEFAULTS["PERIOD_START"],
        "period_end": DEFAULTS["PERIOD_END"],
        "system_input_volume_m3": DEFAULTS["SYSTEM_INPUT_VOLUME_M3"],
        "billed_authorized_m3": DEFAULTS["BILLED_AUTHORIZED_M3"],
        "unbilled_authorized_m3": DEFAULTS["UNBILLED_AUTHORIZED_M3"],
        "unauthorized_consumption_m3": DEFAULTS["UNAUTHORIZED_CONSUMPTION_M3"],
        "metering_inaccuracy_m3": DEFAULTS["METERING_INACCURACY_M3"],
        "expected_dma_version": expected_dma_version,
    }
    defaults.update(overrides)
    return defaults


def create_night_flow_assessment_payload(dma_id, **overrides) -> dict:
    defaults = {
        "dma_id": dma_id,
        "window_start": DEFAULTS["WINDOW_START"],
        "window_end": DEFAULTS["WINDOW_END"],
        "measured_mnf_lps": DEFAULTS["MEASURED_MNF_LPS"],
        "expected_legitimate_night_use_lps": (
            DEFAULTS["EXPECTED_LEGITIMATE_NIGHT_USE_LPS"]
        ),
    }
    defaults.update(overrides)
    return defaults


def create_leak_survey_payload(dma_id, **overrides) -> dict:
    defaults = {
        "dma_id": dma_id,
        "planned_start": DEFAULTS["SURVEY_PLANNED_START"],
        "planned_end": DEFAULTS["SURVEY_PLANNED_END"],
        "method": DEFAULTS["SURVEY_METHOD"],
        "crew_lead_user_id": DEFAULTS["CREW_LEAD_USER_ID"],
    }
    defaults.update(overrides)
    return defaults


def create_leak_payload(survey_id, **overrides) -> dict:
    defaults = {
        "survey_id": survey_id,
        "location_description": DEFAULTS["LOCATION_DESCRIPTION"],
        "estimated_loss_lps": DEFAULTS["ESTIMATED_LOSS_LPS"],
        "detected_at": DEFAULTS["DETECTED_AT"],
        "repair_cost_estimate": DEFAULTS["REPAIR_COST_ESTIMATE"],
    }
    defaults.update(overrides)
    return defaults


def create_customer_meter_payload(dma_id, **overrides) -> dict:
    defaults = {
        "dma_id": dma_id,
        "serial_number": DEFAULTS["SERIAL_NUMBER"],
        "size_mm": DEFAULTS["SIZE_MM"],
        "installed_at": DEFAULTS["INSTALLED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_meter_accuracy_test_payload(meter_id, **overrides) -> dict:
    defaults = {
        "meter_id": meter_id,
        "tested_at": DEFAULTS["TESTED_AT"],
        "flow_rate_lps": DEFAULTS["FLOW_RATE_LPS"],
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(dma_id, **overrides) -> dict:
    defaults = {
        "dma_id": dma_id,
        "service_location_ref": DEFAULTS["SERVICE_LOCATION_REF"],
        "opened_at": DEFAULTS["OPENED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_pressure_project_payload(dma_id, **overrides) -> dict:
    defaults = {
        "dma_id": dma_id,
        "name": DEFAULTS["PROJECT_NAME"],
        "planned_start": DEFAULTS["PROJECT_PLANNED_START"],
        "planned_end": DEFAULTS["PROJECT_PLANNED_END"],
        "baseline_pressure_m": DEFAULTS["BASELINE_PRESSURE_M"],
        "target_pressure_m": DEFAULTS["TARGET_PRESSURE_M"],
    }
    defaults.update(overrides)
    return defaults


def create_intervention_proposal_payload(dma_id, **overrides) -> dict:
    defaults = {
        "dma_id": dma_id,
        "kind": DEFAULTS["KIND"],
        "capital_cost": DEFAULTS["CAPITAL_COST"],
        "annual_om_cost": DEFAULTS["ANNUAL_OM_COST"],
        "expected_volume_saved_m3_per_year": (
            DEFAULTS["EXPECTED_VOLUME_SAVED_M3_PER_YEAR"]
        ),
    }
    defaults.update(overrides)
    return defaults


def create_benchmark_report_payload(dma_ids, **overrides) -> dict:
    defaults = {
        "reporting_year": DEFAULTS["REPORTING_YEAR"],
        "reporting_period_start": DEFAULTS["REPORTING_PERIOD_START"],
        "reporting_period_end": DEFAULTS["REPORTING_PERIOD_END"],
        "dma_ids": list(dma_ids),
    }
    defaults.update(overrides)
    return defaults
