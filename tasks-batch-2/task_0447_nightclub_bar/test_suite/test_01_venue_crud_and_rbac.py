"""Venue creation/CRUD, listing, computed-field exposure, and RBAC denials.

Each test translates exactly one corner-design instance (queue B).
"""
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    create_venue_payload, create_id_check_payload, create_tab_payload, create_tab_item_payload,
    TEST_USERS,
)
from test_helpers.constants import NONEXISTENT_UUID

ADMIN = TEST_USERS["platform_admin_headers"]
DOOR = TEST_USERS["door_host_headers"]
BAR = TEST_USERS["bartender_headers"]


def test_create_venue_returns_201_with_defaults_applied(api):
    """PRD §3.1: "Four further inputs are optional and fall back to defaults when
    omitted: `last_call_offset_minutes` ... defaults to 30 ...; `cover_base_cents`
    ... defaults to 2000 ...; `cover_surge_pct` ... defaults to 0.5 ...; and
    `max_alcohol_strikes` ... defaults to 4 ...."
    PRD §3.1: "On creation the venue's `posture` is `OPEN`, its `occupancy_count`
    ... is 0, its `tabs_open_count` ... is 0, and its `version` is 1."

    Design: Corner/entities/create_venue_returns_201_with_defaults_applied
    """
    res = api.create_venue(
        create_venue_payload(name="Club", fire_code_capacity=50,
                             closing_time_utc="2026-03-16T06:00:00Z"),
        ADMIN,
    )
    venue = validate_success(res, 201)
    assert venue["version"] == 1
    assert venue["posture"] == "OPEN"
    assert venue["occupancy_count"] == 0
    assert venue["cover_base_cents"] == 2000
    assert venue["last_call_offset_minutes"] == 30
    assert venue["max_alcohol_strikes"] == 4


def test_create_venue_missing_fire_code_capacity_returns_invalid_request(api):
    """PRD §3.10: "Then the request shape is validated — a missing required field,
    a wrong type, an out-of-range enum value, or a negative value where a
    non-negative one is required yields `ERR_INVALID_REQUEST`."
    PRD §3.1: "The creator supplies the venue's display `name`, its
    `fire_code_capacity` ..., and the scheduled `closing_time_utc` ...."

    Design: Corner/entities/create_venue_missing_fire_code_capacity_returns_invalid_request
    """
    payload = {"name": "Club", "closing_time_utc": "2026-03-16T06:00:00Z"}
    res = api.create_venue(payload, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_get_venue_nonexistent_returns_not_found(api):
    """PRD §3.10: "path identifiers are resolved left to right, and an unresolved
    path id yields `ERR_NOT_FOUND`."

    Design: Corner/entities/get_venue_nonexistent_returns_not_found
    """
    res = api.get_venue(NONEXISTENT_UUID, ADMIN)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_list_venues_paginated_envelope_fields(api):
    """PRD §2.3: "Paginated list responses include the following fields in the
    `meta` object of the response envelope: `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/entities/list_venues_paginated_envelope_fields
    """
    api.create_venue(create_venue_payload(name="A"), ADMIN)
    api.create_venue(create_venue_payload(name="B"), ADMIN)
    data, meta = validate_paginated(api.list_venues(ADMIN, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_idcheck_computed_outcome_input_ignored(api):
    """PRD §3.3: "The server computes the patron's age and the verification
    `outcome` and stores both, along with a `refusal_reason` note when the check
    fails."
    PRD §3.3: "Otherwise the `outcome` is `PASS` and the `refusal_reason` is null."

    Design: Corner/entities/idcheck_computed_outcome_input_ignored
    """
    validate_success(api.set_clock("2026-03-15T20:00:00Z", ADMIN), 200)
    venue = validate_success(api.create_venue(create_venue_payload(name="V"), ADMIN), 201)
    res = api.create_id_check(
        create_id_check_payload(venue["id"], patron_name="A",
                                date_of_birth="1990-01-01", id_expiry="2030-01-01"),
        DOOR,
    )
    idc = validate_success(res, 201)
    assert idc["outcome"] == "PASS"
    assert idc["refusal_reason"] is None
    assert idc["computed_age_years"] == 36


def test_tabitem_immutable_no_version_field(api):
    """PRD §2.4: "A Tab Item (a single bar-POS line) carries only `id` and
    `created_at`; it has no `updated_at` and no `version`. A line is effectively
    immutable once written, save for the single `voided` flag described later ...."

    Design: Corner/entities/tabitem_immutable_no_version_field
    """
    venue = validate_success(api.create_venue(create_venue_payload(name="V"), ADMIN), 201)
    tab = validate_success(
        api.create_tab(create_tab_payload(venue["id"], patron_name="T", preauth_cents=50000), BAR),
        201,
    )
    item = validate_success(
        api.add_tab_item(tab["id"], create_tab_item_payload(
            name="Water", category="NA_BEVERAGE", qty=1, unit_price_cents=500), BAR),
        201,
    )
    data, _ = validate_paginated(api.list_tab_items(tab["id"], BAR))
    assert data[0]["voided"] is False
    assert data[0]["id"] == item["id"]
    assert "version" not in data[0]
    assert "updated_at" not in data[0]


def test_bartender_cannot_create_venue_returns_forbidden(api):
    """PRD §2.1: "The `PlatformAdmin` is the operator superset ... and it
    exclusively holds the authority to create a venue ...."
    PRD §2.1: "When the headers are well-formed but the named role is not permitted
    to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/bartender_cannot_create_venue_returns_forbidden
    """
    res = api.create_venue(create_venue_payload(name="X"), BAR)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_doorhost_cannot_open_tab_returns_forbidden(api):
    """PRD §2.1: "A `Bartender` owns bar tabs and their line items."
    PRD §2.1: "When the headers are well-formed but the named role is not permitted
    to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/doorhost_cannot_open_tab_returns_forbidden
    """
    venue = validate_success(api.create_venue(create_venue_payload(name="V"), ADMIN), 201)
    res = api.create_tab(create_tab_payload(venue["id"], patron_name="P", preauth_cents=5000), DOOR)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_missing_headers_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` does not name one
    of these five roles, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    res = api.list_venues({})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)
