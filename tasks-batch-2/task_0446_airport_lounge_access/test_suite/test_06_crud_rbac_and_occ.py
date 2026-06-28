"""CRUD surface, system/computed/default fields, RBAC, optimistic concurrency,
and listing/pagination corners.

All queue-B instances: entity creation/retrieval/listing/not-found/required/enum/
system-field/parent-FK corners, role authorization, ownership isolation, the
lounge-version OCC guard, and filtered pagination.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    api_client,
    ApiErrorId,
    TEST_USERS,
    make_member_headers,
    make_lounge_agent_headers,
    fixtures,
    assert_lounge,
    assert_member,
    MISSING_UUID,
)

ADMIN = TEST_USERS["network_admin_headers"]
MEMBER_SHARED = TEST_USERS["member_headers"]


# ─── Queue B: entity CRUD corners ────────────────────────────────────────────
def test_create_lounge_returns_201_with_defaults(api):
    """PRD §3.1: "On creation a lounge starts in `OPEN` status with both occupancy
    counters and its settlement balance at zero."
    PRD §2.4: "a `version` integer that starts at 1 and increments by one on every
    mutation."

    Design: Corner/entities/entity_create_lounge_returns_201_with_defaults
    """
    resp = api_client.create_lounge(
        {"name": "Create L", "airport_code": "SFO", "capacity": 10,
         "settlement_rate_cents": 1200, "guest_fee_cents": 1000, "day_pass_price_cents": 4000},
        ADMIN,
    )
    lounge = validate_success(resp, expected_status=201)
    assert_lounge(lounge)
    assert lounge["status"] == "OPEN", lounge
    assert lounge["current_occupancy"] == 0, lounge
    assert lounge["settlement_balance_cents"] == 0, lounge
    assert lounge["version"] == 1, lounge


def test_get_member_returns_stored_with_counters(api):
    """PRD §3.2: "Enrolment stamps `membership_year_start` to the current
    logical-clock instant, starts the member in `GOOD` standing, and zeroes every
    usage counter: `visits_used`, `guest_visits_used`, `no_show_strikes`, and
    `wallet_balance_cents` all begin at 0."

    Design: Corner/entities/entity_get_member_returns_stored
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    plan = fixtures.create_plan(tier="STANDARD", included_visits_per_year=0, included_guest_visits_per_year=0)
    member = fixtures.create_member(plan["id"], full_name="Stored Member")
    got = get_success_data(api_client.get_member(member["id"], ADMIN))
    assert_member(got)
    assert got["plan_id"] == plan["id"], got
    assert got["standing"] == "GOOD", got
    assert got["visits_used"] == 0, got
    assert got["wallet_balance_cents"] == 0, got


def test_list_lounges_paginated_envelope(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope, where `total_count` is the
    count of all matching resources before pagination and `has_more` indicates
    whether further pages remain."

    Design: Corner/entities/entity_list_lounges_paginated_envelope
    """
    fixtures.create_lounge(name="L1", airport_code="AAA")
    fixtures.create_lounge(name="L2", airport_code="BBB")
    data, meta = validate_paginated(api_client.list_lounges(ADMIN, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2, meta
    assert meta["has_more"] is True, meta
    assert len(data) == 1, data


def test_get_member_not_found(api):
    """PRD §2.9: "The first identifier that does not resolve to an existing resource
    causes the request to be rejected with `ERR_NOT_FOUND` (HTTP 404) before any
    later resource is examined and before any state or business check is attempted."

    Design: Corner/entities/entity_get_member_not_found
    """
    resp = api_client.get_member(MISSING_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_lounge_missing_required_capacity_rejected(api):
    """PRD §3.1: "A lounge is created with a display `name`, an `airport_code` that
    must be exactly three uppercase letters of an IATA code, a `capacity` of at
    least 1 (the maximum number of occupants present at once, where each primary
    occupant and each guest counts as one)..."
    PRD §2.10: "body-shape validation — required fields present, enum and type
    values legal, and on shower bookings the start instant strictly before the end
    instant — is enforced with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/entity_create_lounge_missing_required_field
    """
    resp = api_client.create_lounge(
        {"name": "No Cap", "airport_code": "SFO",
         "settlement_rate_cents": 1200, "guest_fee_cents": 1000, "day_pass_price_cents": 4000},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_card_invalid_enum_rejected(api):
    """PRD §3.2: "An eligibility card is issued to a member (identified by
    `member_id`) with a `card_status` of `BASIC`, `SILVER`, or `GOLD`; a `fare_class`
    for the active trip of `ECONOMY`, `BUSINESS`, or `FIRST`; and a `valid_until`
    UTC expiry instant."
    PRD §2.10: "body-shape validation — required fields present, enum and type
    values legal... is enforced with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/entity_card_invalid_enum_rejected
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    plan = fixtures.create_plan(tier="PRESTIGE", included_visits_per_year=10)
    member = fixtures.create_member(plan["id"])
    resp = api_client.create_card(
        {"member_id": member["id"], "card_status": "PLATINUM", "fare_class": "ECONOMY",
         "valid_until": "2027-01-01T00:00:00Z"},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_member_membership_year_start_system_stamped(api):
    """PRD §3.2: "Enrolment stamps `membership_year_start` to the current
    logical-clock instant, starts the member in `GOOD` standing, and zeroes every
    usage counter."
    PRD §2.4: "On startup the clock reads exactly `2026-01-01T00:00:00Z`... The
    network operator can advance the clock to any absolute instant by supplying a
    `to_iso8601` value."

    Design: Corner/entities/entity_member_system_fields_generated
    """
    fixtures.set_clock("2026-03-15T00:00:00Z")
    plan = fixtures.create_plan(tier="STANDARD", included_visits_per_year=0, included_guest_visits_per_year=0)
    member = fixtures.create_member(plan["id"], full_name="Sys Member")
    assert member["membership_year_start"] == "2026-03-15T00:00:00.000Z", member


def test_create_card_for_missing_member_not_found(api):
    """PRD §2.9: "Identifiers that appear in the URL path are validated first, left
    to right, followed by foreign-key references carried in the request body —
    members, lounges, visits, day passes, plans, settlements, and cards alike. The
    first identifier that does not resolve to an existing resource causes the
    request to be rejected with `ERR_NOT_FOUND` (HTTP 404)..."

    Design: Corner/entities/entity_flat_topology_fk_validated
    """
    resp = api_client.create_card(
        {"member_id": MISSING_UUID, "card_status": "GOLD", "fare_class": "FIRST",
         "valid_until": "2027-01-01T00:00:00Z"},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_hold_against_missing_lounge_not_found(api):
    """PRD §2.9: "The first identifier that does not resolve to an existing resource
    causes the request to be rejected with `ERR_NOT_FOUND` (HTTP 404) before any
    later resource is examined and before any state or business check is attempted."

    Existence (404) is checked before the OCC version check, so the supplied
    version is moot.

    Design: Corner/entities/entity_visit_wrong_lounge_parent_not_found
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    plan = fixtures.create_plan(tier="PRESTIGE", included_visits_per_year=10)
    real_lounge = fixtures.create_lounge(airport_code="SFO", capacity=10)
    member = fixtures.create_member(plan["id"])
    fixtures.create_card(member["id"])
    resp = api_client.create_visit(
        {"member_id": member["id"], "lounge_id": MISSING_UUID, "guest_count": 0,
         "expected_lounge_version": real_lounge["version"]},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ─── Queue B: RBAC corners ───────────────────────────────────────────────────
def test_member_cannot_create_lounge(api):
    """PRD §2.1: "A request that is authenticated but whose role is not permitted to
    perform the requested operation is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    POST /lounges is NetworkAdmin-only (§4 endpoint table).

    Design: Corner/rbac/rbac_member_cannot_create_lounge
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    plan = fixtures.create_plan(tier="STANDARD", included_visits_per_year=0, included_guest_visits_per_year=0)
    member = fixtures.create_member(plan["id"], full_name="RBAC Member")
    resp = api_client.create_lounge(
        {"name": "Hack", "airport_code": "XXX", "capacity": 1, "settlement_rate_cents": 1,
         "guest_fee_cents": 1, "day_pass_price_cents": 1},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_member_cannot_cancel_other_members_visit(api):
    """PRD §2.1: "Ownership checks on any resource that references a member compare
    that resource's owning member reference to `X-User-ID`: a member acting on a
    visit, day pass, eligibility card, or shower reservation must own it."
    PRD §2.1: "Ownership violations — a member touching a resource they do not own,
    or an agent touching a visit at a lounge they do not staff — are rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/rbac_member_cannot_cancel_other_members_visit
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    plan = fixtures.create_plan(tier="PRESTIGE", included_visits_per_year=10)
    lounge = fixtures.create_lounge(airport_code="OAK", capacity=10)
    owner = fixtures.create_member(plan["id"], full_name="Owner A")
    fixtures.create_card(owner["id"])
    intruder = fixtures.create_member(plan["id"], full_name="Intruder B")
    visit = fixtures.open_hold(lounge["id"], member_id=owner["id"])
    resp = api_client.cancel_visit(visit["id"], make_member_headers(intruder["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_member_cannot_check_in(api):
    """PRD §2.1: "A request that is authenticated but whose role is not permitted to
    perform the requested operation is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    POST /visits/{id}/check-in is LoungeAgent-only (§4 endpoint table).

    Design: Corner/rbac/rbac_member_cannot_checkin
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    plan = fixtures.create_plan(tier="PRESTIGE", included_visits_per_year=10)
    lounge = fixtures.create_lounge(airport_code="BNA", capacity=10)
    member = fixtures.create_member(plan["id"])
    fixtures.create_card(member["id"])
    visit = fixtures.open_hold(lounge["id"], member_id=member["id"])
    resp = api_client.check_in(visit["id"], make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_lounge_agent_cannot_check_in_visit_at_other_lounge(api):
    """PRD §2.1: "When `X-User-Role` is `LoungeAgent`, `X-User-ID` is the `id` of the
    lounge whose door the agent staffs (the agent identity is backed by the `Lounge`
    entity). Ownership checks on any operation an agent performs against a visit
    compare that visit's `lounge_id` to `X-User-ID`; an agent may only act on visits
    at the lounge they staff."

    Design: Corner/rbac/rbac_lounge_agent_cannot_checkin_other_lounge_visit
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    plan = fixtures.create_plan(tier="PRESTIGE", included_visits_per_year=10)
    la = fixtures.create_lounge(airport_code="CLE", capacity=10)
    lb = fixtures.create_lounge(airport_code="CMH", capacity=10)
    member = fixtures.create_member(plan["id"])
    fixtures.create_card(member["id"])
    visit = fixtures.open_hold(la["id"], member_id=member["id"])
    # Agent staffs LB but tries to admit a visit at LA.
    resp = api_client.check_in(visit["id"], make_lounge_agent_headers(lb["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_unknown_role_unauthenticated(api):
    """PRD §2.1: "A request that omits either header, or that carries an
    `X-User-Role` value that is not one of these three, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/err_unauthenticated_missing_role_header
    """
    from test_helpers import build_user_headers
    ghost = build_user_headers("ghost-1", "Ghost")
    resp = api_client.list_lounges(ghost)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ─── Queue B: optimistic concurrency corners ─────────────────────────────────
def test_stale_lounge_version_on_hold_rejected(api):
    """PRD §2.7: "Opening a hold requires `expected_lounge_version` to match the
    target lounge's current `version`. If the lounge's version has advanced since
    the client last read it — because, for instance, the lounge was just closed or
    its occupancy line moved — the client's view is stale and the hold is refused
    rather than allowed to slip a seat past a capacity or closure change the client
    never saw."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_lounge_version_on_hold
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    plan = fixtures.create_plan(tier="PRESTIGE", included_visits_per_year=10)
    lounge = fixtures.create_lounge(airport_code="PIT", capacity=10)
    v0 = lounge["version"]
    ma = fixtures.create_member(plan["id"], full_name="Occ A")
    fixtures.create_card(ma["id"])
    mb = fixtures.create_member(plan["id"], full_name="Occ B")
    fixtures.create_card(mb["id"])
    # First hold advances the lounge version.
    fixtures.open_hold(lounge["id"], member_id=ma["id"], expected_version=v0)
    # Second hold still carries the stale v0.
    resp = api_client.create_visit(
        {"member_id": mb["id"], "lounge_id": lounge["id"], "guest_count": 0,
         "expected_lounge_version": v0},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_stale_lounge_version_on_close_rejected(api):
    """PRD §2.7: "Closing a lounge requires `expected_lounge_version` to match the
    lounge's current `version` before the close is applied."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_lounge_version_on_close
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    plan = fixtures.create_plan(tier="PRESTIGE", included_visits_per_year=10)
    lounge = fixtures.create_lounge(airport_code="MCO", capacity=10)
    v0 = lounge["version"]
    member = fixtures.create_member(plan["id"])
    fixtures.create_card(member["id"])
    fixtures.open_hold(lounge["id"], member_id=member["id"], expected_version=v0)
    resp = api_client.close_lounge(
        lounge["id"], {"expected_lounge_version": v0}, ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_lounge_version_increments_on_close(api):
    """PRD §2.4: "a `version` integer that starts at 1 and increments by one on
    every mutation."
    PRD §3.1: "Closing a lounge transitions its `status` to `CLOSED` from either
    `OPEN` or `OVERFLOW`; this is one of the version-guarded writes of §2.7 and
    requires the supplied lounge version to match."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_write
    """
    lounge = fixtures.create_lounge(airport_code="STL", capacity=10)
    assert lounge["version"] == 1, lounge
    closed = get_success_data(
        api_client.close_lounge(lounge["id"], {"expected_lounge_version": 1}, ADMIN)
    )
    assert closed["version"] == 2, closed
    assert closed["status"] == "CLOSED", closed


def test_lounge_listing_filter_then_paginate(api):
    """PRD §2.3: "every list is returned sorted by the resource's creation timestamp
    in ascending order. Every list response carries `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object of the envelope, where `total_count` is the
    count of all matching resources before pagination and `has_more` indicates
    whether further pages remain."

    Filtering by airport_code restricts total_count to the matching set.

    Design: Corner/cross_cutting_complexity_layers/pagination_lounges_offset_consistency
    """
    fixtures.create_lounge(name="S1", airport_code="SFO")
    fixtures.create_lounge(name="S2", airport_code="SFO")
    fixtures.create_lounge(name="X1", airport_code="LAX")
    data, meta = validate_paginated(
        api_client.list_lounges(ADMIN, params={"airport_code": "SFO", "limit": 1, "offset": 0})
    )
    assert meta["total_count"] == 2, meta
    assert meta["has_more"] is True, meta
    assert len(data) == 1, data
