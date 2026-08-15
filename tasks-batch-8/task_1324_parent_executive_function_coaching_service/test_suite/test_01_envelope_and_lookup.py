"""Envelope shape, pagination, identifier lookup, and request-shape validation."""
from test_helpers import (
    UNKNOWN_UUID,
    ApiErrorId,
    assert_family,
    create_client_payload,
    create_family,
    schedule_session_ok,
    setup_active_plan_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_family_list_pagination_defaults_and_params(api, admin_headers):
    """PRD §2.3: "The `limit` parameter caps the number of returned items: it
    defaults to 10 when omitted, accepts a minimum of 1, and accepts a maximum
    of 100. The `offset` parameter specifies how many items to skip and defaults
    to 0."
    PRD §2.3: "Unless an endpoint states otherwise, every list is sorted by
    `created_at` in ascending order. The `meta` object of a list response
    includes the pagination fields `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/endpoints/family_list_pagination_defaults_and_params
    """
    fam1 = create_family("Fam P1", "p1@example.com")
    fam2 = create_family("Fam P2", "p2@example.com")

    # Defaults: limit 10, offset 0 — both families on one page.
    data, meta = validate_paginated(api.list_families(admin_headers))
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert len(data) == 2

    # Explicit limit 1: first page holds the first-created family.
    data1, meta1 = validate_paginated(
        api.list_families(admin_headers, params={"limit": 1, "offset": 0})
    )
    assert meta1["limit"] == 1
    assert meta1["total_count"] == 2
    assert meta1["has_more"] is True
    assert data1[0]["id"] == fam1["id"]

    # Offset 1 returns the second family.
    data2, meta2 = validate_paginated(
        api.list_families(admin_headers, params={"limit": 1, "offset": 1})
    )
    assert meta2["offset"] == 1
    assert data2[0]["id"] == fam2["id"]


def test_sessions_reverse_lookup_under_plan(api, admin_headers):
    """PRD §4: "| GET | `/api/plans/{id}/sessions` | Sessions of a plan | PracticeAdmin, Coach, FamilyMember |" — the
    sub-resource list returns exactly the sessions owned by that plan.

    Design: Corner/endpoints/sessions_reverse_lookup_under_plan
    """
    ctx = setup_active_plan_scenario(
        account_name="Fam RL",
        primary_email="rl@example.com",
        package={"track": "INDIVIDUAL", "credits_total": 2},
    )
    plan, coach, package = ctx["plans"][0], ctx["coach"], ctx["packages"][0]
    session = schedule_session_ok(
        plan["id"], coach["id"], package["id"],
        "2026-08-05T15:00:00Z", "2026-08-05T16:00:00Z",
    )
    listed = validate_success(api.list_plan_sessions(plan["id"], admin_headers))
    assert isinstance(listed, list)
    assert [s["id"] for s in listed] == [session["id"]]


def test_family_get_not_found_returns_404(api, admin_headers):
    """PRD §2.8: "For any such request the system validates identifiers
    sequentially, left to right: the first path identifier that does not
    correspond to an existing resource produces `ERR_NOT_FOUND` (HTTP 404), and
    no further identifiers or body-referenced ids are examined."

    Design: Corner/entities/family_get_not_found_returns_404
    """
    resp = api.get_family(UNKNOWN_UUID, admin_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_unknown_session_get_not_found(api, admin_headers):
    """PRD §2.8: "the first path identifier that does not correspond to an
    existing resource produces `ERR_NOT_FOUND` (HTTP 404), and no further
    identifiers or body-referenced ids are examined."

    Design: Corner/errors/unknown_session_get_not_found
    """
    resp = api.get_session(UNKNOWN_UUID, admin_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_missing_auth_headers_returns_401(api):
    """PRD §2.1: "A request missing either header, or presenting a role outside
    this enumeration, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/errors/missing_auth_headers_returns_401
    """
    resp = api.list_families(headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_existence_beats_shape_validation(api, admin_headers):
    """PRD §2.8: "the first path identifier that does not correspond to an
    existing resource produces `ERR_NOT_FOUND` (HTTP 404), and no further
    identifiers or body-referenced ids are examined."
    PRD §2.8: "then existence of every path and body-referenced id, left to
    right (`ERR_NOT_FOUND`); then request shape — required fields present, enum
    members valid, ranges valid (`ERR_VALIDATION`)"

    Design: Corner/validations/existence_beats_shape_validation
    """
    resp = api.transition_family(UNKNOWN_UUID, "BOGUS", admin_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_client_create_missing_required_field_returns_400(api, admin_headers):
    """PRD §3.1: "creating a Client requires a `full_name`, a `date_of_birth`,
    and a coaching `track` of `INDIVIDUAL`, `GROUP`, or `HYBRID`"
    PRD §2.8: "then request shape — required fields present, enum members
    valid, ranges valid (`ERR_VALIDATION`)"

    Design: Corner/entities/client_create_missing_required_field_returns_400
    """
    family = create_family("Fam RF", "rf@example.com")
    payload = {"full_name": "Kid RF", "date_of_birth": "2014-01-01"}
    resp = api.create_client(family["id"], payload, admin_headers)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_client_create_invalid_enum_track_returns_400(api, admin_headers):
    """PRD §3.1: "creating a Client requires a `full_name`, a `date_of_birth`,
    and a coaching `track` of `INDIVIDUAL`, `GROUP`, or `HYBRID`"
    PRD §2.8: "then request shape — required fields present, enum members
    valid, ranges valid (`ERR_VALIDATION`)"

    Design: Corner/entities/client_create_invalid_enum_track_returns_400
    """
    family = create_family("Fam IE", "ie@example.com")
    resp = api.create_client(
        family["id"],
        create_client_payload(full_name="Kid IE", track="DELUXE"),
        admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)
