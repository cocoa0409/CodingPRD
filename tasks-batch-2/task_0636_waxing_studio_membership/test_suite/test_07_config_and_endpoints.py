"""Configuration CRUD (locations, service types, members, memberships) plus
endpoint-surface behaviors: defaults, computed-field baselines, not-found,
required-field validation, type constraints, listing, PATCH, and filtered reads."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    setup_studio,
    set_clock,
    create_location,
    create_member,
    create_service_type,
    create_and_activate_membership,
    book_reservation,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    make_member_headers,
    make_technician_headers,
)
from test_helpers.factories import (
    create_location_payload,
    create_member_payload,
    create_service_type_payload,
    create_membership_payload,
    create_room_payload,
)

ADMIN = TEST_USERS["studio_admin_headers"]
FRONT = TEST_USERS["front_desk_headers"]


def test_create_location_returns_201_with_defaults(api):
    """PRD 3.1: "its `open_minute_of_day` and `close_minute_of_day` default to
    540 and 1200 if omitted, and its `deposit_required_cents` (default 1000) and
    `no_show_fee_cents` (default 2500)".
    PRD 2.4: "The `version` field starts at 1 when the resource is created".

    Creating a location with only name + state_code returns 201, version==1, and
    the documented defaults applied.

    Design: Corner/entities/create_location_returns_201_all_fields
    """
    data = validate_success(
        api.create_location(create_location_payload(name="Mall", state_code="CA"), ADMIN), 201)
    assert data["version"] == 1
    assert data["deposit_required_cents"] == 1000
    assert data["no_show_fee_cents"] == 2500
    assert data["open_minute_of_day"] == 540


def test_get_member_not_found(api):
    """PRD 2.9: "every path identifier and every foreign-key reference in a
    request must resolve to an existing resource ... the first reference that
    does not resolve causes the request to be rejected with `ERR_NOT_FOUND`".

    GET on a non-existent member id returns ERR_NOT_FOUND (404).

    Design: Corner/entities/get_member_not_found_returns_404
    """
    resp = api.get_member(NON_EXISTENT_UUID, FRONT)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_member_missing_email_invalid_request(api):
    """PRD 3.2: "A `Member` is registered by a `FrontDesk` operator or a
    `StudioAdmin` with a `home_location_id` naming their primary studio, a
    `full_name`, and a unique `email`."
    PRD 3.4: "request well-formedness — required fields present, enum values
    valid, integers in range (`ERR_INVALID_REQUEST`)".

    Registering a member without the required email field is rejected
    ERR_INVALID_REQUEST (422).

    Design: Corner/entities/create_member_missing_email_returns_invalid_request
    """
    loc = create_location(name="L")
    payload = {"home_location_id": loc["id"], "full_name": "NoEmail"}
    resp = api.create_member(payload, FRONT)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_service_type_defaults_applied(api):
    """PRD 3.1: "a `buffer_minutes` cleanup/turnover period appended after the
    slot (default 5) ... and a `credit_cost` (default 1) ... A service's
    `intro_eligible` flag (default false) ... and its `active` flag (default
    true)".

    Creating a service type omitting buffer_minutes, credit_cost, intro_eligible,
    and active applies the documented defaults.

    Design: Corner/entities/service_type_default_credit_cost_applied
    """
    data = validate_success(api.create_service_type(
        create_service_type_payload(name="Quick Brow", duration_minutes=15,
                                    list_price_cents=1500), ADMIN), 201)
    assert data["credit_cost"] == 1
    assert data["buffer_minutes"] == 5
    assert data["intro_eligible"] is False
    assert data["active"] is True


def test_member_computed_fields_start_at_baseline(api):
    """PRD 3.2: "At registration the member's computed fields start at their
    baseline: `intro_used` is false, `no_show_strike_count` is zero, and
    `wallet_credit_cents` — the prepaid store-credit balance where refunds and
    forfeits land, never permitted to go negative — is zero."

    A freshly registered member has intro_used==false, no_show_strike_count==0,
    wallet_credit_cents==0.

    Design: Corner/entities/member_computed_fields_initialized_zero
    """
    loc = create_location(name="L2")
    data = validate_success(api.create_member(
        create_member_payload(loc["id"], full_name="Fresh", email="fresh-uniq@x.com"), FRONT), 201)
    assert data["intro_used"] is False
    assert data["no_show_strike_count"] == 0
    assert data["wallet_credit_cents"] == 0


def test_membership_invalid_tier_rejected(api):
    """PRD 3.2: "choosing a `tier` of `BASIC`, `PLUS`, or `UNLIMITED`".
    PRD 3.4: "request well-formedness — required fields present, enum values
    valid, integers in range (`ERR_INVALID_REQUEST`)".

    Creating a membership with tier 'GOLD' (not a valid enum value) is rejected
    ERR_INVALID_REQUEST (422).

    Design: Corner/entities/membership_invalid_tier_enum_rejected
    """
    loc = create_location(name="L3")
    member = create_member(loc["id"])
    payload = create_membership_payload(member["id"], tier="GOLD",
                                        monthly_credit_grant=4, monthly_fee_cents=6000)
    resp = api.create_membership(payload, FRONT)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_room_nonexistent_location_not_found(api):
    """PRD 2.9: "every path identifier and every foreign-key reference in a
    request must resolve to an existing resource ... the first reference that
    does not resolve causes the request to be rejected with `ERR_NOT_FOUND`".

    Creating a room whose location_id does not exist is rejected ERR_NOT_FOUND
    (404).

    Design: Corner/entities/room_create_wrong_parent_location_not_found
    """
    resp = api.create_room(create_room_payload(NON_EXISTENT_UUID, label="Ghost"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_list_locations_pagination_envelope(api):
    """PRD 2.3: "List responses carry `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    After creating two locations, GET /studio/locations returns an array with
    total_count==2 and has_more==false.

    Design: Corner/entities/list_locations_pagination_envelope
    """
    create_location(name="A", state_code="CA")
    create_location(name="B", state_code="TX")
    data, meta = validate_paginated(api.list_locations(FRONT))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


def test_patch_service_type_price_bumps_version(api):
    """PRD 3.1: "A `StudioAdmin` may later edit a service; such an update is an
    optimistically-guarded write that requires `expected_servicetype_version` and
    may change `list_price_cents`, `duration_minutes`, `buffer_minutes`,
    `credit_cost`, `intro_eligible`, or `active`."
    PRD 2.4: "The `version` field starts at 1 when the resource is created and
    increases by exactly 1 on each mutation".

    PATCH with the matching expected_servicetype_version updates list_price_cents
    and bumps the version to 2.

    Design: Corner/endpoints/patch_service_type_price_update
    """
    svc = create_service_type(name="Patchable", duration_minutes=30, list_price_cents=2000)
    data = validate_success(api.update_service_type(
        svc["id"], {"expected_servicetype_version": svc["version"], "list_price_cents": 2500},
        ADMIN), 200)
    assert data["list_price_cents"] == 2500
    assert data["version"] == 2


def test_list_reservations_filtered_by_technician(api):
    """PRD 4: "reservations by `member_id`, `location_id`, `room_id`,
    `technician_id`, `service_type_id`, `membership_id`, and `booking_status`".

    GET /studio/reservations?technician_id={tech} returns only that technician's
    reservations (total_count==1 after one booking for that technician).

    Design: Corner/endpoints/list_reservations_filtered_by_technician
    """
    studio = setup_studio(clock="2026-06-15T12:00:00Z", location_overrides={"name": "Filt"},
                          service_overrides={"name": "QF", "duration_minutes": 30,
                                             "list_price_cents": 2000})
    book_reservation(member=studio["member"], location_id=studio["loc"]["id"],
                     room_id=studio["room"]["id"], technician_id=studio["tech"]["id"],
                     service_type_id=studio["svc"]["id"], start_utc="2026-06-16T10:00:00Z",
                     payment_method="WALK_IN", expected_room_version=studio["room"]["version"],
                     booked_by="frontdesk")
    data, meta = validate_paginated(api.list_reservations(
        make_technician_headers(studio["tech"]["id"]),
        params={"technician_id": studio["tech"]["id"]}))
    assert meta["total_count"] == 1


def test_membership_ledger_lists_activation_grant(api):
    """PRD 3.3: "Activation ... writes a `GRANT` ledger entry whose
    `delta_credits` is the `monthly_credit_grant` for a `BASIC` or `PLUS` pass".
    PRD 4: "| GET | `/studio/memberships/{id}/ledger` | List a membership's
    credit ledger |".

    The ledger of a just-activated PLUS membership lists the single GRANT entry
    written at activation (total_count==1).

    Design: Corner/endpoints/membership_ledger_lists_entries
    """
    loc = create_location(name="Ledg")
    member = create_member(loc["id"])
    mbr = create_and_activate_membership(member["id"], tier="PLUS",
                                         monthly_credit_grant=4, monthly_fee_cents=6000)
    data, meta = validate_paginated(api.list_membership_ledger(
        mbr["id"], make_member_headers(member["id"])))
    assert meta["total_count"] == 1
