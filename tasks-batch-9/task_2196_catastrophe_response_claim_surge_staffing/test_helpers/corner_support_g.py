"""Shared setup helpers for the cross-cutting and consistency-model corner tests.

These build the one scenario shape those two groups share: the clock parked at
2026-09-01T00:00:00.000Z, a DECLARED Florida hurricane event over 1000 exposures
at 250000 average insured value with a severity index of 0.1000, and a claim
carrying a single DWELLING coverage line against an 8000 first notice of loss.

That claim triages to a severity score of 5.07, a `FAST_TRACK` tier, a `DESK`
inspection mode, an advance cap of 13800.00 and an opening case reserve of
28750.00; the event's exposure-based modelled ultimate is 35000000.00.

Every helper takes the client first and returns the resource dict, so tests can
build all of their preconditions inline against an empty database.
"""
from .api_client import ApiClient  # noqa: F401  (documents the expected client type)
from .test_users import (
    make_catastrophe_manager_headers,
    make_claims_examiner_headers,
    make_deployment_coordinator_headers,
)

from prd_bench_local_runner.testing import get_success_data

CM = make_catastrophe_manager_headers("mgr-01")
CM_ALT = make_catastrophe_manager_headers("mgr-02")
DC = make_deployment_coordinator_headers("coord-01")
CE = make_claims_examiner_headers("examiner-alice")
CE_ALT = make_claims_examiner_headers("examiner-bob")

CLOCK = "2026-09-01T00:00:00.000Z"
LOSS_DATE = "2026-09-02T00:00:00.000Z"

EVENT_INPUTS = {
    "peril_type": "HURRICANE",
    "jurisdiction_state": "FL",
    "event_start_utc": CLOCK,
    "exposure_count": 1000,
    "avg_insured_value": 250000,
    "expected_severity_index": 0.1000,
}

CLAIM_LINES = [
    {
        "coverage_code": "DWELLING",
        "limit_amount": 300000,
        "deductible_amount": 5000,
        "estimated_damage_amount": 120000,
    }
]

ADJUSTER_INPUTS = {
    "full_name": "Dana Reyes",
    "employment_type": "STAFF",
    "home_state": "FL",
    "licensed_states": ["FL"],
    "license_expiry_utc": "2027-12-31T00:00:00.000Z",
    "max_open_claims": 5,
    "daily_rate": 700,
    "per_diem_rate": 100,
    "desk_certified": True,
    "aerial_certified": False,
}

BLOCK_INPUTS = {
    "hotel_name": "Gulfview Inn",
    "city": "Tampa",
    "rooms_total": 2,
    "nightly_rate": 200,
    "block_start_date": "2026-09-01T00:00:00.000Z",
    "block_end_date": "2026-09-08T00:00:00.000Z",
}


def declared_hurricane_event(client, cat_code):
    """Park the clock at 2026-09-01, then register and declare the FL event."""
    get_success_data(client.set_clock(CLOCK, CM))
    event = get_success_data(client.create_event(dict(EVENT_INPUTS, cat_code=cat_code), CM))
    return get_success_data(client.declare_event(event["id"], CM))


def cat_coded_claim(client, event_id, policy_number):
    """One INTAKE claim already attached to the event at intake time."""
    return get_success_data(
        client.create_claim(
            {
                "policy_number": policy_number,
                "loss_state": "FL",
                "loss_date_utc": LOSS_DATE,
                "reported_loss_amount": 8000,
                "coverage_lines": CLAIM_LINES,
                "event_id": event_id,
            },
            CE,
        )
    )


def triaged_fast_track_claim(client, event_id, policy_number):
    """The shared FAST_TRACK / DESK claim, opened at a case reserve of 28750.00."""
    claim = cat_coded_claim(client, event_id, policy_number)
    return get_success_data(client.triage_claim(claim["id"], CE))


def desk_certified_adjuster(client):
    """An idle FL staff adjuster certified for desk work with a valid licence."""
    return get_success_data(client.create_adjuster(dict(ADJUSTER_INPUTS), DC))


def two_room_block(client, event_id):
    """A PENDING 2-room block at 200.00 a night across seven nights."""
    return get_success_data(
        client.create_housing_block(dict(BLOCK_INPUTS, event_id=event_id), DC)
    )


def inspected_claim_via_desk_assignment(client, event_id, policy_number,
                                        verified_damage_amount=90000):
    """Triage, schedule a DESK inspection, start it and complete it.

    Returns ``(claim_after_triage, adjuster, assignment)``. The claim ends
    `INSPECTED`; completion appends a `REVISION` ledger row.
    """
    claim = triaged_fast_track_claim(client, event_id, policy_number)
    adjuster = desk_certified_adjuster(client)
    assignment = get_success_data(
        client.create_inspection_assignment(
            {
                "claim_id": claim["id"],
                "mode": "DESK",
                "window_start_utc": "2026-09-01T00:00:00.000Z",
                "window_end_utc": "2026-09-02T00:00:00.000Z",
                "adjuster_id": adjuster["id"],
            },
            DC,
        )
    )
    own = make_adjuster_headers_for(adjuster)
    get_success_data(client.start_inspection(assignment["id"], own))
    get_success_data(
        client.complete_inspection(
            assignment["id"], {"verified_damage_amount": verified_damage_amount}, own
        )
    )
    return claim, adjuster, assignment


def make_adjuster_headers_for(adjuster):
    """Headers carrying the adjuster row's own id, as ownership checks require."""
    from .test_users import make_adjuster_headers

    return make_adjuster_headers(adjuster["id"])
