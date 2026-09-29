"""Cross-cutting complexity: the four optimistic-concurrency races taken as one
sequence, and the seat selector that resolves an assignment's room seat.

Every test in this module translates exactly one instance of
SCAFFOLD_CORNER_DESIGN.yaml section `cross_cutting_complexity_layers`.
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
from test_helpers.test_users import STUDIO_EXECUTIVE_HEADERS

# --- Module landmarks --------------------------------------------------------

# The room row is mutated once by its creation and once by open-staffing.
ROOM_VERSION_AT_OPEN_STAFFING = 2
# ... and then by the offer, the reconfiguration, the acceptance and activation.
ROOM_VERSION_AFTER_ACTIVATION = 6

STAFF_WRITER_FLOOR = K.MIN_WEEKLY_CENTS_BY_LEVEL["STAFF_WRITER"]

# A reschedule two weeks later than the canonical 2026-11-02 start, and a second
# one that is never applied.
NEW_PRODUCTION_START = "2026-11-16T00:00:00Z"
LATER_PRODUCTION_START = "2026-12-01T00:00:00Z"

# The lead days 42 / 28 / 14 / 3 counted back from 2026-11-16.
DUE_DATES_NOV_16 = {
    "OUTLINE": "2026-10-05T23:59:59.999Z",
    "FIRST_DRAFT": "2026-10-19T23:59:59.999Z",
    "SECOND_DRAFT": "2026-11-02T23:59:59.999Z",
    "POLISH": "2026-11-13T23:59:59.999Z",
}
TELEPLAY_MILESTONE_CHAIN = ["OUTLINE", "FIRST_DRAFT", "SECOND_DRAFT"]

# A sibling room of the same season, so one writer can hold two seats at once.
SECOND_UNIT_ROOM = {
    "name": "Second Unit Room",
    "format": "REMOTE",
    "seat_capacity": 2,
}
# A window that starts later than the registry's aw1, so the window selector
# takes aw1 for the first seat and this one for the second.
SECOND_WINDOW_START = "2026-08-20T00:00:00Z"
CLOCK_AUGUST_05 = "2026-08-05T00:00:00Z"

RELEASE_ROOM_FOLDED = {"reason": "Room folded into the second unit."}
RELEASE_WRITER_LEFT = {"reason": "Writer left the show."}

# STORY_EDITOR carries a 0.5 guarantee offset fraction on a one-hour episode.
TELEPLAY_OFFSET_ONE_HOUR = 1750000
TELEPLAY_PAYABLE_ONE_HOUR = 1750000
STORY_OFFSET_ONE_HOUR = 750000
STORY_PAYABLE_ONE_HOUR = 750000


# --- Local helpers -----------------------------------------------------------

def _assert_error_envelope(response, expected_error_id, expected_status):
    """Validate one error response and the envelope shape 2.2 prescribes."""
    error = validate_error(response, expected_error_id, expected_status)
    body = response.json()
    assert set(body["data"]) == {"error_id", "message"}, (
        f"An error payload carries only error_id and message: {sorted(body['data'])}"
    )
    return error


def _total(response):
    """The pre-pagination row count of one list response."""
    _rows, meta = validate_paginated(response)
    return meta["total_count"]


def test_all_four_version_races_refuse_the_stale_token_and_admit_the_retry(api):
    """Each of the four declared races is run with a version that was genuinely
    current when it was read and went stale on an unrelated write. The refusal
    names the stale-version code rather than the business failure sitting under
    it, consumes no version, and the retry at version + 1 lands.

    PRD: "In every case the version field is a **required, non-optional** input, and a value that does not equal the parent row's current `version` at the moment of the write is rejected before any side effect is applied."

    PRD: "A mismatch is rejected with `ERR_STALE_ROOM_VERSION` (HTTP 412)."

    PRD: "a reconfigure carrying a version the room has already advanced past is rejected with `ERR_STALE_ROOM_VERSION` (HTTP 412) rather than being applied on top of a configuration the client never saw"

    PRD: "so a create from a stale episode view is rejected with `ERR_STALE_EPISODE_VERSION` (HTTP 412)"

    PRD: "so a reschedule carrying a version that has already advanced is rejected with `ERR_STALE_SEASON_VERSION` (HTTP 412) instead of shifting dates derived from a production start the client never observed"

    PRD: "Ownership and season-showrunner checks therefore precede optimistic concurrency, and optimistic concurrency precedes every state and domain check"

    PRD: "**Availability containment** then requires that the writer has at least one availability window in `OPEN` status whose interval fully contains the seat's: the window must start at or before the seat's start and end at or after the seat's end."

    PRD: "`version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that row"

    PRD: "Step three multiplies the facility fee for the selected tier by the agreement's format surcharge fraction for the room's `format` and rounds the product to whole cents, giving `facility_surcharge_weekly_cents`."

    PRD: "every episode of the season whose `script_readiness` is not `LOCKED` has its own `production_start_date` shifted by that same signed delta"

    PRD: "Every non-void script assignment on a shifted episode has all four of its due-date fields re-derived from the new episode date, and every milestone of those assignments has its `due_date` re-derived to match."

    Design: Corner/cross_cutting_complexity_layers/all_four_declared_races_refuse_a_stale_parent_version_and_admit_the_fresh_one
    """
    world = X.build_staffing_room_world(api)
    room_id = world["room_id"]
    season_id = world["season_id"]

    # The token a client would have captured at open-staffing.
    rv1 = world["room_version"]
    assert rv1 == ROOM_VERSION_AT_OPEN_STAFFING, (
        f"the room is created at 1 and open-staffing takes it to 2, got {rv1}"
    )

    # The unrelated write that supersedes rv1.
    s1 = X.seed_seat(
        api,
        room_id,
        world["w1_id"],
        world["sr_headers"],
        expected_room_version=rv1,
        episodic_guarantee_count=1,
    )
    A.assert_field_values(
        X.read_room(api, room_id), status="STAFFING", version=rv1 + 1
    )

    # RACE 1 - a seat offer issued from the pre-offer view of the room. w3 owns
    # no availability window at all, so the same payload also fails containment
    # at step 18; the answer is the stale-version code because concurrency is
    # step 13.
    stale_offer = F.build_seat_offer(
        world["w3_id"],
        rv1,
        level_at_hire="STAFF_WRITER",
        offered_weekly_compensation_cents=STAFF_WRITER_FLOOR,
        exclusivity="NON_EXCLUSIVE",
        episodic_guarantee_count=0,
    )
    _assert_error_envelope(
        api.offer_seat(room_id, stale_offer, world["sr_headers"]),
        ApiErrorId.STALE_ROOM_VERSION,
        412,
    )

    # RACE 2 - a reconfiguration carrying the same superseded token.
    _assert_error_envelope(
        api.reconfigure_room(
            room_id, F.build_reconfigure(rv1), STUDIO_EXECUTIVE_HEADERS
        ),
        ApiErrorId.STALE_ROOM_VERSION,
        412,
    )

    # Neither refusal applied a side effect, so neither consumed a version and
    # the format the client never saw is still in place.
    room = X.read_room(api, room_id)
    A.assert_field_values(room, format="IN_PERSON", version=rv1 + 1)
    assert _total(api.list_room_seats(STUDIO_EXECUTIVE_HEADERS, {"room_id": room_id})) == 1, (
        "the refused offer must not have created a seat"
    )

    # The retry at the version the room actually holds is admitted. Only s1 is
    # OFFERED, so the subtotal is 0 and the burn is the REMOTE surcharge alone.
    rv26 = room["version"]
    reconfigured = validate_success(
        api.reconfigure_room(
            room_id, F.build_reconfigure(rv26), STUDIO_EXECUTIVE_HEADERS
        )
    )
    A.assert_field_values(
        reconfigured, format="REMOTE", status="STAFFING", version=rv26 + 1
    )
    A.assert_room_burn(
        reconfigured,
        0,
        K.FACILITY_TIER_1,
        K.ROOM_BURN_EMPTY_REMOTE,
        K.ROOM_BURN_EMPTY_REMOTE,
    )

    # Acceptance and activation are the fifth and sixth mutations of the room.
    X.accept_seat(api, s1["id"], world["w1_id"])
    activated = X.activate_room(api, room_id)
    A.assert_field_values(
        activated, status="ACTIVE", version=ROOM_VERSION_AFTER_ACTIVATION
    )

    episode = X.seed_episode(api, season_id, 1)
    episode_id = episode["id"]
    ev1 = episode["version"]
    A.assert_field_values(episode, version=1, script_readiness="NOT_STARTED")

    a1 = X.seed_assignment(
        api,
        episode_id,
        world["w1_id"],
        world["sr_headers"],
        assignment_type="TELEPLAY",
        expected_episode_version=ev1,
    )
    A.assert_field_values(X.read_episode(api, episode_id), version=ev1 + 1)

    # RACE 3 - a second create from the episode view the first create superseded.
    _assert_error_envelope(
        api.create_script_assignment(
            episode_id,
            F.build_script_assignment(world["w1_id"], ev1, assignment_type="STORY"),
            world["sr_headers"],
        ),
        ApiErrorId.STALE_EPISODE_VERSION,
        412,
    )
    assert _total(
        api.list_script_assignments(
            STUDIO_EXECUTIVE_HEADERS, {"episode_id": episode_id}
        )
    ) == 1, "the refused create must not have persisted a second assignment"

    # The season token is read after the episode and the assignment have already
    # moved the season's coverage figures.
    sv2 = X.read_season(api, season_id)["version"]
    rescheduled = validate_success(
        api.reschedule_season(
            season_id,
            F.build_reschedule(sv2, new_production_start_date=NEW_PRODUCTION_START),
            STUDIO_EXECUTIVE_HEADERS,
        )
    )
    A.assert_instant(
        rescheduled["production_start_date"],
        NEW_PRODUCTION_START,
        "season production_start_date",
    )
    A.assert_field_values(rescheduled, version=sv2 + 1)

    # The same signed delta reaches the unlocked episode, the assignment's four
    # due-date fields and every milestone due date.
    A.assert_instant(
        X.read_episode(api, episode_id)["production_start_date"],
        NEW_PRODUCTION_START,
        "episode production_start_date",
    )
    shifted = X.read_assignment(api, a1["id"])
    A.assert_field_values(
        shifted,
        outline_due_date=DUE_DATES_NOV_16["OUTLINE"],
        first_draft_due_date=DUE_DATES_NOV_16["FIRST_DRAFT"],
        second_draft_due_date=DUE_DATES_NOV_16["SECOND_DRAFT"],
        polish_due_date=DUE_DATES_NOV_16["POLISH"],
    )
    milestones = X.milestones_of(api, a1["id"])
    assert [row["milestone_type"] for row in milestones] == TELEPLAY_MILESTONE_CHAIN, (
        f"a TELEPLAY carries the three-milestone chain, got "
        f"{[row['milestone_type'] for row in milestones]}"
    )
    for row in milestones:
        A.assert_instant(
            row["due_date"],
            DUE_DATES_NOV_16[row["milestone_type"]],
            f"{row['milestone_type']} due_date",
        )
        assert row["status"] == "PENDING", (
            f"every re-derived deadline is still ahead of the clock: {row['status']}"
        )

    # RACE 4 - the reschedule the accepted one superseded.
    _assert_error_envelope(
        api.reschedule_season(
            season_id,
            F.build_reschedule(
                sv2, new_production_start_date=LATER_PRODUCTION_START
            ),
            STUDIO_EXECUTIVE_HEADERS,
        ),
        ApiErrorId.STALE_SEASON_VERSION,
        412,
    )
    season = X.read_season(api, season_id)
    A.assert_instant(
        season["production_start_date"],
        NEW_PRODUCTION_START,
        "season production_start_date",
    )
    A.assert_field_values(season, version=sv2 + 1)

    # Every successful write in the sequence moved exactly one version, and the
    # reschedule never touched the room.
    A.assert_field_values(
        X.read_room(api, room_id), version=ROOM_VERSION_AFTER_ACTIVATION
    )


def test_the_assignment_takes_the_earliest_confirmed_seat_and_freezes_the_choice(api):
    """A writer confirmed in two ACTIVE rooms of one season is assigned through
    the seat confirmed first, not the newest and not the one with more guarantee
    slots. The choice is frozen at creation: releasing the chosen seat sends the
    existing assignment to REASSIGNMENT_PENDING with its seat reference intact,
    while the next assignment picks the survivor - and once both seats are gone
    the create is refused outright.

    PRD: "The system resolves the assignment's `room_seat_id` by filtering to seats of the named writer whose status is `CONFIRMED` in a writers room belonging to this episode's season whose own status is `ACTIVE`; candidates are ranked by the seat's `confirmed_at` ascending with the seat's `created_at` breaking ties, and the first candidate is stored on the assignment."

    PRD: "There is no freelance path in this system: an empty candidate set is rejected with `ERR_WRITER_NOT_STAFFED`."

    PRD: "Acceptance moves the seat `OFFERED → CONFIRMED` and stamps `confirmed_at` from the logical clock."

    PRD: "The pair collides only when at least one of the two seats is `EXCLUSIVE`; two `NON_EXCLUSIVE` seats may overlap freely."

    PRD: "candidates are ranked by the window's `start_date` ascending, and ties are broken by the window's `created_at` ascending; the first candidate wins"

    PRD: "The winning window moves to `CONSUMED` and records the seat in its `consumed_by_seat_id`, while the seat records the window in its `consumed_window_id`"

    PRD: "An assignment inside the allocated prefix has `guarantee_slot_applied` set true, and its `guarantee_offset_cents` becomes its gross fee multiplied by the agreement's guarantee offset fraction for the level recorded on the seat's `level_at_hire`, rounded half up to whole cents"

    PRD: "every script assignment held through that seat whose status is `DRAFTING`, `DELIVERED` or `IN_NOTES` moves to `REASSIGNMENT_PENDING`; the assignment keeps the seat reference it was created with, so the seat's guarantee counters are unaffected by the release"

    PRD: "the writer's `active_seat_count` drops by one"

    Design: Corner/cross_cutting_complexity_layers/the_seat_selector_ranks_confirmed_seats_by_confirmation_time
    """
    world = X.build_staffing_room_world(api)
    writer_id = world["w1_id"]

    # SEAT A - the earlier confirmation, one guarantee slot, in the IN_PERSON
    # room. Both seats are NON_EXCLUSIVE so their identical intervals may overlap.
    seat_a = X.seed_seat(
        api,
        world["room_id"],
        writer_id,
        world["sr_headers"],
        expected_room_version=world["room_version"],
        exclusivity="NON_EXCLUSIVE",
        episodic_guarantee_count=1,
    )
    seat_a = X.accept_seat(api, seat_a["id"], writer_id)
    A.assert_field_values(
        seat_a,
        status="CONFIRMED",
        episodic_guarantee_count=1,
        guarantee_slots_remaining=1,
        consumed_window_id=world["aw1_id"],
    )
    A.assert_instant(seat_a["confirmed_at"], K.CLOCK_EPOCH, "seat A confirmed_at")
    X.activate_room(api, world["room_id"])

    # SEAT B - a sibling ACTIVE room of the same season, funded by a window that
    # starts later than aw1 so the window selector cannot confuse the two.
    second_room = X.seed_room(
        api, world["season_id"], world["sr_headers"], **SECOND_UNIT_ROOM
    )
    X.open_room(api, second_room["id"], world["sr_headers"])
    window_b = X.seed_window(
        api,
        writer_id,
        "NON_EXCLUSIVE",
        start_date=SECOND_WINDOW_START,
        end_date=K.WINDOW_END_DATE,
    )
    seat_b = X.seed_seat(
        api,
        second_room["id"],
        writer_id,
        world["sr_headers"],
        exclusivity="NON_EXCLUSIVE",
        episodic_guarantee_count=2,
    )
    X.set_clock(api, CLOCK_AUGUST_05)
    seat_b = X.accept_seat(api, seat_b["id"], writer_id)
    A.assert_field_values(
        seat_b,
        status="CONFIRMED",
        episodic_guarantee_count=2,
        guarantee_slots_remaining=2,
        consumed_window_id=window_b["id"],
    )
    A.assert_instant(seat_b["confirmed_at"], CLOCK_AUGUST_05, "seat B confirmed_at")
    X.activate_room(api, second_room["id"])

    # The two-way links stand on both seats at once.
    A.assert_field_values(
        X.read_window(api, world["aw1_id"]),
        status="CONSUMED",
        consumed_by_seat_id=seat_a["id"],
    )
    A.assert_field_values(
        X.read_window(api, window_b["id"]),
        status="CONSUMED",
        consumed_by_seat_id=seat_b["id"],
    )
    A.assert_field_values(X.read_writer(api, writer_id), active_seat_count=2)

    episode = X.seed_episode(api, world["season_id"], 1)
    episode_id = episode["id"]

    # The earliest confirmed_at wins over the seat carrying more guarantee slots.
    a14 = X.seed_assignment(
        api,
        episode_id,
        writer_id,
        world["sr_headers"],
        assignment_type="TELEPLAY",
        expected_episode_version=episode["version"],
    )
    assert a14["room_seat_id"] == seat_a["id"], (
        "the selector must take the seat confirmed on 2026-08-01, not the seat "
        "confirmed on 2026-08-05 with two guarantee slots"
    )
    A.assert_assignment_settlement(
        a14,
        K.SCRIPT_FEE_ONE_HOUR["TELEPLAY"],
        True,
        TELEPLAY_OFFSET_ONE_HOUR,
        TELEPLAY_PAYABLE_ONE_HOUR,
    )
    A.assert_field_values(
        X.read_seat(api, seat_a["id"]),
        guarantee_slots_consumed=1,
        guarantee_slots_remaining=0,
    )
    A.assert_field_values(
        X.read_seat(api, seat_b["id"]),
        guarantee_slots_consumed=0,
        guarantee_slots_remaining=2,
    )

    # Releasing the chosen seat does not re-run the selector.
    validate_success(
        api.release_seat(
            seat_a["id"], STUDIO_EXECUTIVE_HEADERS, dict(RELEASE_ROOM_FOLDED)
        )
    )
    A.assert_field_values(
        X.read_assignment(api, a14["id"]),
        status="REASSIGNMENT_PENDING",
        room_seat_id=seat_a["id"],
    )
    # The released seat keeps the counters the settlement gave it.
    A.assert_field_values(
        X.read_seat(api, seat_a["id"]),
        status="RELEASED",
        guarantee_slots_consumed=1,
        guarantee_slots_remaining=0,
    )
    A.assert_field_values(X.read_writer(api, writer_id), active_seat_count=1)

    # The next create sees a candidate set of one.
    a15 = X.seed_assignment(
        api,
        episode_id,
        writer_id,
        world["sr_headers"],
        assignment_type="STORY",
        expected_episode_version=X.current_episode_version(api, episode_id),
    )
    assert a15["room_seat_id"] == seat_b["id"], (
        "the surviving seat is the only candidate left"
    )
    A.assert_assignment_settlement(
        a15,
        K.SCRIPT_FEE_ONE_HOUR["STORY"],
        True,
        STORY_OFFSET_ONE_HOUR,
        STORY_PAYABLE_ONE_HOUR,
    )
    A.assert_field_values(
        X.read_seat(api, seat_b["id"]),
        guarantee_slots_consumed=1,
        guarantee_slots_remaining=1,
    )

    # With both seats released the candidate set is empty, which is a business
    # refusal - 409 per the error table - and not a null room_seat_id.
    validate_success(
        api.release_seat(
            seat_b["id"], STUDIO_EXECUTIVE_HEADERS, dict(RELEASE_WRITER_LEFT)
        )
    )
    A.assert_field_values(X.read_writer(api, writer_id), active_seat_count=0)
    A.assert_field_values(
        X.read_assignment(api, a15["id"]),
        status="REASSIGNMENT_PENDING",
        room_seat_id=seat_b["id"],
    )
    _assert_error_envelope(
        api.create_script_assignment(
            episode_id,
            F.build_script_assignment(
                writer_id,
                X.current_episode_version(api, episode_id),
                assignment_type="STORY_AND_TELEPLAY",
            ),
            world["sr_headers"],
        ),
        ApiErrorId.WRITER_NOT_STAFFED,
        409,
    )
    assert _total(
        api.list_script_assignments(
            STUDIO_EXECUTIVE_HEADERS, {"episode_id": episode_id}
        )
    ) == 2, "the refused create must not have persisted a third assignment"
