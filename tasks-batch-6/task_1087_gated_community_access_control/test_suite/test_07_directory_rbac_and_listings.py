"""Directory / resident CRUD corners, RBAC and ownership enforcement, terminal
lockdown, authentication, and list-endpoint envelope behavior.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    create_community, create_resident, create_vehicle,
    setup_community_and_resident,
    make_resident_headers,
    ADMIN,
)
from test_helpers.test_users import ANONYMOUS_HEADERS


def test_get_nonexistent_resident_returns_not_found(api):
    """PRD §2.9: "The first identifier that does not resolve to an existing
    resource causes the request to be rejected with that resource's specific
    not-found error (for example, `ERR_COMMUNITY_NOT_FOUND`,
    `ERR_RESIDENT_NOT_FOUND`, ...".

    Design: Corner/entities/get_nonexistent_resident_returns_not_found
    """
    create_community()
    validate_error(api.get_resident(NON_EXISTENT_UUID, ADMIN),
                   ApiErrorId.ERR_RESIDENT_NOT_FOUND.value, expected_status=404)


def test_create_resident_missing_email_returns_validation(api):
    """PRD §2.10: "Basic body well-formedness — missing required fields, unknown
    enum values, out-of-range numbers — surfaces as `ERR_VALIDATION`."

    Design: Corner/entities/create_resident_missing_email_returns_validation
    """
    community = create_community()
    resp = api.create_resident(
        {"community_id": community["id"], "full_name": "No Email", "resident_type": "OWNER"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=400)


def test_resident_callbox_code_minted_by_system(api):
    """PRD §3.1: "On creation the resident's `status` is `ACTIVE`, `standing` is
    `GOOD`, and `outstanding_balance_cents` is zero, and the system mints a
    numeric `callbox_code` used to dial the unit from the gate callbox."

    Design: Corner/entities/resident_callbox_code_minted_by_system
    """
    community = create_community()
    resident = validate_success(api.create_resident(
        {"community_id": community["id"], "full_name": "Cal Callbox",
         "email": "cal@x.com", "resident_type": "OWNER"}, ADMIN), expected_status=201)
    assert resident["callbox_code"] is not None and str(resident["callbox_code"]) != ""
    assert resident["status"] == "ACTIVE"
    assert resident["standing"] == "GOOD"


def test_resident_directory_listed_defaults_true(api):
    """PRD §3.1: "`phone`, `unit_label`, and `lot_number` default to null and
    `directory_listed` defaults to true."

    Design: Corner/entities/resident_directory_listed_defaults_true
    """
    community = create_community()
    resident = validate_success(api.create_resident(
        {"community_id": community["id"], "full_name": "Deb Default",
         "email": "deb@x.com", "resident_type": "TENANT"}, ADMIN), expected_status=201)
    assert resident["directory_listed"] is True


def test_reactivate_movedout_resident_returns_invalid_state(api):
    """PRD §3.1: "or move an `ACTIVE` or `SUSPENDED` resident out to the terminal
    `MOVED_OUT`."
    PRD §2.10: "whether the target resource's current state permits the requested
    transition (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/reactivate_movedout_resident_returns_invalid_state
    """
    _, resident = setup_community_and_resident(resident_overrides={"full_name": "Gone Gary"})
    validate_success(api.transition_resident(resident["id"], {"to_status": "MOVED_OUT"}, ADMIN))
    validate_error(api.transition_resident(resident["id"], {"to_status": "ACTIVE"}, ADMIN),
                   ApiErrorId.ERR_INVALID_STATE.value)


def test_missing_role_header_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or `X-User-Role` does not name a
    role the system recognizes, the request is rejected with
    `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/missing_role_header_returns_unauthenticated
    """
    community = create_community()
    validate_error(api.get_community(community["id"], ANONYMOUS_HEADERS),
                   ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)


def test_resident_creates_amenity_returns_unauthorized(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not
    permitted to perform the requested operation — or a resident attempts to act
    on another resident's resource — the request is rejected with
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/resident_creates_amenity_returns_unauthorized
    """
    community, resident = setup_community_and_resident(resident_overrides={"full_name": "Rita Role"})
    resp = api.create_amenity(
        {"community_id": community["id"], "name": "Rogue Pool", "amenity_type": "POOL",
         "capacity": 5, "hourly_fee_cents": 0, "deposit_cents": 0,
         "open_hour": 6, "close_hour": 22}, make_resident_headers(resident["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)


def test_resident_creates_vehicle_for_other_resident_returns_unauthorized(api):
    """PRD §2.1: "ownership checks on any resource that references a resident
    compare that resource's foreign-key field — `resident_id` on a vehicle,
    reservation, or violation, or `sponsor_resident_id` on a pass — to
    `X-User-ID`. A resident acting on a resource whose owning resident is not
    themselves is refused with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/resident_creates_vehicle_for_other_resident_returns_unauthorized
    """
    community, resident_a = setup_community_and_resident(resident_overrides={"full_name": "Owner A", "email": "a@x.com"})
    resident_b = create_resident(community["id"], full_name="Owner B", email="b@x.com", resident_type="OWNER")
    resp = api.create_vehicle(
        {"resident_id": resident_b["id"], "plate": "MINE01", "plate_state": "CA"},
        make_resident_headers(resident_a["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_list_residents_pagination_envelope(api):
    """PRD §2.3: "Each list response includes `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object, where `total_count` reflects the full
    number of matching resources before the page window is applied and `has_more`
    indicates whether any matching resources remain beyond the current page."

    Design: Corner/endpoints/list_residents_pagination_envelope
    """
    community = create_community()
    create_resident(community["id"], full_name="One One", email="one@x.com", resident_type="OWNER")
    create_resident(community["id"], full_name="Two Two", email="two@x.com", resident_type="TENANT")
    data, meta = validate_paginated(api.list_residents(ADMIN, params={"community_id": community["id"], "limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_list_vehicles_by_resident_reverse_lookup(api):
    """PRD §3.2: "Vehicles can be listed and filtered by `resident_id` and
    `status`."

    Design: Corner/endpoints/list_vehicles_by_resident_reverse_lookup
    """
    community, resident = setup_community_and_resident(resident_overrides={"full_name": "Val Vehicle"})
    vehicle = create_vehicle(resident["id"], plate="FIND01", plate_state="CA")
    data, meta = validate_paginated(api.list_vehicles(ADMIN, params={"resident_id": resident["id"]}))
    assert len(data) == 1
    assert data[0]["id"] == vehicle["id"]
