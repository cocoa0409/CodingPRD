"""Requests that break two rules at once, so only the precedence order decides.

Each pair is issued twice: once with both rules live, and once with the loser
isolated, which proves the second rule was suppressed rather than absent.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import constants as K
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import GUILD_ADMINISTRATOR_HEADERS, STUDIO_EXECUTIVE_HEADERS

OVERLAPPING_SEAT_START = "2026-09-15T00:00:00Z"
OVERLAPPING_SEAT_END = "2026-12-01T00:00:00Z"
SECOND_WINDOW_START = "2026-08-20T00:00:00Z"


def _seats_of(api, **params):
    """Every seat row matching the supplied filter."""
    rows, _ = validate_paginated(
        api.list_room_seats(STUDIO_EXECUTIVE_HEADERS, dict(params, limit=100))
    )
    return rows


def _tight_budget_world(api):
    """One confirmed seat has already spent most of a 1,000,000 weekly budget."""
    world = X.build_staffing_room_world(
        api, season_overrides={"staffing_budget_weekly_cents": 1000000}
    )
    validate_success(
        api.add_credit_history(
            world["w2_id"],
            {"episodic_credits_awarded": 4, "agreement_id": world["agreement_id"]},
            GUILD_ADMINISTRATOR_HEADERS,
        )
    )
    seat = X.seed_seat(
        api,
        world["room_id"],
        world["w1_id"],
        world["sr_headers"],
        expected_room_version=world["room_version"],
        episodic_guarantee_count=0,
    )
    world["s1_id"] = seat["id"]
    X.accept_seat(api, seat["id"], world["w1_id"])
    world["room_version"] = X.current_room_version(api, world["room_id"])
    return world


def _unaffordable_offer(world, room_version):
    """A CO_PRODUCER offer that would take the season 700,000 over its budget."""
    return F.build_seat_offer(
        world["w2_id"],
        room_version,
        level_at_hire="CO_PRODUCER",
        offered_weekly_compensation_cents=900000,
        episodic_guarantee_count=0,
    )


def _double_booked_world(api):
    """A writer already holding an exclusive seat, with a second window still open."""
    world = X.build_staffing_room_world(api)
    seat = X.seed_seat(
        api,
        world["room_id"],
        world["w1_id"],
        world["sr_headers"],
        expected_room_version=world["room_version"],
        episodic_guarantee_count=0,
    )
    world["s1_id"] = seat["id"]
    X.accept_seat(api, seat["id"], world["w1_id"])
    world["aw2"] = X.seed_window(
        api,
        world["w1_id"],
        "NON_EXCLUSIVE",
        SECOND_WINDOW_START,
        K.WINDOW_END_DATE,
    )
    world["aw2_id"] = world["aw2"]["id"]
    world["room_version"] = X.current_room_version(api, world["room_id"])
    return world


def _overlapping_offer(world, room_version, offered_cents):
    """A second exclusive seat that overlaps the first by two and a half months."""
    return F.build_seat_offer(
        world["w1_id"],
        room_version,
        offered_weekly_compensation_cents=offered_cents,
        start_date=OVERLAPPING_SEAT_START,
        end_date=OVERLAPPING_SEAT_END,
        episodic_guarantee_count=0,
    )


def test_an_over_budget_offer_into_a_staffing_room_reports_the_fiscal_ceiling(api):
    """With the room still hiring, the budget is the only rule the offer breaks.

    PRD: "The **staffing budget** test on a seat offer adds the new seat's own weekly compensation to the season's current commitment and requires the result to be at or below `staffing_budget_weekly_cents`; exceeding it is rejected with `ERR_SEASON_STAFFING_BUDGET_EXCEEDED`."

    PRD: "20. Fiscal ceilings: the season staffing budget and the script fee budget."

    Design: Difficulty/priority_pair_validation_conflict/state_30_beats_fiscal_75_on_an_over_budget_offer_into_an_active_room
    """
    world = _tight_budget_world(api)
    room = X.read_room(api, world["room_id"])
    A.assert_field_values(room, status="STAFFING")
    A.assert_cents(
        X.read_season(api, world["season_id"])["staffing_commitment_weekly_cents"],
        K.ROOM_BURN_ONE_SEAT_600000,
        "staffing_commitment_weekly_cents",
    )

    validate_error(
        api.offer_seat(
            world["room_id"],
            _unaffordable_offer(world, world["room_version"]),
            world["sr_headers"],
        ),
        ApiErrorId.SEASON_STAFFING_BUDGET_EXCEEDED,
    )

    after = X.read_room(api, world["room_id"])
    A.assert_field_values(
        after, confirmed_seat_count=1, filled_seat_count=1, open_seat_count=2
    )
    assert after["version"] == world["room_version"], (
        "A refused offer must not advance the room version"
    )
    assert len(_seats_of(api, room_id=world["room_id"])) == 1, (
        "The refused offer must not have been persisted"
    )


def test_the_same_over_budget_offer_into_an_active_room_reports_the_room_state(api):
    """Both rules are live, and only the state check at step 14 is reported.

    PRD: "When more than one rule could reject a request, the checks run in a fixed precedence and the first failure is the one reported. The order is:"

    PRD: "First the room must be in `STAFFING`, otherwise `ERR_ROOM_NOT_ACCEPTING_SEATS`."

    Design: Difficulty/priority_pair_validation_conflict/state_30_beats_fiscal_75_on_an_over_budget_offer_into_an_active_room
    """
    world = _tight_budget_world(api)
    activated = X.activate_room(api, world["room_id"])
    A.assert_field_values(activated, status="ACTIVE")
    live_version = activated["version"]

    validate_error(
        api.offer_seat(
            world["room_id"],
            _unaffordable_offer(world, live_version),
            world["sr_headers"],
        ),
        ApiErrorId.ROOM_NOT_ACCEPTING_SEATS,
    )

    after = X.read_room(api, world["room_id"])
    A.assert_field_values(after, status="ACTIVE", confirmed_seat_count=1)
    assert after["version"] == live_version, (
        "A refused offer must not advance the room version"
    )
    A.assert_cents(
        X.read_season(api, world["season_id"])["staffing_commitment_weekly_cents"],
        K.ROOM_BURN_ONE_SEAT_600000,
        "staffing_commitment_weekly_cents",
    )
    assert len(_seats_of(api, room_id=world["room_id"])) == 1, (
        "The refused offer must not have been persisted"
    )


def test_an_underpaid_overlapping_offer_reports_the_compensation_floor(api):
    """The money floor at step 16 outranks the interval collision at step 18.

    PRD: "16. Domain safety rules: guild compensation floor, level requirement, diversity funding eligibility, diversity staffing requirement, clearance gates and the conditional-note requirement."

    PRD: "Then the money floor: the offered weekly compensation must be at least the agreement's minimum weekly cents for the seat's `level_at_hire`, otherwise `ERR_BELOW_GUILD_MINIMUM`."

    Design: Difficulty/priority_pair_validation_conflict/safety_45_beats_constraint_65_on_an_underpaid_overlapping_second_seat
    """
    world = _double_booked_world(api)

    validate_error(
        api.offer_seat(
            world["room_id"],
            _overlapping_offer(world, world["room_version"], 500000),
            world["sr_headers"],
        ),
        ApiErrorId.BELOW_GUILD_MINIMUM,
    )

    room = X.read_room(api, world["room_id"])
    assert room["version"] == world["room_version"], (
        "A refused offer must not advance the room version"
    )
    A.assert_field_values(
        room, confirmed_seat_count=1, filled_seat_count=1, open_seat_count=2
    )
    assert len(_seats_of(api, room_id=world["room_id"])) == 1, (
        "The refused offer must not have been persisted"
    )
    A.assert_field_values(X.read_window(api, world["aw2_id"]), status="OPEN")


def test_repairing_the_rate_exposes_the_interval_collision_underneath(api):
    """At a lawful rate the same dates collide with the writer's exclusive seat.

    PRD: "18. Structural business constraints: writer interval exclusivity, availability containment, production-unit turnaround, capacity and uniqueness, and the revision cap."

    PRD: "The pair collides only when at least one of the two seats is `EXCLUSIVE`; two `NON_EXCLUSIVE` seats may overlap freely."

    Design: Difficulty/priority_pair_validation_conflict/safety_45_beats_constraint_65_on_an_underpaid_overlapping_second_seat
    """
    world = _double_booked_world(api)

    validate_error(
        api.offer_seat(
            world["room_id"],
            _overlapping_offer(world, world["room_version"], 600000),
            world["sr_headers"],
        ),
        ApiErrorId.WRITER_WINDOW_CONFLICT,
    )

    room = X.read_room(api, world["room_id"])
    assert room["version"] == world["room_version"], (
        "A refused offer must not advance the room version"
    )
    A.assert_seat_capacity_conserved(room)
    A.assert_field_values(X.read_window(api, world["aw2_id"]), status="OPEN")
    A.assert_field_values(X.read_writer(api, world["w1_id"]), active_seat_count=1)
    A.assert_field_values(X.read_seat(api, world["s1_id"]), status="CONFIRMED")
