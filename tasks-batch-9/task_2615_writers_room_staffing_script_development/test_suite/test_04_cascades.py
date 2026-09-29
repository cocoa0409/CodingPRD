"""Single writes whose consequences run four and five entities deep.

A reschedule walks season to episode to assignment to milestone and back out
through lateness; a seat release fans out across the seat, the window, the
assignment, the room, the season and the writer.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as A
from test_helpers import constants as K
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import STUDIO_EXECUTIVE_HEADERS

CLOCK_MID_OCTOBER = "2026-10-10T00:00:00Z"
PULLED_IN_PRODUCTION_START = "2026-10-25T00:00:00Z"

DUE_DATES_OCT_25 = {
    "outline_due_date": "2026-09-13T23:59:59.999Z",
    "first_draft_due_date": "2026-09-27T23:59:59.999Z",
    "second_draft_due_date": "2026-10-11T23:59:59.999Z",
    "polish_due_date": "2026-10-22T23:59:59.999Z",
}

DUE_DATES_JAN_04 = {
    "outline_due_date": K.DUE_DATES_JAN_04["OUTLINE"],
    "first_draft_due_date": K.DUE_DATES_JAN_04["FIRST_DRAFT"],
    "second_draft_due_date": K.DUE_DATES_JAN_04["SECOND_DRAFT"],
    "polish_due_date": K.DUE_DATES_JAN_04["POLISH"],
}

SINGLE_SEAT_ROOM = {"seat_capacity": 3}


def _reschedule_world(api):
    """An assignment whose milestones are all pending with the clock past two of them."""
    world = X.build_assignment_world(api)
    X.set_clock(api, CLOCK_MID_OCTOBER)
    world["season"] = X.read_season(api, world["season_id"])
    world["season_version"] = world["season"]["version"]
    return world


def _single_seat_world(api):
    """One confirmed seat in an ACTIVE room, carrying one drafting assignment."""
    world = X.build_staffing_room_world(api, room_overrides=SINGLE_SEAT_ROOM)
    seat = X.seed_seat(
        api,
        world["room_id"],
        world["w1_id"],
        world["sr_headers"],
        expected_room_version=world["room_version"],
        episodic_guarantee_count=1,
    )
    world["s1_id"] = seat["id"]
    world["s1"] = X.accept_seat(api, seat["id"], world["w1_id"])
    world["room"] = X.activate_room(api, world["room_id"])
    world["ep1"] = X.seed_episode(api, world["season_id"], 1)
    world["ep1_id"] = world["ep1"]["id"]
    world["a1"] = X.seed_assignment(
        api, world["ep1_id"], world["w1_id"], world["sr_headers"], "TELEPLAY"
    )
    world["a1_id"] = world["a1"]["id"]
    return world


def test_pulling_the_production_start_in_flips_two_milestones_late(api):
    """An eight-day slip backwards re-derives every deadline and lands two in the past.

    PRD: "When the date is accepted, the delta between the old and new season production start is computed once and applied uniformly: every episode of the season whose `script_readiness` is not `LOCKED` has its own `production_start_date` shifted by that same signed delta, so relative episode spacing and unit assignments survive the move untouched."

    PRD: "Each re-derived milestone is then re-evaluated against the logical clock: a `PENDING` milestone whose new deadline has already passed flips to `LATE`, and — this is the direction that only a reschedule can produce — a `LATE` milestone whose re-derived deadline is now at or after the logical clock flips back to `PENDING`."

    Design: Difficulty/transitive_cascade/cascade_a_season_reschedule_propagates_to_milestone_lateness_and_back
    """
    world = _reschedule_world(api)
    before = X.milestones_of(api, world["a1_id"])
    assert [m["status"] for m in before] == ["PENDING"] * 3, (
        f"Advancing the clock alone must mutate nothing: {[m['status'] for m in before]}"
    )

    validate_success(
        api.reschedule_season(
            world["season_id"],
            F.build_reschedule(world["season_version"], PULLED_IN_PRODUCTION_START),
            STUDIO_EXECUTIVE_HEADERS,
        )
    )

    A.assert_instant(
        X.read_episode(api, world["ep1_id"])["production_start_date"],
        PULLED_IN_PRODUCTION_START,
        "production_start_date",
    )
    assignment = X.read_assignment(api, world["a1_id"])
    A.assert_field_values(assignment, **DUE_DATES_OCT_25)
    A.assert_field_values(assignment, late_milestone_count=2)

    outline, first_draft, second_draft = X.milestones_of(api, world["a1_id"])
    A.assert_field_values(outline, status="LATE")
    A.assert_field_values(first_draft, status="LATE")
    A.assert_field_values(second_draft, status="PENDING")


def test_pushing_the_production_start_out_again_un_flips_the_lateness(api):
    """Lateness is derived state, so a later deadline returns a milestone to pending.

    PRD: "Every affected assignment's `late_milestone_count` is recomputed from the resulting milestone statuses, the season's coverage figures are recomputed, and the season's `version` increments by one."

    PRD: "A reschedule supersedes the season's entire milestone calendar, so a reschedule carrying a version that has already advanced is rejected with `ERR_STALE_SEASON_VERSION` (HTTP 412) instead of shifting dates derived from a production start the client never observed."

    Design: Difficulty/transitive_cascade/cascade_a_season_reschedule_propagates_to_milestone_lateness_and_back
    """
    world = _reschedule_world(api)
    first = validate_success(
        api.reschedule_season(
            world["season_id"],
            F.build_reschedule(world["season_version"], PULLED_IN_PRODUCTION_START),
            STUDIO_EXECUTIVE_HEADERS,
        )
    )
    assert first["version"] == world["season_version"] + 1, (
        "Each reschedule advances the season version by exactly one"
    )

    second = validate_success(
        api.reschedule_season(
            world["season_id"],
            F.build_reschedule(first["version"], K.RESCHEDULED_PRODUCTION_START),
            STUDIO_EXECUTIVE_HEADERS,
        )
    )
    A.assert_instant(
        second["production_start_date"],
        K.RESCHEDULED_PRODUCTION_START,
        "production_start_date",
    )
    A.assert_instant(
        X.read_episode(api, world["ep1_id"])["production_start_date"],
        K.RESCHEDULED_PRODUCTION_START,
        "production_start_date",
    )

    assignment = X.read_assignment(api, world["a1_id"])
    A.assert_field_values(assignment, **DUE_DATES_JAN_04)
    A.assert_field_values(assignment, late_milestone_count=0)

    milestones = X.milestones_of(api, world["a1_id"])
    assert [m["status"] for m in milestones] == ["PENDING"] * 3, (
        f"Every milestone must return to PENDING: {[m['status'] for m in milestones]}"
    )
    A.assert_field_values(milestones[0], due_date=K.DUE_DATES_JAN_04["OUTLINE"])

    validate_error(
        api.reschedule_season(
            world["season_id"],
            F.build_reschedule(world["season_version"], PULLED_IN_PRODUCTION_START),
            STUDIO_EXECUTIVE_HEADERS,
        ),
        ApiErrorId.STALE_SEASON_VERSION,
    )


def test_releasing_a_seat_frees_the_window_and_parks_the_assignment(api):
    """The release reaches the consumed window and the script the seat was carrying.

    PRD: "On release the seat becomes `RELEASED`; the window it consumed returns to `OPEN` with its `consumed_by_seat_id` cleared and the seat's `consumed_window_id` cleared, freeing that stretch of the writer's calendar for another room; the room's `filled_seat_count` and `confirmed_seat_count` each drop by one, `confirmed_diversity_seat_count` drops too when the seat was diversity-funded, and `open_seat_count` is recomputed; the writer's `active_seat_count` drops by one; and the room's weekly figures and then the season's staffing commitment are recomputed."

    Design: Difficulty/transitive_cascade/cascade_b_seat_release_reaches_availability_window_assignment_room_and_season
    """
    world = _single_seat_world(api)

    released = validate_success(
        api.release_seat(
            world["s1_id"],
            STUDIO_EXECUTIVE_HEADERS,
            {"reason": "Writer moved to a competing overall deal."},
        )
    )
    A.assert_field_values(released, status="RELEASED", consumed_window_id=None)

    window = X.read_window(api, world["aw1_id"])
    A.assert_field_values(window, status="OPEN", consumed_by_seat_id=None)

    assignment = X.read_assignment(api, world["a1_id"])
    # PRD: "the assignment keeps the seat reference it was created with, so the
    # seat's guarantee counters are unaffected by the release".
    A.assert_field_values(
        assignment, status="REASSIGNMENT_PENDING", room_seat_id=world["s1_id"]
    )
    A.assert_cents(assignment["payable_fee_cents"], 1750000, "payable_fee_cents")

    rows = X.ledger_for_assignment(api, world["a1_id"])
    assert len(rows) == 2, f"A release must not touch the fee ledger: {rows}"
    A.assert_ledger_sum(rows, 1750000)


def test_releasing_a_seat_collapses_the_room_burn_and_the_season_commitment(api):
    """With no confirmed seat left the room's whole burn is its facility surcharge.

    PRD: "Step one sums `weekly_compensation_cents` across only those seats of the room whose status is `CONFIRMED`, producing `seat_subtotal_weekly_cents`; seats merely `OFFERED` contribute nothing."

    PRD: "**Season staffing commitment** is the sum of `weekly_burn_cents` over the season's rooms whose status is `STAFFING` or `ACTIVE`; rooms that are still `OPEN` and rooms that have `WRAPPED` retain their computed burn but are excluded from the sum."

    Design: Difficulty/transitive_cascade/cascade_b_seat_release_reaches_availability_window_assignment_room_and_season
    """
    world = _single_seat_world(api)
    room_before = X.read_room(api, world["room_id"])
    A.assert_room_burn(
        room_before, 600000, K.FACILITY_TIER_1, 200000, K.ROOM_BURN_ONE_SEAT_600000
    )

    validate_success(
        api.release_seat(
            world["s1_id"],
            STUDIO_EXECUTIVE_HEADERS,
            {"reason": "Writer moved to a competing overall deal."},
        )
    )

    room = X.read_room(api, world["room_id"])
    A.assert_room_burn(
        room, 0, K.FACILITY_TIER_1, K.ROOM_BURN_EMPTY_IN_PERSON, K.ROOM_BURN_EMPTY_IN_PERSON
    )
    A.assert_field_values(
        room, confirmed_seat_count=0, filled_seat_count=0, open_seat_count=3
    )
    A.assert_seat_capacity_conserved(room)

    season = X.read_season(api, world["season_id"])
    A.assert_cents(
        season["staffing_commitment_weekly_cents"],
        K.ROOM_BURN_EMPTY_IN_PERSON,
        "staffing_commitment_weekly_cents",
    )
    A.assert_field_values(
        season, ready_script_count=0, coverage_gap=1, coverage_posture="AT_RISK"
    )

    A.assert_field_values(X.read_writer(api, world["w1_id"]), active_seat_count=0)
    A.assert_field_values(
        X.read_episode(api, world["ep1_id"]), script_readiness="IN_PROGRESS"
    )
