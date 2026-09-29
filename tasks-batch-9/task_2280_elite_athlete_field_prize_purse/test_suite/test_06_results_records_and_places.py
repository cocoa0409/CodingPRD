"""Two independent result dimensions, record ratification and the masters partition."""
from test_helpers import (
    ApiErrorId,
    FINANCE,
    TECHNICAL,
    api_client,
    assert_purse_ledger,
    compute_awards,
    create_race_result_payload,
    decide_record_claim,
    enroll_bibbed_invitation,
    enter_result,
    list_awards,
    lock_field,
    mark_raced,
    read_edition,
    read_invitation,
    read_result,
    set_clock,
    setup_edition_with_certified_results,
    setup_field_open_edition,
    submit_record_package,
    validate_error,
    validate_paginated,
    withdraw_invitation,
)

RECORD_ON_FILE_SECONDS = 7_500
RECORD_OFFER = {
    "appearance_fee_cents": 1_000_000,
    "air_class": "ECONOMY",
    "hotel_nights": 3,
    "ground_transport": False,
}
CHAIN_OFFER = {
    "appearance_fee_cents": 400_000,
    "air_class": "ECONOMY",
    "hotel_nights": 2,
    "ground_transport": False,
}
OVERALL_MALE_FIRST = {"category": "OVERALL", "gender": "MALE", "place": 1,
                      "amount_cents": 1_000_000}
ELITE_MALE_STANDARD = {"division": "ELITE", "gender": "MALE",
                       "max_qualifying_seconds": 8_100,
                       "bib_range_start": 11, "bib_range_end": 20}


def _certified_result_holding_a_record_claim():
    """One certified 7,412-second finish against a 7,500-second record on file, so
    the edition certification pass raised a claim on it."""
    return setup_edition_with_certified_results(
        [{"gun_seconds": 7_412, "net_seconds": 7_410, "offer": RECORD_OFFER,
          "athlete_overrides": {"country_code": "USA"},
          "performance_overrides": {"performance_seconds": 7_800}}],
        purse_lines=[OVERALL_MALE_FIRST],
        standards=[ELITE_MALE_STANDARD],
        race_clock="2026-11-01T09:00:00Z",
        name="Parallel Dimensions Marathon",
        appearance_budget_cents=5_000_000,
        total_purse_cents=5_000_000,
        bonus_pool_cap_cents=0,
        course_record_male_seconds=RECORD_ON_FILE_SECONDS,
    )


def test_certification_survives_every_move_of_the_record_claim():
    """Lodging and rejecting a package leaves `certification_status` at `CERTIFIED`.

    PRD §3.7: "The second dimension of a result is its record claim, whose values
    are `NONE`, `CLAIMED`, `SUBMITTED`, `RATIFIED` and `REJECTED`." Lodging "stores
    the reference and moves the claim `CLAIMED → SUBMITTED`", and "A `REJECTED`
    decision moves the claim `SUBMITTED → REJECTED`, leaves the course record
    untouched, and changes nothing else."

    Design: Difficulty/non_linear_state_machine/race_result_parallel_dimensions_with_record_resubmission_loop
    """
    scenario = _certified_result_holding_a_record_claim()
    result = scenario["entrants"][0]["result"]
    assert result["certification_status"] == "CERTIFIED"
    assert result["record_claim_status"] == "CLAIMED", (
        "7,412 official seconds is strictly faster than the 7,500 on file"
    )
    assert result["place_overall"] == 1

    submitted = submit_record_package(result["id"], "PKG-1")
    assert submitted["record_claim_status"] == "SUBMITTED"
    assert submitted["sanctioning_submission_ref"] == "PKG-1"
    assert submitted["certification_status"] == "CERTIFIED"

    rejected = decide_record_claim(result["id"], "REJECTED",
                                  decision_note="wind gauge certificate missing")
    assert rejected["record_claim_status"] == "REJECTED"
    assert rejected["certification_status"] == "CERTIFIED"
    assert read_edition(scenario["edition"]["id"])["course_record_male_seconds"] == (
        RECORD_ON_FILE_SECONDS
    ), "a rejected decision leaves the course record untouched"


def test_a_rejected_record_package_may_be_corrected_and_lodged_again():
    """`REJECTED → SUBMITTED` is a legal return to a state the claim already held.

    PRD §3.7: lodging "is admitted only for a result whose `certification_status` is
    `CERTIFIED`, whose division is not `SUB_ELITE`, and whose claim stands in
    `CLAIMED` or in `REJECTED` — a rejected package may be corrected and lodged
    again, moving `REJECTED → SUBMITTED`."

    Design: Difficulty/non_linear_state_machine/race_result_parallel_dimensions_with_record_resubmission_loop
    """
    scenario = _certified_result_holding_a_record_claim()
    result_id = scenario["entrants"][0]["result"]["id"]
    submit_record_package(result_id, "PKG-1")
    decide_record_claim(result_id, "REJECTED",
                       decision_note="wind gauge certificate missing")

    relodged = submit_record_package(result_id, "PKG-2")
    assert relodged["record_claim_status"] == "SUBMITTED"
    assert relodged["sanctioning_submission_ref"] == "PKG-2"
    assert relodged["certification_status"] == "CERTIFIED"

    ratified = decide_record_claim(result_id, "RATIFIED",
                                  decision_note="corrected package accepted")
    assert ratified["record_claim_status"] == "RATIFIED"
    assert ratified["certification_status"] == "CERTIFIED", (
        "four consecutive claim transitions never disturbed the certification"
    )
    assert ratified["place_overall"] == 1, (
        "the place assigned by the certification pass is untouched by the claim"
    )


def test_only_ratification_rewrites_the_edition_course_record():
    """The record field moves on the ratifying decision and on no earlier one.

    PRD §3.7: "A `RATIFIED` decision moves the claim `SUBMITTED → RATIFIED` and then
    cascades twice: because the claim is ratified, the edition's course-record field
    for that result's record class and gender is overwritten with the result's
    `official_seconds` and the edition's `version` is incremented". PRD §3.7 also
    fixes which time that is: "for `ELITE` and `SUB_ELITE` results the official time
    is the gun time".

    Design: Difficulty/non_linear_state_machine/race_result_parallel_dimensions_with_record_resubmission_loop
    """
    scenario = _certified_result_holding_a_record_claim()
    edition_id = scenario["edition"]["id"]
    result_id = scenario["entrants"][0]["result"]["id"]

    submit_record_package(result_id, "PKG-1")
    decide_record_claim(result_id, "REJECTED")
    assert read_edition(edition_id)["course_record_male_seconds"] == (
        RECORD_ON_FILE_SECONDS
    )

    submit_record_package(result_id, "PKG-2")
    decide_record_claim(result_id, "RATIFIED")

    edition = read_edition(edition_id)
    assert edition["course_record_male_seconds"] == 7_412, (
        "the ratified gun time becomes the edition's record"
    )
    assert edition["status"] == "RESULTS_CERTIFIED"


def _three_certified_finishers_with_one_package_lodged():
    """Finishes of 7,412, 7,480 and 7,600 against a 7,500 record: the first two hold
    claims, the third never raised one, and the fastest package is with the
    sanctioning body."""
    scenario = setup_edition_with_certified_results(
        [
            {"gun_seconds": 7_412, "net_seconds": 7_410, "offer": CHAIN_OFFER,
             "athlete_overrides": {"country_code": "USA"},
             "performance_overrides": {"performance_seconds": 7_900}},
            {"gun_seconds": 7_480, "net_seconds": 7_478, "offer": CHAIN_OFFER,
             "athlete_overrides": {"country_code": "USA"},
             "performance_overrides": {"performance_seconds": 7_910}},
            {"gun_seconds": 7_600, "net_seconds": 7_598, "offer": CHAIN_OFFER,
             "athlete_overrides": {"country_code": "USA"},
             "performance_overrides": {"performance_seconds": 7_920}},
        ],
        purse_lines=[OVERALL_MALE_FIRST],
        standards=[ELITE_MALE_STANDARD],
        race_clock="2026-11-01T09:00:00Z",
        name="Ratification Chain Marathon",
        appearance_budget_cents=6_000_000,
        total_purse_cents=6_000_000,
        bonus_pool_cap_cents=0,
        course_record_male_seconds=RECORD_ON_FILE_SECONDS,
    )
    fastest = scenario["entrants"][0]["result"]
    submit_record_package(fastest["id"], "PKG-CHAIN-1")
    scenario["edition"] = read_edition(scenario["edition"]["id"])
    return scenario


def test_ratifying_the_fastest_claim_raises_the_record_and_bumps_the_edition():
    """The first two hops: the claim closes and the edition's record field follows.

    PRD §3.7: "because the claim is ratified, the edition's course-record field for
    that result's record class and gender is overwritten with the result's
    `official_seconds` and the edition's `version` is incremented". PRD §2.5 fixes
    what that means: `version` is "a system-managed integer that starts at 1 on
    creation and increases by one on every mutation".

    Design: Difficulty/transitive_cascade/record_ratification_three_hop_rejects_weaker_claims
    """
    scenario = _three_certified_finishers_with_one_package_lodged()
    version_before = scenario["edition"]["version"]

    ratified = decide_record_claim(scenario["entrants"][0]["result"]["id"], "RATIFIED")
    assert ratified["record_claim_status"] == "RATIFIED"
    assert ratified["certification_status"] == "CERTIFIED"

    edition = read_edition(scenario["edition"]["id"])
    assert edition["course_record_male_seconds"] == 7_412
    assert edition["version"] == version_before + 1


def test_the_new_record_rejects_the_weaker_claim_and_spares_the_claimless_result():
    """The third hop reaches only results that were actually holding a claim.

    PRD §3.7: "and because the edition's course record has changed, every other
    `CERTIFIED` result of the edition whose claim stands in `CLAIMED` and whose
    `official_seconds` is not strictly faster than the newly ratified figure moves
    `CLAIMED → REJECTED`." The slowest finisher never entered that set, because the
    pass raises a claim only "When that record field is null, or when the result's
    `official_seconds` is strictly faster than the value on file".

    Design: Difficulty/transitive_cascade/record_ratification_three_hop_rejects_weaker_claims
    """
    scenario = _three_certified_finishers_with_one_package_lodged()
    runner_up = scenario["entrants"][1]["result"]
    slowest = scenario["entrants"][2]["result"]
    assert runner_up["record_claim_status"] == "CLAIMED"
    assert slowest["record_claim_status"] == "NONE", (
        "7,600 was slower than the 7,500 on file, so no claim was ever raised"
    )

    decide_record_claim(scenario["entrants"][0]["result"]["id"], "RATIFIED")

    runner_up = read_result(runner_up["id"])
    assert runner_up["record_claim_status"] == "REJECTED", (
        "7,480 is not strictly faster than the newly ratified 7,412"
    )
    assert runner_up["certification_status"] == "CERTIFIED"
    assert runner_up["place_overall"] == 2

    assert read_result(slowest["id"])["record_claim_status"] == "NONE"
    # No award run has happened, so the purse ledger cannot have moved.
    assert_purse_ledger(read_edition(scenario["edition"]["id"]), 0, 6_000_000)


def _raced_edition_with_a_late_scratch():
    """Two bibbed starters, one of whom withdrew after the field locked; the edition
    is `RACED`."""
    scenario = setup_field_open_edition(
        purse_lines=[OVERALL_MALE_FIRST],
        standards=[ELITE_MALE_STANDARD],
        name="Withdrawn Starter Marathon",
        appearance_budget_cents=9_000_000,
        total_purse_cents=3_000_000,
        bonus_pool_cap_cents=0,
    )
    edition_id = scenario["edition"]["id"]
    offer = {"appearance_fee_cents": 700_000, "air_class": "ECONOMY",
             "hotel_nights": 2, "ground_transport": False}
    scratched = enroll_bibbed_invitation(
        edition_id, offer=offer, athlete_overrides={"country_code": "USA"},
        performance_overrides={"performance_seconds": 7_900},
    )
    starter = enroll_bibbed_invitation(
        edition_id, offer=offer, athlete_overrides={"country_code": "USA"},
        performance_overrides={"performance_seconds": 7_910},
    )
    lock_field(edition_id)
    withdraw_invitation(scratched["invitation"]["id"],
                        reason="stress fracture confirmed 48h before the gun")
    set_clock("2026-11-01T09:00:00Z")
    mark_raced(edition_id)
    scenario["scratched"] = scratched
    scenario["starter"] = starter
    return scenario


def test_a_finish_may_not_be_recorded_against_a_withdrawn_invitation():
    """The invitation is real and belongs to this edition, but it is no longer a starter.

    PRD §3.7: "The named invitation must belong to the same edition, must be
    `ACCEPTED` and must already hold a `bib_number`; any of those three failing is
    `ERR_INVITATION_EDITION_MISMATCH`."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_race_result_rejected_for_withdrawn_invitation
    """
    scenario = _raced_edition_with_a_late_scratch()
    edition_id = scenario["edition"]["id"]
    scratched_id = scenario["scratched"]["invitation"]["id"]

    scratched = read_invitation(scratched_id)
    assert scratched["status"] == "WITHDRAWN"
    assert scratched["bib_number"] is None
    assert scratched["guaranteed_commitment_cents"] == 0
    assert scratched["race_edition_id"] == edition_id, (
        "the invitation still belongs to the edition the result names"
    )

    response = api_client.create_race_result(
        create_race_result_payload(edition_id, scratched_id, gun_seconds=7_800,
                                   net_seconds=7_798),
        TECHNICAL,
    )
    validate_error(response, ApiErrorId.ERR_INVITATION_EDITION_MISMATCH.value, 422)


def test_the_surviving_starter_records_a_result_in_the_same_edition_state():
    """The endpoint and the edition are otherwise ready, and the refusal wrote nothing.

    PRD §3.7: "On creation the server copies `athlete_id` and `division` from the
    invitation rather than accepting them from the client", and "The result begins
    with `certification_status` at `PROVISIONAL` and `record_claim_status` at `NONE`".

    Design: Difficulty/cross_entity_state_dependency/cross_entity_race_result_rejected_for_withdrawn_invitation
    """
    scenario = _raced_edition_with_a_late_scratch()
    edition_id = scenario["edition"]["id"]

    refused = api_client.create_race_result(
        create_race_result_payload(edition_id,
                                   scenario["scratched"]["invitation"]["id"],
                                   gun_seconds=7_800, net_seconds=7_798),
        TECHNICAL,
    )
    validate_error(refused, ApiErrorId.ERR_INVITATION_EDITION_MISMATCH.value, 422)

    recorded = enter_result(edition_id, scenario["starter"]["invitation"]["id"],
                           gun_seconds=7_850, net_seconds=7_848)
    assert recorded["certification_status"] == "PROVISIONAL"
    assert recorded["record_claim_status"] == "NONE"
    assert recorded["athlete_id"] == scenario["starter"]["athlete"]["id"]

    results, meta = validate_paginated(
        api_client.list_race_results(TECHNICAL, {"race_edition_id": edition_id})
    )
    assert meta["total_count"] == 1, "no phantom row exists for the withdrawn athlete"
    assert len(results) == 1


def _masters_boundary_edition():
    """A race dated 2026-11-01 with a runner born exactly forty years earlier and
    another born one day later."""
    return setup_edition_with_certified_results(
        [
            {"gun_seconds": 8_400, "net_seconds": 8_398,
             "athlete_overrides": {"country_code": "USA",
                                   "birth_date": "1986-11-02"},
             "performance_overrides": {"performance_seconds": 8_510}},
            {"gun_seconds": 8_450, "net_seconds": 8_448,
             "athlete_overrides": {"country_code": "USA",
                                   "birth_date": "1986-11-01"},
             "performance_overrides": {"performance_seconds": 8_500}},
        ],
        purse_lines=[
            OVERALL_MALE_FIRST,
            {"category": "MASTERS", "gender": "MALE", "place": 1,
             "amount_cents": 300_000},
        ],
        standards=[{"division": "ELITE", "gender": "MALE",
                    "max_qualifying_seconds": 9_000,
                    "bib_range_start": 11, "bib_range_end": 20}],
        race_clock="2026-11-01T09:00:00Z",
        name="Masters Age Boundary Marathon",
        race_date="2026-11-01",
        appearance_budget_cents=9_000_000,
        total_purse_cents=5_000_000,
        bonus_pool_cap_cents=0,
    )


def test_a_birthday_falling_exactly_on_race_day_counts_as_reached():
    """Born 1986-11-01 and racing on 2026-11-01, the runner is forty and a master.

    PRD §3.7: "Age is computed as the difference between the race year and the birth
    year, reduced by one when the race's month-and-day pair falls before the birth
    date's month-and-day pair, so a birthday landing exactly on race day counts as
    reached; `is_masters` is true when that age in completed years is at least the
    edition's `masters_min_age`." PRD §3.1 fixes the dial's default: `masters_min_age`
    "is the minimum age in completed years, as at race day, that makes a runner a
    master; it defaults to 40 and must lie between 35 and 60 inclusive."

    Design: Difficulty/boundary_precision_check/boundary_masters_age_exactly_forty_on_race_day_at_certify_results
    """
    scenario = _masters_boundary_edition()
    exactly_forty = read_result(scenario["entrants"][1]["result"]["id"])

    assert exactly_forty["is_masters"] is True
    assert exactly_forty["place_masters"] == 1
    assert exactly_forty["place_overall"] == 2, (
        "8,450 official seconds is the slower of the two finishes"
    )


def test_a_runner_one_day_short_of_forty_is_not_a_master():
    """Born 1986-11-02, the runner is thirty-nine on race day and holds no masters place.

    PRD §3.7: "The masters partition groups by the athlete's gender and admits only
    results whose division is `ELITE` and whose `is_masters` is true." Consequently
    "`place_masters` is the result's place in the masters partition when the result is
    `ELITE` and a master, and null otherwise."

    Design: Difficulty/boundary_precision_check/boundary_masters_age_exactly_forty_on_race_day_at_certify_results
    """
    scenario = _masters_boundary_edition()
    one_day_short = read_result(scenario["entrants"][0]["result"]["id"])

    assert one_day_short["is_masters"] is False
    assert one_day_short["place_masters"] is None
    assert one_day_short["place_overall"] == 1, (
        "the masters classification is independent of the overall placing"
    )


def test_the_masters_purse_line_pays_the_qualifying_runner_only():
    """One masters award of 300,000 cents is generated, alongside the overall prize.

    PRD §3.8: "`MASTERS` purse lines pay only results whose division is `ELITE` and
    whose `is_masters` is true". PRD §2.9 fixes the ledger: "`purse_allocated_cents`
    is the sum of `gross_amount_cents` over the prize awards of that edition whose
    `status` is any of `COMPUTED`, `APPROVED`, `PAID` or `CLAWBACK_PENDING`".

    Design: Difficulty/boundary_precision_check/boundary_masters_age_exactly_forty_on_race_day_at_certify_results
    """
    scenario = _masters_boundary_edition()
    edition_id = scenario["edition"]["id"]
    compute_awards(edition_id,
                   expected_race_edition_version=scenario["edition"]["version"])

    masters_awards, meta = list_awards(
        {"race_edition_id": edition_id, "category": "MASTERS"}, FINANCE
    )
    assert meta["total_count"] == 1
    assert masters_awards[0]["athlete_id"] == (
        scenario["entrants"][1]["athlete"]["id"]
    )
    assert masters_awards[0]["gross_amount_cents"] == 300_000

    assert_purse_ledger(read_edition(edition_id), 1_300_000, 3_700_000)
