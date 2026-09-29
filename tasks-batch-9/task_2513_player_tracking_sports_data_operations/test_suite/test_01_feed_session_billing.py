"""
Feed-session pricing: the reserved-forward variant at admission and the
metered-actual variant at settlement, plus the unit ledger that both move.
"""

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as fac
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_unit_ledger,
    expected_charge_cents,
    expected_record_units,
    expected_reserved_units,
)
from test_helpers.constants import (
    HALT_CLIENT_REQUEST,
    MULTIPLIER_PREMIUM,
    SESSION_TERMINATED,
    TIER_GOLD,
    WINDOW_REVOKED,
)
from test_helpers.test_users import OPS_HEADERS

WINDOW_OVERRIDES = {"max_latency_ms": 400, "allowed_scopes": ["POSITIONAL", "EVENT"]}
LICENSEE_OVERRIDES = {"licensee_class": "COMMERCIAL_LICENSEE"}

# The three samples the session reports, in the order they are reported.
USAGE_SAMPLES = [
    {"sampled_at_utc": "2026-08-01T18:05:00Z", "bandwidth_mbps": 20, "duration_seconds": 600, "latency_p95_ms": 300},
    {"sampled_at_utc": "2026-08-01T18:15:00Z", "bandwidth_mbps": 20, "duration_seconds": 400, "latency_p95_ms": 320},
    {"sampled_at_utc": "2026-08-01T18:25:00Z", "bandwidth_mbps": 18, "duration_seconds": 200, "latency_p95_ms": 280},
]

SINGLE_SAMPLE = {
    "sampled_at_utc": "2026-08-01T18:05:00Z",
    "bandwidth_mbps": 20,
    "duration_seconds": 600,
    "latency_p95_ms": 300,
}


def _billing_world(api: ApiClient) -> fx.World:
    """A LIVE game with a GOLD licensee holding one 20 mbps half-hour session."""
    return fx.active_session_world(
        api,
        licensee_overrides=LICENSEE_OVERRIDES,
        window_overrides=WINDOW_OVERRIDES,
    )


def _report_sample(api: ApiClient, world: fx.World, sample: dict) -> dict:
    return get_success_data(
        api.create_usage_record(
            world.session_id, fac.usage_record_payload(**sample), world.licensee_headers
        ),
        expected_status=201,
    )


def _report_all_samples(api: ApiClient, world: fx.World) -> list:
    return [_report_sample(api, world, sample)["units_charged"] for sample in USAGE_SAMPLES]


def test_reserved_forward_ceils_once_over_the_whole_booked_window(api, clock):
    """PRD §3.8: "Under the reserved-forward variant the session is priced as if the entire
    booked window were fully consumed: `reserved_units` is the product of
    `bandwidth_mbps`, `duration_minutes` and `latency_multiplier`, rounded up to a whole
    unit with a single ceiling over the whole window, and `reserved_charge_cents` is
    that unit count multiplied by the licensee's per-unit tier rate and rounded half up
    to whole cents."
    PRD §3.8: "`latency_multiplier` is a premium selected from the latency the session
    asked for: a `requested_latency_ms` of at most 250 milliseconds — a quarter of a
    second — carries a multiplier of 1.50; anything above that but at most 1,000
    milliseconds, a full second, carries 1.20; anything slower carries 1.00."
    PRD §3.8: "It fixes the unit price: a `BRONZE` licence is billed at 40 cents per
    unit, a `SILVER` licence at 30 cents, and a `GOLD` licence at 22 cents — volume buys
    a discount."

    A 20 mbps half-hour booking at 250 ms reserves 900 units up front.

    duration_minutes is the exact unrounded 30, the latency premium is 1.50 and
    the single ceiling over the whole window gives 900 units at 22 cents each.

    Design: Difficulty/dual_variant_calc/feed_session_reserved_forward_versus_metered_actual_settlement
    """
    world = _billing_world(api)
    session = world.session

    assert float(session["latency_multiplier"]) == pytest.approx(MULTIPLIER_PREMIUM)
    assert float(session["duration_minutes"]) == pytest.approx(30.0)
    assert session["reserved_units"] == 900
    assert session["reserved_units"] == expected_reserved_units(20, 1800, 250)
    assert session["reserved_charge_cents"] == 19800
    assert session["reserved_charge_cents"] == expected_charge_cents(900, TIER_GOLD)
    assert session["metered_units"] == 0
    assert session["settled_charge_cents"] == 0
    assert session["refunded_units"] == 0

    assert_unit_ledger(world.licensee, available=4100, reserved=900, consumed=0)


def test_metered_actual_ceils_each_record_and_refunds_the_difference(api, clock):
    """PRD §3.8: "The record's `units_charged` is the product of its `bandwidth_mbps`, its
    `duration_seconds` divided by sixty, and the parent session's `latency_multiplier`,
    rounded up to a whole unit — the ceiling is applied to this record alone."
    PRD §3.8: "The session's usage records are replayed in ascending `sampled_at_utc`
    order with `created_at` ascending as the tie-break; each record's charge is the
    per-record ceiling described above; `metered_units` is the sum of those per-record
    charges; and `settled_charge_cents` is `metered_units` multiplied by the tier rate
    and rounded half up to whole cents."
    PRD §3.8: "`refunded_units` is the session's `reserved_units` less its metered units
    rounded up to a whole unit."

    Settlement prices only what was reported, one ceiling per record.

    600 s, 400 s and 200 s of reported traffic charge 300 + 200 + 90 = 590
    units against a 900-unit reservation, so 310 units come back.

    Design: Difficulty/dual_variant_calc/feed_session_reserved_forward_versus_metered_actual_settlement
    """
    world = _billing_world(api)
    charged = _report_all_samples(api, world)

    assert charged == [300, 200, 90]
    assert charged[0] == expected_record_units(20, 600, MULTIPLIER_PREMIUM)
    assert charged[2] == expected_record_units(18, 200, MULTIPLIER_PREMIUM)

    settled = validate_success(
        api.terminate_feed_session(world.session_id, world.licensee_headers)
    )
    assert settled["status"] == SESSION_TERMINATED
    assert settled["halt_reason"] == HALT_CLIENT_REQUEST
    assert settled["metered_units"] == 590
    assert settled["settled_charge_cents"] == 12980
    assert settled["settled_charge_cents"] == expected_charge_cents(590, TIER_GOLD)
    assert settled["refunded_units"] == 310
    assert settled["reserved_units"] == 900


def test_settlement_moves_the_licensee_ledger_and_frees_the_window(api, clock):
    """PRD §3.8: "Settlement then moves the licensee's ledger in four coordinated steps:
    `reserved_units` falls by the session's `reserved_units`, `consumed_units` rises by
    the session's metered units rounded up to a whole unit, `available_units` rises by
    the session's `refunded_units`, and the licensee's `settled_charge_cents` rises by
    the session's `settled_charge_cents`."
    PRD §3.8: "The session moves to `TERMINATED` with `halt_reason` overwritten to
    `CLIENT_REQUEST` — overwritten even when the session was suspended for some other
    reason — and the rights window's `active_feed_session_count` falls by one."

    The two variants meet on the licensee: 590 consumed, 310 released.

    Design: Difficulty/dual_variant_calc/feed_session_reserved_forward_versus_metered_actual_settlement
    """
    world = _billing_world(api)
    _report_all_samples(api, world)
    validate_success(
        api.terminate_feed_session(world.session_id, world.licensee_headers)
    )

    licensee = validate_success(api.get_licensee(world.licensee_id, OPS_HEADERS))
    assert_unit_ledger(licensee, available=4410, reserved=0, consumed=590)
    assert licensee["settled_charge_cents"] == 12980

    windows, _ = validate_paginated(
        api.list_rights_windows(world.game_id, OPS_HEADERS)
    )
    window = next(row for row in windows if row["id"] == world.window_id)
    assert window["active_feed_session_count"] == 0


# ---------------------------------------------------------------------------
# The unit ledger as a conserved quantity
# ---------------------------------------------------------------------------

def _revoke_world(api: ApiClient) -> fx.World:
    """One session with a single 300-unit usage record, ready to be revoked."""
    world = _billing_world(api)
    _report_sample(api, world, SINGLE_SAMPLE)
    return world


def test_unit_ledger_balances_while_the_session_is_open(api, clock):
    """PRD §2.11: "A licensee's `available_units`, `reserved_units` and `consumed_units`
    sum to exactly its `granted_units` at all times."
    PRD §3.8: "On success the licensee's `available_units` falls by `reserved_units` and
    its `reserved_units` rises by the same amount — the total of granted units never
    moves, only its distribution — and the rights window's `active_feed_session_count`
    rises by one."

    5000 granted units sit as 4100 available + 900 reserved + 0 consumed.

    Design: Difficulty/compensating_invariant/licensee_unit_ledger_conserved_through_revoke_settlement
    """
    world = _revoke_world(api)

    licensee = validate_success(api.get_licensee(world.licensee_id, OPS_HEADERS))
    assert licensee["granted_units"] == 5000
    assert_unit_ledger(licensee, available=4100, reserved=900, consumed=0)

    records, meta = validate_paginated(
        api.list_usage_records(world.session_id, world.licensee_headers)
    )
    assert meta["total_count"] == 1
    assert records[0]["units_charged"] == 300


def test_revoking_the_window_settles_the_session_and_conserves_the_grant(api, clock):
    """PRD §3.7: "The first link reaches every feed session held under the window whose
    `status` is `ACTIVE` or `SUSPENDED`: each is settled against its reported usage
    exactly as a voluntary termination would settle it, and moved to `TERMINATED` with
    `halt_reason` of `CLIENT_REQUEST`."
    PRD §3.7: "The second link, caused by the first, settles each affected licensee's
    ledger: that licensee's `reserved_units` falls by the session's `reserved_units`,
    its `consumed_units` rises by the session's metered units, its `available_units`
    rises by the session's `refunded_units`, and its `settled_charge_cents` rises by the
    session's `settled_charge_cents`."

    Revocation compensates exactly the 600 unconsumed units and no more.

    Design: Difficulty/compensating_invariant/licensee_unit_ledger_conserved_through_revoke_settlement
    """
    world = _revoke_world(api)

    revoked = validate_success(api.revoke_rights_window(world.window_id, OPS_HEADERS))
    assert revoked["status"] == WINDOW_REVOKED

    session = validate_success(api.get_feed_session(world.session_id, OPS_HEADERS))
    assert session["status"] == SESSION_TERMINATED
    assert session["halt_reason"] == HALT_CLIENT_REQUEST
    assert session["metered_units"] == 300
    assert session["settled_charge_cents"] == 6600
    assert session["refunded_units"] == 600

    licensee = validate_success(api.get_licensee(world.licensee_id, OPS_HEADERS))
    assert_unit_ledger(licensee, available=4700, reserved=0, consumed=300)
    assert licensee["settled_charge_cents"] == 6600
    assert licensee["granted_units"] == 5000


def test_revocation_returns_the_windows_minutes_to_the_net_pool(api, clock):
    """PRD §3.7: "Finally the window's minutes return to the pool they came from: for a
    window of any non-archive class the game's `allocated_minutes_total` falls by that
    window's `allocated_minutes` and `remaining_allocatable_minutes` rises by the same
    amount, while for a `LEAGUE_ARCHIVE` window the game's
    `league_reserve_allocated_minutes` falls by that amount, freeing the same number of
    minutes inside the reserve pool."
    PRD §3.7: "Revoked windows contribute nothing to either total."

    The 180 minutes the revoked window drew go back to the game's pool.

    Design: Difficulty/compensating_invariant/licensee_unit_ledger_conserved_through_revoke_settlement
    """
    world = _revoke_world(api)
    validate_success(api.revoke_rights_window(world.window_id, OPS_HEADERS))

    game = validate_success(api.get_game(world.game_id, OPS_HEADERS))
    assert game["allocated_minutes_total"] == 0
    assert game["remaining_allocatable_minutes"] == 204
    assert game["net_allocatable_minutes"] == 204
