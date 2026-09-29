"""Exact edges: the warning that first costs a stroke, and a selector run with
nothing to select.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_EMPTY_FIELD
from test_helpers.assertions import assert_two_decimals
from test_helpers.test_users import RULES_OFFICIAL, TOUR_ADMIN
from test_helpers.types import (
    PACE_WARNING,
    ROUND_SCHEDULED,
    TOURNAMENT_FIELD_SET,
)


def _round_on_the_course(api):
    """A live event with one scheduled card that observations can be logged against."""
    ctx = fx.tournament_in_progress(api, 2)
    round_row = fx.create_round(
        api, ctx["entry_ids"][0], ctx["member_ids"][1], 1, fx.TEE_TIME_ROUND_ONE
    )
    ctx["round_id"] = round_row["id"]
    return ctx


def _warn(api, round_id, minutes_behind=5):
    return validate_success(
        api.record_pace_observation(
            round_id, f.pace_observation_payload(PACE_WARNING, minutes_behind),
            RULES_OFFICIAL,
        ),
        200,
    )


class TestPaceWarningThreshold:
    """The first two warnings are free and the third is not."""

    def test_second_warning_costs_nothing_and_the_third_costs_one_stroke(self, api):
        """Three warnings five minutes behind produce exactly one penalty stroke.

        PRD: "The second warning of a round therefore still costs nothing and the
        third costs one stroke."

        Design: Difficulty/boundary_precision_check/pace_warning_third_crosses_penalty_threshold
        """
        ctx = _round_on_the_course(api)

        first = _warn(api, ctx["round_id"])
        assert first["pace_warning_count"] == 1
        assert first["pace_penalty_strokes"] == 0

        second = _warn(api, ctx["round_id"])
        assert second["pace_warning_count"] == 2
        assert second["pace_penalty_strokes"] == 0

        third = _warn(api, ctx["round_id"])
        assert third["pace_warning_count"] == 3
        assert third["pace_penalty_strokes"] == 1
        assert third["pace_penalty_strokes"] != 3
        assert third["max_minutes_behind"] == 5
        assert third["status"] == ROUND_SCHEDULED
        assert third["adjusted_gross"] is None

    def test_a_fourth_warning_costs_a_second_stroke(self, api):
        """The warning component is the count less two, so four warnings cost two.

        PRD: "The first two warnings of a round are free; each warning beyond the
        second costs one stroke, so the warning component is the
        `pace_warning_count` less two, floored at zero."

        Design: Difficulty/boundary_precision_check/pace_warning_third_crosses_penalty_threshold
        """
        ctx = _round_on_the_course(api)
        for _ in range(3):
            _warn(api, ctx["round_id"])

        fourth = _warn(api, ctx["round_id"])
        assert fourth["pace_warning_count"] == 4
        assert fourth["pace_penalty_strokes"] == 2
        assert fourth["max_minutes_behind"] == 5


class TestSelectorWithNoCandidates:
    """A field nobody entered is a legal field."""

    def test_set_field_on_an_empty_pool_succeeds_with_a_neutral_quality_factor(self, api):
        """No entries at all still lands at FIELD_SET with every slot open.

        PRD: "An empty candidate pool is a legitimate outcome, not an error."

        Design: Difficulty/boundary_precision_check/set_field_with_empty_candidate_pool_succeeds
        """
        fx.set_clock(api, fx.CLOCK_ENTRY_WINDOW)
        season = fx.create_season(api)
        tournament = fx.create_tournament(api, season["id"], name="Empty Field Regional")
        validate_success(api.open_entries(tournament["id"], TOUR_ADMIN), 200)

        fx.set_clock(api, fx.CLOCK_AFTER_ENTRY_CLOSE)
        closed = validate_success(api.close_entries(tournament["id"], TOUR_ADMIN), 200)
        assert closed["entry_count"] == 0

        field = validate_success(api.set_field(tournament["id"], TOUR_ADMIN), 200)
        assert field["status"] == TOURNAMENT_FIELD_SET
        assert field["accepted_count"] == 0
        assert field["waitlist_count"] == 0
        assert field["open_slot_count"] == 2
        assert_two_decimals(field["field_quality_factor"], 1.00,
                            "field_quality_factor")

        after = fx.read_tournament(api, tournament["id"])
        assert after["applied_count"] == 0
        assert after["closed_count"] == 0

    def test_only_starting_play_refuses_the_empty_field(self, api):
        """The selector accepts nothing; the start endpoint is what says no.

        PRD: "The tournament's `accepted_count` must be at least 1 — a tournament
        whose selector produced an empty field cannot be started, and the attempt
        is refused with `ERR_EMPTY_FIELD`."

        Design: Difficulty/boundary_precision_check/set_field_with_empty_candidate_pool_succeeds
        """
        fx.set_clock(api, fx.CLOCK_ENTRY_WINDOW)
        season = fx.create_season(api)
        tournament = fx.create_tournament(api, season["id"], name="Empty Field Regional",
                                          field_size_limit=4)
        validate_success(api.open_entries(tournament["id"], TOUR_ADMIN), 200)

        fx.set_clock(api, fx.CLOCK_AFTER_ENTRY_CLOSE)
        validate_success(api.close_entries(tournament["id"], TOUR_ADMIN), 200)
        field = validate_success(api.set_field(tournament["id"], TOUR_ADMIN), 200)
        assert field["status"] == TOURNAMENT_FIELD_SET
        assert field["open_slot_count"] == 4
        assert_two_decimals(field["field_quality_factor"], 1.00,
                            "field_quality_factor")

        fx.set_clock(api, fx.CLOCK_ROUND_ONE)
        validate_error(api.start_tournament(tournament["id"], TOUR_ADMIN),
                       ERR_EMPTY_FIELD, 409)
        assert fx.read_tournament(api, tournament["id"])["status"] == TOURNAMENT_FIELD_SET
