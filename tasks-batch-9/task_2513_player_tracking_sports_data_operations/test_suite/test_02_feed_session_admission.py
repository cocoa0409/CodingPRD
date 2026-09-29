"""
Admission of a feed session: the venue's aggregate transport capacity, the
rights window it hangs off, and the order the refusals come out in.
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
    ERR_GAME_NOT_COLLECTING,
    ERR_LICENSEE_QUOTA_EXHAUSTED,
    ERR_RIGHTS_WINDOW_REVOKED,
    ERR_VENUE_TRANSPORT_CAPACITY_EXCEEDED,
)
from test_helpers.assertions import assert_unit_ledger, expected_charge_cents
from test_helpers.constants import (
    COLLECTION_LIVE,
    COLLECTION_SCHEDULED,
    SESSION_ACTIVE,
    TIER_SILVER,
    WINDOW_ACTIVE,
    WINDOW_REVOKED,
)
from test_helpers.test_users import OPS_HEADERS

COMMERCIAL_WINDOW = {"max_latency_ms": 400, "allowed_scopes": ["POSITIONAL", "EVENT"]}


# ---------------------------------------------------------------------------
# Aggregate venue transport capacity, on half-open intervals
# ---------------------------------------------------------------------------

def _capacity_world(api: ApiClient) -> fx.World:
    """A 100 mbps venue whose LIVE game already carries a 20 mbps session."""
    return fx.active_session_world(
        api,
        licensee_overrides={"licensee_class": "COMMERCIAL_LICENSEE", "granted_units": 20000},
        window_overrides=COMMERCIAL_WINDOW,
    )


def _session_response(api: ApiClient, world: fx.World, **overrides):
    return api.create_feed_session(
        fac.feed_session_payload(world.game_id, world.window_id, **overrides),
        world.licensee_headers,
    )


def test_overlapping_bandwidth_above_the_venue_pipe_is_refused(api, clock):
    """PRD §3.8: "At every instant inside the candidate's half-open occupation interval,
    the sum of `bandwidth_mbps` across all feed sessions in `ACTIVE` or `SUSPENDED`
    status that sit on games at the same venue, plus the candidate's own
    `bandwidth_mbps`, must not exceed that venue's `transport_capacity_mbps`."
    PRD §3.8: "An over-subscription is refused with
    `ERR_VENUE_TRANSPORT_CAPACITY_EXCEEDED`."

    20 mbps already held plus 85 more overlapping is 105 on a 100 mbps pipe.

    The two windows share [18:15, 18:30), so both sessions count toward the
    same aggregate and the venue's transport capacity is breached.

    Design: Difficulty/resource_temporal_overlap/feed_session_half_open_aggregate_venue_capacity
    """
    world = _capacity_world(api)
    assert world.session["reserved_units"] == 900

    validate_error(
        _session_response(
            api,
            world,
            bandwidth_mbps=85,
            window_start_utc="2026-08-01T18:15:00Z",
            window_end_utc="2026-08-01T18:45:00Z",
        ),
        ERR_VENUE_TRANSPORT_CAPACITY_EXCEEDED,
    )


def test_capacity_is_admitted_at_exactly_the_venue_pipe(api, clock):
    """PRD §3.8: "At every instant inside the candidate's half-open occupation interval,
    the sum of `bandwidth_mbps` across all feed sessions in `ACTIVE` or `SUSPENDED`
    status that sit on games at the same venue, plus the candidate's own
    `bandwidth_mbps`, must not exceed that venue's `transport_capacity_mbps`."
    PRD §3.1: "`transport_capacity_mbps` is the total egress bandwidth the venue can
    sustain across all concurrent feed sessions, and must be greater than zero; §3.8
    explains how candidate sessions are admitted against it."

    20 + 80 mbps reaches the 100 mbps capacity without exceeding it.

    Design: Difficulty/resource_temporal_overlap/feed_session_half_open_aggregate_venue_capacity
    """
    world = _capacity_world(api)

    second = get_success_data(
        _session_response(
            api,
            world,
            bandwidth_mbps=80,
            window_start_utc="2026-08-01T18:15:00Z",
            window_end_utc="2026-08-01T18:45:00Z",
        ),
        expected_status=201,
    )
    assert second["status"] == SESSION_ACTIVE
    assert second["reserved_units"] == 3600


def test_a_session_starting_when_another_ends_does_not_overlap(api, clock):
    """PRD §3.8: "Two sessions where one ends at exactly the instant the other starts are
    adjacent rather than overlapping and do not contend."
    PRD §3.8: "A suspended session still holds its slice of the pipe — suspension is a
    pause, not a release."

    The end instant of a session's window is exclusive, so 18:45 is free.

    A 90 mbps session over [18:45, 19:15) shares no instant with the 80 mbps
    session over [18:15, 18:45), so only its own bandwidth is aggregated.

    Design: Difficulty/resource_temporal_overlap/feed_session_half_open_aggregate_venue_capacity
    """
    world = _capacity_world(api)
    get_success_data(
        _session_response(
            api,
            world,
            bandwidth_mbps=80,
            window_start_utc="2026-08-01T18:15:00Z",
            window_end_utc="2026-08-01T18:45:00Z",
        ),
        expected_status=201,
    )

    third = get_success_data(
        _session_response(
            api,
            world,
            bandwidth_mbps=90,
            window_start_utc="2026-08-01T18:45:00Z",
            window_end_utc="2026-08-01T19:15:00Z",
        ),
        expected_status=201,
    )
    assert third["status"] == SESSION_ACTIVE
    assert third["reserved_units"] == 4050

    licensee = validate_success(api.get_licensee(world.licensee_id, OPS_HEADERS))
    assert_unit_ledger(licensee, available=11450, reserved=8550, consumed=0)

    sessions, meta = validate_paginated(
        api.list_feed_sessions(
            world.licensee_headers,
            params={"game_id": world.game_id, "status": SESSION_ACTIVE},
        )
    )
    assert meta["total_count"] == 3
    assert len(sessions) == 3


# ---------------------------------------------------------------------------
# State refusals outrank fiscal refusals
# ---------------------------------------------------------------------------

def _thin_quota_world(api: ApiClient) -> fx.World:
    """A SCHEDULED game plus a licensee holding only 10 of the 900 units needed."""
    world = fx.scheduled_game_world(api)
    world.licensee = fx.onboard_licensee(
        api,
        name="Thin Quota Ltd",
        licensee_class="DEVELOPER",
        granted_units=10,
    )
    world.window = fx.allocate_window(
        api, world.game_id, world.licensee["id"], **COMMERCIAL_WINDOW
    )
    return world


def test_a_scheduled_game_is_refused_before_the_quota_is_looked_at(api, clock):
    """PRD §2.10: "Checks are evaluated in the following fixed order, and the first
    violated check determines the response."
    PRD §2.10: "Live collection: the game's `collection_status` is `LIVE` — otherwise
    `ERR_GAME_NOT_COLLECTING`."

    One request breaks both rules; the collection-state refusal is returned.

    Design: Difficulty/priority_pair_validation_conflict/state_precedes_fiscal_on_feed_session_open
    """
    world = _thin_quota_world(api)
    assert world.game["collection_status"] == COLLECTION_SCHEDULED

    validate_error(
        _session_response(api, world), ERR_GAME_NOT_COLLECTING
    )


def test_removing_the_state_violation_exposes_the_quota_refusal(api, clock):
    """PRD §3.8: "The reservation must fit the licensee's remaining quota: `reserved_units`
    must be less than or equal to the licensee's `available_units`, equality allowed, or
    the session is refused with `ERR_LICENSEE_QUOTA_EXHAUSTED` at HTTP 402."
    PRD §2.10: "Licensee quota: the reservation the session needs is at most the
    licensee's `available_units`, equality allowed — otherwise
    `ERR_LICENSEE_QUOTA_EXHAUSTED` (HTTP 402)."

    Opening collection changes nothing fiscal, so the same payload now fails on units.

    Design: Difficulty/priority_pair_validation_conflict/state_precedes_fiscal_on_feed_session_open
    """
    world = _thin_quota_world(api)
    validate_error(_session_response(api, world), ERR_GAME_NOT_COLLECTING)

    opened = validate_success(api.open_collection(world.game_id, OPS_HEADERS))
    assert opened["collection_status"] == COLLECTION_LIVE

    validate_error(
        _session_response(api, world), ERR_LICENSEE_QUOTA_EXHAUSTED
    )


def test_neither_refusal_leaves_a_session_or_moves_the_ledger(api, clock):
    """PRD §3.8: "On success the licensee's `available_units` falls by `reserved_units` and
    its `reserved_units` rises by the same amount — the total of granted units never
    moves, only its distribution — and the rights window's `active_feed_session_count`
    rises by one."
    PRD §3.8: "The session is created in `ACTIVE` status with `halt_reason` null,
    `metered_units`, `settled_charge_cents`, `refunded_units`, `usage_record_count` and
    `sla_breach_count` all at zero."

    Two rejected admissions mint nothing and reserve nothing.

    Design: Difficulty/priority_pair_validation_conflict/state_precedes_fiscal_on_feed_session_open
    """
    world = _thin_quota_world(api)
    validate_error(_session_response(api, world), ERR_GAME_NOT_COLLECTING)
    validate_success(api.open_collection(world.game_id, OPS_HEADERS))
    validate_error(_session_response(api, world), ERR_LICENSEE_QUOTA_EXHAUSTED)

    licensee = validate_success(api.get_licensee(world.licensee["id"], OPS_HEADERS))
    assert_unit_ledger(licensee, available=10, reserved=0, consumed=0)

    _, meta = validate_paginated(
        api.list_feed_sessions(OPS_HEADERS, params={"game_id": world.game_id})
    )
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# A session depends on its window still being ACTIVE
# ---------------------------------------------------------------------------

def _two_window_world(api: ApiClient) -> fx.World:
    """A LIVE game with a revoked US window and an ACTIVE Canadian one.

    The two windows cover the same three hours; because their territories
    differ they do not collide, so both can exist on the same game.
    """
    world = fx.live_game_world(api)
    world.licensee = fx.onboard_licensee(
        api, name="Meridian Sports Media", tier=TIER_SILVER
    )
    revoked = fx.allocate_window(
        api, world.game_id, world.licensee["id"], territory="US", **COMMERCIAL_WINDOW
    )
    validate_success(api.revoke_rights_window(revoked["id"], OPS_HEADERS))
    world.window = fx.allocate_window(
        api, world.game_id, world.licensee["id"], territory="CA", **COMMERCIAL_WINDOW
    )
    world.extra["revoked_window_id"] = revoked["id"]
    return world


def test_a_session_under_a_revoked_window_is_refused(api, clock):
    """PRD §2.10: "Rights-window lifecycle: the window's `status` is `ACTIVE` — otherwise
    `ERR_RIGHTS_WINDOW_REVOKED`."
    PRD §2.10: "Applies to opening a feed session and to revoking a window."

    A REVOKED window cannot carry a new session even while the game is LIVE.

    Design: Difficulty/cross_entity_state_dependency/feed_session_requires_active_rights_window
    """
    world = _two_window_world(api)
    revoked_id = world.extra["revoked_window_id"]

    windows, _ = validate_paginated(api.list_rights_windows(world.game_id, OPS_HEADERS))
    revoked = next(row for row in windows if row["id"] == revoked_id)
    assert revoked["status"] == WINDOW_REVOKED
    assert revoked["revoked_at_utc"] == "2026-08-01T12:00:00Z"
    assert revoked["active_feed_session_count"] == 0

    validate_error(
        api.create_feed_session(
            fac.feed_session_payload(world.game_id, revoked_id),
            world.licensee_headers,
        ),
        ERR_RIGHTS_WINDOW_REVOKED,
    )


def test_the_same_payload_is_admitted_under_the_active_window(api, clock):
    """PRD §3.8: "It fixes the unit price: a `BRONZE` licence is billed at 40 cents per
    unit, a `SILVER` licence at 30 cents, and a `GOLD` licence at 22 cents — volume buys
    a discount."
    PRD §3.8: "Under the reserved-forward variant the session is priced as if the entire
    booked window were fully consumed: `reserved_units` is the product of
    `bandwidth_mbps`, `duration_minutes` and `latency_multiplier`, rounded up to a whole
    unit with a single ceiling over the whole window, and `reserved_charge_cents` is
    that unit count multiplied by the licensee's per-unit tier rate and rounded half up
    to whole cents."

    Only the window changes, and the session opens at the SILVER rate.

    Design: Difficulty/cross_entity_state_dependency/feed_session_requires_active_rights_window
    """
    world = _two_window_world(api)

    session = get_success_data(
        api.create_feed_session(
            fac.feed_session_payload(world.game_id, world.window_id),
            world.licensee_headers,
        ),
        expected_status=201,
    )
    assert session["status"] == SESSION_ACTIVE
    assert session["rights_window_id"] == world.window_id
    assert session["reserved_units"] == 900
    assert session["reserved_charge_cents"] == 27000
    assert session["reserved_charge_cents"] == expected_charge_cents(900, TIER_SILVER)

    windows, _ = validate_paginated(api.list_rights_windows(world.game_id, OPS_HEADERS))
    active = next(row for row in windows if row["id"] == world.window_id)
    assert active["status"] == WINDOW_ACTIVE
    assert active["active_feed_session_count"] == 1

    licensee = validate_success(api.get_licensee(world.licensee_id, OPS_HEADERS))
    assert_unit_ledger(licensee, available=4100, reserved=900, consumed=0)


def test_the_revoked_windows_minutes_were_returned_before_the_second_drew(api, clock):
    """PRD §3.7: "Finally the window's minutes return to the pool they came from: for a
    window of any non-archive class the game's `allocated_minutes_total` falls by that
    window's `allocated_minutes` and `remaining_allocatable_minutes` rises by the same
    amount, while for a `LEAGUE_ARCHIVE` window the game's
    `league_reserve_allocated_minutes` falls by that amount, freeing the same number of
    minutes inside the reserve pool."
    PRD §3.7: "Revoked windows contribute nothing to either total."

    The pool sees only one live draw of 180 minutes, not two.

    Design: Difficulty/cross_entity_state_dependency/feed_session_requires_active_rights_window
    """
    world = _two_window_world(api)

    game = validate_success(api.get_game(world.game_id, OPS_HEADERS))
    assert game["allocated_minutes_total"] == 180
    assert game["remaining_allocatable_minutes"] == 24
