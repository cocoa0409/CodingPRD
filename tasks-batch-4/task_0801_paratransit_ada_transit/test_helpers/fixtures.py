"""Composite setup helpers.

Every test starts against an empty database (the runner restarts the server
before each test), so these helpers build all preconditions from scratch using
only PRD-declared endpoints. They use get_success_data() (lenient) internally so
setup failures surface as clear "Setup failed" errors.

Identity threading: the Rider role is entity_backed, so ownership-gated calls
(trip create/counter/accept/cancel, subscription create, appeal-by-rider) are
issued with make_rider_headers(rider_id) — never the shared TEST_USERS rider
constant — so the X-User-ID matches the real Rider.id.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_rider_headers
from .factories import (
    create_rider_payload, create_service_zone_payload, create_application_payload,
    create_assessment_payload, complete_assessment_payload, create_trip_payload,
    create_subscription_payload, create_run_payload,
)
from .constants import TEST_DEFAULTS

_D = TEST_DEFAULTS
ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
DRIVER = TEST_USERS["driver_headers"]
SPECIALIST = TEST_USERS["specialist_headers"]


def _data(resp):
    return get_success_data(resp)


# --------------------------------------------------------------------------
# Primitive builders
# --------------------------------------------------------------------------
def set_clock(api, iso="2026-06-01T00:00:00Z"):
    return _data(api.set_clock({"to_iso8601": iso}, ADMIN))


def create_zone(api, **overrides):
    return _data(api.create_service_zone(create_service_zone_payload(**overrides), ADMIN))


def create_zone_a(api):
    return create_zone(api, zone_code="ZA", name="Zone A",
                       center_lat=_D["ZA_CENTER_LAT"], center_lng=_D["ZA_CENTER_LNG"],
                       base_fare_cents=_D["ZA_BASE_FARE_CENTS"],
                       fixed_route_fare_cents=_D["ZA_FIXED_ROUTE_FARE_CENTS"])


def create_zone_b(api):
    return create_zone(api, zone_code="ZB", name="Zone B",
                       center_lat=_D["ZB_CENTER_LAT"], center_lng=_D["ZB_CENTER_LNG"],
                       base_fare_cents=_D["ZB_BASE_FARE_CENTS"],
                       fixed_route_fare_cents=_D["ZB_FIXED_ROUTE_FARE_CENTS"])


def create_rider(api, **overrides):
    """Register an (uncertified) rider."""
    return _data(api.create_rider(create_rider_payload(**overrides), SPECIALIST))


def certify_rider(api, rider_id, outcome="PASS_UNCONDITIONAL",
                  assessed_mobility_device="NONE", scheduled_at="2026-06-02T10:00:00Z"):
    """Run a rider through the full certification lifecycle to CERTIFIED.
    outcome PASS_UNCONDITIONAL -> eligibility FULL; PASS_CONDITIONAL -> CONDITIONAL.
    Returns the certified rider record."""
    app = _data(api.create_application(create_application_payload(rider_id), SPECIALIST))
    fa = _data(api.create_assessment(create_assessment_payload(app["id"], scheduled_at), SPECIALIST))
    api.complete_assessment(fa["id"], complete_assessment_payload(outcome, assessed_mobility_device), SPECIALIST)
    api.certify_application(app["id"], SPECIALIST)
    return _data(api.get_rider(rider_id, SPECIALIST))


def create_certified_rider(api, outcome="PASS_UNCONDITIONAL",
                           assessed_mobility_device="NONE", **rider_overrides):
    """Register + fully certify a rider. Returns the certified rider record."""
    rider = create_rider(api, **rider_overrides)
    certify_rider(api, rider["id"], outcome, assessed_mobility_device)
    return _data(api.get_rider(rider["id"], SPECIALIST))


def create_run(api, zone_id, seats=4, positions=2, service_date="2026-06-05", **overrides):
    return _data(api.create_run(
        create_run_payload(zone_id, service_date=service_date,
                           total_ambulatory_seats=seats,
                           total_wheelchair_positions=positions, **overrides), DISPATCHER))


# --------------------------------------------------------------------------
# Trip lifecycle helpers
# --------------------------------------------------------------------------
def request_trip(api, rider_id, pickup_zone_id, dropoff_zone_id,
                 requested_pickup_at="2026-06-05T09:00:00Z", **overrides):
    """POST /trip-reservations as the owning rider."""
    payload = create_trip_payload(rider_id, pickup_zone_id, dropoff_zone_id,
                                  requested_pickup_at=requested_pickup_at, **overrides)
    return _data(api.create_trip(payload, make_rider_headers(rider_id)))


def offer_trip(api, trip_id, proposed_pickup_at="2026-06-05T09:00:00Z"):
    return _data(api.offer_trip(trip_id, {"proposed_pickup_at": proposed_pickup_at}, DISPATCHER))


def counter_trip(api, trip_id, rider_id, proposed_pickup_at):
    return _data(api.counter_trip(trip_id, {"proposed_pickup_at": proposed_pickup_at},
                                  make_rider_headers(rider_id)))


def accept_trip(api, trip_id, rider_id, run_id, expected_run_version):
    """Accept an offered trip (returns the raw Response so callers may assert on it)."""
    return api.accept_trip(trip_id,
                           {"run_id": run_id, "expected_run_version": expected_run_version},
                           make_rider_headers(rider_id))


def create_offered_trip(api, rider_id, pickup_zone_id, dropoff_zone_id,
                        requested_pickup_at="2026-06-05T09:00:00Z",
                        proposed_pickup_at=None, **trip_overrides):
    """Request a trip and place one dispatcher offer. Returns the trip (OFFERED)."""
    trip = request_trip(api, rider_id, pickup_zone_id, dropoff_zone_id,
                        requested_pickup_at=requested_pickup_at, **trip_overrides)
    offer_trip(api, trip["id"], proposed_pickup_at or requested_pickup_at)
    return _data(api.get_trip(trip["id"], DISPATCHER))


def create_scheduled_trip(api, rider_id, pickup_zone_id, dropoff_zone_id, run_id, run_version,
                          requested_pickup_at="2026-06-05T09:00:00Z",
                          proposed_pickup_at=None, **trip_overrides):
    """Request -> offer -> accept a trip onto run_id. Returns the trip (SCHEDULED)."""
    trip = create_offered_trip(api, rider_id, pickup_zone_id, dropoff_zone_id,
                               requested_pickup_at=requested_pickup_at,
                               proposed_pickup_at=proposed_pickup_at, **trip_overrides)
    accept_trip(api, trip["id"], rider_id, run_id, run_version)
    return _data(api.get_trip(trip["id"], DISPATCHER))


# --------------------------------------------------------------------------
# Composite scenarios (dict returns; keys documented per helper)
# --------------------------------------------------------------------------
def scenario_certified_rider_zone(api, clock="2026-06-01T00:00:00Z",
                                  outcome="PASS_UNCONDITIONAL",
                                  assessed_mobility_device="NONE", **rider_overrides):
    """Empty DB -> clock set + one certified rider + zone ZA.

    Returns {rider, zone_a}."""
    if clock:
        set_clock(api, clock)
    zone_a = create_zone_a(api)
    rider = create_certified_rider(api, outcome=outcome,
                                   assessed_mobility_device=assessed_mobility_device,
                                   **rider_overrides)
    return {"rider": rider, "zone_a": zone_a}


def scenario_certified_rider_zone_run(api, clock="2026-06-01T00:00:00Z",
                                      seats=4, positions=2,
                                      outcome="PASS_UNCONDITIONAL",
                                      assessed_mobility_device="NONE", **rider_overrides):
    """Empty DB -> certified rider + zone ZA + one PLANNED run (version captured).

    Returns {rider, zone_a, run, run_version}."""
    base = scenario_certified_rider_zone(api, clock=clock, outcome=outcome,
                                         assessed_mobility_device=assessed_mobility_device,
                                         **rider_overrides)
    run = create_run(api, base["zone_a"]["id"], seats=seats, positions=positions)
    base["run"] = run
    base["run_version"] = run["version"]
    return base


def scenario_scheduled_trip(api, clock="2026-06-01T00:00:00Z", seats=4, positions=2,
                            requested_pickup_at="2026-06-05T09:00:00Z", **trip_overrides):
    """Certified rider + zone + run + one SCHEDULED trip on the run.

    Returns {rider, zone_a, run, run_version_at_create, trip}."""
    base = scenario_certified_rider_zone_run(api, clock=clock, seats=seats, positions=positions)
    trip = create_scheduled_trip(api, base["rider"]["id"], base["zone_a"]["id"],
                                 base["zone_a"]["id"], base["run"]["id"], base["run_version"],
                                 requested_pickup_at=requested_pickup_at,
                                 proposed_pickup_at=requested_pickup_at, **trip_overrides)
    base["trip"] = trip
    base["run_version_at_create"] = base["run_version"]
    return base


def scenario_picked_up_trip(api, clock="2026-06-01T00:00:00Z",
                            actual_pickup_at="2026-06-05T09:00:00Z",
                            actual_pickup_zone_id=None,
                            requested_pickup_at="2026-06-05T09:00:00Z", **trip_overrides):
    """Certified rider + SCHEDULED trip driven to PICKED_UP.

    Returns {rider, zone_a, run, trip}."""
    base = scenario_scheduled_trip(api, clock=clock,
                                   requested_pickup_at=requested_pickup_at, **trip_overrides)
    zone_id = actual_pickup_zone_id or base["zone_a"]["id"]
    api.pickup_trip(base["trip"]["id"],
                    {"actual_pickup_at": actual_pickup_at, "actual_pickup_zone_id": zone_id},
                    DRIVER)
    base["trip"] = _data(api.get_trip(base["trip"]["id"], DRIVER))
    return base


def submitted_application(api, clock=None, **rider_overrides):
    """Rider + one application in SUBMITTED. Returns {rider, application}."""
    if clock:
        set_clock(api, clock)
    rider = create_rider(api, **rider_overrides)
    app = _data(api.create_application(create_application_payload(rider["id"]), SPECIALIST))
    return {"rider": rider, "application": app}


def assessed_application(api, outcome="PASS_UNCONDITIONAL", clock=None, **rider_overrides):
    """Rider + application walked to ASSESSED with the given assessment outcome.

    Returns {rider, application, assessment}."""
    base = submitted_application(api, clock=clock, **rider_overrides)
    fa = _data(api.create_assessment(
        create_assessment_payload(base["application"]["id"]), SPECIALIST))
    api.complete_assessment(fa["id"], complete_assessment_payload(outcome=outcome), SPECIALIST)
    base["assessment"] = _data(api.get_assessment(fa["id"], SPECIALIST))
    base["application"] = _data(api.get_application(base["application"]["id"], SPECIALIST))
    return base


def no_showed_trip(api, clock="2026-06-01T00:00:00Z", **trip_overrides):
    """Certified rider + SCHEDULED trip marked NO_SHOW; one ACTIVE PenaltyEvent exists.

    Returns {rider, zone_a, run, trip, penalty}."""
    base = scenario_scheduled_trip(api, clock=clock, **trip_overrides)
    api.no_show_trip(base["trip"]["id"], DRIVER)
    base["trip"] = _data(api.get_trip(base["trip"]["id"], DRIVER))
    penalties = get_success_data(api.list_penalties(ADMIN, params={"trip_id": base["trip"]["id"]}))
    base["penalty"] = penalties[0] if isinstance(penalties, list) and penalties else None
    return base
