"""Player lifecycle: PENDING_VERIFICATION → AGE_VERIFIED → EVALUATED.

Also covers age window, birth certificate, evaluation tier classification,
and withdrawal from each non-terminal state.

PRD §3.2 drives all of this; tier_classification thresholds are PRD
§2.10 / §3.2.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_DEFAULTS,
    advance_player_to_evaluated,
    advance_to_regular_season,
    assert_player,
    assert_status,
    create_guardian,
    create_player,
    create_season,
    make_guardian_headers,
    record_evaluation,
    record_evaluation_payload,
    setup_regular_season,
    setup_season_with_teams,
    validate_error,
    validate_success,
    verify_age,
    verify_age_payload,
)


# ===========================================================================
# Create player — PRD §3.2
# ===========================================================================
class TestCreatePlayer:
    """PRD §3.2: "A newly registered player begins in
    `PENDING_VERIFICATION`."
    """

    def test_create_player_starts_in_pending_verification(self, api):
        """PRD §3.2: "A newly registered player begins in
        `PENDING_VERIFICATION`."

        Claim: created Player.status == 'PENDING_VERIFICATION'.
        """
        season = create_season()
        guardian = create_guardian()
        player = create_player(
            season_id=season["id"],
            guardian_id=guardian["id"],
        )
        assert_player(player)
        assert_status(player, "PENDING_VERIFICATION")
        # team_id and draft_pick_overall default to null pre-draft.
        assert player.get("team_id") is None
        assert player.get("draft_pick_overall") is None


# ===========================================================================
# Verify age — PRD §3.2
# ===========================================================================
class TestVerifyAge:
    """PRD §3.2: "Age verification — driven by a `LeagueAdmin` — moves
    the player from `PENDING_VERIFICATION` to `AGE_VERIFIED`."
    """

    def test_verify_age_happy_path(self, api, league_admin_headers):
        """PRD §3.2: "Age verification — driven by a `LeagueAdmin` —
        moves the player from `PENDING_VERIFICATION` to `AGE_VERIFIED`."

        Claim: after verify-age, Player.status == 'AGE_VERIFIED'.
        """
        season = create_season()
        guardian = create_guardian()
        player = create_player(
            season_id=season["id"],
            guardian_id=guardian["id"],
        )
        resp = api.verify_age(player["id"], league_admin_headers)
        data = validate_success(resp)
        assert_status(data, "AGE_VERIFIED")

    def test_verify_age_without_uri_rejected(self, api, league_admin_headers):
        """PRD §3.2: "if neither the request nor the player's stored
        value provides a non-null URI, the request fails with
        `ERR_BIRTH_CERT_REQUIRED`."

        Claim: player created without uri AND verify body without uri
        -> ERR_BIRTH_CERT_REQUIRED.
        """
        season = create_season()
        guardian = create_guardian()
        player = create_player(
            season_id=season["id"],
            guardian_id=guardian["id"],
            birth_certificate_uri=None,
        )
        resp = api.verify_age(player["id"], league_admin_headers, {})
        validate_error(resp, ApiErrorId.ERR_BIRTH_CERT_REQUIRED.value)

    def test_verify_age_outside_min_birth_date_rejected(
        self, api, league_admin_headers,
    ):
        """PRD §3.2: "The player's `birth_date` must also fall inside
        the season's birth-date window — at or after `min_birth_date`
        and at or before `max_birth_date`, with both boundary dates
        eligible — and a player outside the window is rejected with
        `ERR_AGE_INELIGIBLE`."

        Claim: birth_date one day before min_birth_date ->
        ERR_AGE_INELIGIBLE.
        """
        season = create_season(
            min_birth_date="2014-01-01T00:00:00.000Z",
            max_birth_date="2015-12-31T00:00:00.000Z",
        )
        guardian = create_guardian()
        player = create_player(
            season_id=season["id"],
            guardian_id=guardian["id"],
            birth_date="2013-12-31T00:00:00.000Z",
        )
        resp = api.verify_age(player["id"], league_admin_headers)
        validate_error(resp, ApiErrorId.ERR_AGE_INELIGIBLE.value)

    def test_verify_age_outside_max_birth_date_rejected(
        self, api, league_admin_headers,
    ):
        """PRD §3.2: "The player's `birth_date` must also fall inside
        the season's birth-date window — at or after `min_birth_date`
        and at or before `max_birth_date`, with both boundary dates
        eligible — and a player outside the window is rejected with
        `ERR_AGE_INELIGIBLE`."

        Claim: birth_date one day after max_birth_date ->
        ERR_AGE_INELIGIBLE.
        """
        season = create_season(
            min_birth_date="2014-01-01T00:00:00.000Z",
            max_birth_date="2015-12-31T00:00:00.000Z",
        )
        guardian = create_guardian()
        player = create_player(
            season_id=season["id"],
            guardian_id=guardian["id"],
            birth_date="2016-01-01T00:00:00.000Z",
        )
        resp = api.verify_age(player["id"], league_admin_headers)
        validate_error(resp, ApiErrorId.ERR_AGE_INELIGIBLE.value)

    def test_verify_age_boundary_min_inclusive(
        self, api, league_admin_headers,
    ):
        """PRD §3.2: "at or after `min_birth_date` and at or before
        `max_birth_date`, with both boundary dates eligible".

        Claim: birth_date == min_birth_date succeeds (inclusive).
        """
        min_iso = "2014-01-01T00:00:00.000Z"
        season = create_season(
            min_birth_date=min_iso,
            max_birth_date="2015-12-31T00:00:00.000Z",
        )
        guardian = create_guardian()
        player = create_player(
            season_id=season["id"],
            guardian_id=guardian["id"],
            birth_date=min_iso,
        )
        resp = api.verify_age(player["id"], league_admin_headers)
        data = validate_success(resp)
        assert_status(data, "AGE_VERIFIED")

    def test_verify_age_boundary_max_inclusive(
        self, api, league_admin_headers,
    ):
        """PRD §3.2: "at or after `min_birth_date` and at or before
        `max_birth_date`, with both boundary dates eligible".

        Claim: birth_date == max_birth_date succeeds (inclusive).
        """
        max_iso = "2015-12-31T00:00:00.000Z"
        season = create_season(
            min_birth_date="2014-01-01T00:00:00.000Z",
            max_birth_date=max_iso,
        )
        guardian = create_guardian()
        player = create_player(
            season_id=season["id"],
            guardian_id=guardian["id"],
            birth_date=max_iso,
        )
        resp = api.verify_age(player["id"], league_admin_headers)
        data = validate_success(resp)
        assert_status(data, "AGE_VERIFIED")


# ===========================================================================
# Evaluation tier — PRD §3.2 / §2.10
# ===========================================================================
class TestEvaluationTier:
    """PRD §3.2: "a score of at least 85.0 yields `TIER_A`; otherwise a
    score of at least 70.0 yields `TIER_B`; otherwise a score of at
    least 50.0 yields `TIER_C`; anything below is `TIER_D`."
    PRD §2.10: "The tier-classification thresholds are interpreted with
    the at-least operator at the boundary points (so a score of exactly
    85.0 is `TIER_A`, exactly 70.0 is `TIER_B`, exactly 50.0 is
    `TIER_C`)."
    """

    @pytest.mark.parametrize(
        "score,expected_tier",
        [
            (100.0, "TIER_A"),
            (85.0, "TIER_A"),
            (84.9, "TIER_B"),
            (70.0, "TIER_B"),
            (69.9, "TIER_C"),
            (50.0, "TIER_C"),
            (49.9, "TIER_D"),
            (0.0, "TIER_D"),
        ],
    )
    def test_tier_threshold_boundary(self, api, score, expected_tier):
        """PRD §3.2: "a score of at least 85.0 yields `TIER_A`;
        otherwise a score of at least 70.0 yields `TIER_B`; otherwise a
        score of at least 50.0 yields `TIER_C`; anything below is
        `TIER_D`."
        PRD §2.10: "a score of exactly 85.0 is `TIER_A`, exactly 70.0
        is `TIER_B`, exactly 50.0 is `TIER_C`."

        Claim: each boundary score classifies to its inclusive tier.
        """
        season = create_season()
        guardian = create_guardian()
        player = advance_player_to_evaluated(
            season_id=season["id"],
            guardian_id=guardian["id"],
            evaluation_score=score,
        )
        assert player["evaluation_score"] == pytest.approx(score, abs=0.01)
        assert player["evaluation_tier"] == expected_tier


# ===========================================================================
# Player withdrawal — PRD §3.2
# ===========================================================================
class TestWithdraw:
    """PRD §3.2: "A guardian may withdraw their own player while the
    player is in `PENDING_VERIFICATION`, `AGE_VERIFIED`, or `EVALUATED`;
    the transition moves the player's `status` to `WITHDRAWN`, which is
    terminal."
    """

    def test_withdraw_from_pending_verification(self, api):
        """PRD §3.2: "A guardian may withdraw their own player while the
        player is in `PENDING_VERIFICATION`, `AGE_VERIFIED`, or
        `EVALUATED`; the transition moves the player's `status` to
        `WITHDRAWN`".

        Claim: withdraw from PENDING_VERIFICATION succeeds.
        """
        season = create_season()
        guardian = create_guardian()
        player = create_player(
            season_id=season["id"],
            guardian_id=guardian["id"],
        )
        resp = api.withdraw_player(
            player["id"], make_guardian_headers(guardian["id"]),
        )
        data = validate_success(resp)
        assert_status(data, "WITHDRAWN")

    def test_withdraw_from_age_verified(self, api):
        """PRD §3.2: "A guardian may withdraw their own player while the
        player is in `PENDING_VERIFICATION`, `AGE_VERIFIED`, or
        `EVALUATED`".

        Claim: withdraw from AGE_VERIFIED succeeds.
        """
        season = create_season()
        guardian = create_guardian()
        player = create_player(
            season_id=season["id"],
            guardian_id=guardian["id"],
        )
        verify_age(player["id"])
        resp = api.withdraw_player(
            player["id"], make_guardian_headers(guardian["id"]),
        )
        data = validate_success(resp)
        assert_status(data, "WITHDRAWN")

    def test_withdraw_from_evaluated(self, api):
        """PRD §3.2: "A guardian may withdraw their own player while the
        player is in `PENDING_VERIFICATION`, `AGE_VERIFIED`, or
        `EVALUATED`".

        Claim: withdraw from EVALUATED succeeds.
        """
        season = create_season()
        guardian = create_guardian()
        player = advance_player_to_evaluated(
            season_id=season["id"],
            guardian_id=guardian["id"],
            evaluation_score=80.0,
        )
        resp = api.withdraw_player(
            player["id"], make_guardian_headers(guardian["id"]),
        )
        data = validate_success(resp)
        assert_status(data, "WITHDRAWN")

    def test_withdraw_by_non_owner_guardian_rejected(self, api):
        """PRD §3.2: "in either case, only the responsible guardian
        (matching `guardian_id`) — or an admin — may execute it, with a
        non-matching guardian receiving `ERR_NOT_OWNER`."

        Claim: a Guardian acting with a different guardian_id receives
        ERR_NOT_OWNER.
        """
        season = create_season()
        owning_guardian = create_guardian()
        other_guardian = create_guardian()
        player = create_player(
            season_id=season["id"],
            guardian_id=owning_guardian["id"],
        )
        # Use the OTHER guardian's headers — should be rejected.
        resp = api.withdraw_player(
            player["id"], make_guardian_headers(other_guardian["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_OWNER.value)
