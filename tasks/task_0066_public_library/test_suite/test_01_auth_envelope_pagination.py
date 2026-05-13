"""Auth headers, response envelope, and pagination tests (PRD §2.1, §2.2, §2.3).

All tests here are framework-of-the-API tests: they verify request-level
contracts that every endpoint observes, not domain logic.
"""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    api_client,
    build_user_headers,
    create_book_title,
    create_book_title_payload,
    create_verified_reader_with_card,
    create_reader_payload,
    LIBRARIAN_HEADERS,
    make_reader_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


# =============================================================================
# Authentication / authorization (PRD §2.1)
# =============================================================================


def test_missing_user_id_header_rejected(api):
    """PRD §2.1: "If either header is missing, the request is rejected with
    ERR_AUTH_REQUIRED (HTTP 401)."

    Claim: omitting X-User-ID returns ERR_AUTH_REQUIRED with HTTP 401.
    """
    res = api.create_book_title(create_book_title_payload(), {"X-User-Role": "Librarian"})
    validate_error(res, "ERR_AUTH_REQUIRED", expected_status=401)


def test_missing_user_role_header_rejected(api):
    """PRD §2.1: "If either header is missing, the request is rejected with
    ERR_AUTH_REQUIRED (HTTP 401)."

    Claim: omitting X-User-Role returns ERR_AUTH_REQUIRED with HTTP 401.
    """
    res = api.create_book_title(create_book_title_payload(), {"X-User-ID": "u-1"})
    validate_error(res, "ERR_AUTH_REQUIRED", expected_status=401)


def test_empty_headers_rejected(api):
    """PRD §2.1: "If either header is missing, the request is rejected with
    ERR_AUTH_REQUIRED (HTTP 401)."

    Claim: passing entirely empty headers returns ERR_AUTH_REQUIRED.
    """
    res = api.list_book_titles({})
    validate_error(res, "ERR_AUTH_REQUIRED", expected_status=401)


def test_reader_cannot_catalog_book_title(api):
    """PRD §2.1: "If both headers are present but the role is not authorized
    for the requested endpoint, the request is rejected with ERR_FORBIDDEN
    (HTTP 403)."

    Claim: a Reader calling POST /library/book-titles (Librarian-only) gets
    ERR_FORBIDDEN with HTTP 403.
    """
    reader_headers = build_user_headers("test-reader-not-cataloger", "Reader")
    res = api.create_book_title(create_book_title_payload(), reader_headers)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_fine_officer_cannot_create_book_title(api):
    """PRD §2.1: "If both headers are present but the role is not authorized
    for the requested endpoint, the request is rejected with ERR_FORBIDDEN
    (HTTP 403)."

    Claim: FineOfficer is not authorized for POST /library/book-titles.
    """
    fine_off = build_user_headers("test-fine-officer-z", "FineOfficer")
    res = api.create_book_title(create_book_title_payload(), fine_off)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_reader_acting_on_someone_elses_loan_forbidden(api):
    """PRD §2.1: "A Reader acting on someone else's resource is rejected with
    ERR_FORBIDDEN."

    Claim: Reader A trying to renew Reader B's loan gets ERR_FORBIDDEN 403.
    """
    from test_helpers import create_active_loan
    ctx = create_active_loan()
    other_reader_headers = build_user_headers("test-reader-not-owner", "Reader")
    res = api.renew_loan(ctx["loan"]["id"], None, other_reader_headers)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


# =============================================================================
# Response envelope (PRD §2.2)
# =============================================================================


def test_success_envelope_shape_on_create(api):
    """PRD §2.2: "All successful API responses (those with 2xx status codes)
    follow this standard envelope format in their JSON body".

    Claim: 2xx responses carry meta + response_type + data.
    """
    res = api.create_book_title(create_book_title_payload(), LIBRARIAN_HEADERS)
    assert res.status_code == 201
    body = res.json()
    assert "meta" in body
    assert "response_type" in body
    assert "data" in body
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_"), (
        "PRD §2.2: api_request_id is a server-generated unique identifier for "
        "the request that starts with `req_`."
    )


def test_error_envelope_shape(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this
    standard envelope format ... response_type: error, data: {error_id, message}."

    Claim: 4xx responses carry meta + response_type=error + data{error_id,message}.
    """
    res = api.get_book_title(NON_EXISTENT_UUID, LIBRARIAN_HEADERS)
    assert res.status_code == 404
    body = res.json()
    assert body["response_type"] == "error"
    assert isinstance(body["data"]["error_id"], str)
    assert isinstance(body["data"]["message"], str)


def test_list_envelope_is_array(api):
    """PRD §2.2: "response_type is either object for a single resource or
    array for a list of resources."

    Claim: list endpoints return response_type=array.
    """
    create_book_title()
    res = api.list_book_titles(LIBRARIAN_HEADERS)
    assert res.status_code == 200
    body = res.json()
    assert body["response_type"] == "array"
    assert isinstance(body["data"], list)


# =============================================================================
# Pagination (PRD §2.3)
# =============================================================================


def test_pagination_meta_keys(api):
    """PRD §2.3: "The meta envelope on every list response exposes the
    effective limit, the effective offset, the total_count of records that
    satisfy the filters, and the has_more boolean derived from offset + limit
    < total_count."

    Claim: list-endpoint meta carries limit + offset + total_count + has_more.
    """
    create_book_title()
    create_book_title()
    data, meta = validate_paginated(api.list_book_titles(LIBRARIAN_HEADERS))
    assert "limit" in meta
    assert "offset" in meta
    assert "total_count" in meta
    assert "has_more" in meta
    assert isinstance(meta["has_more"], bool)


def test_pagination_default_limit_is_10(api):
    """PRD §2.3: "The limit parameter defaults to 10".

    Claim: when no limit query param is supplied, meta.limit is 10.
    """
    create_book_title()
    data, meta = validate_paginated(api.list_book_titles(LIBRARIAN_HEADERS))
    assert meta["limit"] == 10


def test_pagination_has_more_true_when_more_records_remain(api):
    """PRD §2.3: "has_more boolean derived from offset + limit < total_count."

    Claim: with limit=1 and ≥2 records, has_more is True.
    """
    for _ in range(3):
        create_book_title()
    data, meta = validate_paginated(
        api.list_book_titles(LIBRARIAN_HEADERS, params={"limit": 1})
    )
    assert len(data) == 1
    assert meta["limit"] == 1
    assert meta["has_more"] is True


def test_pagination_has_more_false_when_offset_past_total(api):
    """PRD §2.3: "has_more boolean derived from offset + limit < total_count."

    Claim: with offset past total_count, has_more is False and data is empty.
    """
    data, meta = validate_paginated(
        api.list_book_titles(LIBRARIAN_HEADERS, params={"offset": 999_999})
    )
    assert len(data) == 0
    assert meta["has_more"] is False


@pytest.mark.parametrize("bad_limit", [0, -1, 101, 1000])
def test_pagination_limit_out_of_range_rejected(api, bad_limit):
    """PRD §2.3: "has a minimum of 1, and a maximum of 100; requests beyond
    those bounds are rejected with ERR_INVALID_INPUT."

    Claim: limit outside [1,100] returns ERR_INVALID_INPUT (HTTP 422).
    """
    res = api.list_book_titles(LIBRARIAN_HEADERS, params={"limit": bad_limit})
    validate_error(res, "ERR_INVALID_INPUT", expected_status=422)


def test_list_sorted_by_created_at_ascending(api):
    """PRD §2.3: "List endpoints sort results by created_at in ascending order."

    Claim: consecutive list pages return entries with non-decreasing created_at.
    """
    first = create_book_title()
    second = create_book_title()
    third = create_book_title()
    data, _ = validate_paginated(
        api.list_book_titles(LIBRARIAN_HEADERS, params={"limit": 100})
    )
    ids = [d["id"] for d in data]
    # Three titles we just created should appear; verify their order matches
    # the sequence in which they were created (which is the created_at order).
    indexed = [ids.index(t["id"]) for t in (first, second, third) if t["id"] in ids]
    assert indexed == sorted(indexed), (
        "PRD §2.3: List endpoints sort by created_at ascending"
    )
