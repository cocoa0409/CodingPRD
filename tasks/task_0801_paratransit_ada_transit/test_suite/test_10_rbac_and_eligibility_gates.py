"""Authentication/authorization/ownership gates, not-found errors, and the rider
eligibility gate (including its precedence over the service-area check).

Queue A (Difficulty): cross_entity_state_dependency (eligibility gate),
priority_pair_validation_conflict (eligibility beats service-area).
Queue B (Corner): errors (not-found, unauthenticated), rbac (unauthorized, not-owner).
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_trip_payload, NON_EXISTENT_UUID,
)
import test_helpers as th

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
DRIVER = TEST_USERS["driver_headers"]
SPECIALIST = TEST_USERS["specialist_headers"]


# ==========================================================================
# Difficulty A — eligibility gate: UNCERTIFIED rider cannot request a trip
# ==========================================================================
def _uncertified_request_in_area(api):
    th.set_clock(api, "2026-06-01T00:00:00Z")
    zone = th.create_zone_a(api)
    rider = th.create_rider(api)  # never certified -> UNCERTIFIED
    payload = create_trip_payload(rider["id"], zone["id"], zone["id"],
                                  pickup_lat=40.0, pickup_lng=-74.0,
                                  dropoff_lat=40.0, dropoff_lng=-74.0)
    resp = api.create_trip(payload, th.make_rider_headers(rider["id"]))
    return resp, rider


def test_uncertified_rider_trip_request_rejected(api):
    """PRD §3.4: "To request a trip the rider's `eligibility_status` must be either `FULL`
    or `CONDITIONAL`, or the request is rejected with `ERR_RIDER_NOT_ELIGIBLE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/request_gated_by_rider_eligibility_status_uncertified_rejected
    """
    resp, _ = _uncertified_request_in_area(api)
    validate_error(resp, ApiErrorId.ERR_RIDER_NOT_ELIGIBLE.value)


def test_uncertified_rider_stays_uncertified_after_rejection(api):
    """PRD §3.1: "A newly registered rider begins with `eligibility_status` of
    `UNCERTIFIED` and `account_status` of `ACTIVE`."
    PRD §3.4: "To request a trip the rider's `eligibility_status` must be either `FULL` or
    `CONDITIONAL`, or the request is rejected with `ERR_RIDER_NOT_ELIGIBLE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/request_gated_by_rider_eligibility_status_uncertified_rejected
    """
    resp, rider = _uncertified_request_in_area(api)
    validate_error(resp, ApiErrorId.ERR_RIDER_NOT_ELIGIBLE.value)
    read = validate_success(api.get_rider(rider["id"], SPECIALIST))
    assert read["eligibility_status"] == "UNCERTIFIED"


# ==========================================================================
# Difficulty A — eligibility (state) beats service-area (referential)
# ==========================================================================
def _uncertified_request_out_of_area(api):
    th.set_clock(api, "2026-06-01T00:00:00Z")
    zone = th.create_zone_a(api)
    rider = th.create_rider(api)  # UNCERTIFIED
    payload = create_trip_payload(rider["id"], zone["id"], zone["id"],
                                  pickup_lat=41.0, pickup_lng=-74.0,   # ~69 mi out of area
                                  dropoff_lat=40.0, dropoff_lng=-74.0)
    return api.create_trip(payload, th.make_rider_headers(rider["id"]))


def test_eligibility_error_precedes_service_area_error(api):
    """PRD §3.4: "Before any booking is created the system enforces the rider's
    eligibility. To request a trip the rider's `eligibility_status` must be either `FULL`
    or `CONDITIONAL`, or the request is rejected with `ERR_RIDER_NOT_ELIGIBLE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/request_state_not_eligible_beats_referential_outside_service_area
    """
    resp = _uncertified_request_out_of_area(api)
    validate_error(resp, ApiErrorId.ERR_RIDER_NOT_ELIGIBLE.value)


def test_out_of_area_uncertified_request_not_reported_as_service_area(api):
    """PRD §3.4: "Before any booking is created the system enforces the rider's
    eligibility. To request a trip the rider's `eligibility_status` must be either `FULL`
    or `CONDITIONAL`, or the request is rejected with `ERR_RIDER_NOT_ELIGIBLE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/request_state_not_eligible_beats_referential_outside_service_area
    """
    resp = _uncertified_request_out_of_area(api)
    error_data = validate_error(resp, ApiErrorId.ERR_RIDER_NOT_ELIGIBLE.value)
    assert error_data["error_id"] != ApiErrorId.ERR_OUTSIDE_SERVICE_AREA.value


# ==========================================================================
# Corner B — not-found errors
# ==========================================================================
def test_get_unknown_trip_returns_not_found(api):
    """PRD §2.6: "the first identifier that does not resolve produces the corresponding
    not-found error — `ERR_RIDER_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`,
    `ERR_ASSESSMENT_NOT_FOUND`, `ERR_ZONE_NOT_FOUND`, `ERR_TRIP_NOT_FOUND`,
    `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_RUN_NOT_FOUND`, or `ERR_PENALTY_NOT_FOUND`
    (all HTTP 404)."

    Design: Corner/errors/trip_get_nonexistent_returns_trip_not_found
    """
    resp = api.get_trip(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_TRIP_NOT_FOUND.value)


def test_get_unknown_run_returns_not_found(api):
    """PRD §2.6: "the first identifier that does not resolve produces the corresponding
    not-found error — `ERR_RIDER_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`,
    `ERR_ASSESSMENT_NOT_FOUND`, `ERR_ZONE_NOT_FOUND`, `ERR_TRIP_NOT_FOUND`,
    `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_RUN_NOT_FOUND`, or `ERR_PENALTY_NOT_FOUND`
    (all HTTP 404)."

    Design: Corner/errors/vehicle_run_get_nonexistent_returns_run_not_found
    """
    resp = api.get_run(NON_EXISTENT_UUID, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_RUN_NOT_FOUND.value)


def test_unrecognized_role_returns_unauthenticated(api):
    """PRD §2.1: "If `X-User-Role` is missing or is not one of the recognized roles, the
    request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/get_riders_unrecognized_role_returns_unauthenticated
    """
    rider = th.create_rider(api)
    resp = api.get_rider(rider["id"], TEST_USERS["unknown_role_headers"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ==========================================================================
# Corner B — RBAC (peer-role authorization + ownership)
# ==========================================================================
def test_dispatcher_cannot_create_trip_reservation(api):
    """PRD §2.1: "If the role is recognized but is not permitted to perform the requested
    operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/dispatcher_cannot_create_trip_reservation_unauthorized
    """
    zone = th.create_zone_a(api)
    rider = th.create_rider(api)
    payload = create_trip_payload(rider["id"], zone["id"], zone["id"])
    resp = api.create_trip(payload, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_driver_cannot_offer_trip(api):
    """PRD §2.1: "If the role is recognized but is not permitted to perform the requested
    operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/driver_cannot_offer_trip_unauthorized
    """
    base = th.scenario_certified_rider_zone(api, clock=None)
    trip = th.request_trip(api, base["rider"]["id"], base["zone_a"]["id"], base["zone_a"]["id"])
    resp = api.offer_trip(trip["id"], {"proposed_pickup_at": "2026-06-05T09:00:00Z"}, DRIVER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_rider_cannot_cancel_another_riders_trip(api):
    """PRD §2.1: "A rider acting on a trip reservation, subscription, or appeal they do
    not own is rejected with `ERR_FORBIDDEN_NOT_OWNER` (HTTP 403)."

    Design: Corner/rbac/rider_cannot_cancel_other_riders_trip_forbidden_not_owner
    """
    base = th.scenario_certified_rider_zone(api, clock=None)
    owner_id = base["rider"]["id"]
    za = base["zone_a"]["id"]
    other = th.create_rider(api, phone="555-1030", email="otherb@x.com")
    trip = th.request_trip(api, owner_id, za, za)
    resp = api.cancel_trip(trip["id"], th.make_rider_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_NOT_OWNER.value)
