"""Payload factories — one per entity, input fields only.

Each factory provides sensible defaults and accepts **overrides for the fields a
test needs to control. Only client-supplied (input) fields appear here.
"""


def create_community_payload(**overrides) -> dict:
    payload = {
        "name": "Test Community",
        "state_code": "CA",
    }
    payload.update(overrides)
    return payload


def create_lot_payload(community_id, **overrides) -> dict:
    payload = {
        "community_id": community_id,
        "lot_number": "A1",
        "base_rent_cents": 60000,
    }
    payload.update(overrides)
    return payload


def create_resident_payload(community_id, **overrides) -> dict:
    payload = {
        "community_id": community_id,
        "full_name": "Test Resident",
        "household_size": 2,
    }
    payload.update(overrides)
    return payload


def create_lease_payload(lot_id, resident_id, **overrides) -> dict:
    payload = {
        "lot_id": lot_id,
        "resident_id": resident_id,
        "start_date": "2026-01-01",
    }
    payload.update(overrides)
    return payload


def create_rent_schedule_payload(lot_id, **overrides) -> dict:
    payload = {
        "lot_id": lot_id,
        "proposed_rent_cents": 63000,
        "effective_date": "2027-01-01",
    }
    payload.update(overrides)
    return payload


def create_utility_bill_payload(community_id, **overrides) -> dict:
    payload = {
        "community_id": community_id,
        "utility_type": "WATER",
        "period_start": "2026-01-01",
        "period_end": "2026-02-01",
        "master_charge_cents": 10000,
    }
    payload.update(overrides)
    return payload


def create_reading_payload(lot_id, metered_units, **overrides) -> dict:
    payload = {
        "lot_id": lot_id,
        "metered_units": metered_units,
    }
    payload.update(overrides)
    return payload


def create_eviction_case_payload(lease_id, reason="NONPAYMENT", **overrides) -> dict:
    payload = {
        "lease_id": lease_id,
        "reason": reason,
    }
    payload.update(overrides)
    return payload


def create_conversion_vote_payload(community_id, quorum_threshold_pct=0.5, **overrides) -> dict:
    payload = {
        "community_id": community_id,
        "quorum_threshold_pct": quorum_threshold_pct,
    }
    payload.update(overrides)
    return payload


def create_ballot_payload(lot_id, choice="YES", **overrides) -> dict:
    payload = {
        "lot_id": lot_id,
        "choice": choice,
    }
    payload.update(overrides)
    return payload
