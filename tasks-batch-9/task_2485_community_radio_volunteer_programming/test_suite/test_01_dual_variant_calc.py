"""Two calculations that each carry two variants, priced over identical facts.

The royalty pair prices one playlist under SURVEY and under CENSUS; the
performance pair scores one airing history under TRAILING_SIX and under
QUARTER_TO_DATE. In both pairs the inputs never change between the variants, so
any divergence in the answer is the variant's own arithmetic.
"""

from prd_bench_local_runner.testing import validate_success
from test_helpers import DIRECTOR_HEADERS, api_client, assertions, factories, fixtures

REVIEW_CLOCK = "2026-02-20T12:00:00Z"

SPRING_SEASON = "2026-SPRING"
WINTER_SEASON = "2026-WINTER"
EARLY_FROM = "2026-01-05T00:00:00Z"
EARLY_TO = "2026-06-28T23:59:00Z"

MUSIC_EPISODE_START = "2026-01-05T20:00:00Z"

# Three library spins, every one of them at least 30 seconds long and on a
# featured play source, so all three are priced. Two are local acts.
FEATURED_PLAYLIST = [
    {
        "artist": "Riverbend Quartet",
        "title": "Low Water",
        "duration_seconds": 185,
        "play_source": "LIBRARY_CD",
        "is_local_artist": True,
    },
    {
        "artist": "Nine Mile Choir",
        "title": "Levee Song",
        "duration_seconds": 212,
        "play_source": "DIGITAL",
        "is_local_artist": True,
    },
    {
        "artist": "Tuesday Static",
        "title": "Short Wave",
        "duration_seconds": 47,
        "play_source": "LIBRARY_VINYL",
        "is_local_artist": False,
    },
]

TALK_EPISODE_STARTS = [
    "2026-01-05T19:00:00Z",
    "2026-01-12T19:00:00Z",
    "2026-01-19T19:00:00Z",
    "2026-01-26T19:00:00Z",
    "2026-02-02T19:00:00Z",
    "2026-02-09T19:00:00Z",
    "2026-02-16T19:00:00Z",
]


def _music_airing_with_open_log():
    """One aired music airing whose log is open and already carries its spins."""
    base = fixtures.station(clock=REVIEW_CLOCK)
    approved = fixtures.create_approved_program(
        base["host_id"],
        base["members"],
        title="Delta Sessions",
        format_code="MUSIC",
        requested_daypart="EVENING",
        requested_duration_minutes=120,
    )
    grid = fixtures.create_grid(
        season_code=SPRING_SEASON, effective_from=EARLY_FROM, effective_to=EARLY_TO
    )
    slot = fixtures.add_slot(
        grid["id"],
        approved["program_id"],
        day_of_week=1,
        start_minute=1200,
        duration_minutes=120,
    )
    episode = fixtures.create_episode(
        approved["program_id"],
        slot["id"],
        base["host_id"],
        scheduled_start_utc=MUSIC_EPISODE_START,
    )
    aired = fixtures.record_air_result(episode["id"], air_status="AIRED")
    assert aired["log_status"] == "PENDING", (
        "an aired MUSIC airing owes a log, so the log dimension opens at PENDING"
    )
    entries = fixtures.add_playlist_entries(episode["id"], base["host_id"], FEATURED_PLAYLIST)
    return {
        "host_id": base["host_id"],
        "program_id": approved["program_id"],
        "episode_id": episode["id"],
        "entries": entries,
    }


def _talk_show_with_seven_airings():
    """A published winter grid carrying one talk show with seven airings, the
    oldest of which was missed."""
    base = fixtures.station(clock=REVIEW_CLOCK)
    talk = fixtures.create_approved_program(
        base["host_id"],
        base["members"],
        title="Open Line",
        format_code="TALK",
        requested_daypart="EVENING",
        requested_duration_minutes=120,
    )
    news = fixtures.create_approved_program(
        base["host_id"],
        base["members"],
        title="County Report",
        format_code="NEWS",
        requested_daypart="MORNING_DRIVE",
        requested_duration_minutes=30,
    )
    grid = fixtures.create_grid(
        season_code=WINTER_SEASON, effective_from=EARLY_FROM, effective_to=EARLY_TO
    )
    talk_slot = fixtures.add_slot(
        grid["id"], talk["program_id"], day_of_week=1, start_minute=1140, duration_minutes=120
    )
    news_slot = fixtures.add_slot(
        grid["id"], news["program_id"], day_of_week=2, start_minute=420, duration_minutes=30
    )
    fixtures.confirm_slot(talk_slot["id"])
    fixtures.confirm_slot(news_slot["id"])
    fixtures.publish_grid(grid["id"])

    episode_ids = []
    for index, start in enumerate(TALK_EPISODE_STARTS):
        episode = fixtures.create_episode(
            talk["program_id"], talk_slot["id"], base["host_id"], scheduled_start_utc=start
        )
        fixtures.record_air_result(
            episode["id"], air_status="MISSED" if index == 0 else "AIRED"
        )
        episode_ids.append(episode["id"])
    return {
        "host_id": base["host_id"],
        "grid_id": grid["id"],
        "talk_program_id": talk["program_id"],
        "news_program_id": news["program_id"],
        "episode_ids": episode_ids,
    }


class TestEpisodeRoyaltyVariants:
    def test_survey_variant_carries_one_rounding_after_the_uplift(self):
        """The provisional figure is the sampled estimate.

        "It sums the `duration_seconds` of every featured entry into a single
        total, divides that total by 60 to get minutes, multiplies by 65 cents,
        multiplies the result by the survey uplift factor of 1.10, and only then
        rounds half up to a whole cent." 185 + 212 + 47 seconds is 444 seconds,
        so 444 / 60 * 65 * 1.10 is 529.1 cents, which rounds to 529.

        Submission is also what fixes the two counts: it "recomputes
        `featured_performance_count` as the number of the airing's entries whose
        `royalty_class` is `FEATURED`" and "recomputes `local_featured_count` as
        the number of those `FEATURED` entries whose `is_local_artist` is true".

        Design: Difficulty/dual_variant_calc/episode_royalty_survey_versus_census_diverge_on_identical_playlist
        """
        setup = _music_airing_with_open_log()

        submitted = fixtures.submit_log(setup["episode_id"], setup["host_id"])

        assert submitted["log_status"] == "SUBMITTED"
        assert submitted["featured_performance_count"] == 3
        assert submitted["local_featured_count"] == 2
        assert submitted["provisional_royalty_cents"] == 529
        assertions.assert_integer_cents(
            submitted["provisional_royalty_cents"], "provisional_royalty_cents"
        )

        reread = fixtures.read_episode(setup["episode_id"])
        assert reread["provisional_royalty_cents"] == 529
        assert reread["final_royalty_cents"] is None

    def test_census_variant_prices_each_spin_and_diverges_from_the_survey_figure(self):
        """Certification prices the identical featured set the other way.

        "Each featured spin is priced individually — its own `duration_seconds`
        divided by 60, multiplied by 65 cents, rounded half up to a whole cent —
        and the already-rounded per-spin cents are then added together." The
        three spins price at 200, 230 and 51 cents for 481, and "There is no
        uplift factor in the census variant." The survey figure is left standing:
        `CERTIFY` "moves the log `SUBMITTED → CERTIFIED` and writes
        `final_royalty_cents` from the **CENSUS** variant."

        Design: Difficulty/dual_variant_calc/episode_royalty_survey_versus_census_diverge_on_identical_playlist
        """
        setup = _music_airing_with_open_log()
        submitted = fixtures.submit_log(setup["episode_id"], setup["host_id"])
        assert submitted["provisional_royalty_cents"] == 529

        certified = fixtures.decide_log(setup["episode_id"], decision="CERTIFY")

        assert certified["log_status"] == "CERTIFIED"
        assert certified["final_royalty_cents"] == 481
        assert certified["provisional_royalty_cents"] == 529
        assert certified["provisional_royalty_cents"] - certified["final_royalty_cents"] == 48

        reread = fixtures.read_episode(setup["episode_id"])
        assert reread["final_royalty_cents"] == 481
        assert reread["provisional_royalty_cents"] == 529
        assert reread["featured_performance_count"] == 3
        assert reread["local_featured_count"] == 2


class TestProgramPerformanceWindows:
    def test_trailing_six_window_ignores_the_older_missed_airing(self):
        """The six-airing window no longer reaches the missed broadcast.

        "`TRAILING_SIX` looks at the six most recent airings of the show whose
        `scheduled_start_utc` is at or before the current clock, taken in
        descending order of `scheduled_start_utc` and excluding any airing whose
        `air_status` is `CANCELLED`." All six of those aired, and a talk show
        "owes no logs at all has a required count of zero and its log compliance
        is taken as 1.0", so the weighted sum is a full 100.00.

        Design: Difficulty/dual_variant_calc/program_performance_trailing_six_versus_quarter_to_date_diverge
        """
        setup = _talk_show_with_seven_airings()

        response = api_client.create_performance_review(
            setup["talk_program_id"],
            factories.performance_review_payload(review_window="TRAILING_SIX"),
            DIRECTOR_HEADERS,
        )
        reviewed = validate_success(response, 200)

        assertions.assert_two_decimals_equal(
            reviewed["performance_score"], 100.00, "performance_score"
        )
        assert reviewed["performance_score_method"] == "TRAILING_SIX"
        assert reviewed["programming_status"] == "ON_AIR_ACTIVE"
        assertions.assert_instant_equals(
            reviewed["last_evaluated_at"], REVIEW_CLOCK, "last_evaluated_at"
        )
        assert reviewed["compliance_penalty_points"] == 0

    def test_quarter_to_date_window_reaches_back_and_scores_lower(self):
        """The quarter window admits every airing, missed one included.

        "`QUARTER_TO_DATE` looks at every airing of the show from the first
        instant of the calendar quarter containing the current clock through the
        clock itself, again excluding `CANCELLED` airings, with no limit on how
        many airings enter the window." Six of the seven aired, so reliability is
        6/7 and the weighted sum is 92.142857..., "rounded half up to two decimal
        places" once at the end for 92.14 — the two variants "can disagree
        sharply".

        Design: Difficulty/dual_variant_calc/program_performance_trailing_six_versus_quarter_to_date_diverge
        """
        setup = _talk_show_with_seven_airings()

        trailing = validate_success(
            api_client.create_performance_review(
                setup["talk_program_id"],
                factories.performance_review_payload(review_window="TRAILING_SIX"),
                DIRECTOR_HEADERS,
            ),
            200,
        )
        quarterly = validate_success(
            api_client.create_performance_review(
                setup["talk_program_id"],
                factories.performance_review_payload(review_window="QUARTER_TO_DATE"),
                DIRECTOR_HEADERS,
            ),
            200,
        )

        assertions.assert_two_decimals_equal(
            quarterly["performance_score"], 92.14, "performance_score"
        )
        assert quarterly["performance_score_method"] == "QUARTER_TO_DATE"
        assert quarterly["performance_score"] != trailing["performance_score"]
        assert quarterly["programming_status"] == "ON_AIR_ACTIVE"
        assertions.assert_instant_equals(
            quarterly["last_evaluated_at"], REVIEW_CLOCK, "last_evaluated_at"
        )

        reread = fixtures.read_program(setup["talk_program_id"])
        assertions.assert_two_decimals_equal(
            reread["performance_score"], 92.14, "performance_score"
        )
        assert reread["performance_score_method"] == "QUARTER_TO_DATE"
