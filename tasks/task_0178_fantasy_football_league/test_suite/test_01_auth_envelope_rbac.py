"""Authentication, role recognition, RBAC, response envelope,
pagination, and path-existence checks.

Covers PRD §2.1 (auth headers, role recognition, Manager identity),
§2.2 (envelope), §2.3 (pagination bounds), §2.7 (nested resource
resolution: ERR_RESOURCE_NOT_FOUND vs ERR_REFERENCE_NOT_FOUND), §4
(RBAC table).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_league_payload,
    create_league_with_teams,
    create_player_payload,
    create_team_payload,
    is_iso8601_timestamp,
    make_manager_headers,
    setup_drafted_league,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Auth headers — PRD §2.1
# ===========================================================================
class TestAuthHeaders:
    def test_missing_both_headers_rejected_with_auth_missing(self, api):
        """PRD §2.1: "Every request to the API must carry two mandatory HTTP headers: X-User-ID, which identifies the acting user, and X-User-Role, which declares the role the user is acting under. Requests missing either header are rejected with ERR_AUTH_MISSING."

        Claim: omission of X-User-ID and X-User-Role on a mutation
        yields ERR_AUTH_MISSING.
        """
        res = api.create_league(create_league_payload(), headers={})
        validate_error(res, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "Requests missing either header are rejected with ERR_AUTH_MISSING."

        Claim: per-header presence check; X-User-Role alone is not enough.
        """
        res = api.create_league(
            create_league_payload(),
            headers={"X-User-Role": "Commissioner"},
        )
        validate_error(res, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_missing_user_role_header_rejected(self, api):
        """PRD §2.1: "Requests missing either header are rejected with ERR_AUTH_MISSING."

        Claim: X-User-ID alone is not enough.
        """
        res = api.create_league(
            create_league_payload(),
            headers={"X-User-ID": "anyone"},
        )
        validate_error(res, ApiErrorId.ERR_AUTH_MISSING.value)

    @pytest.mark.parametrize(
        "bad_role", ["Owner", "admin", "commissioner", "MANAGER", "Referee"],
    )
    def test_unrecognized_role_rejected(self, api, bad_role):
        """PRD §2.1: "The system recognizes exactly two role names — Commissioner and Manager — and any other value submitted in X-User-Role is rejected with ERR_AUTH_INVALID_ROLE."

        Claim: roles outside {Commissioner, Manager} yield ERR_AUTH_INVALID_ROLE.
        """
        headers = {"X-User-ID": "anyone", "X-User-Role": bad_role}
        res = api.create_league(create_league_payload(), headers=headers)
        validate_error(res, ApiErrorId.ERR_AUTH_INVALID_ROLE.value)


# ===========================================================================
# RBAC — PRD §4 table
# ===========================================================================
class TestRBAC:
    def test_create_league_forbidden_for_manager(self, api, manager_fallback_headers):
        """PRD §4: "POST /leagues | Create a new league in DRAFT_PENDING. | Commissioner".

        Claim: Manager is not authorized to POST /leagues.
        PRD §2.1: "a header pair that authenticates correctly but maps to a role not permitted for the requested endpoint yields ERR_FORBIDDEN."
        """
        res = api.create_league(create_league_payload(), manager_fallback_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_create_player_forbidden_for_manager(self, api, manager_fallback_headers):
        """PRD §4: "POST /players | Register a player in the league-wide catalog. | Commissioner".

        Claim: Manager cannot POST /players.
        """
        res = api.create_player(create_player_payload(), manager_fallback_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_create_team_forbidden_for_manager(self, api, manager_fallback_headers):
        """PRD §4: "POST /leagues/{league_id}/teams | Create a team within a DRAFT_PENDING league. | Commissioner".

        Claim: Manager cannot POST /teams.
        """
        league, _ = create_league_with_teams(team_count=4)
        # Use a non-real league but the league exists; the auth check
        # fires before existence here (priority 3 vs 4).
        res = api.create_team(
            league["id"],
            create_team_payload(manager_user_id="any"),
            manager_fallback_headers,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Response envelope — PRD §2.2
# ===========================================================================
class TestSuccessEnvelope:
    def test_success_envelope_has_meta_and_data(self, api, commissioner_headers):
        """PRD §2.2: "The api_request_id is a server-generated unique identifier for the request that starts with req_."
        PRD §2.2: "The response_type is either object for a single resource or array for a list of resources."

        Claim: 2xx responses carry meta (api_request_id, api_request_timestamp),
        response_type, and data.
        """
        res = api.create_league(create_league_payload(), commissioner_headers)
        payload = res.json()
        assert "meta" in payload, "PRD §2.2: success envelope requires 'meta'"
        meta = payload["meta"]
        assert isinstance(meta.get("api_request_id"), str), \
            "PRD §2.2: meta.api_request_id required"
        assert meta["api_request_id"].startswith("req_"), \
            "PRD §2.2: api_request_id must start with 'req_'"
        assert is_iso8601_timestamp(meta.get("api_request_timestamp", "")), \
            "PRD §2.2: meta.api_request_timestamp must be ISO 8601"
        assert payload.get("response_type") == "object", \
            "PRD §2.2: single-resource responses must set response_type to 'object'"
        assert isinstance(payload.get("data"), dict), \
            "PRD §2.2: data must be an object for object-type responses"

    def test_list_endpoint_uses_array_response_type(self, api, commissioner_headers):
        """PRD §2.2: "The response_type is either object for a single resource or array for a list of resources."

        Claim: GET /players sets response_type to "array".
        """
        res = api.list_players(commissioner_headers, params={"limit": 1})
        body = res.json()
        assert body.get("response_type") == "array", \
            "PRD §2.2: list responses must set response_type to 'array'"

    def test_pagination_fields_in_meta_for_list(self, api, commissioner_headers):
        """PRD §2.3: "Every list response includes limit, offset, total_count, and has_more inside its meta envelope."

        Claim: list endpoints expose limit/offset/total_count/has_more.
        """
        res = api.list_players(commissioner_headers)
        data, meta = validate_paginated(res)
        for key in ("limit", "offset", "total_count", "has_more"):
            assert key in meta, f"PRD §2.3: meta.{key} required on list responses"


class TestErrorEnvelope:
    def test_error_envelope_carries_error_id_and_message(self, api):
        """PRD §2.2: "The error_id is a unique, machine-readable string that identifies the specific error."
        PRD §2.2: "The message provides a human-readable explanation of what went wrong."

        Claim: 4xx responses carry response_type=error and data.{error_id, message}.
        """
        res = api.create_league(create_league_payload(), headers={})
        body = res.json()
        assert body.get("response_type") == "error", \
            "PRD §2.2: error responses must set response_type to 'error'"
        assert isinstance(body.get("data", {}).get("error_id"), str)
        assert isinstance(body.get("data", {}).get("message"), str)


# ===========================================================================
# Pagination bounds — PRD §2.3
# ===========================================================================
class TestPaginationBounds:
    @pytest.mark.parametrize("limit", [0, -1, 101, 1000])
    def test_limit_out_of_range_rejected(self, api, commissioner_headers, limit):
        """PRD §2.3: "Pagination parameters outside these bounds are rejected with ERR_VALIDATION."

        Claim: limit outside [1, 100] yields ERR_VALIDATION.
        """
        res = api.list_players(commissioner_headers, params={"limit": limit})
        validate_error(res, ApiErrorId.ERR_VALIDATION.value)

    def test_negative_offset_rejected(self, api, commissioner_headers):
        """PRD §2.3: "Pagination parameters outside these bounds are rejected with ERR_VALIDATION."

        Claim: negative offset yields ERR_VALIDATION.
        """
        res = api.list_players(commissioner_headers, params={"offset": -1})
        validate_error(res, ApiErrorId.ERR_VALIDATION.value)


# ===========================================================================
# Nested resource resolution — PRD §2.7
# ===========================================================================
class TestNestedResourceResolution:
    def test_nonexistent_league_yields_resource_not_found(self, api, commissioner_headers):
        """PRD §2.7: "Path identifiers are validated strictly left-to-right: a request for a child resource under a non-existent parent fails at the parent with ERR_RESOURCE_NOT_FOUND before the child is even consulted."

        Claim: GET /leagues/{nonexistent} → ERR_RESOURCE_NOT_FOUND.
        """
        res = api.get_league(NON_EXISTENT_UUID, commissioner_headers)
        validate_error(res, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)

    def test_nonexistent_league_with_child_path_fails_at_league(
        self, api, commissioner_headers,
    ):
        """PRD §2.7: "Path identifiers are validated strictly left-to-right: a request for a child resource under a non-existent parent fails at the parent with ERR_RESOURCE_NOT_FOUND before the child is even consulted."

        Claim: GET /leagues/{nonexistent}/teams/{nonexistent} → ERR_RESOURCE_NOT_FOUND
        (the league check is left-of and must fire before the team check).
        """
        res = api.get_team(NON_EXISTENT_UUID, NON_EXISTENT_UUID, commissioner_headers)
        validate_error(res, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)

    def test_body_fk_yields_reference_not_found(
        self, api, commissioner_headers,
    ):
        """PRD §2.7: "a body whose foreign key points at a non-existent row is rejected with ERR_REFERENCE_NOT_FOUND, distinct from the 404 that applies to path identifiers."

        Claim: a body FK (proposing_team_id) pointing at a non-existent
        team yields ERR_REFERENCE_NOT_FOUND (422), not ERR_RESOURCE_NOT_FOUND.
        """
        bundle = setup_drafted_league(team_count=4)
        league = bundle["league"]
        teams = bundle["teams"]
        # Use a real team as counterparty but a bogus proposer.
        cp = teams[0]
        # Need a manager header to satisfy auth + role + ownership; but
        # ownership check (priority 6) is on the team referenced by the
        # acting Manager — that team must exist. Use cp's manager so
        # ownership check sees a real team. But the route is POST
        # /leagues/{id}/trades and PRD §1.4 priority 6 reads "Acting
        # Manager owns the team referenced in the URL/body for
        # ownership-gated actions". Here proposing_team_id is the
        # ownership FK; since it's bogus the body-FK check at priority
        # 5 fires first.
        headers = make_manager_headers(cp["manager_user_id"])
        # Build a syntactically-valid trade payload with a non-existent
        # proposing_team_id.
        payload = {
            "proposing_team_id": NON_EXISTENT_UUID,
            "counterparty_team_id": cp["id"],
            "send_player_ids": [NON_EXISTENT_UUID],
            "receive_player_ids": [NON_EXISTENT_UUID],
        }
        res = api.create_trade(league["id"], payload, headers)
        validate_error(res, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)
