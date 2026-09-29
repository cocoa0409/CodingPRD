"""Reaching the catalogue: authentication, existence, re-entry guards and the two
offer-time referential refusals."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    DIRECTOR,
    FINANCE,
    FINANCE_PAYER,
    LIAISON,
    SANCTIONING,
    TECHNICAL,
    adjudicate_doping_test,
    api_client,
    certify_edition_results,
    certify_result,
    collect_sample,
    compute_awards,
    create_invitation,
    create_verified_performance,
    enter_result,
    get_success_data,
    list_awards,
    make_finance_officer_headers,
    make_headers,
    read_athlete,
    read_award,
    read_doping_test,
    read_invitation,
    register_agent,
    register_athlete,
    schedule_doping_test,
    send_offer,
    setup_field_open_edition,
    setup_raced_edition,
    validate_error,
    validate_paginated,
)

ELITE_MALE_STANDARD = {"division": "ELITE", "gender": "MALE",
                       "max_qualifying_seconds": 8_100,
                       "bib_range_start": 11, "bib_range_end": 20}
OVERALL_MALE_FIRST = {"category": "OVERALL", "gender": "MALE", "place": 1,
                      "amount_cents": 1_000_000}
STANDARD_OFFER = {"appearance_fee_cents": 400_000, "air_class": "ECONOMY",
                  "hotel_nights": 2, "ground_transport": False}
RACE_MORNING = "2026-11-01T10:00:00Z"
TEST_WINDOW = ("2026-11-01T09:00:00Z", "2026-11-01T18:00:00Z")


def test_a_missing_or_unrecognised_role_header_is_unauthenticated():
    """No role at all and a role outside the six both fail authentication, and the
    check runs before any lookup.

    PRD §2.1: "Every request — reads included — must carry two headers. `X-User-ID`
    identifies the acting user and `X-User-Role` declares the capacity in which they are
    acting. Six roles exist and their spelling is exact: `ElitesDirector`,
    `AthleteAgent`, `TechnicalOfficial`, `AntiDopingLiaison`, `SanctioningBody`, and
    `FinanceOfficer`. If either header is absent, or if `X-User-Role` is not one of those
    six strings, the request fails with `ERR_UNAUTHENTICATED`." PRD §2.11 puts that first
    and existence third: "1. **Authentication.** Both headers present and `X-User-Role`
    one of the six declared roles, else `ERR_UNAUTHENTICATED` (401). Applies to every
    endpoint." then "3. **Existence.** Every referenced identifier resolves, path
    identifiers left to right first and then body foreign keys in input order, else the
    matching 404 code from §2.10."

    Design: Corner/errors/corner_error_unauthenticated_and_unknown_id_sweep_returns_401_and_404
    """
    athlete = register_athlete(full_name="Sweep Sam", country_code="USA",
                              gender="MALE", birth_date="1997-03-03")

    no_role = api_client.get_athlete(athlete["id"], {"X-User-ID": "director-1"})
    validate_error(no_role, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    invented_role = api_client.get_athlete(
        athlete["id"], make_headers("announcer-1", "RaceAnnouncer")
    )
    validate_error(invented_role, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    unknown_id_without_a_role = api_client.get_invitation(
        NON_EXISTENT_UUID, {"X-User-ID": "director-1"}
    )
    validate_error(unknown_id_without_a_role, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    assert read_athlete(athlete["id"])["full_name"] == "Sweep Sam"


def test_each_read_endpoint_reports_its_own_not_found_code():
    """A never-issued identifier surfaces the code belonging to the entity type asked
    for.

    PRD §2.10: "The first identifier that does not resolve determines the error, and each
    entity type has its own code — `ERR_RACE_EDITION_NOT_FOUND`,
    `ERR_ATHLETE_NOT_FOUND`, `ERR_REP_AGENT_NOT_FOUND`,
    `ERR_PERFORMANCE_RECORD_NOT_FOUND`, `ERR_INVITATION_NOT_FOUND`,
    `ERR_DOPING_TEST_NOT_FOUND`, `ERR_RACE_RESULT_NOT_FOUND` and
    `ERR_PRIZE_AWARD_NOT_FOUND`, all HTTP 404."

    Design: Corner/errors/corner_error_unauthenticated_and_unknown_id_sweep_returns_401_and_404
    """
    register_athlete(full_name="Sweep Sam", country_code="USA", gender="MALE",
                     birth_date="1997-03-03")

    validate_error(api_client.get_invitation(NON_EXISTENT_UUID, DIRECTOR),
                   ApiErrorId.ERR_INVITATION_NOT_FOUND.value, 404)
    validate_error(api_client.get_doping_test(NON_EXISTENT_UUID, LIAISON),
                   ApiErrorId.ERR_DOPING_TEST_NOT_FOUND.value, 404)
    validate_error(api_client.get_race_result(NON_EXISTENT_UUID, TECHNICAL),
                   ApiErrorId.ERR_RACE_RESULT_NOT_FOUND.value, 404)
    validate_error(api_client.get_prize_award(NON_EXISTENT_UUID, FINANCE),
                   ApiErrorId.ERR_PRIZE_AWARD_NOT_FOUND.value, 404)


def _raced_edition_with_a_scheduled_test():
    """One bibbed starter on a `RACED` edition with an in-competition test still
    `SCHEDULED` inside a window the clock already sits in."""
    scenario = setup_raced_edition(
        [{"gun_seconds": 7_400, "net_seconds": 7_398,
          "athlete_overrides": {"country_code": "USA"},
          "performance_overrides": {"performance_seconds": 7_900}}],
        purse_lines=[OVERALL_MALE_FIRST],
        standards=[ELITE_MALE_STANDARD],
        race_clock=RACE_MORNING,
        name="State Guard Marathon",
        appearance_budget_cents=9_000_000,
        total_purse_cents=8_000_000,
        bonus_pool_cap_cents=0,
        course_record_male_seconds=7_000,
    )
    runner = scenario["entrants"][0]
    scenario["test"] = schedule_doping_test(
        runner["athlete"]["id"], scenario["edition"]["id"],
        test_type="IN_COMPETITION", window_start_at=TEST_WINDOW[0],
        window_end_at=TEST_WINDOW[1], sample_code="S-SGD-1",
    )
    return scenario


def test_a_doping_test_refuses_every_second_attempt_at_its_transitions():
    """Adjudication before collection, a repeated collection and a repeated
    adjudication are all state errors.

    PRD §3.6: "Attempting collection on a test that is not `SCHEDULED` is
    `ERR_INVALID_DOPING_TEST_STATE`." and "Adjudication is admitted only from
    `COLLECTED`; from anywhere else it is `ERR_INVALID_DOPING_TEST_STATE`." The outcome
    is final once written: "`CLEARED`, `ADVERSE` and `MISSED` are all terminal." PRD
    §2.11 priority 8 makes these 409s.

    Design: Corner/errors/corner_error_invalid_doping_test_state_and_invalid_award_state
    """
    scenario = _raced_edition_with_a_scheduled_test()
    test_id = scenario["test"]["id"]

    before_collection = api_client.adjudicate_doping_test(
        test_id, {"outcome": "CLEARED"}, SANCTIONING
    )
    validate_error(before_collection,
                   ApiErrorId.ERR_INVALID_DOPING_TEST_STATE.value, 409)

    collected = collect_sample(test_id, "COC-SGD-1")
    assert collected["status"] == "COLLECTED"

    twice = api_client.collect_sample(
        test_id, {"collected_sample_ref": "COC-SGD-2"}, LIAISON
    )
    validate_error(twice, ApiErrorId.ERR_INVALID_DOPING_TEST_STATE.value, 409)
    assert read_doping_test(test_id)["collected_sample_ref"] == "COC-SGD-1"

    cleared = adjudicate_doping_test(test_id, "CLEARED", outcome_notes="clean")
    assert cleared["status"] == "CLEARED"

    second_thoughts = api_client.adjudicate_doping_test(
        test_id, {"outcome": "ADVERSE", "outcome_notes": "second thoughts"}, SANCTIONING
    )
    validate_error(second_thoughts,
                   ApiErrorId.ERR_INVALID_DOPING_TEST_STATE.value, 409)
    assert read_doping_test(test_id)["status"] == "CLEARED"


def test_an_award_refuses_payment_before_approval_and_after_it_is_paid():
    """Approval and payment each fire once, and every re-entry is a state error.

    PRD §3.8: "Approval is the first of two `FinanceOfficer` acts on an individual award
    and moves it `COMPUTED → APPROVED`." and "Payment moves the award `APPROVED → PAID`,
    supplies a `payment_reference` which is stored, records the acting operator in
    `paid_by_user_id` and stamps `paid_at` from the logical clock." The guard is explicit:
    "Approving or paying an award that is not in the required state is refused with
    `ERR_INVALID_AWARD_STATE`."

    Design: Corner/errors/corner_error_invalid_doping_test_state_and_invalid_award_state
    """
    scenario = _raced_edition_with_a_scheduled_test()
    edition_id = scenario["edition"]["id"]
    collect_sample(scenario["test"]["id"], "COC-SGD-1")
    adjudicate_doping_test(scenario["test"]["id"], "CLEARED")
    result = enter_result(edition_id, scenario["entrants"][0]["invitation"]["id"],
                         gun_seconds=7_400, net_seconds=7_398)
    certify_result(result["id"])
    certify_edition_results(edition_id)
    compute_awards(edition_id)
    awards, _meta = list_awards({"race_edition_id": edition_id, "status": "COMPUTED"})
    award_id = awards[0]["id"]

    too_early = api_client.pay_prize_award(
        award_id, {"payment_reference": "TRSY-SGD-EARLY"}, FINANCE_PAYER
    )
    validate_error(too_early, ApiErrorId.ERR_INVALID_AWARD_STATE.value, 409)

    approved = get_success_data(api_client.approve_prize_award(award_id, FINANCE))
    assert approved["status"] == "APPROVED"
    second_approval = api_client.approve_prize_award(
        award_id, make_finance_officer_headers("fin-approve-3")
    )
    validate_error(second_approval, ApiErrorId.ERR_INVALID_AWARD_STATE.value, 409)
    assert read_award(award_id)["approved_by_user_id"] == "fin-approve-1"

    paid = get_success_data(
        api_client.pay_prize_award(award_id, {"payment_reference": "TRSY-SGD-1"},
                                   FINANCE_PAYER)
    )
    assert paid["status"] == "PAID"
    second_payment = api_client.pay_prize_award(
        award_id, {"payment_reference": "TRSY-SGD-2"},
        make_finance_officer_headers("fin-pay-4"),
    )
    validate_error(second_payment, ApiErrorId.ERR_INVALID_AWARD_STATE.value, 409)

    settled_row = read_award(award_id)
    assert settled_row["status"] == "PAID"
    assert settled_row["payment_reference"] == "TRSY-SGD-1"
    assert settled_row["paid_by_user_id"] == "fin-pay-2"


def _open_edition_with_only_an_elite_male_standard():
    """A `FIELD_OPEN` edition whose only standard is `ELITE` / `MALE`, with four draft
    invitations: a female entrant, two miswired pins and one coherent pin."""
    scenario = setup_field_open_edition(
        purse_lines=[OVERALL_MALE_FIRST],
        standards=[ELITE_MALE_STANDARD],
        name="Standard Miss Marathon",
        appearance_budget_cents=9_000_000,
        total_purse_cents=3_000_000,
        bonus_pool_cap_cents=0,
    )
    edition_id = scenario["edition"]["id"]
    agent = register_agent(agency_name="Standard Miss Reps", license_code="AGT-SM-1")
    fay = register_athlete(full_name="Missing Standard Fay", country_code="USA",
                          gender="FEMALE", birth_date="1997-05-01")
    marcus = register_athlete(full_name="Mismatch Marcus", country_code="USA",
                             gender="MALE", birth_date="1997-05-02")
    owen = register_athlete(full_name="Other Owen", country_code="USA",
                           gender="MALE", birth_date="1997-05-03")
    fay_elite = create_verified_performance(
        fay["id"], race_name="Qual SM-F", performance_date="2026-03-01",
        performance_seconds=7_900, division="ELITE", sanctioning_ref="SB-SM-F",
        chip_timed=True,
    )
    marcus_sub_elite = create_verified_performance(
        marcus["id"], race_name="Qual SM-M1-SUB", performance_date="2026-03-02",
        performance_seconds=7_900, division="SUB_ELITE", sanctioning_ref="SB-SM-M1S",
        chip_timed=True,
    )
    marcus_elite = create_verified_performance(
        marcus["id"], race_name="Qual SM-M1", performance_date="2026-03-03",
        performance_seconds=7_900, division="ELITE", sanctioning_ref="SB-SM-M1",
        chip_timed=True,
    )
    scenario["agent"] = agent
    scenario["female_entrant"] = create_invitation(
        edition_id, fay["id"], agent["id"], fay_elite["id"], "ELITE"
    )
    scenario["wrong_division"] = create_invitation(
        edition_id, marcus["id"], agent["id"], marcus_sub_elite["id"], "ELITE"
    )
    scenario["wrong_athlete"] = create_invitation(
        edition_id, owen["id"], agent["id"], marcus_elite["id"], "ELITE"
    )
    scenario["coherent"] = create_invitation(
        edition_id, marcus["id"], agent["id"], marcus_elite["id"], "ELITE"
    )
    return scenario


def test_an_offer_needs_a_division_standard_for_the_athletes_own_gender():
    """No `ELITE` / `FEMALE` standard exists, so the female entrant cannot be offered
    to at all.

    PRD §3.3: "There must be a division standard for the combination of this edition, the
    invitation's division and the athlete's gender, and if there is none the offer is
    refused with `ERR_QUALIFYING_STANDARD_MISSING`." PRD §2.11 priority 14 lists "the
    qualifying standard's existence and satisfaction" among the capacity and uniqueness
    rules and settles the status code: the codes "are all 409 except
    `ERR_QUALIFYING_STANDARD_MISSING`, `ERR_QUALIFYING_STANDARD_NOT_MET`,
    `ERR_PACING_BEYOND_LIMIT` and `ERR_TESTING_FREQUENCY_EXCEEDED`, which are 422."

    Design: Corner/errors/corner_error_qualifying_standard_missing_and_performance_division_mismatch
    """
    scenario = _open_edition_with_only_an_elite_male_standard()

    refused = api_client.send_offer(scenario["female_entrant"]["id"],
                                   dict(STANDARD_OFFER), DIRECTOR)
    validate_error(refused, ApiErrorId.ERR_QUALIFYING_STANDARD_MISSING.value, 422)

    untouched = read_invitation(scenario["female_entrant"]["id"])
    assert untouched["status"] == "DRAFT"
    assert untouched["offer_sent_at"] is None


def test_the_pinned_performance_must_match_both_the_division_and_the_athlete():
    """A sub-elite pin and another athlete's pin are both coherence failures, while the
    matching pin goes out.

    PRD §3.3: "It also runs the qualifying gate against exactly one performance record —
    the one pinned on the invitation. Other, faster performances by the same athlete are
    irrelevant. The pinned record must belong to the invited athlete and must have been
    claimed against the invitation's own division; either mismatch is
    `ERR_PERFORMANCE_DIVISION_MISMATCH`." PRD §2.11 priority 15 confirms the shape: "The
    pinned performance belongs to the invited athlete and to the invitation's division,
    else `ERR_PERFORMANCE_DIVISION_MISMATCH`". Invitations "may be listed and filtered on
    `race_edition_id`, `athlete_id`, `agent_id`, `qualifying_performance_id`, `status` and
    `division`".

    Design: Corner/errors/corner_error_qualifying_standard_missing_and_performance_division_mismatch
    """
    scenario = _open_edition_with_only_an_elite_male_standard()

    sub_elite_pin = api_client.send_offer(scenario["wrong_division"]["id"],
                                        dict(STANDARD_OFFER), DIRECTOR)
    validate_error(sub_elite_pin,
                   ApiErrorId.ERR_PERFORMANCE_DIVISION_MISMATCH.value, 422)

    someone_elses_pin = api_client.send_offer(scenario["wrong_athlete"]["id"],
                                             dict(STANDARD_OFFER), DIRECTOR)
    validate_error(someone_elses_pin,
                   ApiErrorId.ERR_PERFORMANCE_DIVISION_MISMATCH.value, 422)

    offered = send_offer(scenario["coherent"]["id"], **STANDARD_OFFER)
    assert offered["status"] == "OFFERED"
    assert offered["current_appearance_fee_cents"] == 400_000

    drafts, meta = validate_paginated(
        api_client.list_invitations(DIRECTOR,
                                   {"race_edition_id": scenario["edition"]["id"],
                                    "status": "DRAFT"})
    )
    assert meta["total_count"] == 3, "the three refused invitations are still drafts"
    assert all(row["offer_sent_at"] is None for row in drafts)
