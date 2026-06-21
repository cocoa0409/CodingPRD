"""Catalog & CRUD basics: organization/volunteer creation, defaults, required
fields, computed-field initialization, not-found, type constraints, listing,
immutability, archived-parent blocking, and the universal header gate.

Queue B (Corner) — sections: entities, rbac (header gate).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    create_organization_payload, create_volunteer_payload,
    create_skill_payload, create_volunteer_skill_payload,
    assert_organization, assert_volunteer, assert_volunteer_skill,
    TEST_USERS, NON_EXISTENT_UUID,
)
from test_helpers.fixtures import create_organization

COORD = TEST_USERS["shift_coordinator_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def test_create_organization_returns_201_with_defaults(api):
    """PRD §3.1: "A newly created organization has `status` `ACTIVE` and `version` 1."
    PRD §3.1: "created with a `name` and optionally with overrides for its
    `reliability_suspension_threshold` and `no_show_strike_limit`; absent overrides,
    those default to 40 and 3 respectively."

    Design: Corner/entities/create_organization_returns_201_with_defaults
    """
    resp = api.create_organization(create_organization_payload(name="Fresh Org"), COMPLIANCE)
    data = validate_success(resp, expected_status=201)
    assert_organization(data)
    assert data["status"] == "ACTIVE", f"expected ACTIVE, got {data['status']}"
    assert data["version"] == 1, f"expected version 1, got {data['version']}"
    assert data["reliability_suspension_threshold"] == 40
    assert data["no_show_strike_limit"] == 3


def test_create_volunteer_missing_email_returns_invalid_request(api):
    """PRD §2.7: "when a request omits a required input field or supplies one with
    the wrong type, it is rejected with `ERR_INVALID_REQUEST`."
    PRD §3.1: "registers a `Volunteer` by supplying the `organization_id`, the
    volunteer's `full_name`, and their `email`."

    Design: Corner/entities/create_volunteer_missing_email_returns_invalid_request
    """
    org = create_organization(headers=COMPLIANCE)
    payload = {"organization_id": org["id"], "full_name": "No Email"}
    resp = api.create_volunteer(payload, COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_volunteer_computed_fields_ignore_client_input(api):
    """PRD §3.1: "A freshly registered volunteer starts with `status` `ACTIVE`, a
    `bg_check_tier` of `NONE`, a `reliability_score` of 100, a `milestone_tier` of
    `NONE`, a `lifetime_no_show_count` of 0, and `total_verified_hours` of 0."

    Design: Corner/entities/volunteer_computed_fields_ignore_client_input
    """
    org = create_organization(headers=COORD)
    resp = api.create_volunteer(create_volunteer_payload(org["id"], full_name="New V"), COORD)
    data = validate_success(resp, expected_status=201)
    assert_volunteer(data)
    assert data["reliability_score"] == 100
    assert data["bg_check_tier"] == "NONE"
    assert data["milestone_tier"] == "NONE"
    assert data["total_verified_hours"] == 0
    assert data["lifetime_no_show_count"] == 0


def test_get_volunteer_nonexistent_returns_not_found(api):
    """PRD §2.7: "a missing volunteer `ERR_VOLUNTEER_NOT_FOUND`."

    Design: Corner/entities/get_volunteer_nonexistent_returns_not_found
    """
    create_organization(headers=COORD)  # one org so headers are valid context
    resp = api.get_volunteer(NON_EXISTENT_UUID, COORD)
    validate_error(resp, ApiErrorId.ERR_VOLUNTEER_NOT_FOUND.value)


def test_create_shift_invalid_times_rejected(api):
    """PRD §3.3: "an `ends_at` that must be strictly after `starts_at` (else
    `ERR_INVALID_SHIFT_TIMES`)."

    Design: Corner/entities/create_shift_invalid_times_rejected
    """
    org = create_organization(headers=COORD)
    opp = validate_success(
        api.create_opportunity({"organization_id": org["id"], "title": "Opp"}, COORD),
        expected_status=201,
    )
    resp = api.create_shift({
        "opportunity_id": opp["id"],
        "starts_at": "2026-07-01T12:00:00Z",
        "ends_at": "2026-07-01T12:00:00Z",
        "capacity": 2,
    }, COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_SHIFT_TIMES.value)


def test_create_shift_zero_capacity_rejected(api):
    """PRD §3.3: "a `capacity` that must be at least 1 (else `ERR_INVALID_CAPACITY`)."

    Design: Corner/entities/create_shift_zero_capacity_rejected
    """
    org = create_organization(headers=COORD)
    opp = validate_success(
        api.create_opportunity({"organization_id": org["id"], "title": "Opp"}, COORD),
        expected_status=201,
    )
    resp = api.create_shift({
        "opportunity_id": opp["id"],
        "starts_at": "2026-07-01T09:00:00Z",
        "ends_at": "2026-07-01T12:00:00Z",
        "capacity": 0,
    }, COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_CAPACITY.value)


def test_list_volunteers_pagination_envelope(api):
    """PRD §2.3: "Paginated and non-paginated list-based responses include the
    following fields in the `meta` object of the response envelope: `limit`,
    `offset`, `total_count`, and `has_more`."
    PRD §2.3: "The `limit` parameter specifies the maximum number of items to return."

    Design: Corner/entities/list_volunteers_pagination_envelope
    """
    org = create_organization(headers=COORD)
    api.create_volunteer(create_volunteer_payload(org["id"], full_name="A"), COORD)
    api.create_volunteer(create_volunteer_payload(org["id"], full_name="B"), COORD)
    resp = api.list_volunteers(COORD, params={"organization_id": org["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True, "expected has_more true with limit 1 of 2"
    assert len(data) == 1, f"expected 1 returned item, got {len(data)}"


def test_immutable_volunteerskill_has_no_version_field(api):
    """PRD §2.4: "`VolunteerSkill`, `WaiverAcceptance`, and `TrainingCompletion` are
    append-only membership and signature records that are immutable after creation.
    Each of these carries only an `id` and a `created_at` — they have neither an
    `updated_at` nor a `version` field, and they are never mutated in place."
    PRD §3.1: "a `proficiency` that defaults to `VERIFIED`."

    Design: Corner/entities/immutable_volunteerskill_has_no_version_field
    """
    org = create_organization(headers=COORD)
    vol = validate_success(
        api.create_volunteer(create_volunteer_payload(org["id"]), COORD), expected_status=201)
    skill = validate_success(
        api.create_skill(create_skill_payload(org["id"], code="FIRST_AID", label="First Aid"), COORD),
        expected_status=201)
    resp = api.create_volunteer_skill(
        create_volunteer_skill_payload(vol["id"], skill["id"]), COORD)
    data = validate_success(resp, expected_status=201)
    assert_volunteer_skill(data)
    assert data["proficiency"] == "VERIFIED"
    assert "version" not in data, "append-only VolunteerSkill must not carry a version field"


def test_create_volunteer_in_archived_org_rejected(api):
    """PRD §2.9: "While an organization is `ARCHIVED`, every attempt to create a child
    resource beneath it is blocked with `ERR_ORGANIZATION_ARCHIVED`."

    Design: Corner/entities/create_volunteer_in_archived_org_rejected
    """
    org = validate_success(
        api.create_organization(create_organization_payload(), COMPLIANCE), expected_status=201)
    validate_success(
        api.archive_organization(
            org["id"], {"expected_organization_version": org["version"]}, COMPLIANCE),
        expected_status=200)
    resp = api.create_volunteer(create_volunteer_payload(org["id"], full_name="Late V"), COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_ORGANIZATION_ARCHIVED.value)


def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "A request that omits either header, or that carries a malformed or
    unrecognized value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/rbac/missing_user_context_header_rejected
    """
    resp = api._request("GET", "/vm/organizations", headers={})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)
