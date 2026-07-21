"""CRUD envelope, required-field and not-found validation, pagination, and RBAC."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, is_valid_uuid, ApiErrorId,
    assert_travel_policy,
    make_policy, make_traveler,
    create_travel_policy_payload, create_group_booking_payload,
    make_traveler_headers,
    TEST_USERS,
)

MGR = TEST_USERS["travel_manager_headers"]


def test_create_traveler_missing_email_rejected(api):
    """PRD §3.1: "Each **traveler** is created with a `full_name`, an `email` (unique among
    active travelers), a `grade` ... the `policy_id` ... and a `home_iata` home-airport code."
    PRD §2.7: "well-formedness of the request body — required fields present, enum values
    legal, amounts and counts positive ... (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/create_traveler_missing_required_email_returns_invalid_request
    """
    policy = make_policy()
    payload = {"full_name": "No Email", "grade": "STANDARD",
               "policy_id": policy["id"], "home_iata": "JFK"}
    res = api.create_traveler(payload, MGR)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_group_booking_nonexistent_vendor_not_found(api):
    """PRD §2.7: "Every referenced resource id, whether it arrives as a path parameter or as
    a foreign key in the body, must exist; ids are validated left-to-right in the order they
    appear, and the first id that does not resolve yields `ERR_NOT_FOUND`."

    Design: Corner/entities/group_booking_nonexistent_vendor_returns_not_found
    """
    policy = make_policy()
    organizer = make_traveler(policy["id"], grade="MANAGER")
    res = api.create_group_booking(
        create_group_booking_payload("00000000-0000-4000-8000-000000000000",
                                     organizer["id"], block_size=3), MGR)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_list_travelers_pagination_envelope(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/list_travelers_pagination_envelope
    """
    policy = make_policy()
    make_traveler(policy["id"])
    make_traveler(policy["id"])
    res = api.list_travelers(MGR, params={"policy_id": policy["id"]})
    assert res.json()["response_type"] == "array"
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 2, f"two travelers created -> total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is False
    assert len(data) == 2


def test_create_policy_returns_object_envelope_with_version_one(api):
    """PRD §2.4: "`id`: a server-minted UUID with no type prefix, unique across the
    resource's collection."
    PRD §2.4: "`version`: an integer that starts at its initial value on creation and
    increments by one on every mutation."

    Design: Corner/entities/create_policy_response_envelope_object
    """
    res = api.create_travel_policy(create_travel_policy_payload(), MGR)
    assert res.json()["response_type"] == "object"
    policy = validate_success(res, 201)
    assert_travel_policy(policy)
    assert is_valid_uuid(policy["id"]), f"id must be a bare UUID, got {policy['id']!r}"
    assert policy["version"] == 1, f"new resource version must be 1, got {policy['version']}"
    assert policy.get("created_at"), "created_at must be present"


def test_create_policy_as_traveler_forbidden(api):
    """PRD §2.1: "If the headers are well-formed but the declared role is not permitted to
    perform the requested operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`."

    Design: Corner/endpoints/create_policy_as_traveler_forbidden_for_role
    """
    res = api.create_travel_policy(
        create_travel_policy_payload(name="X"),
        make_traveler_headers("11111111-1111-4111-8111-111111111111"))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


def test_create_policy_missing_user_context_rejected(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the acting
    principal, and `X-User-Role`, declaring the capacity in which they act. If either header
    is missing or malformed, the request is rejected with `ERR_MISSING_USER_CONTEXT`."

    Design: Corner/endpoints/create_policy_missing_auth_header_returns_400
    """
    res = api.create_travel_policy(create_travel_policy_payload(name="X"),
                                   {"Content-Type": "application/json"})
    validate_error(res, ApiErrorId.ERR_MISSING_USER_CONTEXT)
