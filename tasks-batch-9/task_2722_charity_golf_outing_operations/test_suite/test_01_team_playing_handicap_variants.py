"""The two treatments of a team's playing handicap."""

import pytest

from test_helpers import (
    DIRECTOR_HEADERS,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

OUTING = {
    "name": "Fairway Fund Classic",
    "format": "SCRAMBLE",
    "start_format": "TEE_TIME",
    "field_capacity_teams": 1,
    "prize_pool_cents": 60000,
}
CONTRACT = {
    "guaranteed_player_count": 4,
    "course_rating": 71.4,
    "slope_rating": 128,
    "par": 72,
    "tee_interval_minutes": 10,
    "cart_allowance_count": 4,
}
INDEXES = (12.0, 18.4, 8.2, 24.0)


def _confirmed_foursome(api):
    """One CONFIRMED foursome grouped into the team 'Birdie Boys' while OPEN."""
    ctx = fx.open_outing(api, outing=OUTING, contract=CONTRACT)
    reg = fx.confirmed_registration(
        api, ctx, players=INDEXES, buyer_name="Alders LLP",
        names=["P1", "P2", "P3", "P4"],
    )
    team = fx.new_team(api, ctx["outing_id"], reg["player_ids"], team_name="Birdie Boys")
    ctx.update(reg)
    ctx["team"] = team
    ctx["team_id"] = team["id"]
    return ctx


class TestProvisionalAndLockedPlayingHandicap:
    def test_provisional_playing_handicap_reads_the_confirmation_snapshot(self, api):
        """The PRD says that before the field is locked "the index in use is
        `handicap_index_at_confirm`, the value snapshotted when the package was
        confirmed, and `effective_handicap_index` remains null", and that under
        SCRAMBLE "the four sorted course handicaps are weighted 0.20, 0.15, 0.10,
        and 0.05 respectively, lowest handicap taking the largest weight".

        Design: Difficulty/dual_variant_calc/team_playing_handicap_provisional_vs_locked
        """
        ctx = _confirmed_foursome(api)

        course_handicaps = [
            fx.read_player(api, pid)["course_handicap"] for pid in ctx["player_ids"]
        ]
        assert course_handicaps == [13, 20, 9, 27]
        for pid in ctx["player_ids"]:
            assert fx.read_player(api, pid)["effective_handicap_index"] is None

        team = fx.read_team(api, ctx["team_id"])
        assert team["handicap_variant"] == "PROVISIONAL"
        assert team["team_playing_handicap"] == pytest.approx(7.1, abs=0.01)

    def test_locking_the_field_caps_a_six_stroke_improvement_at_three(self, api):
        """The PRD says that at the lock "`effective_handicap_index` is written as
        the larger of the golfer's current `handicap_index` and their
        `handicap_index_at_confirm` reduced by 3.0 strokes, and that capped value
        then becomes the index in use for the conversion", so "a golfer whose index
        dropped by more than three strokes since confirmation is credited with only
        a three-stroke improvement".

        Design: Difficulty/dual_variant_calc/team_playing_handicap_provisional_vs_locked
        """
        ctx = _confirmed_foursome(api)
        improved = ctx["player_ids"][3]
        validate_success(
            api.update_handicap_index(improved, f.handicap_index_payload(18.0), DIRECTOR_HEADERS)
        )

        outing = validate_success(
            api.play_transition(
                ctx["outing_id"], f.play_transition_payload("LOCK_FIELD"), DIRECTOR_HEADERS
            )
        )
        assert outing["play_status"] == "FIELD_LOCKED"

        capped = fx.read_player(api, improved)
        assert capped["effective_handicap_index"] == pytest.approx(21.0, abs=0.01)
        assert capped["course_handicap"] == 23

        team = fx.read_team(api, ctx["team_id"])
        assert team["handicap_variant"] == "LOCKED"
        assert team["team_playing_handicap"] == pytest.approx(6.9, abs=0.01)
        assert team["team_playing_handicap"] != pytest.approx(6.8, abs=0.001)

        untouched = [fx.read_player(api, pid)["course_handicap"] for pid in ctx["player_ids"][:3]]
        assert untouched == [13, 20, 9]
