"""Payload factories — one per entity, input fields only (PRD §3/§4)."""
import itertools

_counter = itertools.count(9000)

DEFAULTS = {
    "LEGAL_NAME": "Acme Hazmat LLC",
    "FLEET_SIZE": 5,
    "VERIFIED_FLEET_SIZE": 5,
    "PSN": "FLAMMABLE LIQUID, N.O.S.",
    "ERG_GUIDE": "128",
    "SPEC_CODE": "UN4G",
    "MAX_NET_QUANTITY_KG": 500.0,
    "QUANTITY_KG": 100.0,
    "DECLARED_VALUE_CENTS": 1000,
    "EMERGENCY_PHONE": "+1-800-555-0100",
    "EMERGENCY_SUMMARY": "Isolate 25m",
    "ENDORSEMENT_EXPIRES": "2027-01-01T00:00:00Z",
    "ROUTE_EFFECTIVE_FROM": "2026-01-01T00:00:00Z",
    "ROUTE_EFFECTIVE_TO": "2027-12-31T00:00:00Z",
    "PLAN_EFFECTIVE_FROM": "2026-01-01T00:00:00Z",
    "PLAN_EFFECTIVE_TO": "2027-12-31T00:00:00Z",
    "LOAD_DEPARTURE": "2026-05-10T08:00:00Z",
    "LOAD_ARRIVAL": "2026-05-10T12:00:00Z",
}


def _seq() -> int:
    return next(_counter)


def create_carrier_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "legal_name": f"{DEFAULTS['LEGAL_NAME']} {n}",
        "usdot_number": f"USDOT-{n}",
        "fleet_size_declared": DEFAULTS["FLEET_SIZE"],
        "hazmat_categories": ["FLAMMABLE_LIQUID"],
        "accepts_dangerous_placard_substitution": False,
    }
    defaults.update(overrides)
    return defaults


def create_security_plan_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "plan_name": f"PLAN-{n}",
        "coverage_categories": ["FLAMMABLE_LIQUID"],
        "effective_from": DEFAULTS["PLAN_EFFECTIVE_FROM"],
        "effective_to": DEFAULTS["PLAN_EFFECTIVE_TO"],
    }
    defaults.update(overrides)
    return defaults


def create_material_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "un_na_number": f"UN{n}",
        "proper_shipping_name": DEFAULTS["PSN"],
        "hazard_class": "CLASS_3",
        "packing_group": "PG_II",
        "placard_table": "TABLE_2",
        "transport_category": "FLAMMABLE_LIQUID",
        "reportable_quantity_lbs": 100,
        "is_inhalation_hazard": False,
        "segregation_group": "SG_NONE",
        "erg_guide_number": DEFAULTS["ERG_GUIDE"],
    }
    defaults.update(overrides)
    return defaults


def create_packaging_spec_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "spec_code": f"UN4G-{n}",
        "authorized_hazard_classes": ["CLASS_3"],
        "max_packing_group": "PG_II",
        "max_net_quantity_kg": DEFAULTS["MAX_NET_QUANTITY_KG"],
    }
    defaults.update(overrides)
    return defaults


def create_driver_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "full_name": f"Dana Roe {n}",
        "cdl_number": f"CDL-{n}",
        "hazmat_endorsement_expires_at": DEFAULTS["ENDORSEMENT_EXPIRES"],
    }
    defaults.update(overrides)
    return defaults


def create_training_record_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "training_type": "INITIAL",
        "completed_at": "2026-04-01T00:00:00Z",
        "certificate_code": f"CERT-{n}",
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "plate_number": f"PLT-{n}",
        "vehicle_class": "VAN",
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(material_id: str, packaging_spec_id: str, **overrides) -> dict:
    defaults = {
        "material_id": material_id,
        "packaging_spec_id": packaging_spec_id,
        "declared_shipping_name": DEFAULTS["PSN"],
        "quantity_kg": DEFAULTS["QUANTITY_KG"],
        "declared_value_cents": DEFAULTS["DECLARED_VALUE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_shipping_paper_payload(**overrides) -> dict:
    defaults = {
        "emergency_contact_phone": DEFAULTS["EMERGENCY_PHONE"],
        "emergency_response_summary": DEFAULTS["EMERGENCY_SUMMARY"],
        "shipper_certification_signed": True,
    }
    defaults.update(overrides)
    return defaults


def create_load_payload(route_id: str, **overrides) -> dict:
    defaults = {
        "route_id": route_id,
        "planned_departure_at": DEFAULTS["LOAD_DEPARTURE"],
        "planned_arrival_at": DEFAULTS["LOAD_ARRIVAL"],
    }
    defaults.update(overrides)
    return defaults


def create_route_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "route_code": f"R-{n}",
        "allowed_hazard_classes": ["CLASS_3"],
        "is_restricted_corridor": False,
        "effective_from": DEFAULTS["ROUTE_EFFECTIVE_FROM"],
        "effective_to": DEFAULTS["ROUTE_EFFECTIVE_TO"],
    }
    defaults.update(overrides)
    return defaults


def create_incident_report_payload(**overrides) -> dict:
    defaults = {
        "occurred_at": "2026-05-02T00:00:00Z",
        "severity": "MINOR",
    }
    defaults.update(overrides)
    return defaults
