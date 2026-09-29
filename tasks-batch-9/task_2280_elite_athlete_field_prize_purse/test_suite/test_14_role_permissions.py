"""Role walls: what each role may not do, and what an agent may not do to a peer's deal."""
from test_helpers import (
    ApiErrorId,
    DIRECTOR,
    FINANCE,
    SANCTIONING,
    TECHNICAL,
    api_client,
    create_invitation,
    create_race_edition_payload,
    create_verified_performance,
    make_athlete_agent_headers,
    negotiation_round_payload,
    open_field,
    read_athlete,
    read_edition,
    read_invitation,
    register_agent,
    register_athlete,
    send_offer,
    setup_configured_edition,
    setup_field_open_edition,
    submit_performance,
    validate_error,
    validate_paginated,
    validate_success,
)

ELITE_MALE_STANDARD = {"division": "ELITE", "gender": "MALE",
                       "max_qualifying_seconds": 8_100,
                       "bib_range_start": 11, "bib_range_end": 20}
OVERALL_MALE_FIRST = {"category": "OVERALL", "gender": "MALE", "place": 1,
                      "amount_cents": 1_000_000}
STANDARD_OFFER = {"appearance_fee_cents": 400_000, "air_class": "ECONOMY",
                  "hotel_nights": 2, "ground_transport": False}
AGENT_COUNTER = {"appearance_fee_cents": 900_000, "air_class": "BUSINESS",
                 "hotel_nights": 4, "ground_transport": True}
STRANGER = make_athlete_agent_headers("agent-x")


def _planning_edition_with_a_submitted_time():
    """A `PLANNING` edition, one athlete and one performance record still awaiting
    adjudication."""
    scenario = setup_configured_edition(
        purse_lines=[OVERALL_MALE_FIRST],
        standards=[ELITE_MALE_STANDARD],
        name="Role Wall Marathon",
        appearance_budget_cents=9_000_000,
        total_purse_cents=3_000_000,
        bonus_pool_cap_cents=0,
    )
    scenario["athlete"] = register_athlete(full_name="Wall Walter", country_code="USA",
                                          gender="MALE", birth_date="1997-06-01")
    scenario["record"] = submit_performance(
        scenario["athlete"]["id"], race_name="Qual RW",
        performance_date="2026-03-01", performance_seconds=7_900, division="ELITE",
        sanctioning_ref="SB-RW-1", chip_timed=True,
    )
    return scenario


def test_no_role_may_reach_across_into_another_roles_operations():
    """Five crossings are refused, nothing moves, and the owning role still succeeds.

    PRD §2.1: "If the headers are well formed but the declared role is not among the
    roles authorized for the endpoint being called (see the table in §4), the request
    fails with `ERR_ROLE_NOT_PERMITTED`." The ownership of each operation is declared in
    §2.1 as well: "A `TechnicalOfficial` is the chief referee and technical delegate: it
    verifies claimed qualifying times, opens the race, enters and certifies results,
    disqualifies for assistance or course violations, and lodges record ratification
    packages." and "The `AntiDopingLiaison` is the committee's anti-doping coordinator,
    scheduling tests inside declared athlete availability windows and collecting
    samples." and "The `FinanceOfficer` maintains withholding profiles, generates the
    award set, approves and pays prizes, and settles the purse." PRD §2.11 priority 2
    fixes the status: "The declared role appears in the called endpoint's authorized-role
    list in §4, else `ERR_ROLE_NOT_PERMITTED` (403). Applies to every endpoint."

    Design: Corner/rbac/corner_rbac_exclusive_operations_refuse_every_other_role
    """
    scenario = _planning_edition_with_a_submitted_time()
    edition_id = scenario["edition"]["id"]

    agent_invents_a_race = api_client.create_race_edition(
        create_race_edition_payload(name="Agent Invented Race", city="Nowhere",
                                   race_date="2026-12-01",
                                   appearance_budget_cents=1_000,
                                   total_purse_cents=1_000,
                                   bonus_pool_cap_cents=0),
        STRANGER,
    )
    validate_error(agent_invents_a_race, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    director_verifies_a_time = api_client.verify_performance_record(
        scenario["record"]["id"], {"decision": "VERIFIED", "official_seconds": 7_900},
        DIRECTOR,
    )
    validate_error(director_verifies_a_time, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    finance_schedules_a_test = api_client.create_doping_test(
        {"athlete_id": scenario["athlete"]["id"], "race_edition_id": edition_id,
         "test_type": "OUT_OF_COMPETITION",
         "window_start_at": "2026-10-01T08:00:00Z",
         "window_end_at": "2026-10-01T18:00:00Z", "sample_code": "S-RW-1"},
        FINANCE,
    )
    validate_error(finance_schedules_a_test, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    director_touches_the_money = api_client.update_tax_profile(
        scenario["athlete"]["id"], {"w8ben_on_file": True}, DIRECTOR
    )
    validate_error(director_touches_the_money,
                   ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    finance_opens_the_field = api_client.open_field(edition_id, FINANCE)
    validate_error(finance_opens_the_field, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    records, _meta = validate_paginated(
        api_client.list_performance_records(scenario["athlete"]["id"], TECHNICAL)
    )
    assert records[0]["verification_status"] == "SUBMITTED"
    assert read_athlete(scenario["athlete"]["id"])["w8ben_on_file"] is False
    assert read_edition(edition_id)["status"] == "PLANNING"

    assert open_field(edition_id)["status"] == "FIELD_OPEN"


def test_the_shared_read_surface_stays_open_to_every_listed_role():
    """Three reads from three different roles all succeed on the same edition.

    PRD §4 declares the readers of each list: "| GET | `/race-editions/{id}` | Read one
    edition including its computed ledger fields | ElitesDirector, FinanceOfficer,
    TechnicalOfficial, AntiDopingLiaison, SanctioningBody, AthleteAgent |", "| GET |
    `/race-editions/{id}/division-standards` | List the qualifying standards and bib
    pools of an edition | ElitesDirector, FinanceOfficer, TechnicalOfficial,
    AthleteAgent |" and "| GET | `/race-editions/{id}/purse-lines` | List the purse
    structure of an edition | ElitesDirector, FinanceOfficer, TechnicalOfficial |".

    Design: Corner/rbac/corner_rbac_exclusive_operations_refuse_every_other_role
    """
    scenario = _planning_edition_with_a_submitted_time()
    edition_id = scenario["edition"]["id"]
    open_field(edition_id)

    by_the_sanctioning_body = validate_success(
        api_client.get_race_edition(edition_id, SANCTIONING)
    )
    assert by_the_sanctioning_body["status"] == "FIELD_OPEN"

    standards, standards_meta = validate_paginated(
        api_client.list_division_standards(edition_id, STRANGER, {"division": "ELITE"})
    )
    assert standards_meta["total_count"] == 1
    assert standards[0]["division"] == "ELITE"

    lines, lines_meta = validate_paginated(
        api_client.list_purse_lines(edition_id, FINANCE, {"category": "OVERALL"})
    )
    assert lines_meta["total_count"] == 1
    assert lines[0]["category"] == "OVERALL"


def _one_offered_invitation_and_a_rival_agency():
    """An `OFFERED` invitation belonging to agent one, plus an unrelated agent two."""
    scenario = setup_field_open_edition(
        purse_lines=[OVERALL_MALE_FIRST],
        standards=[ELITE_MALE_STANDARD],
        name="Peer Agent Marathon",
        appearance_budget_cents=9_000_000,
        total_purse_cents=3_000_000,
        bonus_pool_cap_cents=0,
    )
    edition_id = scenario["edition"]["id"]
    scenario["agent_one"] = register_agent(agency_name="Agent One Group",
                                         license_code="AGT-PA-1")
    scenario["agent_two"] = register_agent(agency_name="Agent Two Group",
                                         license_code="AGT-PA-2")
    athlete = register_athlete(full_name="Peer Pete", country_code="USA",
                              gender="MALE", birth_date="1997-07-01")
    record = create_verified_performance(
        athlete["id"], race_name="Qual PA", performance_date="2026-03-01",
        performance_seconds=7_900, division="ELITE", sanctioning_ref="SB-PA-1",
        chip_timed=True,
    )
    invitation = create_invitation(edition_id, athlete["id"],
                                  scenario["agent_one"]["id"], record["id"], "ELITE")
    scenario["invitation"] = send_offer(invitation["id"], **STANDARD_OFFER)
    return scenario


def test_a_rival_agent_can_neither_counter_nor_answer_a_deal_it_does_not_hold():
    """Agent two passes the role gate and fails on identity, twice.

    PRD §2.1: "When `X-User-Role` is `AthleteAgent`, `X-User-ID` is the `id` of the
    acting `RepAgent`; ownership checks on any resource that references a `RepAgent`
    compare the resource's foreign-key field to `X-User-ID` — concretely, an
    invitation-scoped write by an `AthleteAgent` requires `X-User-ID` to equal that
    invitation's `agent_id`, and a mismatch is rejected with
    `ERR_NOT_INVITATION_AGENT`." PRD §2.11 priority 5 places that check ahead of the
    version check of priority 10: "When the acting role is `AthleteAgent` on an
    invitation-scoped write, `X-User-ID` must equal that invitation's `agent_id`, else
    `ERR_NOT_INVITATION_AGENT` (403). This guards exactly two operations: appending a
    negotiation round, and responding to terms."

    Design: Corner/rbac/corner_rbac_peer_agents_cannot_act_on_each_others_invitations
    """
    scenario = _one_offered_invitation_and_a_rival_agency()
    invitation = scenario["invitation"]
    rival = make_athlete_agent_headers(scenario["agent_two"]["id"])

    stolen_answer = api_client.respond_to_invitation(
        invitation["id"], {"decision": "ACCEPT"}, rival
    )
    validate_error(stolen_answer, ApiErrorId.ERR_NOT_INVITATION_AGENT.value, 403)

    stolen_counter = api_client.create_negotiation_round(
        invitation["id"],
        negotiation_round_payload(invitation["version"], **AGENT_COUNTER),
        rival,
    )
    validate_error(stolen_counter, ApiErrorId.ERR_NOT_INVITATION_AGENT.value, 403)

    untouched = read_invitation(invitation["id"])
    assert untouched["status"] == "OFFERED"
    assert untouched["version"] == invitation["version"]
    assert untouched["current_appearance_fee_cents"] == 400_000


def test_the_rightful_agent_makes_the_only_agent_side_round_on_the_record():
    """The same call from agent one is accepted and is the only `AGENT` round stored.

    PRD §3.3: "From `OFFERED` only the `AthleteAgent` may append a round, which moves the
    invitation `OFFERED → COUNTERED`". The round is numbered from the tally: "A successful
    append writes a round whose `round_number` is one more than the previous `round_count`
    and whose `side` is derived from the acting role, `COMMITTEE` for the director and
    `AGENT` for the agent". The opening offer already wrote round one, because "Sending
    the offer writes the first **negotiation round**, with `side` set to `COMMITTEE` and
    `round_number` 1". The history "can be read in ascending `round_number` and filtered
    by `side`".

    Design: Corner/rbac/corner_rbac_peer_agents_cannot_act_on_each_others_invitations
    """
    scenario = _one_offered_invitation_and_a_rival_agency()
    invitation = scenario["invitation"]
    rival = make_athlete_agent_headers(scenario["agent_two"]["id"])
    validate_error(
        api_client.create_negotiation_round(
            invitation["id"],
            negotiation_round_payload(invitation["version"], **AGENT_COUNTER),
            rival,
        ),
        ApiErrorId.ERR_NOT_INVITATION_AGENT.value, 403,
    )

    round_two = validate_success(
        api_client.create_negotiation_round(
            invitation["id"],
            negotiation_round_payload(invitation["version"], **AGENT_COUNTER),
            make_athlete_agent_headers(scenario["agent_one"]["id"]),
        ),
        201,
    )
    assert round_two["side"] == "AGENT"
    assert round_two["round_number"] == 2
    assert read_invitation(invitation["id"])["status"] == "COUNTERED"

    agent_side, meta = validate_paginated(
        api_client.list_negotiation_rounds(invitation["id"], FINANCE,
                                          {"side": "AGENT"})
    )
    assert meta["total_count"] == 1, "the rival's two attempts stored no round"
    assert agent_side[0]["round_number"] == 2
