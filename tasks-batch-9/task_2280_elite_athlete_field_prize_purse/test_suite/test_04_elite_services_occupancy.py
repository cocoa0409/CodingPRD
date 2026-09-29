"""Bibs, fluid-table positions and paced kilometres as contested resources."""
from test_helpers import (
    ApiErrorId,
    DIRECTOR,
    api_client,
    assign_bib,
    create_fluid_station_slot_payload,
    create_pacer_assignment_payload,
    enroll_accepted_invitation,
    enroll_bibbed_invitation,
    list_fluid_slots,
    read_invitation,
    register_agent,
    register_pacer,
    reserve_fluid_slot,
    setup_field_open_edition,
    validate_error,
    validate_paginated,
    withdraw_invitation,
)

MODEST_OFFER = {
    "appearance_fee_cents": 900_000,
    "air_class": "ECONOMY",
    "hotel_nights": 2,
    "ground_transport": False,
}


def _three_bibbed_starters():
    """Three bibbed ELITE MALE starters; the first already holds table positions
    3 through 4 at the 10 kilometre station."""
    scenario = setup_field_open_edition(
        standards=[{"division": "ELITE", "gender": "MALE",
                    "bib_range_start": 11, "bib_range_end": 20}],
        name="Fluid Table Marathon",
        appearance_budget_cents=9_000_000,
        total_purse_cents=3_000_000,
        bonus_pool_cap_cents=0,
    )
    edition_id = scenario["edition"]["id"]
    agent = register_agent(agency_name="Hydration Reps")
    starters = [
        enroll_bibbed_invitation(
            edition_id, offer=MODEST_OFFER, agent=agent,
            athlete_overrides={"country_code": "USA"},
            performance_overrides={"performance_seconds": seconds},
        )
        for seconds in (7_900, 7_910, 7_920)
    ]
    scenario["starters"] = starters
    scenario["slot_a"] = reserve_fluid_slot(
        starters[0]["invitation"]["id"], station_km=10.0, table_position=3,
        bottle_count=2,
    )
    return scenario


def test_fluid_reservations_must_leave_one_free_position_between_them():
    """Positions 3-4 block 5-6 but admit 6-7, so a touching neighbour is illegal.

    PRD §3.5: "The rule is not simple intersection: two reservations must leave at
    least one free position between them, so a new reservation conflicts with an
    existing one unless the earlier one's last position is at least two positions
    below the later one's first position. Positions 3 through 4 and positions 5
    through 6 therefore conflict, because nothing free separates them, while
    positions 3 through 4 and positions 6 through 7 coexist, because position 5 stays
    free."

    Design: Difficulty/resource_temporal_overlap/overlap_fluid_station_closed_integer_interval_with_adjacency_buffer
    """
    scenario = _three_bibbed_starters()
    second_invitation_id = scenario["starters"][1]["invitation"]["id"]

    touching = api_client.create_fluid_station_slot(
        create_fluid_station_slot_payload(second_invitation_id, station_km=10.0,
                                         table_position=5, bottle_count=2),
        DIRECTOR,
    )
    validate_error(touching, ApiErrorId.ERR_FLUID_SLOT_CONFLICT.value, 409)

    separated = reserve_fluid_slot(second_invitation_id, station_km=10.0,
                                   table_position=6, bottle_count=2)
    assert separated["status"] == "RESERVED"
    assert separated["occupied_from"] == 6
    assert separated["occupied_to"] == 7


def test_fluid_occupancy_is_per_station_and_bounded_at_position_forty():
    """The same positions are free at another station, and 39 through 41 is malformed.

    PRD §3.5: "Conflict is then tested against the `RESERVED` reservations at the
    same `station_km` whose owning invitations belong to the same edition;
    reservations in `RELEASED` never conflict, and reservations at a different station
    or in a different edition are irrelevant." PRD §2.11 priority 4 rejects the
    over-long reservation first: "the last table position occupied (`table_position`
    plus `bottle_count` minus one) not beyond 40; `station_km` one of the allowed station
    marks", and the priority closes with "Otherwise `ERR_INVALID_REQUEST` (400). Applies
    to every endpoint."

    Design: Difficulty/resource_temporal_overlap/overlap_fluid_station_closed_integer_interval_with_adjacency_buffer
    """
    scenario = _three_bibbed_starters()
    third_invitation_id = scenario["starters"][2]["invitation"]["id"]

    elsewhere = reserve_fluid_slot(third_invitation_id, station_km=20.0,
                                  table_position=3, bottle_count=2)
    assert elsewhere["status"] == "RESERVED", (
        "positions 3 and 4 are free at the 20 kilometre station"
    )

    beyond_table = api_client.create_fluid_station_slot(
        create_fluid_station_slot_payload(third_invitation_id, station_km=10.0,
                                         table_position=39, bottle_count=3),
        DIRECTOR,
    )
    validate_error(beyond_table, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_released_fluid_positions_become_reusable():
    """A withdrawal frees the positions it held for another athlete to take.

    PRD §3.4: a withdrawal from `ACCEPTED` "moves every fluid-station reservation
    belonging to the invitation from `RESERVED` to `RELEASED`", and PRD §3.5 adds that
    "reservations in `RELEASED` never conflict".

    Design: Difficulty/resource_temporal_overlap/overlap_fluid_station_closed_integer_interval_with_adjacency_buffer
    """
    scenario = _three_bibbed_starters()
    first_invitation_id = scenario["starters"][0]["invitation"]["id"]
    second_invitation_id = scenario["starters"][1]["invitation"]["id"]
    third_invitation_id = scenario["starters"][2]["invitation"]["id"]
    reserve_fluid_slot(second_invitation_id, station_km=10.0, table_position=6,
                       bottle_count=2)

    withdraw_invitation(first_invitation_id, reason="illness")

    slots, meta = list_fluid_slots(first_invitation_id)
    assert meta["total_count"] == 1
    assert slots[0]["status"] == "RELEASED"

    reissued = reserve_fluid_slot(third_invitation_id, station_km=10.0,
                                 table_position=3, bottle_count=2)
    assert reissued["status"] == "RESERVED", (
        "positions 3 and 4 are reusable, and position 5 still separates them from "
        "the surviving reservation at 6 through 7"
    )


def _edition_with_one_paced_half():
    """A `FIELD_OPEN` edition where licence PC-1 already paces 0.0 up to 21.0."""
    scenario = setup_field_open_edition(
        standards=[{"division": "ELITE", "gender": "MALE",
                    "bib_range_start": 11, "bib_range_end": 20}],
        name="Pacing Range Marathon",
        appearance_budget_cents=9_000_000,
        total_purse_cents=3_000_000,
        bonus_pool_cap_cents=0,
    )
    scenario["first_leg"] = register_pacer(
        scenario["edition"]["id"], pacer_license_code="PC-1", start_km=0.0,
        end_km=21.0, pacer_name="Pace One", target_pace_seconds_per_km=175,
    )
    return scenario


def test_half_open_pacing_ranges_may_abut_but_may_not_overlap():
    """A range starting 0.1 km early conflicts; one starting exactly at 21.0 does not.

    PRD §3.5: "Two arrangements conflict only when they belong to the same edition
    and the same `pacer_license_code` and their half-open ranges genuinely overlap —
    that is, when the new range starts before the existing one ends and the existing
    one starts before the new one ends. There is no buffer, so abutting ranges are
    legal and one pacer may hold both 0 through 21.0 and 21.0 through 32.0."

    Design: Difficulty/resource_temporal_overlap/overlap_pacer_half_open_km_range_with_legal_adjacency
    """
    scenario = _edition_with_one_paced_half()
    edition_id = scenario["edition"]["id"]

    overlapping = api_client.create_pacer_assignment(
        create_pacer_assignment_payload(
            edition_id, pacer_license_code="PC-1", start_km=20.9, end_km=32.0,
            pacer_name="Pace One", target_pace_seconds_per_km=178,
        ),
        DIRECTOR,
    )
    validate_error(overlapping, ApiErrorId.ERR_PACING_RANGE_CONFLICT.value, 409)

    abutting = register_pacer(
        edition_id, pacer_license_code="PC-1", start_km=21.0, end_km=32.0,
        pacer_name="Pace One", target_pace_seconds_per_km=178,
    )
    assert float(abutting["start_km"]) == 21.0
    assert float(abutting["end_km"]) == 32.0


def test_pacing_may_reach_thirty_two_kilometres_and_no_further():
    """An `end_km` of exactly 32.0 is admitted while 33.0 is refused.

    PRD §3.5: "Pacing on this course stops at 32.0 kilometres, well short of the
    42.195-kilometre race distance; an `end_km` exactly equal to 32.0 is admitted
    while anything beyond it is refused with `ERR_PACING_BEYOND_LIMIT`, and this
    ceiling is a business rule rather than a schema bound."

    Design: Difficulty/resource_temporal_overlap/overlap_pacer_half_open_km_range_with_legal_adjacency
    """
    scenario = _edition_with_one_paced_half()
    edition_id = scenario["edition"]["id"]

    to_the_limit = register_pacer(
        edition_id, pacer_license_code="PC-1", start_km=21.0, end_km=32.0,
        pacer_name="Pace One", target_pace_seconds_per_km=178,
    )
    assert float(to_the_limit["end_km"]) == 32.0

    beyond = api_client.create_pacer_assignment(
        create_pacer_assignment_payload(
            edition_id, pacer_license_code="PC-1", start_km=32.0, end_km=33.0,
            pacer_name="Pace One", target_pace_seconds_per_km=180,
        ),
        DIRECTOR,
    )
    validate_error(beyond, ApiErrorId.ERR_PACING_BEYOND_LIMIT.value, 422)


def test_pacing_occupancy_is_scoped_to_one_licence_code():
    """A second licence may pace the identical kilometres.

    PRD §3.5: "Arrangements of a different licence code never conflict." The
    edition's arrangements are readable as a list, and PRD §2.3 fixes what the window
    reports: "`total_count` is the number of matching rows before the window is
    applied".

    Design: Difficulty/resource_temporal_overlap/overlap_pacer_half_open_km_range_with_legal_adjacency
    """
    scenario = _edition_with_one_paced_half()
    edition_id = scenario["edition"]["id"]
    register_pacer(edition_id, pacer_license_code="PC-1", start_km=21.0, end_km=32.0,
                   pacer_name="Pace One", target_pace_seconds_per_km=178)

    other_licence = register_pacer(
        edition_id, pacer_license_code="PC-2", start_km=0.0, end_km=21.0,
        pacer_name="Pace Two", target_pace_seconds_per_km=175,
    )
    assert other_licence["pacer_license_code"] == "PC-2"

    assignments, meta = validate_paginated(
        api_client.list_pacer_assignments(edition_id, DIRECTOR)
    )
    assert meta["total_count"] == 3, (
        "exactly the three accepted arrangements exist"
    )
    assert len(assignments) == 3


def _single_bib_pool_with_a_non_compliant_athlete():
    """A one-bib pool already consumed, and a second accepted athlete who has not
    filed whereabouts."""
    scenario = setup_field_open_edition(
        standards=[{"division": "ELITE", "gender": "MALE",
                    "bib_range_start": 11, "bib_range_end": 11}],
        name="Bib Pool Priority Marathon",
        appearance_budget_cents=8_000_000,
        total_purse_cents=3_000_000,
        bonus_pool_cap_cents=0,
    )
    edition_id = scenario["edition"]["id"]
    agent = register_agent(agency_name="Bib Pool Agency")
    compliant = enroll_accepted_invitation(
        edition_id, offer=MODEST_OFFER, agent=agent,
        athlete_overrides={"country_code": "USA", "whereabouts_filed": True},
        performance_overrides={"performance_seconds": 7_900},
    )
    unfiled = enroll_accepted_invitation(
        edition_id, offer=MODEST_OFFER, agent=agent,
        athlete_overrides={"country_code": "USA", "whereabouts_filed": False},
        performance_overrides={"performance_seconds": 7_910},
    )
    compliant["invitation"] = assign_bib(compliant["invitation"]["id"])
    scenario["compliant"] = compliant
    scenario["unfiled"] = unfiled
    return scenario


def test_bib_assignment_screens_doping_compliance_before_the_pool():
    """The availability gate outranks pool exhaustion on the same request.

    PRD §2.11 priority 12: "**Anti-doping and representation gates.** Bib assignment
    requires the athlete to be doping-compliant, else
    `ERR_ATHLETE_NOT_DOPING_COMPLIANT`". Pool availability is later, at priority 14:
    "**Occupancy, capacity and uniqueness.** The negotiation round cap, the qualifying
    standard's existence and satisfaction, bib pool availability and single-assignment",
    whose codes include "`ERR_BIB_POOL_EXHAUSTED`, `ERR_BIB_ALREADY_ASSIGNED`". PRD §3.5
    defines the gate: "An athlete is **doping-compliant** for an edition when three things
    hold at once: `whereabouts_filed` is true; the number of that athlete's doping tests in
    `MISSED` whose `window_end_at` falls on or after the day 365 days before the edition's
    `race_date` is strictly fewer than two, so it is the second recent missed test that
    breaks compliance rather than the first; and no doping test exists for that athlete in
    that edition with status `ADVERSE`."

    Design: Difficulty/priority_pair_validation_conflict/priority_doping_compliance_beats_bib_pool_exhaustion
    """
    scenario = _single_bib_pool_with_a_non_compliant_athlete()
    assert scenario["compliant"]["invitation"]["bib_number"] == 11, (
        "the only bib in the pool is taken"
    )

    response = api_client.assign_bib(scenario["unfiled"]["invitation"]["id"], DIRECTOR)
    validate_error(response, ApiErrorId.ERR_ATHLETE_NOT_DOPING_COMPLIANT.value, 422)


def test_refused_bib_assignment_changes_nothing():
    """The pool was genuinely exhausted, and the refusal left both invitations alone.

    PRD §3.5: "The eligible pool is every integer from `bib_range_start` through
    `bib_range_end` inclusive on the division standard matching this invitation's
    edition, division and the athlete's gender. From that pool the server excludes
    every bib currently held by an `ACCEPTED` invitation of the same edition — and
    only of the same edition." With one number in the pool and one holder, nothing
    remains, so the second violation on the refused request was real.

    Design: Difficulty/priority_pair_validation_conflict/priority_doping_compliance_beats_bib_pool_exhaustion
    """
    scenario = _single_bib_pool_with_a_non_compliant_athlete()
    unfiled_id = scenario["unfiled"]["invitation"]["id"]

    response = api_client.assign_bib(unfiled_id, DIRECTOR)
    validate_error(response, ApiErrorId.ERR_ATHLETE_NOT_DOPING_COMPLIANT.value, 422)

    unfiled = read_invitation(unfiled_id)
    assert unfiled["bib_number"] is None
    assert unfiled["status"] == "ACCEPTED"
    assert read_invitation(
        scenario["compliant"]["invitation"]["id"]
    )["bib_number"] == 11
