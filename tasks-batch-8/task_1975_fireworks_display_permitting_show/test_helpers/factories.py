"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "LEGAL_NAME": "Pyro Co",
    "ATF_LICENSE_NUMBER": "ATF-001",
    "LICENSE_CLASS": "DISPLAY_1_3G",
    "LICENSE_VALID_FROM": "2026-01-01T00:00:00Z",
    "LICENSE_EXPIRES_AT": "2027-01-01T00:00:00Z",
    "CERT_EXPIRES_AT": "2027-06-01T00:00:00Z",
    "VENUE_ID": "VEN-1",
    "VENUE_NAME": "Fairgrounds",
    "SHOW_START": "2026-09-01T20:00:00Z",
    "SHOW_END": "2026-09-01T23:00:00Z",
    "DECLARED_DIAMETER_IN": 4,
    "DIAGRAM_REF": "D1",
    "LAUNCH_W_FT": 200,
    "LAUNCH_L_FT": 200,
    "BOUNDARY_FT": 300,
    "ARC_CENTER_DEG": 0,
    "STRUCTURE_FT": 500,
    "STANDBY_ENGINES": 1,
    "MAGAZINE_NAME": "MAG-1",
    "MAGAZINE_PERMIT": "P-1",
    "MAGAZINE_TYPE": "OUTDOOR",
    "MAGAZINE_CAPACITY_LBS": 100.00,
    "INSPECTION_DUE_AT": "2027-01-01T00:00:00Z",
    "PRODUCT_NAME": "Shell 4in",
    "UN_NUMBER": "UN0335",
    "SHELL_DIAMETER_IN": 4,
    "QUANTITY_UNITS": 50,
    "NEW_PER_UNIT_LBS": 0.50,
    "LOT_NUMBER": "L1",
    "DRIVER_NAME": "Dan",
    "VEHICLE_PLACARD": "1.3G",
    "POST_LABEL": "N",
    "ARC_DEGREES": 45,
    "POST_RADIUS_FT": 300,
    "GUARD_COMPANY": "SEC",
}


def create_operator_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "atf_license_number": DEFAULTS["ATF_LICENSE_NUMBER"],
        "license_class": DEFAULTS["LICENSE_CLASS"],
        "license_valid_from": DEFAULTS["LICENSE_VALID_FROM"],
        "license_expires_at": DEFAULTS["LICENSE_EXPIRES_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_crew_member_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Lee",
        "cert_level": "LEAD_OPERATOR",
        "cert_expires_at": DEFAULTS["CERT_EXPIRES_AT"],
        "hazmat_endorsed": True,
    }
    defaults.update(overrides)
    return defaults


def create_display_payload(**overrides) -> dict:
    defaults = {
        "venue_id": DEFAULTS["VENUE_ID"],
        "venue_name": DEFAULTS["VENUE_NAME"],
        "scheduled_start_at": DEFAULTS["SHOW_START"],
        "scheduled_end_at": DEFAULTS["SHOW_END"],
        "declared_max_shell_diameter_in": DEFAULTS["DECLARED_DIAMETER_IN"],
    }
    defaults.update(overrides)
    return defaults


def create_site_plan_payload(expected_display_event_version, **overrides) -> dict:
    defaults = {
        "diagram_ref": DEFAULTS["DIAGRAM_REF"],
        "launch_area_width_ft": DEFAULTS["LAUNCH_W_FT"],
        "launch_area_length_ft": DEFAULTS["LAUNCH_L_FT"],
        "spectator_boundary_ft": DEFAULTS["BOUNDARY_FT"],
        "spectator_arc_center_deg": DEFAULTS["ARC_CENTER_DEG"],
        "nearest_structure_ft": DEFAULTS["STRUCTURE_FT"],
        "expected_display_event_version": expected_display_event_version,
    }
    defaults.update(overrides)
    return defaults


def create_permit_application_payload(site_plan_id, **overrides) -> dict:
    defaults = {
        "site_plan_id": site_plan_id,
        "standby_engines": DEFAULTS["STANDBY_ENGINES"],
    }
    defaults.update(overrides)
    return defaults


def create_magazine_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["MAGAZINE_NAME"],
        "atf_magazine_permit": DEFAULTS["MAGAZINE_PERMIT"],
        "magazine_type": DEFAULTS["MAGAZINE_TYPE"],
        "capacity_new_lbs": DEFAULTS["MAGAZINE_CAPACITY_LBS"],
        "inspection_due_at": DEFAULTS["INSPECTION_DUE_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_batch_payload(**overrides) -> dict:
    defaults = {
        "product_name": DEFAULTS["PRODUCT_NAME"],
        "un_number": DEFAULTS["UN_NUMBER"],
        "shell_diameter_in": DEFAULTS["SHELL_DIAMETER_IN"],
        "quantity_units": DEFAULTS["QUANTITY_UNITS"],
        "new_per_unit_lbs": DEFAULTS["NEW_PER_UNIT_LBS"],
        "lot_number": DEFAULTS["LOT_NUMBER"],
    }
    defaults.update(overrides)
    return defaults


def create_checkout_payload(display_event_id, quantity, **overrides) -> dict:
    defaults = {
        "movement_type": "CHECK_OUT",
        "quantity": quantity,
        "display_event_id": display_event_id,
        "driver_name": DEFAULTS["DRIVER_NAME"],
        "vehicle_placard": DEFAULTS["VEHICLE_PLACARD"],
        "cdl_hazmat_endorsed": True,
    }
    defaults.update(overrides)
    return defaults


def create_return_payload(display_event_id, quantity, **overrides) -> dict:
    defaults = {
        "movement_type": "RETURN",
        "quantity": quantity,
        "display_event_id": display_event_id,
    }
    defaults.update(overrides)
    return defaults


def create_expend_payload(display_event_id, quantity, **overrides) -> dict:
    defaults = {
        "movement_type": "EXPEND",
        "quantity": quantity,
        "display_event_id": display_event_id,
    }
    defaults.update(overrides)
    return defaults


def create_weather_reading_payload(**overrides) -> dict:
    defaults = {
        "wind_speed_mph": 5.0,
        "gust_mph": 12.0,
        "wind_direction_deg": 180,
        "precipitation": False,
        "source": "NWS",
    }
    defaults.update(overrides)
    return defaults


def create_security_post_payload(**overrides) -> dict:
    defaults = {
        "post_label": DEFAULTS["POST_LABEL"],
        "arc_degrees": DEFAULTS["ARC_DEGREES"],
        "radius_ft": DEFAULTS["POST_RADIUS_FT"],
    }
    defaults.update(overrides)
    return defaults


def create_assign_payload(guard_name, **overrides) -> dict:
    defaults = {
        "guard_name": guard_name,
        "guard_company": DEFAULTS["GUARD_COMPANY"],
    }
    defaults.update(overrides)
    return defaults


def create_misfire_payload(product_batch_id, **overrides) -> dict:
    defaults = {
        "product_batch_id": product_batch_id,
        "shell_description": "dud",
    }
    defaults.update(overrides)
    return defaults


def create_sweep_payload(**overrides) -> dict:
    defaults = {
        "sweep_type": "NIGHT_SWEEP",
        "area_clear": True,
    }
    defaults.update(overrides)
    return defaults


def create_incident_payload(**overrides) -> dict:
    defaults = {
        "incident_type": "PROPERTY_DAMAGE",
        "severity": "MINOR",
        "description": "scorched grass",
    }
    defaults.update(overrides)
    return defaults


def create_standby_confirm_payload(**overrides) -> dict:
    defaults = {"standby_engines_on_site": DEFAULTS["STANDBY_ENGINES"]}
    defaults.update(overrides)
    return defaults


def create_go_no_go_payload(decision, expected_display_event_version) -> dict:
    return {
        "decision": decision,
        "expected_display_event_version": expected_display_event_version,
    }
