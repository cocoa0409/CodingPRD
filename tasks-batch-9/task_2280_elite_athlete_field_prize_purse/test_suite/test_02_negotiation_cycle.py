"""The alternating offer/counter cycle, its round allowance and its deadline."""
from test_helpers import (
    ApiErrorId,
    DIRECTOR,
    agent_counters,
    api_client,
    assert_appearance_ledger,
    assert_negotiation_round,
    committee_counters,
    enroll_offered_invitation,
    make_athlete_agent_headers,
    negotiation_round_payload,
    read_edition,
    read_invitation,
    respond_as_director,
    set_clock,
    setup_field_open_edition,
    validate_error,
    validate_paginated,
)

OPENING_OFFER = {
    "appearance_fee_cents": 1_500_000,
    "air_class": "ECONOMY",
    "hotel_nights": 3,
    "ground_transport": False,
}
AGENT_ROUND_2 = {
    "appearance_fee_cents": 2_500_000,
    "air_class": "BUSINESS",
    "hotel_nights": 7,
    "ground_transport": True,
}
COMMITTEE_ROUND_3 = {
    "appearance_fee_cents": 1_900_000,
    "air_class": "PREMIUM_ECONOMY",
    "hotel_nights": 6,
    "ground_transport": True,
}
AGENT_ROUND_4 = {
    "appearance_fee_cents": 2_000_000,
    "air_class": "BUSINESS",
    "hotel_nights": 5,
    "ground_transport": True,
}
# 2,000,000 fee + 540,000 BUSINESS air + 5 nights x 32,000 + 18,000 ground
ROUND_4_GUARANTEED_CENTS = 2_718_000


def _haggling_invitation():
    """An `OFFERED` invitation on an edition whose per-side round allowance is two,
    so the total round tally may never reach four."""
    scenario = setup_field_open_edition(
        standards=[{"division": "ELITE", "gender": "MALE",
                    "bib_range_start": 11, "bib_range_end": 20}],
        name="Negotiation Cycle Marathon",
        appearance_budget_cents=5_000_000,
        total_purse_cents=5_000_000,
        bonus_pool_cap_cents=0,
        max_negotiation_rounds=2,
    )
    entrant = enroll_offered_invitation(
        scenario["edition"]["id"],
        offer=OPENING_OFFER,
        athlete_overrides={"country_code": "USA"},
        performance_overrides={"performance_seconds": 7_900},
    )
    scenario["entrant"] = entrant
    return scenario


def test_negotiation_returns_to_offered_after_a_committee_counter():
    """The cycle `OFFERED → COUNTERED → OFFERED` is walked twice over, alternating sides.

    PRD §3.3: "From `OFFERED` only the `AthleteAgent` may append a round, which
    moves the invitation `OFFERED → COUNTERED`; from `COUNTERED` only the
    `ElitesDirector` may append one, which moves it `COUNTERED → OFFERED`. The cycle
    `OFFERED → COUNTERED → OFFERED` may repeat until the round allowance is used
    up." Each append "writes a round whose `round_number` is one more than the
    previous `round_count` and whose `side` is derived from the acting role,
    `COMMITTEE` for the director and `AGENT` for the agent; replaces all four
    `current_` term fields with the newly proposed ones".

    Design: Difficulty/non_linear_state_machine/invitation_negotiation_cycle_offered_countered_to_round_cap
    """
    scenario = _haggling_invitation()
    invitation_id = scenario["entrant"]["invitation"]["id"]
    agent_id = scenario["entrant"]["agent"]["id"]

    round_two = agent_counters(invitation_id, agent_id, **AGENT_ROUND_2)
    assert_negotiation_round(round_two)
    assert round_two["round_number"] == 2
    assert round_two["side"] == "AGENT"

    countered = read_invitation(invitation_id)
    assert countered["status"] == "COUNTERED"
    assert countered["round_count"] == 2
    assert countered["current_appearance_fee_cents"] == 2_500_000
    assert countered["current_air_class"] == "BUSINESS"
    assert countered["current_hotel_nights"] == 7
    assert countered["current_ground_transport"] is True

    round_three = committee_counters(invitation_id, **COMMITTEE_ROUND_3)
    assert round_three["round_number"] == 3
    assert round_three["side"] == "COMMITTEE"

    reoffered = read_invitation(invitation_id)
    assert reoffered["status"] == "OFFERED", (
        "the committee's counter returns the invitation to OFFERED, which a "
        "forward-only chain could never do"
    )
    assert reoffered["round_count"] == 3
    assert reoffered["current_appearance_fee_cents"] == 1_900_000
    assert reoffered["current_air_class"] == "PREMIUM_ECONOMY"


def test_fifth_round_is_refused_once_the_allowance_is_exhausted():
    """The tally may not reach twice the per-side allowance, and the history stays at four.

    PRD §3.3: each append "requires the invitation's `round_count` to be strictly
    below twice the edition's `max_negotiation_rounds`; once the tally has reached
    that ceiling the append is refused with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`." PRD
    §2.3 adds that "The single documented exception is the negotiation history of an
    invitation, which is returned in ascending `round_number`".

    Design: Difficulty/non_linear_state_machine/invitation_negotiation_cycle_offered_countered_to_round_cap
    """
    scenario = _haggling_invitation()
    invitation_id = scenario["entrant"]["invitation"]["id"]
    agent_id = scenario["entrant"]["agent"]["id"]

    agent_counters(invitation_id, agent_id, **AGENT_ROUND_2)
    committee_counters(invitation_id, **COMMITTEE_ROUND_3)
    round_four = agent_counters(invitation_id, agent_id, **AGENT_ROUND_4)
    assert round_four["round_number"] == 4
    assert round_four["side"] == "AGENT"
    assert read_invitation(invitation_id)["status"] == "COUNTERED"

    payload = negotiation_round_payload(
        read_invitation(invitation_id)["version"],
        appearance_fee_cents=2_100_000, air_class="BUSINESS", hotel_nights=5,
        ground_transport=True,
    )
    response = api_client.create_negotiation_round(invitation_id, payload, DIRECTOR)
    validate_error(response, ApiErrorId.ERR_NEGOTIATION_ROUNDS_EXHAUSTED.value, 409)

    rounds, meta = validate_paginated(
        api_client.list_negotiation_rounds(invitation_id, DIRECTOR)
    )
    assert meta["total_count"] == 4, "the refused append wrote no round"
    assert [entry["round_number"] for entry in rounds] == [1, 2, 3, 4]
    assert [entry["side"] for entry in rounds] == [
        "COMMITTEE", "AGENT", "COMMITTEE", "AGENT",
    ]


def test_accepting_at_the_round_cap_commits_the_last_round_terms():
    """An invitation at the round cap is still alive and accepts on round four's terms.

    PRD §3.4: "from `COUNTERED` it comes from the `ElitesDirector` accepting or
    refusing the agent's counter." The valuation reads the superseded package, since
    a round "replaces all four `current_` term fields with the newly proposed ones"
    and "That valuation is built from the invitation's four `current_` term fields."

    Design: Difficulty/non_linear_state_machine/invitation_negotiation_cycle_offered_countered_to_round_cap
    """
    scenario = _haggling_invitation()
    invitation_id = scenario["entrant"]["invitation"]["id"]
    agent_id = scenario["entrant"]["agent"]["id"]

    agent_counters(invitation_id, agent_id, **AGENT_ROUND_2)
    committee_counters(invitation_id, **COMMITTEE_ROUND_3)
    agent_counters(invitation_id, agent_id, **AGENT_ROUND_4)

    accepted = respond_as_director(invitation_id, "ACCEPT")
    assert accepted["status"] == "ACCEPTED"
    assert accepted["guaranteed_commitment_cents"] == ROUND_4_GUARANTEED_CENTS, (
        "the terms of the last round in the cycle are the ones committed"
    )

    assert_appearance_ledger(read_edition(scenario["edition"]["id"]),
                             ROUND_4_GUARANTEED_CENTS, 2_282_000)


def _countered_invitation_past_its_deadline():
    """A `COUNTERED` invitation whose response window lapsed five days ago."""
    scenario = setup_field_open_edition(
        standards=[{"division": "ELITE", "gender": "MALE",
                    "bib_range_start": 11, "bib_range_end": 20}],
        name="Deadline Priority Marathon",
        appearance_budget_cents=8_000_000,
        total_purse_cents=3_000_000,
        bonus_pool_cap_cents=0,
    )
    entrant = enroll_offered_invitation(
        scenario["edition"]["id"],
        offer={"appearance_fee_cents": 900_000, "air_class": "ECONOMY",
               "hotel_nights": 2, "ground_transport": False},
        athlete_overrides={"country_code": "USA"},
        performance_overrides={"performance_seconds": 7_960},
    )
    agent_counters(
        entrant["invitation"]["id"], entrant["agent"]["id"],
        appearance_fee_cents=1_400_000, air_class="BUSINESS", hotel_nights=4,
        ground_transport=True,
    )
    set_clock("2026-08-20T00:00:00Z")
    scenario["entrant"] = entrant
    return scenario


def test_agent_responding_from_countered_is_refused_out_of_turn():
    """Acting from the wrong side of the cycle outranks the lapsed response window.

    PRD §2.11 priority 9 is "**Turn-taking.** Which side may act depends on the
    invitation's current state: from `OFFERED` only an `AthleteAgent` may act, from
    `COUNTERED` only an `ElitesDirector` may act. The rule governs both responding to
    terms and appending a negotiation round, and a violation is
    `ERR_ROLE_NOT_PERMITTED_FROM_STATE` (403)." The deadline rule sits later, at
    priority 13: "A negotiation round or a response must arrive at or before the
    invitation's `response_deadline_at`, else `ERR_OFFER_DEADLINE_PASSED`". The
    window opened at the clock's start instant and ran for the default
    `offer_response_days` of 14 days.

    Design: Difficulty/priority_pair_validation_conflict/priority_role_from_state_beats_offer_deadline_lapse
    """
    scenario = _countered_invitation_past_its_deadline()
    invitation_id = scenario["entrant"]["invitation"]["id"]
    invitation = read_invitation(invitation_id)
    assert invitation["response_deadline_at"].startswith("2026-08-15T00:00:00"), (
        "the deadline is the logical clock plus the edition's offer_response_days, "
        f"got {invitation['response_deadline_at']}"
    )

    response = api_client.respond_to_invitation(
        invitation_id, {"decision": "ACCEPT"},
        make_athlete_agent_headers(scenario["entrant"]["agent"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED_FROM_STATE.value, 403)


def test_state_appropriate_role_still_meets_the_lapsed_deadline():
    """The temporal violation was live all along; it was merely outranked.

    PRD §2.11 priority 13: "**Clock-relative windows.** A negotiation round or a
    response must arrive at or before the invitation's `response_deadline_at`, else
    `ERR_OFFER_DEADLINE_PASSED`". PRD §2.4 explains why the invitation has not moved
    on its own: "an offer whose deadline has passed does not become `EXPIRED` on its
    own. It stays where it is until either the operational sweep visits it or the
    field is locked, at which point the expiry is recorded explicitly."

    Design: Difficulty/priority_pair_validation_conflict/priority_role_from_state_beats_offer_deadline_lapse
    """
    scenario = _countered_invitation_past_its_deadline()
    invitation_id = scenario["entrant"]["invitation"]["id"]

    agent_response = api_client.respond_to_invitation(
        invitation_id, {"decision": "ACCEPT"},
        make_athlete_agent_headers(scenario["entrant"]["agent"]["id"]),
    )
    validate_error(agent_response,
                   ApiErrorId.ERR_ROLE_NOT_PERMITTED_FROM_STATE.value, 403)

    director_response = api_client.respond_to_invitation(
        invitation_id, {"decision": "ACCEPT"}, DIRECTOR
    )
    validate_error(director_response, ApiErrorId.ERR_OFFER_DEADLINE_PASSED.value, 422)

    invitation = read_invitation(invitation_id)
    assert invitation["status"] == "COUNTERED", (
        "neither rejected response moved the invitation"
    )
    assert invitation["round_count"] == 2
    assert invitation["guaranteed_commitment_cents"] == 0
