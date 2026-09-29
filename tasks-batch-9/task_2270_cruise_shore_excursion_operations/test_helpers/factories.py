"""Payload factories — one per creatable resource, input fields only.

Each factory returns the canonical request body used by the shared world setups
and accepts keyword overrides.  `without()` strips fields for omission tests.
"""

from .constants import INSTANTS

DEFAULTS = {
    "PORT_CODE": "COZ",
    "PORT_NAME": "Cozumel",
    "COUNTRY_CODE": "MX",
    "TENDER_PORT_CODE": "NASS",
    "TENDER_PORT_NAME": "Nassau",
    "TENDER_COUNTRY_CODE": "BS",
    "RISK_BUFFER_MINUTES": 30,
    "TENDER_EGRESS_MINUTES": 25,
    "MEETING_POINT_NAME": "Terminal Hall B",
    "MEETING_POINT_ZONE": "TERMINAL_HALL",
    "MAX_CONCURRENT_GROUPS": 4,
    "SLOT_BUFFER_MINUTES": 10,
    "VOYAGE_CODE": "V2609",
    "SHIP_CODE": "MS-AURORA",
    "OPERATOR_NAME": "Maya Reef Excursions",
    "OPERATOR_EMAIL": "ops@maya.example",
    "INSURANCE_LIMIT_CENTS": 100_000_000,
    "COMMISSION_RATE_BPS": 1800,
    "EXCURSION_TITLE": "Reef Snorkel",
    "DURATION_MINUTES": 300,
    "MIN_AGE": 18,
    "MOBILITY_LEVEL": "LEVEL_2",
    "LANGUAGES": ["EN", "ES"],
    "BASE_PRICE_CENTS": 12000,
    "PRICE_TIER": "PREMIUM",
    "DISPATCH_DWELL_MINUTES": 20,
    "TOTAL_CAPACITY": 40,
    "PRECRUISE_ALLOCATION": 25,
    "ONBOARD_ALLOCATION": 15,
    "GUEST_NAME": "Ada Reyes",
    "GUEST_BIRTH_DATE": "1985-04-02T00:00:00Z",
    "GUEST_MOBILITY_LEVEL": "FULL",
    "GUEST_LANGUAGE_PREF": "EN",
    "PARTY_SIZE": 2,
    "CHANNEL": "PRE_CRUISE",
    "LANGUAGE_CHOICE": "EN",
    "GUEST_CAPACITY": 100,
    "NARRATIVE": "Guest slipped on the wet tender pontoon while boarding.",
    "CLAIMED_AMOUNT_CENTS": 200000,
    "CLAIM_BASIS_CODE": "NEGLIGENCE",
}


def without(payload: dict, *fields: str) -> dict:
    """Copy of `payload` with the named fields removed."""
    return {k: v for k, v in payload.items() if k not in fields}


# --------------------------------------------------------------------------
# Ports and meeting points
# --------------------------------------------------------------------------

def create_port_payload(**overrides) -> dict:
    payload = {
        "port_code": DEFAULTS["PORT_CODE"],
        "name": DEFAULTS["PORT_NAME"],
        "country_code": DEFAULTS["COUNTRY_CODE"],
        "docking_mode": "ALONGSIDE",
        "risk_buffer_minutes": DEFAULTS["RISK_BUFFER_MINUTES"],
        "tender_egress_minutes": DEFAULTS["TENDER_EGRESS_MINUTES"],
    }
    payload.update(overrides)
    return payload


def create_tender_port_payload(**overrides) -> dict:
    payload = create_port_payload(
        port_code=DEFAULTS["TENDER_PORT_CODE"],
        name=DEFAULTS["TENDER_PORT_NAME"],
        country_code=DEFAULTS["TENDER_COUNTRY_CODE"],
        docking_mode="TENDER",
    )
    payload.update(overrides)
    return payload


def create_meeting_point_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["MEETING_POINT_NAME"],
        "zone": DEFAULTS["MEETING_POINT_ZONE"],
        "max_concurrent_groups": DEFAULTS["MAX_CONCURRENT_GROUPS"],
        "slot_buffer_minutes": DEFAULTS["SLOT_BUFFER_MINUTES"],
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Port calls and tender waves
# --------------------------------------------------------------------------

def create_port_call_payload(port_id: str, **overrides) -> dict:
    payload = {
        "port_id": port_id,
        "voyage_code": DEFAULTS["VOYAGE_CODE"],
        "ship_code": DEFAULTS["SHIP_CODE"],
        "arrival_utc": INSTANTS["CALL_ARRIVAL"],
        "all_aboard_utc": INSTANTS["CALL_ALL_ABOARD"],
        "departure_utc": INSTANTS["CALL_DEPARTURE"],
    }
    payload.update(overrides)
    return payload


def create_tender_wave_payload(**overrides) -> dict:
    payload = {
        "wave_index": 1,
        "window_start_utc": INSTANTS["WAVE1_START"],
        "window_end_utc": INSTANTS["WAVE1_END"],
        "guest_capacity": DEFAULTS["GUEST_CAPACITY"],
        "priority_class": "EXCURSION_PRIORITY",
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Operators and audits
# --------------------------------------------------------------------------

def create_operator_payload(port_id: str, **overrides) -> dict:
    payload = {
        "port_id": port_id,
        "legal_name": DEFAULTS["OPERATOR_NAME"],
        "contact_email": DEFAULTS["OPERATOR_EMAIL"],
        "insurance_expiry_date": INSTANTS["INSURANCE_EXPIRY"],
        "insurance_liability_limit_cents": DEFAULTS["INSURANCE_LIMIT_CENTS"],
        "commission_rate_bps": DEFAULTS["COMMISSION_RATE_BPS"],
    }
    payload.update(overrides)
    return payload


def create_safety_audit_payload(**overrides) -> dict:
    payload = {
        "audit_type": "INITIAL",
        "conducted_on": INSTANTS["AUDIT_CONDUCTED_ON"],
        "raw_score": 82,
        "critical_finding_count": 0,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Catalog and departures
# --------------------------------------------------------------------------

def create_excursion_payload(port_id: str, operator_id: str, **overrides) -> dict:
    payload = {
        "port_id": port_id,
        "operator_id": operator_id,
        "title": DEFAULTS["EXCURSION_TITLE"],
        "duration_minutes": DEFAULTS["DURATION_MINUTES"],
        "min_age": DEFAULTS["MIN_AGE"],
        "mobility_level": DEFAULTS["MOBILITY_LEVEL"],
        "languages": list(DEFAULTS["LANGUAGES"]),
        "base_price_cents": DEFAULTS["BASE_PRICE_CENTS"],
        "price_tier": DEFAULTS["PRICE_TIER"],
        "is_line_operated": False,
    }
    payload.update(overrides)
    return payload


def create_departure_payload(excursion_id: str, port_call_id: str,
                             meeting_point_id: str, **overrides) -> dict:
    payload = {
        "excursion_id": excursion_id,
        "port_call_id": port_call_id,
        "meeting_point_id": meeting_point_id,
        "meeting_time_utc": INSTANTS["MEETING_TIME"],
        "dispatch_dwell_minutes": DEFAULTS["DISPATCH_DWELL_MINUTES"],
        "total_capacity": DEFAULTS["TOTAL_CAPACITY"],
        "precruise_allocation": DEFAULTS["PRECRUISE_ALLOCATION"],
        "onboard_allocation": DEFAULTS["ONBOARD_ALLOCATION"],
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Guests and bookings
# --------------------------------------------------------------------------

def create_guest_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["GUEST_NAME"],
        "birth_date": DEFAULTS["GUEST_BIRTH_DATE"],
        "voyage_code": DEFAULTS["VOYAGE_CODE"],
        "mobility_level": DEFAULTS["GUEST_MOBILITY_LEVEL"],
        "language_pref": DEFAULTS["GUEST_LANGUAGE_PREF"],
    }
    payload.update(overrides)
    return payload


def create_booking_payload(departure_id: str, guest_id: str,
                           expected_departure_version: int, **overrides) -> dict:
    payload = {
        "departure_id": departure_id,
        "guest_id": guest_id,
        "party_size": DEFAULTS["PARTY_SIZE"],
        "channel": DEFAULTS["CHANNEL"],
        "language_choice": DEFAULTS["LANGUAGE_CHOICE"],
        "expected_departure_version": expected_departure_version,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Incidents, claims and statements
# --------------------------------------------------------------------------

def create_incident_payload(**overrides) -> dict:
    payload = {
        "category": "INJURY",
        "severity": "MODERATE",
        "occurred_utc": INSTANTS["MEETING_TIME"],
        "narrative": DEFAULTS["NARRATIVE"],
    }
    payload.update(overrides)
    return payload


def create_claim_payload(**overrides) -> dict:
    payload = {
        "claimed_amount_cents": DEFAULTS["CLAIMED_AMOUNT_CENTS"],
        "basis_code": DEFAULTS["CLAIM_BASIS_CODE"],
    }
    payload.update(overrides)
    return payload


def create_statement_payload(operator_id: str, port_call_id: str,
                             expected_operator_version: int,
                             basis: str = "PROVISIONAL", **overrides) -> dict:
    payload = {
        "operator_id": operator_id,
        "port_call_id": port_call_id,
        "basis": basis,
        "expected_operator_version": expected_operator_version,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Which body fields the PRD declares mandatory (fields carrying a documented
# default are optional and must NOT be tested as required).
# --------------------------------------------------------------------------

REQUIRED_FIELDS = {
    "port": ["port_code", "name", "country_code", "docking_mode"],
    "meeting_point": ["name", "zone", "max_concurrent_groups"],
    "port_call": ["port_id", "voyage_code", "ship_code", "arrival_utc",
                  "all_aboard_utc", "departure_utc"],
    "tender_wave": ["wave_index", "window_start_utc", "window_end_utc",
                    "guest_capacity", "priority_class"],
    "operator": ["port_id", "legal_name", "contact_email", "insurance_expiry_date",
                 "insurance_liability_limit_cents", "commission_rate_bps"],
    "safety_audit": ["audit_type", "conducted_on", "raw_score",
                     "critical_finding_count"],
    "excursion": ["port_id", "operator_id", "title", "duration_minutes", "min_age",
                  "mobility_level", "languages", "base_price_cents", "price_tier",
                  "is_line_operated"],
    "departure": ["excursion_id", "port_call_id", "meeting_point_id",
                  "meeting_time_utc", "dispatch_dwell_minutes", "total_capacity",
                  "precruise_allocation", "onboard_allocation"],
    "guest": ["full_name", "birth_date", "voyage_code", "mobility_level",
              "language_pref"],
    "booking": ["departure_id", "guest_id", "party_size", "channel",
                "language_choice", "expected_departure_version"],
    "incident": ["category", "severity", "occurred_utc", "narrative"],
    "claim": ["claimed_amount_cents", "basis_code"],
    "statement": ["operator_id", "port_call_id", "basis",
                  "expected_operator_version"],
}

OPTIONAL_FIELDS = {
    "port": ["risk_buffer_minutes", "tender_egress_minutes"],
    "meeting_point": ["slot_buffer_minutes"],
    "excursion": ["max_age", "medical_warning_codes", "alternative_excursion_id"],
    "guest": ["medical_flags", "loyalty_tier"],
    "booking": ["medical_warning_acknowledged"],
}
