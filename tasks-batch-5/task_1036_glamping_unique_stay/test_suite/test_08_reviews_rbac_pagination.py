"""Reviews, role-based access control, and list pagination.

Covers corner queue B (review gating, RBAC forbidden/not-owner/unauthenticated,
pagination envelope).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    make_host_headers, make_guest_headers,
    NO_AUTH_HEADERS, TEST_USERS,
    create_listing_payload, create_review_payload,
)
import test_helpers.fixtures as fx

ADMIN = TEST_USERS["platform_admin_headers"]

_COMPLETE_KW = dict(site_type="CABIN", max_guests=4, min_nights=1,
                    base_nightly_rate_cents=20000, cleaning_fee_cents=0,
                    cancellation_policy="MODERATE", permit_type="CAMPING",
                    rate_cents=20000, rate_end="2026-08-01T00:00:00Z")


# ------------------------------------------------ corner: review gating
def test_review_before_complete_rejected(api):
    """PRD §3.9: "A review is permitted only when the booking has reached
    `COMPLETED`; an attempt against a booking in any other status is rejected with
    `ERR_REVIEW_NOT_ALLOWED` (HTTP 400)."

    Design: Corner/validations/review_before_complete_rejected
    """
    env = fx.setup_confirmed_booking(check_in="2026-07-10T00:00:00Z",
                                     check_out="2026-07-12T00:00:00Z", **_COMPLETE_KW)
    resp = api.create_review(env["booking"]["id"],
                             create_review_payload(env["booking"]["id"], rating=5,
                                                   comment="early"),
                             make_guest_headers(env["guest"]["id"]))
    validate_error(resp, "ERR_REVIEW_NOT_ALLOWED")


def test_duplicate_review_rejected(api):
    """PRD §3.9: "Only one review may exist per booking; a second attempt is
    rejected with `ERR_DUPLICATE_REVIEW` (HTTP 409)."

    Design: Corner/state_machines/duplicate_review_rejected
    """
    env = fx.setup_completed_booking(check_in="2026-07-10T00:00:00Z",
                                     check_out="2026-07-13T00:00:00Z",
                                     checkin_clock="2026-07-13T00:00:00Z",
                                     **_COMPLETE_KW)
    gh = make_guest_headers(env["guest"]["id"])
    get_success_data(api.create_review(
        env["booking"]["id"],
        create_review_payload(env["booking"]["id"], rating=5, comment="great"), gh))
    resp = api.create_review(
        env["booking"]["id"],
        create_review_payload(env["booking"]["id"], rating=4, comment="again"), gh)
    validate_error(resp, "ERR_DUPLICATE_REVIEW")


# ------------------------------------------------ corner: pagination envelope
def test_list_listings_pagination_envelope(api):
    """PRD §2.3: "Every list response echoes `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/endpoints/list_listings_pagination_envelope
    """
    host = fx.onboard_host()
    hh = make_host_headers(host["id"])
    get_success_data(api.create_listing(
        create_listing_payload(host["id"], title="E1a", site_type="YURT",
                               max_guests=2, base_nightly_rate_cents=10000), hh))
    get_success_data(api.create_listing(
        create_listing_payload(host["id"], title="E1b", site_type="CABIN",
                               max_guests=2, base_nightly_rate_cents=12000), hh))
    resp = api.list_listings(ADMIN,
                             params={"host_id": host["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


# ------------------------------------------------ corner: RBAC
def test_guest_cannot_accept_booking_returns_forbidden(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."

    Design: Corner/rbac/guest_cannot_accept_booking_returns_forbidden
    """
    env = fx.setup_listed_listing(site_type="CABIN", min_nights=1, cleaning_fee_cents=0,
                                  permit_type="CAMPING", rate_end="2026-08-01T00:00:00Z")
    booking = fx.request_booking(env["listing"]["id"], env["guest"]["id"],
                                 "2026-07-10T00:00:00Z", "2026-07-12T00:00:00Z")
    resp = api.accept_booking(booking["id"], make_guest_headers(env["guest"]["id"]))
    validate_error(resp, "ERR_FORBIDDEN")


def test_host_cannot_manage_other_hosts_listing_returns_not_owner(api):
    """PRD §2.1: "When an `entity_backed` principal (a `Host` or a `Guest`)
    attempts an ownership-guarded mutation on a resource it does not own, the
    request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/host_cannot_manage_other_hosts_listing_returns_not_owner
    """
    env = fx.setup_listed_listing(site_type="CABIN", cleaning_fee_cents=0,
                                  permit_type="CAMPING", rate_end="2026-08-01T00:00:00Z")
    host_b = fx.onboard_host()
    resp = api.suspend_listing(env["listing"]["id"], make_host_headers(host_b["id"]))
    validate_error(resp, "ERR_NOT_RESOURCE_OWNER")


def test_unauthenticated_request_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of
    the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP
    401)."

    Design: Corner/rbac/unauthenticated_request_returns_unauthenticated
    """
    resp = api.get_listing("00000000-0000-0000-0000-000000000000", NO_AUTH_HEADERS)
    validate_error(resp, "ERR_UNAUTHENTICATED")
