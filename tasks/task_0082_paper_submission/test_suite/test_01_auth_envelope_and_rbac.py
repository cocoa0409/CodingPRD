"""Authentication, RBAC, response envelope, and pagination (PRD §2.1–§2.3, §2.4)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    create_author_payload,
    create_reviewer_payload,
    register_author,
    register_reviewer,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Missing or unparseable user-context headers (PRD §2.1)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("headers", [
    {},
    {"X-User-ID": "test-user-1"},
    {"X-User-Role": "PlatformAdmin"},
    {"X-User-ID": "", "X-User-Role": "PlatformAdmin"},
    {"X-User-ID": "test-user-1", "X-User-Role": ""},
])
def test_missing_or_empty_user_context_headers_rejected(api, headers):
    """PRD §2.1: "Requests that omit either header, or carry an
    unparseable value, are rejected with ERR_AUTH_REQUIRED (HTTP 401)."
    """
    res = api.create_author(create_author_payload(), headers)
    validate_error(res, ApiErrorId.ERR_AUTH_REQUIRED.value)


@pytest.mark.parametrize("bad_role", [
    "platformadmin",   # case-sensitive: lowercase rejected
    "ADMIN",           # not in enum
    "Unknown",
])
def test_unknown_role_header_rejected(api, bad_role):
    """PRD §2.1: "Role names are case-sensitive and must be one of:
    PlatformAdmin, Author, EditorInChief, SectionEditor, AssociateEditor,
    Reviewer."
    """
    headers = build_user_headers("test-user-1", bad_role)
    res = api.create_author(create_author_payload(), headers)
    # PRD §2.1 says ERR_AUTH_REQUIRED is raised when X-User-Role is
    # unparseable. A role not in the enum is unparseable as a role value.
    validate_error(res, ApiErrorId.ERR_AUTH_REQUIRED.value)


# ---------------------------------------------------------------------------
# Role authorization (PRD §2.1, §4)
# ---------------------------------------------------------------------------
def test_reviewer_creation_requires_platform_admin(api, author_fallback_headers):
    """PRD §4: "POST /reviewers ... Authorized Role(s): PlatformAdmin."
    PRD §2.1: "Requests whose role is not authorized for the requested
    endpoint are rejected with ERR_FORBIDDEN (HTTP 403)."
    """
    res = api.create_reviewer(create_reviewer_payload(), author_fallback_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


def test_editor_creation_requires_platform_admin(api, author_fallback_headers):
    """PRD §4: "POST /editors ... Authorized Role(s): PlatformAdmin."
    PRD §2.1: "Requests whose role is not authorized for the requested
    endpoint are rejected with ERR_FORBIDDEN (HTTP 403)."
    """
    from test_helpers import create_editor_payload
    res = api.create_editor(
        create_editor_payload(role="EDITOR_IN_CHIEF"),
        author_fallback_headers,
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


def test_clock_advance_requires_platform_admin(api, author_fallback_headers):
    """PRD §4: "POST /_clock/advance ... Authorized Role(s): PlatformAdmin."
    PRD §2.1: "Requests whose role is not authorized for the requested
    endpoint are rejected with ERR_FORBIDDEN (HTTP 403)."
    """
    res = api.advance_clock({"to": "2099-01-01T00:00:00.000Z"},
                            author_fallback_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


def test_get_editors_list_forbidden_for_reviewer(api, reviewer_fallback_headers):
    """PRD §4: "GET /editors ... Authorized Role(s): PlatformAdmin,
    EditorInChief, SectionEditor." Reviewer is not in the list.
    PRD §2.1: "Requests whose role is not authorized for the requested
    endpoint are rejected with ERR_FORBIDDEN (HTTP 403)."
    """
    res = api.list_editors(reviewer_fallback_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


# ---------------------------------------------------------------------------
# Response envelope (PRD §2.2)
# ---------------------------------------------------------------------------
def test_success_envelope_shape(api, platform_admin_headers):
    """PRD §2.2: "All successful API responses (those with 2xx status
    codes) follow this standard envelope format in their JSON body" with
    meta.api_request_id starting with 'req_' and meta.api_request_timestamp
    as ISO 8601.
    """
    res = api.create_author(create_author_payload(), platform_admin_headers)
    body = res.json()
    assert "meta" in body and "data" in body and "response_type" in body
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_', got {meta.get('api_request_id')!r}"
    )
    assert isinstance(meta["api_request_timestamp"], str)
    assert body["response_type"] == "object"


def test_error_envelope_shape(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this
    standard envelope format" with response_type='error' and data carrying
    error_id and message.
    """
    res = api.create_author(create_author_payload(), {})
    body = res.json()
    assert body.get("response_type") == "error"
    assert "error_id" in body["data"]
    assert "message" in body["data"]


# ---------------------------------------------------------------------------
# Common resource properties (PRD §2.4)
# ---------------------------------------------------------------------------
def test_author_carries_full_common_envelope(api, platform_admin_headers):
    """PRD §2.4: "Most persisted entities — Author, Reviewer, Editor,
    Manuscript, CoAuthorConfirmation, ReviewerInvitation, Review,
    EditorDecision, and Publication — carry the same four envelope
    fields: id ... created_at and updated_at ... and version (an integer
    that starts at 1 on creation and is incremented by one on every
    mutation that changes the resource)."
    """
    # PRD §2.4: "version (an integer that starts at 1 on creation ...)" —
    # check at creation time only; verify_orcid=False keeps the author at
    # version 1 (the verify event in §3.1 would itself be a mutation).
    author = register_author(verify_orcid=False)
    assert "id" in author and "created_at" in author
    assert "updated_at" in author and "version" in author
    assert author["version"] == 1


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def test_pagination_default_limit_is_ten(api, platform_admin_headers):
    """PRD §2.3: "The default limit is 10 ..." — list endpoint must return
    meta.limit == 10 when limit is not specified.
    """
    for _ in range(3):
        register_reviewer()
    res = api.list_reviewers(platform_admin_headers)
    data, meta = validate_paginated(res)
    assert meta["limit"] == 10
    assert meta["offset"] == 0


def test_pagination_explicit_limit(api, platform_admin_headers):
    """PRD §2.3: "List endpoints accept two query parameters: limit and
    offset." Server must honor explicit limit and offset values in the
    closed interval [1, 100].
    """
    for _ in range(3):
        register_reviewer()
    res = api.list_reviewers(platform_admin_headers, params={"limit": 1})
    data, meta = validate_paginated(res)
    assert len(data) == 1
    assert meta["limit"] == 1


@pytest.mark.parametrize("limit", [0, -1, 101])
def test_pagination_invalid_limit_rejected(api, platform_admin_headers, limit):
    """PRD §2.3: "any value outside [1, 100] is rejected as ERR_VALIDATION
    (HTTP 400)."
    """
    res = api.list_reviewers(platform_admin_headers, params={"limit": limit})
    validate_error(res, ApiErrorId.ERR_VALIDATION.value)


def test_pagination_negative_offset_rejected(api, platform_admin_headers):
    """PRD §2.3: "The default offset is 0; negative offsets are rejected
    the same way."
    """
    res = api.list_reviewers(platform_admin_headers, params={"offset": -1})
    validate_error(res, ApiErrorId.ERR_VALIDATION.value)


def test_pagination_meta_has_more(api, platform_admin_headers):
    """PRD §2.3: "has_more is true exactly when more rows remain past the
    returned page."
    """
    for _ in range(3):
        register_reviewer()
    res = api.list_reviewers(platform_admin_headers, params={"limit": 1})
    data, meta = validate_paginated(res)
    assert meta["has_more"] is True

    res = api.list_reviewers(
        platform_admin_headers, params={"limit": 100, "offset": 100_000},
    )
    data, meta = validate_paginated(res)
    assert len(data) == 0
    assert meta["has_more"] is False


# ---------------------------------------------------------------------------
# Not-found resolution (PRD §2.7)
# ---------------------------------------------------------------------------
def test_get_nonexistent_author_returns_not_found(api, platform_admin_headers):
    """PRD §2.5: "path-resource existence resolved left to right
    (ERR_NOT_FOUND)." PRD §2.7: "A missing outer resource produces
    ERR_NOT_FOUND ..."
    """
    res = api.get_author(NON_EXISTENT_UUID, platform_admin_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


def test_invitations_path_with_missing_manuscript_returns_not_found(
        api, platform_admin_headers):
    """PRD §2.7: "Endpoints with multi-segment paths ... resolve their
    path parameters left to right. The outer Manuscript must exist first;
    only then is the inner ... resolved. A missing outer resource produces
    ERR_NOT_FOUND and the inner lookup is never attempted."
    """
    res = api.list_invitations(NON_EXISTENT_UUID, platform_admin_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)
