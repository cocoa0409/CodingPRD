"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "PROJECT_NAME": "P-DEFAULT",
    "MEASUREMENT_BASIS": "SCOW",
    "BASE_RATE": 1500,
    "STANDBY_RATE": 5000,
    "LD_RATE": 100000,
    "PERMIT_NUMBER": "PER-1",
    "WINDOW_START": "2026-05-01T00:00:00Z",
    "WINDOW_END": "2026-08-31T23:59:59Z",
    "TURBIDITY_LIMIT": 50,
    "TURBIDITY_CEILING": 100,
    "TURBIDITY_AVERAGING_HOURS": 24,
    "SPECIES_STANDDOWN_HOURS": 6,
    "REACH_NAME": "R1",
    "DESIGN_QUANTITY": 40000,
    "REQUIRED_DEPTH": 25.0,
    "ALLOWABLE_OVERDEPTH": 1.0,
    "OVERDEPTH_ALLOWANCE": 2000,
    "CONTRACTOR_REF": "DGE-7",
    "PLANT_TYPE": "HOPPER",
    "RATED_DAILY_PRODUCTION": 4000,
    "MATERIAL_CLASS": "SAND",
    "PLANNED_START": "2026-05-10T00:00:00Z",
    "PLANNED_END": "2026-06-30T00:00:00Z",
    "PRE_SURVEY_VOLUME": 40000,
    "PRE_SURVEY_DEPTH": 18.5,
    "EVENT_STARTED": "2026-05-10T00:00:00Z",
    "SITE_NAME": "SITE-A",
    "SITE_TYPE": "OPEN_WATER",
    "SITE_CAPACITY": 50000,
    "BULKING_FACTOR": 1.6,
    "PLACED_UTC": "2026-05-12T12:00:00Z",
    "DECLARED_VOLUME": 1609,
    "WITNESSED_VOLUME": 1609,
    "SPECIES_CLASS": "FISH",
    "CERT_PERIOD_START": "2026-05-01T00:00:00Z",
    "CERT_PERIOD_END": "2026-05-31T00:00:00Z",
}


def create_project_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PROJECT_NAME"],
        "measurement_basis": DEFAULTS["MEASUREMENT_BASIS"],
        "base_rate_cents_per_cy": DEFAULTS["BASE_RATE"],
        "standby_rate_cents_per_hour": DEFAULTS["STANDBY_RATE"],
        "liquidated_damages_cents_per_day": DEFAULTS["LD_RATE"],
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(project_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "permit_number": DEFAULTS["PERMIT_NUMBER"],
        "window_start_utc": DEFAULTS["WINDOW_START"],
        "window_end_utc": DEFAULTS["WINDOW_END"],
        "turbidity_limit_ntu": DEFAULTS["TURBIDITY_LIMIT"],
        "turbidity_ceiling_ntu": DEFAULTS["TURBIDITY_CEILING"],
        "turbidity_averaging_hours": DEFAULTS["TURBIDITY_AVERAGING_HOURS"],
        "species_standdown_hours": DEFAULTS["SPECIES_STANDDOWN_HOURS"],
    }
    defaults.update(overrides)
    return defaults


def create_reach_payload(project_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "name": DEFAULTS["REACH_NAME"],
        "design_quantity_cy": DEFAULTS["DESIGN_QUANTITY"],
        "required_depth_ft": DEFAULTS["REQUIRED_DEPTH"],
        "allowable_overdepth_ft": DEFAULTS["ALLOWABLE_OVERDEPTH"],
        "overdepth_allowance_cy": DEFAULTS["OVERDEPTH_ALLOWANCE"],
    }
    defaults.update(overrides)
    return defaults


def create_plant_payload(**overrides) -> dict:
    defaults = {
        "contractor_ref": DEFAULTS["CONTRACTOR_REF"],
        "plant_type": DEFAULTS["PLANT_TYPE"],
        "rated_daily_production_cy": DEFAULTS["RATED_DAILY_PRODUCTION"],
    }
    defaults.update(overrides)
    return defaults


def create_dredge_plan_payload(project_id: str, plant_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "plant_id": plant_id,
        "material_class": DEFAULTS["MATERIAL_CLASS"],
        "planned_start_utc": DEFAULTS["PLANNED_START"],
        "planned_end_utc": DEFAULTS["PLANNED_END"],
    }
    defaults.update(overrides)
    return defaults


def create_survey_payload(reach_id: str, **overrides) -> dict:
    defaults = {
        "reach_id": reach_id,
        "kind": "PRE_DREDGE",
        "measured_volume_cy": DEFAULTS["PRE_SURVEY_VOLUME"],
        "min_sounding_depth_ft": DEFAULTS["PRE_SURVEY_DEPTH"],
    }
    defaults.update(overrides)
    return defaults


def create_dredge_event_payload(reach_id: str, plant_id: str, **overrides) -> dict:
    defaults = {
        "reach_id": reach_id,
        "plant_id": plant_id,
        "started_utc": DEFAULTS["EVENT_STARTED"],
    }
    defaults.update(overrides)
    return defaults


def create_turbidity_reading_payload(project_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "value_ntu": 30,
        "taken_utc": "2026-05-10T08:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_species_sighting_payload(project_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "species_class": DEFAULTS["SPECIES_CLASS"],
        "observed_utc": "2026-05-10T06:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_disposal_site_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["SITE_NAME"],
        "site_type": DEFAULTS["SITE_TYPE"],
        "capacity_cy": DEFAULTS["SITE_CAPACITY"],
        "bulking_factor": DEFAULTS["BULKING_FACTOR"],
    }
    defaults.update(overrides)
    return defaults


def create_placement_ticket_payload(
    dredge_event_id: str, disposal_site_id: str, **overrides
) -> dict:
    defaults = {
        "dredge_event_id": dredge_event_id,
        "disposal_site_id": disposal_site_id,
        "placed_utc": DEFAULTS["PLACED_UTC"],
        "declared_volume_cy": DEFAULTS["DECLARED_VOLUME"],
    }
    defaults.update(overrides)
    return defaults


def create_standby_claim_payload(project_id: str, plant_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "plant_id": plant_id,
        "period_start_utc": "2026-05-10T06:00:00Z",
        "period_end_utc": "2026-05-10T16:00:00Z",
        "claimed_hours": 10.0,
        "reason": "WEATHER",
    }
    defaults.update(overrides)
    return defaults


def create_payment_certificate_payload(
    project_id: str, reach_ids, **overrides
) -> dict:
    defaults = {
        "project_id": project_id,
        "certificate_type": "INTERIM",
        "period_start_utc": DEFAULTS["CERT_PERIOD_START"],
        "period_end_utc": DEFAULTS["CERT_PERIOD_END"],
        "reach_ids": list(reach_ids),
    }
    defaults.update(overrides)
    return defaults
