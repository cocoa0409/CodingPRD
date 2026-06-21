"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "TERRITORY_NAME": "ter",
    "ZIP": "33101",
    "TRAVEL_BUFFER": 30,
    "FS_LABEL": "fs",
    "BASE_RATE": 15000,
    "TIER1_RATE": 12,
    "TIER2_RATE": 8,
    "TIER3_RATE": 5,
    "ADDON_RADON": 9900,
    "ADDON_TERMITE": 8500,
    "ADDON_SEWER": 12000,
    "INSPECTOR_NAME": "Ina",
    "CAPACITY": 480,
    "CLIENT_NAME": "Cli",
    "CLIENT_EMAIL": "cli@x.com",
    "AGENT_NAME": "Agt",
    "AGENT_EMAIL": "agt@x.com",
    "BROKERAGE": "BrkX",
    "ADDRESS": "1 A St",
    "SQFT": 2200,
    "YEAR_BUILT": 1990,
}


def create_territory_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["TERRITORY_NAME"],
        "zip_codes": [DEFAULTS["ZIP"]],
        "travel_buffer_minutes": DEFAULTS["TRAVEL_BUFFER"],
    }
    defaults.update(overrides)
    return defaults


def create_fee_schedule_payload(**overrides) -> dict:
    defaults = {
        "label": DEFAULTS["FS_LABEL"],
        "base_rate_cents": DEFAULTS["BASE_RATE"],
        "tier1_rate_cents_per_sqft": DEFAULTS["TIER1_RATE"],
        "tier2_rate_cents_per_sqft": DEFAULTS["TIER2_RATE"],
        "tier3_rate_cents_per_sqft": DEFAULTS["TIER3_RATE"],
        "addon_radon_cents": DEFAULTS["ADDON_RADON"],
        "addon_termite_cents": DEFAULTS["ADDON_TERMITE"],
        "addon_sewer_cents": DEFAULTS["ADDON_SEWER"],
    }
    defaults.update(overrides)
    return defaults


def create_inspector_payload(territory_id, certifications=None, **overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["INSPECTOR_NAME"],
        "territory_id": territory_id,
        "certifications": certifications if certifications is not None else ["BUYER"],
        "daily_capacity_minutes": DEFAULTS["CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_client_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["CLIENT_NAME"],
        "email": DEFAULTS["CLIENT_EMAIL"],
        "role_in_deal": "BUYER",
    }
    defaults.update(overrides)
    return defaults


def create_agent_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["AGENT_NAME"],
        "email": DEFAULTS["AGENT_EMAIL"],
        "brokerage": DEFAULTS["BROKERAGE"],
    }
    defaults.update(overrides)
    return defaults


def create_property_payload(**overrides) -> dict:
    defaults = {
        "address_line": DEFAULTS["ADDRESS"],
        "zip_code": DEFAULTS["ZIP"],
        "square_footage": DEFAULTS["SQFT"],
        "year_built": DEFAULTS["YEAR_BUILT"],
    }
    defaults.update(overrides)
    return defaults


def create_inspection_order_payload(property_id, client_id, agent_id,
                                     fee_schedule_id, inspection_type="BUYER",
                                     **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "client_id": client_id,
        "agent_id": agent_id,
        "fee_schedule_id": fee_schedule_id,
        "inspection_type": inspection_type,
    }
    defaults.update(overrides)
    return defaults


def schedule_order_payload(inspector_id, scheduled_start, **overrides) -> dict:
    defaults = {"inspector_id": inspector_id, "scheduled_start": scheduled_start}
    defaults.update(overrides)
    return defaults


def pay_order_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def reinspect_order_payload(inspector_id, scheduled_start, expected_order_version,
                            **overrides) -> dict:
    defaults = {
        "inspector_id": inspector_id,
        "scheduled_start": scheduled_start,
        "expected_order_version": expected_order_version,
    }
    defaults.update(overrides)
    return defaults


def create_addon_payload(kind, **overrides) -> dict:
    defaults = {"kind": kind}
    defaults.update(overrides)
    return defaults


def create_report_payload(measured_square_footage, **overrides) -> dict:
    defaults = {"measured_square_footage": measured_square_footage}
    defaults.update(overrides)
    return defaults


def create_defect_payload(location, severity, **overrides) -> dict:
    defaults = {"location": location, "severity": severity}
    defaults.update(overrides)
    return defaults
