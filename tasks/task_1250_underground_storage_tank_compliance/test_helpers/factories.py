"""Payload factories — one per creatable resource, input fields only (PRD §3)."""

DEFAULTS = {
    "FACILITY_NAME": "Test Facility",
    "STATE_CODE": "CA",
    "FEES_PAID_THROUGH": "2027-01-01T00:00:00Z",
    "TANK_TAG": "T1",
    "SUBSTANCE": "DIESEL",
    "CAPACITY_GALLONS": 10000,
    "INSTALLED_ON": "2018-01-01T00:00:00Z",
    "TANK_CONSTRUCTION": "STEEL",
    "PIPING_TYPE": "PRESSURIZED",
    "RELEASE_DETECTION_MODE": "ATG_INVENTORY",
    "INSTALL_DATE": "2018-01-01T00:00:00Z",
    "SERIAL_NO": "SN-1",
    "TECH_NAME": "Field Tech",
    "DISCOVERED_AT": "2026-05-01T08:00:00Z",
    "SOURCE_DESCRIPTION": "interstitial alarm",
    "LINE_ITEMS": [{"description": "field work", "qty": 1, "unit_price_cents": 60000}],
}


def create_facility_payload(**overrides) -> dict:
    """Facility registration input (PRD §3.1). fund_program_election only when given."""
    payload = {
        "facility_name": DEFAULTS["FACILITY_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
        "annual_fee_paid_through": DEFAULTS["FEES_PAID_THROUGH"],
    }
    payload.update(overrides)
    return payload


def create_tank_payload(facility_id: str, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "tank_tag": DEFAULTS["TANK_TAG"],
        "substance": DEFAULTS["SUBSTANCE"],
        "capacity_gallons": DEFAULTS["CAPACITY_GALLONS"],
        "installed_on": DEFAULTS["INSTALLED_ON"],
        "tank_construction": DEFAULTS["TANK_CONSTRUCTION"],
        "piping_type": DEFAULTS["PIPING_TYPE"],
        "release_detection_mode": DEFAULTS["RELEASE_DETECTION_MODE"],
    }
    payload.update(overrides)
    return payload


def create_component_payload(tank_system_id: str, **overrides) -> dict:
    payload = {
        "tank_system_id": tank_system_id,
        "component_type": "CATHODIC_PROTECTION",
        "install_date": DEFAULTS["INSTALL_DATE"],
        "serial_no": DEFAULTS["SERIAL_NO"],
    }
    payload.update(overrides)
    return payload


def create_technician_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["TECH_NAME"],
        "endorsements": [],
        "trainer": False,
    }
    payload.update(overrides)
    return payload


def create_service_order_payload(facility_id: str, tank_system_id: str,
                                 service_type: str, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "tank_system_id": tank_system_id,
        "service_type": service_type,
        "line_items": list(DEFAULTS["LINE_ITEMS"]),
    }
    payload.update(overrides)
    return payload


def create_record_payload(tank_system_id: str, period_month: str, **overrides) -> dict:
    payload = {
        "tank_system_id": tank_system_id,
        "period_month": period_month,
        "readings_summary": {"log": "clean"},
    }
    payload.update(overrides)
    return payload


def create_submission_payload(facility_id: str, submission_type: str, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "submission_type": submission_type,
    }
    payload.update(overrides)
    return payload


def create_operator_payload(facility_id: str, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "full_name": "Site Operator",
        "operator_class": "A",
    }
    payload.update(overrides)
    return payload


def create_training_record_payload(operator_id: str, course_class: str, **overrides) -> dict:
    payload = {
        "operator_id": operator_id,
        "course_class": course_class,
        "completed_at": "2026-01-10T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_release_event_payload(facility_id: str, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "discovered_at": DEFAULTS["DISCOVERED_AT"],
        "source_description": DEFAULTS["SOURCE_DESCRIPTION"],
    }
    payload.update(overrides)
    return payload


def create_fund_claim_payload(facility_id: str, release_event_id: str, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "release_event_id": release_event_id,
        "expense_lines": [{"description": "cleanup", "amount_cents": 3000000}],
    }
    payload.update(overrides)
    return payload


# --- Readings factories (PRD §3.4 type-specific schemas) ---

def tightness_readings(leak_rate_gph: float = 0.05) -> dict:
    return {"leak_rate_gph": leak_rate_gph}


def lld_readings(detects_simulated_leak: bool = True) -> dict:
    return {"detects_simulated_leak": detects_simulated_leak}


def spill_readings(visual_cracks_found: bool = False,
                   drain_test_hold_minutes: int = 10,
                   overfill_activates_pct: float = 80.0) -> dict:
    return {
        "visual_cracks_found": visual_cracks_found,
        "drain_test_hold_minutes": drain_test_hold_minutes,
        "overfill_activates_pct": overfill_activates_pct,
    }


def cp_readings(instant_off_mv: int = -900, polarized_mv: int = -950,
                native_mv: int = -600, valid_contact: bool = True,
                criterion: str = "INSTANT_OFF") -> dict:
    return {
        "instant_off_mv": instant_off_mv,
        "polarized_mv": polarized_mv,
        "native_mv": native_mv,
        "valid_contact": valid_contact,
        "criterion": criterion,
    }


def cp_divergence_readings(criterion: str) -> dict:
    """Voltage triple that FAILs INSTANT_OFF (-800 > -850) and PASSes
    POLARIZATION_SHIFT (-500 - (-700) = 200 >= 100) (PRD §3.4)."""
    return cp_readings(instant_off_mv=-800, polarized_mv=-700, native_mv=-500,
                       valid_contact=True, criterion=criterion)
