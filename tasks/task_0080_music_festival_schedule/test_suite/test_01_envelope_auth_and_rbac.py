"""Standard envelope shape, the auth-and-role gates of PRD §2.1, and the
audit-log-allowlist of PRD §2.1.

These tests target the cross-cutting header-and-envelope contract that
every endpoint shares.  The PRD §2.2 prose pins the meta block's
`api_request_id` prefix (the literal "req_" prefix) and the ISO 8601
timestamp shape, and the §2.3 prose pins the four-field pagination meta
block keyed `limit`, `offset`, `total_count`, `has_more` with the
boolean `has_more == (offset + limit < total_count)` rule.

The audit-log gate is a finer-grained restriction than the standard
per-endpoint role allowlist — the PRD §2.1 names the three-role
allowlist `AuditViewer, FestivalProducer, PlatformAdmin` and the
distinct error id `ERR_AUDIT_LOG_FORBIDDEN`.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_error_envelope_shape,
    assert_festival_shape,
    assert_pagination_meta,
    assert_success_envelope_meta,
    create_festival,
    festival_in_scheduling,
    festival_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# §2.2 success envelope shape — meta.api_request_id prefix, the response_type
# discriminator, and the data field.
# ---------------------------------------------------------------------------


def test_success_envelope_meta_carries_req_prefixed_id_and_iso_timestamp(
        api, producer_headers, time_anchor):
    """PRD §2.2: "The `api_request_id` is a server-generated unique
    identifier for the request that starts with `req_`."  Also: "The
    `api_request_timestamp` is a server-generated ISO 8601 UTC
    timestamp with three fractional digits."

    Claim: every 2xx response carries a meta block whose
    `api_request_id` is a string starting with the literal four-character
    prefix `req_` and whose `api_request_timestamp` is parseable as an
    ISO 8601 UTC timestamp.
    """
    payload = festival_payload(start_time=time_anchor,
                               end_time=time_anchor + 3 * 86400)
    resp = api.create_festival(payload, producer_headers)
    body = resp.json()
    meta = body.get("meta", {})
    rid = meta.get("api_request_id", "")
    ts = meta.get("api_request_timestamp", "")
    assert isinstance(rid, str) and rid.startswith("req_"), \
        f"api_request_id must begin with the literal prefix 'req_' per PRD §2.2 — got {rid!r}"
    assert is_iso8601_timestamp(str(ts)), \
        f"api_request_timestamp must be ISO 8601 UTC per PRD §2.2 — got {ts!r}"
    # The created Festival is in the data envelope.
    data = validate_success(resp, expected_status=201)
    assert is_valid_uuid(str(data["id"])), "Festival.id is a UUID per PRD §2.4"


def test_create_festival_returns_status_planned_and_full_common_fields(api,
                                                                      producer_headers,
                                                                      time_anchor):
    """PRD §3.1: the system "sets `status` to the initial state
    `PLANNED`" on festival creation.  Also PRD §2.4: "`id` is a
    server-minted UUID string", "`created_at`/`updated_at` are ISO 8601
    UTC", "`version` is a non-negative integer that starts at 1 on
    creation".

    Claim: a fresh festival has status==PLANNED, a UUID id, ISO
    timestamps, and version==1.
    """
    body = festival_payload(start_time=time_anchor,
                            end_time=time_anchor + 3 * 86400)
    resp = api.create_festival(body, producer_headers)
    data = validate_success(resp, expected_status=201)
    assert_festival_shape(data)
    assert data["status"] == "PLANNED", \
        "A fresh festival's status is PLANNED per PRD §3.1"
    assert data["version"] == 1, "Common-fields version starts at 1 per PRD §2.4"
    assert data["clock_offset_seconds"] == 0, \
        "Festival.clock_offset_seconds initialises to zero per PRD §3.1"
    assert data["current_program_version_id"] is None, \
        "Festival.current_program_version_id is null until first publish per PRD §2.4"
    assert data["festival_day_count"] == 3, \
        "festival_day_count is the integer ceil((end_time - start_time) / 86400) per PRD §2.4"


# ---------------------------------------------------------------------------
# §2.3 pagination meta block shape.
# ---------------------------------------------------------------------------


def test_list_festivals_pagination_meta_has_four_canonical_keys(api, audit_headers):
    """PRD §2.3: "The `meta` block on a list response contains the four
    pagination fields named in §2.2: `limit`, `offset`, `total_count`
    (the total number of rows that match the filter, independent of the
    limit window), and `has_more` (true when `offset + limit <
    total_count`)."

    Claim: the list endpoint's meta block contains exactly those four
    pagination keys and the boolean `has_more` derives the literal
    inequality `offset + limit < total_count`.
    """
    # No prior assumptions about how many festivals are in the database —
    # we just want the meta shape.  The "Any" role label in the §4 table
    # for the festivals-list endpoint means every authenticated role is
    # admitted; AuditViewer is the read-only role and has access to all
    # GETs per the §2.1 prose.
    resp = api.list_festivals(audit_headers, params={"limit": 5, "offset": 0})
    data, meta = validate_paginated(resp)
    assert isinstance(data, list)
    assert_pagination_meta(meta, expected_limit=5, expected_offset=0)


def test_list_festivals_default_pagination_is_limit_ten_offset_zero(api, audit_headers):
    """PRD §2.3: "The defaults are `limit` 10 and `offset` 0."

    Claim: the default pagination meta block has limit==10, offset==0.
    """
    resp = api.list_festivals(audit_headers, params=None)
    _, meta = validate_paginated(resp)
    assert meta["limit"] == 10, "default limit is 10 per PRD §2.3"
    assert meta["offset"] == 0, "default offset is 0 per PRD §2.3"


@pytest.mark.parametrize("bad_limit", [-1, 0, 101, 1000])
def test_list_festivals_invalid_limit_rejected(api, audit_headers, bad_limit):
    """PRD §2.3: "A value out of these ranges — `limit` below 1 or above
    100, or a negative `offset`, or a non-integer — is rejected at HTTP
    400 with `ERR_INVALID_PAGINATION`."

    Claim: a `limit` below 1 or above 100 is rejected with
    `ERR_INVALID_PAGINATION` at HTTP 400.  Boundary precision: limit==1
    and limit==100 are accepted (asserted in the next test).
    """
    resp = api.list_festivals(audit_headers, params={"limit": bad_limit})
    validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION.value)


def test_list_festivals_boundary_limits_accepted(api, audit_headers):
    """PRD §2.3: "The accepted range for `limit` is from 1 to 100
    inclusive on both ends."  Boundary precision pair to the previous
    test.

    Claim: limit==1 and limit==100 are both accepted.
    """
    for good_limit in (1, 100):
        resp = api.list_festivals(audit_headers, params={"limit": good_limit, "offset": 0})
        data, meta = validate_paginated(resp)
        assert meta["limit"] == good_limit, "boundary limit echoed verbatim per PRD §2.3"


def test_list_festivals_negative_offset_rejected(api, audit_headers):
    """PRD §2.3: "the accepted range for `offset` is any non-negative
    integer."

    Claim: a negative offset is rejected with `ERR_INVALID_PAGINATION`.
    """
    resp = api.list_festivals(audit_headers, params={"offset": -1})
    validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION.value)


# ---------------------------------------------------------------------------
# §2.1 header gates — ERR_MISSING_USER_CONTEXT_HEADER and ERR_UNKNOWN_ROLE.
# ---------------------------------------------------------------------------


def test_request_with_missing_user_headers_rejected(api, no_headers, time_anchor):
    """PRD §2.1: "If either header is missing or an empty string, the
    request is rejected at HTTP 400 with
    `ERR_MISSING_USER_CONTEXT_HEADER`."

    Claim: a request whose X-User-ID and X-User-Role headers are both
    absent is rejected at HTTP 400 with the missing-header error id.
    """
    body = festival_payload(start_time=time_anchor,
                            end_time=time_anchor + 86400)
    resp = api.create_festival(body, no_headers)
    err = validate_error(resp, ApiErrorId.ERR_MISSING_USER_CONTEXT_HEADER.value,
                         expected_status=400)
    # The error envelope itself has the §2.2 error shape.
    assert_error_envelope_shape(resp.json())


def test_request_with_empty_user_id_header_rejected(api, time_anchor):
    """PRD §2.1: the X-User-ID header "is the opaque identifier of the
    actor making the call. ... If either header is missing or an empty
    string, the request is rejected at HTTP 400 with
    `ERR_MISSING_USER_CONTEXT_HEADER`."

    Claim: a request whose X-User-ID header is an empty string is
    rejected the same way the missing-header case is.
    """
    headers = {"X-User-ID": "", "X-User-Role": "FestivalProducer"}
    body = festival_payload(start_time=time_anchor,
                            end_time=time_anchor + 86400)
    resp = api.create_festival(body, headers)
    validate_error(resp, ApiErrorId.ERR_MISSING_USER_CONTEXT_HEADER.value,
                   expected_status=400)


def test_request_with_unknown_role_header_rejected(api, unknown_role_headers, time_anchor):
    """PRD §2.1: "an unrecognised role name fails fast with the error
    `ERR_UNKNOWN_ROLE` at HTTP 403, distinct from the permission-denied
    case `ERR_INSUFFICIENT_PERMISSIONS` at HTTP 403 which fires when
    the role is recognised but is not on the endpoint's allowlist."

    Claim: a request whose X-User-Role is a string outside the seven
    declared role names is rejected with the unknown-role error id at
    HTTP 403, distinct from the insufficient-permissions error id.
    """
    body = festival_payload(start_time=time_anchor,
                            end_time=time_anchor + 86400)
    resp = api.create_festival(body, unknown_role_headers)
    validate_error(resp, ApiErrorId.ERR_UNKNOWN_ROLE.value, expected_status=403)


def test_create_festival_rejects_role_outside_allowlist(api, ticketing_headers, time_anchor):
    """PRD §2.1 / §4 table: the festivals create endpoint's allowlist is
    `FestivalProducer, PlatformAdmin`.  Other roles are rejected.  And
    PRD §2.1 names the error id for a recognised-role-not-on-allowlist
    case as `ERR_INSUFFICIENT_PERMISSIONS` at HTTP 403.

    Claim: a `TicketingAdmin` calling POST /festivals receives
    `ERR_INSUFFICIENT_PERMISSIONS` at HTTP 403.
    """
    body = festival_payload(start_time=time_anchor,
                            end_time=time_anchor + 86400)
    resp = api.create_festival(body, ticketing_headers)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value,
                   expected_status=403)


# ---------------------------------------------------------------------------
# Audit-log allowlist gate — the finer-grained restriction of PRD §2.1.
# ---------------------------------------------------------------------------


def test_audit_log_read_forbidden_to_non_allowlisted_role(api, ticketing_headers, time_anchor):
    """PRD §2.1: "`GET /festivals/{festivalId}/audit-entries` is open
    only to `AuditViewer`, `FestivalProducer`, and `PlatformAdmin`.
    Every other role receives `ERR_AUDIT_LOG_FORBIDDEN` at HTTP 403,
    even when the request's headers are otherwise valid.  This is a
    separate error from the generic `ERR_INSUFFICIENT_PERMISSIONS` so
    the client can distinguish 'you have no read access at all' from
    'you're not on the audit-log allowlist'."

    Claim: a TicketingAdmin (a recognised role with valid headers, not
    on the three-role audit-allowlist) reading the audit log receives
    `ERR_AUDIT_LOG_FORBIDDEN` at HTTP 403, distinct from
    `ERR_INSUFFICIENT_PERMISSIONS`.
    """
    bag = create_festival(api)
    resp = api.list_audit_entries(bag.festival_id, ticketing_headers,
                                  params={"limit": 10})
    validate_error(resp, ApiErrorId.ERR_AUDIT_LOG_FORBIDDEN.value,
                   expected_status=403)


@pytest.mark.parametrize("headers_key", ["audit_headers", "producer_headers", "admin_headers"])
def test_audit_log_read_open_to_three_role_allowlist(api, request, headers_key):
    """PRD §2.1: the three-role audit-log allowlist is `AuditViewer,
    FestivalProducer, PlatformAdmin`.

    Claim: every one of those three roles can read the audit log without
    `ERR_AUDIT_LOG_FORBIDDEN`.  The list may be empty for a brand-new
    festival; the test asserts the success envelope shape.
    """
    bag = create_festival(api)
    h = request.getfixturevalue(headers_key)
    resp = api.list_audit_entries(bag.festival_id, h, params={"limit": 100})
    data, meta = validate_paginated(resp)
    assert isinstance(data, list), \
        "the audit-entries list endpoint returns an array of rows per PRD §3.7"
    assert_pagination_meta(meta)


# ---------------------------------------------------------------------------
# The §2.4 not-found family — one not-found error id per resource type.
# ---------------------------------------------------------------------------


def test_get_unknown_festival_returns_festival_not_found(api, audit_headers):
    """PRD §2.1: "The full not-found family is one error per resource
    type: `ERR_FESTIVAL_NOT_FOUND`, ...".

    Claim: a GET on a non-existent festival id returns
    `ERR_FESTIVAL_NOT_FOUND` at HTTP 404.
    """
    from test_helpers import NON_EXISTENT_UUID
    resp = api.get_festival(NON_EXISTENT_UUID, audit_headers)
    validate_error(resp, ApiErrorId.ERR_FESTIVAL_NOT_FOUND.value,
                   expected_status=404)


def test_get_unknown_program_item_under_existing_festival_returns_item_not_found(
        api, audit_headers):
    """PRD §2.1: "A request to `/festivals/{festivalId}/program-items/{itemId}`
    first verifies the festival id resolves (returning
    `ERR_FESTIVAL_NOT_FOUND` if not), then verifies the program-item id
    resolves under it (returning `ERR_PROGRAM_ITEM_NOT_FOUND` if not),
    then the parent-match guard fires (returning
    `ERR_RESOURCE_MISMATCHED_PARENT` if the resolved program item
    belongs to a different festival).  The URL-path existence check is
    run left-to-right."

    Claim: the festival id resolves but the program-item id does not,
    so the second-step check fires with `ERR_PROGRAM_ITEM_NOT_FOUND`
    at HTTP 404 — not `ERR_FESTIVAL_NOT_FOUND` and not the parent
    mismatch.
    """
    from test_helpers import NON_EXISTENT_UUID
    bag = festival_in_scheduling(api)
    resp = api.get_program_item(bag.festival_id, NON_EXISTENT_UUID, audit_headers)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_ITEM_NOT_FOUND.value,
                   expected_status=404)


def test_invalid_festival_window_zero_day_count_rejected(api, producer_headers, time_anchor):
    """PRD §3.1: "A `Festival` whose window fails the validity check —
    either `end_time` is not strictly greater than `start_time`, or
    either time is non-positive, or `festival_day_count` would be zero
    — is rejected at HTTP 400 with `ERR_INVALID_FESTIVAL_WINDOW`."

    Claim: a festival with end_time == start_time is rejected at HTTP
    400 with `ERR_INVALID_FESTIVAL_WINDOW`.
    """
    body = festival_payload(start_time=time_anchor, end_time=time_anchor)
    resp = api.create_festival(body, producer_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_FESTIVAL_WINDOW.value,
                   expected_status=400)


def test_festival_day_count_ceiling_division_by_86400(api, producer_headers, time_anchor):
    """PRD §2.7: "The festival's `festival_day_count` is the integer
    `ceil((end_time - start_time) / 86400)` ... a window of exactly two
    days' worth of seconds gives 2, a window with one extra second over
    the two-day boundary gives 3."

    Claim: a (2*86400 + 1)-second window yields festival_day_count==3,
    while a 2*86400-second window yields 2.  Two distinct windows, two
    distinct expected day counts — the ceiling-division literal pinned
    in PRD §2.7's worked sentence.
    """
    # Exactly two whole days — the literal "exactly two days' worth of
    # seconds" sentence in PRD §2.7 says this yields 2.
    body_two = festival_payload(start_time=time_anchor,
                                end_time=time_anchor + 2 * 86400)
    resp_two = api.create_festival(body_two, producer_headers)
    data_two = validate_success(resp_two, expected_status=201)
    assert data_two["festival_day_count"] == 2, \
        "Exactly two days of seconds gives festival_day_count==2 per PRD §2.7"
    # One extra second over the two-day boundary — the literal "with one
    # extra second over the two-day boundary gives 3" sentence in PRD
    # §2.7.
    body_three = festival_payload(start_time=time_anchor,
                                  end_time=time_anchor + 2 * 86400 + 1)
    resp_three = api.create_festival(body_three, producer_headers)
    data_three = validate_success(resp_three, expected_status=201)
    assert data_three["festival_day_count"] == 3, \
        "One second past the 2-day boundary gives festival_day_count==3 per PRD §2.7"
