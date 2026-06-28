"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "PANEL_CODE": "CMP14",
    "PANEL_NAME": "Comprehensive Metabolic",
    "REQUIRED_TUBE_COUNT": 3,
    "BASE_LAB_FEE_CENTS": 4000,
    "PARTNER_NAME": "Quest",
    "COURIER_SLA_HOURS": 24,
    "STAT_SURCHARGE_CENTS": 1500,
    "TERRITORY": "SF_BAY",
    "PHLEB_NAME": "Pat Phleb",
    "SERVICE_DATE": "2026-02-01",
    "SHIFT_START": "2026-02-01T08:00:00Z",
    "SHIFT_END": "2026-02-01T18:00:00Z",
    "STOP_CAPACITY": 10,
    "PATIENT_NAME": "Sam Patient",
    "WINDOW_START": "2026-02-01T09:00:00Z",
    "WINDOW_END": "2026-02-01T09:30:00Z",
    "KIT_LOT": "LOT1",
}


def create_test_panel_payload(**overrides) -> dict:
    payload = {
        "panel_code": DEFAULTS["PANEL_CODE"],
        "name": DEFAULTS["PANEL_NAME"],
        "required_tube_count": DEFAULTS["REQUIRED_TUBE_COUNT"],
        "base_lab_fee_cents": DEFAULTS["BASE_LAB_FEE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_lab_partner_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["PARTNER_NAME"],
        "courier_sla_hours": DEFAULTS["COURIER_SLA_HOURS"],
        "accepted_panel_codes": [DEFAULTS["PANEL_CODE"]],
    }
    payload.update(overrides)
    return payload


def create_phlebotomist_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["PHLEB_NAME"],
        "territory_code": DEFAULTS["TERRITORY"],
    }
    payload.update(overrides)
    return payload


def create_route_day_payload(**overrides) -> dict:
    payload = {
        "territory_code": DEFAULTS["TERRITORY"],
        "service_date": DEFAULTS["SERVICE_DATE"],
        "shift_start_utc": DEFAULTS["SHIFT_START"],
        "shift_end_utc": DEFAULTS["SHIFT_END"],
        "stop_capacity": DEFAULTS["STOP_CAPACITY"],
    }
    payload.update(overrides)
    return payload


def create_lab_order_payload(**overrides) -> dict:
    payload = {
        "patient_full_name": DEFAULTS["PATIENT_NAME"],
        "patient_territory_code": DEFAULTS["TERRITORY"],
        "panel_code": DEFAULTS["PANEL_CODE"],
        "billing_mode": "SELF_PAY",
    }
    # lab_partner_id is required and supplied by the caller via overrides.
    payload.update(overrides)
    return payload


def book_appointment_payload(route_day_id, expected_route_day_version, **overrides) -> dict:
    payload = {
        "route_day_id": route_day_id,
        "window_start_utc": DEFAULTS["WINDOW_START"],
        "window_end_utc": DEFAULTS["WINDOW_END"],
        "expected_route_day_version": expected_route_day_version,
    }
    payload.update(overrides)
    return payload


def assign_kit_payload(**overrides) -> dict:
    payload = {
        "kit_lot_number": DEFAULTS["KIT_LOT"],
        "tube_count": DEFAULTS["REQUIRED_TUBE_COUNT"],
    }
    payload.update(overrides)
    return payload


def collect_specimen_payload(tube_label, **overrides) -> dict:
    payload = {"tube_label": tube_label}
    payload.update(overrides)
    return payload


def create_manifest_payload(lab_partner_id, **overrides) -> dict:
    payload = {
        "lab_partner_id": lab_partner_id,
        "territory_code": DEFAULTS["TERRITORY"],
    }
    payload.update(overrides)
    return payload


def post_results_payload(**overrides) -> dict:
    payload = {"result_value": "ok"}
    payload.update(overrides)
    return payload
