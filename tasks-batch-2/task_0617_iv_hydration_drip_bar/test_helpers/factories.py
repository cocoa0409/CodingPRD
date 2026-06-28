"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "MENU_NAME": "Myers Cocktail",
    "MENU_TIER": "MYERS",
    "MENU_PRICE_CENTS": 17500,
    "ADDON_NAME": "Glutathione Push",
    "ADDON_CODE": "GLUTATHIONE",
    "ADDON_PRICE_CENTS": 4500,
    "PATIENT_NAME": "Test Patient",
    "PATIENT_DOB": "1990-01-01T00:00:00Z",
    "LOUNGE_NAME": "Test Lounge",
    "BAY_COUNT": 3,
    "NURSE_NAME": "Test Nurse",
    "LICENSE_NUMBER": "RN-0001",
    "START_AT": "2026-06-23T09:00:00Z",
    "DURATION_MINUTES": 60,
    "FAR_EXPIRY": "2026-12-31T00:00:00Z",
    "EFFECTIVE_FROM": "2026-06-01T00:00:00Z",
    "SERVICE_DATE": "2026-06-23T00:00:00Z",
    "TURNAROUND_MINUTES": 30,
}


def create_menu_item_payload(**overrides) -> dict:
    """POST /menu-items. requires_standing_order/g6pd_sensitive/active are
    server defaults (true/false/true) unless overridden."""
    defaults = {
        "name": DEFAULTS["MENU_NAME"],
        "tier": DEFAULTS["MENU_TIER"],
        "base_price_cents": DEFAULTS["MENU_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_add_on_payload(**overrides) -> dict:
    """POST /add-ons. active defaults to true server-side unless overridden."""
    defaults = {
        "name": DEFAULTS["ADDON_NAME"],
        "code": DEFAULTS["ADDON_CODE"],
        "price_cents": DEFAULTS["ADDON_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(**overrides) -> dict:
    """POST /patients. membership_id optional (null when absent)."""
    defaults = {
        "full_name": DEFAULTS["PATIENT_NAME"],
        "date_of_birth": DEFAULTS["PATIENT_DOB"],
    }
    defaults.update(overrides)
    return defaults


def create_membership_payload(**overrides) -> dict:
    """POST /memberships. drip_credits_total/addon_credits_total default 0."""
    defaults = {
        "tier": "PLATINUM",
        "covered_drip_tier": "MYERS",
        "drip_credits_total": 0,
        "addon_credits_total": 0,
    }
    defaults.update(overrides)
    return defaults


def create_standing_order_payload(**overrides) -> dict:
    """POST /standing-orders."""
    defaults = {
        "medical_director_user_id": "md-1",
        "covered_tier": "NAD",
        "effective_from": DEFAULTS["EFFECTIVE_FROM"],
        "expires_at": DEFAULTS["FAR_EXPIRY"],
    }
    defaults.update(overrides)
    return defaults


def create_nurse_payload(**overrides) -> dict:
    """POST /nurses. home_lounge_id optional; status defaults AVAILABLE."""
    defaults = {
        "full_name": DEFAULTS["NURSE_NAME"],
        "license_number": DEFAULTS["LICENSE_NUMBER"],
    }
    defaults.update(overrides)
    return defaults


def create_lounge_payload(**overrides) -> dict:
    """POST /lounges. open/close minute default 480/1200 server-side."""
    defaults = {
        "name": DEFAULTS["LOUNGE_NAME"],
        "bay_count": DEFAULTS["BAY_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_supply_lot_payload(**overrides) -> dict:
    """POST /supply-lots."""
    defaults = {
        "item_kind": "DRIP_BASE",
        "tier_or_code": "MYERS",
        "lot_number": "LOT-1",
        "units_total": 5,
        "expires_at": DEFAULTS["FAR_EXPIRY"],
    }
    defaults.update(overrides)
    return defaults


def create_dispatch_route_payload(nurse_id, **overrides) -> dict:
    """POST /dispatch-routes. turnaround_minutes defaults 30 server-side."""
    defaults = {
        "nurse_id": nurse_id,
        "service_date": DEFAULTS["SERVICE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(patient_id, menu_item_id, **overrides) -> dict:
    """POST /appointments. addon_ids default []; location_type LOUNGE here, so
    pass lounge_id. For MOBILE callers must drop lounge_id and set
    location_type=MOBILE. duration_minutes default 60; membership_id optional."""
    defaults = {
        "patient_id": patient_id,
        "menu_item_id": menu_item_id,
        "location_type": "LOUNGE",
        "start_at": DEFAULTS["START_AT"],
        "duration_minutes": DEFAULTS["DURATION_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_intake_payload(author_user_id="intake-1", **overrides) -> dict:
    """POST /appointments/{id}/intake. Five contraindication flags default false."""
    defaults = {"author_user_id": author_user_id}
    defaults.update(overrides)
    return defaults


def create_consent_payload(appointment_id, witness_user_id="wit-1",
                           signed_by_patient=True, **overrides) -> dict:
    """POST /consents."""
    defaults = {
        "appointment_id": appointment_id,
        "signed_by_patient": signed_by_patient,
        "witness_user_id": witness_user_id,
    }
    defaults.update(overrides)
    return defaults


def create_adverse_event_payload(appointment_id, reported_by_user_id,
                                 severity="MODERATE",
                                 description="flushing", **overrides) -> dict:
    """POST /adverse-events."""
    defaults = {
        "appointment_id": appointment_id,
        "reported_by_user_id": reported_by_user_id,
        "severity": severity,
        "description": description,
    }
    defaults.update(overrides)
    return defaults
