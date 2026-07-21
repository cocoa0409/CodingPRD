"""Member onboarding, tier derivation, envelope/listing shape, and access control.

Queue B (Corner) translations for the entities / endpoints / rbac sections.
"""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_member,
    assert_points_bucket,
    create_member_payload,
    create_reservation_payload,
    create_resort_payload,
    make_member_headers,
    set_clock,
    setup_member_and_unit_type,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_create_member_computes_gold_tier(api):
    """PRD §3.1: "Ownership of at least 13,000 points confers `PLATINUM`; otherwise
    at least 7,000 points confers `GOLD`; otherwise at least 4,000 points confers
    `SILVER`; below 4,000 points the member is `STANDARD`."
    PRD §3.1: "Onboarding returns a new member whose `account_status` begins as
    `ACTIVE`, whose `current_use_year` is set to the calendar year of the logical
    clock at creation".

    Design: Corner/entities/corner_create_member_success_and_tier
    """
    set_clock("2026-07-01T00:00:00Z")
    resp = api.create_member(create_member_payload(full_name="Gold Owner", owned_points=7000), ADMIN)
    data = validate_success(resp, 201)
    assert_member(data)
    assert data["tier"] == "GOLD"
    assert data["account_status"] == "ACTIVE"
    assert data["current_use_year"] == 2026
    assert data["version"] == 1


def test_get_missing_member_not_found(api):
    """PRD §2.9: "the first identifier that does not resolve produces the
    corresponding not-found error before any later check runs: a missing member
    yields `ERR_MEMBER_NOT_FOUND`".

    Design: Corner/entities/corner_member_not_found
    """
    resp = api.get_member(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_FOUND.value, 404)


def test_fresh_bucket_available_equals_allotment(api):
    """PRD §3.1: "Every counter on that fresh bucket — `banked_in`, `banked_out`,
    `borrowed_in`, `borrowed_out`, `transferred_in`, `transferred_out`, and
    `points_used` — starts at zero, so its initial `points_available` equals the
    allotment."

    Design: Corner/entities/corner_points_bucket_available_computed
    """
    set_clock("2026-07-01T00:00:00Z")
    member = validate_success(api.create_member(create_member_payload(owned_points=5000), ADMIN), 201)
    buckets, _ = validate_paginated(api.list_member_points_buckets(member["id"], ADMIN))
    assert len(buckets) == 1
    bucket = buckets[0]
    assert_points_bucket(bucket)
    assert bucket["annual_allotment"] == 5000
    assert bucket["points_available"] == 5000
    assert bucket["status"] == "OPEN"


def test_get_member_envelope_shape(api):
    """PRD §2.2: "The response_type is either "object" for a single resource or
    "array" for a list of resources." PRD §2.2: "The api_request_id is a
    server-generated unique identifier for the request that starts with req_."

    Design: Corner/endpoints/corner_response_envelope_shape_on_get
    """
    set_clock("2026-07-01T00:00:00Z")
    member = validate_success(api.create_member(create_member_payload(owned_points=5000), ADMIN), 201)
    resp = api.get_member(member["id"], ADMIN)
    validate_success(resp, 200)
    body = resp.json()
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str) and body["meta"]["api_request_id"]
    assert body["data"]["id"] == member["id"]


def test_member_points_buckets_reverse_listing(api):
    """PRD §3.1: "At onboarding the system also creates the member's initial points
    ledger for the current use year: an OPEN PointsBucket whose use_year equals the
    clock's current year and whose annual_allotment equals the member's owned_points."

    Design: Corner/endpoints/corner_fk_reverse_points_buckets_listing
    """
    set_clock("2026-07-01T00:00:00Z")
    member = validate_success(api.create_member(create_member_payload(owned_points=5000), ADMIN), 201)
    buckets, _ = validate_paginated(api.list_member_points_buckets(member["id"], ADMIN))
    assert len(buckets) == 1
    assert buckets[0]["member_id"] == member["id"]
    assert buckets[0]["use_year"] == 2026


def test_unauthenticated_request_rejected(api, no_auth_headers):
    """PRD §2.1: "If either header is missing or not recognized, the request is
    rejected with ERR_UNAUTHENTICATED (HTTP 401). This check precedes every other
    form of validation."

    Design: Corner/rbac/corner_unauthenticated_missing_headers
    """
    set_clock("2026-07-01T00:00:00Z")
    member = validate_success(api.create_member(create_member_payload(owned_points=5000), ADMIN), 201)
    resp = api.get_member(member["id"], no_auth_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_member_creating_resort_unauthorized(api):
    """PRD §2.1: "When a request invokes an operation the caller's role is not
    permitted to perform, the request is rejected with ERR_UNAUTHORIZED (HTTP 403)."
    PRD §4: creating a resort is authorized for ClubAdmin only.

    Design: Corner/rbac/corner_unauthorized_member_creates_resort
    """
    set_clock("2026-07-01T00:00:00Z")
    member = validate_success(api.create_member(create_member_payload(owned_points=5000), ADMIN), 201)
    resp = api.create_resort(create_resort_payload(name="Rogue", region="XX"), make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_member_booking_for_other_member_forbidden(api):
    """PRD §2.1: "a Member may act only on a Reservation whose member_id is their
    own ... A member acting on a resource they do not own is rejected with
    ERR_FORBIDDEN (HTTP 403)."

    Design: Corner/rbac/corner_forbidden_member_books_for_other
    """
    world = setup_member_and_unit_type(owned_points=5000, total_units=2)
    member_a = validate_success(api.create_member(create_member_payload(owned_points=5000), ADMIN), 201)
    # Member A acts (X-User-ID = A) but the booking member_id is B (world["member"]).
    payload = create_reservation_payload(
        world["member"]["id"], world["unit_type"]["id"], world["bucket"]["id"],
        "2026-08-10", "2026-08-14",
    )
    resp = api.create_reservation(payload, make_member_headers(member_a["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, 403)
