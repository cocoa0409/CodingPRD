"""Rider registration, service-zone configuration, and vehicle-run input validation.

Corner-design (queue B) translations for the `entities` section.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    assert_rider, assert_service_zone, NON_EXISTENT_UUID,
    create_rider_payload, create_service_zone_payload, create_run_payload,
    create_zone_a,
)

ADMIN = TEST_USERS["admin_headers"]
SPECIALIST = TEST_USERS["specialist_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


def test_rider_registration_returns_created_with_system_defaults(api):
    """PRD §3.1: "A newly registered rider begins with `eligibility_status` of
    `UNCERTIFIED` and `account_status` of `ACTIVE`."
    PRD §3.1: "The `mobility_device` is one of `NONE`, `CANE`, `WALKER`,
    `MANUAL_WHEELCHAIR`, `POWER_WHEELCHAIR`, or `SCOOTER`, defaulting to `NONE`,
    and `requires_pca` defaults to false."

    Design: Corner/entities/rider_creation_returns_201_with_system_defaults
    """
    resp = api.create_rider(create_rider_payload(full_name="New Rider", phone="555-1000",
                                                 email="new@x.com"), SPECIALIST)
    data = validate_success(resp, 201)
    assert_rider(data)
    assert data["eligibility_status"] == "UNCERTIFIED"
    assert data["account_status"] == "ACTIVE"
    assert data["mobility_device"] == "NONE"
    assert data["requires_pca"] is False


def test_rider_registration_defaults_penalty_tier_none_and_initial_version(api):
    """PRD §2.10: "otherwise the tier is `NONE`."
    PRD §2.5: "`version` is an integer that starts at its initial value and
    increments by one on every mutation of the resource; it underpins optimistic
    concurrency."

    Design: Corner/entities/rider_creation_returns_201_with_system_defaults
    """
    resp = api.create_rider(create_rider_payload(full_name="Tier Rider", phone="555-1001",
                                                 email="tier@x.com"), SPECIALIST)
    data = validate_success(resp, 201)
    assert data["penalty_tier"] == "NONE"
    assert data["no_show_points_rolling"] == 0
    assert data["no_show_points_lifetime"] == 0
    assert data["version"] == 1


def test_rider_missing_required_full_name_rejected(api):
    """PRD §2.6: "Structural request problems (a missing required field, a wrong
    type, or an unrecognized enum member) yield `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/rider_missing_required_full_name_returns_invalid_request
    """
    payload = {"phone": "555-1001", "email": "nf@x.com", "home_lat": 40.0, "home_lng": -74.0}
    resp = api.create_rider(payload, SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_rider_invalid_mobility_device_enum_rejected(api):
    """PRD §2.6: "Structural request problems (a missing required field, a wrong
    type, or an unrecognized enum member) yield `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/rider_invalid_mobility_device_enum_returns_invalid_request
    """
    resp = api.create_rider(create_rider_payload(full_name="Bad Enum", phone="555-1002",
                                                 email="be@x.com",
                                                 mobility_device="HOVERBOARD"), SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_get_unknown_rider_returns_not_found(api):
    """PRD §2.6: "the first identifier that does not resolve produces the
    corresponding not-found error — `ERR_RIDER_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`,
    `ERR_ASSESSMENT_NOT_FOUND`, `ERR_ZONE_NOT_FOUND`, `ERR_TRIP_NOT_FOUND`,
    `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_RUN_NOT_FOUND`, or `ERR_PENALTY_NOT_FOUND`
    (all HTTP 404)."

    Design: Corner/entities/rider_get_nonexistent_returns_rider_not_found
    """
    resp = api.get_rider(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_RIDER_NOT_FOUND.value)


def test_service_zone_applies_default_radius_when_omitted(api):
    """PRD §2.7: "a `service_radius_miles` that defaults to 0.75 when omitted — the
    three-quarter-mile ADA radius."

    Design: Corner/entities/service_zone_creation_applies_default_radius
    """
    payload = {"zone_code": "ZD", "name": "Zone D", "center_lat": 40.0, "center_lng": -74.0,
               "base_fare_cents": 500, "fixed_route_fare_cents": 290}
    resp = api.create_service_zone(payload, ADMIN)
    data = validate_success(resp, 201)
    assert data["service_radius_miles"] == 0.75


def test_service_zone_is_lightweight_without_version_field(api):
    """PRD §2.5: "A `ServiceZone` and a `NegotiationOffer` carry only `id` and
    `created_at`; they have neither `updated_at` nor `version`, because a zone is
    configuration and an offer is an immutable historical record of a single
    negotiation round."

    Design: Corner/entities/service_zone_immutable_has_no_version_field
    """
    resp = api.create_service_zone(create_service_zone_payload(zone_code="ZE", name="Zone E",
                                                               base_fare_cents=400,
                                                               fixed_route_fare_cents=250), ADMIN)
    data = validate_success(resp, 201)
    assert_service_zone(data)
    assert "created_at" in data
    assert "version" not in data
    assert "updated_at" not in data


def test_vehicle_run_negative_seats_rejected(api):
    """PRD §2.6: "numeric inputs outside their allowed range (negative capacities,
    negative companion counts, or invalid coordinates) yield `ERR_OUT_OF_RANGE`
    (HTTP 422); range checking applies to vehicle-run creation, trip requests, and
    subscription creation."

    Design: Corner/entities/vehicle_run_negative_seats_returns_out_of_range
    """
    zone = create_zone_a(api)
    payload = create_run_payload(zone["id"], total_ambulatory_seats=-2, total_wheelchair_positions=1)
    resp = api.create_run(payload, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_OUT_OF_RANGE.value)


def test_application_for_unknown_rider_returns_not_found(api):
    """PRD §2.6: "every resource referenced in the path or body must exist; existence
    is validated left-to-right along the URL, and the first identifier that does not
    resolve produces the corresponding not-found error — `ERR_RIDER_NOT_FOUND`,
    `ERR_APPLICATION_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_ZONE_NOT_FOUND`,
    `ERR_TRIP_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_RUN_NOT_FOUND`, or
    `ERR_PENALTY_NOT_FOUND` (all HTTP 404)."

    Design: Corner/entities/eligibility_application_unknown_rider_returns_rider_not_found
    """
    resp = api.create_application({"rider_id": NON_EXISTENT_UUID}, SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_RIDER_NOT_FOUND.value)
