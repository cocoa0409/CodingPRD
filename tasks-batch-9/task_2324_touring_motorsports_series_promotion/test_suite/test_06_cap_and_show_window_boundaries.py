"""Inclusive boundaries on the marketing channel cap and the show window.

Both ceilings admit a total that lands exactly on them and reject the very next
cent or minute, so each is pinned from both sides: the exact-fit call succeeds and
the one-unit overshoot is rejected, with the ledgers and the run order shown
untouched afterwards.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

from test_helpers import (
    ApiClient,
    ApiErrorId,
    assert_marketing_allocation,
    assert_marketing_budget_conserved,
    assert_show_segment,
    make_marketing_allocation_payload,
    make_series_promoter_headers,
    make_show_segment_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as helpers


# A forty-thousand-dollar season budget gives a stop ceiling of 8,000,000 cents
# and a GRASSROOTS ceiling of 2,400,000 cents, both landing on whole cents.
_SEASON_BUDGET_CENTS = 40000000
_GRASSROOTS_CAP_CENTS = 2400000


def _confirmed_stop(api: ApiClient) -> Dict[str, Any]:
    """A confirmed stop in the primary market with no marketing money committed."""
    return helpers.confirmed_booking(
        api, total_marketing_budget_cents=_SEASON_BUDGET_CENTS
    )


def _commit(
    api: ApiClient, stop_id: str, season_id: str, channel: str, amount_cents: int
):
    """Commit spend on one channel, reading the season's version immediately first."""
    return api.create_marketing_allocation(
        stop_id,
        make_marketing_allocation_payload(
            helpers.fetch_season_version(api, season_id),
            channel=channel,
            amount_cents=amount_cents,
        ),
        headers=make_series_promoter_headers(),
    )


# The run order that fills a 150-minute window to the minute. Only the two
# adjacent COMPETITION pairs earn a floor reset, which is what makes the last
# segment 14 minutes rather than 30.
_EXACT_FIT_RUN_ORDER: Sequence[Tuple[str, str, int, int]] = (
    ("COMPETITION", "Heat 1", 1, 30),
    ("INTERMISSION", "Freestyle Show", 2, 20),
    ("COMPETITION", "Heat 2", 3, 30),
    ("COMPETITION", "Heat 3", 4, 40),
    ("COMPETITION", "Main Event", 5, 14),
)


def _insert_segment(
    api: ApiClient,
    stop_id: str,
    segment_type: str,
    title: str,
    position: int,
    duration_minutes: int,
):
    """Insert one run-order segment at a position, as the promoter."""
    return api.create_show_segment(
        stop_id,
        make_show_segment_payload(
            segment_type=segment_type,
            title=title,
            run_order_position=position,
            duration_minutes=duration_minutes,
        ),
        headers=make_series_promoter_headers(),
    )


def _pack_run_order(
    api: ApiClient,
    stop_id: str,
    plan: Sequence[Tuple[str, str, int, int]] = _EXACT_FIT_RUN_ORDER,
) -> List[Dict[str, Any]]:
    """Insert a whole run order in ascending position order, returning the rows."""
    rows: List[Dict[str, Any]] = []
    for segment_type, title, position, duration_minutes in plan:
        rows.append(
            validate_success(
                _insert_segment(
                    api, stop_id, segment_type, title, position, duration_minutes
                ),
                expected_status=201,
            )
        )
    return rows


def _segments_by_position(api: ApiClient, stop_id: str) -> Dict[int, Dict[str, Any]]:
    """The stop's run order, keyed by position."""
    rows, _ = validate_paginated(
        api.list_show_segments(stop_id, headers=make_series_promoter_headers())
    )
    return {row["run_order_position"]: row for row in rows}


# ---------------------------------------------------------------------------
# The GRASSROOTS channel ceiling
# ---------------------------------------------------------------------------


class TestGrassrootsChannelCapBoundary:
    """Thirty percent of the stop ceiling, admitted exactly and then overshot."""

    def test_a_channel_total_landing_exactly_on_the_ceiling_is_admitted(
        self, api: ApiClient
    ) -> None:
        """PRD §3.9: "The per-stop ceiling is 20 percent of the season's
        `total_marketing_budget_cents`, rounded half up to whole cents; each
        channel's ceiling is a share of that stop ceiling, again rounded half up —
        40 percent for `RADIO`, 60 percent for `DIGITAL` and 30 percent for
        `GRASSROOTS`."
        PRD §3.9: "All caps are inclusive: a running total landing exactly on a
        ceiling is admitted."

        Design: Difficulty/boundary_precision_check/grassroots_channel_cap_admits_exact_equality_then_rejects_one_cent
        """
        state = _confirmed_stop(api)
        stop_id = state["stop_id"]
        season_id = state["season_id"]

        allocation = validate_success(
            _commit(api, stop_id, season_id, "GRASSROOTS", _GRASSROOTS_CAP_CENTS),
            expected_status=201,
        )
        assert_marketing_allocation(allocation)
        assert allocation["channel"] == "GRASSROOTS"
        assert allocation["amount_cents"] == 2400000, (
            "thirty percent of the 8,000,000 cent stop ceiling"
        )
        assert allocation["state"] == "COMMITTED"
        assert allocation["released_at"] is None

        stop = helpers.fetch_stop(api, stop_id)
        assert stop["marketing_spend_committed_cents"] == 2400000

        season = helpers.fetch_season(api, season_id)
        assert season["marketing_allocated_cents"] == 2400000
        assert season["marketing_unallocated_cents"] == 37600000
        assert_marketing_budget_conserved(season)

    def test_one_cent_past_the_channel_ceiling_reports_the_channel_cap(
        self, api: ApiClient
    ) -> None:
        """PRD §3.9: "First, the channel running total after this commit — the sum
        of `amount_cents` over the stop's `COMMITTED` allocations on the same
        channel, plus this `amount_cents` — must not exceed that channel's ceiling,
        or the request is rejected with `ERR_CHANNEL_CAP_EXCEEDED`."
        PRD §2.10: "Note the ordering consequence in the marketing tier: the
        channel cap is checked before the per-stop cap, which is checked before the
        season pool, so an allocation that breaches two of them reports the earliest
        breach."

        Design: Difficulty/boundary_precision_check/grassroots_channel_cap_admits_exact_equality_then_rejects_one_cent
        """
        state = _confirmed_stop(api)
        stop_id = state["stop_id"]
        season_id = state["season_id"]
        validate_success(
            _commit(api, stop_id, season_id, "GRASSROOTS", _GRASSROOTS_CAP_CENTS),
            expected_status=201,
        )
        version_before = helpers.fetch_season_version(api, season_id)

        response = _commit(api, stop_id, season_id, "GRASSROOTS", 1)
        error = validate_error(
            response, ApiErrorId.ERR_CHANNEL_CAP_EXCEEDED, expected_status=409
        )
        assert error["error_id"] != ApiErrorId.ERR_STOP_MARKETING_CAP_EXCEEDED.value, (
            "the stop ceiling still has 5,599,999 cents of headroom, so only the "
            "channel ceiling can be the reported failure"
        )

        stop = helpers.fetch_stop(api, stop_id)
        assert stop["marketing_spend_committed_cents"] == 2400000, (
            "a rejected commit moves no money"
        )
        season = helpers.fetch_season(api, season_id)
        assert season["marketing_allocated_cents"] == 2400000
        assert season["version"] == version_before, (
            "a rejected commit does not bump the season's version"
        )

        rows, meta = validate_paginated(
            api.list_marketing_allocations(
                stop_id, {"channel": "GRASSROOTS"}, headers=make_series_promoter_headers()
            )
        )
        assert meta["total_count"] == 1, "the rejected commit must leave no trace"
        assert [row["amount_cents"] for row in rows] == [2400000]

    def test_the_same_cent_is_admitted_on_a_channel_with_headroom(
        self, api: ApiClient
    ) -> None:
        """PRD §3.9: "The commit adds `amount_cents` to the season's
        `marketing_allocated_cents`, recomputes `marketing_unallocated_cents` as the
        total budget minus the allocated figure, increments the season's `version`
        by one, adds `amount_cents` to the stop's
        `marketing_spend_committed_cents`, and recomputes the stop's posture — which
        is how the first marketing dollar in a market lifts one of the conditions
        holding the stop at `RESTRICTED`."

        Design: Difficulty/boundary_precision_check/grassroots_channel_cap_admits_exact_equality_then_rejects_one_cent
        """
        state = _confirmed_stop(api)
        stop_id = state["stop_id"]
        season_id = state["season_id"]
        validate_success(
            _commit(api, stop_id, season_id, "GRASSROOTS", _GRASSROOTS_CAP_CENTS),
            expected_status=201,
        )
        # The premise of the comparison: this cent is inadmissible on GRASSROOTS.
        rejected = _commit(api, stop_id, season_id, "GRASSROOTS", 1)
        assert rejected.status_code == 409

        allocation = validate_success(
            _commit(api, stop_id, season_id, "DIGITAL", 1), expected_status=201
        )
        assert_marketing_allocation(allocation)
        assert allocation["channel"] == "DIGITAL"
        assert allocation["amount_cents"] == 1
        assert allocation["state"] == "COMMITTED"

        stop = helpers.fetch_stop(api, stop_id)
        assert stop["marketing_spend_committed_cents"] == 2400001

        season = helpers.fetch_season(api, season_id)
        assert season["marketing_allocated_cents"] == 2400001
        assert season["marketing_unallocated_cents"] == 37599999
        assert_marketing_budget_conserved(season)


# ---------------------------------------------------------------------------
# The show window ceiling
# ---------------------------------------------------------------------------


class TestRunOrderShowWindowBoundary:
    """A run order packed to the minute, then one minute too long."""

    def test_the_timeline_walk_places_floor_resets_only_between_heats(
        self, api: ApiClient
    ) -> None:
        """PRD §3.4: "For each segment in turn, `reset_gap_minutes` is set to 8
        minutes when the immediately preceding position's segment is also of type
        `COMPETITION` and this segment is of type `COMPETITION`, and to 0 in every
        other case, including the very first segment; that reset gap accounts for
        clearing and re-preparing the floor between heats."
        PRD §3.4: "The offset advances by the reset gap, `start_offset_minutes` is
        written as the offset, `end_offset_minutes` is written as the offset plus
        the segment's `duration_minutes`, and the offset then advances to that end
        value — so segments sit flush against each other with a gap of zero, which
        is legal."

        Design: Difficulty/boundary_precision_check/run_order_exact_fit_at_the_show_window_then_one_more_segment_overruns
        """
        state = helpers.stop_with_show_timing(api, show_window_minutes=150)
        stop_id = state["stop_id"]
        _pack_run_order(api, stop_id, _EXACT_FIT_RUN_ORDER[:4])

        segments = _segments_by_position(api, stop_id)
        expected = {
            1: (0, 0, 30),
            2: (0, 30, 50),
            3: (0, 50, 80),
            4: (8, 88, 128),
        }
        for position, (reset, start, end) in expected.items():
            row = segments[position]
            assert_show_segment(row)
            assert row["reset_gap_minutes"] == reset, (
                f"position {position} reset gap"
            )
            assert row["start_offset_minutes"] == start, (
                f"position {position} start offset"
            )
            assert row["end_offset_minutes"] == end, f"position {position} end offset"

    def test_a_run_order_filling_the_show_window_exactly_is_admissible(
        self, api: ApiClient
    ) -> None:
        """PRD §3.4: "When the walk finishes, the stop's
        `run_order_end_offset_minutes` is set to the final offset, which is exactly
        the `end_offset_minutes` of the highest-positioned segment."
        PRD §3.4: "Equality is allowed — a run order that fills the window exactly
        is admissible."

        Design: Difficulty/boundary_precision_check/run_order_exact_fit_at_the_show_window_then_one_more_segment_overruns
        """
        state = helpers.stop_with_show_timing(api, show_window_minutes=150)
        stop_id = state["stop_id"]
        rows = _pack_run_order(api, stop_id)

        main_event = rows[-1]
        assert_show_segment(main_event)
        assert main_event["title"] == "Main Event"
        assert main_event["reset_gap_minutes"] == 8
        assert main_event["start_offset_minutes"] == 136
        assert main_event["end_offset_minutes"] == 150

        stop = helpers.fetch_stop(api, stop_id)
        assert stop["show_window_minutes"] == 150
        assert stop["run_order_end_offset_minutes"] == 150, (
            "the run order lands on the window rather than inside it"
        )

    def test_one_more_minute_of_run_order_overruns_the_show_window(
        self, api: ApiClient
    ) -> None:
        """PRD §3.4: "Aggregate capacity is then checked: if the recomputed
        `run_order_end_offset_minutes` is strictly greater than the stop's
        `show_window_minutes`, the insert is rejected with
        `ERR_SHOW_WINDOW_EXCEEDED`."
        PRD §3.4: "Each insert also refreshes the stop's
        `competition_segment_count`, which is the number of the stop's segments
        whose `segment_type` is `COMPETITION`, and recomputes the posture — which
        matters because a stop with zero competition segments is held at
        `RESTRICTED` and cannot open sales."

        Design: Difficulty/boundary_precision_check/run_order_exact_fit_at_the_show_window_then_one_more_segment_overruns
        """
        state = helpers.stop_with_show_timing(api, show_window_minutes=150)
        stop_id = state["stop_id"]
        _pack_run_order(api, stop_id)

        # A one-minute heat after another heat still costs the 8-minute floor
        # reset, so it would end at 159 minutes against a 150-minute window.
        response = _insert_segment(api, stop_id, "COMPETITION", "Bonus Heat", 6, 1)
        validate_error(
            response, ApiErrorId.ERR_SHOW_WINDOW_EXCEEDED, expected_status=409
        )

        stop = helpers.fetch_stop(api, stop_id)
        assert stop["run_order_end_offset_minutes"] == 150, (
            "a rejected insert leaves the timeline where it was"
        )
        assert stop["competition_segment_count"] == 4, (
            "the four admitted heats, and not the rejected one"
        )

        _, meta = validate_paginated(
            api.list_show_segments(stop_id, headers=make_series_promoter_headers())
        )
        assert meta["total_count"] == 5, "the rejected segment must leave no trace"
