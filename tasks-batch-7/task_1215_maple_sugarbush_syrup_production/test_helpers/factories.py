"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "YEAR": 2027,
    "OPENS_ON": "2027-02-01",
    "CLOSES_ON": "2027-04-15",
    "PLANNED_TAPS": 10000,
    "BUSH_NAME": "North Woods",
    "TAP_CAPACITY": 5000,
    "LINE_CODE": "L1",
    "TAP_COUNT": 100,
    "VACUUM_TARGET_INHG": 25.0,
    "WINDOW_OPENS_AT": "2027-03-01T00:00:00Z",
    "WINDOW_CLOSES_AT": "2027-03-10T00:00:00Z",
    "FORECAST_MIN_F": 28.0,
    "FORECAST_MAX_F": 42.0,
    "TAPPER_NAME": "Tammy Tapper",
    "BOILER_NAME": "Bob Boiler",
    "GRADER_NAME": "Gail Grader",
    "GALLONS_COLLECTED": 10.0,
    "MEASURED_BRIX": 2.0,
    "EVAPORATOR_CAPACITY_GAL": 200,
    "LANDOWNER_NAME": "Landowner Lou",
    "PER_TAP_CENTS": 300,
    "SHARE_PCT": 30.0,
    "TERM_START": "2027-01-01",
    "TERM_END": "2027-12-31",
    "FLAVOR_SCORE": 90,
    "TRANSMITTANCE": 80.0,
    "FINISHED_BRIX": 66.5,
    "MEASURED_SYRUP_GALLONS": 0.22,
}


def create_season_payload(**overrides) -> dict:
    defaults = {
        "year": DEFAULTS["YEAR"],
        "opens_on": DEFAULTS["OPENS_ON"],
        "closes_on": DEFAULTS["CLOSES_ON"],
        "planned_taps": DEFAULTS["PLANNED_TAPS"],
    }
    defaults.update(overrides)
    return defaults


def create_sugarbush_payload(season_id: str, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "name": DEFAULTS["BUSH_NAME"],
        "tap_capacity": DEFAULTS["TAP_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_lease_payload(sugarbush_id: str, **overrides) -> dict:
    defaults = {
        "sugarbush_id": sugarbush_id,
        "landowner_name": DEFAULTS["LANDOWNER_NAME"],
        "royalty_basis": "PER_TAP",
        "per_tap_cents": DEFAULTS["PER_TAP_CENTS"],
        "certified_organic_required": False,
        "term_start": DEFAULTS["TERM_START"],
        "term_end": DEFAULTS["TERM_END"],
    }
    defaults.update(overrides)
    return defaults


def create_tap_line_payload(sugarbush_id: str, **overrides) -> dict:
    defaults = {
        "sugarbush_id": sugarbush_id,
        "line_code": DEFAULTS["LINE_CODE"],
        "tap_count": DEFAULTS["TAP_COUNT"],
        "vacuum_target_inhg": DEFAULTS["VACUUM_TARGET_INHG"],
    }
    defaults.update(overrides)
    return defaults


def create_vacuum_reading_payload(inhg: float, **overrides) -> dict:
    defaults = {"inhg": inhg}
    defaults.update(overrides)
    return defaults


def create_weather_window_payload(season_id: str, expected_season_version: int, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "opens_at": DEFAULTS["WINDOW_OPENS_AT"],
        "closes_at": DEFAULTS["WINDOW_CLOSES_AT"],
        "forecast_min_f": DEFAULTS["FORECAST_MIN_F"],
        "forecast_max_f": DEFAULTS["FORECAST_MAX_F"],
        "expected_season_version": expected_season_version,
    }
    defaults.update(overrides)
    return defaults


def create_crew_member_payload(season_id: str, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "name": DEFAULTS["TAPPER_NAME"],
        "crew_role": "TAPPER",
    }
    defaults.update(overrides)
    return defaults


def create_sap_run_payload(sugarbush_id: str, weather_window_id: str, collected_by: str, **overrides) -> dict:
    defaults = {
        "sugarbush_id": sugarbush_id,
        "weather_window_id": weather_window_id,
        "collected_by": collected_by,
        "gallons_collected": DEFAULTS["GALLONS_COLLECTED"],
        "measured_brix": DEFAULTS["MEASURED_BRIX"],
    }
    defaults.update(overrides)
    return defaults


def create_batch_payload(season_id: str, boiled_by: str, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "boiled_by": boiled_by,
        "evaporator_capacity_gal": DEFAULTS["EVAPORATOR_CAPACITY_GAL"],
    }
    defaults.update(overrides)
    return defaults


def create_batch_intake_payload(sap_run_id: str, gallons_drawn: float, **overrides) -> dict:
    defaults = {"sap_run_id": sap_run_id, "gallons_drawn": gallons_drawn}
    defaults.update(overrides)
    return defaults


def create_auto_fill_payload(target_gallons, **overrides) -> dict:
    defaults = {"target_gallons": target_gallons}
    defaults.update(overrides)
    return defaults


def create_finish_payload(finished_brix: float, measured_syrup_gallons: float, **overrides) -> dict:
    defaults = {
        "finished_brix": finished_brix,
        "measured_syrup_gallons": measured_syrup_gallons,
    }
    defaults.update(overrides)
    return defaults


def create_grade_payload(light_transmittance_pct: float, **overrides) -> dict:
    defaults = {"light_transmittance_pct": light_transmittance_pct}
    defaults.update(overrides)
    return defaults


def create_flavor_evaluation_payload(evaluator_id: str, flavor_score: int, **overrides) -> dict:
    defaults = {"evaluator_id": evaluator_id, "flavor_score": flavor_score}
    defaults.update(overrides)
    return defaults


def create_packaging_run_payload(syrup_lot_id: str, **overrides) -> dict:
    defaults = {
        "syrup_lot_id": syrup_lot_id,
        "container_type": "DRUM_55",
        "units_planned": 1,
    }
    defaults.update(overrides)
    return defaults


def create_cert_audit_payload(**overrides) -> dict:
    defaults = {"audit_type": "ORGANIC", "scheduled_for": "2027-02-10"}
    defaults.update(overrides)
    return defaults
