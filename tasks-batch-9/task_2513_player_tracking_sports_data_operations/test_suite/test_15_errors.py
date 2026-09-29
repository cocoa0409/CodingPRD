"""
Reference resolution: eleven addressable resources with eleven distinct 404s, and
the same catalogue applied to references carried in a request body.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as fac
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CLUB_NOT_FOUND,
    ERR_CONSENT_RECORD_NOT_FOUND,
    ERR_CORRECTION_REQUEST_NOT_FOUND,
    ERR_EVENT_TAG_NOT_FOUND,
    ERR_FEED_SESSION_NOT_FOUND,
    ERR_GAME_NOT_FOUND,
    ERR_INSTALLATION_NOT_FOUND,
    ERR_LICENSEE_NOT_FOUND,
    ERR_PLAYER_NOT_FOUND,
    ERR_RIGHTS_WINDOW_NOT_FOUND,
    ERR_VENUE_NOT_FOUND,
)
from test_helpers.test_users import (
    ENGINEER_HEADERS,
    OPS_HEADERS,
    REVIEWER_HEADERS,
    STATISTICIAN_HEADERS,
    make_licensee_headers,
)

UNISSUED_UUID = "00000000-0000-4000-8000-000000000000"
SECOND_DAY_START = "2026-08-02T18:00:00Z"


# ---------------------------------------------------------------------------
# One identifier, eleven resource types, eleven error ids
# ---------------------------------------------------------------------------

def test_every_addressed_resource_has_its_own_not_found_error(api):
    """PRD §2.10: "Path resolution: every path-parameter resource exists, resolved left to
    right — otherwise the matching 404 from §2.5."
    PRD §2.5: "The resolution errors are `ERR_VENUE_NOT_FOUND`,
    `ERR_INSTALLATION_NOT_FOUND`, `ERR_CLUB_NOT_FOUND`, `ERR_PLAYER_NOT_FOUND`,
    `ERR_CONSENT_RECORD_NOT_FOUND`, `ERR_GAME_NOT_FOUND`, `ERR_EVENT_TAG_NOT_FOUND`,
    `ERR_CORRECTION_REQUEST_NOT_FOUND`, `ERR_RIGHTS_WINDOW_NOT_FOUND`,
    `ERR_LICENSEE_NOT_FOUND` and `ERR_FEED_SESSION_NOT_FOUND`, each carrying HTTP 404."
    PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

    The same well-formed identifier is unknown to eleven different collections.

    Four of the calls are action endpoints whose domain rules would also have
    complained, so a state error here would mean the lookup ran too late.

    Design: Corner/errors/every_path_parameter_lookup_has_its_own_not_found_error_id
    """
    attempts = [
        (api.get_venue(UNISSUED_UUID, OPS_HEADERS), ERR_VENUE_NOT_FOUND),
        (
            api.get_installation(UNISSUED_UUID, ENGINEER_HEADERS),
            ERR_INSTALLATION_NOT_FOUND,
        ),
        (api.get_club(UNISSUED_UUID, OPS_HEADERS), ERR_CLUB_NOT_FOUND),
        (api.get_player(UNISSUED_UUID, STATISTICIAN_HEADERS), ERR_PLAYER_NOT_FOUND),
        (
            api.ratify_consent_record(UNISSUED_UUID, OPS_HEADERS),
            ERR_CONSENT_RECORD_NOT_FOUND,
        ),
        (api.get_game(UNISSUED_UUID, OPS_HEADERS), ERR_GAME_NOT_FOUND),
        (api.get_event_tag(UNISSUED_UUID, REVIEWER_HEADERS), ERR_EVENT_TAG_NOT_FOUND),
        (
            api.approve_correction(UNISSUED_UUID, REVIEWER_HEADERS),
            ERR_CORRECTION_REQUEST_NOT_FOUND,
        ),
        (
            api.revoke_rights_window(UNISSUED_UUID, OPS_HEADERS),
            ERR_RIGHTS_WINDOW_NOT_FOUND,
        ),
        (api.get_licensee(UNISSUED_UUID, OPS_HEADERS), ERR_LICENSEE_NOT_FOUND),
        (api.get_feed_session(UNISSUED_UUID, OPS_HEADERS), ERR_FEED_SESSION_NOT_FOUND),
    ]
    assert len({expected for _, expected in attempts}) == 11

    for response, expected_error_id in attempts:
        payload = validate_error(response, expected_error_id, expected_status=404)
        assert payload["message"].strip(), "every rejection carries a message"


# ---------------------------------------------------------------------------
# The same catalogue serves body-borne references
# ---------------------------------------------------------------------------

def test_body_references_are_resolved_before_any_domain_rule(api, clock):
    """PRD §2.10: "Body reference resolution: every foreign key supplied in the body
    resolves — `venue_id`, `home_club_id`, `away_club_id`, `club_id`, `game_id`,
    `player_id`, `rights_window_id`, `holder_id`, `proposed_player_id` — otherwise the
    matching 404."
    PRD §2.5: "The same catalogue serves body-borne references: a `venue_id`,
    `home_club_id`, `away_club_id`, `club_id`, `game_id`, `player_id`,
    `rights_window_id`, `holder_id` or `proposed_player_id` that does not resolve to an
    existing row is a 404 naming the missing resource type, and an unresolvable
    `holder_id` under a licensee holder is reported as `ERR_LICENSEE_NOT_FOUND`."

    A dangling reference in the body is a 404 naming the missing type.

    The polymorphic holder is resolved before the holder-type rule can complain,
    and the unknown window is reported before the scheduled game's own gate.

    Design: Corner/errors/body_foreign_keys_are_resolved_before_any_domain_rule_runs
    """
    venue = fx.register_venue(api)
    clubs = fx.register_clubs(api)
    game = get_success_data(
        api.create_game(
            fac.game_payload(venue["id"], clubs["home"]["id"], clubs["away"]["id"]),
            OPS_HEADERS,
        )
    )
    licensee = fx.onboard_licensee(api)

    validate_error(
        api.create_game(
            fac.game_payload(
                UNISSUED_UUID,
                clubs["home"]["id"],
                clubs["away"]["id"],
                scheduled_start_utc=SECOND_DAY_START,
            ),
            OPS_HEADERS,
        ),
        ERR_VENUE_NOT_FOUND,
    )
    validate_error(
        api.create_game(
            fac.game_payload(
                venue["id"],
                clubs["home"]["id"],
                UNISSUED_UUID,
                scheduled_start_utc=SECOND_DAY_START,
            ),
            OPS_HEADERS,
        ),
        ERR_CLUB_NOT_FOUND,
    )
    validate_error(
        api.create_rights_window(
            game["id"],
            fac.rights_window_payload(UNISSUED_UUID, max_latency_ms=400),
            OPS_HEADERS,
        ),
        ERR_LICENSEE_NOT_FOUND,
    )
    validate_error(
        api.create_feed_session(
            fac.feed_session_payload(
                game["id"], UNISSUED_UUID, requested_latency_ms=300
            ),
            make_licensee_headers(licensee["id"]),
        ),
        ERR_RIGHTS_WINDOW_NOT_FOUND,
    )

    _, games_meta = validate_paginated(api.list_games(OPS_HEADERS))
    assert games_meta["total_count"] == 1
    _, windows_meta = validate_paginated(
        api.list_rights_windows(game["id"], OPS_HEADERS)
    )
    assert windows_meta["total_count"] == 0
