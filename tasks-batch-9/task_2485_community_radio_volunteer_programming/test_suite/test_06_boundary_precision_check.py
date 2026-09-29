"""Thresholds tested at the exact value, one step short and one step over.

A seniority margin of exactly 5.00 points takes a window that a margin of 4.00
cannot, and a public-affairs share of exactly 8.00 percent publishes a grid that
7.69 percent cannot. Both boundaries are inclusive, and both are reached with
figures the PRD spells out.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import (
    DIRECTOR_HEADERS,
    api_client,
    assertions,
    factories,
    fixtures,
)

CLOCK = "2026-08-01T00:00:00Z"

ADA_SCORES = {"BOARD_OPERATION": 88, "STATION_POLICY": 90, "BROADCAST_REGULATION": 91}
FAY_SCORES = {"BOARD_OPERATION": 85, "STATION_POLICY": 86, "BROADCAST_REGULATION": 87}
EVE_SCORES = {"BOARD_OPERATION": 92, "STATION_POLICY": 93, "BROADCAST_REGULATION": 94}


def _three_hosts_contending_for_one_window():
    """Three certified hosts whose seniority scores are 54.00, 58.00 and 59.00,
    with the least senior holding the contested Monday evening window."""
    fixtures.set_clock(CLOCK)
    ada = fixtures.create_certified_host(
        legal_name="Ada Reyes",
        email="ada@krcr.example",
        seniority_start_date="2024-08-01",
        scores=ADA_SCORES,
    )
    fay = fixtures.create_certified_host(
        legal_name="Fay Ortiz",
        email="fay@krcr.example",
        seniority_start_date="2024-04-01",
        scores=FAY_SCORES,
    )
    eve = fixtures.create_certified_host(
        legal_name="Eve Sandoval",
        email="eve@krcr.example",
        seniority_start_date="2024-03-01",
        scores=EVE_SCORES,
    )
    members = fixtures.create_committee_members(count=3)

    ada_program = fixtures.create_approved_program(
        ada["id"], members, title="Delta Sessions", format_code="MUSIC",
        language_code="EN", requested_daypart="EVENING", requested_duration_minutes=120,
    )
    fay_program = fixtures.create_approved_program(
        fay["id"], members, title="Border Radio", format_code="MUSIC",
        language_code="ES", requested_daypart="EVENING", requested_duration_minutes=120,
    )
    eve_program = fixtures.create_approved_program(
        eve["id"], members, title="Night Ledger", format_code="MUSIC",
        language_code="EN", requested_daypart="EVENING", requested_duration_minutes=120,
    )

    grid = fixtures.create_grid()
    incumbent = fixtures.add_slot(
        grid["id"], ada_program["program_id"], day_of_week=1, start_minute=1200,
        duration_minutes=120,
    )
    fixtures.confirm_slot(incumbent["id"])
    return {
        "ada_id": ada["id"],
        "fay_id": fay["id"],
        "eve_id": eve["id"],
        "ada_program_id": ada_program["program_id"],
        "fay_program_id": fay_program["program_id"],
        "eve_program_id": eve_program["program_id"],
        "grid_id": grid["id"],
        "incumbent_slot_id": incumbent["id"],
    }


def _read_seniority(volunteer_id):
    return validate_success(api_client.get_volunteer(volunteer_id, DIRECTOR_HEADERS), 200)[
        "seniority_score"
    ]


def _grid_just_short_of_the_quota():
    """An in-review grid carrying 60 public-affairs minutes inside 780 assigned
    minutes, which is 7.69 percent."""
    base = fixtures.station()
    news = fixtures.create_approved_program(
        base["host_id"], base["members"], title="County Report", format_code="NEWS",
        requested_daypart="MORNING_DRIVE", requested_duration_minutes=30,
    )
    music = fixtures.create_approved_program(
        base["host_id"], base["members"], title="Delta Sessions", format_code="MUSIC",
        requested_daypart="OVERNIGHT", requested_duration_minutes=720,
    )
    grid = fixtures.create_grid()
    first_news = fixtures.add_slot(
        grid["id"], news["program_id"], day_of_week=2, start_minute=420, duration_minutes=30
    )
    second_news = fixtures.add_slot(
        grid["id"], news["program_id"], day_of_week=3, start_minute=420, duration_minutes=30
    )
    long_music = fixtures.add_slot(
        grid["id"], music["program_id"], day_of_week=1, start_minute=0, duration_minutes=720
    )
    for slot_id in (first_news["id"], second_news["id"], long_music["id"]):
        fixtures.confirm_slot(slot_id)
    return {
        "grid_id": grid["id"],
        "news_program_id": news["program_id"],
        "music_program_id": music["program_id"],
        "long_music_slot_id": long_music["id"],
    }


class TestSeniorityPreemptMargin:
    def test_a_margin_of_four_points_cannot_take_the_window(self):
        """Fay outranks Ada by 4.00 points, which is not enough.

        "The challenger's host must outrank the incumbent's host by a margin of
        at least `5.00` seniority points, measured as the challenger host's
        `seniority_score` minus the incumbent host's `seniority_score`; a smaller
        margin is refused with `ERR_SENIORITY_MARGIN_UNMET`." The scores follow
        from the PRD's own worked figure: "A volunteer with all three core
        certifications, twenty-four whole months of service, no strikes and no
        hosted shows therefore scores exactly `54.00`".

        Design: Difficulty/boundary_precision_check/seniority_preempt_margin_of_exactly_five_points_takes_the_window
        """
        setup = _three_hosts_contending_for_one_window()

        assertions.assert_two_decimals_equal(
            _read_seniority(setup["ada_id"]), 54.00, "seniority_score"
        )
        assertions.assert_two_decimals_equal(
            _read_seniority(setup["fay_id"]), 58.00, "seniority_score"
        )
        assertions.assert_two_decimals_equal(
            _read_seniority(setup["eve_id"]), 59.00, "seniority_score"
        )

        version_before = fixtures.grid_version(setup["grid_id"])
        response = api_client.create_slot_assignment(
            setup["grid_id"],
            factories.create_slot_assignment_payload(
                setup["fay_program_id"],
                version_before,
                day_of_week=1,
                start_minute=1200,
                duration_minutes=120,
                conflict_policy="SENIORITY_PREEMPT",
            ),
            DIRECTOR_HEADERS,
        )
        validate_error(response, "ERR_SENIORITY_MARGIN_UNMET", 409)

        assert fixtures.read_slot(setup["incumbent_slot_id"])["status"] == "CONFIRMED"
        grid = fixtures.read_grid(setup["grid_id"])
        assert grid["version"] == version_before
        assert grid["total_assigned_minutes"] == 120

    def test_a_margin_of_exactly_five_points_takes_the_window(self):
        """Eve outranks Ada by exactly 5.00 points, which is enough.

        "When the margin is met, the incumbent occupation moves from `TENTATIVE`
        or `CONFIRMED` to `PREEMPTED`, its `preempted_by_program_id` is set to the
        challenging show, the grid's derived minute figures are recomputed and the
        grid's `version` advances — and the challenger's own occupation is created
        on `TENTATIVE` as usual."

        Design: Difficulty/boundary_precision_check/seniority_preempt_margin_of_exactly_five_points_takes_the_window
        """
        setup = _three_hosts_contending_for_one_window()

        response = api_client.create_slot_assignment(
            setup["grid_id"],
            factories.create_slot_assignment_payload(
                setup["eve_program_id"],
                fixtures.grid_version(setup["grid_id"]),
                day_of_week=1,
                start_minute=1200,
                duration_minutes=120,
                conflict_policy="SENIORITY_PREEMPT",
            ),
            DIRECTOR_HEADERS,
        )
        challenger = validate_success(response, 201)
        assert challenger["status"] == "TENTATIVE"

        incumbent = fixtures.read_slot(setup["incumbent_slot_id"])
        assert incumbent["status"] == "PREEMPTED"
        assert incumbent["preempted_by_program_id"] == setup["eve_program_id"]

        grid = fixtures.read_grid(setup["grid_id"])
        assert grid["total_assigned_minutes"] == 120
        assertions.assert_two_decimals_equal(
            grid["public_affairs_minutes_pct"], 0.00, "public_affairs_minutes_pct"
        )

        _, meta = validate_paginated(
            api_client.list_slot_assignments(
                DIRECTOR_HEADERS,
                params={"grid_id": setup["grid_id"], "status": "PREEMPTED"},
            )
        )
        assert meta["total_count"] == 1


class TestPublicAffairsQuotaBoundary:
    def test_a_share_of_seven_point_six_nine_percent_cannot_publish(self):
        """Sixty public-affairs minutes inside 780 is short of the floor.

        "Sixty public-affairs minutes inside 750 assigned minutes is therefore
        exactly `8.00`; the same sixty minutes inside 780 assigned minutes is
        `7.69`." Publication requires that "the grid's
        `public_affairs_minutes_pct` must be at least `8.00`, or the answer is
        `ERR_DIVERSITY_QUOTA_UNMET`".

        Design: Difficulty/boundary_precision_check/grid_public_affairs_share_of_exactly_eight_percent_publishes
        """
        setup = _grid_just_short_of_the_quota()

        before = fixtures.read_grid(setup["grid_id"])
        assert before["total_assigned_minutes"] == 780
        assertions.assert_two_decimals_equal(
            before["public_affairs_minutes_pct"], 7.69, "public_affairs_minutes_pct"
        )

        response = api_client.publish_schedule_grid(
            setup["grid_id"],
            factories.publish_grid_payload(before["version"]),
            DIRECTOR_HEADERS,
        )
        validate_error(response, "ERR_DIVERSITY_QUOTA_UNMET", 422)

        assert fixtures.read_grid(setup["grid_id"])["status"] == "IN_REVIEW"

    def test_a_share_of_exactly_eight_percent_publishes(self):
        """Trimming the music hour to 690 minutes lands the share on 8.00.

        "because releases shrink the denominator, releasing a music occupation
        raises the public-affairs share without any public-affairs occupation
        being added." At 750 assigned minutes the share is exactly `8.00`, the
        inclusive floor, and "A successful publication stamps `published_at` with
        the clock" while "Every show holding a `CONFIRMED` occupation on the newly
        published grid moves `SCHEDULED → ON_AIR_ACTIVE`".

        Design: Difficulty/boundary_precision_check/grid_public_affairs_share_of_exactly_eight_percent_publishes
        """
        setup = _grid_just_short_of_the_quota()

        validate_success(
            api_client.release_slot_assignment(
                setup["long_music_slot_id"],
                factories.release_slot_payload(
                    release_reason="Trimmed to make room for the public-affairs quota."
                ),
                DIRECTOR_HEADERS,
            ),
            200,
        )
        trimmed = fixtures.add_slot(
            setup["grid_id"],
            setup["music_program_id"],
            day_of_week=1,
            start_minute=0,
            duration_minutes=690,
        )
        fixtures.confirm_slot(trimmed["id"])

        ready = fixtures.read_grid(setup["grid_id"])
        assert ready["total_assigned_minutes"] == 750
        assertions.assert_two_decimals_equal(
            ready["public_affairs_minutes_pct"], 8.00, "public_affairs_minutes_pct"
        )

        published = validate_success(
            api_client.publish_schedule_grid(
                setup["grid_id"],
                factories.publish_grid_payload(ready["version"]),
                DIRECTOR_HEADERS,
            ),
            200,
        )
        assert published["status"] == "PUBLISHED"
        assertions.assert_instant_equals(published["published_at"], CLOCK, "published_at")

        assert (
            fixtures.read_program(setup["music_program_id"])["programming_status"]
            == "ON_AIR_ACTIVE"
        )
        assert (
            fixtures.read_program(setup["news_program_id"])["programming_status"]
            == "ON_AIR_ACTIVE"
        )
        assert fixtures.read_slot(setup["long_music_slot_id"])["status"] == "RELEASED"
        assert fixtures.read_slot(trimmed["id"])["status"] == "CONFIRMED"

        _, meta = validate_paginated(
            api_client.list_schedule_grids(DIRECTOR_HEADERS, params={"status": "PUBLISHED"})
        )
        assert meta["total_count"] == 1
