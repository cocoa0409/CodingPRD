"""Screen occupancy geometry and the optimiser's slot ranking.

Every screening in this file stands on the canonical twelve-seat house whose
trailer reel is 12 minutes and whose turnaround buffer is 25 minutes, so a
104-minute title runs 116 minutes on screen and occupies the screen for 141.
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_screen_block,
    assert_screening_allowance_conserved,
    assert_showtime,
    auto_place_showtime,
    clearance_version,
    place_showtime,
    read_clearance,
    read_showtime,
    setup_programming_baseline,
    setup_scheduled_screening,
    showtime_payload,
    validate_error,
    validate_paginated,
)

FIRST_START = "2026-08-14T12:00:00Z"
FIRST_END = "2026-08-14T13:56:00.000Z"
FIRST_BLOCKED_UNTIL = "2026-08-14T14:21:00.000Z"


def _candidate_payload(world, start_at):
    """Build a hand-placement payload against the world's cleared licence."""
    return showtime_payload(
        world["venue"]["id"],
        world["title"]["id"],
        world["booking"]["id"],
        world["clearance"]["id"],
        world["asset"]["id"],
        start_at,
        clearance_version(world["clearance"]["id"]),
    )


class TestHalfOpenScreenOccupancy:
    """The reset buffer is appended to the tail only, so blocks may touch."""

    def test_screening_block_is_computed_from_the_reel_runtime_and_turnaround(self):
        """A hand-placed screening's own block is derived, never supplied.

        PRD: "`end_at` is `start_at` advanced by that total number of minutes, and `blocked_until` is `end_at` advanced by the auditorium's `turnaround_minutes`."

        Design: Difficulty/resource_temporal_overlap/screen_occupancy_half_open_so_next_show_may_start_exactly_at_blocked_until
        """
        world = setup_scheduled_screening(FIRST_START)
        first = world["showtime"]

        assert_showtime(first)
        assert first["start_at"] == "2026-08-14T12:00:00.000Z"
        assert_screen_block(first, FIRST_END, FIRST_BLOCKED_UNTIL)

    def test_next_show_starting_exactly_at_blocked_until_is_admitted(self):
        """Back-to-back programming at the buffer's edge is legal.

        PRD: "A screening occupies the screen from its `start_at` up to but not including its `blocked_until`."

        Design: Difficulty/resource_temporal_overlap/screen_occupancy_half_open_so_next_show_may_start_exactly_at_blocked_until
        """
        world = setup_scheduled_screening(FIRST_START)
        assert_screen_block(world["showtime"], FIRST_END, FIRST_BLOCKED_UNTIL)

        second = place_showtime(world, "2026-08-14T14:21:00Z")

        assert_showtime(second)
        assert second["start_at"] == "2026-08-14T14:21:00.000Z"
        assert_screen_block(
            second, "2026-08-14T16:17:00.000Z", "2026-08-14T16:42:00.000Z"
        )
        assert second["status"] == "SCHEDULED"

    def test_next_show_starting_one_minute_before_blocked_until_collides(
        self, programmer_headers
    ):
        """One minute inside the buffer is a strict overlap and is refused.

        PRD: "Two screenings therefore collide when the candidate's start is strictly before the other's `blocked_until` **and** the other's start is strictly before the candidate's `blocked_until`; a candidate whose `start_at` falls exactly on an existing screening's `blocked_until` is legal, back-to-back programming."

        Design: Difficulty/resource_temporal_overlap/screen_occupancy_half_open_so_next_show_may_start_exactly_at_blocked_until
        """
        world = setup_scheduled_screening(FIRST_START)

        response = api_client.create_showtime(
            _candidate_payload(world, "2026-08-14T14:20:00Z"), programmer_headers
        )

        validate_error(response, ApiErrorId.ERR_SCREEN_SLOT_CONFLICT)

    def test_touching_pair_draws_down_two_screenings_and_the_refusal_draws_none(
        self, programmer_headers
    ):
        """The admitted pair persists; the colliding candidate leaves no trace.

        PRD: "A clearance's `screenings_used` is the count of screenings referencing it whose status is scheduled or completed, and `screenings_remaining` is `max_screenings` less `screenings_used`, never negative; a cancelled screening releases its allowance."

        Design: Difficulty/resource_temporal_overlap/screen_occupancy_half_open_so_next_show_may_start_exactly_at_blocked_until
        """
        world = setup_scheduled_screening(FIRST_START)
        place_showtime(world, "2026-08-14T14:21:00Z")

        validate_error(
            api_client.create_showtime(
                _candidate_payload(world, "2026-08-14T14:20:00Z"), programmer_headers
            ),
            ApiErrorId.ERR_SCREEN_SLOT_CONFLICT,
        )

        rows, meta = validate_paginated(
            api_client.list_showtimes(
                programmer_headers, {"venue_id": world["venue"]["id"]}
            )
        )
        assert meta["total_count"] == 2, "only the two admitted screenings exist"
        assert len(rows) == 2

        clearance = read_clearance(world["clearance"]["id"])
        assert clearance["screenings_used"] == 2
        assert clearance["screenings_remaining"] == 4
        assert_screening_allowance_conserved(clearance)

        first = read_showtime(world["showtime"]["id"])
        assert first["blocked_until"] == FIRST_BLOCKED_UNTIL


class TestOptimiserSlotRanking:
    """Four scoring components decide the slot, and the earliest slot breaks ties."""

    def test_optimiser_places_the_screening_at_the_first_prime_time_slot(self):
        """On an empty day the 18:00 grid instant is the earliest top scorer.

        PRD: "The highest score wins; where two slots tie, the earlier `start_at` wins, and since grid instants are unique that tie-break always resolves."

        Design: Difficulty/combinatorial_formula/slot_ranking_multi_factor_score_with_capped_spacing
        """
        world = setup_programming_baseline()

        showtime = auto_place_showtime(world, "2026-08-14", "11:00", "19:00")

        assert_showtime(showtime)
        assert showtime["start_at"] == "2026-08-14T18:00:00.000Z"
        assert_screen_block(
            showtime, "2026-08-14T19:56:00.000Z", "2026-08-14T20:21:00.000Z"
        )

    def test_optimiser_score_sums_prime_time_capped_spacing_and_strand_bonus(self):
        """Prime 60 plus twice-capped spacing 24 plus the strand bonus 10 is 94.

        PRD: "Each gap is divided by 15 discarding any remainder, the quotient is doubled, and the result is capped at 12; the two capped values are added together."

        Design: Difficulty/combinatorial_formula/slot_ranking_multi_factor_score_with_capped_spacing
        """
        world = setup_programming_baseline()

        showtime = auto_place_showtime(world, "2026-08-14", "11:00", "19:00")

        assert showtime["slot_score"] == 94, (
            "60 prime + 12 + 12 capped spacing + 10 strand bonus, no fragmentation"
        )
        assert showtime["strand"] == "REPERTORY_SERIES"

    def test_optimiser_placement_draws_down_the_licence_like_a_hand_placement(self):
        """The optimised screening is born fresh in all three dimensions.

        PRD: "The winning slot is then created exactly as a hand-placed screening would be, drawing down the licence allowance and incrementing the licence's `version` in the same way."

        Design: Difficulty/combinatorial_formula/slot_ranking_multi_factor_score_with_capped_spacing
        """
        world = setup_programming_baseline()
        version_before = clearance_version(world["clearance"]["id"])

        showtime = auto_place_showtime(world, "2026-08-14", "11:00", "19:00")

        assert showtime["status"] == "SCHEDULED"
        assert showtime["sale_status"] == "DRAFT"
        assert showtime["playback_status"] == "UNVERIFIED"
        assert showtime["seats_sold"] == 0
        assert showtime["surcharge_cents"] == 0

        clearance = read_clearance(world["clearance"]["id"])
        assert clearance["screenings_used"] == 1
        assert clearance["screenings_remaining"] == 5
        assert_screening_allowance_conserved(clearance)
        assert clearance["version"] > version_before, (
            "every draw-down increments the licence version"
        )
