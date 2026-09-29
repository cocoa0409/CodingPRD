"""
The minute ledger on a game: where the league reserve comes from, and how a
broadcast window's five-minute buffer decides collisions.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as fac
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_ALLOCATION_POOL_EXHAUSTED,
    ERR_RIGHTS_WINDOW_OVERLAP,
)
from test_helpers.assertions import (
    assert_minute_ledger,
    expected_allocated_minutes,
    expected_league_reserve_minutes,
)
from test_helpers.constants import (
    HOLDER_LEAGUE,
    RIGHTS_CLASS_BROADCAST_LIVE,
    RIGHTS_CLASS_LEAGUE_ARCHIVE,
    TERRITORY_GLOBAL,
    WINDOW_ACTIVE,
)
from test_helpers.test_users import OPS_HEADERS

BROADCAST_US = {
    "rights_class": RIGHTS_CLASS_BROADCAST_LIVE,
    "holder_type": HOLDER_LEAGUE,
    "territory": "US",
    "max_latency_ms": 400,
    "allowed_scopes": ["POSITIONAL", "EVENT"],
}


def _unrigged_game(api: ApiClient) -> fx.World:
    """A SCHEDULED game at a venue with no rigs; allocation ignores posture."""
    world = fx.World()
    world.venue = fx.register_venue(api)
    clubs = fx.register_clubs(api)
    world.home_club = clubs["home"]
    world.away_club = clubs["away"]
    world.game = get_success_data(
        api.create_game(
            fac.game_payload(
                world.venue["id"], world.home_club["id"], world.away_club["id"]
            ),
            OPS_HEADERS,
        )
    )
    return world


def _window(api: ApiClient, game_id: str, **overrides):
    return api.create_rights_window(
        game_id, fac.rights_window_payload(None, **overrides), OPS_HEADERS
    )


def _full_pool_window(api: ApiClient, game_id: str) -> dict:
    """A broadcast window covering 18:00 to 21:24, exactly the 204-minute pool."""
    return get_success_data(
        _window(
            api,
            game_id,
            window_start_utc="2026-08-01T18:00:00Z",
            window_end_utc="2026-08-01T21:24:00Z",
            **BROADCAST_US,
        ),
        expected_status=201,
    )


# ---------------------------------------------------------------------------
# The reserve is taken off the gross figure
# ---------------------------------------------------------------------------

def test_the_reserve_is_fifteen_percent_of_the_gross_licensable_minutes(api, clock):
    """PRD §3.7: "Step one, on the gross basis: the league's archival reserve,
    `league_reserve_minutes`, is fifteen percent of the game's `licensable_minutes`,
    rounded up to a whole minute."
    PRD §3.7: "The reserve is always a share of the *gross* licensable figure, never of
    the net pool it creates."
    PRD §3.7: "Step two: `net_allocatable_minutes` is `licensable_minutes` less
    `league_reserve_minutes`."

    240 gross minutes yield a 36-minute reserve and a 204-minute net pool.

    Taking the fraction off the net pool instead would leave 209 net minutes,
    so the split pins the evaluation order.

    Design: Difficulty/combinatorial_formula/league_reserve_computed_on_gross_licensable_minutes_not_net_pool
    """
    world = _unrigged_game(api)

    game = validate_success(api.get_game(world.game_id, OPS_HEADERS))
    assert game["licensable_minutes"] == 240
    assert game["league_reserve_minutes"] == 36
    assert game["league_reserve_minutes"] == expected_league_reserve_minutes(240)
    assert game["net_allocatable_minutes"] == 204
    assert_minute_ledger(
        game,
        league_reserve_minutes=36,
        net_allocatable_minutes=204,
        allocated_minutes_total=0,
        remaining_allocatable_minutes=204,
    )


def test_a_single_window_can_draw_the_whole_net_pool(api, clock):
    """PRD §3.7: "Each window's own draw, `allocated_minutes`, is the number of seconds
    between its `window_start_utc` and `window_end_utc` divided by sixty and rounded up
    to a whole minute; the rounding up happens once per window and is never applied to a
    sum of windows."
    PRD §3.7: "A `LEAGUE_ARCHIVE` candidate is admitted when its `allocated_minutes` is
    less than or equal to `league_reserve_minutes` less
    `league_reserve_allocated_minutes`; a candidate of any other class is admitted when
    its `allocated_minutes` is less than or equal to `remaining_allocatable_minutes`."
    PRD §3.7: "Equality is admitted in both cases — a window that exactly exhausts its
    pool is legal."

    A 204-minute broadcast window exhausts the net pool exactly.

    Design: Difficulty/combinatorial_formula/league_reserve_computed_on_gross_licensable_minutes_not_net_pool
    """
    world = _unrigged_game(api)

    window = _full_pool_window(api, world.game_id)
    assert window["allocated_minutes"] == 204
    assert window["allocated_minutes"] == expected_allocated_minutes(204 * 60)

    game = validate_success(api.get_game(world.game_id, OPS_HEADERS))
    assert_minute_ledger(
        game,
        league_reserve_minutes=36,
        net_allocatable_minutes=204,
        allocated_minutes_total=204,
        remaining_allocatable_minutes=0,
    )


def test_one_further_minute_of_non_archive_rights_does_not_fit(api, clock):
    """PRD §3.7: "A candidate that does not fit is refused with
    `ERR_ALLOCATION_POOL_EXHAUSTED`, and the practical consequence is that the archival
    reserve can never be cannibalised by a broadcaster and a broadcaster can never be
    squeezed out by the archive."
    PRD §3.7: "A `LEAGUE_ARCHIVE` candidate is admitted when its `allocated_minutes` is
    less than or equal to `league_reserve_minutes` less
    `league_reserve_allocated_minutes`; a candidate of any other class is admitted when
    its `allocated_minutes` is less than or equal to `remaining_allocatable_minutes`."

    The reserve is not available to a broadcast window, so 205 is too many.

    Design: Difficulty/combinatorial_formula/league_reserve_computed_on_gross_licensable_minutes_not_net_pool
    """
    world = _unrigged_game(api)
    _full_pool_window(api, world.game_id)

    validate_error(
        _window(
            api,
            world.game_id,
            window_start_utc="2026-08-01T22:00:00Z",
            window_end_utc="2026-08-01T22:01:00Z",
            rights_class=RIGHTS_CLASS_BROADCAST_LIVE,
            holder_type=HOLDER_LEAGUE,
            territory="US",
            max_latency_ms=400,
            allowed_scopes=["POSITIONAL"],
        ),
        ERR_ALLOCATION_POOL_EXHAUSTED,
    )


def test_an_archive_window_draws_the_disjoint_reserve_pool(api, clock):
    """PRD §3.7: "Step three establishes two disjoint pools, each drawn down in window
    creation order from oldest to newest: the reserve pool is drawn only by windows
    whose `rights_class` is `LEAGUE_ARCHIVE`, and the net pool is drawn by windows of
    all three other classes."
    PRD §3.7: "`league_reserve_allocated_minutes` is the total of `allocated_minutes`
    across the game's active `LEAGUE_ARCHIVE` windows, `allocated_minutes_total` is the
    total across the game's active windows of every other class, and
    `remaining_allocatable_minutes` is `net_allocatable_minutes` less
    `allocated_minutes_total`."

    36 archive minutes fit even with the net pool at zero.

    Archive minutes never enter allocated_minutes_total, and the reserve draw
    leaves the net pool's remaining figure untouched.

    Design: Difficulty/combinatorial_formula/league_reserve_computed_on_gross_licensable_minutes_not_net_pool
    """
    world = _unrigged_game(api)
    _full_pool_window(api, world.game_id)

    archive = get_success_data(
        _window(
            api,
            world.game_id,
            rights_class=RIGHTS_CLASS_LEAGUE_ARCHIVE,
            holder_type=HOLDER_LEAGUE,
            territory=TERRITORY_GLOBAL,
            window_start_utc="2026-08-01T18:00:00Z",
            window_end_utc="2026-08-01T18:36:00Z",
            max_latency_ms=5000,
            allowed_scopes=["POSITIONAL", "EVENT"],
        ),
        expected_status=201,
    )
    assert archive["allocated_minutes"] == 36

    game = validate_success(api.get_game(world.game_id, OPS_HEADERS))
    assert_minute_ledger(
        game,
        league_reserve_minutes=36,
        net_allocatable_minutes=204,
        allocated_minutes_total=204,
        remaining_allocatable_minutes=0,
        league_reserve_allocated_minutes=36,
    )


# ---------------------------------------------------------------------------
# Closed intervals, expanded by the broadcast buffer
# ---------------------------------------------------------------------------

def _buffered_base_world(api: ApiClient) -> fx.World:
    """A game carrying one 18:00-21:00 US broadcast window worth 180 minutes."""
    world = _unrigged_game(api)
    world.window = get_success_data(
        _window(
            api,
            world.game_id,
            window_start_utc="2026-08-01T18:00:00Z",
            window_end_utc="2026-08-01T21:00:00Z",
            **BROADCAST_US,
        ),
        expected_status=201,
    )
    assert world.window["allocated_minutes"] == 180
    return world


def _candidate(api: ApiClient, game_id: str, start: str, end: str):
    return _window(
        api,
        game_id,
        window_start_utc=start,
        window_end_utc=end,
        rights_class=RIGHTS_CLASS_BROADCAST_LIVE,
        holder_type=HOLDER_LEAGUE,
        territory="US",
        max_latency_ms=400,
        allowed_scopes=["POSITIONAL"],
    )


def test_broadcast_windows_whose_buffers_touch_collide(api, clock):
    """PRD §3.7: "Intervals are **closed** on both ends, so two windows that merely touch —
    one ending at exactly the instant the next begins — do collide."
    PRD §3.7: "For `BROADCAST_LIVE` windows a further safety margin applies: both the
    candidate interval and each existing interval are first expanded by 300 seconds,
    five minutes, on each side before intersection is tested, so consecutive live
    broadcast windows must be separated by more than ten minutes of real distance."
    PRD §3.7: "A collision is refused with `ERR_RIGHTS_WINDOW_OVERLAP`."

    21:10:00 is refused: the buffered intervals meet at 21:05:00 exactly.

    Each interval is widened by five minutes on both sides, leaving
    18:00-21:00 as 17:55:00-21:05:00 and 21:10:00-21:34:00 as
    21:05:00-21:39:00, and contact at a single instant is a collision.

    Design: Difficulty/resource_temporal_overlap/rights_window_closed_interval_with_broadcast_buffer
    """
    world = _buffered_base_world(api)

    game = validate_success(api.get_game(world.game_id, OPS_HEADERS))
    assert game["remaining_allocatable_minutes"] == 24

    validate_error(
        _candidate(api, world.game_id, "2026-08-01T21:10:00Z", "2026-08-01T21:34:00Z"),
        ERR_RIGHTS_WINDOW_OVERLAP,
    )


def test_one_second_of_clearance_is_enough_for_the_second_window(api, clock):
    """PRD §3.7: "Exclusivity is the commercial promise behind a rights window, and it is
    enforced on three axes at once: the same game, the same `rights_class`, and a
    colliding `territory`."
    PRD §3.7: "For `BROADCAST_LIVE` windows a further safety margin applies: both the
    candidate interval and each existing interval are first expanded by 300 seconds,
    five minutes, on each side before intersection is tested, so consecutive live
    broadcast windows must be separated by more than ten minutes of real distance."

    21:10:01 is admitted and takes the last 24 minutes of the pool.

    Design: Difficulty/resource_temporal_overlap/rights_window_closed_interval_with_broadcast_buffer
    """
    world = _buffered_base_world(api)

    admitted = get_success_data(
        _candidate(api, world.game_id, "2026-08-01T21:10:01Z", "2026-08-01T21:34:01Z"),
        expected_status=201,
    )
    assert admitted["status"] == WINDOW_ACTIVE
    assert admitted["allocated_minutes"] == 24

    game = validate_success(api.get_game(world.game_id, OPS_HEADERS))
    assert_minute_ledger(
        game,
        league_reserve_minutes=36,
        net_allocatable_minutes=204,
        allocated_minutes_total=204,
        remaining_allocatable_minutes=0,
    )

    _, meta = validate_paginated(
        api.list_rights_windows(
            world.game_id, OPS_HEADERS, params={"status": WINDOW_ACTIVE}
        )
    )
    assert meta["total_count"] == 2
