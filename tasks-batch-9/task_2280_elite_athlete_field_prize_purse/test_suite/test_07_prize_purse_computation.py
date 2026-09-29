"""Generating the award set: pooled ties, nested bonuses and the withholding variants."""
from test_helpers import (
    FINANCE,
    api_client,
    assert_purse_ledger,
    certify_edition_results,
    certify_result,
    compute_awards,
    decide_record_claim,
    disqualify_result,
    enter_result,
    get_success_data,
    list_awards,
    read_award,
    read_edition,
    read_invitation,
    read_result,
    set_clock,
    setup_edition_with_certified_results,
    setup_raced_edition,
    submit_record_package,
)

ELITE_MALE_STANDARD = {"division": "ELITE", "gender": "MALE",
                       "max_qualifying_seconds": 8_100,
                       "bib_range_start": 11, "bib_range_end": 20}
TIE_PURSE_LINES = [
    {"category": "OVERALL", "gender": "MALE", "place": 1, "amount_cents": 1_000_000},
    {"category": "OVERALL", "gender": "MALE", "place": 2, "amount_cents": 1_400_000},
    {"category": "OVERALL", "gender": "MALE", "place": 3, "amount_cents": 1_300_000},
]


# ==========================================================================
# The two treaty variants over an identical pair of grosses
# ==========================================================================
def _foreign_winner_with_a_large_and_a_small_prize():
    """A Kenyan winner whose treaty certification is on file, holding a 250,000-cent
    overall prize and a 50,000-cent division prize at a 3,000 bps treaty rate."""
    scenario = setup_edition_with_certified_results(
        [{"gun_seconds": 7_500, "net_seconds": 7_498,
          "offer": {"appearance_fee_cents": 1_000_000, "air_class": "ECONOMY",
                    "hotel_nights": 3, "ground_transport": False},
          "athlete_overrides": {"country_code": "KEN",
                                "tax_residency_country": "KEN",
                                "w8ben_on_file": True,
                                "treaty_withholding_bps": 3_000},
          "performance_overrides": {"performance_seconds": 7_900}}],
        purse_lines=[
            {"category": "OVERALL", "gender": "MALE", "place": 1,
             "amount_cents": 250_000},
            {"category": "DIVISION", "division": "ELITE", "gender": "MALE",
             "place": 1, "amount_cents": 50_000},
        ],
        standards=[ELITE_MALE_STANDARD],
        race_clock="2026-11-01T09:00:00Z",
        name="Withholding Variant Marathon",
        appearance_budget_cents=10_000_000,
        total_purse_cents=10_000_000,
        bonus_pool_cap_cents=0,
    )
    edition_id = scenario["edition"]["id"]
    scenario["edition"] = compute_awards(
        edition_id, expected_race_edition_version=scenario["edition"]["version"]
    )
    scenario["overall"] = list_awards(
        {"race_edition_id": edition_id, "category": "OVERALL", "status": "COMPUTED"}
    )[0][0]
    scenario["division"] = list_awards(
        {"race_edition_id": edition_id, "category": "DIVISION", "status": "COMPUTED"}
    )[0][0]
    return scenario


def test_per_award_withholding_exempts_the_small_prize_entirely():
    """Each award is screened on its own, so 50,000 cents escapes withholding.

    PRD §3.8: "when `w8ben_on_file` is true, the variant is `PER_AWARD` and the rate
    is the athlete's `treaty_withholding_bps`; each award is then handled on its own, in
    ascending category order with `created_at` ascending as the tie-break, where category
    order runs `OVERALL`, `DIVISION`, `MASTERS`, `TIME_BONUS`, `RECORD_BONUS`. An award
    whose `gross_amount_cents` is below 60,000 cents is withheld nothing at all; otherwise
    its `withholding_cents` is the gross multiplied by the rate and divided by 10,000,
    rounded half up to whole cents." PRD §3.8 also fixes the
    reported rate: "an award exempted by either de-minimis threshold still reports the
    rate that would have applied, with `withholding_cents` at zero."

    Design: Difficulty/dual_variant_calc/dual_variant_withholding_per_award_vs_aggregated
    """
    scenario = _foreign_winner_with_a_large_and_a_small_prize()

    overall = scenario["overall"]
    assert overall["gross_amount_cents"] == 250_000
    assert overall["withholding_variant"] == "PER_AWARD"
    assert overall["withholding_bps"] == 3_000
    assert overall["withholding_cents"] == 75_000
    assert overall["net_amount_cents"] == 175_000

    division = scenario["division"]
    assert division["gross_amount_cents"] == 50_000
    assert division["withholding_variant"] == "PER_AWARD"
    assert division["withholding_cents"] == 0, "50,000 is below the 60,000 threshold"
    assert division["net_amount_cents"] == 50_000

    assert overall["withholding_cents"] + division["withholding_cents"] == 75_000


def test_aggregated_withholding_reaches_the_prize_per_award_exempted():
    """At an identical rate the same two grosses owe 90,000 instead of 75,000.

    PRD §3.8: "When the athlete's residency is not domestic and `w8ben_on_file` is
    false, the variant is `AGGREGATED` and the rate is the statutory 3,000 basis
    points. Here the de-minimis test runs on the athlete's aggregate rather than award
    by award: the aggregate is the summed `gross_amount_cents` of the athlete's awards
    from this run, and when that aggregate is at or below 150,000 cents every award is
    withheld nothing." The consequence is stated outright: "an award small enough to
    escape under `PER_AWARD` is still withheld on under `AGGREGATED`".

    Design: Difficulty/dual_variant_calc/dual_variant_withholding_per_award_vs_aggregated
    """
    scenario = _foreign_winner_with_a_large_and_a_small_prize()
    edition_id = scenario["edition"]["id"]
    athlete_id = scenario["entrants"][0]["athlete"]["id"]

    revised = get_success_data(api_client.update_tax_profile(
        athlete_id, {"w8ben_on_file": False}, FINANCE
    ))
    assert revised["w8ben_on_file"] is False

    edition = compute_awards(
        edition_id, expected_race_edition_version=scenario["edition"]["version"]
    )
    assert edition["purse_allocated_cents"] == 300_000

    division_awards, meta = list_awards(
        {"race_edition_id": edition_id, "category": "DIVISION", "status": "COMPUTED"}
    )
    assert meta["total_count"] == 1
    small = division_awards[0]
    assert small["gross_amount_cents"] == 50_000
    assert small["withholding_variant"] == "AGGREGATED"
    assert small["withholding_bps"] == 3_000
    assert small["withholding_cents"] == 15_000, (
        "the 300,000 aggregate clears the 150,000 de-minimis, so the small prize is "
        "withheld on"
    )

    overall_awards, _ = list_awards(
        {"race_edition_id": edition_id, "category": "OVERALL", "status": "COMPUTED"}
    )
    assert overall_awards[0]["withholding_cents"] == 75_000
    assert small["withholding_cents"] + overall_awards[0]["withholding_cents"] == 90_000, (
        "the same grosses that owed 75,000 under PER_AWARD owe 90,000 here"
    )


def test_a_recompute_voids_the_previous_awards_without_re_withholding_them():
    """The superseded awards keep the cents they were computed with.

    PRD §3.8: "It begins by superseding: every existing prize award of the edition
    whose `status` is `COMPUTED` becomes `VOID`". PRD §3.2 is explicit about the
    profile edit: "awards already computed are deliberately not re-withheld by that
    edit, and the new profile takes effect only the next time the award set is
    regenerated."

    Design: Difficulty/dual_variant_calc/dual_variant_withholding_per_award_vs_aggregated
    """
    scenario = _foreign_winner_with_a_large_and_a_small_prize()
    first_run_division_id = scenario["division"]["id"]

    get_success_data(api_client.update_tax_profile(
        scenario["entrants"][0]["athlete"]["id"], {"w8ben_on_file": False}, FINANCE
    ))
    compute_awards(scenario["edition"]["id"],
                   expected_race_edition_version=scenario["edition"]["version"])

    superseded = read_award(first_run_division_id)
    assert superseded["status"] == "VOID"
    assert superseded["withholding_variant"] == "PER_AWARD"
    assert superseded["withholding_cents"] == 0, (
        "the tax-profile edit never rewrote an award that already existed"
    )


# ==========================================================================
# The bonus nest: supersede, then clip to the remaining headroom
# ==========================================================================
def _ratified_record_against_a_narrow_bonus_pool():
    """A ratified course record worth 1,500,000 on paper against 1,200,000 of bonus
    pool, plus a second finisher who also clears the time tier."""
    scenario = setup_edition_with_certified_results(
        [
            {"gun_seconds": 7_500, "net_seconds": 7_498,
             "offer": {"appearance_fee_cents": 1_000_000, "air_class": "ECONOMY",
                       "hotel_nights": 3, "ground_transport": False},
             "athlete_overrides": {"country_code": "USA"},
             "performance_overrides": {"performance_seconds": 7_900}},
            {"gun_seconds": 7_550, "net_seconds": 7_548,
             "offer": {"appearance_fee_cents": 1_000_000, "air_class": "ECONOMY",
                       "hotel_nights": 3, "ground_transport": False},
             "athlete_overrides": {"country_code": "USA"},
             "performance_overrides": {"performance_seconds": 7_950}},
        ],
        purse_lines=[
            {"category": "OVERALL", "gender": "MALE", "place": 1,
             "amount_cents": 1_000_000},
            {"category": "OVERALL", "gender": "MALE", "place": 2,
             "amount_cents": 500_000},
            {"category": "TIME_BONUS", "division": "ELITE", "gender": "MALE",
             "threshold_seconds": 7_600, "amount_cents": 500_000},
            {"category": "RECORD_BONUS", "division": "ELITE", "gender": "MALE",
             "amount_cents": 1_500_000},
        ],
        standards=[ELITE_MALE_STANDARD],
        race_clock="2026-11-01T09:00:00Z",
        name="Bonus Nest Marathon",
        appearance_budget_cents=10_000_000,
        total_purse_cents=10_000_000,
        bonus_pool_cap_cents=1_200_000,
        course_record_male_seconds=7_600,
    )
    winner_result_id = scenario["entrants"][0]["result"]["id"]
    submit_record_package(winner_result_id, "PKG-A")
    decide_record_claim(winner_result_id, "RATIFIED")
    scenario["edition"] = read_edition(scenario["edition"]["id"])
    return scenario


def test_the_record_bonus_supersedes_the_time_bonus_and_is_clipped_to_the_headroom():
    """1,500,000 replaces 500,000 rather than adding to it, then meets a 1,200,000 cap.

    PRD §3.8: "The candidate paid is the greater of the two: a record bonus supersedes
    a time bonus, it never adds to it. The award's `category` is `RECORD_BONUS` when
    the record candidate is above zero and is at least as large as the time candidate,
    and `TIME_BONUS` in every other case. The headroom is the edition's
    `bonus_pool_cap_cents` less the consumed figure, floored at zero, and the amount
    actually paid is the lesser of the candidate and that headroom." The award shape is
    pinned too: it is created "with that `category`, a null `place`, a
    `tie_share_count` of 1 and a `gross_amount_cents` equal to the paid amount".

    Design: Difficulty/combinatorial_formula/combinatorial_bonus_nested_max_supersede_then_min_headroom_cap
    """
    scenario = _ratified_record_against_a_narrow_bonus_pool()
    edition_id = scenario["edition"]["id"]
    compute_awards(edition_id,
                   expected_race_edition_version=scenario["edition"]["version"])

    bonuses, meta = list_awards(
        {"race_edition_id": edition_id, "category": "RECORD_BONUS",
         "status": "COMPUTED"}
    )
    assert meta["total_count"] == 1
    bonus = bonuses[0]
    assert bonus["gross_amount_cents"] == 1_200_000, (
        "the 1,500,000 record candidate beats the 500,000 time candidate and is then "
        "clipped to the 1,200,000 of remaining pool"
    )
    assert bonus["place"] is None
    assert bonus["tie_share_count"] == 1
    assert bonus["race_result_id"] == scenario["entrants"][0]["result"]["id"]
    assert bonus["withholding_variant"] == "NONE"
    assert bonus["withholding_cents"] == 0
    assert bonus["net_amount_cents"] == 1_200_000


def test_an_exhausted_bonus_pool_creates_no_award_for_the_next_finisher():
    """With zero headroom left the second runner's time tier pays nothing at all.

    PRD §3.8: "Bonuses are computed next, against the edition's `bonus_pool_cap_cents`,
    and the pool is consumed in a strict order that makes the cap a genuine race between
    athletes." The headroom decides what is actually paid: "The headroom is the edition's
    `bonus_pool_cap_cents` less the consumed figure, floored at zero, and the amount
    actually paid is the lesser of the candidate and that headroom. When the paid amount is
    above zero an award is created in `COMPUTED` with that `category`, a null `place`, a
    `tie_share_count` of 1 and a `gross_amount_cents` equal to the paid amount, and the
    consumed figure grows by it. When the paid amount is zero — because no tier matched or
    because the pool is exhausted — no award is created at all."

    Design: Difficulty/combinatorial_formula/combinatorial_bonus_nested_max_supersede_then_min_headroom_cap
    """
    scenario = _ratified_record_against_a_narrow_bonus_pool()
    edition_id = scenario["edition"]["id"]
    runner_up = read_result(scenario["entrants"][1]["result"]["id"])
    assert runner_up["record_claim_status"] == "REJECTED", (
        "the ratification rejected the slower claim, so only a time tier remains"
    )

    compute_awards(edition_id,
                   expected_race_edition_version=scenario["edition"]["version"])

    time_bonuses, meta = list_awards(
        {"race_edition_id": edition_id, "category": "TIME_BONUS", "status": "COMPUTED"}
    )
    assert meta["total_count"] == 0
    assert time_bonuses == []


def test_the_clipped_bonus_is_what_the_ledgers_report():
    """Both bonus projections follow the amount actually paid, not the candidate.

    PRD §2.9: "`bonus_pool_consumed_cents` is the sum of `gross_amount_cents` over
    that same set of awards restricted to those whose `category` is `TIME_BONUS` or
    `RECORD_BONUS`." PRD §3.8 closes the run by recomputing them: "The run closes by
    recomputing the edition's `purse_allocated_cents`, `purse_unallocated_cents` and
    `bonus_pool_consumed_cents` and incrementing the edition's `version`."

    Design: Difficulty/combinatorial_formula/combinatorial_bonus_nested_max_supersede_then_min_headroom_cap
    """
    scenario = _ratified_record_against_a_narrow_bonus_pool()
    edition = compute_awards(
        scenario["edition"]["id"],
        expected_race_edition_version=scenario["edition"]["version"],
    )

    assert edition["bonus_pool_consumed_cents"] == 1_200_000
    assert_purse_ledger(edition, 2_700_000, 7_300_000)


# ==========================================================================
# A three-way dead heat: pool, divide, floor, then hand out the remainder
# ==========================================================================
def _three_way_dead_heat(name, appearance_budget_cents, fee_cents):
    """Three domestic finishers on an identical gun time, their results created one
    second apart so `created_at` ascending is unambiguous."""
    offer = {"appearance_fee_cents": fee_cents, "air_class": "ECONOMY",
             "hotel_nights": 2, "ground_transport": False}
    scenario = setup_raced_edition(
        [
            {"offer": offer, "athlete_overrides": {"country_code": "USA"},
             "performance_overrides": {"performance_seconds": seconds}}
            for seconds in (7_900, 7_910, 7_920)
        ],
        purse_lines=TIE_PURSE_LINES,
        standards=[ELITE_MALE_STANDARD],
        race_clock="2026-11-01T09:00:00Z",
        name=name,
        appearance_budget_cents=appearance_budget_cents,
        total_purse_cents=8_000_000,
        bonus_pool_cap_cents=0,
    )
    edition_id = scenario["edition"]["id"]
    for index, entrant in enumerate(scenario["entrants"]):
        set_clock(f"2026-11-01T09:00:0{index}Z")
        entrant["result"] = enter_result(
            edition_id, entrant["invitation"]["id"],
            gun_seconds=7_500, net_seconds=7_498 - index,
        )
    for entrant in scenario["entrants"]:
        certify_result(entrant["result"]["id"])
    certify_edition_results(edition_id)
    for entrant in scenario["entrants"]:
        entrant["result"] = read_result(entrant["result"]["id"])
    scenario["edition"] = read_edition(edition_id)
    return scenario


def _awards_for(edition_id, result_id):
    return list_awards({"race_edition_id": edition_id, "race_result_id": result_id,
                        "status": "COMPUTED"})


def test_a_three_way_tie_pools_three_place_amounts_before_dividing():
    """3,700,000 divided three ways is 1,233,333 with one cent left to place.

    PRD §3.8: "The order of operations is pinned: pool the matching line amounts
    first, then divide the pool by the tie count and take the floor of the quotient as
    each runner's share, then compute the leftover as the pool less that share
    multiplied by the tie count — a value between zero and one less than the tie count —
    and hand one extra cent to each of the earliest tied results, ordering the tied group
    by the result's `created_at` ascending, until the leftover is exhausted. Rounding each
    purse line before pooling is wrong and will produce different cents."

    Design: Difficulty/combinatorial_formula/combinatorial_tie_pool_before_divide_then_floor_then_remainder
    """
    scenario = _three_way_dead_heat("Three Way Tie Marathon", 10_000_000, 500_000)
    edition_id = scenario["edition"]["id"]
    compute_awards(edition_id,
                   expected_race_edition_version=scenario["edition"]["version"])

    shares = []
    for entrant in scenario["entrants"]:
        awards, meta = _awards_for(edition_id, entrant["result"]["id"])
        assert meta["total_count"] == 1
        shares.append(awards[0]["gross_amount_cents"])
        assert awards[0]["place"] == 1
        assert awards[0]["tie_share_count"] == 3
        assert awards[0]["category"] == "OVERALL"

    assert shares == [1_233_334, 1_233_333, 1_233_333], (
        "the earliest-created result takes the single remainder cent"
    )
    assert sum(shares) == 3_700_000, "no cent is created or destroyed by the pooling"


def test_the_places_absorbed_by_the_tie_produce_no_further_awards():
    """The place 2 and place 3 lines were consumed by the pooled group.

    PRD §3.8: "The pool for that group is the sum of `amount_cents` over the edition's
    purse lines of that category matching the group's partition — matching on gender, and
    additionally on division for `DIVISION` lines — whose `place` falls in the run of
    consecutive places starting at the shared place and extending for as many places as
    there are tied runners. A purse line that does not exist contributes nothing." Each
    award carries "its `place` set to the shared place".

    Design: Difficulty/combinatorial_formula/combinatorial_tie_pool_before_divide_then_floor_then_remainder
    """
    scenario = _three_way_dead_heat("Three Way Tie Marathon", 10_000_000, 500_000)
    edition_id = scenario["edition"]["id"]
    compute_awards(edition_id,
                   expected_race_edition_version=scenario["edition"]["version"])

    awards, meta = list_awards({"race_edition_id": edition_id, "status": "COMPUTED"})
    assert meta["total_count"] == 3
    assert [award["place"] for award in awards] == [1, 1, 1]


def test_the_shared_place_is_visible_on_the_results_and_the_purse_ledger():
    """Standard competition ranking puts all three at place 1 with a tie group of three.

    PRD §3.7: "Within a partition, a result's place is one more than the number of
    results in that partition strictly faster than it, which is standard competition
    ranking: two runners on the same official time share a place and the place after a
    shared pair is skipped." PRD §2.9 fixes the invariant: "`total_purse_cents` equals
    `purse_unallocated_cents` plus the summed `gross_amount_cents` of the edition's
    awards in `COMPUTED`, `APPROVED`, `PAID` or `CLAWBACK_PENDING`."

    Design: Difficulty/combinatorial_formula/combinatorial_tie_pool_before_divide_then_floor_then_remainder
    """
    scenario = _three_way_dead_heat("Three Way Tie Marathon", 10_000_000, 500_000)
    edition_id = scenario["edition"]["id"]
    middle = scenario["entrants"][1]["result"]
    assert middle["place_overall"] == 1
    assert middle["place_division"] == 1
    assert middle["place_masters"] is None
    assert middle["tie_group_size"] == 3
    assert middle["is_masters"] is False

    compute_awards(edition_id,
                   expected_race_edition_version=scenario["edition"]["version"])
    assert_purse_ledger(read_edition(edition_id), 3_700_000, 4_300_000)


# ==========================================================================
# Aggregated withholding: one rounding, then a largest-remainder split
# ==========================================================================
def _masters_foreigner_taking_three_prizes():
    """A 46-year-old Kenyan with no treaty certification on file, winning three
    100,001-cent prizes: overall, division and masters."""
    scenario = setup_edition_with_certified_results(
        [{"gun_seconds": 8_000, "net_seconds": 7_998,
          "offer": {"appearance_fee_cents": 800_000, "air_class": "ECONOMY",
                    "hotel_nights": 2, "ground_transport": False},
          "athlete_overrides": {"country_code": "KEN",
                                "tax_residency_country": "KEN",
                                "w8ben_on_file": False,
                                "birth_date": "1980-05-05"},
          "performance_overrides": {"performance_seconds": 7_900}}],
        purse_lines=[
            {"category": "OVERALL", "gender": "MALE", "place": 1,
             "amount_cents": 100_001},
            {"category": "DIVISION", "division": "ELITE", "gender": "MALE",
             "place": 1, "amount_cents": 100_001},
            {"category": "MASTERS", "gender": "MALE", "place": 1,
             "amount_cents": 100_001},
        ],
        standards=[ELITE_MALE_STANDARD],
        race_clock="2026-11-01T09:00:00Z",
        name="Aggregate Rounding Marathon",
        race_date="2026-11-01",
        appearance_budget_cents=10_000_000,
        total_purse_cents=10_000_000,
        bonus_pool_cap_cents=0,
    )
    scenario["edition"] = compute_awards(
        scenario["edition"]["id"],
        expected_race_edition_version=scenario["edition"]["version"],
    )
    return scenario


def _single_award(edition_id, category):
    awards, meta = list_awards(
        {"race_edition_id": edition_id, "category": category, "status": "COMPUTED"}
    )
    assert meta["total_count"] == 1, f"exactly one {category} award is expected"
    return awards[0]


def test_one_runner_may_hold_the_overall_division_and_masters_prizes_at_once():
    """The three partitions each place the same runner first.

    PRD §3.7: "Three partitions are then formed among the certified results of the
    edition. The overall partition groups results by the athlete's gender and admits
    only divisions `ELITE` and `SUB_ELITE`. The division partition groups by division
    and the athlete's gender. The masters partition groups by the athlete's gender and
    admits only results whose division is `ELITE` and whose `is_masters` is true."

    Design: Difficulty/combinatorial_formula/combinatorial_aggregated_withholding_total_then_largest_remainder_split
    """
    scenario = _masters_foreigner_taking_three_prizes()
    edition_id = scenario["edition"]["id"]

    result = read_result(scenario["entrants"][0]["result"]["id"])
    assert result["is_masters"] is True, "a 1980 birth date is 46 on race day"
    assert result["place_overall"] == 1
    assert result["place_division"] == 1
    assert result["place_masters"] == 1

    for category in ("OVERALL", "DIVISION", "MASTERS"):
        assert _single_award(edition_id, category)["gross_amount_cents"] == 100_001

    assert_purse_ledger(read_edition(edition_id), 300_003, 9_699_997)


def test_the_aggregate_is_rounded_once_and_split_by_largest_remainder():
    """90,001 cents of tax, not three independent roundings of 30,000.

    PRD §3.8: "the total withheld is the aggregate multiplied by the statutory rate
    and divided by 10,000, rounded half up once, and that single total is then split
    across the awards pro rata by gross using largest-remainder allocation. Each
    award's exact share is the total multiplied by that award's gross and divided by
    the aggregate; each award provisionally receives the integer part of its exact
    share, truncated toward zero; the leftover is the total less the sum of those
    integer parts; and one extra cent goes to each of the first awards when the awards
    are ordered by the fractional part of their exact share descending, with the
    award's own `created_at` ascending as the tie-break, until the leftover is
    exhausted." Category order runs "`OVERALL`, `DIVISION`, `MASTERS`, `TIME_BONUS`,
    `RECORD_BONUS`".

    Design: Difficulty/combinatorial_formula/combinatorial_aggregated_withholding_total_then_largest_remainder_split
    """
    scenario = _masters_foreigner_taking_three_prizes()
    edition_id = scenario["edition"]["id"]

    overall = _single_award(edition_id, "OVERALL")
    division = _single_award(edition_id, "DIVISION")
    masters = _single_award(edition_id, "MASTERS")

    assert overall["withholding_variant"] == "AGGREGATED"
    assert overall["withholding_bps"] == 3_000
    assert overall["withholding_cents"] == 30_001, (
        "the three exact shares tie on their fractional part, so the leftover cent "
        "goes to the award created first in the pinned category order"
    )
    assert overall["net_amount_cents"] == 70_000

    assert division["withholding_cents"] == 30_000
    assert division["net_amount_cents"] == 70_001
    assert masters["withholding_cents"] == 30_000
    assert masters["net_amount_cents"] == 70_001

    total = (overall["withholding_cents"] + division["withholding_cents"]
             + masters["withholding_cents"])
    assert total == 90_001, (
        "300,003 cents at 3,000 bps rounds half up once to 90,001"
    )


# ==========================================================================
# The zero-cardinality boundary and the gun-versus-net selector
# ==========================================================================
def _wheelchair_finisher_with_no_matching_purse_line():
    """The single finisher races the wheelchair division while every purse line is an
    overall line, which covers only `ELITE` and `SUB_ELITE`."""
    return setup_edition_with_certified_results(
        [{"division": "WHEELCHAIR", "gun_seconds": 7_500, "net_seconds": 7_400,
          "offer": {"appearance_fee_cents": 600_000, "air_class": "ECONOMY",
                    "hotel_nights": 3, "ground_transport": True},
          "athlete_overrides": {"country_code": "USA",
                                "birth_date": "1993-09-09"},
          "performance_overrides": {"performance_seconds": 7_800}}],
        purse_lines=[
            {"category": "OVERALL", "gender": "MALE", "place": 1,
             "amount_cents": 2_000_000},
            {"category": "OVERALL", "gender": "MALE", "place": 2,
             "amount_cents": 1_000_000},
        ],
        standards=[{"division": "WHEELCHAIR", "gender": "MALE",
                    "max_qualifying_seconds": 8_000,
                    "bib_range_start": 901, "bib_range_end": 910}],
        race_clock="2026-11-01T09:00:00Z",
        name="Empty Award Set Marathon",
        appearance_budget_cents=9_000_000,
        total_purse_cents=8_000_000,
        bonus_pool_cap_cents=0,
    )


def test_a_wheelchair_result_is_officially_timed_on_the_chip():
    """The official time is the net 7,400, and the overall partition excludes the runner.

    PRD §3.7: the server "derives `official_seconds` from the division: for `ELITE`
    and `SUB_ELITE` results the official time is the gun time, while for `WHEELCHAIR`
    results it is the net time." Consequently "`place_overall` is the result's place in
    the overall partition for `ELITE` and `SUB_ELITE` results and null for
    `WHEELCHAIR` results", while "`place_division` is the result's place in the
    division partition and is always assigned."

    Design: Difficulty/boundary_precision_check/boundary_empty_award_set_and_net_time_selection_on_compute_awards
    """
    scenario = _wheelchair_finisher_with_no_matching_purse_line()
    result = scenario["entrants"][0]["result"]

    assert result["division"] == "WHEELCHAIR"
    assert result["official_seconds"] == 7_400, "the chip time, not the gun time"
    assert result["place_overall"] is None
    assert result["place_division"] == 1
    assert result["is_masters"] is False
    assert result["place_masters"] is None


def test_generating_an_empty_award_set_is_a_legitimate_outcome():
    """Compute-awards succeeds and pays nobody, leaving the whole purse unallocated.

    PRD §3.8: "`OVERALL` lines ignore division entirely and cover the `ELITE` and
    `SUB_ELITE` results of the matching gender", and "An award whose gross would be
    zero is not created at all." PRD §2.9 then reads at its zero boundary:
    "`purse_allocated_cents` is the sum of `gross_amount_cents` over the prize awards
    of that edition whose `status` is any of `COMPUTED`, `APPROVED`, `PAID` or
    `CLAWBACK_PENDING`, and `purse_unallocated_cents` is `total_purse_cents` less
    `purse_allocated_cents`."

    Design: Difficulty/boundary_precision_check/boundary_empty_award_set_and_net_time_selection_on_compute_awards
    """
    scenario = _wheelchair_finisher_with_no_matching_purse_line()
    edition_id = scenario["edition"]["id"]

    edition = compute_awards(
        edition_id, expected_race_edition_version=scenario["edition"]["version"]
    )
    assert edition["status"] == "RESULTS_CERTIFIED", (
        "generating an empty award set is not a failure and moves no posture"
    )

    awards, meta = list_awards({"race_edition_id": edition_id})
    assert meta["total_count"] == 0
    assert awards == []
    assert_purse_ledger(read_edition(edition_id), 0, 8_000_000)


# ==========================================================================
# Purse cents conserved across a disqualification and the recompute after it
# ==========================================================================
def _dead_heat_with_awards_computed():
    """The three-way tie with its award set generated, so 3,700,000 cents stand
    allocated in three `COMPUTED` awards."""
    scenario = _three_way_dead_heat("Purse Invariant Marathon", 9_000_000, 800_000)
    edition_id = scenario["edition"]["id"]
    scenario["edition"] = compute_awards(
        edition_id, expected_race_edition_version=scenario["edition"]["version"]
    )
    for entrant in scenario["entrants"]:
        awards, _ = _awards_for(edition_id, entrant["result"]["id"])
        entrant["award"] = awards[0]
    return scenario


def test_disqualifying_one_tied_runner_returns_exactly_that_award_s_cents():
    """The voided 1,233,334 comes back to the unallocated pool and nothing else moves.

    PRD §3.7: "Because the result is disqualified, each of its prize awards in
    `COMPUTED` or `APPROVED` becomes `VOID` and each in `PAID` becomes
    `CLAWBACK_PENDING`. Because those awards changed status, the edition's
    `purse_allocated_cents`, `purse_unallocated_cents` and `bonus_pool_consumed_cents` are
    all recomputed and the edition's `version` is incremented — a `VOID` award leaves the
    allocated pool and its cents return to the unallocated pool, whereas a
    `CLAWBACK_PENDING` award stays inside the allocated pool and the unallocated pool does
    not grow." The reason chosen is not one of
    the breach reasons, and PRD §3.7 limits the breach to those: "when the `dq_reason`
    is one of the four breach reasons `PACER_BEYOND_RANGE`,
    `UNAUTHORIZED_FLUID_HANDOFF`, `COURSE_CUTTING` or `ADVERSE_ANALYTICAL_FINDING`,
    the invitation the runner ran under moves `ACCEPTED → BREACHED`."

    Design: Difficulty/compensating_invariant/compensating_purse_ledger_invariant_across_disqualification_and_recompute
    """
    scenario = _dead_heat_with_awards_computed()
    first = scenario["entrants"][0]
    assert first["award"]["gross_amount_cents"] == 1_233_334
    assert_purse_ledger(scenario["edition"], 3_700_000, 4_300_000)

    disqualified = disqualify_result(first["result"]["id"], "MISSED_TEST_THRESHOLD")
    assert disqualified["certification_status"] == "DISQUALIFIED"
    assert disqualified["dq_reason"] == "MISSED_TEST_THRESHOLD"

    assert read_award(first["award"]["id"])["status"] == "VOID"
    assert read_invitation(first["invitation"]["id"])["status"] == "ACCEPTED", (
        "a missed-test disqualification is not a breach"
    )
    assert_purse_ledger(read_edition(scenario["edition"]["id"]), 2_466_666, 5_533_334)


def test_the_survivors_keep_their_places_until_the_award_set_is_recomputed():
    """A disqualification does not re-place anybody.

    PRD §3.7: "A disqualification deliberately does not re-place the surviving
    results; re-placement happens only when the award set is explicitly recomputed."

    Design: Difficulty/compensating_invariant/compensating_purse_ledger_invariant_across_disqualification_and_recompute
    """
    scenario = _dead_heat_with_awards_computed()
    disqualify_result(scenario["entrants"][0]["result"]["id"],
                     "MISSED_TEST_THRESHOLD")

    survivor = read_result(scenario["entrants"][1]["result"]["id"])
    assert survivor["place_overall"] == 1
    assert survivor["tie_group_size"] == 3, (
        "the tie group is frozen at three until a recompute re-derives it"
    )


def test_the_recompute_re_derives_a_two_way_tie_and_restores_the_invariant():
    """Two survivors pool places 1 and 2 and split 2,400,000 evenly.

    PRD §3.8: a recompute "re-runs the place-and-tie assignment of §3.7 over the
    current `CERTIFIED` set, which is where a disqualification recorded since the last
    run finally re-places the survivors." PRD §3.7 explains why the disqualified runner
    contributes nothing: "a disqualified result is excluded from the input set of every
    calculation in the system — it does not consume a place and it does not enlarge any
    tie group."

    Design: Difficulty/compensating_invariant/compensating_purse_ledger_invariant_across_disqualification_and_recompute
    """
    scenario = _dead_heat_with_awards_computed()
    edition_id = scenario["edition"]["id"]
    disqualify_result(scenario["entrants"][0]["result"]["id"],
                     "MISSED_TEST_THRESHOLD")

    edition = compute_awards(
        edition_id,
        expected_race_edition_version=read_edition(edition_id)["version"],
    )
    assert_purse_ledger(edition, 2_400_000, 5_600_000)

    awards, meta = list_awards({"race_edition_id": edition_id, "status": "COMPUTED"})
    assert meta["total_count"] == 2
    assert [award["gross_amount_cents"] for award in awards] == [1_200_000, 1_200_000]
    assert [award["tie_share_count"] for award in awards] == [2, 2]

    survivor = read_result(scenario["entrants"][1]["result"]["id"])
    assert survivor["place_overall"] == 1
    assert survivor["tie_group_size"] == 2
