"""Authentication, envelope structure, RBAC permissions, and existence checks."""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    create_player_payload,
    create_room_payload,
    create_venue_payload,
    is_iso8601_timestamp,
    make_player_headers,
    make_venue_operator_headers,
    setup_basic_scenario,
    validate_error,
    validate_success,
)


# ─── §2.1 Header well-formedness ──────────────────────────────────────────

@pytest.mark.parametrize("missing", ["both", "user_id", "user_role"])
def test_missing_user_context_header_rejected(api, missing):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID` (the acting principal's identifier) and `X-User-Role` (the role string that scopes capability). When either header is missing, malformed, or empty, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Claim: missing or empty X-User-ID / X-User-Role yields ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400).
    """
    if missing == "both":
        headers = {}
    elif missing == "user_id":
        headers = {"X-User-Role": "PlatformAdmin"}
    else:
        headers = {"X-User-ID": "test-admin-1"}
    resp = api.list_venues(headers)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)


def test_empty_user_id_header_rejected(api):
    """PRD §2.1: "When either header is missing, malformed, or empty, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Claim: empty X-User-ID is treated as malformed/missing.
    """
    resp = api.list_venues({"X-User-ID": "", "X-User-Role": "PlatformAdmin"})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)


# ─── §2.2 Standard success envelope ───────────────────────────────────────

def test_success_envelope_shape(api):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."
    PRD §2.2: "The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits."

    Claim: 2xx responses carry meta.api_request_id (req_-prefixed) and meta.api_request_timestamp (ISO 8601).
    """
    resp = api.list_venues(TEST_USERS["platform_admin_headers"])
    body = resp.json()
    assert "meta" in body and "data" in body
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert body["meta"]["api_request_id"].startswith("req_"), "api_request_id must start with req_"
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])


def test_success_envelope_response_type(api):
    """PRD §2.2: "The `response_type` is either \"object\" for a single resource or \"array\" for a list of resources."

    Claim: list endpoints set response_type=array; create endpoints set response_type=object.
    """
    list_resp = api.list_venues(TEST_USERS["platform_admin_headers"])
    assert list_resp.json()["response_type"] == "array"

    payload = create_venue_payload()
    create_resp = api.create_venue(payload, TEST_USERS["platform_admin_headers"])
    assert create_resp.json()["response_type"] == "object"


def test_error_envelope_shape(api):
    """PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."

    Claim: 4xx responses carry response_type='error' and data.error_id.
    """
    resp = api.list_venues({})
    body = resp.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"
    assert isinstance(body["data"].get("message"), str)


# ─── §2.3 Pagination ──────────────────────────────────────────────────────

def test_pagination_meta_fields_on_list(api):
    """PRD §2.3: "The `meta` block on list responses populates `limit`, `offset`, `total_count`, and `has_more`; non-list responses omit the four pagination fields."

    Claim: list-endpoint responses carry the four pagination meta fields.
    """
    resp = api.list_venues(TEST_USERS["platform_admin_headers"])
    body = resp.json()
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key in body["meta"], f"List meta must include {key}"


def test_pagination_default_limit(api):
    """PRD §2.3: "`limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0 and may be any non-negative integer."

    Claim: omitted limit defaults to 10.
    """
    resp = api.list_venues(TEST_USERS["platform_admin_headers"])
    body = resp.json()
    assert body["meta"]["limit"] == 10
    assert body["meta"]["offset"] == 0


# ─── §2.1 RBAC role enforcement (forbidden roles) ─────────────────────────

def test_create_venue_forbidden_for_player(api):
    """PRD §4 endpoint table: "POST /venues — Authorized Role(s): PlatformAdmin."
    PRD §2.1: "When the headers are well-formed but the role is not authorised for the requested operation per §4 and the role descriptions below, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

    Claim: a Player cannot create a venue.
    """
    resp = api.create_venue(create_venue_payload(), TEST_USERS["player_headers"])
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


def test_create_room_forbidden_for_player(api):
    """PRD §4 endpoint table: "POST /venues/{venueId}/rooms — Authorized Role(s): VenueOperator."

    Claim: a Player cannot create rooms.
    """
    venue, _, _ = setup_basic_scenario()
    resp = api.create_room(venue["id"], create_room_payload(), TEST_USERS["player_headers"])
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


def test_create_room_forbidden_for_wrong_venue_operator(api):
    """PRD §2.1: "When `X-User-Role` is `VenueOperator`, `X-User-ID` is the `id` of the acting `Venue`; for slot, booking, room, maintenance-window, and staff-assignment actions, the venue is resolved via the path's `venueId`, the slot's `venue_id`, or the booking's `slot.venue_id`, and that resolved id must equal `X-User-ID`."

    Claim: a VenueOperator with X-User-ID != path venueId is rejected with ERR_INSUFFICIENT_PERMISSIONS.
    """
    venue, _, _ = setup_basic_scenario()
    other_venue, _, _ = setup_basic_scenario()
    foreign_headers = make_venue_operator_headers(other_venue["id"])
    resp = api.create_room(venue["id"], create_room_payload(), foreign_headers)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


# ─── §2.8 Existence checks (left-to-right) ────────────────────────────────

def test_get_venue_not_found(api):
    """PRD §2.8: "the outer `venueId` is checked first and yields `ERR_VENUE_NOT_FOUND` if absent."

    Claim: GET /venues/{unknown} returns ERR_VENUE_NOT_FOUND (404).
    """
    resp = api.get_venue(NON_EXISTENT_UUID, TEST_USERS["platform_admin_headers"])
    validate_error(resp, ApiErrorId.ERR_VENUE_NOT_FOUND.value)


def test_get_room_not_found(api):
    """PRD §2.8: "only then is `roomId` checked, yielding `ERR_ROOM_NOT_FOUND`."

    Claim: GET on existing venue but unknown room returns ERR_ROOM_NOT_FOUND.
    """
    venue, _, _ = setup_basic_scenario()
    headers = make_venue_operator_headers(venue["id"])
    resp = api.get_room(venue["id"], NON_EXISTENT_UUID, headers)
    validate_error(resp, ApiErrorId.ERR_ROOM_NOT_FOUND.value)


def test_get_slot_not_found(api):
    """PRD §2.8: existence check for slotId yields ERR_SLOT_NOT_FOUND.

    Claim: GET /session-slots/{unknown} returns ERR_SLOT_NOT_FOUND.
    """
    resp = api.get_session_slot(NON_EXISTENT_UUID, TEST_USERS["platform_admin_headers"])
    validate_error(resp, ApiErrorId.ERR_SLOT_NOT_FOUND.value)


def test_get_booking_not_found(api):
    """PRD §2.8: existence check for bookingId yields ERR_BOOKING_NOT_FOUND.

    Claim: GET /bookings/{unknown} returns ERR_BOOKING_NOT_FOUND.
    """
    resp = api.get_booking(NON_EXISTENT_UUID, TEST_USERS["platform_admin_headers"])
    validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_FOUND.value)


def test_get_player_not_found(api):
    """PRD §2.8: existence check for playerId yields ERR_PLAYER_NOT_FOUND.

    Claim: GET /players/{unknown} returns ERR_PLAYER_NOT_FOUND.
    """
    resp = api.get_player(NON_EXISTENT_UUID, TEST_USERS["platform_admin_headers"])
    validate_error(resp, ApiErrorId.ERR_PLAYER_NOT_FOUND.value)


# ─── §2.5 Optimistic concurrency ──────────────────────────────────────────

def test_version_mismatch_on_patch_returns_invalid_request(api):
    """PRD §2.5: "When the caller supplies `version` and it does not match the current row's `version`, the request is rejected with `ERR_INVALID_REQUEST` and no state changes."

    Claim: PATCH /venues/{id} with stale version yields ERR_INVALID_REQUEST.
    """
    admin = TEST_USERS["platform_admin_headers"]
    venue = validate_success(api.create_venue(create_venue_payload(), admin), expected_status=201)
    # Bump version once via a successful patch.
    bumped = validate_success(api.update_venue(venue["id"], {"deposit_policy_cents": venue["deposit_policy_cents"] + 100}, admin))
    assert bumped["version"] == venue["version"] + 1
    # Now patch with the original (stale) version.
    resp = api.update_venue(venue["id"], {"deposit_policy_cents": 1234, "version": venue["version"]}, admin)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_omitted_version_skips_check(api):
    """PRD §2.5: "When the caller omits `version`, the version check is skipped and the mutation proceeds against whatever the current row holds."

    Claim: PATCH without version succeeds and bumps version by 1.
    """
    admin = TEST_USERS["platform_admin_headers"]
    venue = validate_success(api.create_venue(create_venue_payload(), admin), expected_status=201)
    updated = validate_success(api.update_venue(venue["id"], {"deposit_policy_cents": 999}, admin))
    assert updated["deposit_policy_cents"] == 999
    assert updated["version"] == venue["version"] + 1
