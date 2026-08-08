"""Ratings aggregation plus access-control and pagination guards: role denials, the
missing-auth guard, the active-booking close guard, and pagination bounds.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, ANON_HEADERS, TEST_USERS,
    setup_reserved_booking, setup_completed_booking, file_claim, review_claim,
    set_clock, create_host, get_bags,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# --- Ratings ------------------------------------------------------------------

def test_host_avg_rating_running_average(api):
    """PRD §3.9: "the `score` is added to the host's `rating_sum`, the host's `rating_count`
    is incremented by one, and the host's `avg_rating` is recomputed as `rating_sum` divided
    by `rating_count`, rounded half up to two decimals — and is zero whenever the host has no
    ratings."

    Design: Corner/calculations/host_avg_rating_running_average
    """
    ctx, booking, bags = setup_completed_booking(
        api, tier="NONE", per_bag_coverage_cents=0, premium_cents_per_bag_day=0,
        bags=[{"declared_value_cents": 1000, "dimension_sum_cm": 100}], seal_codes=["K0"],
        check_in_date="2026-06-10", check_out_date="2026-06-11")
    validate_success(api.create_rating(booking["id"], {"score": 5, "comment": "great"},
                                       ctx["traveler_headers"]), 201)
    host = get_success_data(api.get_host(ctx["host"]["id"], ctx["admin_headers"]))
    assert host["rating_count"] == 1
    assert float(host["avg_rating"]) == pytest.approx(5.0, abs=0.001)


def test_rating_before_completed_returns_error(api):
    """PRD §3.9: "Rating a booking that is not completed is rejected with
    `ERR_BOOKING_NOT_COMPLETED`."

    Design: Corner/validations/rating_before_completed_returns_error
    """
    ctx, booking, bags = setup_reserved_booking(
        api, tier="NONE", per_bag_coverage_cents=0, premium_cents_per_bag_day=0,
        bags=[{"declared_value_cents": 1000, "dimension_sum_cm": 100}],
        check_in_date="2026-06-10", check_out_date="2026-06-11")
    from test_helpers import dropoff
    dropoff(api, ctx, booking["id"], seal_codes=["K0"])   # STORED, not COMPLETED
    resp = api.create_rating(booking["id"], {"score": 4}, ctx["traveler_headers"])
    validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_COMPLETED.value)


# --- Location close guard -----------------------------------------------------

def test_close_location_with_active_bookings_returns_error(api):
    """PRD §3.2: "an attempt to close a location that still has such active bookings is
    rejected with `ERR_LOCATION_HAS_ACTIVE_BOOKINGS`."

    Design: Corner/state_machines/close_location_with_active_bookings_returns_error
    """
    ctx, booking, bags = setup_reserved_booking(
        api, tier="NONE", per_bag_coverage_cents=0, premium_cents_per_bag_day=0,
        bags=[{"declared_value_cents": 1000, "dimension_sum_cm": 100}],
        check_in_date="2026-06-10", check_out_date="2026-06-12")
    resp = api.set_location_status(ctx["location"]["id"], {"to_status": "CLOSED"}, ctx["host_headers"])
    validate_error(resp, ApiErrorId.ERR_LOCATION_HAS_ACTIVE_BOOKINGS.value)


# --- Pagination ---------------------------------------------------------------

def test_bookings_list_invalid_limit_returns_error(api):
    """PRD §2.3: "A request whose `limit` falls outside the inclusive range of 1 through 100,
    or whose `offset` is negative, is rejected with `ERR_INVALID_PAGINATION`."

    Design: Corner/endpoints/bookings_list_invalid_limit_returns_error
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    resp = api.list_bookings(ADMIN, params={"limit": 0})
    validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION.value)


# --- RBAC denials -------------------------------------------------------------

def test_traveler_cannot_perform_dropoff(api):
    """PRD §2.1: "A well-formed request whose role is not permitted for the target operation
    is rejected with `ERR_INVALID_ROLE`."

    Design: Corner/rbac/traveler_cannot_perform_dropoff
    """
    ctx, booking, bags = setup_reserved_booking(
        api, tier="NONE", per_bag_coverage_cents=0, premium_cents_per_bag_day=0,
        bags=[{"declared_value_cents": 1000, "dimension_sum_cm": 100}],
        check_in_date="2026-06-10", check_out_date="2026-06-11")
    seals = [{"bag_id": bags[0]["id"], "seal_code": "K0", "photo_url": "http://p/0"}]
    resp = api.dropoff_booking(booking["id"], {"seals": seals}, ctx["traveler_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_ROLE.value)


def test_host_cannot_decide_claim(api):
    """PRD §2.1: "A well-formed request whose role is not permitted for the target operation
    is rejected with `ERR_INVALID_ROLE`."

    Design: Corner/rbac/host_cannot_decide_claim
    """
    ctx, booking, bags = setup_completed_booking(
        api, tier="PREMIUM", per_bag_coverage_cents=50000, premium_cents_per_bag_day=200,
        bags=[{"declared_value_cents": 20000, "dimension_sum_cm": 100}], seal_codes=["K0"],
        check_in_date="2026-06-10", check_out_date="2026-06-11")
    claim = file_claim(api, ctx, booking["id"], bags[0]["id"], reason="DAMAGE",
                       description="d", claimed_amount_cents=5000)
    review_claim(api, ctx, claim["id"])
    resp = api.decide_claim(claim["id"], {"decision": "APPROVE", "approved_amount_cents": 5000},
                            ctx["host_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_ROLE.value)


def test_host_status_missing_auth_header_returns_unauthenticated(api):
    """PRD §2.1: "A request that omits either header, or supplies a malformed one, is
    rejected with `ERR_MISSING_AUTH_HEADER`."

    Design: Corner/rbac/dropoff_missing_auth_header_returns_unauthenticated
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    host = create_host(api, email="h@x.com")
    resp = api.set_host_status(host["id"], {"to_status": "SUSPENDED"}, ANON_HEADERS)
    validate_error(resp, ApiErrorId.ERR_MISSING_AUTH_HEADER.value)
