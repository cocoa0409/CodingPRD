"""Operations whose only unmet precondition lives on a different entity: an entry
gated by a certificate in the boat registry, a protest gated by the seat count of
the panel named in its payload, and a race gated by a sibling division.

Each pair fixes the other entity and repeats the identical call, so nothing but
the cross-entity state can explain the change of answer.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    MEASUREMENT_A,
    MEASUREMENT_B,
    SAFETY_COURSE_OK_UNTIL,
    ApiErrorId,
    build_accepted_fleet_world,
    create_protest_payload,
    enrol_member,
    enrol_standard_roster,
    evidence_payload,
    form_panel,
    issue_certificate,
    make_jury_chair_headers,
    merge_division,
    read_certificate,
    read_division,
    read_entry,
    read_panel,
    read_protest,
    read_race,
    read_regatta,
    record_result,
    schedule_hearing_payload,
    seat_judge,
    set_clock,
    withdraw_entry,
)

DRAFT_ONLY_ENTRANT = (
    {
        "key": "A",
        "helm": "helm_1",
        "measurement": MEASUREMENT_A,
        "issue": False,
        "inspect": None,
        "assign": False,
        "accept": False,
    },
)


def _draft_certificate_world():
    """A submitted, crewed entry pinned to a certificate deliberately left in
    DRAFT, and a division whose band would happily accept its key."""
    return build_accepted_fleet_world(
        entrants=DRAFT_ONLY_ENTRANT,
        confirm_division_codes=(),
    )


def test_a_draft_certificate_blocks_division_assignment_from_another_aggregate(api):
    """PRD 3.5: "The selector reads the `band_key_spm` of the entry's pinned
    certificate as its key and the `boat_type` of the entry's boat, and the pinned
    certificate must be `ISSUED` at that moment or the assignment is refused with
    `ERR_CERTIFICATE_NOT_ISSUED`."

    Design: Difficulty/cross_entity_state_dependency/assign_division_requires_issued_certificate
    """
    world = _draft_certificate_world()
    entry_id = world["entries"]["A"]["id"]
    certificate = read_certificate(world["certificates"]["A"]["id"])
    assert certificate["status"] == "DRAFT"
    assert certificate["band_key_spm"] == 171.3, (
        "the key is fully computed at filing, so the selector could have matched it"
    )

    validate_error(
        api.assign_division(entry_id, world["h"]["chair"]),
        ApiErrorId.ERR_CERTIFICATE_NOT_ISSUED,
        expected_status=409,
    )

    assert read_entry(entry_id)["division_id"] is None
    assert read_division(world["divisions"]["A"]["id"])["assigned_entry_count"] == 0, (
        "the refusal left no partial write"
    )


def test_issuing_the_certificate_alone_lets_the_identical_assignment_through(api):
    """PRD 3.2: "Issuing is what makes a certificate usable, and only the measurer
    who filed it may issue it: the acting identity must equal the row's
    `measured_by_member_id`, and the logical clock must lie inside the inclusive
    window from `valid_from` to `valid_until`. The certificate then moves `DRAFT →
    ISSUED`."

    Design: Difficulty/cross_entity_state_dependency/assign_division_requires_issued_certificate
    """
    world = _draft_certificate_world()
    entry_id = world["entries"]["A"]["id"]
    chair = world["h"]["chair"]
    division_id = world["divisions"]["A"]["id"]
    validate_error(
        api.assign_division(entry_id, chair), ApiErrorId.ERR_CERTIFICATE_NOT_ISSUED
    )

    issued = issue_certificate(world["certificates"]["A"]["id"], world["ids"]["measurer"])
    assert issued["status"] == "ISSUED"
    assert issued["supersedes_certificate_id"] is None
    assert issued["band_key_spm"] == 171.3, "the selector inputs never changed"

    assigned = validate_success(api.assign_division(entry_id, chair))

    assert assigned["division_id"] == division_id
    assert assigned["registration_status"] == "SUBMITTED"
    assert assigned["inspection_status"] == "NOT_INSPECTED", (
        "the assignment reads no inspection state at all"
    )
    division = read_division(division_id)
    assert division["assigned_entry_count"] == 1
    assert division["accepted_entry_count"] == 0
    assert division["status"] == "PROVISIONAL"


SECOND_PANEL_ROSTER = {
    "jury_chair_2": {"judge_certification_level": "REGIONAL"},
    "judge_3": {"judge_certification_level": "CLUB"},
}
TWO_RATED_ENTRANTS = (
    {"key": "A", "helm": "helm_1", "measurement": MEASUREMENT_A},
    {"key": "B", "helm": "helm_2", "measurement": MEASUREMENT_B},
)


def _roster_with(**extra):
    """The standard roster plus additional members enrolled for this world."""
    roster = enrol_standard_roster()
    for key, fields in extra.items():
        roster[key] = enrol_member(**fields)
    return roster


def _two_panel_world(api):
    """One regatta, two jury panels: the first seated at quorum, the second still
    FORMING with a single chair, and a filed protest awaiting a hearing."""
    roster = _roster_with(**SECOND_PANEL_ROSTER)
    world = build_accepted_fleet_world(
        roster=roster,
        entrants=TWO_RATED_ENTRANTS,
        panel=True,
        racing=True,
        staffing=True,
        races=({"race_number": 1, "scheduled_start_utc": "2026-08-05T14:00:00Z"},),
        start_races=(1,),
    )
    world["forming_panel"] = form_panel(
        world["regatta_id"], world["ids"]["chair"], roster["jury_chair_2"]["id"]
    )
    set_clock("2026-08-05T18:00:00Z")
    pro_id = world["ids"]["pro"]
    race_id = world["races"][1]["id"]
    for key, elapsed in (("A", 5027.8), ("B", 5312.8)):
        record_result(race_id, world["entries"][key]["id"], pro_id, elapsed_seconds=elapsed)
    protest = validate_success(
        api.create_protest(
            create_protest_payload(
                race_id,
                world["entries"]["B"]["id"],
                world["entries"]["A"]["id"],
                "2026-08-05T14:20:00Z",
            ),
            world["h"]["helm_2"],
        ),
        expected_status=201,
    )
    validate_success(
        api.file_evidence(
            protest["id"],
            evidence_payload(world["entries"]["B"]["id"]),
            world["h"]["helm_2"],
        )
    )
    world["protest"] = protest
    return world


HEARING_UTC = "2026-08-05T19:00:00Z"


def test_a_forming_panel_blocks_the_hearing_even_beside_a_seated_sibling(api):
    """PRD 3.10: "The named panel must be in status `SEATED` with
    `seated_member_count` at least the regatta's `jury_quorum_required`, otherwise
    `ERR_JURY_QUORUM_NOT_MET`"

    Design: Difficulty/cross_entity_state_dependency/schedule_hearing_requires_seated_jury_panel
    """
    world = _two_panel_world(api)
    forming = world["forming_panel"]
    assert forming["status"] == "FORMING"
    assert forming["seated_member_count"] == 1
    assert world["panel"]["status"] == "SEATED", "a sibling panel of the same regatta"

    validate_error(
        api.schedule_hearing(
            world["protest"]["id"],
            schedule_hearing_payload(forming["id"], HEARING_UTC),
            make_jury_chair_headers(world["roster"]["jury_chair_2"]["id"]),
        ),
        ApiErrorId.ERR_JURY_QUORUM_NOT_MET,
        expected_status=409,
    )

    unscheduled = read_protest(world["protest"]["id"])
    assert unscheduled["status"] == "FILED"
    assert unscheduled["jury_panel_id"] is None
    assert unscheduled["hearing_utc"] is None
    assert read_panel(world["panel"]["id"])["seated_member_count"] == 2, (
        "the seated sibling was neither read nor written"
    )


def test_seating_the_second_judge_lets_the_identical_hearing_request_through(api):
    """PRD 3.10: "Once `seated_member_count` reaches the regatta's
    `jury_quorum_required`, the panel bubbles up `FORMING → SEATED`."

    Design: Difficulty/cross_entity_state_dependency/schedule_hearing_requires_seated_jury_panel
    """
    world = _two_panel_world(api)
    panel_id = world["forming_panel"]["id"]
    chair_2_id = world["roster"]["jury_chair_2"]["id"]
    jury_2 = make_jury_chair_headers(chair_2_id)
    payload = schedule_hearing_payload(panel_id, HEARING_UTC)
    validate_error(
        api.schedule_hearing(world["protest"]["id"], payload, jury_2),
        ApiErrorId.ERR_JURY_QUORUM_NOT_MET,
    )

    seated = seat_judge(panel_id, world["ids"]["chair"], world["roster"]["judge_3"]["id"])
    assert seated["status"] == "SEATED"
    assert seated["seated_member_count"] == 2
    assert [seat["seat_role"] for seat in seated["seats"]] == ["CHAIR", "MEMBER"]
    assert all(seat["recused"] is False for seat in seated["seats"])
    assert seated["version"] == 2, "one increment for the one seating"

    scheduled = validate_success(
        api.schedule_hearing(world["protest"]["id"], payload, jury_2)
    )

    assert scheduled["status"] == "HEARING_SCHEDULED"
    assert scheduled["jury_panel_id"] == panel_id
    assert scheduled["hearing_utc"] == HEARING_UTC
    assert scheduled["evidence_count"] == 1, "the refusal cost no evidence"
    assert scheduled["reopen_count"] == 0
    assert read_race(world["races"][1]["id"])["scoring_status"] == "PROVISIONAL"


NARROW = {
    "code": "NARROW",
    "boat_type_filter": "MONOHULL",
    "rating_band_low": 165.0,
    "rating_band_high": 175.0,
    "min_entries": 2,
}
WIDE = {
    "code": "WIDE",
    "boat_type_filter": "MONOHULL",
    "rating_band_low": 150.0,
    "rating_band_high": 230.0,
    "min_entries": 2,
}
FOUR_ENTRANTS = (
    {"key": "A", "helm": "helm_1", "measurement": MEASUREMENT_A},
    {"key": "B", "helm": "helm_2", "measurement": MEASUREMENT_A},
    {"key": "C", "helm": "helm_3", "measurement": MEASUREMENT_B},
    {"key": "D", "helm": "helm_4", "measurement": MEASUREMENT_B},
)


def _blocked_race_world():
    """Two confirmed divisions and a PENDING race created while both met their
    floor, then one withdrawal that drops the narrow division back to one assigned
    entry and stamps the block on the race."""
    world = build_accepted_fleet_world(
        roster=_roster_with(helm_4={"safety_course_expiry_utc": SAFETY_COURSE_OK_UNTIL}),
        divisions=(NARROW, WIDE),
        entrants=FOUR_ENTRANTS,
        panel=True,
        racing=True,
        staffing=True,
        races=({"race_number": 1, "scheduled_start_utc": "2026-08-05T14:00:00Z"},),
    )
    assert world["entries"]["A"]["division_id"] == world["divisions"]["NARROW"]["id"]
    assert world["entries"]["C"]["division_id"] == world["divisions"]["WIDE"]["id"]
    assert read_race(world["races"][1]["id"])["start_blocked_reason"] is None
    world["entries"]["B"] = withdraw_entry(
        world["entries"]["B"]["id"], world["ids"]["helm_2"]
    )
    return world


def test_a_sibling_division_under_its_floor_blocks_the_start_sequence(api):
    """PRD 3.7: "`start_blocked_reason` must be null, or the attempt is refused
    with `ERR_RACE_START_BLOCKED`"

    PRD 3.5 fixes the cascade that stamped the field: "The entry keeps its
    `division_id` for audit, but the division re-derives both counts, which may
    pull it `CONFIRMED → PROVISIONAL` and set `start_blocked_reason` to
    `DIVISION_UNDER_MINIMUM` on every `PENDING` race of the regatta."

    PRD 2.9 fixes the count that moved: "`assigned_entry_count` on a division is
    the number of entries pointing at that division whose `registration_status` is
    `SUBMITTED` or `ACCEPTED`."

    Design: Difficulty/cross_entity_state_dependency/start_sequence_blocked_while_division_reverted_to_provisional
    """
    world = _blocked_race_world()
    race_id = world["races"][1]["id"]
    narrow = read_division(world["divisions"]["NARROW"]["id"])
    assert narrow["status"] == "PROVISIONAL"
    assert narrow["assigned_entry_count"] == 1
    wide = read_division(world["divisions"]["WIDE"]["id"])
    assert wide["status"] == "CONFIRMED", "the other division still meets its floor"
    blocked = read_race(race_id)
    assert blocked["start_blocked_reason"] == "DIVISION_UNDER_MINIMUM"
    assert blocked["staffing_ready"] is True, "no staffing gate is in play here"
    assert read_regatta(world["regatta_id"])["status"] == "RACING"

    validate_error(
        api.start_sequence(race_id, world["h"]["pro"]),
        ApiErrorId.ERR_RACE_START_BLOCKED,
        expected_status=409,
    )

    refused = read_race(race_id)
    assert refused["start_status"] == "PENDING"
    assert refused["start_blocked_reason"] == "DIVISION_UNDER_MINIMUM"
    assert refused["general_recall_count"] == 0


def test_merging_the_short_division_clears_the_block_for_the_identical_start(api):
    """PRD 3.4: "Hop four clears `start_blocked_reason` to null on every race of
    the regatta that was carrying `DIVISION_UNDER_MINIMUM`, once no division of the
    regatta remains `PROVISIONAL` while holding at least one assigned entry."

    Design: Difficulty/cross_entity_state_dependency/start_sequence_blocked_while_division_reverted_to_provisional
    """
    world = _blocked_race_world()
    race_id = world["races"][1]["id"]
    narrow_id = world["divisions"]["NARROW"]["id"]
    wide_id = world["divisions"]["WIDE"]["id"]
    pro = world["h"]["pro"]
    validate_error(api.start_sequence(race_id, pro), ApiErrorId.ERR_RACE_START_BLOCKED)

    merged = merge_division(narrow_id, world["ids"]["chair"])
    assert merged["status"] == "MERGED"
    assert merged["merged_into_division_id"] == wide_id
    assert merged["assigned_entry_count"] == 0
    assert merged["accepted_entry_count"] == 0
    assert read_entry(world["entries"]["A"]["id"])["division_id"] == wide_id
    assert read_race(race_id)["start_blocked_reason"] is None, (
        "no division of the regatta is left provisional while holding an entry"
    )

    started = validate_success(api.start_sequence(race_id, pro))

    assert started["start_status"] == "SEQUENCE_STARTED"
    assert started["general_recall_count"] == 0
    assert started["black_flag_active"] is False
    target = read_division(wide_id)
    assert target["status"] == "CONFIRMED"
    assert target["assigned_entry_count"] == 3
    assert target["accepted_entry_count"] == 3
    assert read_entry(world["entries"]["B"]["id"])["registration_status"] == "WITHDRAWN"
    regatta = read_regatta(world["regatta_id"])
    assert regatta["confirmed_division_count"] == 1
    assert regatta["status"] == "RACING"
