"""Two temporal-occupancy rules whose interval conventions deliberately differ.

An experiment reserves its channel over a half-open interval, and the quarantine
buffer that widens that reservation is added to the incumbent's tail alone, so
the same pair of dates conflicts or clears depending on which of the two rows is
holding the buffer. A data window, by contrast, is compared against its siblings
over the closed interval — endpoints included, no buffer at all — and the
comparison is scoped by `granularity`, so two windows over the very same calendar
stretch coexist as long as they chop it differently. The same window's own
observation grid then goes back to the half-open reading, which is what makes the
asymmetry observable from one fixture.
"""

from typing import Any, Dict, Optional

from test_helpers import ApiClient, validate_error, validate_paginated, validate_success
from test_helpers import assertions as expect
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.api_errors import ApiErrorId

# The incumbent experiment's in-market period and its quarantine, which together
# make its occupied interval [2026-09-07, 2026-10-12).
_INCUMBENT_START = "2026-09-07T00:00:00Z"
_INCUMBENT_END = "2026-10-05T00:00:00Z"
_INCUMBENT_WASHOUT_DAYS = 7

# One day before the incumbent's quarantine expires, and the day it expires.
_ONE_DAY_BEFORE_BUFFER_CLEARS = "2026-10-11T00:00:00Z"
_ONE_DAY_BEFORE_BUFFER_CLEARS_END = "2026-11-08T00:00:00Z"
_BUFFER_CLEARS = "2026-10-12T00:00:00Z"
_BUFFER_CLEARS_END = "2026-11-09T00:00:00Z"

# A candidate that runs up to the incumbent's own start and carries a long
# quarantine of its own, which the occupancy test must not charge it for.
_EARLIER_CANDIDATE_START = "2026-08-10T00:00:00Z"
_EARLIER_CANDIDATE_END = _INCUMBENT_START
_EARLIER_CANDIDATE_WASHOUT_DAYS = 30

# A weekly window that starts on the canonical window's own end date, so the two
# touch at exactly one endpoint.
_TOUCHING_WINDOW_START = "2026-08-31T00:00:00Z"
_TOUCHING_WINDOW_END = "2026-09-28T00:00:00Z"

# Period counts the two granularities derive from a twenty-eight-day range.
_WEEKLY_EXPECTED_PERIOD_COUNT = 4
_DAILY_EXPECTED_PERIOD_COUNT = 28

# Period boundaries probed against the canonical weekly window
# [2026-08-03, 2026-08-31): the last legal one, one that is on no weekly
# boundary, and the exclusive end date itself.
_LAST_LEGAL_PERIOD = "2026-08-24T00:00:00Z"
_OFF_GRID_PERIOD = "2026-08-04T00:00:00Z"
_EXCLUSIVE_END_PERIOD = "2026-08-31T00:00:00Z"


def _market(api: ApiClient) -> Dict[str, Any]:
    """The canonical market and its two channels; its posture is not FROZEN."""
    ctx = fx.market_with_channels(api)
    assert ctx["market"]["data_posture"] != "FROZEN"
    return ctx


def _incumbent_on_a_search(api: ApiClient, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """One locked experiment on A_SEARCH, occupying [2026-09-07, 2026-10-12)."""
    experiment = fx.locked_experiment(
        api,
        ctx,
        start_date=_INCUMBENT_START,
        end_date=_INCUMBENT_END,
        washout_days=_INCUMBENT_WASHOUT_DAYS,
    )
    assert experiment["status"] == "DESIGN_LOCKED"
    return experiment


def _candidate(
    api: ApiClient,
    ctx: Dict[str, Any],
    start_date: str,
    end_date: str,
    channel_id: Optional[str] = None,
    washout_days: int = _INCUMBENT_WASHOUT_DAYS,
) -> Dict[str, Any]:
    """A drafted sibling on one channel of the same market."""
    return fx.create_experiment(
        api,
        ctx,
        channel_id=channel_id,
        start_date=start_date,
        end_date=end_date,
        washout_days=washout_days,
    )


def test_lock_refused_one_day_inside_the_incumbents_washout_buffer(api):
    """PRD §3.6: "Touching is therefore allowed: a candidate whose `start_date`
    equals an incumbent's `end_date` plus that incumbent's `washout_days` is
    fine, while one day earlier is a conflict and answers
    `ERR_EXPERIMENT_WINDOW_CONFLICT`."

    The incumbent's own in-market period ended on 2026-10-05, so a candidate
    starting 2026-10-11 clears the period outright; only the seven quarantine days
    appended to the incumbent's tail put it in the way.

    Design: Difficulty/resource_temporal_overlap/experiment_channel_window_half_open_with_incumbent_washout_buffer
    """
    ctx = _market(api)
    incumbent = _incumbent_on_a_search(api, ctx)
    candidate = _candidate(
        api, ctx, _ONE_DAY_BEFORE_BUFFER_CLEARS, _ONE_DAY_BEFORE_BUFFER_CLEARS_END
    )

    response = api.lock_design(candidate["id"], users.EXPERIMENT_DESIGNER)
    validate_error(response, ApiErrorId.ERR_EXPERIMENT_WINDOW_CONFLICT.value, 409)

    after = validate_success(api.get_experiment(candidate["id"], users.EXPERIMENT_DESIGNER))
    assert after["status"] == "DRAFT"
    expect.assert_version_unchanged(candidate, after)
    expect.assert_draft_experiment_fields_cleared(after)

    still_locked = validate_success(
        api.get_experiment(incumbent["id"], users.EXPERIMENT_DESIGNER)
    )
    assert still_locked["status"] == "DESIGN_LOCKED"
    expect.assert_version_unchanged(incumbent, still_locked)


def test_lock_admitted_on_the_day_the_incumbents_washout_buffer_clears(api):
    """PRD §3.6: "Touching is therefore allowed: a candidate whose `start_date`
    equals an incumbent's `end_date` plus that incumbent's `washout_days` is
    fine, while one day earlier is a conflict and answers
    `ERR_EXPERIMENT_WINDOW_CONFLICT`."

    2026-10-12 is exactly 2026-10-05 advanced by seven days, and the incumbent's
    occupied interval excludes it. PRD §3.6 then says what the accepted lock
    writes: "A successful lock freezes `power_index` and `computed_power` onto the
    row, sets `status` to `DESIGN_LOCKED` and increments `version`."

    Design: Difficulty/resource_temporal_overlap/experiment_channel_window_half_open_with_incumbent_washout_buffer
    """
    ctx = _market(api)
    incumbent = _incumbent_on_a_search(api, ctx)
    candidate = _candidate(api, ctx, _BUFFER_CLEARS, _BUFFER_CLEARS_END)

    locked = validate_success(
        api.lock_design(candidate["id"], users.EXPERIMENT_DESIGNER)
    )
    assert locked["status"] == "DESIGN_LOCKED"
    assert locked["version"] == candidate["version"] + 1
    assert locked["power_index"] is not None
    expect.assert_power_step(locked)
    assert locked["computed_power"] >= 0.80

    rows, meta = validate_paginated(
        api.list_experiments(
            users.EXPERIMENT_DESIGNER,
            {"channel_id": ctx["a_search"]["id"], "status": "DESIGN_LOCKED"},
        )
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {incumbent["id"], locked["id"]}


def test_candidates_own_washout_is_never_charged_against_its_leading_edge(api):
    """PRD §3.6: "The test is deliberately asymmetric: the candidate occupies the
    half-open interval from its own `start_date` up to but not including its
    `end_date`, while each incumbent occupies the half-open interval from its
    `start_date` up to but not including its `end_date` advanced by its own
    `washout_days` — the quarantine buffer is appended to the incumbent's tail
    only, never to the candidate's."

    The candidate here ends on the incumbent's own `start_date` and carries thirty
    quarantine days of its own. Charging the candidate for that buffer would drive
    it thirty days into the incumbent; charging only the incumbent leaves the two
    merely touching, which is admissible.

    Design: Difficulty/resource_temporal_overlap/experiment_channel_window_half_open_with_incumbent_washout_buffer
    """
    ctx = _market(api)
    _incumbent_on_a_search(api, ctx)
    candidate = _candidate(
        api,
        ctx,
        _EARLIER_CANDIDATE_START,
        _EARLIER_CANDIDATE_END,
        washout_days=_EARLIER_CANDIDATE_WASHOUT_DAYS,
    )
    assert candidate["washout_days"] == _EARLIER_CANDIDATE_WASHOUT_DAYS

    locked = validate_success(
        api.lock_design(candidate["id"], users.EXPERIMENT_DESIGNER)
    )
    assert locked["status"] == "DESIGN_LOCKED"
    assert locked["version"] == candidate["version"] + 1
    assert locked["washout_days"] == _EARLIER_CANDIDATE_WASHOUT_DAYS


def test_occupancy_is_scoped_to_the_channel_under_measurement(api):
    """PRD §3.6: "No other experiment on the same market and channel whose status
    is `DESIGN_LOCKED`, `CELLS_ASSIGNED`, `RUNNING`, `READ_OUT` or `ACCEPTED` may
    occupy an overlapping interval."

    The interval refused on A_SEARCH one test earlier is admitted verbatim on
    B_SOCIAL, because the reservation belongs to a market-and-channel pair rather
    than to the market alone.

    Design: Difficulty/resource_temporal_overlap/experiment_channel_window_half_open_with_incumbent_washout_buffer
    """
    ctx = _market(api)
    _incumbent_on_a_search(api, ctx)

    on_a_search = _candidate(
        api, ctx, _ONE_DAY_BEFORE_BUFFER_CLEARS, _ONE_DAY_BEFORE_BUFFER_CLEARS_END
    )
    refused = api.lock_design(on_a_search["id"], users.EXPERIMENT_DESIGNER)
    validate_error(refused, ApiErrorId.ERR_EXPERIMENT_WINDOW_CONFLICT.value, 409)

    on_b_social = _candidate(
        api,
        ctx,
        _ONE_DAY_BEFORE_BUFFER_CLEARS,
        _ONE_DAY_BEFORE_BUFFER_CLEARS_END,
        channel_id=ctx["b_social"]["id"],
    )
    locked = validate_success(
        api.lock_design(on_b_social["id"], users.EXPERIMENT_DESIGNER)
    )
    assert locked["status"] == "DESIGN_LOCKED"
    assert locked["channel_id"] == ctx["b_social"]["id"]


def test_draft_sibling_reserves_no_interval_at_all(api):
    """PRD §3.6: "A `DRAFT` sibling reserves nothing — it may never lock — and a
    `REJECTED` or `CLOSED` one has already given the channel back, so only
    locked-or-later experiments occupy time."

    Two drafts are written over the identical interval on the identical channel.
    Whichever locks first takes the channel; the other, now facing a
    `DESIGN_LOCKED` incumbent, answers `ERR_EXPERIMENT_WINDOW_CONFLICT` — so the
    draft never reserved anything, it merely lost the race.

    Design: Difficulty/resource_temporal_overlap/experiment_channel_window_half_open_with_incumbent_washout_buffer
    """
    ctx = _market(api)
    first = _candidate(api, ctx, _INCUMBENT_START, _INCUMBENT_END)
    second = _candidate(api, ctx, _INCUMBENT_START, _INCUMBENT_END)
    assert first["status"] == "DRAFT"
    assert second["status"] == "DRAFT"

    # A draft incumbent reserves nothing, so the first lock sees a clear channel.
    locked = validate_success(api.lock_design(first["id"], users.EXPERIMENT_DESIGNER))
    assert locked["status"] == "DESIGN_LOCKED"

    response = api.lock_design(second["id"], users.EXPERIMENT_DESIGNER)
    validate_error(response, ApiErrorId.ERR_EXPERIMENT_WINDOW_CONFLICT.value, 409)
    after = validate_success(api.get_experiment(second["id"], users.EXPERIMENT_DESIGNER))
    assert after["status"] == "DRAFT"
    expect.assert_version_unchanged(second, after)


def test_rejected_incumbent_hands_the_channel_back_before_its_washout_expires(api):
    """PRD §3.6: "A `DRAFT` sibling reserves nothing — it may never lock — and a
    `REJECTED` or `CLOSED` one has already given the channel back, so only
    locked-or-later experiments occupy time."

    The incumbent here is carried all the way to `REJECTED`, which is outside the
    occupying set, so the interval it once held — quarantine buffer and all — is
    free again even though the clock has not reached the end of that quarantine.

    Design: Difficulty/resource_temporal_overlap/experiment_channel_window_half_open_with_incumbent_washout_buffer
    """
    ctx = _market(api)
    incumbent = fx.rejected_experiment(
        api,
        ctx,
        start_date=_INCUMBENT_START,
        end_date=_INCUMBENT_END,
        washout_days=_INCUMBENT_WASHOUT_DAYS,
    )
    assert incumbent["status"] == "REJECTED"

    candidate = _candidate(
        api, ctx, _ONE_DAY_BEFORE_BUFFER_CLEARS, _ONE_DAY_BEFORE_BUFFER_CLEARS_END
    )
    locked = validate_success(
        api.lock_design(candidate["id"], users.EXPERIMENT_DESIGNER)
    )
    assert locked["status"] == "DESIGN_LOCKED"
    assert locked["version"] == candidate["version"] + 1


def _window_response(api: ApiClient, market_id: str, **overrides: Any):
    """Attempt to open a window, handing back the raw response."""
    return api.create_data_window(
        f.data_window_payload(market_id, **overrides), users.DATA_ENGINEER
    )


def _windows_of(api: ApiClient, market_id: str):
    """Every window of one market, with the page meta that framed the list."""
    return validate_paginated(
        api.list_data_windows(users.DATA_ENGINEER, {"market_id": market_id})
    )


def test_window_starting_on_an_incumbents_end_date_collides(api):
    """PRD §3.2: "The consequence is that two back-to-back windows whose endpoints
    merely touch do conflict: a window ending 2026-08-31 blocks a new window
    starting 2026-08-31, and the new window must start 2026-09-01 or later."

    The incumbent's own range is half-open, so 2026-08-31 is not one of its
    periods at all; it is the closed conflict interval that still counts the
    endpoint as occupied. PRD §3.2: "A genuine collision is
    `ERR_DATA_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/data_window_closed_interval_touching_conflict_scoped_by_granularity
    """
    ctx = _market(api)
    incumbent = fx.create_data_window(api, ctx["market"]["id"])
    assert incumbent["granularity"] == "WEEKLY"

    response = _window_response(
        api,
        ctx["market"]["id"],
        window_start_date=_TOUCHING_WINDOW_START,
        window_end_date=_TOUCHING_WINDOW_END,
    )
    validate_error(response, ApiErrorId.ERR_DATA_WINDOW_OVERLAP.value, 409)

    rows, meta = _windows_of(api, ctx["market"]["id"])
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [incumbent["id"]]


def test_window_starting_the_day_after_an_incumbents_end_date_opens(api):
    """PRD §3.2: "The consequence is that two back-to-back windows whose endpoints
    merely touch do conflict: a window ending 2026-08-31 blocks a new window
    starting 2026-08-31, and the new window must start 2026-09-01 or later."

    2026-09-01 is the first admissible start, and the window it opens is a
    completely fresh one. PRD §3.2: "A new window opens in `OPEN` status with
    `sales_period_count`, `spend_observation_count` and `lag_completeness_pct` all
    at zero, `reopen_count` at 0 and `reopen_reason` null."

    Design: Difficulty/resource_temporal_overlap/data_window_closed_interval_touching_conflict_scoped_by_granularity
    """
    ctx = _market(api)
    incumbent = fx.create_data_window(api, ctx["market"]["id"])

    opened = validate_success(
        _window_response(
            api,
            ctx["market"]["id"],
            window_start_date=f.SECOND_WINDOW_START,
            window_end_date=f.SECOND_WINDOW_END,
        ),
        201,
    )
    expect.assert_data_window(opened)
    assert opened["status"] == "OPEN"
    assert opened["granularity"] == "WEEKLY"
    assert opened["expected_period_count"] == _WEEKLY_EXPECTED_PERIOD_COUNT
    assert opened["sales_period_count"] == 0
    assert opened["spend_observation_count"] == 0
    assert opened["lag_completeness_pct"] == 0.0
    assert opened["reopen_count"] == 0
    assert opened["reopen_reason"] is None

    rows, meta = _windows_of(api, ctx["market"]["id"])
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {incumbent["id"], opened["id"]}


def test_granularity_is_part_of_the_conflict_key_not_a_tie_break(api):
    """PRD §3.2: "Granularity is part of the conflict key rather than a tie-break,
    so two windows of the same market with different granularities may overlap as
    freely as the analyst likes — a weekly window and a daily window over the same
    quarter are both legitimate views of the same period."

    The daily twin covers the identical calendar range as the weekly incumbent and
    is admitted, while a second weekly window over that same range is refused, so
    granularity is the only thing separating the two attempts. PRD §3.2: "From that
    range and the granularity the system derives `expected_period_count` as the
    number of days between the two dates divided by seven when the granularity is
    `WEEKLY`, or by one when it is `DAILY`."

    Design: Difficulty/resource_temporal_overlap/data_window_closed_interval_touching_conflict_scoped_by_granularity
    """
    ctx = _market(api)
    weekly = fx.create_data_window(api, ctx["market"]["id"])
    assert weekly["expected_period_count"] == _WEEKLY_EXPECTED_PERIOD_COUNT

    daily = validate_success(
        _window_response(api, ctx["market"]["id"], granularity="DAILY"), 201
    )
    assert daily["granularity"] == "DAILY"
    assert daily["window_start_date"] == weekly["window_start_date"]
    assert daily["window_end_date"] == weekly["window_end_date"]
    assert daily["expected_period_count"] == _DAILY_EXPECTED_PERIOD_COUNT
    assert daily["status"] == "OPEN"

    clash = _window_response(api, ctx["market"]["id"])
    validate_error(clash, ApiErrorId.ERR_DATA_WINDOW_OVERLAP.value, 409)

    rows, meta = _windows_of(api, ctx["market"]["id"])
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {weekly["id"], daily["id"]}

    weekly_rows, weekly_meta = validate_paginated(
        api.list_data_windows(
            users.DATA_ENGINEER,
            {"market_id": ctx["market"]["id"], "granularity": "WEEKLY"},
        )
    )
    assert weekly_meta["total_count"] == 1
    assert expect.only(weekly_rows)["id"] == weekly["id"]


def test_period_placement_uses_the_half_open_range_the_conflict_test_widens(api):
    """PRD §3.2: "Note the deliberate asymmetry with the previous paragraph —
    period placement uses the half-open range, while window-versus-window conflict
    detection uses the closed range."

    One fixture shows both readings at once. 2026-08-31 is occupied for conflict
    purposes yet is not a period this window will accept, because PRD §3.2 says "A
    date outside the half-open range or off the grid is `ERR_PERIOD_NOT_ALIGNED`."
    2026-08-04 is inside the range but off the weekly grid and fails the same way,
    while 2026-08-24 is the last period the half-open range admits.

    Design: Difficulty/resource_temporal_overlap/data_window_closed_interval_touching_conflict_scoped_by_granularity
    """
    ctx = _market(api)
    window = fx.create_data_window(api, ctx["market"]["id"])

    # The exclusive end date: occupied for conflict detection, not a period here.
    at_end = api.create_sales_observation(
        f.sales_observation_payload(window["id"], _EXCLUSIVE_END_PERIOD, 5000, 25000000),
        users.DATA_ENGINEER,
    )
    validate_error(at_end, ApiErrorId.ERR_PERIOD_NOT_ALIGNED.value, 422)

    # Inside the half-open range, but not a whole multiple of seven days in.
    off_grid = api.create_sales_observation(
        f.sales_observation_payload(window["id"], _OFF_GRID_PERIOD, 5000, 25000000),
        users.DATA_ENGINEER,
    )
    validate_error(off_grid, ApiErrorId.ERR_PERIOD_NOT_ALIGNED.value, 422)

    accepted = validate_success(
        api.create_sales_observation(
            f.sales_observation_payload(
                window["id"], _LAST_LEGAL_PERIOD, 5000, 25000000
            ),
            users.DATA_ENGINEER,
        ),
        201,
    )
    assert accepted["data_window_id"] == window["id"]
    refreshed = validate_success(api.get_data_window(window["id"], users.DATA_ENGINEER))
    assert refreshed["sales_period_count"] == 1

    # And the closed reading still governs the sibling test on the same dates.
    clash = _window_response(
        api,
        ctx["market"]["id"],
        window_start_date=_TOUCHING_WINDOW_START,
        window_end_date=_TOUCHING_WINDOW_END,
    )
    validate_error(clash, ApiErrorId.ERR_DATA_WINDOW_OVERLAP.value, 409)
