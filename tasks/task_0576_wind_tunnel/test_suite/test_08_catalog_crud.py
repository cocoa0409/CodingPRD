"""Catalog CRUD, defaults, computed fields on create, not-found, validation, and
listing (PRD §3.1, §3.2, §3.4, §2.3, §2.8, §2.10)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    assign_session_instructor,
    create_member_payload,
    create_tunnel_payload,
    make_booking,
    make_flight,
    make_instructor,
    make_member,
    make_package,
    make_session,
    make_tunnel,
    validate_error,
    validate_paginated,
    validate_success,
)

MANAGER = TEST_USERS["manager_headers"]
FRONTDESK = TEST_USERS["frontdesk_headers"]


def test_create_tunnel_returns_201_with_fields(api):
    """PRD §3.1: "A new tunnel begins with its `status` set to `OPERATIONAL`."
    PRD §4: "Creating a new, standalone resource returns `201 Created`."

    Design: Corner/entities/create_tunnel_returns_201_with_fields
    """
    resp = api.create_tunnel(create_tunnel_payload(max_weight_kg=120), MANAGER)
    tunnel = validate_success(resp, 201)
    assert tunnel["status"] == "OPERATIONAL", tunnel["status"]
    assert tunnel["max_weight_kg"] == 120, tunnel["max_weight_kg"]


def test_get_member_not_found_returns_404(api):
    """PRD §2.8: "A single-resource retrieval validates the identifier in its path and
    returns `404` with the resource-specific not-found error (for example
    `ERR_SESSION_NOT_FOUND`) when it does not resolve."

    Design: Corner/entities/get_member_not_found_returns_404
    """
    resp = api.get_member(NON_EXISTENT_UUID, FRONTDESK)
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_FOUND.value)


def test_get_session_not_found_returns_404(api):
    """PRD §2.8: "A single-resource retrieval validates the identifier in its path and
    returns `404` with the resource-specific not-found error (for example
    `ERR_SESSION_NOT_FOUND`) when it does not resolve."

    Design: Corner/entities/get_session_not_found_returns_404
    """
    resp = api.get_session(NON_EXISTENT_UUID, FRONTDESK)
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_FOUND.value)


def test_create_member_defaults_empty_health_flags(api):
    """PRD §3.2: "an optional list of `health_flags` describing declared health
    conditions, which defaults to an empty list."
    PRD §3.2: "A newly registered member starts with every counter and balance at zero
    ... and a `membership_tier` of `NONE`."

    Design: Corner/entities/create_member_defaults_empty_health_flags
    """
    resp = api.create_member(create_member_payload(name="Ada", weight_kg=80), FRONTDESK)
    member = validate_success(resp, 201)
    assert member["health_flags"] == [], member["health_flags"]
    assert member["membership_tier"] == "NONE", member["membership_tier"]


def test_booking_missing_package_id_returns_validation(api):
    """PRD §2.10: "Malformed bodies — a missing required field, a wrong type, or an
    invalid enum value — are rejected with `ERR_VALIDATION` (400)."

    Design: Corner/entities/booking_missing_package_id_returns_validation
    """
    member = make_member(api, name="Ada", weight_kg=80)
    resp = api.create_booking(
        {"member_id": member["id"], "booking_type": "WALK_IN", "party_size": 1}, FRONTDESK
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_booking_invalid_type_enum_returns_validation(api):
    """PRD §2.10: "Malformed bodies — a missing required field, a wrong type, or an
    invalid enum value — are rejected with `ERR_VALIDATION` (400)."

    Design: Corner/entities/booking_invalid_type_enum_returns_validation
    """
    pkg = make_package(api, included_minutes=2, base_price_cents=6000)
    member = make_member(api, name="Ada", weight_kg=80)
    resp = api.create_booking(
        {"member_id": member["id"], "package_id": pkg["id"],
         "booking_type": "DROP_IN", "party_size": 1},
        FRONTDESK,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_session_seats_available_computed_on_create(api):
    """PRD §3.4: "A new session begins with `op_status` at `OPEN`, `staffing_status` at
    `UNSTAFFED`, `instructor_id` null, `seats_taken` at 0, and `seats_available` equal
    to its capacity."

    Design: Corner/entities/session_seats_available_computed_on_create
    """
    tunnel = make_tunnel(api)
    session = make_session(api, tunnel["id"], capacity=4)
    assert session["seats_taken"] == 0, session["seats_taken"]
    assert session["seats_available"] == 4, session["seats_available"]


def test_tunnel_maintenance_toggle_updates_status(api):
    """PRD §3.1: "A manager may later toggle that status through a maintenance
    capability that accepts a `mode` of either `OPERATIONAL` or `MAINTENANCE` and
    writes it to `status`".

    Design: Corner/endpoints/tunnel_maintenance_toggle_updates_status
    """
    tunnel = make_tunnel(api)
    validate_success(api.tunnel_maintenance(tunnel["id"], {"mode": "MAINTENANCE"}, MANAGER), 200)
    restored = validate_success(
        api.tunnel_maintenance(tunnel["id"], {"mode": "OPERATIONAL"}, MANAGER), 200
    )
    assert restored["status"] == "OPERATIONAL", restored["status"]


def test_list_flights_by_session_pagination(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; when omitted
    it defaults to 10, with a minimum of 1 and a maximum of 100."
    PRD §2.8: "flights by `booking_id`, `session_id`, `member_id`, and `status`".

    Design: Corner/entities/list_flights_by_session_pagination
    """
    tunnel = make_tunnel(api)
    instructor = make_instructor(api)
    pkg = make_package(api, included_minutes=2, base_price_cents=6000)
    m1 = make_member(api, name="M1", weight_kg=80)
    m2 = make_member(api, name="M2", weight_kg=80)
    b1 = make_booking(api, m1["id"], pkg["id"], party_size=1)
    b2 = make_booking(api, m2["id"], pkg["id"], party_size=1)
    session = make_session(api, tunnel["id"], capacity=4)
    assign_session_instructor(api, session["id"], instructor["id"], session["version"])
    make_flight(api, b1["id"], session["id"], m1["id"], 2)
    make_flight(api, b2["id"], session["id"], m2["id"], 2)
    data, meta = validate_paginated(
        api.list_flights(FRONTDESK, params={"session_id": session["id"], "limit": 1})
    )
    assert meta["total_count"] == 2, meta["total_count"]
    assert meta["has_more"] is True, meta["has_more"]
    assert len(data) == 1, len(data)
