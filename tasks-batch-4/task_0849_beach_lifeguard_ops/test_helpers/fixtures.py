"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared endpoints
and uses get_success_data() so setup failures surface as clear "Setup failed"
errors. Identity threading: Lifeguard is entity_backed, so any shift/incident
lifecycle call is driven with make_lifeguard_headers(<lifeguard id>).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_lifeguard_headers
from .factories import (
    create_beach_payload,
    create_zone_payload,
    create_tower_payload,
    create_lifeguard_payload,
    create_shift_payload,
    create_incident_payload,
    create_sample_payload,
    create_advisory_payload,
    create_parking_lot_payload,
    create_parking_pass_payload,
)

CAPTAIN = TEST_USERS["beach_captain_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]
CLERK = TEST_USERS["parking_clerk_headers"]
PUBLIC = TEST_USERS["public_headers"]


# --- Logical clock -----------------------------------------------------------

def set_clock(api, iso: str) -> dict:
    return get_success_data(api.set_clock({"to_iso8601": iso}, CAPTAIN))


# --- Single-entity creators --------------------------------------------------

def new_beach(api, **overrides) -> dict:
    return get_success_data(api.create_beach(create_beach_payload(**overrides), CAPTAIN))


def new_zone(api, beach_id, min_guards_required=1, **overrides) -> dict:
    payload = create_zone_payload(beach_id, min_guards_required=min_guards_required, **overrides)
    return get_success_data(api.create_zone(payload, CAPTAIN))


def new_tower(api, zone_id, max_concurrent_guards=2, **overrides) -> dict:
    payload = create_tower_payload(zone_id, max_concurrent_guards=max_concurrent_guards, **overrides)
    return get_success_data(api.create_tower(payload, CAPTAIN))


def new_lifeguard(api, beach_id, **overrides) -> dict:
    return get_success_data(api.create_lifeguard(create_lifeguard_payload(beach_id, **overrides), CAPTAIN))


def new_shift(api, lifeguard_id, tower_id, scheduled_start, scheduled_end, **overrides) -> dict:
    payload = create_shift_payload(lifeguard_id, tower_id, scheduled_start, scheduled_end, **overrides)
    return get_success_data(api.create_shift(payload, CAPTAIN))


def new_sample(api, zone_id, enterococci_mpn, sampled_at, **overrides) -> dict:
    payload = create_sample_payload(zone_id, enterococci_mpn, sampled_at, **overrides)
    return get_success_data(api.create_sample(payload, INSPECTOR))


def new_advisory(api, zone_id, basis, expected_zone_version, **overrides) -> dict:
    payload = create_advisory_payload(basis, expected_zone_version, **overrides)
    return get_success_data(api.create_advisory(zone_id, payload, INSPECTOR))


def new_parking_lot(api, beach_id, total_spaces, daily_rate_cents, **overrides) -> dict:
    payload = create_parking_lot_payload(beach_id, total_spaces, daily_rate_cents, **overrides)
    return get_success_data(api.create_parking_lot(payload, CLERK))


def new_parking_pass(api, lot_id, plate="P1", vehicle_type="CAR", pass_type="DAILY", **overrides) -> dict:
    payload = create_parking_pass_payload(lot_id, plate, vehicle_type, pass_type, **overrides)
    return get_success_data(api.create_parking_pass(payload, CLERK))


def new_incident(api, zone_id, lifeguard_id, occurred_at="2026-07-15T10:00:00Z", incident_type="MEDICAL", **overrides) -> dict:
    payload = create_incident_payload(zone_id, occurred_at, type=incident_type, lifeguard_id=lifeguard_id, **overrides)
    return get_success_data(api.create_incident(payload, make_lifeguard_headers(lifeguard_id)))


# --- Lifecycle drivers (ownership-threaded) ----------------------------------

def clock_in(api, shift_id, lifeguard_id) -> dict:
    return get_success_data(
        api.transition_shift(shift_id, {"action": "CLOCK_IN"}, make_lifeguard_headers(lifeguard_id))
    )


def clock_out(api, shift_id, lifeguard_id) -> dict:
    return get_success_data(
        api.transition_shift(shift_id, {"action": "CLOCK_OUT"}, make_lifeguard_headers(lifeguard_id))
    )


def raise_flag(api, zone_id, flag_status) -> dict:
    return get_success_data(api.set_zone_flag(zone_id, {"flag_status": flag_status}, CAPTAIN))


def zone_version(api, zone_id) -> int:
    return get_success_data(api.get_zone(zone_id, CAPTAIN))["version"]


# --- Composite setups --------------------------------------------------------

def setup_beach_zone(api, min_guards_required=1, clock=None, **zone_overrides):
    """Beach + one zone. Returns (beach, zone)."""
    if clock:
        set_clock(api, clock)
    beach = new_beach(api)
    zone = new_zone(api, beach["id"], min_guards_required=min_guards_required, **zone_overrides)
    return beach, zone


def setup_zone_tower_guard(api, min_guards_required=1, max_concurrent_guards=2, clock=None):
    """Beach + zone + tower + lifeguard. Returns (beach, zone, tower, guard)."""
    beach, zone = setup_beach_zone(api, min_guards_required=min_guards_required, clock=clock)
    tower = new_tower(api, zone["id"], max_concurrent_guards=max_concurrent_guards)
    guard = new_lifeguard(api, beach["id"])
    return beach, zone, tower, guard


def setup_scheduled_shift(
    api,
    scheduled_start="2026-07-15T09:00:00Z",
    scheduled_end="2026-07-15T17:00:00Z",
    min_guards_required=1,
    max_concurrent_guards=2,
    clock="2026-07-15T09:00:00Z",
):
    """Beach + zone + tower + guard + one SCHEDULED shift.

    Returns (beach, zone, tower, guard, shift).
    """
    beach, zone, tower, guard = setup_zone_tower_guard(
        api, min_guards_required=min_guards_required,
        max_concurrent_guards=max_concurrent_guards, clock=clock,
    )
    shift = new_shift(api, guard["id"], tower["id"], scheduled_start, scheduled_end)
    return beach, zone, tower, guard, shift


def setup_green_zone(
    api,
    scheduled_start="2026-07-15T09:00:00Z",
    scheduled_end="2026-07-15T17:00:00Z",
    clock="2026-07-15T09:00:00Z",
):
    """Beach/zone(min1)/tower/guard + one shift clocked in (count=1) + flag raised GREEN.

    Returns (beach, zone, tower, guard, shift).
    """
    beach, zone, tower, guard, shift = setup_scheduled_shift(
        api, scheduled_start=scheduled_start, scheduled_end=scheduled_end, clock=clock,
    )
    clock_in(api, shift["id"], guard["id"])
    raise_flag(api, zone["id"], "GREEN")
    return beach, zone, tower, guard, shift


def setup_zone_with_samples(api, samples, min_guards_required=1, clock="2026-07-15T12:00:00Z"):
    """Beach + zone + a list of samples. `samples` is a list of (mpn, sampled_at).

    Returns (beach, zone). Zone version is fresh (1) after this setup.
    """
    beach, zone = setup_beach_zone(api, min_guards_required=min_guards_required, clock=clock)
    for mpn, sampled_at in samples:
        new_sample(api, zone["id"], mpn, sampled_at)
    return beach, zone


def setup_open_incident(api, incident_type="MEDICAL", clock=None):
    """Beach + zone + guard + one OPEN incident. Returns (beach, zone, guard, incident)."""
    if clock:
        set_clock(api, clock)
    beach = new_beach(api)
    zone = new_zone(api, beach["id"], min_guards_required=1)
    guard = new_lifeguard(api, beach["id"])
    incident = new_incident(api, zone["id"], guard["id"], incident_type=incident_type)
    return beach, zone, guard, incident


def setup_lot(api, total_spaces=10, daily_rate_cents=1000, clock="2026-07-15T09:00:00Z"):
    """Beach + one parking lot. Returns (beach, lot)."""
    if clock:
        set_clock(api, clock)
    beach = new_beach(api)
    lot = new_parking_lot(api, beach["id"], total_spaces, daily_rate_cents)
    return beach, lot
