"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "ELECTION_NAME": "General",
    "JURISDICTION": "COUNTY-1",
    "ELECTION_DATE": "2026-11-03",
    "INITIAL_BALLOT_STOCK": 10000,
    "PLACE_NAME": "Precinct 1",
    "ADDRESS": "1 Main St",
    "MIN_WORKERS_REQUIRED": 1,
    "STAFFING_CAPACITY": 5,
    "STATION_CAPACITY": 5,
    "SERIAL": "SN-1",
    "BALLOT_COUNT": 500,
    "SEAL": "SEAL-1",
    "WORKER_NAME": "Jane Poll",
    "WORKER_EMAIL": "jane@x.com",
}


def create_election_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["ELECTION_NAME"],
        "jurisdiction": DEFAULTS["JURISDICTION"],
        "election_date": DEFAULTS["ELECTION_DATE"],
        "initial_ballot_stock": DEFAULTS["INITIAL_BALLOT_STOCK"],
    }
    payload.update(overrides)
    return payload


def create_polling_place_payload(election_id, **overrides) -> dict:
    payload = {
        "election_id": election_id,
        "name": DEFAULTS["PLACE_NAME"],
        "address": DEFAULTS["ADDRESS"],
        "min_workers_required": DEFAULTS["MIN_WORKERS_REQUIRED"],
        "staffing_capacity": DEFAULTS["STAFFING_CAPACITY"],
        "station_capacity": DEFAULTS["STATION_CAPACITY"],
    }
    payload.update(overrides)
    return payload


def create_equipment_payload(**overrides) -> dict:
    payload = {
        "equipment_type": "SCANNER",
        "serial_number": DEFAULTS["SERIAL"],
    }
    payload.update(overrides)
    return payload


def create_poll_worker_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["WORKER_NAME"],
        "email": DEFAULTS["WORKER_EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_assignment_payload(poll_worker_id, polling_place_id, **overrides) -> dict:
    payload = {
        "poll_worker_id": poll_worker_id,
        "polling_place_id": polling_place_id,
    }
    payload.update(overrides)
    return payload


def create_shift_payload(assignment_id, scheduled_start, scheduled_end, **overrides) -> dict:
    payload = {
        "assignment_id": assignment_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    payload.update(overrides)
    return payload


def create_supply_kit_payload(election_id, **overrides) -> dict:
    payload = {
        "election_id": election_id,
        "ballot_count": DEFAULTS["BALLOT_COUNT"],
        "seal_number": DEFAULTS["SEAL"],
    }
    payload.update(overrides)
    return payload


def create_provisional_ballot_payload(polling_place_id, voter_name="V1", reason="NO_ID",
                                      **overrides) -> dict:
    payload = {
        "polling_place_id": polling_place_id,
        "voter_name": voter_name,
        "reason": reason,
    }
    payload.update(overrides)
    return payload


def create_incident_payload(polling_place_id, category, description="hotline report",
                            **overrides) -> dict:
    payload = {
        "polling_place_id": polling_place_id,
        "category": category,
        "description": description,
    }
    payload.update(overrides)
    return payload
