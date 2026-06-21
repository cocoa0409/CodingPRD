"""Role-based access control corners (§1.9 rbac section).

The Driver role is entity-backed; the not-owner test threads the real Driver id.
"""
import pytest
from test_helpers import (
    TEST_USERS,
    validate_error,
    ApiErrorId,
    build_user_headers,
    make_driver_headers,
    create_member_payload,
    NON_EXISTENT_UUID,
)
from test_helpers import fixtures

COORD = TEST_USERS["coordinator_headers"]


def test_driver_cannot_create_member(api):
    """PRD 2.1: "If the role is recognized but is not permitted to perform the
    requested operation, the request is rejected with `ERR_FORBIDDEN`."
    PRD 4: POST /members is authorized for Coordinator only.

    Design: Corner/rbac/driver_cannot_create_member
    """
    driver_headers = build_user_headers(NON_EXISTENT_UUID, "Driver")
    resp = api.create_member(
        create_member_payload(medicaid_id="M-RB1", full_name="Rbac One",
                              mobility_level="AMBULATORY", home_county="C1"),
        driver_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_missing_role_header_returns_401(api):
    """PRD 2.1: "If `X-User-Role` is missing or does not name a recognized role,
    the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_role_header_returns_401
    """
    no_role_headers = {"X-User-ID": "anybody", "Content-Type": "application/json"}
    resp = api.get_member(NON_EXISTENT_UUID, no_role_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_unrecognized_role_returns_401(api):
    """PRD 2.1: "If `X-User-Role` is missing or does not name a recognized role,
    the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_role_header_returns_401
    """
    bogus_headers = build_user_headers("anybody", "Nobody")
    resp = api.get_member(NON_EXISTENT_UUID, bogus_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_driver_not_owner_of_trip_cannot_act_on_leg(api):
    """PRD 2.1: "A driver who is not the trip's assigned driver may not act on
    that trip's legs."
    PRD 3.5: "Only the trip's assigned driver may act on its legs; any other
    driver attempting a leg action is rejected with `ERR_NOT_OWNER`."

    Design: Corner/rbac/driver_not_owner_of_trip_cannot_act_on_leg
    """
    world = fixtures.setup_world(modality="AMBULATORY", medicaid_id="M-NO1")
    # A second, unrelated driver in the same broker.
    other_driver = fixtures.create_driver(
        world["broker"]["id"], vehicle_modality="AMBULATORY", base_county="C2")
    assigned, legs = fixtures.create_assigned_trip(
        world, modality="AMBULATORY", scheduled_loaded_miles=8, is_round_trip=False)
    ob = legs[0]
    resp = api.leg_depart(ob["id"], make_driver_headers(other_driver["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_OWNER.value)
