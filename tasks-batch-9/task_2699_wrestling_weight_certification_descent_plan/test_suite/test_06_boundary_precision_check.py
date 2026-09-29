"""
Boundary precision on the weigh-in verdict and on the seeding pool.

Two families of edge live here, both taken from the requirements document.

The first is the numeric one: the weigh-in verdict compares a one-decimal
recorded weight against a one-decimal ``effective_limit_lbs``, and §2.6 states
that landing exactly on a limit is permitted.  §3.8 fixes the limit as the
entry's ``weight_class_lbs`` plus the growth-allowance component plus the capped
consecutive-day component, so the limit itself moves from one weigh-in day to
the next and the boundary has to be re-derived per day rather than assumed.

The second is a cardinality one: §3.8 admits exactly the entries in
``WEIGHED_IN`` to an initial seeding run, refuses the run outright when that
pool is globally empty, and otherwise gives each occupied class a contiguous run
of seed numbers beginning at 1 — so the conserved ``seed_integrity_sum`` of
§2.9 sits at 0 on the empty side of the edge and at 1 for a single seeded
entry.
"""

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import api_errors, factories, fixtures
from test_helpers.assertions import (
    assert_weight_equals,
    expected_consecutive_day_allowance,
    expected_seed_integrity_sum,
    expected_weigh_in_result,
    round_weight,
)
from test_helpers.constants import (
    CANON_MINIMUM_CERTIFIED_WEIGHT_LBS,
    CANON_TARGET_CLASS_LBS,
    DEFAULT_MAX_CONSECUTIVE_DAY_ALLOWANCE_LBS,
    ENTRY_ENTERED,
    ENTRY_SCRATCHED,
    ENTRY_SEEDED,
    ENTRY_WEIGHED_IN,
    EVENT_SEEDED,
    EVENT_TYPE_DUAL,
    EVENT_TYPE_TOURNAMENT,
    EVENT_WEIGH_IN_CLOSED,
    SCRATCH_REASON_NO_WEIGH_IN,
    WEIGH_IN_FAIL,
    WEIGH_IN_PASS,
    WEIGH_IN_PASS_WITH_ALLOWANCE,
)
from test_helpers.test_users import STATE_OFFICE, WEIGH_IN_OFFICIAL

# ── The regulatory figures both families are built on ────────────────
#
# Two published growth-allowance dates, cumulative and inclusive of their own
# effective date (§3.1), so the growth total is 4.0 pounds for any date on or
# after the later of the two.
_GROWTH_EARLY_DATE = "2026-12-01"
_GROWTH_EARLY_LBS = 1.0
_GROWTH_LATE_DATE = "2026-12-12"
_GROWTH_LATE_LBS = 3.0
_GROWTH_TOTAL_LBS = 4.0

# The per-additional-day allowance the multi-day event declares, well under the
# season ceiling of 2.0 pounds so that the cap is not what decides the figure.
_PER_DAY_ALLOWANCE_LBS = 1.0

# The two-day event whose weigh-in limit moves between day 0 and day 1.
_DUALS_NAME = "Region Duals"
_DUALS_DATE = "2026-12-12"
_DUALS_DAY0_INSTANT = "2026-12-12T08:00:00Z"
_DUALS_DAY1_INSTANT = "2026-12-13T08:00:00Z"

# The two single-day events with adjacent, non-overlapping competition windows:
# [2026-12-14, 2026-12-15) and [2026-12-15, 2026-12-16).
_EMPTY_EVENT_NAME = "Holiday Open"
_EMPTY_EVENT_DATE = "2026-12-14"
_SEEDED_EVENT_NAME = "Winter Classic"
_SEEDED_EVENT_DATE = "2026-12-15"
_SEEDED_EVENT_INSTANT = "2026-12-15T08:00:00Z"

_SEASON_WIN_COUNT = 6


def _expected_allowance_lbs(day_index: int) -> float:
    """The stored ``allowance_lbs`` for a weigh-in day at the shared event.

    §3.8: the growth-allowance component plus the consecutive-day component,
    the latter rounded to one place and then capped at the season's
    ``max_consecutive_day_allowance_lbs``, and the sum rounded to one place.
    """
    consecutive = expected_consecutive_day_allowance(
        day_index, _PER_DAY_ALLOWANCE_LBS, DEFAULT_MAX_CONSECUTIVE_DAY_ALLOWANCE_LBS
    )
    return round_weight(_GROWTH_TOTAL_LBS + consecutive)


def _expected_effective_limit_lbs(weight_class_lbs: int, day_index: int) -> float:
    """The entry's class limit plus that day's allowance, to one decimal place."""
    return round_weight(weight_class_lbs + _expected_allowance_lbs(day_index))


def _publish_december_allowances(api, season_id: str) -> None:
    """Publish the two growth-allowance dates that total 4.0 pounds."""
    fixtures.publish_growth_allowance(
        api, season_id, _GROWTH_EARLY_DATE, _GROWTH_EARLY_LBS, "December growth allowance"
    )
    fixtures.publish_growth_allowance(
        api, season_id, _GROWTH_LATE_DATE, _GROWTH_LATE_LBS, "Mid-season growth allowance"
    )


def _record_weigh_in(api, event_id: str, entry_id: str, day_index: int, recorded_weight_lbs: float):
    """Record one weigh-in as the official who operates the scale.

    The scale reading goes out as a JSON number, and the created row comes back
    with HTTP 201 as §4 requires of every creation.
    """
    payload = factories.weigh_in_payload(entry_id, day_index, recorded_weight_lbs)
    response = api.create_weigh_in(event_id, payload, WEIGH_IN_OFFICIAL)
    return validate_success(response, 201)


def _duals_scenario(api):
    """A certified wrestler entered at 150 in a two-day event open for weigh-ins.

    The wrestler follows the worked example of §3.3 — a 159.6 pound measurement
    at 14.0 percent body fat yielding a 147.6 pound minimum certified weight and
    a 150 pound minimum class — and carries a certified ``WEEKLY_STEP`` plan, so
    the lowest eligible class as of the event date is 150 and the entry at 150 is
    admitted.
    """
    scenario = fixtures.certified_wrestler(api)
    _publish_december_allowances(api, scenario.season_id)
    event = fixtures.create_event(
        api,
        scenario.season_id,
        _DUALS_NAME,
        _DUALS_DATE,
        EVENT_TYPE_DUAL,
        competition_days=2,
        weigh_in_days=2,
        consecutive_day_allowance_lbs=_PER_DAY_ALLOWANCE_LBS,
    )
    entry = fixtures.create_entry(
        api,
        event["id"],
        scenario.wrestler_id,
        scenario.team_id,
        CANON_TARGET_CLASS_LBS,
        season_win_count=_SEASON_WIN_COUNT,
    )
    fixtures.open_weigh_ins(api, event["id"])
    scenario.update(
        event=event, event_id=event["id"], entry=entry, entry_id=entry["id"]
    )
    return scenario


def _adjacent_events_scenario(api):
    """One certified wrestler entered at 150 in each of two adjacent events.

    §3.7 permits adjacency with a gap of exactly zero days, so an entry on the
    event whose window closes at the instant the next one opens is admitted on
    both.
    """
    scenario = fixtures.certified_wrestler(api)
    _publish_december_allowances(api, scenario.season_id)
    empty_event = fixtures.create_event(
        api,
        scenario.season_id,
        _EMPTY_EVENT_NAME,
        _EMPTY_EVENT_DATE,
        EVENT_TYPE_TOURNAMENT,
        competition_days=1,
        weigh_in_days=1,
    )
    seeded_event = fixtures.create_event(
        api,
        scenario.season_id,
        _SEEDED_EVENT_NAME,
        _SEEDED_EVENT_DATE,
        EVENT_TYPE_TOURNAMENT,
        competition_days=1,
        weigh_in_days=1,
    )
    empty_entry = fixtures.create_entry(
        api,
        empty_event["id"],
        scenario.wrestler_id,
        scenario.team_id,
        CANON_TARGET_CLASS_LBS,
        season_win_count=_SEASON_WIN_COUNT,
    )
    seeded_entry = fixtures.create_entry(
        api,
        seeded_event["id"],
        scenario.wrestler_id,
        scenario.team_id,
        CANON_TARGET_CLASS_LBS,
        season_win_count=_SEASON_WIN_COUNT,
    )
    scenario.update(
        empty_event=empty_event,
        empty_event_id=empty_event["id"],
        empty_entry=empty_entry,
        empty_entry_id=empty_entry["id"],
        seeded_event=seeded_event,
        seeded_event_id=seeded_event["id"],
        seeded_entry=seeded_entry,
        seeded_entry_id=seeded_entry["id"],
    )
    return scenario


def _close_weigh_ins_without_any_reading(api, event_id: str) -> None:
    """Walk an event through weigh-in day without recording a single reading.

    §3.8: closing weigh-ins scratches every entry still in ``ENTERED`` with
    ``scratch_reason`` ``NO_WEIGH_IN``, which is what empties the seeding pool.
    """
    fixtures.open_weigh_ins(api, event_id)
    fixtures.close_weigh_ins(api, event_id)


# ── The weigh-in verdict at the inclusive upper bound ─────────────────


def test_day_zero_weight_exactly_on_the_effective_limit_passes_with_allowance(api):
    """A recorded weight equal to the effective limit sits inside the bound.

    Day 0 earns nothing from the consecutive-day component, so the allowance is
    the 4.0 pound growth total alone and the effective limit is 150 + 4.0 =
    154.0.  A recorded 154.0 is strictly greater than the 150 pound class limit,
    which rules out ``PASS``, and exactly equal to the effective limit, which
    §3.8 resolves as ``PASS_WITH_ALLOWANCE`` rather than ``FAIL`` because §2.6
    makes landing on a limit permitted.

    Design: Difficulty/boundary_precision_check/weigh_in_effective_limit_inclusive_boundary
    """
    scenario = _duals_scenario(api)
    fixtures.move_clock(api, _DUALS_DAY0_INSTANT)

    expected_allowance = _expected_allowance_lbs(0)
    expected_limit = _expected_effective_limit_lbs(CANON_TARGET_CLASS_LBS, 0)
    assert expected_allowance == pytest.approx(_GROWTH_TOTAL_LBS, abs=0.01)
    assert expected_limit == pytest.approx(154.0, abs=0.01)

    weigh_in = _record_weigh_in(api, scenario.event_id, scenario.entry_id, 0, expected_limit)

    assert_weight_equals(weigh_in["allowance_lbs"], expected_allowance, "allowance_lbs")
    assert_weight_equals(
        weigh_in["effective_limit_lbs"], expected_limit, "effective_limit_lbs"
    )
    assert weigh_in["result"] == WEIGH_IN_PASS_WITH_ALLOWANCE, (
        f"a recorded {expected_limit} against an effective limit of {expected_limit} "
        f"is inside the inclusive bound, got {weigh_in['result']!r}"
    )
    assert weigh_in["result"] == expected_weigh_in_result(
        expected_limit, CANON_TARGET_CLASS_LBS, expected_limit
    )


def test_day_zero_boundary_weight_is_not_below_the_certified_minimum(api):
    """The boundary weight is above the certified floor, so no deficit is signalled.

    §3.8 makes ``below_minimum`` true only when the recorded weight is strictly
    below the wrestler's ``minimum_certified_weight_lbs``, which the worked
    example of §3.3 puts at 147.6 pounds.  A recorded 154.0 is well above it, so
    the flag reads false and no ``WEIGH_IN_DEFICIT`` flag is raised.

    Design: Difficulty/boundary_precision_check/weigh_in_effective_limit_inclusive_boundary
    """
    scenario = _duals_scenario(api)
    fixtures.move_clock(api, _DUALS_DAY0_INSTANT)

    expected_limit = _expected_effective_limit_lbs(CANON_TARGET_CLASS_LBS, 0)
    weigh_in = _record_weigh_in(api, scenario.event_id, scenario.entry_id, 0, expected_limit)

    assert expected_limit > CANON_MINIMUM_CERTIFIED_WEIGHT_LBS
    assert weigh_in["below_minimum"] is False, (
        f"{expected_limit} is not strictly below the certified minimum "
        f"{CANON_MINIMUM_CERTIFIED_WEIGHT_LBS}, got "
        f"below_minimum={weigh_in['below_minimum']!r}"
    )

    wrestler = fixtures.read_wrestler(api, scenario.wrestler_id)
    assert wrestler["open_health_flag_count"] == 0, (
        "a weigh-in above the certified minimum raises no health flag, got "
        f"open_health_flag_count={wrestler['open_health_flag_count']!r}"
    )


def test_day_one_weight_one_tenth_over_the_moved_limit_fails(api):
    """The limit moves with the consecutive-day component, and one tenth over fails.

    Day 1 earns ``day_index`` times the event's 1.0 pound per-day figure, capped
    at the season's 2.0 pound ceiling, so the allowance becomes 4.0 + 1.0 = 5.0
    and the effective limit becomes 150 + 5.0 = 155.0.  A recorded 155.1 strictly
    exceeds that limit at the one decimal place §2.6 carries weights to, which
    §3.8 resolves as ``FAIL``.

    Design: Difficulty/boundary_precision_check/weigh_in_effective_limit_inclusive_boundary
    """
    scenario = _duals_scenario(api)
    fixtures.move_clock(api, _DUALS_DAY0_INSTANT)
    _record_weigh_in(
        api,
        scenario.event_id,
        scenario.entry_id,
        0,
        _expected_effective_limit_lbs(CANON_TARGET_CLASS_LBS, 0),
    )

    fixtures.move_clock(api, _DUALS_DAY1_INSTANT)
    expected_allowance = _expected_allowance_lbs(1)
    expected_limit = _expected_effective_limit_lbs(CANON_TARGET_CLASS_LBS, 1)
    assert expected_allowance == pytest.approx(5.0, abs=0.01)
    assert expected_limit == pytest.approx(155.0, abs=0.01)

    over_the_limit = round_weight(expected_limit + 0.1)
    weigh_in = _record_weigh_in(
        api, scenario.event_id, scenario.entry_id, 1, over_the_limit
    )

    assert_weight_equals(weigh_in["allowance_lbs"], expected_allowance, "allowance_lbs")
    assert_weight_equals(
        weigh_in["effective_limit_lbs"], expected_limit, "effective_limit_lbs"
    )
    assert weigh_in["result"] == WEIGH_IN_FAIL, (
        f"a recorded {over_the_limit} strictly exceeds the effective limit "
        f"{expected_limit}, got {weigh_in['result']!r}"
    )
    assert weigh_in["result"] == expected_weigh_in_result(
        over_the_limit, CANON_TARGET_CLASS_LBS, expected_limit
    )


@pytest.mark.parametrize(
    "recorded_weight_lbs, expected_result",
    [
        (155.0, WEIGH_IN_PASS_WITH_ALLOWANCE),
        (155.1, WEIGH_IN_FAIL),
    ],
)
def test_day_one_verdict_turns_over_exactly_one_tenth_of_a_pound(
    api, recorded_weight_lbs, expected_result
):
    """The verdict flips between 155.0 and 155.1 against a 155.0 pound limit.

    Both readings are strictly greater than the 150 pound class limit, so the
    allowance is consulted in each case.  §3.8 makes the upper comparison
    inclusive, so the reading equal to the limit still passes with allowance
    while the reading one tenth of a pound above it fails; rounding 155.1 to the
    whole pound would collapse the two.

    Design: Difficulty/boundary_precision_check/weigh_in_effective_limit_inclusive_boundary
    """
    scenario = _duals_scenario(api)
    fixtures.move_clock(api, _DUALS_DAY1_INSTANT)

    expected_limit = _expected_effective_limit_lbs(CANON_TARGET_CLASS_LBS, 1)
    weigh_in = _record_weigh_in(
        api, scenario.event_id, scenario.entry_id, 1, recorded_weight_lbs
    )

    assert_weight_equals(
        weigh_in["effective_limit_lbs"], expected_limit, "effective_limit_lbs"
    )
    assert weigh_in["result"] == expected_result, (
        f"a recorded {recorded_weight_lbs} against an effective limit of "
        f"{expected_limit} is {expected_result}, got {weigh_in['result']!r}"
    )


def test_failed_later_day_never_overwrites_the_boundary_passing_weight(api):
    """The day-0 boundary pass stands as the entry's latest effective weight.

    §3.8: a passing weigh-in advances the entry to ``WEIGHED_IN`` and sets
    ``latest_effective_weight_lbs`` from the passing weigh-in with the greatest
    ``day_index``, while a ``FAIL`` never overwrites that field and does not
    advance the entry.  The event's ``weighed_in_count`` counts entries in
    ``WEIGHED_IN`` or ``SEEDED``, so it reads 1.

    Design: Difficulty/boundary_precision_check/weigh_in_effective_limit_inclusive_boundary
    """
    scenario = _duals_scenario(api)
    boundary_weight = _expected_effective_limit_lbs(CANON_TARGET_CLASS_LBS, 0)

    fixtures.move_clock(api, _DUALS_DAY0_INSTANT)
    _record_weigh_in(api, scenario.event_id, scenario.entry_id, 0, boundary_weight)
    fixtures.move_clock(api, _DUALS_DAY1_INSTANT)
    failing = _record_weigh_in(
        api,
        scenario.event_id,
        scenario.entry_id,
        1,
        round_weight(_expected_effective_limit_lbs(CANON_TARGET_CLASS_LBS, 1) + 0.1),
    )
    assert failing["result"] == WEIGH_IN_FAIL

    entry = fixtures.read_entry(api, scenario.entry_id)
    assert entry["status"] == ENTRY_WEIGHED_IN, (
        f"the failing later day leaves the entry where it was, got {entry['status']!r}"
    )
    assert_weight_equals(
        entry["latest_effective_weight_lbs"],
        boundary_weight,
        "latest_effective_weight_lbs",
    )

    event = fixtures.read_event(api, scenario.event_id)
    assert event["weighed_in_count"] == 1, (
        f"expected weighed_in_count 1, got {event['weighed_in_count']!r}"
    )


# ── The seeding pool at the zero/one cardinality edge ─────────────────


def test_seeding_an_event_whose_only_entry_was_scratched_is_refused(api):
    """A globally empty admitted pool refuses the seeding run.

    Closing weigh-ins with no reading recorded scratches the event's only entry
    with ``scratch_reason`` ``NO_WEIGH_IN``, and §3.8 excludes ``SCRATCHED``
    entries from the admitted pool.  The initial run out of ``WEIGH_IN_CLOSED``
    therefore sees zero admitted entries and is refused with
    ``ERR_NO_SEEDABLE_ENTRIES``.

    Design: Difficulty/boundary_precision_check/empty_seeding_pool_zero_count_edge
    """
    scenario = _adjacent_events_scenario(api)
    _close_weigh_ins_without_any_reading(api, scenario.empty_event_id)

    entry = fixtures.read_entry(api, scenario.empty_entry_id)
    assert entry["status"] == ENTRY_SCRATCHED, (
        f"an entry that never weighed in is scratched at close, got {entry['status']!r}"
    )
    assert entry["scratch_reason"] == SCRATCH_REASON_NO_WEIGH_IN, (
        f"expected scratch_reason {SCRATCH_REASON_NO_WEIGH_IN}, "
        f"got {entry['scratch_reason']!r}"
    )
    assert entry["seed_number"] is None, (
        f"an excluded entry receives no seed number, got {entry['seed_number']!r}"
    )

    response = api.seed_event(scenario.empty_event_id, STATE_OFFICE)
    validate_error(response, api_errors.ERR_NO_SEEDABLE_ENTRIES, 409)


def test_refused_seeding_leaves_the_bracket_unlocked_and_the_seed_sum_at_zero(api):
    """The refused run leaves the event exactly where the state machine had it.

    §3.8 sets ``bracket_locked`` true only on a first *successful* seeding run and
    refreshes ``seeded_entry_count`` and ``seed_integrity_sum`` only there, so the
    refusal leaves the event in ``WEIGH_IN_CLOSED`` with the lock still false and
    both counters at the zero they were created with — the empty side of the
    cardinality edge.

    Design: Difficulty/boundary_precision_check/empty_seeding_pool_zero_count_edge
    """
    scenario = _adjacent_events_scenario(api)
    _close_weigh_ins_without_any_reading(api, scenario.empty_event_id)

    response = api.seed_event(scenario.empty_event_id, STATE_OFFICE)
    validate_error(response, api_errors.ERR_NO_SEEDABLE_ENTRIES, 409)

    event = fixtures.read_event(api, scenario.empty_event_id)
    assert event["status"] == EVENT_WEIGH_IN_CLOSED, (
        f"the refused seed drives no transition, got {event['status']!r}"
    )
    assert event["bracket_locked"] is False, (
        f"only a successful seeding run locks the bracket, got "
        f"bracket_locked={event['bracket_locked']!r}"
    )
    assert event["seeded_entry_count"] == 0, (
        f"expected seeded_entry_count 0, got {event['seeded_entry_count']!r}"
    )
    assert event["seed_integrity_sum"] == expected_seed_integrity_sum([]), (
        f"expected seed_integrity_sum 0 for an empty pool, got "
        f"{event['seed_integrity_sum']!r}"
    )


def test_weigh_in_exactly_at_the_class_limit_passes_outright(api):
    """A reading equal to the class limit passes before the allowance is consulted.

    §3.8 orders the three comparisons: ``PASS`` when the recorded weight is less
    than or equal to the entry's ``weight_class_lbs`` outright.  A recorded 150.0
    against a 150 pound class is exactly on that first bound, so the verdict is
    ``PASS`` and not ``PASS_WITH_ALLOWANCE``, and 150.0 is not strictly below the
    147.6 pound certified minimum so ``below_minimum`` reads false.

    Design: Difficulty/boundary_precision_check/empty_seeding_pool_zero_count_edge
    """
    scenario = _adjacent_events_scenario(api)
    fixtures.open_weigh_ins(api, scenario.seeded_event_id)
    fixtures.move_clock(api, _SEEDED_EVENT_INSTANT)

    at_the_class_limit = float(CANON_TARGET_CLASS_LBS)
    weigh_in = _record_weigh_in(
        api, scenario.seeded_event_id, scenario.seeded_entry_id, 0, at_the_class_limit
    )

    assert weigh_in["result"] == WEIGH_IN_PASS, (
        f"a recorded {at_the_class_limit} equals the class limit "
        f"{CANON_TARGET_CLASS_LBS} and passes outright, got {weigh_in['result']!r}"
    )
    assert weigh_in["below_minimum"] is False, (
        f"{at_the_class_limit} is not strictly below "
        f"{CANON_MINIMUM_CERTIFIED_WEIGHT_LBS}, got "
        f"below_minimum={weigh_in['below_minimum']!r}"
    )


def test_single_weighed_in_entry_seeds_to_the_minimum_non_empty_seed_sum(api):
    """Exactly one admitted entry is the other side of the cardinality edge.

    With one entry in ``WEIGHED_IN``, §3.8 admits it, gives its class a
    contiguous run of seed numbers beginning at 1, moves the entry to ``SEEDED``
    and the event to ``SEEDED``, locks the bracket and refreshes both counters.
    §2.9 fixes the conserved sum at one times one plus one divided by two, so it
    reads 1 rather than the 0 the empty pool leaves behind.

    Design: Difficulty/boundary_precision_check/empty_seeding_pool_zero_count_edge
    """
    scenario = _adjacent_events_scenario(api)
    fixtures.open_weigh_ins(api, scenario.seeded_event_id)
    fixtures.move_clock(api, _SEEDED_EVENT_INSTANT)
    _record_weigh_in(
        api,
        scenario.seeded_event_id,
        scenario.seeded_entry_id,
        0,
        float(CANON_TARGET_CLASS_LBS),
    )
    fixtures.close_weigh_ins(api, scenario.seeded_event_id)

    event = get_success_data(api.seed_event(scenario.seeded_event_id, STATE_OFFICE), 200)

    assert event["status"] == EVENT_SEEDED, (
        f"a successful initial run lands the event in SEEDED, got {event['status']!r}"
    )
    assert event["bracket_locked"] is True, (
        f"the initial run sets bracket_locked true, got {event['bracket_locked']!r}"
    )
    assert event["reseed_required"] is False, (
        f"the initial run sets reseed_required false, got {event['reseed_required']!r}"
    )
    assert event["seeded_entry_count"] == 1, (
        f"expected seeded_entry_count 1, got {event['seeded_entry_count']!r}"
    )
    assert event["seed_integrity_sum"] == expected_seed_integrity_sum([1]), (
        f"one seeded entry in one class conserves a seed sum of 1, got "
        f"{event['seed_integrity_sum']!r}"
    )

    entry = fixtures.read_entry(api, scenario.seeded_entry_id)
    assert entry["status"] == ENTRY_SEEDED, (
        f"the admitted entry moves to SEEDED, got {entry['status']!r}"
    )
    assert entry["seed_number"] == 1, (
        f"seed numbers count from 1 within a class, got {entry['seed_number']!r}"
    )


def test_adjacent_competition_windows_admit_both_entries(api):
    """Two windows meeting at a single instant are not an entry conflict.

    The half-open competition windows are [2026-12-14, 2026-12-15) and
    [2026-12-15, 2026-12-16), and §3.7 permits adjacency with a gap of exactly
    zero days, so the second entry is admitted rather than refused with
    ``ERR_ENTRY_WINDOW_CONFLICT``.  Each event counts its own single entry.

    Design: Difficulty/boundary_precision_check/empty_seeding_pool_zero_count_edge
    """
    scenario = _adjacent_events_scenario(api)

    for entry_id, label in (
        (scenario.empty_entry_id, _EMPTY_EVENT_NAME),
        (scenario.seeded_entry_id, _SEEDED_EVENT_NAME),
    ):
        entry = fixtures.read_entry(api, entry_id)
        assert entry["status"] == ENTRY_ENTERED, (
            f"{label}: a freshly admitted entry lands in ENTERED, got "
            f"{entry['status']!r}"
        )
        assert entry["weight_class_lbs"] == CANON_TARGET_CLASS_LBS

    for event_id, label in (
        (scenario.empty_event_id, _EMPTY_EVENT_NAME),
        (scenario.seeded_event_id, _SEEDED_EVENT_NAME),
    ):
        event = fixtures.read_event(api, event_id)
        assert event["entry_count"] == 1, (
            f"{label}: expected entry_count 1, got {event['entry_count']!r}"
        )
