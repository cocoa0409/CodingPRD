"""Business validations, RBAC enforcement, authentication, and reverse-reachability reads."""
import requests

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    make_fleet_manager_headers, make_rental_agent_headers, make_member_headers,
    create_location, create_econ_class, create_vehicle, create_member,
    create_reservation, set_member_loyalty,
    create_vehicle_class_payload,
)
from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId

FM = make_fleet_manager_headers()
RA = make_rental_agent_headers()


# ===========================================================================
# Queue B — calculations: zero availability
# ===========================================================================
def test_confirm_with_zero_availability_rejected(api):
    """PRD §3.3: "the reserved class must have availability at the pickup
    location: its `available_count` must be at least 1, else
    `ERR_NO_AVAILABILITY`."

    Design: Corner/calculations/confirm_with_zero_availability_returns_no_availability
    """
    loc = create_location(api=api)
    cls = create_econ_class(api=api)  # no vehicles.
    member = create_member(api=api)
    res = create_reservation(member["id"], loc["id"], loc["id"], cls["id"],
                             "2026-07-01T10:00:00Z", "2026-07-04T10:00:00Z", api=api)
    resp = api.confirm_reservation(res["id"], RA)
    validate_error(resp, ApiErrorId.ERR_NO_AVAILABILITY.value)


# ===========================================================================
# Queue B — validations section
# ===========================================================================
def test_upgrade_to_lower_tier_rejected(api):
    """PRD §3.3: "The new class is accepted only when its `tier_rank` is strictly
    greater than the currently reserved class's `tier_rank`; a same-tier or
    lower-tier target is rejected with `ERR_NOT_AN_UPGRADE`."

    Design: Corner/validations/upgrade_to_lower_tier_returns_not_an_upgrade
    """
    loc = create_location(api=api)
    cls_econ = create_econ_class(api=api)  # tier_rank 1.
    cls_suv = validate_success(api.create_vehicle_class(create_vehicle_class_payload(
        code="SUVZ", tier_rank=3, daily_rate_cents=8000, weekly_rate_cents=49000,
        included_miles_per_day=150, overage_per_mile_cents=35,
        ldw_per_day_cents=2000, pai_per_day_cents=1000,
    ), FM), 201)
    member = create_member(api=api)
    res = create_reservation(member["id"], loc["id"], loc["id"], cls_suv["id"],
                             "2026-07-01T10:00:00Z", "2026-07-04T10:00:00Z", api=api)
    resp = api.upgrade_reservation(res["id"], {"class_id": cls_econ["id"]}, RA)
    validate_error(resp, ApiErrorId.ERR_NOT_AN_UPGRADE.value)


def test_redeem_more_than_balance_rejected(api):
    """PRD §3.2: "A redemption requesting more `points` than the member's current
    `points_balance` is rejected with `ERR_INSUFFICIENT_POINTS`."

    Design: Corner/validations/redeem_more_than_balance_returns_insufficient_points
    """
    member = create_member(api=api)
    set_member_loyalty(member["id"], api=api, points_balance=200, lifetime_points=200)
    member_headers = make_member_headers(member["id"])
    resp = api.redeem_points(member["id"], {"points": 1000}, member_headers)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_POINTS.value)


# ===========================================================================
# Queue B — endpoints section (reverse-reachability reads)
# ===========================================================================
def test_list_vehicles_by_class_includes_created_vehicle(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`,
    and `has_more` inside the `meta` object of the envelope."

    Design: Corner/endpoints/reverse_reachability_list_vehicles_by_class
    """
    loc = create_location(api=api)
    cls = create_econ_class(api=api)
    veh = create_vehicle(loc["id"], cls["id"], api=api, plate="LAX-001")
    resp = api.list_class_vehicles(cls["id"], FM)
    data, meta = validate_paginated(resp)
    assert any(v["id"] == veh["id"] for v in data), "listing should include the created vehicle"
    assert "total_count" in meta and "has_more" in meta


def test_list_reservations_by_member_includes_booking(api):
    """PRD §3.3: "Several endpoints address a parent resource and list its
    children — for example, listing the vehicles at a location, the reservations
    of a member, or the ledger entries of an agreement."

    Design: Corner/endpoints/filtered_list_reservations_by_member
    """
    loc = create_location(api=api)
    cls = create_econ_class(api=api)
    member = create_member(api=api)
    member_headers = make_member_headers(member["id"])
    res = validate_success(api.create_reservation(f.create_reservation_payload(
        member["id"], loc["id"], loc["id"], cls["id"],
        "2026-07-01T10:00:00Z", "2026-07-04T10:00:00Z",
    ), member_headers), 201)
    resp = api.list_member_reservations(member["id"], member_headers)
    data, _meta = validate_paginated(resp)
    assert any(r["id"] == res["id"] for r in data)


# ===========================================================================
# Queue B — errors section
# ===========================================================================
def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed value,
    is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/errors/missing_auth_headers_returns_unauthenticated
    """
    # Send with no auth headers at all.
    resp = requests.post(
        f"{api.base_url}/locations",
        json=f.create_location_payload(code="LAX", name="Los Angeles"),
        headers={"Content-Type": "application/json"},
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_rental_agent_cannot_create_location_forbidden(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted
    to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN`."

    Design: Corner/errors/rental_agent_cannot_create_location_returns_forbidden
    """
    resp = api.create_location(f.create_location_payload(code="LAX", name="Los Angeles"), RA)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Queue B — rbac section
# ===========================================================================
def test_member_cannot_cancel_other_members_reservation(api):
    """PRD §2.1: "An attempt to act on a reservation or account belonging to
    another member is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/member_cannot_cancel_other_members_reservation_forbidden
    """
    loc = create_location(api=api)
    cls = create_econ_class(api=api)
    memA = validate_success(api.create_member(f.create_member_payload(email="a@x.com", full_name="Member A"),
                                              make_member_headers("bootstrap-a")), 201)
    memB = validate_success(api.create_member(f.create_member_payload(email="b@x.com", full_name="Member B"),
                                              make_member_headers("bootstrap-b")), 201)
    headersA = make_member_headers(memA["id"])
    headersB = make_member_headers(memB["id"])
    res = validate_success(api.create_reservation(f.create_reservation_payload(
        memA["id"], loc["id"], loc["id"], cls["id"],
        "2026-07-01T10:00:00Z", "2026-07-04T10:00:00Z",
    ), headersA), 201)
    resp = api.cancel_reservation(res["id"], headersB)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_member_cannot_confirm_reservation_agent_exclusive(api):
    """PRD §4: the confirm endpoint is authorized for RentalAgent only.
    PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN`."

    Design: Corner/rbac/member_cannot_confirm_reservation_exclusive_to_agent
    """
    loc = create_location(api=api)
    cls = create_econ_class(api=api)
    member = validate_success(api.create_member(f.create_member_payload(),
                                               make_member_headers("bootstrap-c")), 201)
    headers = make_member_headers(member["id"])
    res = validate_success(api.create_reservation(f.create_reservation_payload(
        member["id"], loc["id"], loc["id"], cls["id"],
        "2026-07-01T10:00:00Z", "2026-07-04T10:00:00Z",
    ), headers), 201)
    resp = api.confirm_reservation(res["id"], headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
