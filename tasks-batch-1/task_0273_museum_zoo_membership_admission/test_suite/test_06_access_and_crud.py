"""Access control (RBAC + ownership) and CRUD corner cases: patron creation,
email uniqueness, not-found, pagination, listing, household add/remove, and
endpoint state guards.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    NONEXISTENT_UUID,
    TEST_USERS,
    fixtures as fx,
    make_patron_headers,
    build_user_headers,
)


def _membership_id_of(api, patron_id):
    data = validate_success(api.list_memberships(fx.ADMIN, {"primary_patron_id": patron_id}))
    assert len(data) >= 1
    return data[0]["id"]


# ─── Entities: patron CRUD & constraints ──────────────────────────────

def test_create_patron_returns_201_with_system_fields(api):
    """PRD §3.1: "Registering a patron - a capability the front desk and the
    catalog administrator both hold - records the patron's unique login email and
    their display full_name."
    PRD §2.4: "The version field is an integer that starts at 1."

    POST /patrons returns 201, a server-minted id, version==1, and the email.

    Design: Corner/entities/create_patron_returns_201_with_system_fields
    """
    data = validate_success(
        api.create_patron({"email": "c1@x.com", "full_name": "C One"}, fx.BOX_OFFICE),
        expected_status=201,
    )
    assert data["version"] == 1
    assert data["email"] == "c1@x.com"


def test_create_patron_missing_full_name_invalid_request(api):
    """PRD §2.5: "A write that violates body conformance - a missing required
    field, an unrecognized enum value, or a negative integer where a non-negative
    one is required - is rejected with ERR_INVALID_REQUEST."
    PRD §3.1: "records the patron's unique login email and their display
    full_name."

    full_name is a required input with no default; omitting it -> ERR_INVALID_REQUEST.

    Design: Corner/entities/create_patron_missing_full_name_returns_invalid_request
    """
    resp = api.create_patron({"email": "c2@x.com"}, fx.BOX_OFFICE)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_get_nonexistent_patron_not_found(api):
    """PRD §2.5: "the first identifier that does not resolve to an existing
    resource causes the request to be rejected with ERR_NOT_FOUND."

    GET /patrons/{id} with an unknown UUID -> ERR_NOT_FOUND.

    Design: Corner/entities/get_patron_nonexistent_returns_not_found
    """
    resp = api.get_patron(NONEXISTENT_UUID, fx.BOX_OFFICE)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_patron_duplicate_email_taken(api):
    """PRD §3.1: "Each patron's email must be unique across all patrons; a
    registration whose email already exists is rejected with ERR_EMAIL_TAKEN."

    Design: Corner/entities/create_patron_duplicate_email_returns_email_taken
    """
    validate_success(
        api.create_patron({"email": "dup@x.com", "full_name": "First"}, fx.BOX_OFFICE),
        expected_status=201,
    )
    resp = api.create_patron({"email": "dup@x.com", "full_name": "Second"}, fx.BOX_OFFICE)
    validate_error(resp, ApiErrorId.ERR_EMAIL_TAKEN.value)


def test_list_memberships_pagination_envelope(api):
    """PRD §2.3: "Every list response carries limit, offset, total_count, and
    has_more inside the meta object of the envelope."

    GET /memberships returns response_type=array with a paginated meta whose
    total_count reflects the one membership created.

    Design: Corner/entities/list_memberships_pagination_envelope
    """
    plan = fx.create_plan(tier="INDIVIDUAL", household_max=0)
    patron = fx.create_patron()
    fx.create_pending_membership(plan["id"], patron["id"])
    resp = api.list_memberships(fx.ADMIN, {"limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] >= 1
    assert meta["has_more"] is False


def test_pagination_limit_out_of_range_rejected(api):
    """PRD §2.3: "it must lie between a minimum of 1 and a maximum of 100. ... A
    request whose limit or offset falls outside these ranges is rejected with
    ERR_VALIDATION_PAGINATION."

    GET /memberships with limit=101 -> ERR_VALIDATION_PAGINATION.

    Design: Corner/entities/pagination_limit_out_of_range_rejected
    """
    resp = api.list_memberships(fx.ADMIN, {"limit": 101})
    validate_error(resp, ApiErrorId.ERR_VALIDATION_PAGINATION.value)


# ─── Calculations: household count ────────────────────────────────────

def test_household_count_blocks_add_over_max(api):
    """PRD §3.4: "an add is rejected with ERR_HOUSEHOLD_FULL when that active
    count plus the one being added would exceed the plan's household_max."

    Plan household_max=1: first add succeeds, the second -> ERR_HOUSEHOLD_FULL.

    Design: Corner/calculations/household_count_blocks_add_over_max
    """
    plan = fx.create_plan(tier="DUAL", household_max=1)
    patron = fx.create_patron()
    m = fx.create_pending_membership(plan["id"], patron["id"])
    validate_success(api.add_household_member(
        m["id"], {"full_name": "Spouse", "relationship": "SPOUSE"},
        make_patron_headers(patron["id"]),
    ), expected_status=201)
    resp = api.add_household_member(
        m["id"], {"full_name": "Child", "relationship": "CHILD"},
        make_patron_headers(patron["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_HOUSEHOLD_FULL.value)


def test_removed_household_member_frees_a_slot(api):
    """PRD §3.4: "Removing a household member sets its active to false rather than
    deleting it; an inactive member no longer counts against household_max,
    freeing a slot for a future add."

    With household_max=1, removing the lone member lets a subsequent add succeed
    and the new member is born active.

    Design: Corner/calculations/removed_household_member_frees_a_slot
    """
    plan = fx.create_plan(tier="DUAL", household_max=1)
    patron = fx.create_patron()
    m = fx.create_pending_membership(plan["id"], patron["id"])
    hm = validate_success(api.add_household_member(
        m["id"], {"full_name": "Spouse", "relationship": "SPOUSE"},
        make_patron_headers(patron["id"]),
    ), expected_status=201)
    validate_success(api.remove_household_member(hm["id"], make_patron_headers(patron["id"])))
    hm2 = validate_success(api.add_household_member(
        m["id"], {"full_name": "Partner", "relationship": "PARTNER"},
        make_patron_headers(patron["id"]),
    ), expected_status=201)
    assert hm2["active"] is True


# ─── Endpoints: state guards & computed reads ─────────────────────────

def test_add_ticket_to_confirmed_order_rejected(api):
    """PRD §3.5: "Tickets are added one person at a time while the order is a
    draft."
    PRD §3.6: "Confirming an order that is not in DRAFT is rejected with
    ERR_INVALID_STATE."

    POST /admission-orders/{id}/tickets on a CONFIRMED order -> ERR_INVALID_STATE.

    Design: Corner/endpoints/add_ticket_to_confirmed_order_rejected
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    patron = fx.create_patron()
    slot = fx.create_slot()
    order = fx.build_confirmed_order(
        patron["id"], slot["id"], [{"ticket_type": "NON_MEMBER", "person_name": "A"}],
    )
    resp = api.add_ticket(
        order["id"], {"ticket_type": "NON_MEMBER", "person_name": "B"},
        make_patron_headers(patron["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_list_guest_passes_filtered_by_membership(api):
    """PRD §3.4: "Guest passes ... are minted in batches when a membership
    activates or renews ... and they reference their membership through
    membership_id."
    PRD §3.2: "mints the plan's full grant of guest passes as fresh rows in
    UNUSED status under the membership."

    GET /guest-passes?membership_id={m} returns the 2 minted passes.

    Design: Corner/endpoints/list_guest_passes_filtered_by_membership
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan, patron, m = fx.setup_active_membership_simple(
        plan_overrides={"tier": "HOUSEHOLD", "guest_passes_granted": 2},
    )
    membership_id = _membership_id_of(api, patron["id"])
    resp = api.list_guest_passes(make_patron_headers(patron["id"]), {"membership_id": membership_id})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2


def test_exhibit_sessions_reverse_subresource_lists_children(api):
    """PRD §3.1: "Under an exhibit the administrator creates exhibit sessions ...
    Sessions are reachable as the reverse sub-resource of their exhibit."

    GET /special-exhibits/{id}/sessions returns the two sessions created under it.

    Design: Corner/endpoints/exhibit_sessions_reverse_subresource_lists_children
    """
    exhibit = fx.create_exhibit(name="Sharks", surcharge_cents=1000)
    fx.create_session(exhibit["id"], starts_at="2026-06-10T10:00:00Z",
                      ends_at="2026-06-10T11:00:00Z", capacity_total=5)
    fx.create_session(exhibit["id"], starts_at="2026-06-10T12:00:00Z",
                      ends_at="2026-06-10T13:00:00Z", capacity_total=5)
    resp = api.list_exhibit_sessions(exhibit["id"], fx.ADMIN)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2


# ─── RBAC ─────────────────────────────────────────────────────────────

def test_patron_cannot_create_membership_plan_forbidden(api):
    """PRD §2.1: "When a caller presents a valid role but that role is not
    permitted to perform the requested operation, the request is rejected with
    ERR_FORBIDDEN_ROLE."
    PRD §4: POST /membership-plans is authorized for MembershipAdmin.

    A Patron creating a membership plan -> ERR_FORBIDDEN_ROLE.

    Design: Corner/rbac/patron_cannot_create_membership_plan_forbidden
    """
    patron = fx.create_patron()
    resp = api.create_membership_plan(
        {"tier": "INDIVIDUAL", "annual_fee_cents": 12000, "household_max": 0,
         "guest_passes_granted": 2, "member_admission_cents": 1500},
        make_patron_headers(patron["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_patron_cannot_act_on_other_patrons_order(api):
    """PRD §2.1: "an AdmissionOrder is owned by the patron named in its patron_id;
    when a Patron attempts to act on a membership or order whose owning patron is
    not X-User-ID, the request is rejected with ERR_NOT_RESOURCE_OWNER."

    Patron P2 confirming P1's order -> ERR_NOT_RESOURCE_OWNER.

    Design: Corner/rbac/patron_cannot_act_on_other_patrons_order
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    p1 = fx.create_patron()
    p2 = fx.create_patron()
    slot = fx.create_slot()
    order = fx.build_draft_order_with_tickets(
        p1["id"], slot["id"], [{"ticket_type": "NON_MEMBER", "person_name": "A"}],
    )
    resp = api.confirm_order(order["id"], make_patron_headers(p2["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "If X-User-Role is missing or is not one of the declared roles,
    the request is rejected with ERR_UNAUTHENTICATED."

    A request whose X-User-Role is not a declared role -> ERR_UNAUTHENTICATED.

    Design: Corner/rbac/missing_role_header_unauthenticated
    """
    bad_headers = build_user_headers("nobody", "NoRole")
    resp = api.list_membership_plans(bad_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_gatescanner_cannot_create_order_forbidden(api):
    """PRD §2.1: "When X-User-Role is GateScanner ... a gate scanner only checks
    confirmed orders in at the entry window."
    PRD §4: POST /admission-orders is authorized for Patron, BoxOffice.

    A GateScanner creating an order -> ERR_FORBIDDEN_ROLE.

    Design: Corner/rbac/gatescanner_can_checkin_but_not_create_order
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    patron = fx.create_patron()
    slot = fx.create_slot()
    resp = api.create_order({"patron_id": patron["id"], "slot_id": slot["id"]}, fx.GATE)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
