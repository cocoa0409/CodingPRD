"""Home listings, activation ownership, availability-window date ranges, and
reverse-reachability listing.

Covers Corner instances (entities, rbac, endpoints) plus the difficulty
zero-night boundary instance.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_home_listing_payload, create_availability_window_payload,
    make_admin_headers,
    register_member, create_draft_listing, verify_identity,
    make_member_headers,
)

ADMIN = make_admin_headers()


def test_create_listing_bad_points_per_night_returns_validation(api):
    """PRD §3.2: "a `points_per_night` value of at least 1".
    PRD §2.9: "Body well-formedness comes fourth — required fields present, enum
    values legal, integers within their declared ranges — otherwise `ERR_VALIDATION`."

    Design: Corner/entities/create_listing_bad_points_per_night_enum_returns_validation
    """
    owner = register_member(full_name="Owner", home_city="Denver")
    res = api.create_home_listing(
        create_home_listing_payload(owner["id"], title="Bad", points_per_night=0),
        make_member_headers(owner["id"]))
    validate_error(res, "ERR_VALIDATION")


def test_non_owner_cannot_activate_listing_returns_unauthorized(api):
    """PRD §3.2: "Activation is permitted only to the owning member, only while the
    listing is still `DRAFT`, and only when the owner's `verification_status` is
    `VERIFIED`; an unverified owner is turned away with `ERR_MEMBER_NOT_VERIFIED`."

    Design: Corner/rbac/non_owner_cannot_activate_listing_returns_unauthorized
    """
    owner = register_member(full_name="Owner", home_city="Denver")
    verify_identity(owner["id"])
    listing = create_draft_listing(owner["id"])
    other = register_member(full_name="Other", home_city="Reno")
    res = api.activate_home_listing(listing["id"], make_member_headers(other["id"]))
    validate_error(res, "ERR_UNAUTHORIZED")


def test_list_member_home_listings_reverse_reachability(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."
    PRD §2.4: "an `id` that is a server-minted UUID with no type prefix".

    Design: Corner/endpoints/list_member_home_listings_reverse_reachability
    """
    owner = register_member(full_name="Host", home_city="Denver")
    listing = create_draft_listing(owner["id"])
    res = api.list_member_home_listings(owner["id"], make_member_headers(owner["id"]))
    data, meta = validate_paginated(res)
    assert any(item["id"] == listing["id"] for item in data), "member's own listing must appear"
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_zero_night_availability_window_rejected(api):
    """PRD §3.2: "The window's `nights` is the number of days in that half-open span
    and must be at least 1, so the `end_date` must fall strictly after the
    `start_date` — a non-positive span is rejected with `ERR_INVALID_DATE_RANGE`."

    Design: Difficulty/boundary_precision_check/zero_night_availability_window_rejected
    """
    owner = register_member(full_name="Host", home_city="Denver")
    listing = create_draft_listing(owner["id"])
    res = api.create_availability_window(
        listing["id"], create_availability_window_payload("2026-07-10", "2026-07-10"),
        make_member_headers(owner["id"]))
    validate_error(res, "ERR_INVALID_DATE_RANGE")


def test_negative_span_availability_window_rejected(api):
    """PRD §3.2: "the `end_date` must fall strictly after the `start_date` — a
    non-positive span is rejected with `ERR_INVALID_DATE_RANGE`."

    Design: Difficulty/boundary_precision_check/zero_night_availability_window_rejected
    """
    owner = register_member(full_name="Host", home_city="Denver")
    listing = create_draft_listing(owner["id"])
    res = api.create_availability_window(
        listing["id"], create_availability_window_payload("2026-07-12", "2026-07-10"),
        make_member_headers(owner["id"]))
    validate_error(res, "ERR_INVALID_DATE_RANGE")


def test_positive_span_availability_window_accepted(api):
    """PRD §3.2: "The window's `nights` is the number of days in that half-open span
    and must be at least 1".

    Design: Difficulty/boundary_precision_check/zero_night_availability_window_rejected
    """
    owner = register_member(full_name="Host", home_city="Denver")
    listing = create_draft_listing(owner["id"])
    res = api.create_availability_window(
        listing["id"], create_availability_window_payload("2026-07-10", "2026-07-11"),
        make_member_headers(owner["id"]))
    window = validate_success(res, 201)
    assert window["nights"] == 1
    assert window["status"] == "OPEN"
