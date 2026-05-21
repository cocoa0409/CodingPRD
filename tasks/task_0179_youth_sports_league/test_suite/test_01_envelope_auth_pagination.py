"""Envelope, auth, role, pagination, and not-found probes.

These tests do not depend on domain workflow state. They probe the
cross-cutting rules from PRD §2.1 (auth + role), §2.2 (response
envelope), §2.3 (pagination), §2.5 (left-to-right path lookup).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    create_season_payload,
    create_season,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Auth headers — PRD §2.1
# ===========================================================================
class TestAuthHeaders:
    """PRD §2.1: "A request missing either header is rejected with
    `ERR_AUTH_REQUIRED` and HTTP 401."
    """

    def test_missing_x_user_id_is_rejected(self, api):
        """PRD §2.1: "A request missing either header is rejected with
        `ERR_AUTH_REQUIRED` and HTTP 401."

        Claim: missing X-User-ID -> ERR_AUTH_REQUIRED (HTTP 401).
        """
        resp = api.list_audit_events({"X-User-Role": "LeagueAdmin"})
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_missing_x_user_role_is_rejected(self, api):
        """PRD §2.1: "A request missing either header is rejected with
        `ERR_AUTH_REQUIRED` and HTTP 401."

        Claim: missing X-User-Role -> ERR_AUTH_REQUIRED.
        """
        resp = api.list_audit_events({"X-User-ID": "admin-1"})
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)


# ===========================================================================
# Role authorization — PRD §2.1 + §4 endpoint table
# ===========================================================================
class TestRoleAuthorization:
    """PRD §2.1: "A request whose role lacks permission for the
    endpoint ... is rejected with `ERR_FORBIDDEN` and HTTP 403."
    """

    def test_guardian_cannot_create_season(self, api, guardian_headers):
        """PRD §4 row: POST /league/seasons is restricted to LeagueAdmin.

        Claim: Guardian POST /league/seasons -> ERR_FORBIDDEN.
        """
        payload = create_season_payload()
        resp = api.create_season(payload, guardian_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_coach_cannot_create_team(self, api, coach_headers):
        """PRD §4 row: POST /league/teams is restricted to LeagueAdmin.
        PRD §2.1: "A request whose role lacks permission for the
        endpoint ... is rejected with `ERR_FORBIDDEN`."

        Claim: Coach POST /league/teams -> ERR_FORBIDDEN.
        """
        resp = api.create_team(
            {
                "season_id": NON_EXISTENT_UUID,
                "name": "Hackers",
                "head_coach_id": NON_EXISTENT_UUID,
                "draft_position": 1,
            },
            coach_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_referee_cannot_register_player(self, api, referee_headers):
        """PRD §4 row: POST /league/players is restricted to {Guardian,
        LeagueAdmin}.

        Claim: Referee POST /league/players -> ERR_FORBIDDEN.
        """
        resp = api.create_player(
            {
                "season_id": NON_EXISTENT_UUID,
                "first_name": "X",
                "last_name": "Y",
                "birth_date": "2015-06-01T00:00:00.000Z",
                "guardian_id": NON_EXISTENT_UUID,
            },
            referee_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Standard envelope — PRD §2.2
# ===========================================================================
class TestSuccessEnvelope:
    """PRD §2.2: "All successful API responses (those with 2xx status
    codes) follow this standard envelope format in their JSON body".
    """

    def test_create_season_envelope(self, api, league_admin_headers):
        """PRD §2.2: success envelope carries meta.api_request_id (with
        req_ prefix), meta.api_request_timestamp (ISO 8601),
        response_type, and data.

        Claim: created Season returns the standard envelope.
        """
        payload = create_season_payload()
        resp = api.create_season(payload, league_admin_headers)
        # validate_success cross-checks status (201 here) and unpacks
        # data.
        data = validate_success(resp, expected_status=201)
        assert data.get("status") == "DRAFT_OPEN"
        assert is_valid_uuid(data["id"])

    def test_envelope_meta_request_id_starts_with_prefix(
        self, api, league_admin_headers,
    ):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."

        Claim: meta.api_request_id starts with the `req_` literal.
        """
        season = create_season()
        raw = api.get_season(season["id"], league_admin_headers)
        body = raw.json()
        assert body.get("meta", {}).get("api_request_id", "").startswith(
            "req_"
        ), (
            f"api_request_id must start with 'req_', got "
            f"{body.get('meta', {}).get('api_request_id')!r}"
        )

    def test_envelope_meta_timestamp_is_iso8601(
        self, api, league_admin_headers,
    ):
        """PRD §2.2: "The `api_request_timestamp` is a server-generated
        ISO 8601 UTC timestamp with three fractional digits."

        Claim: meta.api_request_timestamp is ISO 8601.
        """
        season = create_season()
        raw = api.get_season(season["id"], league_admin_headers)
        body = raw.json()
        ts = body.get("meta", {}).get("api_request_timestamp")
        assert is_iso8601_timestamp(ts), (
            f"api_request_timestamp must be ISO 8601, got {ts!r}"
        )


# ===========================================================================
# Path resolution — PRD §2.5
# ===========================================================================
class TestPathResolution:
    """PRD §2.5: "Path parameters are resolved strictly left to right".
    """

    def test_get_season_not_found(self, api, league_admin_headers):
        """PRD §2.5: "A missing `Season` surfaces as
        `ERR_SEASON_NOT_FOUND`".

        Claim: unknown Season id -> ERR_SEASON_NOT_FOUND.
        """
        resp = api.get_season(NON_EXISTENT_UUID, league_admin_headers)
        validate_error(resp, ApiErrorId.ERR_SEASON_NOT_FOUND.value)

    def test_get_team_not_found(self, api, league_admin_headers):
        """PRD §2.5: "a missing `Team` as `ERR_TEAM_NOT_FOUND`".

        Claim: unknown Team id -> ERR_TEAM_NOT_FOUND.
        """
        resp = api.get_team(NON_EXISTENT_UUID, league_admin_headers)
        validate_error(resp, ApiErrorId.ERR_TEAM_NOT_FOUND.value)

    def test_get_player_not_found(self, api, league_admin_headers):
        """PRD §2.5: "a missing `Player` as `ERR_PLAYER_NOT_FOUND`".

        Claim: unknown Player id -> ERR_PLAYER_NOT_FOUND.
        """
        resp = api.get_player(NON_EXISTENT_UUID, league_admin_headers)
        validate_error(resp, ApiErrorId.ERR_PLAYER_NOT_FOUND.value)

    def test_get_game_not_found(self, api, league_admin_headers):
        """PRD §2.5: "a missing `Game` as `ERR_GAME_NOT_FOUND`".

        Claim: unknown Game id -> ERR_GAME_NOT_FOUND.
        """
        resp = api.get_game(NON_EXISTENT_UUID, league_admin_headers)
        validate_error(resp, ApiErrorId.ERR_GAME_NOT_FOUND.value)

    def test_get_volunteer_shift_not_found(self, api, league_admin_headers):
        """PRD §2.5: "a missing `VolunteerShift` as
        `ERR_SHIFT_NOT_FOUND`".

        Claim: unknown shift id -> ERR_SHIFT_NOT_FOUND.
        """
        resp = api.get_volunteer_shift(
            NON_EXISTENT_UUID, league_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SHIFT_NOT_FOUND.value)


# ===========================================================================
# Pagination — PRD §2.3
# ===========================================================================
class TestPagination:
    """PRD §2.3: "The default `limit` is 10, with a minimum of 1 and a
    maximum of 100; the default `offset` is 0. Results are returned
    sorted by `created_at` in ascending order. Every list response
    surfaces `limit`, `offset`, `total_count`, and `has_more` inside
    the `meta` block".
    """

    def test_list_audit_events_meta_block(self, api, league_admin_headers):
        """PRD §2.3: "Every list response surfaces `limit`, `offset`,
        `total_count`, and `has_more` inside the `meta` block".

        Claim: GET /league/audit-events returns meta with the four
        pagination fields.
        """
        resp = api.list_audit_events(league_admin_headers)
        data, meta = validate_paginated(resp)
        for k in ("limit", "offset", "total_count", "has_more"):
            assert k in meta, f"meta missing '{k}'"
