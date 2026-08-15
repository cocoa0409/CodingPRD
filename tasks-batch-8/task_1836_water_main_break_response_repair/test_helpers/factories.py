"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "SEGMENT_REF": "MAIN-8-OAK",
    "MATERIAL": "DUCTILE_IRON",
    "DIAMETER_INCHES": 8,
    "INSTALL_YEAR": 1978,
    "VALVE_CODE": "V-1",
    "COVERAGE_ZONE": "Z1",
    "CUSTOMERS_SERVED": 100,
    "LOCATION_DESCRIPTION": "12 Oak St",
    "BREAK_SOURCE": "CUSTOMER_CALL",
    "BREAK_TYPE": "CIRCUMFERENTIAL",
    "SEVERITY": "MEDIUM",
    "CREW_NAME": "Crew Alpha",
    "CREW_SIZE": 3,
    "EQUIPMENT_CLASS": "LIGHT",
    "HOURLY_RATE_CENTS": 6000,
    "EST_PIPE_LENGTH_FT": 4,
    "ACTUAL_PIPE_LENGTH_FT": 4,
    "LABOR_HOURS": 1,
    "CLAIMANT_NAME": "J. Homeowner",
    "CLAIMED_AMOUNT_CENTS": 100000,
    "STREET_BLOCK": "OAK-100-BLK",
    "CONTROL_PLAN": "LANE_CLOSURE",
    "ANOMALY_TYPE": "PRESSURE_DROP",
    "OBSERVED_AT": "2026-08-01T00:00:00Z",
    "MAGNITUDE_PCT": 45,
    "PATCH_COST_CENTS": 10000,
}


def create_pipe_segment_payload(**overrides) -> dict:
    defaults = {
        "segment_ref": DEFAULTS["SEGMENT_REF"],
        "material": DEFAULTS["MATERIAL"],
        "diameter_inches": DEFAULTS["DIAMETER_INCHES"],
        "install_year": DEFAULTS["INSTALL_YEAR"],
    }
    defaults.update(overrides)
    return defaults


def create_valve_payload(**overrides) -> dict:
    defaults = {
        "valve_code": DEFAULTS["VALVE_CODE"],
        "pipe_segment_id": None,  # caller must supply
        "coverage_zone": DEFAULTS["COVERAGE_ZONE"],
        "customers_served": DEFAULTS["CUSTOMERS_SERVED"],
    }
    defaults.update(overrides)
    return defaults


def create_pressure_anomaly_payload(**overrides) -> dict:
    defaults = {
        "pipe_segment_id": None,  # caller must supply
        "anomaly_type": DEFAULTS["ANOMALY_TYPE"],
        "observed_at": DEFAULTS["OBSERVED_AT"],
        "magnitude_pct": DEFAULTS["MAGNITUDE_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_break_report_payload(**overrides) -> dict:
    defaults = {
        "location_description": DEFAULTS["LOCATION_DESCRIPTION"],
        "source": DEFAULTS["BREAK_SOURCE"],
    }
    defaults.update(overrides)
    return defaults


def confirm_break_report_payload(**overrides) -> dict:
    defaults = {
        "pipe_segment_id": None,  # caller must supply
        "break_type": DEFAULTS["BREAK_TYPE"],
        "severity": DEFAULTS["SEVERITY"],
    }
    defaults.update(overrides)
    return defaults


def create_isolation_event_payload(**overrides) -> dict:
    defaults = {
        "break_report_id": None,  # caller must supply
        "valve_ids": [],
        "expected_break_report_version": None,  # caller must supply
    }
    defaults.update(overrides)
    return defaults


def create_crew_payload(**overrides) -> dict:
    defaults = {
        "crew_name": DEFAULTS["CREW_NAME"],
        "crew_size": DEFAULTS["CREW_SIZE"],
        "equipment_class": DEFAULTS["EQUIPMENT_CLASS"],
        "hourly_rate_cents": DEFAULTS["HOURLY_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(**overrides) -> dict:
    defaults = {
        "break_report_id": None,  # caller must supply
        "est_pipe_length_ft": DEFAULTS["EST_PIPE_LENGTH_FT"],
    }
    defaults.update(overrides)
    return defaults


def dispatch_work_order_payload(**overrides) -> dict:
    defaults: dict = {}
    defaults.update(overrides)
    return defaults


def complete_work_order_payload(**overrides) -> dict:
    defaults = {
        "actual_pipe_length_ft": DEFAULTS["ACTUAL_PIPE_LENGTH_FT"],
        "labor_hours": DEFAULTS["LABOR_HOURS"],
        "materials_used": [],
    }
    defaults.update(overrides)
    return defaults


def create_boil_water_advisory_payload(**overrides) -> dict:
    defaults = {
        "break_report_id": None,  # caller must supply
    }
    defaults.update(overrides)
    return defaults


def create_water_quality_test_payload(**overrides) -> dict:
    defaults = {
        "advisory_id": None,  # caller must supply
        "sampled_at": "2026-08-02T00:00:00Z",
        "chlorine_residual_mg_l": 0.30,
        "coliform_result": "PASS",
    }
    defaults.update(overrides)
    return defaults


def create_traffic_permit_payload(**overrides) -> dict:
    defaults = {
        "break_report_id": None,  # caller must supply
        "street_block": DEFAULTS["STREET_BLOCK"],
        "valid_from": "2026-08-10T00:00:00Z",
        "valid_to": "2026-08-12T00:00:00Z",
        "control_plan": DEFAULTS["CONTROL_PLAN"],
    }
    defaults.update(overrides)
    return defaults


def schedule_restoration_job_payload(**overrides) -> dict:
    defaults = {
        "scheduled_start": "2026-08-10T08:00:00Z",
        "scheduled_end": "2026-08-10T16:00:00Z",
        "traffic_permit_id": None,  # caller must supply
    }
    defaults.update(overrides)
    return defaults


def complete_restoration_job_payload(**overrides) -> dict:
    defaults = {
        "patch_cost_cents": DEFAULTS["PATCH_COST_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_damage_claim_payload(**overrides) -> dict:
    defaults = {
        "break_report_id": None,  # caller must supply
        "claimant_name": DEFAULTS["CLAIMANT_NAME"],
        "claimed_amount_cents": DEFAULTS["CLAIMED_AMOUNT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def approve_damage_claim_payload(**overrides) -> dict:
    defaults = {
        "approved_amount_cents": 1,  # caller should supply a sensible amount
    }
    defaults.update(overrides)
    return defaults


def correlate_payload(**overrides) -> dict:
    defaults = {
        "pressure_anomaly_id": None,  # caller must supply
    }
    defaults.update(overrides)
    return defaults
