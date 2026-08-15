"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
from .constants import TEST_DEFAULTS as D


def create_customer_payload(**overrides) -> dict:
    """PRD §3.1 inputs: name + billing_email; the four commercial attributes
    are optional and omitted by default so server defaults apply."""
    defaults = {
        "name": "Acme Construction",
        "billing_email": "ap@acme.example",
    }
    defaults.update(overrides)
    return defaults


def create_site_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "name": "Houston Yard",
        "jurisdiction_code": D["SITE_JURISDICTION"],
        "fuel_tank_capacity_liters": D["SITE_TANK_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_equipment_unit_payload(**overrides) -> dict:
    """PRD §3.2 inputs for the canonical 200 kW TIER_4F generator."""
    defaults = {
        "unit_type": "GENERATOR",
        "capacity_kw": D["UNIT_CAPACITY_KW"],
        "fuel_type": "DIESEL",
        "emissions_tier": "TIER_4F",
        "nox_g_per_kwh": D["UNIT_NOX"],
        "day_rate_cents": D["UNIT_DAY_RATE"],
        "week_rate_cents": D["UNIT_WEEK_RATE"],
        "month_rate_cents": D["UNIT_MONTH_RATE"],
        "demob_fee_cents": D["UNIT_DEMOB_FEE"],
        "home_depot_code": D["UNIT_HOME_DEPOT"],
    }
    defaults.update(overrides)
    return defaults


def create_accessory_kit_payload(**overrides) -> dict:
    defaults = {
        "kit_code": D["KIT_CODE"],
        "description": "400A cable + distro kit",
        "max_ampacity_a": D["KIT_AMPACITY"],
        "day_rate_cents": D["KIT_DAY_RATE"],
        "week_rate_cents": D["KIT_WEEK_RATE"],
        "month_rate_cents": D["KIT_MONTH_RATE"],
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(customer_id, site_id, **overrides) -> dict:
    """PRD §3.3 inputs; default profile sizes to ceil(1.25*160) = 200 kW."""
    defaults = {
        "customer_id": customer_id,
        "site_id": site_id,
        "load_profile": [{"load_type": "CONTINUOUS", "nameplate_kw": D["LOAD_NAMEPLATE_KW"]}],
        "start_date": D["CONTRACT_START"],
        "expected_offhire_date": D["CONTRACT_END"],
    }
    defaults.update(overrides)
    return defaults


def create_equipment_line_payload(equipment_unit_id, expected_rental_contract_version) -> dict:
    """PRD §3.3 equipment line: unit id + OCC version; quantity stays 1."""
    return {
        "line_type": "EQUIPMENT",
        "equipment_unit_id": equipment_unit_id,
        "expected_rental_contract_version": expected_rental_contract_version,
    }


def create_kit_line_payload(accessory_kit_id, expected_rental_contract_version, quantity=1) -> dict:
    return {
        "line_type": "ACCESSORY_KIT",
        "accessory_kit_id": accessory_kit_id,
        "quantity": quantity,
        "expected_rental_contract_version": expected_rental_contract_version,
    }


def create_permit_payload(contract_id, permit_type="EMISSIONS") -> dict:
    return {"contract_id": contract_id, "permit_type": permit_type}


def create_service_visit_payload(contract_id, visit_type, **overrides) -> dict:
    """PRD §3.7 inputs; conditional fields supplied per visit_type via overrides."""
    defaults = {"visit_type": visit_type, "contract_id": contract_id}
    defaults.update(overrides)
    return defaults


def create_telemetry_event_payload(contract_id, event_type, value, **overrides) -> dict:
    defaults = {"contract_id": contract_id, "event_type": event_type, "value": value}
    defaults.update(overrides)
    return defaults


def create_incident_payload(contract_id, equipment_unit_id, incident_type, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "equipment_unit_id": equipment_unit_id,
        "incident_type": incident_type,
    }
    defaults.update(overrides)
    return defaults
