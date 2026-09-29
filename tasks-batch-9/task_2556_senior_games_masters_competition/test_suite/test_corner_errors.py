"""Error-code breadth: the not-found codes no other test reaches, the two
authentication defects, the uniqueness scopes, and the codes that only a fully
staffed block lifecycle can trigger."""
from test_helpers import (
    ADMIN_USER_ID,
    ApiErrorId,
    RECORDS_RATIFIER_USER_ID,
    REGISTRATION_OFFICER_USER_ID,
    TEST_USERS,
    advance_slot,
    api_client,
    build_user_headers,
    competition_result_payload,
    create_athlete,
    create_edition,
    create_entry,
    create_session_slot,
    create_sport,
    create_sport_event,
    create_venue,
    file_record_claim,
    get_assignment,
    get_event,
    get_person,
    get_record,
    get_result,
    get_slot,
    make_athlete_headers,
    make_registration_officer_headers,
    make_sport_official_headers,
    open_registration,
    pay_fees,
    publish_result,
    screen_athlete,
    set_clock,
    setup_open_edition,
    setup_pending_record_claim,
    setup_seeded_event_with_staffed_slot,
    submit_result,
    take_up_and_accept,
    validate_error,
    validate_paginated,
    validate_success,
    verify_result,
)

ADMIN = TEST_USERS["games_admin_headers"]
OFFICER = TEST_USERS["registration_officer_headers"]
MEDICAL = TEST_USERS["medical_director_headers"]
SPONSOR = TEST_USERS["sponsor_liaison_headers"]

# Syntactically valid identifiers that name nothing.
GHOST_SLOT = "aaaaaaaa-0001-4000-8000-000000000000"
GHOST_QUALIFIER = "aaaaaaaa-0002-4000-8000-000000000000"
GHOST_ENTRY = "aaaaaaaa-0003-4000-8000-000000000000"
GHOST_SCREENING = "aaaaaaaa-0004-4000-8000-000000000000"
GHOST_PERSON = "aaaaaaaa-0005-4000-8000-000000000000"
GHOST_ASSIGNMENT = "aaaaaaaa-0006-4000-8000-000000000000"
GHOST_BLOCK = "aaaaaaaa-0007-4000-8000-000000000000"
GHOST_STAY = "aaaaaaaa-0008-4000-8000-000000000000"
GHOST_COMMITMENT = "aaaaaaaa-0009-4000-8000-000000000000"
GHOST_EDITION = "bbbbbbbb-0001-4000-8000-000000000000"
FOREIGN_OFFICIAL = "cccccccc-0001-4000-8000-000000000000"


def test_each_remaining_entity_answers_with_the_not_found_code_named_after_it(clock_at_epoch):
    """PRD §2.6: "Each has a dedicated HTTP 404 error: `ERR_GAMES_EDITION_NOT_FOUND`,
    `ERR_SPORT_NOT_FOUND`, `ERR_SPORT_EVENT_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`,
    `ERR_SESSION_SLOT_NOT_FOUND`, `ERR_ATHLETE_NOT_FOUND`,
    `ERR_QUALIFYING_RESULT_NOT_FOUND`, `ERR_SPORT_ENTRY_NOT_FOUND`,
    `ERR_MEDICAL_SCREENING_NOT_FOUND`, `ERR_PERSONNEL_NOT_FOUND`,
    `ERR_PERSONNEL_ASSIGNMENT_NOT_FOUND`, `ERR_COMPETITION_RESULT_NOT_FOUND`,
    `ERR_AGE_GROUP_RECORD_NOT_FOUND`, `ERR_ACCOMMODATION_BLOCK_NOT_FOUND`,
    `ERR_VILLAGE_STAY_NOT_FOUND` and `ERR_SPONSORSHIP_COMMITMENT_NOT_FOUND`."
    PRD §2.10: "Every identifier in the request path resolves, left to right — otherwise
    the matching not-found error."
    PRD §2.2: "- The `error_id` is a unique, machine-readable string that identifies the
    specific error."
    PRD §2.3: "`total_count` reports the number of rows matching the filters before
    pagination is applied, and `has_more` is true when rows remain beyond the returned
    page."

    Nine single-row reads on unknown identifiers, nine distinct 404 codes — and
    the matching list reads answer 200 with an empty page instead.

    Design: Corner/errors/corner_error_every_remaining_entity_reports_its_own_not_found
    """
    probes = (
        (api_client.get_session_slot, GHOST_SLOT,
         ApiErrorId.ERR_SESSION_SLOT_NOT_FOUND.value, ADMIN),
        (api_client.get_qualifying_result, GHOST_QUALIFIER,
         ApiErrorId.ERR_QUALIFYING_RESULT_NOT_FOUND.value, ADMIN),
        (api_client.get_sport_entry, GHOST_ENTRY,
         ApiErrorId.ERR_SPORT_ENTRY_NOT_FOUND.value, ADMIN),
        (api_client.get_medical_screening, GHOST_SCREENING,
         ApiErrorId.ERR_MEDICAL_SCREENING_NOT_FOUND.value, MEDICAL),
        (api_client.get_personnel, GHOST_PERSON,
         ApiErrorId.ERR_PERSONNEL_NOT_FOUND.value, ADMIN),
        (api_client.get_personnel_assignment, GHOST_ASSIGNMENT,
         ApiErrorId.ERR_PERSONNEL_ASSIGNMENT_NOT_FOUND.value, ADMIN),
        (api_client.get_accommodation_block, GHOST_BLOCK,
         ApiErrorId.ERR_ACCOMMODATION_BLOCK_NOT_FOUND.value, ADMIN),
        (api_client.get_village_stay, GHOST_STAY,
         ApiErrorId.ERR_VILLAGE_STAY_NOT_FOUND.value, ADMIN),
        (api_client.get_sponsorship_commitment, GHOST_COMMITMENT,
         ApiErrorId.ERR_SPONSORSHIP_COMMITMENT_NOT_FOUND.value, SPONSOR),
    )

    for reader, ghost_id, expected_code, headers in probes:
        error = validate_error(reader(ghost_id, headers), expected_code, expected_status=404)
        # The error payload is exactly the two documented fields, nothing else.
        assert sorted(error.keys()) == ["error_id", "message"]

    # Absence is a 404 on the single-row path only: the collections answer 200
    # with an empty page rather than a not-found of their own.
    listers = (
        (api_client.list_session_slots, ADMIN),
        (api_client.list_qualifying_results, ADMIN),
        (api_client.list_sport_entries, ADMIN),
        (api_client.list_medical_screenings, MEDICAL),
        (api_client.list_personnel, ADMIN),
        (api_client.list_personnel_assignments, ADMIN),
        (api_client.list_accommodation_blocks, ADMIN),
        (api_client.list_village_stays, ADMIN),
        (api_client.list_sponsorship_commitments, SPONSOR),
    )
    for lister, headers in listers:
        rows, meta = validate_paginated(lister(headers))
        assert rows == []
        assert meta["total_count"] == 0
        assert meta["has_more"] is False


def test_three_header_defects_all_answer_unauthenticated_ahead_of_the_path_check(clock_at_epoch):
    """PRD §2.1: "If either header is absent or present but empty, the request is refused
    with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.1: "The same `ERR_UNAUTHENTICATED` is returned when `X-User-Role` carries a
    value that is not one of the seven role names the system recognises."
    PRD §2.10: "Both `X-User-ID` and `X-User-Role` are present and non-empty on every
    endpoint — otherwise `ERR_UNAUTHENTICATED`."
    PRD §2.10: "`X-User-Role` names one of the seven declared roles — otherwise
    `ERR_UNAUTHENTICATED`."
    PRD §2.10: "Every identifier in the request path resolves, left to right — otherwise
    the matching not-found error."

    An absent role header, an empty user id and an undeclared role name are one
    error at 401 — and that answer precedes identifier resolution.

    Design: Corner/errors/corner_error_missing_x_user_headers_returns_401
    """
    edition = create_edition()

    no_role = api_client.get_games_edition(edition["id"], {"X-User-ID": ADMIN_USER_ID})
    empty_user = api_client.get_games_edition(
        edition["id"], {"X-User-ID": "", "X-User-Role": "GamesAdmin"}
    )
    bystander = build_user_headers(ADMIN_USER_ID, "Bystander")
    bad_role = api_client.get_games_edition(edition["id"], bystander)
    bad_role_ghost = api_client.get_games_edition(GHOST_EDITION, bystander)

    # Both headers must be present and non-empty on every endpoint.
    validate_error(no_role, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)
    validate_error(empty_user, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)
    # An unrecognised role name is an authentication failure, not a 403.
    validate_error(bad_role, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)
    # The header checks run before the path identifier is resolved, so the
    # unknown edition never surfaces as a 404.
    validate_error(bad_role_ghost, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)

    # The same read with a declared role and a non-empty identifier succeeds, so
    # the four refusals came from the headers alone.
    readable = validate_success(api_client.get_games_edition(edition["id"], ADMIN))
    assert readable["status"] == "DRAFT"
    assert readable["version"] == edition["version"]


def test_one_block_lifecycle_produces_four_otherwise_unreachable_codes(clock_at_epoch):
    """PRD §3.7: "The cited block must actually have been contested, meaning its status is
    `IN_PROGRESS` or `COMPLETED` when the mark is filed — anything earlier answers
    `ERR_SLOT_NOT_COMPETED`."
    PRD §3.7: "The recording official may only file marks under their own identity:
    `submitted_by_personnel_id` must match the caller's `X-User-ID`, and a mismatch is
    `ERR_NOT_RESOURCE_OWNER`."
    PRD §3.7: "One entry may hold only one live mark: at most one result per
    `sport_entry_id` may sit in `SUBMITTED`, `VERIFIED`, `RECORD_PENDING` or
    `PUBLISHED`, and a second filing is refused with `ERR_RESULT_ALREADY_RECORDED`."
    PRD §3.7: "Verification is where the workflow forks, and both prongs require the
    block to have finished — the cited slot's status must be `COMPLETED`, not merely
    under way, or the verification answers `ERR_SLOT_NOT_COMPETED`."
    PRD §3.6: "The person and the slot must belong to the same edition; a person may not
    hold two live assignments on the same slot, so the pair of `personnel_id` and
    `session_slot_id` must be unique across assignments whose status is `ASSIGNED`,
    `CONFIRMED` or `COMPLETED`, and a repeat is refused with
    `ERR_ASSIGNMENT_DUPLICATE`."
    PRD §3.6: "When a block closes normally, a `CONFIRMED` assignment moves to
    `COMPLETED` and the person's `assigned_minutes_total` is deliberately left alone,
    because completed service still counts as minutes served; an assignment still
    sitting at `ASSIGNED` when the block closes moves to `NO_SHOW`, which raises
    `no_show_count` by one and debits `assigned_minutes_total` by that assignment's
    `duration_minutes`, since minutes that were never worked should not appear on the
    ledger."

    Filing too early, filing under someone else's identity, filing twice, verifying
    too early and re-staffing a finished block each answer their own code.

    Design: Corner/errors/corner_error_result_submission_and_reassignment_on_finished_slot_rejected
    """
    ctx = setup_seeded_event_with_staffed_slot(
        event_overrides={"capacity": 8, "min_entries_to_stage": 1},
        venue_overrides={"competition_area_count": 4},
        slot_overrides={"teardown_buffer_minutes": 0, "required_official_count": 1},
    )
    entry_id = ctx["entry"]["id"]
    slot_id = ctx["slot"]["id"]
    official_id = ctx["official"]["id"]
    assert get_assignment(ctx["assignment"]["id"])["status"] == "CONFIRMED"
    assert get_slot(slot_id)["confirmed_official_count"] == 1

    own_headers = make_sport_official_headers(official_id)
    mark = competition_result_payload(entry_id, slot_id, official_id, mark_value=13.42, placement=1)

    # The block has not started: submission demands IN_PROGRESS or COMPLETED.
    too_early = api_client.create_competition_result(mark, own_headers)
    validate_error(too_early, ApiErrorId.ERR_SLOT_NOT_COMPETED.value, expected_status=409)

    set_clock("2026-09-12T09:00:00Z")
    advance_slot(slot_id, "IN_PROGRESS")

    # The personnel row named in the body exists, but it is not the caller.
    foreign = api_client.create_competition_result(
        mark, make_sport_official_headers(FOREIGN_OFFICIAL)
    )
    validate_error(foreign, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, expected_status=403)

    filed = submit_result(entry_id, slot_id, official_id, mark_value=13.42, placement=1)
    assert filed["status"] == "SUBMITTED"

    # One live mark per entry.
    second_mark = api_client.create_competition_result(
        competition_result_payload(entry_id, slot_id, official_id, mark_value=13.9, placement=2),
        own_headers,
    )
    validate_error(second_mark, ApiErrorId.ERR_RESULT_ALREADY_RECORDED.value, expected_status=409)
    rows, meta = validate_paginated(
        api_client.list_competition_results(ADMIN, {"sport_entry_id": entry_id})
    )
    assert meta["total_count"] == 1
    assert float(rows[0]["mark_value"]) == 13.42

    # IN_PROGRESS is enough to file a mark but not to verify one.
    early_verify = api_client.verify_competition_result(filed["id"], OFFICER)
    validate_error(early_verify, ApiErrorId.ERR_SLOT_NOT_COMPETED.value, expected_status=409)

    advance_slot(slot_id, "COMPLETED")

    # Completed service stays on the ledger, so the minutes are not unwound.
    assert get_assignment(ctx["assignment"]["id"])["status"] == "COMPLETED"
    assert get_person(official_id)["assigned_minutes_total"] == 60

    # The conflict scan cannot see a COMPLETED assignment on a COMPLETED slot, so
    # the uniqueness rule on the pair is what refuses the re-staffing.
    repeat = api_client.create_personnel_assignment(
        {"personnel_id": official_id, "session_slot_id": slot_id, "role_at_event": "TIMER"},
        ADMIN,
    )
    validate_error(repeat, ApiErrorId.ERR_ASSIGNMENT_DUPLICATE.value, expected_status=409)

    verified = verify_result(filed["id"])
    assert verified["status"] == "RECORD_PENDING"
    assert verified["national_qualifying"] is False


def test_a_sport_code_is_global_while_an_email_is_unique_only_inside_its_edition(clock_at_epoch):
    """PRD §3.1: "A **sport** is registered with a `sport_code` — two to eight uppercase
    letters, unique across the whole catalogue, with a collision refused as
    `ERR_SPORT_CODE_TAKEN` — a human-readable `name`, a `contact_class` of `LOW`,
    `MEDIUM` or `HIGH`, and a `mark_direction` of either `LOWER_IS_BETTER` or
    `HIGHER_IS_BETTER` that determines throughout the system whether a numerically
    smaller or larger mark is the better performance."
    PRD §3.2: "Email addresses are unique per edition: a second athlete row pairing the
    same `games_edition_id` with the same `email` is refused with
    `ERR_ATHLETE_EMAIL_TAKEN`."
    PRD §2.10: "Uniqueness holds — otherwise `ERR_SPORT_CODE_TAKEN`,
    `ERR_ATHLETE_EMAIL_TAKEN`, `ERR_ASSIGNMENT_DUPLICATE` or
    `ERR_RESULT_ALREADY_RECORDED` (all HTTP 409), guarding sport creation, athlete
    creation, personnel-assignment creation and competition-result creation
    respectively."

    Two uniqueness rules at the same rung with different reach: the second TRACK is
    refused outright, the second Ada is refused in her own edition and admitted in
    the neighbouring one.

    Design: Corner/errors/corner_error_uniqueness_sport_code_and_athlete_email_rejected
    """
    edition_a = create_edition(name="Prairie Senior Games 2026")
    edition_b = create_edition(name="Lakeside Senior Games 2026")
    track = create_sport(
        sport_code="TRACK", name="Track and Field", required_certification_level=2
    )
    # Registration opens only once the edition owns at least one OPEN sport event.
    create_sport_event(track["id"], edition_a["id"])
    create_sport_event(track["id"], edition_b["id"])
    open_registration(edition_a["id"])
    open_registration(edition_b["id"])

    duplicate_code = api_client.create_sport(
        {
            "sport_code": "TRACK",
            "name": "Track and Field Masters",
            "contact_class": "LOW",
            "mark_direction": "LOWER_IS_BETTER",
            "required_certification_level": 4,
            "min_age": 50,
        },
        ADMIN,
    )
    # Name and certification level differ; the code alone is the key.
    validate_error(duplicate_code, ApiErrorId.ERR_SPORT_CODE_TAKEN.value, expected_status=409)

    first = create_athlete(
        edition_a["id"], full_name="Ada Fenn", email="ada.fenn@example.org"
    )
    duplicate_email = api_client.create_athlete(
        {
            "games_edition_id": edition_a["id"],
            "full_name": "Ada F. Fenn",
            "email": "ada.fenn@example.org",
            "date_of_birth": "1966-03-02",
            "residency_state_code": "IL",
        },
        OFFICER,
    )
    validate_error(
        duplicate_email, ApiErrorId.ERR_ATHLETE_EMAIL_TAKEN.value, expected_status=409
    )

    # The scope is the (edition, email) pair, so the same address is free next door.
    elsewhere = create_athlete(
        edition_b["id"], full_name="Ada Fenn", email="ada.fenn@example.org"
    )
    assert elsewhere["id"] != first["id"]
    assert elsewhere["games_edition_id"] == edition_b["id"]

    _sports, sport_meta = validate_paginated(api_client.list_sports(ADMIN))
    assert sport_meta["total_count"] == 1
    _rows, athlete_meta = validate_paginated(
        api_client.list_athletes(OFFICER, {"games_edition_id": edition_a["id"]})
    )
    assert athlete_meta["total_count"] == 1


def test_the_recovery_gap_is_measured_when_the_second_block_is_placed(clock_at_epoch):
    """PRD §3.5: "For the athlete in question, gather the session slots whose status is
    `SCHEDULED` or `IN_PROGRESS` and whose sport event is an event on which that athlete
    holds an `ACCEPTED` entry; entries that are `WAITLISTED`, on `MEDICAL_HOLD` or
    `WITHDRAWN` contribute no slots."
    PRD §3.5: "Then take every unordered pair of two distinct slots from that set and
    measure the gap in whole minutes from the earlier of the two blocks' `end_utc`
    values to the later of the two blocks' `start_utc` values."
    PRD §3.5: "If any pair's gap is less than the recovery minimum of half an hour, the
    request is refused with `ERR_ATHLETE_SCHEDULE_CONFLICT`; a gap of exactly thirty
    minutes is acceptable."
    PRD §3.5: "This gate is evaluated when an entry is accepted, and also when a slot is
    created or rescheduled for an event that already holds accepted entries — in the
    latter case for every `ACCEPTED` entry of that event."
    PRD §3.2: "**Step four** picks the multi-event `discount_pct` from `entry_count`:
    zero for a single entry or none at all, five percent for two or three entries,
    twelve percent for four or five entries, and twenty percent for six or more;
    `discount_cents` is the subtotal multiplied by that percentage and rounded half up
    to whole cents, and this is the only rounding step in the whole settlement;
    `discounted_cents` is the subtotal less the discount."
    PRD §3.2: "**Step five** picks `surcharge_cents` from `discounted_cents`: nothing at
    all below two hundred and fifty dollars, fifteen dollars — 1500 cents — from two
    hundred and fifty dollars up to but not including six hundred dollars, and forty
    dollars — 4000 cents — at six hundred dollars and above."

    Both entries are accepted while the calendar is still empty; the twenty-minute
    gap is refused and the thirty-minute gap admitted at slot creation.

    Design: Corner/errors/corner_error_athlete_schedule_conflict_twenty_minute_gap_rejected
    """
    base = setup_open_edition(event={"capacity": 8, "min_entries_to_stage": 1})
    edition, sport, first_event = base["edition"], base["sport"], base["event"]
    second_event = create_sport_event(
        sport["id"], edition["id"], event_code="T200M", capacity=8, min_entries_to_stage=1
    )

    athlete = create_athlete(edition["id"], full_name="Ada Fenn")
    first_entry = create_entry(athlete["id"], first_event["id"])
    second_entry = create_entry(athlete["id"], second_event["id"])

    # 9500 base + two 6000 entry fees = 21500, less the two-entry discount of
    # 1075, and 20425 sits under the 25000 surcharge floor.
    settled = pay_fees(athlete["id"], 20425)
    assert settled["fee_total_cents"] == 20425
    assert settled["registration_status"] == "REGISTERED"
    screen_athlete(athlete["id"])

    # No slot exists yet, so the recovery gate has nothing to measure at acceptance.
    take_up_and_accept(first_entry["id"])
    take_up_and_accept(second_entry["id"])

    venue = create_venue(edition["id"], name="North Oval", competition_area_count=4)
    early_slot = create_session_slot(
        venue["id"], first_event["id"],
        start_utc="2026-09-12T09:00:00Z", end_utc="2026-09-12T10:00:00Z",
        teardown_buffer_minutes=0, required_official_count=1,
    )

    too_close = api_client.create_session_slot(
        {
            "venue_id": venue["id"],
            "sport_event_id": second_event["id"],
            "start_utc": "2026-09-12T10:20:00Z",
            "end_utc": "2026-09-12T11:00:00Z",
            "teardown_buffer_minutes": 0,
            "required_official_count": 1,
        },
        ADMIN,
    )
    # Twenty whole minutes from 10:00 to 10:20, under the half-hour minimum.
    validate_error(
        too_close, ApiErrorId.ERR_ATHLETE_SCHEDULE_CONFLICT.value, expected_status=409
    )

    # Exactly thirty minutes is acceptable.
    late_slot = create_session_slot(
        venue["id"], second_event["id"],
        start_utc="2026-09-12T10:30:00Z", end_utc="2026-09-12T11:00:00Z",
        teardown_buffer_minutes=0, required_official_count=1,
    )
    assert late_slot["status"] == "SCHEDULED"

    rows, meta = validate_paginated(
        api_client.list_session_slots(ADMIN, {"venue_id": venue["id"]})
    )
    assert meta["total_count"] == 2
    assert sorted(row["id"] for row in rows) == sorted([early_slot["id"], late_slot["id"]])
    # The refused create wrote nothing.
    assert get_slot(early_slot["id"])["start_utc"].startswith("2026-09-12T09:00:00")


def test_the_protest_allowance_is_one_round_and_a_published_mark_is_not_terminal(clock_at_epoch):
    """PRD §3.7: "The mark's `protest_round` must still be zero; a second protest is
    refused with `ERR_PROTEST_LIMIT_REACHED`, and that rule — not the terminal-state
    check — is what ultimately locks a published result down, because `PUBLISHED` is a
    settled but re-openable state rather than a final one."
    PRD §3.7: "A `PUBLISHED` mark moves `PUBLISHED` → `PROTESTED` and additionally pulls
    down the paperwork built on it: every record claim citing that mark which is still
    `PENDING_RATIFICATION` moves to `REJECTED`."
    PRD §3.7: "A decision of `REMEASURE` accepts a corrected `mark_value` and
    `placement`, rewrites both onto the result, returns it `PROTESTED` → `SUBMITTED`,
    resets `verified_by_user_id` to null and `national_qualifying` to false so the mark
    must be verified again from scratch, and increments `protest_round` by one."
    PRD §3.7: "The record branch is stricter: a `RECORD_PENDING` mark may only move
    `RECORD_PENDING` → `PUBLISHED` when a record claim citing it exists in
    `PENDING_RATIFICATION` or `RATIFIED`, so a record-beating mark cannot appear in the
    published results until the record paperwork has at least been filed."
    PRD §3.7: "A `RegistrationOfficer` verifies the mark, and the service compares it
    against the standing age-group record of the event: the record branch applies when
    the event's `current_record_id` is null, so that no record yet stands, or when the
    mark is better than the `mark_value` of the record named by `current_record_id`
    judged by the sport's `mark_direction` — smaller is better where the direction is
    `LOWER_IS_BETTER`, larger is better where it is `HIGHER_IS_BETTER`."

    The first protest of a published mark is heard, the remeasure lifts the round
    counter, and the second protest of the re-published mark is refused on the
    allowance rather than on terminality.

    Design: Corner/errors/corner_error_second_protest_after_remeasure_rejected
    """
    ctx = setup_pending_record_claim()
    result_id = ctx["result"]["id"]
    event_id = ctx["event"]["id"]
    athlete_headers = make_athlete_headers(ctx["athlete"]["id"])
    assert ctx["result"]["status"] == "RECORD_PENDING"

    # A filed claim is what lets a record-beating mark be published at all.
    assert ctx["record"]["status"] == "PENDING_RATIFICATION"
    assert publish_result(result_id)["status"] == "PUBLISHED"

    protested = validate_success(
        api_client.protest_competition_result(
            result_id, {"grounds": "Timing gate misfired in lane 4."}, athlete_headers
        )
    )
    assert protested["status"] == "PROTESTED"
    # Protesting a published mark pulls down the paperwork built on it.
    assert get_record(ctx["record"]["id"])["status"] == "REJECTED"

    remeasured = validate_success(
        api_client.resolve_protest(
            result_id,
            {"decision": "REMEASURE", "mark_value": 13.5, "placement": 1},
            make_registration_officer_headers(REGISTRATION_OFFICER_USER_ID),
        )
    )
    assert remeasured["status"] == "SUBMITTED"
    assert remeasured["protest_round"] == 1
    assert float(remeasured["mark_value"]) == 13.5
    assert remeasured["verified_by_user_id"] is None
    assert remeasured["national_qualifying"] is False

    # The first claim was rejected, never ratified, so no record yet stands and
    # the re-verification takes the record branch again.
    assert get_event(event_id)["current_record_id"] is None
    assert verify_result(result_id)["status"] == "RECORD_PENDING"

    second_claim = file_record_claim(event_id, result_id, RECORDS_RATIFIER_USER_ID)
    assert get_record(second_claim["id"])["status"] == "PENDING_RATIFICATION"
    assert publish_result(result_id)["status"] == "PUBLISHED"

    second_protest = api_client.protest_competition_result(
        result_id, {"grounds": "Second look at the remeasured time."}, athlete_headers
    )
    # PUBLISHED is a settled but re-openable state, so terminality is not the
    # rule that answers here — the exhausted allowance is.
    validate_error(
        second_protest, ApiErrorId.ERR_PROTEST_LIMIT_REACHED.value, expected_status=422
    )

    after = get_result(result_id)
    assert after["status"] == "PUBLISHED"
    assert after["protest_round"] == 1
    assert get_record(second_claim["id"])["status"] == "PENDING_RATIFICATION"
