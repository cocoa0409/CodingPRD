"""Response envelope, player master data, not-found and auth behavior."""
import re

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_iso8601_instant_equal,
    assert_player,
    create_player,
    is_valid_uuid,
    make_player_headers,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["organizer_admin_headers"]
TD = TEST_USERS["tournament_director_headers"]

FRACTIONAL_3 = re.compile(r"\.\d{3}(Z|[+-]\d{2}:?\d{2})$")


class TestResponseEnvelope:

    def test_response_envelope_meta_and_error_shape(self):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/endpoints/response_envelope_meta_and_error_shape
        """
        resp = api_client.create_player(
            {"handle": "env", "date_of_birth": "2001-01-01",
             "region": "APAC"}, ADMIN)
        body = resp.json()
        assert resp.status_code == 201, resp.text
        assert body["meta"]["api_request_id"].startswith("req_"), \
            "api_request_id must start with req_"
        ts = body["meta"]["api_request_timestamp"]
        assert isinstance(ts, str) and FRACTIONAL_3.search(ts), \
            f"api_request_timestamp must carry three fractional digits: {ts}"
        assert body["response_type"] == "object"
        assert is_valid_uuid(body["data"]["id"])

        err_resp = api_client.get_player(NON_EXISTENT_UUID, ADMIN)
        err_body = err_resp.json()
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(err_body["data"]["message"], str)
        assert len(err_body["data"]["message"].strip()) > 0


class TestPlayerCreation:

    def test_player_create_defaults_and_system_fields(self):
        """PRD §2.4: "Every persisted resource carries a server-minted `id` —
        a UUID with no type prefix — and a `created_at` timestamp in ISO 8601
        UTC with three fractional digits."
        PRD §2.4: "The `version` starts at 1 at creation and increments by
        exactly 1 on every mutation, regardless of how many fields change;
        `updated_at` refreshes on every mutation."
        PRD §2.5: "At process start the clock reads exactly
        `2026-08-01T00:00:00Z` and never advances on its own."
        PRD §3.9: "A player's public profile carries `handle` (globally
        unique, case-sensitive — duplicates are rejected with
        `ERR_HANDLE_TAKEN`), `date_of_birth` as an ISO date in `YYYY-MM-DD`
        form, the player's home `region`, `eligibility_status`, the
        append-only `ac_strike_events` list, and the computed
        `active_strike_count`."

        Design: Corner/entities/player_create_defaults_and_system_fields
        """
        resp = api_client.create_player(
            {"handle": "solo", "date_of_birth": "1999-12-31", "region": "EU"},
            ADMIN)
        assert resp.status_code == 201, resp.text
        data = resp.json()["data"]
        assert_player(data)
        assert data["eligibility_status"] == "ELIGIBLE", \
            "a fresh player must be ELIGIBLE or the §3.2 submit flow could never run"
        assert data["active_strike_count"] == 0
        assert data["ac_strike_events"] == []
        assert data["version"] == 1
        assert FRACTIONAL_3.search(data["created_at"]), \
            f"created_at must carry three fractional digits: {data['created_at']}"
        assert_iso8601_instant_equal(data["created_at"],
                                     "2026-08-01T00:00:00Z")

    def test_player_create_missing_required_returns_invalid_request(self):
        """PRD §3.9: "A player's public profile carries `handle` (globally
        unique, case-sensitive — duplicates are rejected with
        `ERR_HANDLE_TAKEN`), `date_of_birth` as an ISO date in `YYYY-MM-DD`
        form, the player's home `region`, `eligibility_status`, the
        append-only `ac_strike_events` list, and the computed
        `active_strike_count`."
        PRD §5: "| ERR_VALIDATION | 400 |"

        Design: Corner/entities/player_create_missing_required_returns_invalid_request
        """
        resp = api_client.create_player(
            {"handle": "solo", "date_of_birth": "1999-12-31"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_player_duplicate_handle_returns_handle_taken(self):
        """PRD §3.9: "A player's public profile carries `handle` (globally
        unique, case-sensitive — duplicates are rejected with
        `ERR_HANDLE_TAKEN`), `date_of_birth` as an ISO date in `YYYY-MM-DD`
        form, the player's home `region`, `eligibility_status`, the
        append-only `ac_strike_events` list, and the computed
        `active_strike_count`."

        Design: Corner/entities/player_duplicate_handle_returns_handle_taken
        """
        create_player("solo", "1999-12-31", "EU")
        resp = api_client.create_player(
            {"handle": "solo", "date_of_birth": "2001-01-01", "region": "NA"},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_HANDLE_TAKEN)


class TestNotFound:

    def test_match_get_not_found_returns_404(self):
        """PRD §2.4: "Resources are validated left-to-right through the URL
        path before any request body is examined: a missing path segment
        yields `ERR_NOT_FOUND` (HTTP 404) before body shape is considered, and
        foreign-key references inside the body are likewise validated in body
        order after path resources resolve."

        Design: Corner/entities/match_get_not_found_returns_404
        """
        resp = api_client.get_match(NON_EXISTENT_UUID, TD)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_registration_create_with_bad_tournament_fk_returns_not_found(
            self):
        """PRD §2.4: "Resources are validated left-to-right through the URL
        path before any request body is examined: a missing path segment
        yields `ERR_NOT_FOUND` (HTTP 404) before body shape is considered, and
        foreign-key references inside the body are likewise validated in body
        order after path resources resolve."

        Design: Corner/entities/registration_create_with_bad_tournament_fk_returns_not_found
        """
        player = create_player("p1", "2000-01-01", "NA")
        resp = api_client.create_registration(
            {"tournament_id": NON_EXISTENT_UUID, "team_name": "Ghost",
             "manager_contact_email": "g@x.gg", "region_rank_points": 1,
             "prior_event_points": 0, "qualifier_wins": 0,
             "captain_player_id": player["id"]},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestAuthentication:

    def test_missing_auth_headers_returns_unauthenticated(self):
        """PRD §2.1: "Every request carries two headers: `X-User-ID` and
        `X-User-Role`. A request missing either header, or presenting a role
        the platform does not recognize, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
        """
        player = create_player("p1", "2000-01-01", "NA")
        resp = api_client.get_player(player["id"], None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
