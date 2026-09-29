"""Each remaining refusal reached from the wrong side of its own boundary and then
from the exact edge: certificate coverage of the series start, the two clauses of a
complete manifest, the merge selector's hull scope, the two start-sequence gates, the
prestart and result payload rules, the closing of entries, and the whole protest
lifecycle from filing through hearing to decision.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    MEASUREMENT_A,
    MEASUREMENT_B,
    SERIES_START_UTC,
    TWO_BOAT_DIVISION,
    TWO_ENTRANTS,
    ApiErrorId,
    assert_same_instant,
    add_crew,
    add_crew_payload,
    build_racing_world,
    build_started_race_world,
    confirm_duty,
    create_division_payload,
    create_entry_payload,
    create_protest_payload,
    create_race_result_payload,
    decide_payload,
    evidence_payload,
    file_and_issue_certificate,
    file_certificate,
    make_club_admin_headers,
    make_competitor_headers,
    open_regatta,
    propose_duty,
    publish_document,
    publish_nor,
    read_certificate,
    read_division,
    read_document,
    read_entry,
    read_protest,
    read_race,
    read_regatta,
    read_result,
    recall_payload,
    record_result,
    register_boat,
    schedule_hearing_payload,
    score_race,
    set_clock,
    start_race_payload,
)

ADMIN = make_club_admin_headers()
AFTER_SERIES_START = "2026-08-06T00:00:00Z"
BEFORE_SERIES_START = "2026-08-04T00:00:00Z"
ONE_SECOND_SHORT = "2026-08-04T23:59:59Z"
LATE_SEASON = "2026-12-31T00:00:00Z"
EARLY_SEASON = "2026-01-01T00:00:00Z"


def test_certificate_coverage_of_the_series_start_is_inclusive_at_both_bounds(api, roster):
    """PRD 3.5: "At submission the pinned certificate's validity window must cover the
    regatta's `series_start_utc`, both bounds inclusive, or the submission is refused
    with `ERR_CERTIFICATE_EXPIRED`; and the certificate must belong to the boat named by
    the entry and the boat must belong to the same event context, or the submission is
    refused with `ERR_CROSS_REGATTA_REFERENCE`."

    PRD 2.7 item 26: "The regatta's `series_start_utc` falls inside the certificate's
    inclusive validity window, else `ERR_CERTIFICATE_EXPIRED`. This check applies to
    entry submission and to entry acceptance."

    PRD 3.3 fixes the instant that is compared: "Finally `series_start_utc` fixes the
    first scheduled warning signal of the series, and it is the single instant against
    which certificate validity and crew safety-course validity are tested."

    Design: Corner/errors/entry_certificate_not_covering_series_start_returns_certificate_expired
    """
    chair_id = roster["chair"]["id"]
    measurer_id = roster["measurer"]["id"]
    helm_id = roster["helm_1"]["id"]
    regatta = open_regatta(chair_id)
    assert regatta["series_start_utc"] == SERIES_START_UTC
    publish_nor(regatta["id"], chair_id)
    helm = make_competitor_headers(helm_id)
    windows = {
        "opens_too_late": (AFTER_SERIES_START, LATE_SEASON),
        "closes_on_the_instant": (BEFORE_SERIES_START, SERIES_START_UTC),
        "closes_one_second_short": (EARLY_SEASON, ONE_SECOND_SHORT),
    }
    boats, certificates = {}, {}
    for key, (valid_from, valid_until) in windows.items():
        boats[key] = register_boat(helm_id)
        certificates[key] = file_certificate(
            boats[key]["id"], measurer_id, valid_from=valid_from, valid_until=valid_until
        )

    for key in ("opens_too_late", "closes_one_second_short"):
        validate_error(
            api.create_entry(
                create_entry_payload(
                    regatta["id"], boats[key]["id"], certificates[key]["id"], helm_id
                ),
                helm,
            ),
            ApiErrorId.ERR_CERTIFICATE_EXPIRED,
            expected_status=422,
        )

    admitted = validate_success(
        api.create_entry(
            create_entry_payload(
                regatta["id"],
                boats["closes_on_the_instant"]["id"],
                certificates["closes_on_the_instant"]["id"],
                helm_id,
            ),
            helm,
        ),
        expected_status=201,
    )

    assert admitted["registration_status"] == "SUBMITTED", (
        "a valid_until exactly equal to the series start is inside the inclusive window"
    )
    assert admitted["certificate_id"] == certificates["closes_on_the_instant"]["id"]
    _, pagination = validate_paginated(
        api.list_entries(ADMIN, {"regatta_id": regatta["id"]})
    )
    assert pagination["total_count"] == 1
    for certificate in certificates.values():
        assert read_certificate(certificate["id"])["status"] == "DRAFT", (
            "submission needs a covering certificate, not an issued one"
        )


SHORT_MANIFEST_FLEET = (
    {
        "key": "A",
        "helm": "helm_1",
        "measurement": MEASUREMENT_A,
        "entry": {"declared_crew_count": 2},
        "crew": ({"member": "helm_1", "position": "HELM", "weight_kg": 84.5},),
        "accept": False,
    },
    {
        "key": "B",
        "helm": "helm_2",
        "measurement": MEASUREMENT_B,
        "entry": {"declared_crew_count": 1},
        "crew": ({"member": "helm_3", "position": "TRIM", "weight_kg": 79.25},),
        "accept": False,
    },
)


def test_acceptance_needs_both_the_matching_count_and_the_helm_on_the_manifest(api):
    """PRD 3.5: "The manifest must be complete: `registered_crew_count` equal to
    `declared_crew_count`, with exactly one element whose `position` is `HELM` and whose
    `member_id` equals the entry's `helm_member_id`, otherwise
    `ERR_CREW_MANIFEST_INCOMPLETE`."

    PRD 2.7 item 27 states the same rule as two independent clauses:
    "`registered_crew_count` equals `declared_crew_count` and exactly one manifest
    element has `position` `HELM` with a `member_id` equal to `helm_member_id`, else
    `ERR_CREW_MANIFEST_INCOMPLETE`. This check applies to entry acceptance only."

    PRD 3.4 fixes that admitting a fleet is not the same act as confirming it:
    "Confirmation is the chair's declaration that a real fleet exists."

    Design: Corner/errors/accept_rejections_for_short_and_helmless_crew_manifests
    """
    world = build_racing_world(
        regatta_overrides={"fleet_minimum": 2},
        publish="nor",
        divisions=TWO_BOAT_DIVISION,
        entrants=SHORT_MANIFEST_FLEET,
        confirm_division_codes=(),
    )
    short_id = world["entries"]["A"]["id"]
    helmless_id = world["entries"]["B"]["id"]
    chair = world["h"]["chair"]

    validate_error(
        api.accept_entry(short_id, chair),
        ApiErrorId.ERR_CREW_MANIFEST_INCOMPLETE,
        expected_status=422,
    )
    validate_error(
        api.accept_entry(helmless_id, chair),
        ApiErrorId.ERR_CREW_MANIFEST_INCOMPLETE,
        expected_status=422,
    )

    add_crew(
        short_id, world["ids"]["helm_1"], world["ids"]["helm_3"],
        position="TRIM", weight_kg=79.25,
    )
    completed = validate_success(api.accept_entry(short_id, chair))

    assert completed["registration_status"] == "ACCEPTED"
    assert completed["registered_crew_count"] == 2
    assert completed["crew_weight_kg"] == 163.8

    validate_success(
        api.remove_crew(helmless_id, world["ids"]["helm_3"], world["h"]["helm_2"])
    )
    validate_success(
        api.add_crew(
            helmless_id,
            add_crew_payload(world["ids"]["helm_2"], position="HELM", weight_kg=78.0),
            world["h"]["helm_2"],
        ),
        expected_status=200,
    )
    reseated = validate_success(api.accept_entry(helmless_id, chair))

    assert reseated["registration_status"] == "ACCEPTED", (
        "the same count of one is now carried by the helm itself"
    )
    assert reseated["registered_crew_count"] == 1
    assert reseated["crew_weight_kg"] == 78.0

    division = read_division(world["divisions"]["A"]["id"])
    assert division["assigned_entry_count"] == 2
    assert division["accepted_entry_count"] == 2
    assert division["status"] == "PROVISIONAL", "acceptance alone never confirms a division"
    assert read_entry(short_id)["division_id"] == division["id"]


MONOHULL_ORPHAN = {
    "code": "A",
    "boat_type_filter": "MONOHULL",
    "rating_band_low": 165.0,
    "rating_band_high": 175.0,
    "min_entries": 2,
}
MULTIHULL_NEIGHBOUR = {
    "code": "M",
    "boat_type_filter": "MULTIHULL",
    "rating_band_low": 170.0,
    "rating_band_high": 172.0,
    "min_entries": 2,
}
ANY_HULL_LATECOMER = {
    "code": "B",
    "boat_type_filter": "ANY",
    "rating_band_low": 176.0,
    "rating_band_high": 200.0,
    "min_entries": 2,
}


def test_a_division_with_no_hull_compatible_sibling_has_nothing_to_merge_into(api):
    """PRD 3.4: "Candidates are the other divisions of the same regatta whose `status`
    is `PROVISIONAL` or `CONFIRMED` and whose `boat_type_filter` either equals the
    merging division's `boat_type_filter` or is `ANY`; the merging division itself is
    excluded, and a division already in `MERGED` is never a candidate."

    PRD 3.4 fixes the empty-candidate answer: "If no candidate exists at all, the merge
    is refused with `ERR_NO_MERGE_TARGET` and the division stays `PROVISIONAL`."

    PRD 3.4 also fixes that an empty division is eligible to be merged away in the
    first place: "Merging is permitted only from `PROVISIONAL` and only while the
    division's `assigned_entry_count` is still below the greater of its `min_entries`
    and the regatta's `fleet_minimum` — a division that already meets its floor is
    confirmed, not merged."

    Design: Corner/errors/merge_without_same_hull_scope_sibling_returns_no_merge_target
    """
    world = build_racing_world(
        regatta_overrides={"fleet_minimum": 2},
        publish="nor",
        divisions=(MONOHULL_ORPHAN, MULTIHULL_NEIGHBOUR),
        confirm_division_codes=(),
    )
    orphan_id = world["divisions"]["A"]["id"]
    neighbour_id = world["divisions"]["M"]["id"]
    chair = world["h"]["chair"]

    validate_error(
        api.merge_division(orphan_id, chair),
        ApiErrorId.ERR_NO_MERGE_TARGET,
        expected_status=409,
    )

    stranded = read_division(orphan_id)
    assert stranded["status"] == "PROVISIONAL", "a refused merge leaves the division alone"
    assert stranded["merged_into_division_id"] is None
    assert read_division(neighbour_id)["status"] == "PROVISIONAL", (
        "the multihull band overlaps 170.0 to 172.0 but was never a candidate"
    )

    latecomer = validate_success(
        api.create_division(
            create_division_payload(world["regatta_id"], **ANY_HULL_LATECOMER), chair
        ),
        expected_status=201,
    )
    merged = validate_success(api.merge_division(orphan_id, chair))

    assert merged["status"] == "MERGED"
    assert merged["merged_into_division_id"] == latecomer["id"], (
        "an ANY filter is a candidate for a MONOHULL division, a MULTIHULL one is not"
    )
    absorbed = read_division(latecomer["id"])
    assert absorbed["assigned_entry_count"] == 0, "an empty division carries nothing across"
    assert absorbed["accepted_entry_count"] == 0
    assert absorbed["status"] == "PROVISIONAL"
    assert read_division(neighbour_id)["merged_into_division_id"] is None


SI_AMENDMENT_EFFECTIVE_UTC = "2026-08-06T00:00:00Z"
DAY_TWO_RACE_START = "2026-08-06T14:00:00Z"
DAY_ONE_CLOCK = "2026-08-05T13:00:00Z"
DAY_TWO_CLOCK = "2026-08-06T13:00:00Z"
DAY_TWO_WINDOW = ("2026-08-06T12:00:00Z", "2026-08-06T20:00:00Z")


def test_the_start_sequence_waits_first_on_the_amendment_clock_then_on_the_committee(api):
    """PRD 3.7: "Four conditions gate it: the regatta must be in `RACING`, or the
    attempt is refused with `ERR_REGATTA_PHASE_INVALID`; `start_blocked_reason` must be
    null, or the attempt is refused with `ERR_RACE_START_BLOCKED`; the newest
    `PUBLISHED` sailing-instructions revision of the regatta must have an
    `effective_utc` at or before the current clock, or the attempt is refused with
    `ERR_SAILING_INSTRUCTIONS_NOT_EFFECTIVE` — which is exactly what an amendment
    published with a future effective instant produces; and the committee must be fully
    on station, or the attempt is refused with `ERR_STAFFING_INCOMPLETE`."

    PRD 3.3 fixes that the future-dated amendment itself is lawful: "An amendment
    published with an `effective_utc` in the future is an entirely legitimate act — and
    it is precisely the situation that stops a start sequence, as section 3.7 explains."

    PRD 3.6 fixes what full is: "Three positions are always required, one of each:
    `PRO`, `TIMEKEEPER` and `SIGNALS`."

    Design: Corner/errors/start_sequence_rejected_by_pending_si_then_by_missing_staffing
    """
    world = build_racing_world(
        regatta_overrides={"fleet_minimum": 2, "jury_quorum_required": 2},
        divisions=TWO_BOAT_DIVISION,
        entrants=TWO_ENTRANTS,
        panel=True,
        racing=True,
        races=({"race_number": 1, "scheduled_start_utc": DAY_TWO_RACE_START},),
    )
    regatta_id = world["regatta_id"]
    chair_id = world["ids"]["chair"]
    race_id = world["races"][1]["id"]
    officer = world["h"]["pro"]
    first_si = world["documents"]["SI"]
    set_clock(DAY_ONE_CLOCK)

    amendment = publish_document(
        regatta_id, chair_id, doc_type="SI",
        effective_utc=SI_AMENDMENT_EFFECTIVE_UTC,
        amends_document_id=first_si["id"],
    )
    assert amendment["revision"] == 2

    validate_error(
        api.start_sequence(race_id, officer),
        ApiErrorId.ERR_SAILING_INSTRUCTIONS_NOT_EFFECTIVE,
        expected_status=409,
    )
    assert read_race(race_id)["start_status"] == "PENDING", (
        "the sailing instructions gate is examined before the committee is counted"
    )

    set_clock(DAY_TWO_CLOCK)

    validate_error(
        api.start_sequence(race_id, officer),
        ApiErrorId.ERR_STAFFING_INCOMPLETE,
        expected_status=422,
    )

    for position, key in (("PRO", "pro"), ("TIMEKEEPER", "timekeeper")):
        duty = propose_duty(
            regatta_id, chair_id, world["ids"][key], position,
            window_start_utc=DAY_TWO_WINDOW[0], window_end_utc=DAY_TWO_WINDOW[1],
        )
        confirm_duty(duty["id"], chair_id)

    validate_error(
        api.start_sequence(race_id, officer),
        ApiErrorId.ERR_STAFFING_INCOMPLETE,
        expected_status=422,
    )

    signals = propose_duty(
        regatta_id, chair_id, world["ids"]["signals"], "SIGNALS",
        window_start_utc=DAY_TWO_WINDOW[0], window_end_utc=DAY_TWO_WINDOW[1],
    )
    confirm_duty(signals["id"], chair_id)
    readiness = validate_success(api.get_staffing(race_id, officer))

    assert readiness["staffing_ready"] is True
    assert readiness["staffed_position_codes"] == ["PRO", "SIGNALS", "TIMEKEEPER"]
    assert readiness["missing_position_codes"] == []

    started = validate_success(api.start_sequence(race_id, officer))

    assert started["start_status"] == "SEQUENCE_STARTED"
    assert started["staffing_ready"] is True, "refreshed from the readiness computation"
    assert started["start_blocked_reason"] is None
    assert started["general_recall_count"] == 0
    assert started["black_flag_active"] is False
    assert started["scoring_status"] == "NOT_SCORED"

    assert read_document(first_si["id"])["status"] == "SUPERSEDED"
    assert read_document(amendment["id"])["status"] == "PUBLISHED"
    regatta = read_regatta(regatta_id)
    assert regatta["si_revision"] == 2
    assert regatta["status"] == "RACING", "an amendment never rewinds the phase"


PRESTART_OPENS = "2026-08-05T13:55:00Z"
BEFORE_PRESTART = "2026-08-05T13:50:00Z"
INSIDE_PRESTART = "2026-08-05T13:56:00Z"
LATE_IN_PRESTART = "2026-08-05T13:58:00Z"
RESULTS_CLOCK = "2026-08-05T15:00:00Z"
PRESTART_FLEET = (
    {"key": "A", "helm": "helm_1", "measurement": MEASUREMENT_A},
    {"key": "B", "helm": "helm_2", "measurement": MEASUREMENT_B},
    {
        "key": "C",
        "helm": "helm_3",
        "measurement": MEASUREMENT_A,
        "crew": [],
        "inspect": None,
        "accept": False,
    },
)


def test_every_prestart_and_result_payload_rule_refuses_before_the_exact_edge_lands(api):
    """PRD 3.7: "A signal carries a `recall_type` of `INDIVIDUAL` or `GENERAL`, an
    `entry_id` that is required for `INDIVIDUAL` and must be null for `GENERAL`, a
    `signal_utc` naming the instant the signal was displayed, and a `reason_code` such as
    `PREMATURE_START` or `UNIDENTIFIED_BOATS`. The `signal_utc` may not precede the
    opening of the prestart window, that is five minutes before `scheduled_start_utc`; a
    payload violating the type-and-entry pairing or the timing is refused with
    `ERR_RECALL_PAYLOAD_INVALID`."

    PRD 3.7 fixes the same five minutes for the start itself: "Recording the start moves
    `start_status` `SEQUENCE_STARTED → STARTED` and stores the supplied
    `actual_start_utc`, which may not precede the opening of the prestart window five
    minutes before `scheduled_start_utc`; an earlier instant is refused with
    `ERR_START_TIME_INVALID`."

    PRD 3.8: "The three remaining abbreviations are derived only — `OCS` is minted by a
    black-flag individual recall, and `DSQ` and `RDG` are minted by jury decisions — so a
    client supplying any of them is refused with `ERR_RESULT_PAYLOAD_INVALID`. The same
    code covers the elapsed-time pairing: `elapsed_seconds` is required when
    `finish_status` is `FINISHED` and must be absent for every other value, and when
    supplied it must be greater than 0 and at most 604800, that is at most seven days of
    elapsed time."

    PRD 3.7 fixes what a recall without a black flag does not do: "While
    `black_flag_active` is false, the race stays in `SEQUENCE_STARTED` and no result is
    minted at all."

    Design: Corner/errors/prestart_recall_start_and_result_payload_rejections
    """
    world = build_started_race_world(entrants=PRESTART_FLEET, start_races=(), clock=None)
    race_id = world["races"][1]["id"]
    officer = world["h"]["pro"]
    entry_a = world["entries"]["A"]["id"]
    entry_c = world["entries"]["C"]["id"]
    validate_success(api.start_sequence(race_id, officer))

    for payload in (
        recall_payload("GENERAL", LATE_IN_PRESTART, entry_id=entry_a),
        recall_payload("INDIVIDUAL", LATE_IN_PRESTART),
        recall_payload("INDIVIDUAL", BEFORE_PRESTART, entry_id=entry_a),
    ):
        validate_error(
            api.recall_race(race_id, payload, officer),
            ApiErrorId.ERR_RECALL_PAYLOAD_INVALID,
            expected_status=422,
        )
    validate_error(
        api.recall_race(
            race_id, recall_payload("INDIVIDUAL", INSIDE_PRESTART, entry_id=entry_c), officer
        ),
        ApiErrorId.ERR_ENTRY_NOT_ACCEPTED,
        expected_status=409,
    )
    signals, _ = validate_paginated(api.list_recall_events(ADMIN, {"race_id": race_id}))
    assert signals == [], "four refusals appended nothing to an append-only log"

    signalled = validate_success(
        api.recall_race(
            race_id, recall_payload("INDIVIDUAL", PRESTART_OPENS, entry_id=entry_a), officer
        ),
        expected_status=201,
    )

    assert signalled["recall_type"] == "INDIVIDUAL"
    assert signalled["signal_utc"] == PRESTART_OPENS, "the exact window opening counts"
    assert signalled["black_flag_applied"] is False
    assert signalled["resulting_start_status"] == "SEQUENCE_STARTED"
    assert signalled["recorded_by_member_id"] == world["ids"]["pro"]
    logged, pagination = validate_paginated(
        api.list_recall_events(ADMIN, {"race_id": race_id})
    )
    assert pagination["total_count"] == 1
    assert logged[0]["id"] == signalled["id"]

    recalled = read_race(race_id)
    assert recalled["start_status"] == "SEQUENCE_STARTED", "the start still stands"
    assert recalled["general_recall_count"] == 0
    assert recalled["black_flag_active"] is False
    assert recalled["scoring_status"] == "NOT_SCORED", "no black flag, so no OCS row"

    validate_error(
        api.start_race(race_id, start_race_payload(BEFORE_PRESTART), officer),
        ApiErrorId.ERR_START_TIME_INVALID,
        expected_status=422,
    )
    assert read_race(race_id)["actual_start_utc"] is None

    started = validate_success(
        api.start_race(race_id, start_race_payload(PRESTART_OPENS), officer)
    )

    assert started["start_status"] == "STARTED"
    assert started["actual_start_utc"] == PRESTART_OPENS, (
        "five minutes before the scheduled 14:00 is inside the window, not before it"
    )

    set_clock(RESULTS_CLOCK)
    for payload in (
        {"race_id": race_id, "entry_id": entry_a, "finish_status": "FINISHED"},
        {
            "race_id": race_id, "entry_id": entry_a,
            "finish_status": "DNF", "elapsed_seconds": 4800.0,
        },
        {"race_id": race_id, "entry_id": entry_a, "finish_status": "OCS"},
    ):
        validate_error(
            api.create_race_result(payload, officer),
            ApiErrorId.ERR_RESULT_PAYLOAD_INVALID,
            expected_status=422,
        )
    validate_error(
        api.create_race_result(
            create_race_result_payload(race_id, entry_c, elapsed_seconds=5000.0), officer
        ),
        ApiErrorId.ERR_ENTRY_NOT_ACCEPTED,
        expected_status=409,
    )
    _, empty = validate_paginated(api.list_race_results(ADMIN, {"race_id": race_id}))
    assert empty["total_count"] == 0, "not one of the four refusals minted a row"

    recorded = validate_success(
        api.create_race_result(
            create_race_result_payload(race_id, entry_a, elapsed_seconds=4800.0), officer
        ),
        expected_status=201,
    )

    assert recorded["corrected_seconds"] == 3772.2, "4800.0 less 171.3 over 6.0 miles"
    assert recorded["place"] is None
    assert recorded["points"] == 0
    assert recorded["discardable"] is True
    assert recorded["voided"] is False

    validate_error(
        api.create_race_result(
            {"race_id": race_id, "entry_id": entry_a, "finish_status": "DNF"}, officer
        ),
        ApiErrorId.ERR_DUPLICATE_RECORD,
        expected_status=409,
    )

    scored_open = read_race(race_id)
    assert scored_open["scoring_status"] == "PROVISIONAL"
    assert_same_instant(scored_open["results_closed_utc"], RESULTS_CLOCK, "results_closed_utc")
    _, single = validate_paginated(api.list_race_results(ADMIN, {"race_id": race_id}))
    assert single["total_count"] == 1, (
        "the duplicate refusal is taken before the elapsed-time pairing is examined"
    )


RACE_2_SCHEDULED_START = "2026-08-05T16:00:00Z"
TWO_RACE_CARD = (
    {"race_number": 1, "scheduled_start_utc": "2026-08-05T14:00:00Z"},
    {"race_number": 2, "scheduled_start_utc": RACE_2_SCHEDULED_START},
)
HALF_ACCEPTED_FLEET = (
    {"key": "A", "helm": "helm_1", "measurement": MEASUREMENT_A},
    {
        "key": "B",
        "helm": "helm_2",
        "measurement": MEASUREMENT_B,
        "crew": [],
        "inspect": None,
        "accept": False,
    },
)


def test_racing_shuts_the_entry_list_and_a_withdrawal_unconfirms_the_fleet_it_scores(api):
    """PRD 2.7 item 13: "Entries may not be submitted once the regatta has reached
    `RACING` or `SCORED`, else `ERR_ENTRIES_CLOSED`. This check applies to entry
    submission only."

    PRD 2.7 item 12 fixes that the phase check itself passes this request through:
    "Division creation requires `NOR_PUBLISHED` or `SI_PUBLISHED`; entry submission
    requires that the regatta is no longer `DRAFT`, the too-late cases being handled by
    the next check; starting a sequence, recording a result and scoring a race all
    require `RACING`."

    PRD 3.9: "It requires the race to be in `scoring_status` `PROVISIONAL` with
    `start_status` `STARTED`, the regatta to be in `RACING`, and every division of the
    regatta holding at least one accepted entry to be in status `CONFIRMED`; a
    still-provisional fleet is refused with `ERR_DIVISION_NOT_CONFIRMED`."

    PRD 3.5 fixes what the withdrawal does to the fleet and what it leaves alone: "The
    entry keeps its `division_id` for audit, but the division re-derives both counts,
    which may pull it `CONFIRMED → PROVISIONAL` and set `start_blocked_reason` to
    `DIVISION_UNDER_MINIMUM` on every `PENDING` race of the regatta. No result already
    recorded for the entry is rewritten or removed by a withdrawal, and whatever those
    results contributed to their race's `points_pool_total` stays there."

    Design: Corner/errors/score_and_entry_submission_rejections_after_racing_opened
    """
    world = build_started_race_world(
        entrants=HALF_ACCEPTED_FLEET, races=TWO_RACE_CARD, start_races=(1, 2),
        clock=RESULTS_CLOCK,
    )
    regatta_id = world["regatta_id"]
    first_race_id = world["races"][1]["id"]
    second_race_id = world["races"][2]["id"]
    division_id = world["divisions"]["A"]["id"]
    entry_a = world["entries"]["A"]["id"]
    entry_b = world["entries"]["B"]["id"]
    pro_id = world["ids"]["pro"]
    scored_result = record_result(first_race_id, entry_a, pro_id, elapsed_seconds=4800.0)
    record_result(second_race_id, entry_a, pro_id, elapsed_seconds=5100.0)
    assert read_division(division_id)["status"] == "CONFIRMED"

    finalised = validate_success(api.score_race(first_race_id, world["h"]["pro"]))

    assert finalised["scoring_status"] == "FINAL"
    assert finalised["points_pool_total"] == 1.0, "one accepted entry in the only division"
    placed = read_result(scored_result["id"])
    assert placed["place"] == 1
    assert placed["points"] == 1.0
    assert placed["corrected_seconds"] == 3772.2
    racing = read_regatta(regatta_id)
    assert racing["final_race_count"] == 1
    assert racing["status"] == "RACING", "one final race of a planned six is not a series"
    assert racing["planned_race_count"] == 6

    latecomer = register_boat(world["ids"]["helm_3"])
    late_certificate = file_and_issue_certificate(latecomer["id"], world["ids"]["measurer"])
    validate_error(
        api.create_entry(
            create_entry_payload(
                regatta_id, latecomer["id"], late_certificate["id"], world["ids"]["helm_3"]
            ),
            world["h"]["helm_3"],
        ),
        ApiErrorId.ERR_ENTRIES_CLOSED,
        expected_status=409,
    )
    _, roll = validate_paginated(api.list_entries(ADMIN, {"regatta_id": regatta_id}))
    assert roll["total_count"] == 2, "the late submission minted no entry"

    withdrawn = validate_success(api.withdraw_entry(entry_b, world["h"]["helm_2"]))

    assert withdrawn["registration_status"] == "WITHDRAWN"
    unconfirmed = read_division(division_id)
    assert unconfirmed["assigned_entry_count"] == 1
    assert unconfirmed["accepted_entry_count"] == 1
    assert unconfirmed["status"] == "PROVISIONAL", "one assigned entry is under a floor of two"

    validate_error(
        api.score_race(second_race_id, world["h"]["pro"]),
        ApiErrorId.ERR_DIVISION_NOT_CONFIRMED,
        expected_status=409,
    )

    untouched = read_result(scored_result["id"])
    assert untouched["place"] == 1, "the points already in the books were left alone"
    assert untouched["points"] == 1.0
    assert untouched["corrected_seconds"] == 3772.2
    assert untouched["voided"] is False
    settled = read_race(first_race_id)
    assert settled["points_pool_total"] == 1.0
    assert settled["rescore_count"] == 0
    assert settled["start_blocked_reason"] is None, (
        "the block is stamped only on PENDING races, and this one is STARTED"
    )
    refused = read_race(second_race_id)
    assert refused["scoring_status"] == "PROVISIONAL", "the refused score changed nothing"
    assert refused["start_blocked_reason"] is None
    assert read_entry(entry_b)["division_id"] == division_id, (
        "a withdrawn entry keeps its division for audit"
    )


ACCEPTED_PAIR = (
    {"key": "A", "helm": "helm_1", "measurement": MEASUREMENT_A},
    {"key": "B", "helm": "helm_2", "measurement": MEASUREMENT_B},
)
ACTUAL_START = "2026-08-05T13:55:00Z"
BEFORE_THE_START = "2026-08-05T13:50:00Z"
ONE_SECOND_AFTER_CLOSE = "2026-08-05T15:00:01Z"
MID_RACE_INCIDENT = "2026-08-05T14:30:00Z"


def test_a_protest_needs_an_opened_window_and_an_incident_inside_the_sailing_interval(api):
    """PRD 3.10: "Filing is possible only once the race's results have opened — its
    `results_closed_utc` must be non-null, otherwise `ERR_PROTEST_WINDOW_NOT_OPEN` — and
    only within the time limit: the clock at filing must be at or before
    `results_closed_utc` plus the regatta's `protest_time_limit_minutes`, the exact limit
    instant still counting as inside, otherwise `ERR_PROTEST_WINDOW_CLOSED`."

    PRD 3.10 fixes the interval the incident must fall in: "The two parties must be
    different entries and `incident_utc` must lie between the race's `actual_start_utc`
    and its `results_closed_utc`, both bounds inclusive; a violation is
    `ERR_PROTEST_PARTIES_INVALID`."

    PRD 3.10 fixes what filing writes: "The server copies `regatta_id` from the protested
    race and stamps `filed_utc` from the logical clock."

    PRD 3.10 also fixes the shape of the new row: "A new protest opens in status `FILED`
    with an empty `evidence_log`, `evidence_count` 0, `reopen_count` 0, `decision`
    `NONE`, and `jury_panel_id`, `hearing_utc`, `penalty_target_entry_id`,
    `redress_race_number` and `invalid_reason_code` all null."

    Design: Corner/errors/protest_filing_rejections_before_the_window_opens_and_for_invalid_parties
    """
    world = build_started_race_world(
        entrants=ACCEPTED_PAIR, races=TWO_RACE_CARD, start_races=(), clock=None
    )
    regatta_id = world["regatta_id"]
    sailed_race_id = world["races"][1]["id"]
    idle_race_id = world["races"][2]["id"]
    entry_a = world["entries"]["A"]["id"]
    entry_b = world["entries"]["B"]["id"]
    officer = world["h"]["pro"]
    helm = world["h"]["helm_1"]
    validate_success(api.start_sequence(sailed_race_id, officer))
    started = validate_success(
        api.start_race(sailed_race_id, start_race_payload(ACTUAL_START), officer)
    )
    assert started["actual_start_utc"] == ACTUAL_START
    set_clock(RESULTS_CLOCK)
    record_result(sailed_race_id, entry_a, world["ids"]["pro"], elapsed_seconds=4800.0)
    assert_same_instant(read_race(sailed_race_id)["results_closed_utc"], RESULTS_CLOCK, "results_closed_utc")
    assert read_race(idle_race_id)["results_closed_utc"] is None

    validate_error(
        api.create_protest(
            create_protest_payload(idle_race_id, entry_a, entry_b, MID_RACE_INCIDENT), helm
        ),
        ApiErrorId.ERR_PROTEST_WINDOW_NOT_OPEN,
        expected_status=409,
    )
    for protestor, protestee, incident in (
        (entry_a, entry_a, MID_RACE_INCIDENT),
        (entry_a, entry_b, BEFORE_THE_START),
        (entry_a, entry_b, ONE_SECOND_AFTER_CLOSE),
    ):
        validate_error(
            api.create_protest(
                create_protest_payload(sailed_race_id, protestor, protestee, incident), helm
            ),
            ApiErrorId.ERR_PROTEST_PARTIES_INVALID,
            expected_status=422,
        )
    _, nothing = validate_paginated(api.list_protests(ADMIN, {"regatta_id": regatta_id}))
    assert nothing["total_count"] == 0

    filed = validate_success(
        api.create_protest(
            create_protest_payload(sailed_race_id, entry_a, entry_b, ACTUAL_START), helm
        ),
        expected_status=201,
    )

    assert filed["status"] == "FILED", "an incident at the very instant of the start is inside"
    assert filed["incident_utc"] == ACTUAL_START
    assert_same_instant(filed["filed_utc"], RESULTS_CLOCK, "filed_utc")
    assert filed["regatta_id"] == regatta_id, "copied from the protested race"
    assert filed["evidence_count"] == 0
    assert filed["evidence_log"] == []
    assert filed["reopen_count"] == 0
    assert filed["decision"] == "NONE"
    assert filed["jury_panel_id"] is None, "filing binds no panel"
    assert filed["hearing_utc"] is None
    assert filed["penalty_target_entry_id"] is None
    assert filed["redress_race_number"] is None
    assert filed["invalid_reason_code"] is None

    _, one = validate_paginated(api.list_protests(ADMIN, {"regatta_id": regatta_id}))
    assert one["total_count"] == 1
    idle = read_race(idle_race_id)
    assert idle["start_status"] == "PENDING", "the refused filing changed nothing"
    assert idle["scoring_status"] == "NOT_SCORED"


HEARING_IN_THE_PAST = "2026-08-05T14:30:00Z"
HEARING_UTC = "2026-08-05T18:00:00Z"
ONE_RACE_CARD = ({"race_number": 1, "scheduled_start_utc": "2026-08-05T14:00:00Z"},)


def test_every_gate_of_the_hearing_and_the_decision_fires_in_its_own_right(api):
    """PRD 3.10: "and `hearing_utc` must be strictly later than the current clock,
    otherwise `ERR_HEARING_TIME_INVALID`."

    PRD 3.10: "Holding the hearing moves `HEARING_SCHEDULED → HEARD`. It requires
    `evidence_count` of at least 1, otherwise `ERR_EVIDENCE_REQUIRED`; it requires the
    clock to have reached `hearing_utc`, otherwise `ERR_HEARING_NOT_DUE`; and it must be
    performed by the chair of the bound panel."

    PRD 2.7 fixes which of those two answers a bare hearing gets, item 16 standing above
    item 40: "The clock has reached the protest's `hearing_utc`, else
    `ERR_HEARING_NOT_DUE`. This check applies to holding a hearing only."

    PRD 3.10: "Payload coherence is strict, and a violation is
    `ERR_DECISION_PAYLOAD_INVALID`: `penalty_target_entry_id` must be present and must
    name either the protestor's or the protestee's entry for every decision except
    `DISMISSED`, and `redress_race_number` must be present exactly when the decision is
    `REDRESS_GRANTED` and absent otherwise, naming a race of the regatta that is `FINAL`
    and not abandoned."

    PRD 3.10 fixes the empty-average refusal: "Third, if that source set is empty, the
    whole decision is refused with `ERR_REDRESS_NOT_COMPUTABLE`; otherwise the redress
    score is the arithmetic mean of the `points` of the source results, rounded half-up
    to one decimal place."

    Design: Corner/errors/hearing_and_decision_rejections_across_the_protest_lifecycle
    """
    world = build_started_race_world(
        entrants=ACCEPTED_PAIR, races=ONE_RACE_CARD, start_races=(1,), clock=RESULTS_CLOCK
    )
    race_id = world["races"][1]["id"]
    entry_a = world["entries"]["A"]["id"]
    entry_b = world["entries"]["B"]["id"]
    pro_id = world["ids"]["pro"]
    result_a = record_result(race_id, entry_a, pro_id, elapsed_seconds=3900.0)
    result_b = record_result(race_id, entry_b, pro_id, elapsed_seconds=4300.0)
    assert result_a["corrected_seconds"] == 2872.2
    assert result_b["corrected_seconds"] == 2987.2
    assert score_race(race_id, pro_id)["scoring_status"] == "FINAL"
    protest = validate_success(
        api.create_protest(
            create_protest_payload(race_id, entry_a, entry_b, HEARING_IN_THE_PAST),
            world["h"]["helm_1"],
        ),
        expected_status=201,
    )
    assert protest["status"] == "FILED"
    protest_id = protest["id"]
    panel_id = world["panel"]["id"]
    jury = world["h"]["jury"]

    validate_error(
        api.schedule_hearing(
            protest_id, schedule_hearing_payload(panel_id, HEARING_IN_THE_PAST), jury
        ),
        ApiErrorId.ERR_HEARING_TIME_INVALID,
        expected_status=422,
    )
    behind = read_protest(protest_id)
    assert behind["status"] == "FILED", "a hearing behind the clock binds nothing"
    assert behind["jury_panel_id"] is None

    scheduled = validate_success(
        api.schedule_hearing(protest_id, schedule_hearing_payload(panel_id, HEARING_UTC), jury)
    )

    assert scheduled["status"] == "HEARING_SCHEDULED"
    assert scheduled["jury_panel_id"] == panel_id
    assert scheduled["hearing_utc"] == HEARING_UTC

    validate_error(
        api.hear_protest(protest_id, jury),
        ApiErrorId.ERR_HEARING_NOT_DUE,
        expected_status=409,
    )
    assert read_protest(protest_id)["evidence_count"] == 0, (
        "the log is empty, yet the clock is what answered first"
    )

    set_clock(HEARING_UTC)

    validate_error(
        api.hear_protest(protest_id, jury),
        ApiErrorId.ERR_EVIDENCE_REQUIRED,
        expected_status=409,
    )

    evidenced = validate_success(
        api.file_evidence(protest_id, evidence_payload(entry_a), jury)
    )

    assert evidenced["evidence_count"] == 1
    assert_same_instant(evidenced["evidence_log"][0]["recorded_utc"], HEARING_UTC, "recorded_utc")
    assert evidenced["evidence_log"][0]["kind"] == "GPS_TRACK"
    assert evidenced["status"] == "HEARING_SCHEDULED", "filing evidence is not hearing"

    heard = validate_success(api.hear_protest(protest_id, jury))

    assert heard["status"] == "HEARD"
    assert heard["decision"] == "NONE", "hearing settles nothing on its own"

    validate_error(
        api.decide_protest(protest_id, decide_payload("PENALTY_DSQ"), jury),
        ApiErrorId.ERR_DECISION_PAYLOAD_INVALID,
        expected_status=422,
    )
    validate_error(
        api.decide_protest(
            protest_id, decide_payload("DISMISSED", redress_race_number=1), jury
        ),
        ApiErrorId.ERR_DECISION_PAYLOAD_INVALID,
        expected_status=422,
    )
    validate_error(
        api.decide_protest(
            protest_id,
            decide_payload(
                "REDRESS_GRANTED", penalty_target_entry_id=entry_a, redress_race_number=1
            ),
            jury,
        ),
        ApiErrorId.ERR_REDRESS_NOT_COMPUTABLE,
        expected_status=422,
    )

    undecided = read_protest(protest_id)
    assert undecided["status"] == "HEARD", "a refused decision writes nothing"
    assert undecided["decision"] == "NONE"
    assert undecided["penalty_target_entry_id"] is None
    assert undecided["redress_race_number"] is None

    decided = validate_success(
        api.decide_protest(protest_id, decide_payload("DISMISSED"), jury)
    )

    assert decided["status"] == "DECIDED"
    assert decided["decision"] == "DISMISSED"
    assert decided["penalty_target_entry_id"] is None
    assert decided["redress_race_number"] is None

    kept_a = read_result(result_a["id"])
    assert kept_a["place"] == 1
    assert kept_a["points"] == 1.0
    assert kept_a["corrected_seconds"] == 2872.2
    kept_b = read_result(result_b["id"])
    assert kept_b["place"] == 2
    assert kept_b["points"] == 2.0
    assert kept_b["corrected_seconds"] == 2987.2
    assert read_race(race_id)["rescore_count"] == 0, (
        "a dismissal rewrites no result, so there is nothing to re-score"
    )
    assert read_regatta(world["regatta_id"])["status"] == "RACING", (
        "one final race of a planned six leaves the bubble-up condition unmet"
    )
