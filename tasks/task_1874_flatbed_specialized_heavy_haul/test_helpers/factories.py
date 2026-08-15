"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "COMPANY_NAME": "Test Shipper Co",
    "CREDIT_LIMIT_CENTS": 100_000_000,
    "CARGO_DESCRIPTION": "Crated machinery",
    "GROSS_WEIGHT_LBS": 40000,
    "WIDTH_IN": 100,
    "HEIGHT_IN": 50,
    "LENGTH_IN": 400,
    "ORIGIN": "Portland OR",
    "DESTINATION": "Eugene OR",
    "TRAILER_TYPE": "FLATBED",
    "TRAILER_AXLE_COUNT": 2,
    "DRIVER_NAME": "T. Driver",
    "DRIVER_OVERSIZE_ENDORSED": False,
    "ROUTE_MILES": 100,
    "STATES_CROSSED": ["OR"],
    "MIN_BRIDGE_CLEARANCE_IN": 200,
    "MAX_BRIDGE_WEIGHT_LBS": 80000,
    "SECUREMENT_METHOD": "CHAINS",
    "TIEDOWN_COUNT": 4,
    "WLL_PER_TIEDOWN_LBS": 15000,
    "PROVIDER_NAME": "Test Pilot Co",
    "ESCORT_RATE_CENTS": 12000,
    "CRANE_ID": "CRANE-A",
    "FINE_AMOUNT_CENTS": 30000,
    "FINE_DESCRIPTION": "Deck damage during loading",
}


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "company_name": DEFAULTS["COMPANY_NAME"],
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_load_payload(**overrides) -> dict:
    defaults = {
        "cargo_description": DEFAULTS["CARGO_DESCRIPTION"],
        "gross_weight_lbs": DEFAULTS["GROSS_WEIGHT_LBS"],
        "width_in": DEFAULTS["WIDTH_IN"],
        "height_in": DEFAULTS["HEIGHT_IN"],
        "length_in": DEFAULTS["LENGTH_IN"],
        "origin": DEFAULTS["ORIGIN"],
        "destination": DEFAULTS["DESTINATION"],
    }
    defaults.update(overrides)
    return defaults


def plan_load_payload(**overrides) -> dict:
    defaults = {
        "trailer_type": DEFAULTS["TRAILER_TYPE"],
        "trailer_axle_count": DEFAULTS["TRAILER_AXLE_COUNT"],
        "driver_name": DEFAULTS["DRIVER_NAME"],
        "driver_oversize_endorsed": DEFAULTS["DRIVER_OVERSIZE_ENDORSED"],
    }
    defaults.update(overrides)
    return defaults


def survey_load_payload(**overrides) -> dict:
    defaults = {
        "route_miles": DEFAULTS["ROUTE_MILES"],
        "states_crossed": list(DEFAULTS["STATES_CROSSED"]),
        "min_bridge_clearance_in": DEFAULTS["MIN_BRIDGE_CLEARANCE_IN"],
        "max_bridge_weight_lbs": DEFAULTS["MAX_BRIDGE_WEIGHT_LBS"],
    }
    defaults.update(overrides)
    return defaults


def create_securement_plan_payload(**overrides) -> dict:
    defaults = {
        "method": DEFAULTS["SECUREMENT_METHOD"],
        "tiedown_count": DEFAULTS["TIEDOWN_COUNT"],
        "wll_per_tiedown_lbs": DEFAULTS["WLL_PER_TIEDOWN_LBS"],
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(state_code="CA", permit_type="OVERSIZE",
                          expected_load_version=1, **overrides) -> dict:
    defaults = {
        "state_code": state_code,
        "permit_type": permit_type,
        "expected_load_version": expected_load_version,
    }
    defaults.update(overrides)
    return defaults


def grant_permit_payload(**overrides) -> dict:
    defaults = {
        "travel_window_start": "2026-08-10T00:00:00Z",
        "travel_window_end": "2026-08-20T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def deny_permit_payload(**overrides) -> dict:
    defaults = {"denial_reason": "route study required"}
    defaults.update(overrides)
    return defaults


def create_escort_booking_payload(expected_load_version=1, **overrides) -> dict:
    defaults = {
        "provider_name": DEFAULTS["PROVIDER_NAME"],
        "position": "REAR",
        "scheduled_start": "2026-08-12T08:00:00Z",
        "scheduled_end": "2026-08-12T12:00:00Z",
        "rate_per_hour_cents": DEFAULTS["ESCORT_RATE_CENTS"],
        "expected_load_version": expected_load_version,
    }
    defaults.update(overrides)
    return defaults


def create_crane_appointment_payload(site="ORIGIN", crane_id=None, **overrides) -> dict:
    defaults = {
        "site": site,
        "crane_id": crane_id or DEFAULTS["CRANE_ID"],
        "window_start": "2026-08-12T06:00:00Z",
        "window_end": "2026-08-12T08:00:00Z",
    }
    if site == "DESTINATION":
        defaults["crane_id"] = crane_id or "CRANE-B"
        defaults["window_start"] = "2026-08-13T06:00:00Z"
        defaults["window_end"] = "2026-08-13T08:00:00Z"
    defaults.update(overrides)
    return defaults


def create_delay_event_payload(**overrides) -> dict:
    defaults = {
        "kind": "CUSTOMER_DELAY",
        "started_at": "2026-08-12T11:00:00Z",
        "ended_at": "2026-08-12T13:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_scale_ticket_payload(**overrides) -> dict:
    defaults = {
        "measured_gross_lbs": 40500,
        "weighed_at": "2026-08-12T07:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_fine_payload(**overrides) -> dict:
    defaults = {
        "kind": "DAMAGE",
        "amount_cents": DEFAULTS["FINE_AMOUNT_CENTS"],
        "description": DEFAULTS["FINE_DESCRIPTION"],
    }
    defaults.update(overrides)
    return defaults


def resolve_fine_payload(resolution="CUSTOMER_LIABLE", **overrides) -> dict:
    defaults = {"resolution": resolution}
    defaults.update(overrides)
    return defaults
