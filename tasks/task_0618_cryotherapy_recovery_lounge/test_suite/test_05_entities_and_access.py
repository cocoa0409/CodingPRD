"""Entity CRUD, defaults, computed fields, listing/pagination, reverse-reachability,
RBAC, OCC concurrency, and the remaining state-machine corner instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    make_member_headers,
    create_location_payload, create_service_type_payload, create_member_payload,
    create_subscription_payload, create_credit_pack_payload, create_booking_payload,
    create_freeze_payload, build_user_headers,
    TEST_USERS, MISSING_UUID,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["admin_headers"]
MANAGER = TEST_USERS["manager_headers"]

COMPRESSION = {"code": "COMPRESSION", "name": "Compression",
               "duration_minutes": 30, "buffer_minutes": 0, "credit_cost": 1,
               "requires_medical_clearance": False}
BASE_PLAN = {"tier": "BASE", "monthly_fee_cents": 9900,
             "monthly_credit_grant": 4, "rollover_cap": 0}
PLUS_PLAN = {"tier": "PLUS", "monthly_fee_cents": 16900,
             "monthly_credit_grant": 8, "rollover_cap": 4}


# ─── Queue B: entities ───────────────────────────────────────────────────────
def test_create_location_returns_system_fields(api):
    """PRD §3.1: "the location is born with status of OPEN and an open_booking_count of zero."
    PRD §2.4: "an integer version that begins at its initial value and increments by one on
    every mutation."

    Design: Corner/entities/create_location_returns_201_with_system_fields
    """
    loc = validate_success(api.create_location(
        create_location_payload(name="Dallas", state_code="TX"), ADMIN), 201)
    assert loc["status"] == "OPEN"
    assert loc["open_booking_count"] == 0
    assert loc["version"] == 1


def test_create_member_missing_email_rejected(api):
    """PRD §2.8: "(6) general body well-formedness — required fields present, enum values
    legal, integers within their declared ranges — yielding ERR_INVALID_REQUEST".
    PRD §3.3: "A member is registered ... with a home_location_id naming their default
    location, a unique email, a full_name, and a residence state_code."

    Design: Corner/entities/create_member_missing_required_field_rejected
    """
    loc = fx.create_location()
    payload = create_member_payload(loc["id"])
    del payload["email"]
    res = api.create_member(payload, MANAGER)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_service_type_defaults_applied(api):
    """PRD §3.1: "requires_medical_clearance, which when true means a contraindication flag
    blocks booking the service entirely (defaulting to false), and active, which when false
    hides the service from the menu and prevents it from being booked (defaulting to true)."

    Design: Corner/entities/service_type_default_active_true_applied
    """
    svc = validate_success(api.create_service_type(
        create_service_type_payload(code="RED_LIGHT", name="Red Light",
                                    duration_minutes=20, buffer_minutes=5, credit_cost=1),
        ADMIN), 201)
    assert svc["active"] is True
    assert svc["requires_medical_clearance"] is False


def test_fresh_member_credit_balance_zero(api):
    """PRD §3.3: "A new member is ACTIVE with contraindication_flag false, intro_offer_used
    false, and credit_balance zero."

    Design: Corner/entities/member_credit_balance_computed_ignores_client_input
    """
    loc = fx.create_location()
    member = validate_success(api.create_member(create_member_payload(loc["id"]), MANAGER), 201)
    assert member["credit_balance"] == 0


def test_get_nonexistent_member_not_found(api):
    """PRD §2.7: "the server validates each identifier in left-to-right order and rejects the
    request with ERR_NOT_FOUND (HTTP 404) on the first identifier in the path that does not
    resolve to an existing resource."

    Design: Corner/entities/get_member_nonexistent_returns_not_found
    """
    res = api.get_member(MISSING_UUID, ADMIN)
    validate_error(res, "ERR_NOT_FOUND")


def test_invoice_is_append_only_no_version(api):
    """PRD §2.4: "The Invoice resource is append-only and immutable after issue: it carries
    only id and created_at, and has neither an updated_at nor a version field."
    PRD §3.4: "a SIGNUP invoice for the plan's monthly_fee_cents is appended in PAID status".

    Design: Corner/entities/invoice_immutable_no_version_field
    """
    plan = fx.create_plan(**PLUS_PLAN)
    location = fx.create_location()
    fx.set_clock("2026-06-01T00:00:00Z")
    member = fx.create_member(location["id"])
    sub = validate_success(api.create_subscription(
        member["id"], create_subscription_payload(plan["id"]),
        make_member_headers(member["id"])), 201)

    invoices = fx.list_invoices(sub["id"])
    signup = [i for i in invoices if i["kind"] == "SIGNUP"]
    assert len(signup) == 1, invoices
    assert signup[0]["amount_cents"] == 16900
    assert signup[0]["status"] == "PAID"
    assert "version" not in signup[0]
    assert "updated_at" not in signup[0]


# ─── Queue B: endpoints (listing / pagination / reverse-reachability) ────────
def test_list_locations_pagination_envelope(api):
    """PRD §2.3: "Every list response carries the pagination fields limit, offset,
    total_count, and has_more inside the meta object of the envelope, where total_count is
    the count of all matching resources before pagination and has_more indicates whether
    more results exist beyond the current page."

    Design: Corner/endpoints/list_locations_pagination_envelope
    """
    fx.create_location(name="L1", state_code="TX")
    fx.create_location(name="L2", state_code="CA")
    data, meta = validate_paginated(api.list_locations(ADMIN, params={"limit": 1, "offset": 0}))
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_list_pagination_limit_out_of_bounds(api):
    """PRD §2.3: "A limit outside the inclusive range of 1 to 100, or a negative offset, is
    rejected with ERR_VALIDATION_PAGINATION (HTTP 400)."

    Design: Corner/endpoints/list_pagination_limit_out_of_bounds_rejected
    """
    res = api.list_locations(ADMIN, params={"limit": 101})
    validate_error(res, "ERR_VALIDATION_PAGINATION")


def test_credit_packs_filtered_by_member(api):
    """PRD §3.6: "Packs are listed filterable by member_id and status."
    PRD §3.6: "A new pack is ACTIVE with remaining_credits equal to total_credits".

    Design: Corner/endpoints/reverse_reachability_credit_packs_filtered_by_member
    """
    location = fx.create_location()
    fx.set_clock("2026-06-01T00:00:00Z")
    member = fx.create_member(location["id"])
    pack = fx.buy_pack(member["id"], 5, is_intro=False)

    data, meta = validate_paginated(api.list_credit_packs(
        make_member_headers(member["id"]), params={"member_id": member["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["id"] == pack["id"]
    assert data[0]["remaining_credits"] == 5


# ─── Queue B: state-machine corners (waiver supersede, location reopen) ──────
def test_signing_new_waiver_supersedes_prior(api):
    """PRD §3.3: "when a member already has an ACTIVE waiver and signs a fresh one, the prior
    ACTIVE waiver transitions to SUPERSEDED in the same request and the new waiver becomes
    the member's single ACTIVE waiver. On signing, the member's contraindication_flag is
    recomputed directly from the new active waiver's has_contraindication."

    Design: Corner/state_machines/signing_new_waiver_supersedes_prior_active
    """
    location = fx.create_location()
    fx.set_clock("2026-06-01T00:00:00Z")
    member = fx.create_member(location["id"])
    w1 = fx.sign_waiver(member["id"], has_contraindication=False)

    w2 = validate_success(api.create_waiver(
        member["id"], {"screening_answers": {"heart": True}, "has_contraindication": True},
        make_member_headers(member["id"])), 201)
    assert w2["status"] == "ACTIVE"
    assert validate_success(api.get_waiver(w1["id"], make_member_headers(member["id"])),
                            200)["status"] == "SUPERSEDED"
    assert fx.get_member(member["id"])["contraindication_flag"] is True


def test_location_reopen_clears_closed_block(api):
    """PRD §3.1: "A location may later be moved between OPEN and CLOSED: closing a location
    is permitted only while it is OPEN, and re-opening is permitted only while it is CLOSED."

    Design: Corner/state_machines/location_reopen_clears_closed_block
    """
    location = fx.create_location()
    validate_success(api.close_location(location["id"], MANAGER), 200)
    reopened = validate_success(api.open_location(location["id"], MANAGER), 200)
    assert reopened["status"] == "OPEN"


# ─── Queue B: validations (intro uniqueness) ─────────────────────────────────
def test_second_intro_pack_rejected(api):
    """PRD §3.6: "A member may buy the intro pack at most once: a purchase with is_intro true
    when the member's intro_offer_used is already true is rejected with
    ERR_INTRO_ALREADY_USED (HTTP 409). When an intro pack is purchased successfully, the
    member's intro_offer_used is set to true."

    Design: Corner/validations/error_intro_already_used_second_intro_pack
    """
    location = fx.create_location()
    fx.set_clock("2026-06-01T00:00:00Z")
    member = fx.create_member(location["id"])
    validate_success(api.create_credit_pack(
        member["id"], create_credit_pack_payload(4, True),
        make_member_headers(member["id"])), 201)

    res = api.create_credit_pack(
        member["id"], create_credit_pack_payload(4, True),
        make_member_headers(member["id"]))
    validate_error(res, "ERR_INTRO_ALREADY_USED")


# ─── Queue B: rbac ───────────────────────────────────────────────────────────
def test_unauthenticated_missing_role(api):
    """PRD §2.1: "If either header is missing, or if X-User-Role is not one of the recognized
    role names, the request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/rbac_unauthenticated_missing_headers
    """
    bad = {"X-User-ID": "someone", "X-User-Role": "Nobody", "Content-Type": "application/json"}
    res = api.create_location(create_location_payload(), bad)
    validate_error(res, "ERR_UNAUTHENTICATED")


def test_member_cannot_create_location(api):
    """PRD §2.1: "When the acting role is permitted to reach an endpoint but is not allowed to
    act on the specific target resource, the request is rejected with ERR_FORBIDDEN
    (HTTP 403)."
    PRD §4 endpoint table: POST /locations is authorized for PlatformAdmin only.

    Design: Corner/rbac/rbac_member_cannot_create_location
    """
    loc = fx.create_location(name="Base")
    member = fx.create_member(loc["id"])
    res = api.create_location(create_location_payload(name="Sneaky"),
                              make_member_headers(member["id"]))
    validate_error(res, "ERR_FORBIDDEN")


def test_member_cannot_freeze_other_members_subscription(api):
    """PRD §2.1: "A Member may act only on their own resources."
    PRD §2.1: "ownership checks on any resource that references a Member (its waivers,
    subscription, credit packs, and bookings) compare that resource's member foreign key to
    X-User-ID."

    Design: Corner/rbac/rbac_member_cannot_act_on_other_members_subscription
    """
    plan = fx.create_plan(**PLUS_PLAN)
    location = fx.create_location()
    fx.set_clock("2026-06-01T00:00:00Z")
    member_a = fx.create_member(location["id"])
    sub_a = validate_success(api.create_subscription(
        member_a["id"], create_subscription_payload(plan["id"]),
        make_member_headers(member_a["id"])), 201)
    member_b = fx.create_member(location["id"])

    res = api.freeze_subscription(
        sub_a["id"], create_freeze_payload(1), make_member_headers(member_b["id"]))
    validate_error(res, "ERR_FORBIDDEN")
    after = fx.get_subscription(sub_a["id"])
    assert after["status"] == "ACTIVE"


# ─── Queue B: OCC concurrency ────────────────────────────────────────────────
def test_stale_room_version_on_second_booking_rejected(api):
    """PRD §2.9: "Because a successful booking create increments the room's version (the
    room's occupied intervals are part of its booking surface), a second create that still
    carries the previously observed room version is stale and is rejected with
    ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_room_version_on_second_booking
    """
    s = fx.setup_bookable_scenario(service_overrides=COMPRESSION, plan_overrides=BASE_PLAN,
                                   clock="2026-06-15T09:00:00Z")
    room_v0 = fx.get_room(s.room["id"])["version"]
    # First booking on a non-overlapping slot bumps the room version.
    fx.book(s.member["id"], s.location["id"], s.room["id"], "2026-06-15T11:00:00Z", room_v0)

    res = api.create_booking(create_booking_payload(
        s.member["id"], s.location["id"], s.room["id"], "2026-06-15T13:00:00Z", room_v0),
        make_member_headers(s.member["id"]))
    validate_error(res, "ERR_STALE_VERSION")


def test_correct_room_version_second_booking_succeeds(api):
    """PRD §2.9: "A request to create a booking must carry expected_room_version holding the
    client's last observed version of the target Room."
    PRD §3.5: "On success the booking copies its service_type_id from the chosen room,
    computes the interval it occupies, debits the credits, and is created BOOKED".

    Design: Corner/cross_cutting_complexity_layers/occ_correct_room_version_succeeds
    """
    s = fx.setup_bookable_scenario(service_overrides=COMPRESSION, plan_overrides=PLUS_PLAN,
                                   clock="2026-06-15T09:00:00Z")
    room_v0 = fx.get_room(s.room["id"])["version"]
    fx.book(s.member["id"], s.location["id"], s.room["id"], "2026-06-15T11:00:00Z", room_v0)
    room_v1 = fx.get_room(s.room["id"])["version"]  # re-read fresh version

    b2 = validate_success(api.create_booking(create_booking_payload(
        s.member["id"], s.location["id"], s.room["id"], "2026-06-15T13:00:00Z", room_v1),
        make_member_headers(s.member["id"])), 201)
    assert b2["status"] == "BOOKED"
