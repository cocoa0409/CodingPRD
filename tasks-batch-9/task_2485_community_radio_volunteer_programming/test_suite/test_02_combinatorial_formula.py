"""Formulas whose answer depends on the order the steps are combined in.

The census royalty rounds each spin before it adds them, and the premium
waterfall ranks on one key before it consults another. In both cases a
plausible-looking reordering of the same ingredients lands on a different,
wrong answer, which is exactly what these tests pin down.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success
from test_helpers import (
    DEVELOPMENT_HEADERS,
    DIRECTOR_HEADERS,
    api_client,
    assertions,
    factories,
    fixtures,
)

REVIEW_CLOCK = "2026-02-20T12:00:00Z"
DRIVE_CLOCK = "2026-08-01T00:00:00Z"

SPRING_SEASON = "2026-SPRING"
SPRING_FROM = "2026-01-05T00:00:00Z"
SPRING_TO = "2026-06-28T23:59:00Z"
MUSIC_EPISODE_START = "2026-01-05T20:00:00Z"

# Three half-minute spins on three different featured sources. Every spin
# prices to exactly 32.5 cents before rounding, which is the whole point.
HALF_MINUTE_PLAYLIST = [
    {
        "artist": "Half Cent",
        "title": "Thirty A",
        "duration_seconds": 30,
        "play_source": "LIBRARY_CD",
        "is_local_artist": False,
    },
    {
        "artist": "Half Cent",
        "title": "Thirty B",
        "duration_seconds": 30,
        "play_source": "LIBRARY_VINYL",
        "is_local_artist": False,
    },
    {
        "artist": "Half Cent",
        "title": "Thirty C",
        "duration_seconds": 30,
        "play_source": "DIGITAL",
        "is_local_artist": False,
    },
]


def _airing_with_three_half_minute_spins():
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
        season_code=SPRING_SEASON, effective_from=SPRING_FROM, effective_to=SPRING_TO
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
    fixtures.record_air_result(episode["id"], air_status="AIRED")
    entries = fixtures.add_playlist_entries(
        episode["id"], base["host_id"], HALF_MINUTE_PLAYLIST
    )
    return {
        "host_id": base["host_id"],
        "episode_id": episode["id"],
        "entries": entries,
    }


def _drive_with_three_premiums():
    """Two premiums share the top tier and a third sits below it, so the
    ranking has to break a tie before it can walk the list."""
    fixtures.set_clock(DRIVE_CLOCK)
    mug = fixtures.create_premium(
        sku="MUG-01",
        name="Station Mug",
        tier_threshold_cents=10000,
        fair_market_value_cents=1500,
        units_received_qty=5,
    )
    vinyl = fixtures.create_premium(
        sku="VINYL-02",
        name="Benefit LP",
        tier_threshold_cents=10000,
        fair_market_value_cents=3500,
        units_received_qty=5,
    )
    tote = fixtures.create_premium(
        sku="TOTE-03",
        name="Canvas Tote",
        tier_threshold_cents=5000,
        fair_market_value_cents=1200,
        units_received_qty=5,
    )
    drive = fixtures.create_active_drive(
        name="Fall Drive",
        goal_cents=5_000_000,
        start_at="2026-08-01T00:00:00Z",
        end_at="2026-08-14T23:59:00Z",
        phone_line_count=4,
    )
    return {
        "drive_id": drive["id"],
        "mug_id": mug["id"],
        "vinyl_id": vinyl["id"],
        "tote_id": tote["id"],
    }


class TestCensusRoyaltyRounding:
    def test_each_spin_is_rounded_before_the_spins_are_added(self):
        """Three 32.5-cent spins certify at 99 cents, not 98.

        "Each featured spin is priced individually — its own `duration_seconds`
        divided by 60, multiplied by 65 cents, rounded half up to a whole cent —
        and the already-rounded per-spin cents are then added together." Each
        30-second spin is 32.5 cents and rounds half up to 33, so the total is
        99; summing first would give 97.5 and round to 98.

        Design: Difficulty/combinatorial_formula/census_royalty_rounds_each_spin_before_summing
        """
        setup = _airing_with_three_half_minute_spins()

        submitted = fixtures.submit_log(setup["episode_id"], setup["host_id"])
        certified = fixtures.decide_log(setup["episode_id"], decision="CERTIFY")

        assert submitted["featured_performance_count"] == 3
        assert certified["final_royalty_cents"] == 99
        assert certified["final_royalty_cents"] != 98
        assertions.assert_integer_cents(certified["final_royalty_cents"], "final_royalty_cents")

        reread = fixtures.read_episode(setup["episode_id"])
        assert reread["final_royalty_cents"] == 99

    def test_the_survey_figure_over_the_same_spins_lands_on_one_hundred_and_seven(self):
        """The same three spins under the survey variant round only once.

        The survey variant "sums the `duration_seconds` of every featured entry
        into a single total, divides that total by 60 to get minutes, multiplies
        by 65 cents, multiplies the result by the survey uplift factor of 1.10,
        and only then rounds half up to a whole cent": 90 seconds gives 107.25
        cents and so 107. Every spin is on a featured source and reaches the
        threshold, because an entry is `FEATURED` when its `play_source` is
        `LIBRARY_CD`, `LIBRARY_VINYL` or `DIGITAL` and its `duration_seconds` is
        at least 30.

        Design: Difficulty/combinatorial_formula/census_royalty_rounds_each_spin_before_summing
        """
        setup = _airing_with_three_half_minute_spins()

        submitted = fixtures.submit_log(setup["episode_id"], setup["host_id"])

        assert submitted["provisional_royalty_cents"] == 107
        assert submitted["featured_performance_count"] == 3
        assert submitted["local_featured_count"] == 0

        first_entry = validate_success(
            api_client.get_playlist_entry(setup["entries"][0]["id"], DIRECTOR_HEADERS), 200
        )
        assert first_entry["royalty_class"] == "FEATURED"

        rows, meta = validate_paginated(
            api_client.list_playlist_entries(
                DIRECTOR_HEADERS, params={"episode_id": setup["episode_id"]}
            )
        )
        assert meta["total_count"] == 3
        assert [row["royalty_class"] for row in rows] == ["FEATURED"] * 3


class TestPremiumWaterfallRanking:
    def test_tier_is_ranked_before_fair_market_value_breaks_the_tie(self):
        """The mug wins the tie against the more expensive record.

        "Those candidates are ranked by `tier_threshold_cents` descending, so the
        most generous tier the donor earned comes first; ties are broken by
        `fair_market_value_cents` ascending, so that among equally-priced tiers
        the station gives away the item that costs the donor the least
        deductible". The mug and the record share the 10000-cent tier, so the
        1500-cent mug is selected and "that premium's `reserved_qty` rises by 1."

        Design: Difficulty/combinatorial_formula/premium_waterfall_ranks_tier_threshold_before_fair_market_value
        """
        setup = _drive_with_three_premiums()

        response = api_client.create_pledge(
            factories.create_pledge_payload(
                setup["drive_id"],
                donor_name="Marisol Vega",
                amount_cents=12000,
                wants_premium=True,
            ),
            DEVELOPMENT_HEADERS,
        )
        pledge = validate_success(response, 201)

        assert pledge["premium_item_id"] == setup["mug_id"]
        assert pledge["premium_status"] == "RESERVED"

        mug = fixtures.read_premium(setup["mug_id"])
        assert mug["reserved_qty"] == 1
        assert mug["on_hand_qty"] == 5
        assert mug["shipped_qty"] == 0
        assert mug["status"] == "AVAILABLE"
        assertions.assert_premium_unit_conservation(mug)

        assert fixtures.read_premium(setup["vinyl_id"])["reserved_qty"] == 0
        assert fixtures.read_premium(setup["tote_id"])["reserved_qty"] == 0

    def test_the_deductible_subtracts_only_the_selected_premium_value(self):
        """The deductible follows the item actually reserved.

        "When a premium was selected, whether reserved or backordered, it is the
        `amount_cents` less that premium's `fair_market_value_cents`, floored at
        0". A 12000-cent pledge against the 1500-cent mug therefore deducts to
        10500 — not 10800, which would follow the 1200-cent tote the ranking
        never reaches, and not 8500, which would follow the 3500-cent record the
        tie-break rejects.

        Design: Difficulty/combinatorial_formula/premium_waterfall_ranks_tier_threshold_before_fair_market_value
        """
        setup = _drive_with_three_premiums()

        pledge = validate_success(
            api_client.create_pledge(
                factories.create_pledge_payload(
                    setup["drive_id"],
                    donor_name="Marisol Vega",
                    amount_cents=12000,
                    wants_premium=True,
                ),
                DEVELOPMENT_HEADERS,
            ),
            201,
        )

        assert pledge["tax_deductible_cents"] == 10500
        assert pledge["tax_deductible_cents"] != 10800
        assert pledge["tax_deductible_cents"] != 8500
        assertions.assert_pledge(pledge)

        _, meta = validate_paginated(
            api_client.list_pledges(
                DEVELOPMENT_HEADERS, params={"premium_item_id": setup["mug_id"]}
            )
        )
        assert meta["total_count"] == 1

        _, vinyl_meta = validate_paginated(
            api_client.list_pledges(
                DEVELOPMENT_HEADERS, params={"premium_item_id": setup["vinyl_id"]}
            )
        )
        assert vinyl_meta["total_count"] == 0
