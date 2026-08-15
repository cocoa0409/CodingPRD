"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "GROUP_NAME": "Riverkeepers",
    "ORG_TYPE": "CIVIC",
    "CONTACT_NAME": "Gina Lead",
    "CONTACT_EMAIL": "gina@riverkeepers.org",
    "ROUTE_NAME": "River Rd",
    "MILE_START": 4.0,
    "MILE_END": 6.0,
    "SEGMENT_TYPE": "RIVERBANK",
    "SCHEDULED_DATE": "2026-09-10",
    "EXPECTED_VOLUNTEERS": 2,
    "ADULT_DOB": "1990-05-01",
    "VOLUNTEER_NAME": "Ada Adult",
    "DEPOT_NAME": "Central Depot",
    "BAGS": 500,
    "VESTS": 100,
    "GRABBERS": 50,
    "HAZARD_TYPE": "CHEMICAL_CONTAINER",
    "HAZARD_DESCRIPTION": "rusted drum",
    "HAZARD_LOCATION": "MP 5.1 north bank",
    "SIGN_TEXT": "Riverkeepers of Maple County",
    "RESOLUTION_NOTE": "crew removed and disposed",
}


def create_group_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["GROUP_NAME"],
        "org_type": DEFAULTS["ORG_TYPE"],
        "contact_name": DEFAULTS["CONTACT_NAME"],
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_segment_payload(**overrides) -> dict:
    defaults = {
        "route_name": DEFAULTS["ROUTE_NAME"],
        "mile_marker_start": DEFAULTS["MILE_START"],
        "mile_marker_end": DEFAULTS["MILE_END"],
        "segment_type": DEFAULTS["SEGMENT_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(group_id, segment_id, **overrides) -> dict:
    defaults = {
        "group_id": group_id,
        "segment_id": segment_id,
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_event_payload(agreement_id, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "scheduled_date": DEFAULTS["SCHEDULED_DATE"],
        "expected_volunteers": DEFAULTS["EXPECTED_VOLUNTEERS"],
    }
    defaults.update(overrides)
    return defaults


def create_waiver_payload(agreement_id, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "volunteer_full_name": DEFAULTS["VOLUNTEER_NAME"],
        "dob": DEFAULTS["ADULT_DOB"],
    }
    defaults.update(overrides)
    return defaults


def create_depot_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["DEPOT_NAME"],
        "bags_on_hand": DEFAULTS["BAGS"],
        "vests_on_hand": DEFAULTS["VESTS"],
        "grabbers_on_hand": DEFAULTS["GRABBERS"],
    }
    defaults.update(overrides)
    return defaults


def create_hazard_payload(segment_id, **overrides) -> dict:
    defaults = {
        "segment_id": segment_id,
        "hazard_type": DEFAULTS["HAZARD_TYPE"],
        "description": DEFAULTS["HAZARD_DESCRIPTION"],
        "location_note": DEFAULTS["HAZARD_LOCATION"],
    }
    defaults.update(overrides)
    return defaults


def create_sign_payload(**overrides) -> dict:
    defaults = {"sign_text": DEFAULTS["SIGN_TEXT"]}
    defaults.update(overrides)
    return defaults


def estimated_report_payload(bag_count=2, material_type="GENERAL_TRASH") -> dict:
    return {
        "weight_method": "ESTIMATED",
        "material_lines": [{"material_type": material_type, "bag_count": bag_count}],
    }
