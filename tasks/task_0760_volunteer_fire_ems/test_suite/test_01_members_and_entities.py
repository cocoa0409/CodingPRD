"""Member creation, field validation, listing, and authentication.

Queue B (Corner) translations for the `entities`, `endpoints`, and `rbac` sections.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    is_valid_uuid,
    ApiErrorId,
    CHIEF,
    NON_EXISTENT_UUID,
    build_user_headers,
    create_member_payload,
    create_station_with_apparatus,
    create_officer,
    create_draft_shift,
    assert_member,
)
from test_helpers.factories import create_duty_shift_payload, unique_email


def test_create_member_starts_probationary(api):
    """PRD §3.1: "A new member always begins with `membership_status` of
    `PROBATIONARY`, is not response-eligible, has zero year-to-date points, and,
    unless an opening `dues_balance_cents` is supplied, a dues balance of zero."

    Design: Corner/entities/corner_member_create_success
    """
    resp = api.create_member(
        create_member_payload(full_name="Jane Doe", email="jane@x.com", role_class="FIREFIGHTER"),
        CHIEF,
    )
    data = validate_success(resp, 201)
    assert_member(data)
    assert data["membership_status"] == "PROBATIONARY"
    assert data["points_ytd"] == 0
    assert data["response_eligible"] is False


def test_create_member_version_starts_at_one(api):
    """PRD §2.4: "The `version` is an integer that begins at 1 and increments by
    one on every mutation of the resource; it is the value clients echo back for
    optimistic concurrency control (§2.7)."

    Design: Corner/entities/corner_member_create_success
    """
    data = validate_success(
        api.create_member(create_member_payload(role_class="EMT"), CHIEF), 201
    )
    assert data["version"] == 1


def test_get_member_not_found(api):
    """PRD §2.8: "those ids are validated left to right, and the **first** id that
    does not resolve determines the not-found error returned. The specific
    not-found errors are `ERR_MEMBER_NOT_FOUND`, ..."

    Design: Corner/entities/corner_member_not_found
    """
    resp = api.get_member(NON_EXISTENT_UUID, CHIEF)
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_FOUND.value)


def test_create_member_missing_role_class_rejected(api):
    """PRD §2.6: "**Field validity** — required body fields are present, enum
    fields hold in-range values, numbers that must be positive are positive, and
    any `end_at` is strictly later than its `start_at`, else `ERR_VALIDATION`."

    Design: Corner/entities/corner_member_missing_required_field
    """
    payload = {"full_name": "No Role", "email": "norole@x.com", "join_date": "2026-01-01T00:00:00Z"}
    validate_error(api.create_member(payload, CHIEF), ApiErrorId.ERR_VALIDATION.value)


def test_create_member_bad_enum_role_class_rejected(api):
    """PRD §2.6: "**Field validity** — required body fields are present, enum
    fields hold in-range values, numbers that must be positive are positive, and
    any `end_at` is strictly later than its `start_at`, else `ERR_VALIDATION`."

    Design: Corner/entities/corner_member_bad_enum_role_class
    """
    payload = create_member_payload(role_class="CAPTAIN", email="bad@x.com")
    validate_error(api.create_member(payload, CHIEF), ApiErrorId.ERR_VALIDATION.value)


def test_create_member_system_fields_are_server_generated(api):
    """PRD §3.1: "A new member always begins with `membership_status` of
    `PROBATIONARY`, is not response-eligible, has zero year-to-date points, and,
    unless an opening `dues_balance_cents` is supplied, a dues balance of zero."
    PRD §2.4: "The `id` is a server-minted UUID with no type prefix."

    Design: Corner/entities/corner_member_system_fields_generated
    """
    data = validate_success(
        api.create_member(create_member_payload(role_class="EMT", email="sysf@x.com"), CHIEF), 201
    )
    assert is_valid_uuid(data["id"])
    assert data["version"] == 1
    assert data["points_ytd"] == 0


def test_create_duty_shift_end_before_start_rejected(api):
    """PRD §2.6: "... and any `end_at` is strictly later than its `start_at`, else
    `ERR_VALIDATION`."

    Design: Corner/entities/corner_duty_shift_end_before_start
    """
    off_id, off = create_officer(api)
    station, apparatus = create_station_with_apparatus(api)
    payload = create_duty_shift_payload(
        station_id=station["id"],
        apparatus_id=apparatus["id"],
        start_at="2026-06-01T18:00:00Z",
        end_at="2026-06-01T06:00:00Z",
    )
    validate_error(api.create_duty_shift(payload, off), ApiErrorId.ERR_VALIDATION.value)


def test_list_members_pagination_envelope(api):
    """PRD §2.3: "Each list response echoes `limit` and `offset` in the `meta`
    block and additionally reports `total_count` (the total number of records
    matching the filter, before pagination) and `has_more` (true when records
    remain beyond the current page)."

    Design: Corner/endpoints/corner_members_list_pagination
    """
    for i in range(3):
        get_success_data(
            api.create_member(create_member_payload(email=f"p{i}@x.com", role_class="EMT"), CHIEF)
        )
    data, meta = validate_paginated(api.list_members(CHIEF, params={"limit": 2, "offset": 0}))
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True


def test_missing_role_header_rejected(api):
    """PRD §2.1: "If either header is missing, or `X-User-Role` does not name one
    of the known roles, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401) before any other processing."

    Design: Corner/rbac/corner_unauthenticated_missing_headers
    """
    nobody = build_user_headers("nobody-1", "Nobody")
    validate_error(api.create_station({"name": "NoAuth"}, nobody), ApiErrorId.ERR_UNAUTHENTICATED.value)
