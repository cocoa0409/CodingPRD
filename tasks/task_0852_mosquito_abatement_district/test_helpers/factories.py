"""Payload factories — one per creatable resource, input fields only."""

DEFAULTS = {
    "AREA_NAME": "Northwest Zone",
    "AREA_CODE": "NW1",
    "SEASON_START_DATE": "2026-05-01",
    "POPULATION": 50000,
    "OPERATOR_NAME": "Bee Bright Apiary",
    "CONTACT_EMAIL": "bees@example.com",
    "TRAP_SITE_CODE": "T-001",
    "APPLICATOR_NAME": "Tess Vega",
    "LICENSE_NO": "L-1001",
    "LICENSE_EXPIRES_ON": "2027-12-31",
    "PRODUCT_NAME": "VectoBac 12AS",
    "EPA_REG_NO": "EPA-202",
    "ROUTE_CODE": "R-1",
    "WINDOW_START": "2026-06-05T09:00:00.000Z",
    "WINDOW_END": "2026-06-05T10:00:00.000Z",
    "REPORTER_CONTACT": "a@example.com",
}


def create_service_area_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["AREA_NAME"],
        "code": DEFAULTS["AREA_CODE"],
        "season_start_date": DEFAULTS["SEASON_START_DATE"],
        "population": DEFAULTS["POPULATION"],
    }
    payload.update(overrides)
    return payload


def create_sensitive_site_payload(**overrides) -> dict:
    payload = {
        "site_type": "APIARY",
        "operator_name": DEFAULTS["OPERATOR_NAME"],
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
        "x_m": 960,
        "y_m": 1280,
    }
    payload.update(overrides)
    return payload


def create_trap_site_payload(**overrides) -> dict:
    payload = {
        "site_code": DEFAULTS["TRAP_SITE_CODE"],
        "trap_type": "CDC_LIGHT",
        "habitat": "URBAN",
        "x_m": 0,
        "y_m": 0,
    }
    payload.update(overrides)
    return payload


def create_trap_collection_payload(**overrides) -> dict:
    payload = {
        "collection_date": "2026-05-28",
        "trap_nights": 2,
        "female_count": 60,
        "species": "CULEX_PIPIENS",
    }
    payload.update(overrides)
    return payload


def create_lab_pool_payload(**overrides) -> dict:
    payload = {"pool_size": 50, "assay": "RT_PCR"}
    payload.update(overrides)
    return payload


def create_larval_inspection_payload(**overrides) -> dict:
    payload = {
        "inspection_date": "2026-05-26",
        "dips": 20,
        "larvae_count": 40,
        "habitat": "CATCH_BASIN",
    }
    payload.update(overrides)
    return payload


def create_weather_observation_payload(**overrides) -> dict:
    payload = {
        "obs_date": "2026-05-30",
        "tmax_c": 25.1,
        "tmin_c": 20.0,
        "rainfall_mm": 0.0,
    }
    payload.update(overrides)
    return payload


def create_risk_assessment_payload(expected_service_area_version, **overrides) -> dict:
    payload = {
        "as_of_date": "2026-06-01",
        "expected_service_area_version": expected_service_area_version,
    }
    payload.update(overrides)
    return payload


def create_pesticide_product_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["PRODUCT_NAME"],
        "epa_reg_no": DEFAULTS["EPA_REG_NO"],
        "active_ingredient": "BTI",
        "application_method": "LARVICIDE",
        "label_rate_ml_per_acre": 100.0,
        "reentry_interval_hours": 0,
        "cost_cents_per_liter": 4000,
        "received_total_ml": 100000.0,
    }
    payload.update(overrides)
    return payload


def create_applicator_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["APPLICATOR_NAME"],
        "license_no": DEFAULTS["LICENSE_NO"],
        "license_category": "AERIAL",
        "license_expires_on": DEFAULTS["LICENSE_EXPIRES_ON"],
    }
    payload.update(overrides)
    return payload


def create_treatment_plan_payload(service_area_id, trigger_assessment_id, **overrides) -> dict:
    payload = {
        "service_area_id": service_area_id,
        "trigger_assessment_id": trigger_assessment_id,
        "treatment_type": "LARVICIDE",
    }
    payload.update(overrides)
    return payload


def create_treatment_route_payload(applicator_id, pesticide_product_id, **overrides) -> dict:
    payload = {
        "applicator_id": applicator_id,
        "pesticide_product_id": pesticide_product_id,
        "route_code": DEFAULTS["ROUTE_CODE"],
        "window_start": DEFAULTS["WINDOW_START"],
        "window_end": DEFAULTS["WINDOW_END"],
        "planned_acres": 1.0,
        "center_x_m": 20000,
        "center_y_m": 20000,
    }
    payload.update(overrides)
    return payload


def create_notification_payload(sensitive_site_id, **overrides) -> dict:
    payload = {"sensitive_site_id": sensitive_site_id}
    payload.update(overrides)
    return payload


def create_service_request_payload(service_area_id, **overrides) -> dict:
    payload = {
        "service_area_id": service_area_id,
        "reporter_contact": DEFAULTS["REPORTER_CONTACT"],
        "category": "STANDING_WATER",
        "description": "Standing water in the alley behind the school",
        "x_m": 10,
        "y_m": 10,
    }
    payload.update(overrides)
    return payload


def create_stock_adjustment_payload(delta_ml, expected_product_version, **overrides) -> dict:
    payload = {
        "delta_ml": delta_ml,
        "reason": "Drum received from state depot",
        "expected_product_version": expected_product_version,
    }
    payload.update(overrides)
    return payload
