"""Validation priority — single-failure tests for the priority chain.

PRD §2.6 fixes the order: auth, then existence, then state precondition,
then youth-safety, then temporal, then quota/constraint, then cross-
record referential, then OCC.

These tests construct scenarios where only ONE validation can fail,
and verify the expected error_id is returned.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_DEFAULTS,
    advance_clock_to,
    advance_to_regular_season,
    create_guardian,
    create_player,
    create_season,
    make_guardian_headers,
    setup_regular_season,
    setup_season_with_teams,
    validate_error,
    verify_age_payload,
)


# ===========================================================================
# Auth before existence — PRD §2.6
# ===========================================================================
class TestAuthBeforeExistence:
    """PRD §2.6: "Authentication is checked first (header presence,
    then RBAC, then entity-backed identity resolution), then existence".
    PRD §2.6: "The practical consequence is that an `ERR_AUTH_REQUIRED`
    will always mask any other defect in the payload, and an existence
    failure will mask any state, safety, or temporal failure."
    """

    def test_missing_auth_masks_404_on_nonexistent_path(self, api):
        """PRD §2.6: "an `ERR_AUTH_REQUIRED` will always mask any other
        defect in the payload".

        Claim: GET /league/players/{nonexistent} without auth header ->
        ERR_AUTH_REQUIRED, not ERR_PLAYER_NOT_FOUND.
        """
        resp = api.get_player(NON_EXISTENT_UUID, {})
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)


# ===========================================================================
# Existence before state — PRD §2.6
# ===========================================================================
class TestExistenceBeforeState:
    """PRD §2.6: "then existence (path-referenced entities left to
    right, then body-referenced foreign keys)".
    PRD §2.6: "an existence failure will mask any state, safety, or
    temporal failure."
    """

    def test_404_masks_state_failure(self, api, league_admin_headers):
        """PRD §2.6: "an existence failure will mask any state, safety,
        or temporal failure."

        Claim: verify-age on a non-existent player id ->
        ERR_PLAYER_NOT_FOUND, not any state / safety error.
        """
        resp = api.verify_age(NON_EXISTENT_UUID, league_admin_headers)
        validate_error(resp, ApiErrorId.ERR_PLAYER_NOT_FOUND.value)


# ===========================================================================
# State season-not-draft-open — PRD §2.6
# ===========================================================================
class TestSeasonNotDraftOpen:
    """PRD §2.6: "the season-window check
    (`ERR_SEASON_NOT_DRAFT_OPEN`) where draft-era operations require a
    `DRAFT_OPEN` season".
    """

    def test_verify_age_after_regular_season_starts_rejects(
        self, api, league_admin_headers,
    ):
        """PRD §3.2: "The verification is only valid while the season
        is in `DRAFT_OPEN`; an attempt after that surfaces as
        `ERR_SEASON_NOT_DRAFT_OPEN`."

        Claim: verify-age when Season.status == 'REGULAR_SEASON' (and
        the player itself is PENDING_VERIFICATION with a valid uri) ->
        ERR_SEASON_NOT_DRAFT_OPEN.
        """
        # Build a regular season but add a fresh PENDING_VERIFICATION
        # player so the player's own state is valid for verify-age.
        bundle = setup_regular_season(n_teams=4, players_per_team=8)
        season = bundle["season"]
        guardian = create_guardian()
        # Create the player AFTER season transition. PRD does not forbid
        # registering players after DRAFT_OPEN — the verify-age call is
        # the one that requires DRAFT_OPEN.
        player = create_player(
            season_id=season["id"],
            guardian_id=guardian["id"],
        )
        resp = api.verify_age(player["id"], league_admin_headers)
        validate_error(
            resp, ApiErrorId.ERR_SEASON_NOT_DRAFT_OPEN.value,
        )


# ===========================================================================
# Reference not found — PRD §2.5
# ===========================================================================
class TestBodyReferenceNotFound:
    """PRD §2.5: "Body-supplied foreign keys — `guardian_id`,
    `head_coach_id`, `home_team_id`, `away_team_id`, `referee_id`,
    `forfeiting_team_id`, and so on — are checked after path validation
    and surface as `ERR_REFERENCE_NOT_FOUND` (HTTP 404) when they do
    not resolve."
    """

    def test_create_player_with_unknown_guardian_id_rejects(
        self, api, league_admin_headers,
    ):
        """PRD §2.5: "Body-supplied foreign keys — `guardian_id`,
        `head_coach_id`, `home_team_id`, `away_team_id`, `referee_id`,
        `forfeiting_team_id`, and so on — are checked after path
        validation and surface as `ERR_REFERENCE_NOT_FOUND` (HTTP 404)
        when they do not resolve."

        Claim: POST /league/players with unknown guardian_id ->
        ERR_REFERENCE_NOT_FOUND.
        """
        season = create_season()
        payload = {
            "season_id": season["id"],
            "first_name": "X",
            "last_name": "Y",
            "birth_date": "2015-06-01T00:00:00.000Z",
            "guardian_id": NON_EXISTENT_UUID,
        }
        resp = api.create_player(payload, league_admin_headers)
        validate_error(
            resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value,
        )

    def test_create_player_with_unknown_season_id_rejects(
        self, api, league_admin_headers,
    ):
        """PRD §2.5: "Body-supplied foreign keys — `guardian_id`,
        `head_coach_id`, `home_team_id`, `away_team_id`, `referee_id`,
        `forfeiting_team_id`, and so on — are checked after path
        validation and surface as `ERR_REFERENCE_NOT_FOUND` (HTTP 404)
        when they do not resolve."

        Claim: POST /league/players with unknown season_id ->
        ERR_REFERENCE_NOT_FOUND.
        """
        guardian = create_guardian()
        payload = {
            "season_id": NON_EXISTENT_UUID,
            "first_name": "X",
            "last_name": "Y",
            "birth_date": "2015-06-01T00:00:00.000Z",
            "guardian_id": guardian["id"],
        }
        resp = api.create_player(payload, league_admin_headers)
        validate_error(
            resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value,
        )
