"""Payload factories — one per creatable entity, input fields only.

Each factory provides PRD-faithful defaults and accepts **overrides so tests can
control the field(s) under assertion. Only `source: input` fields appear here.
"""
from .constants import ELECTION_DEFAULTS


def create_election_payload(**overrides) -> dict:
    """POST /elections. All seven fields are required."""
    payload = dict(ELECTION_DEFAULTS)
    payload.update(overrides)
    return payload


def create_precinct_payload(election_id: str, **overrides) -> dict:
    """POST /precincts. max_registrations must be >= 1, street_high >= street_low."""
    payload = {
        "election_id": election_id,
        "code": "P1",
        "county_fips": "06075",
        "street_low": 1,
        "street_high": 999,
        "max_registrations": 50,
    }
    payload.update(overrides)
    return payload


def create_registration_payload(election_id: str, **overrides) -> dict:
    """POST /registrations. party is optional (defaults to UNAFFILIATED server-side)."""
    payload = {
        "election_id": election_id,
        "first_name": "A",
        "last_name": "A",
        "national_id": "N1",
        "is_citizen": True,
        "date_of_birth": "1990-01-01T00:00:00Z",
        "county_fips": "06075",
        "street_number": 10,
    }
    payload.update(overrides)
    return payload


def create_absentee_ballot_payload(registration_id: str, expected_registration_version: int, **overrides) -> dict:
    """POST /absentee-ballots. expected_registration_version is the OCC field (§2.8)."""
    payload = {
        "registration_id": registration_id,
        "mailing_address": "1 A St",
        "expected_registration_version": expected_registration_version,
    }
    payload.update(overrides)
    return payload


def create_voting_machine_payload(precinct_id: str, **overrides) -> dict:
    """POST /voting-machines. role is optional (defaults to PRIMARY); capacity >= 1."""
    payload = {
        "precinct_id": precinct_id,
        "serial": "M-1",
        "role": "PRIMARY",
        "capacity": 30,
    }
    payload.update(overrides)
    return payload


def create_machine_failure_payload(machine_id: str, expected_machine_version: int, **overrides) -> dict:
    """POST /machine-failures. expected_machine_version is the OCC field (§2.8)."""
    payload = {
        "machine_id": machine_id,
        "expected_machine_version": expected_machine_version,
    }
    payload.update(overrides)
    return payload


def create_recount_case_payload(election_id: str, precinct_id: str, **overrides) -> dict:
    """POST /recount-cases."""
    payload = {
        "election_id": election_id,
        "precinct_id": precinct_id,
    }
    payload.update(overrides)
    return payload


def tally_payload(reported_vote_count: int, **overrides) -> dict:
    """POST /precincts/{id}/tally."""
    payload = {"reported_vote_count": reported_vote_count}
    payload.update(overrides)
    return payload


def early_vote_checkin_payload(registration_id: str, **overrides) -> dict:
    """POST /early-vote-checkins."""
    payload = {"registration_id": registration_id}
    payload.update(overrides)
    return payload


def clock_payload(current_utc: str) -> dict:
    """POST /_clock/set."""
    return {"current_utc": current_utc}
