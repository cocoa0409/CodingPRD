"""Rights clearance precedence, the ISO-week first-run ceiling and allowance restore.

The canonical licence carries `max_screenings` 6 over the venue-local window
2026-08-10 through 2026-08-20, and the auditorium caps first-run programming at
a 0.60 share of each ISO week.
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_clearance,
    assert_screening_allowance_conserved,
    assert_showtime,
    cancel_showtime,
    clearance_version,
    lodge_licence,
    place_showtime,
    read_booking,
    read_clearance,
    read_showtime,
    setup_programming_baseline,
    setup_scheduled_screening,
    showtime_payload,
    validate_error,
    validate_paginated,
)

FIRST_RUN_TITLE = {
    "title_name": "Nouvelle Vague Now",
    "release_year": 2026,
    "is_first_run": True,
}


def _candidate_payload(world, clearance_id, start_at, expected_version, **overrides):
    return showtime_payload(
        world["venue"]["id"],
        world["title"]["id"],
        world["booking"]["id"],
        clearance_id,
        world["asset"]["id"],
        start_at,
        expected_version,
        **overrides,
    )


class TestRightsStateOutranksScreenCollision:
    """Rung 7 fires before rung 14, so a licensing failure hides the collision."""

    def test_unlicensed_and_colliding_screening_reports_the_licensing_failure(
        self, programmer_headers
    ):
        """A submitted licence plus an occupied screen yields the rights error.

        PRD: "Because rights state (7), licence window (8) and allowance (9) all outrank screen collision (14), a screening request that is both unlicensed and colliding is reported as a licensing failure, not a scheduling one."

        Design: Difficulty/priority_pair_validation_conflict/clearance_not_cleared_outranks_screen_slot_conflict
        """
        world = setup_scheduled_screening("2026-08-14T12:00:00Z")
        second_licence = lodge_licence(
            world["title"]["id"],
            world["booking"]["id"],
            licensor_name="Fondation Marker",
        )
        assert second_licence["status"] == "SUBMITTED"

        response = api_client.create_showtime(
            _candidate_payload(
                world,
                second_licence["id"],
                "2026-08-14T12:30:00Z",
                second_licence["version"],
            ),
            programmer_headers,
        )

        validate_error(response, ApiErrorId.ERR_CLEARANCE_NOT_CLEARED)

    def test_refused_screening_leaves_the_submitted_licence_and_calendar_untouched(
        self, programmer_headers
    ):
        """No later rung ran, so nothing at all was drawn down.

        PRD: "Checks are evaluated in one strictly ascending order, and **the first violated check wins**: once a rule fails, the request is rejected with that rule's error and no later rule is evaluated."

        Design: Difficulty/priority_pair_validation_conflict/clearance_not_cleared_outranks_screen_slot_conflict
        """
        world = setup_scheduled_screening("2026-08-14T12:00:00Z")
        second_licence = lodge_licence(
            world["title"]["id"],
            world["booking"]["id"],
            licensor_name="Fondation Marker",
        )

        validate_error(
            api_client.create_showtime(
                _candidate_payload(
                    world,
                    second_licence["id"],
                    "2026-08-14T12:30:00Z",
                    second_licence["version"],
                ),
                programmer_headers,
            ),
            ApiErrorId.ERR_CLEARANCE_NOT_CLEARED,
        )

        refused = read_clearance(second_licence["id"])
        assert refused["status"] == "SUBMITTED", "the refusal did not advance the licence"
        assert refused["screenings_used"] == 0
        assert refused["screenings_remaining"] == 6
        assert_clearance(refused)

        rows, meta = validate_paginated(
            api_client.list_showtimes(
                programmer_headers, {"venue_id": world["venue"]["id"]}
            )
        )
        assert meta["total_count"] == 1, "only the originally placed screening exists"
        assert len(rows) == 1

        held = read_showtime(world["showtime"]["id"])
        assert held["blocked_until"] == "2026-08-14T14:21:00.000Z"


class TestWeeklyFirstRunCeiling:
    """ceil(total x 0.60) admits two of two and refuses the third of three."""

    def test_two_first_run_screenings_out_of_two_sit_exactly_on_the_ceiling(self):
        """Both Tuesday and Wednesday first-run screenings are admitted.

        PRD: "The ceiling is applied to the product, never to the share, which makes the boundary directly observable: at a share of 0.60, one first-run screening out of one is admitted, two out of two are admitted, and the third first-run screening in a week of three is refused."

        Design: Difficulty/boundary_precision_check/weekly_first_run_share_ceiling_at_exact_boundary
        """
        world = setup_programming_baseline(title_overrides=dict(FIRST_RUN_TITLE))

        first = place_showtime(world, "2026-08-11T19:00:00Z", strand="FIRST_RUN")
        second = place_showtime(world, "2026-08-12T19:00:00Z", strand="FIRST_RUN")

        assert_showtime(first)
        assert_showtime(second)
        assert first["strand"] == "FIRST_RUN"
        assert second["strand"] == "FIRST_RUN"
        assert first["start_at"] == "2026-08-11T19:00:00.000Z"
        assert second["start_at"] == "2026-08-12T19:00:00.000Z"

    def test_third_first_run_screening_in_a_week_of_three_is_refused(
        self, programmer_headers
    ):
        """A prospective first-run count of 3 beats a ceiling of 2.

        PRD: "Concretely, when a candidate screening is evaluated, the service counts the venue's existing screenings in that ISO week whose status is not cancelled, adds one for the candidate to obtain the prospective total, counts how many of those existing screenings carry the `FIRST_RUN` strand and adds one more if the candidate itself is `FIRST_RUN`, and rejects the candidate with `ERR_WEEKLY_BALANCE_EXCEEDED` when the prospective first-run count is strictly greater than the prospective total multiplied by `max_first_run_share` and then rounded **up** to a whole number."

        Design: Difficulty/boundary_precision_check/weekly_first_run_share_ceiling_at_exact_boundary
        """
        world = setup_programming_baseline(title_overrides=dict(FIRST_RUN_TITLE))
        place_showtime(world, "2026-08-11T19:00:00Z", strand="FIRST_RUN")
        place_showtime(world, "2026-08-12T19:00:00Z", strand="FIRST_RUN")

        response = api_client.create_showtime(
            _candidate_payload(
                world,
                world["clearance"]["id"],
                "2026-08-13T19:00:00Z",
                clearance_version(world["clearance"]["id"]),
                strand="FIRST_RUN",
            ),
            programmer_headers,
        )

        validate_error(response, ApiErrorId.ERR_WEEKLY_BALANCE_EXCEEDED)

    def test_refused_first_run_candidate_leaves_allowance_and_version_alone(
        self, programmer_headers
    ):
        """The week keeps two screenings and the licence keeps its version.

        PRD: "The programming week is the ISO week: the venue-local span running from Monday at `00:00:00.000` through Sunday at `23:59:59.999` that contains the screening's start."

        Design: Difficulty/boundary_precision_check/weekly_first_run_share_ceiling_at_exact_boundary
        """
        world = setup_programming_baseline(title_overrides=dict(FIRST_RUN_TITLE))
        place_showtime(world, "2026-08-11T19:00:00Z", strand="FIRST_RUN")
        place_showtime(world, "2026-08-12T19:00:00Z", strand="FIRST_RUN")
        version_before = clearance_version(world["clearance"]["id"])

        validate_error(
            api_client.create_showtime(
                _candidate_payload(
                    world,
                    world["clearance"]["id"],
                    "2026-08-13T19:00:00Z",
                    version_before,
                    strand="FIRST_RUN",
                ),
                programmer_headers,
            ),
            ApiErrorId.ERR_WEEKLY_BALANCE_EXCEEDED,
        )

        rows, meta = validate_paginated(
            api_client.list_showtimes(
                programmer_headers, {"venue_id": world["venue"]["id"]}
            )
        )
        assert meta["total_count"] == 2
        assert len(rows) == 2

        clearance = read_clearance(world["clearance"]["id"])
        assert clearance["screenings_used"] == 2
        assert clearance["screenings_remaining"] == 4
        assert clearance["version"] == version_before, (
            "a rejected candidate draws nothing down"
        )


def _three_screenings_on_one_licence():
    """Three scheduled screenings on consecutive venue-local dates, one licence."""
    world = setup_programming_baseline()
    first = place_showtime(world, "2026-08-14T12:00:00Z")
    second = place_showtime(world, "2026-08-15T12:00:00Z")
    world["version_before_third"] = clearance_version(world["clearance"]["id"])
    third = place_showtime(world, "2026-08-16T12:00:00Z")
    world["showtimes"] = [first, second, third]
    return world


class TestAllowanceRestoredByCancellation:
    """A cancelled screening hands its allowance back and the identity holds."""

    def test_cancelling_one_screening_returns_its_allowance_to_the_licence(self):
        """Three used becomes two used and four remaining, still summing to six.

        PRD: "The licence gets its allowance back — `screenings_used` falls by one, `screenings_remaining` rises by one, and the licence's `version` increments — and the engagement's `scheduled_showtime_count` falls by one."

        Design: Difficulty/compensating_invariant/clearance_screening_allowance_restored_by_cancel
        """
        world = _three_screenings_on_one_licence()
        before = read_clearance(world["clearance"]["id"])
        assert before["screenings_used"] == 3
        assert before["screenings_remaining"] == 3
        assert_screening_allowance_conserved(before)

        cancel_showtime(world["showtimes"][1]["id"], cancel_reason="PRINT_UNAVAILABLE")

        after = read_clearance(world["clearance"]["id"])
        assert after["screenings_used"] == 2
        assert after["screenings_remaining"] == 4
        assert_screening_allowance_conserved(after)
        assert after["version"] > world["version_before_third"], (
            "the restore increments the licence version"
        )

        booking = read_booking(world["booking"]["id"])
        assert booking["scheduled_showtime_count"] == 2

    def test_cancelled_screening_closes_its_sales_and_spares_its_siblings(self):
        """Only the addressed screening moves; the other two stay scheduled.

        PRD: "It moves the screening `SCHEDULED → CANCELLED`, frees its screen block for other programming, and forces `sale_status` to `SALES_CLOSED`."

        Design: Difficulty/compensating_invariant/clearance_screening_allowance_restored_by_cancel
        """
        world = _three_screenings_on_one_licence()

        cancelled = cancel_showtime(
            world["showtimes"][1]["id"], cancel_reason="PRINT_UNAVAILABLE"
        )

        assert cancelled["status"] == "CANCELLED"
        assert cancelled["sale_status"] == "SALES_CLOSED"
        assert cancelled["cancel_reason"] == "PRINT_UNAVAILABLE"

        survivor_one = read_showtime(world["showtimes"][0]["id"])
        survivor_three = read_showtime(world["showtimes"][2]["id"])
        assert survivor_one["status"] == "SCHEDULED"
        assert survivor_three["status"] == "SCHEDULED"
        assert survivor_one["sale_status"] == "DRAFT"
        assert survivor_three["sale_status"] == "DRAFT"
