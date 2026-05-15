"""Authentication, response envelope, RBAC negatives, pagination.

Anchors: PRD §2.1, §2.2, §2.3.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_borrower,
    build_user_headers,
    create_borrower_payload,
    make_borrower_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import create_borrower


# ---------------------------------------------------------------------------
# 1. Header presence (PRD §2.1)
# ---------------------------------------------------------------------------
def test_missing_x_user_id_header_rejected(api):
    """PRD §2.1: "Every request other than the liveness probe must
    carry two headers: X-User-ID, identifying the acting principal,
    and X-User-Role, naming one of the system's declared roles. When
    either header is missing or empty the request is rejected with
    ERR_AUTH_REQUIRED."

    Claim: omitting X-User-ID → ERR_AUTH_REQUIRED.
    """
    res = api.create_borrower(create_borrower_payload(),
                              headers={"X-User-Role": "ServicerAdmin"})
    validate_error(res, "ERR_AUTH_REQUIRED")


def test_missing_x_user_role_header_rejected(api):
    """PRD §2.1: "When either header is missing or empty the request
    is rejected with ERR_AUTH_REQUIRED."

    Claim: omitting X-User-Role → ERR_AUTH_REQUIRED.
    """
    res = api.create_borrower(create_borrower_payload(),
                              headers={"X-User-ID": "x"})
    validate_error(res, "ERR_AUTH_REQUIRED")


def test_empty_x_user_role_header_rejected(api):
    """PRD §2.1: "When either header is missing or empty the request
    is rejected with ERR_AUTH_REQUIRED."

    Claim: empty X-User-Role → ERR_AUTH_REQUIRED.
    """
    res = api.create_borrower(
        create_borrower_payload(),
        headers={"X-User-ID": "x", "X-User-Role": ""},
    )
    validate_error(res, "ERR_AUTH_REQUIRED")


def test_unrecognized_role_rejected(api):
    """PRD §2.1: "When the supplied role is not one of the recognized
    role names, or when the role is recognized but is not permitted
    to invoke the requested endpoint per the role/endpoint matrix,
    the response is ERR_FORBIDDEN."

    Claim: unknown role string → ERR_FORBIDDEN.
    """
    res = api.create_borrower(
        create_borrower_payload(),
        headers=build_user_headers("ghost-1", "GhostRole"),
    )
    validate_error(res, "ERR_FORBIDDEN")


def test_health_endpoint_does_not_require_auth(api):
    """PRD §2.1: "Every request other than the liveness probe must
    carry two headers."

    Claim: GET /_health is the carved-out exception to the auth rule.
    """
    res = api.health(headers={})
    # Lenient — 2xx (typically 200) per PRD §4.
    assert 200 <= res.status_code < 300, (
        f"Health probe must succeed without auth headers, got "
        f"{res.status_code}"
    )


# ---------------------------------------------------------------------------
# 2. RBAC negatives (PRD §2.1 + §4 role matrix)
# ---------------------------------------------------------------------------
def test_borrower_role_cannot_create_borrower(api):
    """PRD §4 role matrix lists POST /borrowers as ServicerAdmin only.
    PRD §2.1: "the response is ERR_FORBIDDEN" when "the role is
    recognized but is not permitted to invoke the requested endpoint
    per the role/endpoint matrix."

    Claim: Borrower role on POST /borrowers → ERR_FORBIDDEN.
    """
    res = api.create_borrower(
        create_borrower_payload(),
        headers=TEST_USERS["borrower_headers_fallback"],
    )
    validate_error(res, "ERR_FORBIDDEN")


def test_borrower_cannot_read_other_borrower_resources(api):
    """PRD §2.1: "a borrower may not read or mutate another borrower's
    resources."

    Claim: Borrower A using X-User-ID = A.id cannot GET borrower B.
    """
    borrower_a = create_borrower(name="Alice")
    borrower_b = create_borrower(name="Bob")
    res = api.get_borrower(
        borrower_b["id"], make_borrower_headers(borrower_a["id"]),
    )
    # PRD §2.1 says ERR_FORBIDDEN for non-permitted access; ownership
    # rejection is conceptually that same forbidden bucket.
    validate_error(res, "ERR_FORBIDDEN")


def test_collections_officer_cannot_submit_borrower_sourced_payment(api):
    """PRD §3.4: "A Borrower may submit payments only with source =
    BORROWER; a CollectionsOfficer is the only role permitted to
    submit payments with source in ADMINISTRATIVE_WAGE_GARNISHMENT
    or TREASURY_OFFSET; a ServicerAdmin may submit payments with any
    source."

    Claim: a CollectionsOfficer submitting source=BORROWER falls
    outside the carved permission and is rejected with ERR_FORBIDDEN.
    """
    borrower = create_borrower()
    res = api.create_payment(
        borrower["id"],
        {"amount_cents": 1000, "source": "BORROWER"},
        TEST_USERS["collections_officer_headers"],
    )
    validate_error(res, "ERR_FORBIDDEN")


def test_borrower_cannot_submit_garnishment_payment(api):
    """PRD §3.4: "A Borrower may submit payments only with source =
    BORROWER; a CollectionsOfficer is the only role permitted to
    submit payments with source in ADMINISTRATIVE_WAGE_GARNISHMENT
    or TREASURY_OFFSET."

    Claim: Borrower role submitting TREASURY_OFFSET → ERR_FORBIDDEN.
    """
    borrower = create_borrower()
    res = api.create_payment(
        borrower["id"],
        {"amount_cents": 1000, "source": "TREASURY_OFFSET"},
        make_borrower_headers(borrower["id"]),
    )
    validate_error(res, "ERR_FORBIDDEN")


# ---------------------------------------------------------------------------
# 3. Response envelope (PRD §2.2)
# ---------------------------------------------------------------------------
def test_success_envelope_shape(api):
    """PRD §2.2: success envelope carries meta.api_request_id (prefix
    'req_'), meta.api_request_timestamp (ISO 8601 UTC with three
    fractional digits), response_type, and data.

    Claim: successful POST /borrowers returns the §2.2 envelope shape.
    """
    res = api.create_borrower(
        create_borrower_payload(), TEST_USERS["servicer_admin_headers"],
    )
    body = res.json()
    assert "meta" in body
    assert body["meta"]["api_request_id"].startswith("req_"), (
        "PRD §2.2: api_request_id must start with 'req_'"
    )
    assert body["meta"]["api_request_timestamp"].endswith("Z"), (
        "PRD §2.2: api_request_timestamp must be ISO 8601 UTC ending in Z"
    )
    assert body["response_type"] == "object"
    assert "data" in body
    assert body["data"]["full_name"]


def test_error_envelope_shape(api):
    """PRD §2.2: error envelope carries response_type='error' and
    data={error_id, message}.

    Claim: a 404 response uses the §2.2 error envelope.
    """
    res = api.get_borrower(NON_EXISTENT_UUID,
                           TEST_USERS["servicer_admin_headers"])
    body = res.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_BORROWER_NOT_FOUND"
    assert isinstance(body["data"].get("message"), str)


# ---------------------------------------------------------------------------
# 4. Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def test_list_pagination_default_limit_and_meta(api):
    """PRD §2.3: "limit defaults to 10... The meta object on a list
    response includes limit, offset, total_count, and has_more."

    Claim: list endpoint returns the four pagination meta fields.
    """
    for _ in range(3):
        create_borrower()
    data, meta = validate_paginated(
        api.list_borrowers(TEST_USERS["servicer_admin_headers"]),
    )
    assert "total_count" in meta
    assert "limit" in meta
    assert "offset" in meta
    assert "has_more" in meta
    assert meta["limit"] == 10


@pytest.mark.parametrize("limit, offset", [
    (0, 0),       # limit below 1
    (101, 0),    # limit above 100
    (10, -1),    # negative offset
])
def test_pagination_out_of_bounds_rejected(api, limit, offset):
    """PRD §2.3: "limit must be an integer of at least 1, and must
    not exceed 100. offset defaults to 0 and must be at least 0. Any
    value outside these bounds is rejected with ERR_PAGINATION_INVALID."

    Claim: limit/offset out of bounds → ERR_PAGINATION_INVALID.
    """
    res = api.list_borrowers(
        TEST_USERS["servicer_admin_headers"],
        params={"limit": limit, "offset": offset},
    )
    validate_error(res, "ERR_PAGINATION_INVALID")


def test_pagination_total_count_and_has_more(api):
    """PRD §2.3: "total_count reports the total number of records
    that match the filter set ignoring pagination, and has_more is
    true when offset + limit < total_count."

    Claim: total_count reflects all records and has_more obeys the
    inequality.
    """
    for _ in range(4):
        create_borrower()
    data, meta = validate_paginated(api.list_borrowers(
        TEST_USERS["servicer_admin_headers"],
        params={"limit": 2, "offset": 0},
    ))
    assert meta["total_count"] >= 4
    assert meta["has_more"] is True
    assert len(data) == 2


def test_list_results_ordered_by_created_at_ascending(api):
    """PRD §2.3: "Results are sorted by created_at in ascending order."

    Claim: list returns borrowers in ascending created_at order.
    """
    b1 = create_borrower(name="First")
    b2 = create_borrower(name="Second")
    b3 = create_borrower(name="Third")
    data, _ = validate_paginated(api.list_borrowers(
        TEST_USERS["servicer_admin_headers"],
        params={"limit": 100, "offset": 0},
    ))
    timestamps = [b["created_at"] for b in data]
    assert timestamps == sorted(timestamps), (
        "PRD §2.3: list must be sorted by created_at ascending"
    )


# ---------------------------------------------------------------------------
# 5. Resource not-found cascade (PRD §2.7)
# ---------------------------------------------------------------------------
def test_borrower_not_found_resolves_first(api):
    """PRD §2.7: "if no borrower with that id exists the response is
    ERR_BORROWER_NOT_FOUND. The remaining nested id ... is then
    resolved against that borrower; if the sub-resource does not
    exist, or exists but belongs to a different borrower, the
    response is ERR_RESOURCE_NOT_FOUND."

    Claim: a GET on /borrowers/<bad>/loans/<bad> resolves the
    borrower segment first and returns ERR_BORROWER_NOT_FOUND.
    """
    res = api.get_loan(NON_EXISTENT_UUID, NON_EXISTENT_UUID,
                       TEST_USERS["servicer_admin_headers"])
    validate_error(res, "ERR_BORROWER_NOT_FOUND")


def test_sub_resource_not_found_under_valid_borrower(api):
    """PRD §2.7: "if the sub-resource does not exist, or exists but
    belongs to a different borrower, the response is
    ERR_RESOURCE_NOT_FOUND."

    Claim: real borrower + missing loan id → ERR_RESOURCE_NOT_FOUND.
    """
    borrower = create_borrower()
    res = api.get_loan(borrower["id"], NON_EXISTENT_UUID,
                       TEST_USERS["servicer_admin_headers"])
    validate_error(res, "ERR_RESOURCE_NOT_FOUND")
