"""Deterministic selectors: which bib, which invitations count, which bonus tier."""
from test_helpers import (
    ApiErrorId,
    DIRECTOR,
    FINANCE,
    api_client,
    assign_bib,
    compute_awards,
    enroll_accepted_invitation,
    enroll_offered_invitation,
    list_awards,
    read_edition,
    read_invitation,
    register_agent,
    respond_as_agent,
    setup_edition_with_certified_results,
    setup_field_open_edition,
    validate_error,
    validate_paginated,
    withdraw_invitation,
)

ELITE_MALE_STANDARD = {"division": "ELITE", "gender": "MALE",
                       "max_qualifying_seconds": 8_100,
                       "bib_range_start": 11, "bib_range_end": 20}
OVERALL_MALE_FIRST = {"category": "OVERALL", "gender": "MALE", "place": 1,
                      "amount_cents": 1_000_000}
BONUS_PURSE_LINES = [
    OVERALL_MALE_FIRST,
    {"category": "OVERALL", "gender": "MALE", "place": 2, "amount_cents": 600_000},
    {"category": "TIME_BONUS", "division": "ELITE", "gender": "MALE",
     "threshold_seconds": 7_600, "amount_cents": 400_000},
]
LADDER_OFFER = {"appearance_fee_cents": 500_000, "air_class": "ECONOMY",
                "hotel_nights": 2, "ground_transport": False}
UNIFORM_OFFER = {"appearance_fee_cents": 700_000, "air_class": "ECONOMY",
                 "hotel_nights": 2, "ground_transport": False}


def _four_accepted_invitations_against_a_ten_bib_pool():
    """Four accepted, whereabouts-filed ELITE MALE athletes and a pool of 11 to 20,
    none of them bibbed yet."""
    scenario = setup_field_open_edition(
        purse_lines=[OVERALL_MALE_FIRST],
        standards=[ELITE_MALE_STANDARD],
        name="Bib Selector Marathon",
        appearance_budget_cents=9_000_000,
        total_purse_cents=3_000_000,
        bonus_pool_cap_cents=0,
    )
    edition_id = scenario["edition"]["id"]
    agent = register_agent(agency_name="Bib Order Reps", license_code="AGT-BO-1")
    scenario["entrants"] = [
        enroll_accepted_invitation(
            edition_id, offer=LADDER_OFFER, agent=agent,
            athlete_overrides={"country_code": "USA", "whereabouts_filed": True},
            performance_overrides={"performance_seconds": seconds},
        )
        for seconds in (7_900, 7_910, 7_920, 7_930)
    ]
    return scenario


def test_the_bib_selector_hands_out_the_lowest_free_number_each_time():
    """Three assignments against a pool starting at 11 return 11, then 12, then 13.

    PRD §3.5: "The eligible pool is every integer from `bib_range_start` through
    `bib_range_end` inclusive on the division standard matching this invitation's
    edition, division and the athlete's gender. From that pool the server excludes
    every bib currently held by an `ACCEPTED` invitation of the same edition — and only
    of the same edition." Then "The lowest remaining number is written to `bib_number`;
    because bib numbers are distinct integers there is never a tie to break, and the
    selector consults no identifier of any kind."

    Design: Corner/calculations/corner_calc_bib_selector_returns_lowest_free_bib_after_release
    """
    scenario = _four_accepted_invitations_against_a_ten_bib_pool()
    entrants = scenario["entrants"]

    assert assign_bib(entrants[0]["invitation"]["id"])["bib_number"] == 11
    assert assign_bib(entrants[1]["invitation"]["id"])["bib_number"] == 12
    assert assign_bib(entrants[2]["invitation"]["id"])["bib_number"] == 13


def test_a_withdrawal_refills_its_hole_before_the_pool_advances():
    """Releasing 12 makes the next assignment 12 rather than 14.

    PRD §3.5: "Bibs held by invitations that have gone `WITHDRAWN`, `BREACHED`,
    `EXPIRED` or `DECLINED` are not held at all and are immediately reusable." PRD §3.4
    describes the release: a withdrawal from `ACCEPTED` "nulls `bib_number`, returning
    that bib to its division pool for immediate reuse".

    Design: Corner/calculations/corner_calc_bib_selector_returns_lowest_free_bib_after_release
    """
    scenario = _four_accepted_invitations_against_a_ten_bib_pool()
    entrants = scenario["entrants"]
    assign_bib(entrants[0]["invitation"]["id"])
    assign_bib(entrants[1]["invitation"]["id"])
    assign_bib(entrants[2]["invitation"]["id"])

    withdrawn = withdraw_invitation(entrants[1]["invitation"]["id"],
                                   reason="visa refused")
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["bib_number"] is None

    assert assign_bib(entrants[3]["invitation"]["id"])["bib_number"] == 12, (
        "the freed number is the lowest free one, so it comes before 14"
    )


def test_an_invitation_already_wearing_a_bib_cannot_take_a_second():
    """A repeated assignment is refused and the number on the invitation is unchanged.

    PRD §3.5: "Bib assignment is a service operation on an `ACCEPTED` invitation,
    performed by an `ElitesDirector` while the edition is `FIELD_OPEN` or
    `FIELD_LOCKED`; attempting it against an invitation in any other status is
    `ERR_INVALID_INVITATION_STATE`, and attempting it against an invitation that
    already holds a `bib_number` is `ERR_BIB_ALREADY_ASSIGNED`."

    Design: Corner/calculations/corner_calc_bib_selector_returns_lowest_free_bib_after_release
    """
    scenario = _four_accepted_invitations_against_a_ten_bib_pool()
    invitation_id = scenario["entrants"][0]["invitation"]["id"]
    assert assign_bib(invitation_id)["bib_number"] == 11

    repeat = api_client.assign_bib(invitation_id, DIRECTOR)
    validate_error(repeat, ApiErrorId.ERR_BIB_ALREADY_ASSIGNED.value, 409)

    assert read_invitation(invitation_id)["bib_number"] == 11


def _three_identical_packages_on_the_table():
    """Three ELITE MALE athletes offered the same 700,000 package by one agent."""
    scenario = setup_field_open_edition(
        purse_lines=[OVERALL_MALE_FIRST],
        standards=[ELITE_MALE_STANDARD],
        name="Input Set Marathon",
        appearance_budget_cents=9_000_000,
        total_purse_cents=3_000_000,
        bonus_pool_cap_cents=0,
    )
    edition_id = scenario["edition"]["id"]
    agent = register_agent(agency_name="Filter Reps", license_code="AGT-FT-1")
    scenario["entrants"] = [
        enroll_offered_invitation(
            edition_id, offer=UNIFORM_OFFER, agent=agent,
            athlete_overrides={"country_code": "USA"},
            performance_overrides={"performance_seconds": seconds},
        )
        for seconds in (7_900, 7_910, 7_920)
    ]
    return scenario


def test_only_the_accepted_package_reaches_the_appearance_ledger():
    """One acceptance and one refusal out of three offers commit 884,000 cents.

    PRD §3.4: "The guaranteed valuation is `current_appearance_fee_cents` plus the air
    component plus the hotel component plus the ground component, in integer cents, and
    it excludes every bonus exposure term." A refusal moves nothing: "A `DECLINE` moves
    the invitation `OFFERED → DECLINED` or `COUNTERED → DECLINED`. `DECLINED` is
    terminal and no budget moves, because nothing was ever committed." PRD §2.9 fixes
    the projection: "`appearance_committed_cents` is the sum of
    `guaranteed_commitment_cents` over the invitations of that edition whose `status` is
    `ACCEPTED`, and `appearance_uncommitted_cents` is `appearance_budget_cents` less
    `appearance_committed_cents`."

    Design: Corner/calculations/corner_calc_input_set_excludes_declined_and_draft_invitations
    """
    scenario = _three_identical_packages_on_the_table()
    entrants = scenario["entrants"]

    accepted = respond_as_agent(entrants[0]["invitation"]["id"],
                               entrants[0]["agent"]["id"], "ACCEPT")
    assert accepted["status"] == "ACCEPTED"
    assert accepted["guaranteed_commitment_cents"] == 884_000, (
        "700,000 fee plus 120,000 economy air plus two nights at 32,000"
    )

    declined = respond_as_agent(entrants[1]["invitation"]["id"],
                               entrants[1]["agent"]["id"], "DECLINE")
    assert declined["status"] == "DECLINED"
    assert declined["guaranteed_commitment_cents"] == 0

    edition = read_edition(scenario["edition"]["id"])
    assert edition["appearance_committed_cents"] == 884_000
    assert edition["appearance_uncommitted_cents"] == 8_116_000


def test_the_outstanding_offer_is_excluded_on_its_state_not_on_its_absence():
    """The third invitation is still live and still contributes nothing.

    PRD §2.9: "invitations in `WITHDRAWN`, `BREACHED`, `EXPIRED` or `DECLINED`
    contribute nothing to the appearance ledger". An `OFFERED` invitation contributes
    nothing either, because PRD §3.4 says "In every status other than `ACCEPTED`,
    `guaranteed_commitment_cents` reads as zero." PRD §3.3 provides the filter:
    "Invitations may be listed and filtered on `race_edition_id`, `athlete_id`,
    `agent_id`, `qualifying_performance_id`, `status` and `division`".

    Design: Corner/calculations/corner_calc_input_set_excludes_declined_and_draft_invitations
    """
    scenario = _three_identical_packages_on_the_table()
    entrants = scenario["entrants"]
    edition_id = scenario["edition"]["id"]
    respond_as_agent(entrants[0]["invitation"]["id"], entrants[0]["agent"]["id"],
                     "ACCEPT")
    respond_as_agent(entrants[1]["invitation"]["id"], entrants[1]["agent"]["id"],
                     "DECLINE")

    outstanding, meta = validate_paginated(
        api_client.list_invitations(DIRECTOR,
                                   {"race_edition_id": edition_id,
                                    "status": "OFFERED"})
    )
    assert meta["total_count"] == 1
    assert outstanding[0]["id"] == entrants[2]["invitation"]["id"]
    assert outstanding[0]["guaranteed_commitment_cents"] == 0
    assert read_edition(edition_id)["appearance_committed_cents"] == 884_000


def _two_finishers_either_side_of_the_bonus_threshold():
    """Certified finishes of exactly 7,600 and 7,601 gun seconds against a 7,600
    second time-bonus tier with 5,000,000 cents of headroom."""
    return setup_edition_with_certified_results(
        [
            {"gun_seconds": 7_600, "net_seconds": 7_598,
             "athlete_overrides": {"country_code": "USA"},
             "performance_overrides": {"performance_seconds": 7_900}},
            {"gun_seconds": 7_601, "net_seconds": 7_599,
             "athlete_overrides": {"country_code": "USA"},
             "performance_overrides": {"performance_seconds": 7_910}},
        ],
        purse_lines=BONUS_PURSE_LINES,
        standards=[ELITE_MALE_STANDARD],
        race_clock="2026-11-01T09:00:00Z",
        name="Time Bonus Threshold Marathon",
        appearance_budget_cents=9_000_000,
        total_purse_cents=8_000_000,
        bonus_pool_cap_cents=5_000_000,
    )


def test_a_finisher_exactly_on_the_threshold_earns_the_tier():
    """7,600 official seconds against a 7,600 second tier takes the bonus as well as
    the win.

    PRD §3.8: "the time-bonus candidate is the largest `amount_cents` among the
    edition's `TIME_BONUS` purse lines whose `division` equals the result's division,
    whose `gender` equals the athlete's gender, and whose `threshold_seconds` the
    result's `official_seconds` does not exceed — the threshold is inclusive, so hitting
    it exactly earns the tier — or zero when no tier matches." PRD §3.7 fixes the time
    compared: "for `ELITE` and `SUB_ELITE` results the official time is the gun time".

    Design: Corner/calculations/corner_calc_time_bonus_threshold_is_inclusive_at_exact_second
    """
    scenario = _two_finishers_either_side_of_the_bonus_threshold()
    edition_id = scenario["edition"]["id"]
    winner_result = scenario["entrants"][0]["result"]
    assert winner_result["official_seconds"] == 7_600
    compute_awards(edition_id,
                   expected_race_edition_version=scenario["edition"]["version"])

    awards, meta = list_awards(
        {"race_edition_id": edition_id, "race_result_id": winner_result["id"]}, FINANCE
    )
    assert meta["total_count"] == 2
    by_category = {award["category"]: award for award in awards}
    assert by_category["OVERALL"]["gross_amount_cents"] == 1_000_000
    assert by_category["TIME_BONUS"]["gross_amount_cents"] == 400_000


def test_one_second_past_the_threshold_earns_no_bonus_at_all():
    """The runner-up collects the second place prize and nothing else.

    PRD §3.8: "When the paid amount is zero — because no tier matched or because the
    pool is exhausted — no award is created at all." The place prize is unaffected,
    because PRD §3.8 pays place prizes from the lines "whose `place` falls in the run of
    consecutive places starting at the shared place and extending for as many places as
    there are tied runners".

    Design: Corner/calculations/corner_calc_time_bonus_threshold_is_inclusive_at_exact_second
    """
    scenario = _two_finishers_either_side_of_the_bonus_threshold()
    edition_id = scenario["edition"]["id"]
    runner_up_result = scenario["entrants"][1]["result"]
    assert runner_up_result["official_seconds"] == 7_601
    assert runner_up_result["place_overall"] == 2
    compute_awards(edition_id,
                   expected_race_edition_version=scenario["edition"]["version"])

    awards, meta = list_awards(
        {"race_edition_id": edition_id, "race_result_id": runner_up_result["id"]},
        FINANCE,
    )
    assert meta["total_count"] == 1
    assert awards[0]["category"] == "OVERALL"
    assert awards[0]["gross_amount_cents"] == 600_000


def test_the_single_bonus_is_paid_in_full_against_ample_headroom():
    """With a 5,000,000 cent cap the tier is not clipped, and both ledgers say so.

    PRD §3.8: "The headroom is the edition's `bonus_pool_cap_cents` less the consumed
    figure, floored at zero, and the amount actually paid is the lesser of the candidate
    and that headroom." PRD §2.9: "`bonus_pool_consumed_cents` is the sum of
    `gross_amount_cents` over that same set of awards restricted to those whose
    `category` is `TIME_BONUS` or `RECORD_BONUS`."

    Design: Corner/calculations/corner_calc_time_bonus_threshold_is_inclusive_at_exact_second
    """
    scenario = _two_finishers_either_side_of_the_bonus_threshold()
    edition_id = scenario["edition"]["id"]
    computed = compute_awards(
        edition_id, expected_race_edition_version=scenario["edition"]["version"]
    )

    bonuses, meta = list_awards(
        {"race_edition_id": edition_id, "category": "TIME_BONUS"}, FINANCE
    )
    assert meta["total_count"] == 1
    assert bonuses[0]["gross_amount_cents"] == 400_000

    assert computed["bonus_pool_consumed_cents"] == 400_000
    assert computed["purse_allocated_cents"] == 2_000_000, (
        "1,000,000 and 600,000 in place prizes plus the 400,000 bonus"
    )
    assert computed["purse_unallocated_cents"] == 6_000_000
