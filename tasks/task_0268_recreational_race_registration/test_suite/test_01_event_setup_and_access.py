"""Event/catalogue setup, access control, and not-found behaviour.

Covers queue-B corner instances under sections entities, state_machines,
resource_temporal_overlap (pricing-tier point-adjacency), endpoints (listing),
and rbac.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    assert_participant, assert_pricing_tier,
    participant_payload, build_user_headers,
)
from test_helpers import fixtures as fx

RD = TEST_USERS["race_director_headers"]


# ---------------------------------------------------------------------------
# Participant creation (corner: entities)
# ---------------------------------------------------------------------------
def test_create_participant_returns_201_with_system_fields(api):
    """PRD §2.4: "The `version` field starts at 1 when the resource is created and
    increments by 1 on every mutation".
    PRD §3.1: "An account is created with a unique `email`, a `full_name`, a
    `birthdate` given as an ISO date in `YYYY-MM-DD` form ... and a `gender` of `M`,
    `F`, or `X`."

    Design: Corner/entities/create_participant_returns_201_with_system_fields
    """
    resp = api.create_participant(
        participant_payload(email="new-unique@x.com", full_name="New Runner", gender="X"), RD)
    data = validate_success(resp, expected_status=201)
    assert_participant(data)
    assert data["version"] == 1, f"new participant version must be 1, got {data['version']}"
    assert data["email"] == "new-unique@x.com"


# ---------------------------------------------------------------------------
# Not found (corner: entities)
# ---------------------------------------------------------------------------
def test_get_registration_not_found_returns_404(api):
    """PRD §2.9: "the system validates each identifier in the path from left to
    right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first
    identifier that does not correspond to an existing resource".

    Design: Corner/entities/get_registration_not_found_returns_404
    """
    resp = api.get_registration(NON_EXISTENT_UUID, RD)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# Pricing tier immutability + point-adjacency (corner: entities,
# difficulty: resource_temporal_overlap)
# ---------------------------------------------------------------------------
def test_pricing_tier_has_no_version_field(api):
    """PRD §2.4: "a `PricingTier` is immutable after creation, so it carries only
    `id` and `created_at` — it has neither an `updated_at` field nor a `version`
    field."

    Design: Corner/entities/pricing_tier_is_immutable_no_version_field
    """
    event = fx.create_event(name="Imm 5K")
    distance = fx.create_distance(event["id"])
    resp = api.create_pricing_tier(
        distance["id"],
        {"tier_name": "REGULAR", "effective_from_utc": "2026-05-01T00:00:00Z",
         "base_price_cents": 5500}, RD)
    data = validate_success(resp, expected_status=201)
    assert_pricing_tier(data)


def test_duplicate_pricing_tier_start_instant_rejected(api):
    """PRD §3.1: "two tiers on the same distance may never share the same
    `effective_from_utc`: an attempt to add a tier whose `effective_from_utc`
    equals that of an existing tier on the distance is rejected with
    `ERR_DUPLICATE_PRICING_TIER`."

    Design: Difficulty/resource_temporal_overlap/pricing_tier_duplicate_start_instant_rejected
    """
    event = fx.create_event(name="Dup Tier 5K")
    distance = fx.create_distance(event["id"])
    fx.create_pricing_tier(distance["id"], tier_name="REGULAR",
                           effective_from_utc="2026-05-01T00:00:00Z", base_price_cents=5500)
    resp = api.create_pricing_tier(
        distance["id"],
        {"tier_name": "LATE", "effective_from_utc": "2026-05-01T00:00:00Z",
         "base_price_cents": 7000}, RD)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PRICING_TIER.value)


def test_duplicate_pricing_tier_distinct_instant_allowed(api):
    """PRD §3.1: "two tiers on the same distance may never share the same
    `effective_from_utc`: an attempt to add a tier whose `effective_from_utc`
    equals that of an existing tier on the distance is rejected with
    `ERR_DUPLICATE_PRICING_TIER`."

    Design: Difficulty/resource_temporal_overlap/pricing_tier_duplicate_start_instant_rejected
    """
    event = fx.create_event(name="Dup Tier OK 5K")
    distance = fx.create_distance(event["id"])
    fx.create_pricing_tier(distance["id"], tier_name="REGULAR",
                           effective_from_utc="2026-05-01T00:00:00Z", base_price_cents=5500)
    # A distinct effective_from_utc on the same distance must be accepted.
    resp = api.create_pricing_tier(
        distance["id"],
        {"tier_name": "LATE", "effective_from_utc": "2026-06-15T00:00:00Z",
         "base_price_cents": 7000}, RD)
    validate_success(resp, expected_status=201)


# ---------------------------------------------------------------------------
# Event open precondition (corner: state_machines)
# ---------------------------------------------------------------------------
def test_open_event_requires_distance_with_wave_and_tier(api):
    """PRD §3.1: "This transition is permitted only when the event has at least one
    distance that itself has at least one wave and at least one pricing tier, and
    only when the current clock is at or after `registration_opens_utc`".

    Design: Corner/state_machines/open_event_requires_distance_with_wave_and_tier
    """
    event = fx.create_event(name="NoWave 5K")
    fx.create_distance(event["id"])  # distance but no waves / no tiers
    fx.set_clock("2026-06-09T00:00:00Z")
    resp = api.open_event(event["id"], RD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Listing / pagination envelope (corner: endpoints)
# ---------------------------------------------------------------------------
def test_list_distances_paginated_envelope(api):
    """PRD §2.3: "Paginated list responses include the following fields in the
    `meta` object of the response envelope: `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/endpoints/list_distances_paginated_envelope
    """
    event = fx.create_event(name="List Event")
    fx.create_distance(event["id"], label="FIVE_K")
    fx.create_distance(event["id"], label="MARATHON", distance_km=42.195)
    resp = api.list_event_distances(event["id"], RD, {"limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is False, f"expected has_more False, got {meta['has_more']}"


# ---------------------------------------------------------------------------
# RBAC (corner: rbac)
# ---------------------------------------------------------------------------
def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of the
    recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_role_header_unauthenticated
    """
    bogus = build_user_headers("nobody", "Stranger")
    resp = api.create_event(
        {"name": "NoAuth", "race_date_utc": "2026-07-05T00:00:00Z",
         "registration_opens_utc": "2026-01-01T00:00:00Z",
         "registration_closes_utc": "2026-07-01T00:00:00Z"}, bogus)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_timing_official_cannot_create_event(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/timing_official_cannot_create_event
    """
    resp = api.create_event(
        {"name": "TO Event", "race_date_utc": "2026-07-05T00:00:00Z",
         "registration_opens_utc": "2026-01-01T00:00:00Z",
         "registration_closes_utc": "2026-07-01T00:00:00Z"},
        TEST_USERS["timing_official_headers"])
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_participant_cannot_assign_bib(api):
    """PRD §3.6: "Once a registration is `CONFIRMED`, a `RaceDirector` assigns it a
    bib, advancing it from `CONFIRMED` to `BIB_ASSIGNED`".
    PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/participant_cannot_assign_bib
    """
    from test_helpers import make_participant_headers
    event, distance, wave, participant, reg = fx.setup_confirmed_registration(capacity_total=50)
    resp = api.assign_bib(reg["id"], make_participant_headers(participant["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
