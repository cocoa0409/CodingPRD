"""Payload factories — one per entity, input fields only.

Counter-based suffixes guarantee that employee_codes and pairing_codes are
unique within a single test (each test sees an empty DB, so a per-test
counter is enough).
"""
import itertools


# A module-level counter — each test starts against an empty DB, but the
# counter persists across tests in the same process. We only need uniqueness
# within a single test run, so the counter never collides with seed values.
_employee_counter = itertools.count(1)
_pairing_counter = itertools.count(1)


def _next_employee_code(prefix: str = "AB") -> str:
    """Generate a valid two-letter+four-digit employee code."""
    n = next(_employee_counter)
    # Wrap if we ever exceed 9999.
    return f"{prefix}{n % 10000:04d}"


def _next_pairing_code(year: int = 2026) -> str:
    """Generate a valid P-YYYY-NNN pairing code."""
    n = next(_pairing_counter)
    return f"P-{year:04d}-{n % 1000:03d}"


# ---------------------------------------------------------------------
# CrewMember
# ---------------------------------------------------------------------
def create_crew_member_payload(**overrides) -> dict:
    """Minimal valid CrewMember create payload (PRD §3.2)."""
    defaults = {
        "employee_code": _next_employee_code(),
        "full_name": "Test Crew",
        "rank": "CAPTAIN",
        "base_airport": "LAX",
        "seniority_number": 1,
        "line_type": "LINEHOLDER",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------
# Pairing
# ---------------------------------------------------------------------
def create_pairing_payload(**overrides) -> dict:
    """Minimal valid Pairing create payload (PRD §3.1).

    Defaults wire up a 10-hour duty window on 2026-06-02 with bidding close
    well in front of scheduled_start_utc.
    """
    defaults = {
        "pairing_code": _next_pairing_code(),
        "origin_base": "LAX",
        "scheduled_start_utc": "2026-06-02T00:00:00Z",
        "scheduled_end_utc": "2026-06-02T10:00:00Z",
        "required_captains": 1,
        "required_first_officers": 0,
        "required_cabin_crew": 0,
        "bidding_close_utc": "2026-06-01T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------
# FlightLeg
# ---------------------------------------------------------------------
def create_flight_leg_payload(**overrides) -> dict:
    """Minimal valid FlightLeg create payload (PRD §3.1)."""
    defaults = {
        "leg_sequence": 1,
        "departure_airport": "LAX",
        "arrival_airport": "JFK",
        "scheduled_departure_utc": "2026-06-02T01:00:00Z",
        "scheduled_arrival_utc": "2026-06-02T07:00:00Z",
        "leg_type": "REVENUE",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------
# Bid
# ---------------------------------------------------------------------
def create_bid_payload(pairing_id: str, crew_member_id: str, **overrides) -> dict:
    """Minimal valid Bid create payload (PRD §3.2)."""
    defaults = {
        "pairing_id": pairing_id,
        "crew_member_id": crew_member_id,
        "requested_seat": "CAPTAIN",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------
# SickCall
# ---------------------------------------------------------------------
def create_sick_call_payload(assignment_id: str, **overrides) -> dict:
    """Minimal valid SickCall create payload (PRD §3.4)."""
    defaults = {
        "assignment_id": assignment_id,
        "reason_code": "ILLNESS",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------
# TripTrade
# ---------------------------------------------------------------------
def create_trip_trade_payload(
    initiator_assignment_id: str, counterparty_assignment_id: str, **overrides
) -> dict:
    """Minimal valid TripTrade create payload (PRD §3.5)."""
    defaults = {
        "initiator_assignment_id": initiator_assignment_id,
        "counterparty_assignment_id": counterparty_assignment_id,
    }
    defaults.update(overrides)
    return defaults
