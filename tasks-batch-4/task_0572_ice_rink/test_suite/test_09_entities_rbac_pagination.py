"""Resource-shape essentials: computed availability on a fresh rink, the
membership default, not-found, list pagination envelope, and the two access-
control gates (role permission and authentication)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    NON_EXISTENT_UUID, TEST_USERS, make_skater_headers,
    create_rink, create_slot, create_skater,
)

RM = TEST_USERS["rink_manager_headers"]


# ---------------------------------------------------------------------------
# Corner/entities/rink_create_returns_computed_availability
# ---------------------------------------------------------------------------
def test_fresh_rink_reports_full_availability(api):
    """PRD §3.2: "the rink's `available_rental_skates` equals `rental_skate_count`
    minus the number of `ADMITTED` admissions across all of the rink's slots that
    carry `rental_skate` set to true."
    PRD §3.5: "A rink's `available_lockers` equals its `locker_count` minus the
    number of distinct `locker_number` values among that rink's `ACTIVE` locker
    assignments."

    Design: Corner/entities/rink_create_returns_computed_availability
    """
    rink = create_rink(api, public_skate_fee_cents=1500, rental_skate_count=4,
                       locker_count=3, locker_fee_cents=2000)
    data = validate_success(api.get_rink(rink["id"], RM))
    assert data["available_rental_skates"] == 4, (
        f"no admissions; expected 4 free skates, got {data['available_rental_skates']}")
    assert data["available_lockers"] == 3, (
        f"no active lockers; expected 3 free lockers, got {data['available_lockers']}")


# ---------------------------------------------------------------------------
# Corner/entities/skater_membership_defaults_non_member
# ---------------------------------------------------------------------------
def test_skater_defaults_to_non_member_with_zero_wallet(api):
    """PRD §2.7: "an optional `membership` of either `MEMBER` or `NON_MEMBER`
    (defaulting to `NON_MEMBER`)".
    PRD §2.7: "Each skater holds a prepaid wallet balance, `wallet_credit_cents`,
    denominated in integer cents and defaulting to 0."

    Design: Corner/entities/skater_membership_defaults_non_member
    """
    sk = create_skater(api, "default@x.com", full_name="Nobody")
    data = validate_success(api.get_skater(sk["id"], RM))
    assert data["membership"] == "NON_MEMBER", (
        f"expected NON_MEMBER default, got {data['membership']}")
    assert data["wallet_credit_cents"] == 0, (
        f"expected wallet default 0, got {data['wallet_credit_cents']}")


# ---------------------------------------------------------------------------
# Corner/entities/skater_not_found_returns_404
# ---------------------------------------------------------------------------
def test_get_missing_skater_returns_not_found(api):
    """PRD §2.9: "Existence — every resource referenced by a path identifier or a
    foreign-key body field ... must exist ... the first identifier that does not
    resolve yields `ERR_NOT_FOUND` (404)".

    Design: Corner/entities/skater_not_found_returns_404
    """
    validate_error(api.get_skater(NON_EXISTENT_UUID, RM),
                   ApiErrorId.ERR_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# Corner/endpoints/ice_slots_list_pagination_envelope
# ---------------------------------------------------------------------------
def test_ice_slots_list_pagination_meta(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned".
    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/endpoints/ice_slots_list_pagination_envelope
    """
    rink = create_rink(api)
    create_slot(api, rink["id"], "PUBLIC_SKATE",
                "2026-06-10T08:00:00Z", "2026-06-10T09:00:00Z")
    create_slot(api, rink["id"], "PUBLIC_SKATE",
                "2026-06-10T12:00:00Z", "2026-06-10T13:00:00Z")
    data, meta = validate_paginated(
        api.list_ice_slots(RM, params={"rink_id": rink["id"], "limit": 1, "offset": 0}))
    assert len(data) == 1, f"limit=1 should return one item, got {len(data)}"
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True, f"expected has_more True, got {meta['has_more']}"


# ---------------------------------------------------------------------------
# Corner/rbac/skater_cannot_publish_ice_slot
# ---------------------------------------------------------------------------
def test_skater_cannot_publish_ice_slot(api):
    """PRD §2.1: "When a caller is authenticated but the role is not permitted to
    perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/skater_cannot_publish_ice_slot
    """
    rink = create_rink(api)
    slot = create_slot(api, rink["id"], "PUBLIC_SKATE",
                       "2026-06-10T08:00:00Z", "2026-06-10T09:00:00Z")
    sk = create_skater(api, "noperm@x.com")
    validate_error(api.publish_ice_slot(slot["id"], make_skater_headers(sk["id"])),
                   ApiErrorId.ERR_UNAUTHORIZED.value)


# ---------------------------------------------------------------------------
# Corner/rbac/missing_auth_headers_returns_unauthenticated
# ---------------------------------------------------------------------------
def test_request_without_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of
    these three known roles, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    sk = create_skater(api, "authless@x.com")
    # Issue the read with the auth headers omitted entirely.
    validate_error(api.get_skater(sk["id"], {}),
                   ApiErrorId.ERR_UNAUTHENTICATED.value)
