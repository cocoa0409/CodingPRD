"""RBAC, optimistic-concurrency, and CRUD/endpoint tests: role gating,
authentication, the membership-version OCC on reservation create, entity
creation defaults/validation, and list/read endpoints.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    make_visitor_headers,
    set_clock,
    create_garden,
    create_plan,
    create_pending_membership,
    create_venue,
    create_rental,
    create_time_slot,
    create_nonmember_reservation,
    setup_household_member_with_slot,
)

ADMIN = TEST_USERS["admin_headers"]
STAFF = TEST_USERS["staff_headers"]
RENTAL = TEST_USERS["rental_coordinator_headers"]
DEV = TEST_USERS["development_officer_headers"]
VISITOR = TEST_USERS["visitor_headers"]


# =============================================================================
# Corner: rbac section
# =============================================================================
def test_visitor_cannot_confirm_rental_forbidden(api):
    """PRD §2.1: "When both headers are present but the named role is not
    permitted to perform the requested operation under the authorization matrix
    in Section 4, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    Section 4 lists `POST /v1/rentals/{rental_id}/confirm` as RentalCoordinator.

    A Visitor confirming a rental is forbidden.

    Design: Corner/rbac/visitor_cannot_confirm_rental_returns_forbidden
    """
    garden = create_garden(name="Zelkova Zenith")
    venue = create_venue(garden["id"], name="Atrium", hourly_rate_cents=20000)
    rental = create_rental(garden["id"], venue["id"], "2026-05-05T10:00:00Z", "2026-05-05T11:00:00Z")
    resp = api.confirm_rental(rental["id"], make_visitor_headers("anon-vc"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403)


def test_visitor_cannot_create_garden_forbidden(api):
    """PRD §2.1: "the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    Section 4 lists `POST /v1/gardens` as GardenAdmin only.

    A Visitor creating a garden is forbidden.

    Design: Corner/rbac/visitor_cannot_create_garden_returns_forbidden
    """
    resp = api.create_garden({"name": "Sneaky Garden"}, make_visitor_headers("anon-sneak"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "Every request to the platform must carry two headers:
    `X-User-ID`, identifying the calling principal, and `X-User-Role`, naming the
    principal's role. If either header is absent, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing."

    A request with no auth headers returns ERR_UNAUTHENTICATED (auth precedes
    existence: the garden id does not exist, yet 401 wins over 404).

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    resp = api._request("GET", f"/v1/gardens/{NON_EXISTENT_UUID}", headers={"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)


def test_development_officer_cannot_check_in_forbidden(api):
    """PRD §2.1: "the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    Section 4 lists `POST /v1/reservations/{reservation_id}/check-in` as
    GardenStaff only.

    A DevelopmentOfficer checking in a reservation is forbidden.

    Design: Corner/rbac/development_officer_cannot_check_in_returns_forbidden
    """
    garden = create_garden(name="Aloe Arbor")
    slot = create_time_slot(garden["id"], "2026-04-13T10:00:00Z", "2026-04-13T12:00:00Z",
                           capacity=5, ga_price_cents=2000)
    res = create_nonmember_reservation(garden["id"], slot["id"], paid_heads=1)
    set_clock("2026-04-13T10:30:00Z")
    resp = api.check_in_reservation(res["id"], DEV)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403)


# =============================================================================
# Corner: cross_cutting_complexity_layers — OCC on Membership version
# =============================================================================
def test_stale_membership_version_on_second_reservation_rejected(api):
    """PRD §2.8: "Each reservation that spends guest passes or claims member
    heads against a membership increments that membership's `version` by one...
    If, between the moment the client last read the membership and the moment it
    submits the create, another writer has advanced the membership's `version`,
    the supplied `expected_membership_version` no longer matches, and the create
    is rejected with `ERR_STALE_MEMBERSHIP_VERSION` (HTTP 412)."

    After a first guest-pass reservation bumps the version, a second create still
    carrying the pre-bump version is rejected.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_membership_version_on_reservation_create
    """
    garden, plan, membership, slot = setup_household_member_with_slot(
        guest_pass_grant_household=4, slot_capacity=10,
        slot_starts="2026-04-14T10:00:00Z", slot_ends="2026-04-14T12:00:00Z",
    )
    m_id = membership["id"]
    h = make_visitor_headers(m_id)
    v1 = membership["version"]
    validate_success(api.create_reservation(
        {"garden_id": garden["id"], "time_slot_id": slot["id"], "membership_id": m_id,
         "guest_heads": 1, "expected_membership_version": v1}, h,
    ), expected_status=201)
    resp = api.create_reservation(
        {"garden_id": garden["id"], "time_slot_id": slot["id"], "membership_id": m_id,
         "guest_heads": 1, "expected_membership_version": v1}, h,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_MEMBERSHIP_VERSION.value, expected_status=412)


def test_correct_membership_version_succeeds_and_bumps(api):
    """PRD §2.8: "When a reservation is created with a non-empty `membership_id`,
    the request must carry `expected_membership_version`, and this field is
    non-optional in that case: it must equal the target membership's current
    `version`." PRD §3.3: "the spent guest passes are deducted
    (`guest_passes_remaining` decreases by `guest_heads`) and the membership's
    `version` increments by one."

    A create carrying the current version succeeds (201) and reduces
    guest_passes_remaining from 4 to 2.

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds_and_bumps
    """
    garden, plan, membership, slot = setup_household_member_with_slot(
        guest_pass_grant_household=4, slot_capacity=10,
        slot_starts="2026-04-15T10:00:00Z", slot_ends="2026-04-15T12:00:00Z",
    )
    m_id = membership["id"]
    h = make_visitor_headers(m_id)
    res = validate_success(api.create_reservation(
        {"garden_id": garden["id"], "time_slot_id": slot["id"], "membership_id": m_id,
         "guest_heads": 2, "expected_membership_version": membership["version"]}, h,
    ), expected_status=201)
    assert res["status"] == "HELD"
    refreshed = validate_success(api.get_membership(m_id, h))
    assert refreshed["guest_passes_remaining"] == 2, "two guest passes spent of four"
    assert refreshed["version"] > membership["version"], "membership version advanced on the spend"


# =============================================================================
# Corner: entities section — creation defaults, not-found, validation
# =============================================================================
def test_create_garden_returns_defaults(api):
    """PRD §3.1: "The `timezone` is an IANA zone used for local-day math on slots
    and sessions and defaults to `America/New_York`." PRD §3.1: "The
    `household_member_cap` is the maximum number of named household members a
    household-tier membership may carry, excluding the primary member, and
    defaults to 2." PRD §3.1: "`guest_pass_grant_patron` (defaulting to ... 8)".

    POST /v1/gardens with only name -> 201 with the documented defaults and
    version 1.

    Design: Corner/entities/create_garden_returns_201_with_defaults
    """
    garden = validate_success(api.create_garden({"name": "Sunflower State Arboretum"}, ADMIN),
                              expected_status=201)
    assert garden["timezone"] == "America/New_York"
    assert garden["household_member_cap"] == 2
    assert garden["guest_pass_grant_patron"] == 8
    assert garden["version"] == 1


def test_get_membership_not_found(api):
    """PRD §2.7: "A read against a resource id that does not exist likewise yields
    `ERR_NOT_FOUND`."

    GET on a non-existent membership id -> ERR_NOT_FOUND 404.

    Design: Corner/entities/get_membership_not_found_returns_404
    """
    resp = api.get_membership("00000000-0000-4000-8000-000000000000", make_visitor_headers("anon-z"))
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


def test_create_membership_missing_required_field(api):
    """PRD §2.7: "Malformed request bodies — a missing required field, a value of
    the wrong type, or an enum value outside the permitted set — are rejected
    with `ERR_VALIDATION` (HTTP 422)." PRD §3.2: a membership is created "naming
    the `primary_member_name`".

    Omitting primary_member_name on membership create -> ERR_VALIDATION 422.

    Design: Corner/entities/create_membership_missing_required_field_returns_422
    """
    garden = create_garden(name="Tulip Terrace")
    plan = create_plan(garden["id"], tier="INDIVIDUAL", annual_fee_cents=12000)
    resp = api.create_membership(
        {"garden_id": garden["id"], "plan_id": plan["id"], "auto_renew": False},
        make_visitor_headers("anon-mm"),
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)


def test_create_plan_invalid_enum_tier(api):
    """PRD §2.7: "an enum value outside the permitted set — are rejected with
    `ERR_VALIDATION` (HTTP 422)." PRD §3.1: a plan is created "for a specific
    `tier`, which is one of `INDIVIDUAL`, `HOUSEHOLD`, or `PATRON`."

    A plan with tier='GOLD' -> ERR_VALIDATION 422.

    Design: Corner/entities/create_membership_invalid_enum_tier_via_plan_returns_422
    """
    garden = create_garden(name="Umbel Acres")
    resp = api.create_plan({"garden_id": garden["id"], "tier": "GOLD", "annual_fee_cents": 5000}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)


def test_membership_system_fields_set_by_server_on_create(api):
    """PRD §3.2: "A freshly created membership lands in `PENDING` status with
    `guest_passes_remaining` at 0, `paid_total_cents` at 0, and `renewal_count`
    at 0".

    A new membership has server-set status PENDING, paid_total 0, guest_passes 0,
    renewal_count 0 regardless of input.

    Design: Corner/entities/membership_system_fields_ignored_on_create
    """
    garden = create_garden(name="Verbena Vale")
    plan = create_plan(garden["id"], tier="INDIVIDUAL", annual_fee_cents=12000)
    membership = create_pending_membership(garden["id"], plan["id"], primary_member_name="Vi", auto_renew=False)
    assert membership["status"] == "PENDING"
    assert membership["paid_total_cents"] == 0
    assert membership["guest_passes_remaining"] == 0
    assert membership["renewal_count"] == 0


# =============================================================================
# Corner: endpoints section — pagination, filter, refund
# =============================================================================
def test_list_memberships_pagination_envelope(api):
    """PRD §2.3: "The `meta` block of a list response carries the `limit` and
    `offset` in effect, the `total_count` of records matching the filter before
    pagination is applied, and `has_more`, a boolean that is true when records
    remain beyond the current page."

    Two memberships, limit 1 -> total_count 2 and has_more true.

    Design: Corner/endpoints/list_memberships_pagination_envelope
    """
    garden = create_garden(name="Quercus Quarter")
    plan = create_plan(garden["id"], tier="INDIVIDUAL", annual_fee_cents=12000)
    create_pending_membership(garden["id"], plan["id"], primary_member_name="Q1", auto_renew=False)
    create_pending_membership(garden["id"], plan["id"], primary_member_name="Q2", auto_renew=False)
    resp = api.list_memberships(ADMIN, params={"garden_id": garden["id"], "limit": 1})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True


def test_filter_reservations_by_membership(api):
    """PRD §2.3: "The `meta` block of a list response carries the `limit` and
    `offset` in effect, the `total_count` of records matching the filter before
    pagination is applied, and `has_more`, a boolean that is true when records
    remain beyond the current page." PRD §2.7: "every cross-resource reference a
    request makes — a reservation's `time_slot_id` and `membership_id`... must
    point at a resource belonging to the *same* garden named by the request's
    `garden_id`."

    Filtering reservations by membership_id returns exactly the one FK-linked
    reservation (total_count 1).

    Design: Corner/endpoints/filtered_reservations_by_membership_reverse_reachability
    """
    garden, plan, membership, slot = setup_household_member_with_slot(
        guest_pass_grant_household=4, slot_capacity=10,
        slot_starts="2026-04-12T10:00:00Z", slot_ends="2026-04-12T12:00:00Z",
    )
    m_id = membership["id"]
    h = make_visitor_headers(m_id)
    res = validate_success(api.create_reservation(
        {"garden_id": garden["id"], "time_slot_id": slot["id"], "membership_id": m_id,
         "member_heads": 1, "expected_membership_version": membership["version"]}, h,
    ), expected_status=201)
    resp = api.list_reservations(STAFF, params={"membership_id": m_id})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"expected 1 reservation for the membership, got {meta['total_count']}"
    assert data[0]["id"] == res["id"]


def test_refund_purchased_ticket_succeeds(api):
    """PRD §3.4: "`GardenStaff` or `GardenAdmin` may refund a ticket, moving its
    `status` from `PURCHASED` to `REFUNDED`."

    Refunding a PURCHASED ticket -> REFUNDED.

    Design: Corner/endpoints/event_ticket_refund_on_purchased_succeeds
    """
    garden = create_garden(name="Salvia Springs")
    ticket = validate_success(api.create_event_ticket(
        {"garden_id": garden["id"], "exhibit_name": "Cactus Fair", "list_price_cents": 2000, "quantity": 1},
        make_visitor_headers("anon-tk"),
    ), expected_status=201)
    refunded = validate_success(api.refund_event_ticket(ticket["id"], STAFF))
    assert refunded["status"] == "REFUNDED"


def test_refund_already_refunded_ticket_rejected(api):
    """PRD §3.4: "A refund is permitted only on a ticket that is currently
    `PURCHASED`; attempting to refund a ticket in any other status — including a
    second refund of an already-`REFUNDED` ticket — is rejected with
    `ERR_REFUND_NOT_ALLOWED`."

    A second refund on a REFUNDED ticket is rejected.

    Design: Corner/endpoints/refund_already_refunded_ticket_returns_refund_not_allowed
    """
    garden = create_garden(name="Thistle Thicket")
    ticket = validate_success(api.create_event_ticket(
        {"garden_id": garden["id"], "exhibit_name": "Succulent Show", "list_price_cents": 2000, "quantity": 1},
        make_visitor_headers("anon-tk2"),
    ), expected_status=201)
    validate_success(api.refund_event_ticket(ticket["id"], STAFF))
    resp = api.refund_event_ticket(ticket["id"], STAFF)
    validate_error(resp, ApiErrorId.ERR_REFUND_NOT_ALLOWED.value, expected_status=409)
