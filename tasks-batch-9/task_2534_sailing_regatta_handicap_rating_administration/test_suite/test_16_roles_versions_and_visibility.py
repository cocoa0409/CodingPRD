"""Who may call what, what a stale version costs, and when a moved counter becomes
readable: the measurer locked out of the committee's own reads, the start sequence
reserved to the race officer, the club office that opens an event it may not shape,
the credential patch that unlocks a licence, the seat that must be vacated before a
judge takes the start line, the two optimistic-concurrency preconditions, and the
counters that arrive inside the very response that moved them.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    MEASUREMENT_A,
    MEASUREMENT_B,
    NOR_EFFECTIVE_UTC,
    RACE_1_SCHEDULED_START,
    SAFETY_COURSE_OK_UNTIL,
    SI_EFFECTIVE_UTC,
    TWO_BOAT_DIVISION,
    UNKNOWN_UUID,
    ApiErrorId,
    assert_same_instant,
    build_racing_world,
    build_started_race_world,
    confirm_duty,
    create_certificate_payload,
    create_division_payload,
    create_race_document_payload,
    create_race_payload,
    create_regatta_payload,
    enrol_member,
    file_and_issue_certificate,
    form_panel,
    make_club_admin_headers,
    make_jury_chair_headers,
    make_measurer_headers,
    make_race_officer_headers,
    make_regatta_chair_headers,
    open_regatta,
    propose_duty,
    publish_nor,
    publish_si,
    read_boat,
    read_division,
    read_document,
    read_duty,
    read_member,
    read_regatta,
    recuse_payload,
    register_boat,
    schedule_race,
    seat_judge,
    submit_entry,
)

ADMIN = make_club_admin_headers()
RATING_A = 171.3
ALL_THREE_POSITIONS = ["PRO", "SIGNALS", "TIMEKEEPER"]


def test_the_measurer_is_shut_out_of_the_committee_reads_but_not_of_its_own_paperwork(api, roster):
    """PRD 2.1: "A request whose role is not listed against the endpoint it calls is
    rejected with `ERR_FORBIDDEN_ROLE`. Section 4 is the authoritative role list per
    endpoint."

    PRD 2.1 fixes the whole of what a measurer is for: "A `Measurer` files measurement
    data and issues, suspends and reinstates certificates." — the staffing ledger, the
    duty roster and the series standings are none of its business.

    PRD 3.6 fixes what the officer who may read the planning capability gets back: "A
    read-only staffing capability exposes the same computation for planning: it answers
    with the `race_id`, the boolean `staffing_ready`, the `staffed_position_codes`, the
    `missing_position_codes` still outstanding, and the coverage window as
    `coverage_window_start_utc` and `coverage_window_end_utc`."

    Design: Corner/rbac/measurer_cannot_read_duty_assignments_staffing_or_series_standing
    """
    chair_id = roster["chair"]["id"]
    measurer_id = roster["measurer"]["id"]
    helm_id = roster["helm_1"]["id"]
    regatta = open_regatta(chair_id)
    publish_nor(regatta["id"], chair_id)
    boat = register_boat(helm_id)
    certificate = file_and_issue_certificate(boat["id"], measurer_id)
    entry = submit_entry(regatta["id"], boat["id"], certificate["id"], helm_id)
    race = schedule_race(regatta["id"], chair_id, 1, RACE_1_SCHEDULED_START)
    measurer = make_measurer_headers(measurer_id)

    validate_error(
        api.list_duty_assignments(measurer),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        expected_status=403,
    )
    validate_error(
        api.get_staffing(race["id"], measurer),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        expected_status=403,
    )
    validate_error(
        api.get_series_standing(entry["id"], measurer),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        expected_status=403,
    )

    own_work = validate_success(api.get_certificate(certificate["id"], measurer))

    assert own_work["status"] == "ISSUED", "the measurer still reads what it filed"
    assert own_work["rating_value"] == RATING_A
    assert own_work["measured_by_member_id"] == measurer_id

    officer = make_race_officer_headers(roster["pro"]["id"])
    duties, page = validate_paginated(api.list_duty_assignments(officer))

    assert duties == [], "nobody has been rostered for this regatta yet"
    assert page["total_count"] == 0

    staffing = validate_success(api.get_staffing(race["id"], officer))

    assert staffing["race_id"] == race["id"]
    assert staffing["staffing_ready"] is False
    assert staffing["staffed_position_codes"] == []
    assert staffing["missing_position_codes"] == ALL_THREE_POSITIONS, (
        "a coastal distance course under CAT_4 asks for exactly these three"
    )
    assert_same_instant(staffing["coverage_window_start_utc"], "2026-08-05T13:30:00Z", "coverage_window_start_utc")
    assert_same_instant(staffing["coverage_window_end_utc"], "2026-08-05T16:00:00Z", "coverage_window_end_utc")
    assert entry["registration_status"] == "SUBMITTED", "no refusal touched the entry"


RACE_2_SCHEDULED_START = "2026-08-05T16:00:00Z"


def test_the_role_check_on_a_start_sequence_runs_before_the_race_is_even_looked_up(api):
    """PRD 2.7 item 3: "The acting role is listed against the endpoint in section 4, else
    `ERR_FORBIDDEN_ROLE`."

    PRD 2.7 item 8 sits five places later in the same strictly ordered list: "Every `id`
    in the path resolves, checked left to right, and then every foreign key in the body
    resolves, checked in the order the endpoint declares its inputs, else
    `ERR_RESOURCE_NOT_FOUND`."

    PRD 2.1 fixes whose job the start line is: "A `RaceOfficer` inspects equipment, runs
    starts, recalls, abandons and scores races and records results."

    Design: Corner/rbac/jury_chair_and_competitor_cannot_run_the_race_officer_start_sequence
    """
    world = build_started_race_world(start_races=(), clock=None)
    race_id = world["races"][1]["id"]
    jury = world["h"]["jury"]
    competitor = world["h"]["helm_1"]

    validate_error(
        api.start_sequence(race_id, jury),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        expected_status=403,
    )
    validate_error(
        api.start_sequence(race_id, competitor),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        expected_status=403,
    )
    validate_error(
        api.start_sequence(UNKNOWN_UUID, jury),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        expected_status=403,
    )
    validate_error(
        api.create_race(
            create_race_payload(world["regatta_id"], 2, RACE_2_SCHEDULED_START), jury
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        expected_status=403,
    )

    races, page = validate_paginated(
        api.list_races(jury, {"regatta_id": world["regatta_id"]})
    )

    assert page["total_count"] == 1, "the refused scheduling call wrote no second race"
    assert [race["race_number"] for race in races] == [1]

    readable = validate_success(api.get_race(race_id, jury))

    assert readable["start_status"] == "PENDING", "the jury may read what it may not run"
    assert readable["general_recall_count"] == 0
    assert readable["scoring_status"] == "NOT_SCORED"
    assert readable["actual_start_utc"] is None


def test_the_club_office_may_open_an_event_it_is_never_allowed_to_shape(api, roster):
    """PRD 3.3: "A regatta is opened by the club office or by the `RegattaChair` and
    starts life in status `DRAFT`." and "On creation, `nor_revision`, `si_revision`,
    `confirmed_division_count` and `final_race_count` are all 0 and `version` is 1."

    PRD 2.1 draws the line the moment the shell exists: "`ClubAdmin` is the club office
    operator: it maintains the member roster and member credentials and drives the
    logical clock in test environments, and it holds no racing authority whatsoever."
    and "When `X-User-Role` is `ClubAdmin`, `X-User-ID` is an opaque operator identifier
    not tied to any persisted entity; the server neither resolves it to a `ClubMember`
    row nor compares it to any entity's `id`."

    PRD 2.1 hands every one of those three verbs to somebody else: "A `RegattaChair`
    publishes documents, shapes divisions, admits entries, forms panels and staffs the
    committee."

    PRD 3.3 fixes what the chair's publication then produces: "The `revision` is never
    supplied by the client: an original publication takes revision 1, and an amendment
    takes one more than the revision it amends. The document's own `status` starts at
    `PUBLISHED`."

    Design: Corner/rbac/club_admin_cannot_publish_documents_or_shape_the_regatta
    """
    opened = validate_success(
        api.create_regatta(create_regatta_payload(fleet_minimum=2), ADMIN),
        expected_status=201,
    )

    assert opened["status"] == "DRAFT", "an opaque operator identifier opened the event"
    assert opened["nor_revision"] == 0
    assert opened["si_revision"] == 0
    assert opened["confirmed_division_count"] == 0
    assert opened["final_race_count"] == 0
    assert opened["version"] == 1

    validate_error(
        api.create_race_document(
            create_race_document_payload(opened["id"], 1), ADMIN
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        expected_status=403,
    )
    validate_error(
        api.create_division(create_division_payload(opened["id"]), ADMIN),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        expected_status=403,
    )
    validate_error(
        api.open_racing(opened["id"], ADMIN),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        expected_status=403,
    )

    untouched = read_regatta(opened["id"])

    assert untouched["status"] == "DRAFT", "three refusals moved nothing"
    assert untouched["nor_revision"] == 0
    assert untouched["si_revision"] == 0
    assert untouched["confirmed_division_count"] == 0
    assert untouched["version"] == 1, "a refused write never advances the version"

    documents, page = validate_paginated(
        api.list_race_documents(ADMIN, {"regatta_id": opened["id"]})
    )
    assert documents == []
    assert page["total_count"] == 0

    chair = make_regatta_chair_headers(roster["chair"]["id"])
    published = validate_success(
        api.create_race_document(create_race_document_payload(opened["id"], 1), chair),
        expected_status=201,
    )

    assert published["revision"] == 1
    assert published["status"] == "PUBLISHED", "not effective, not draft — published"
    assert published["doc_type"] == "NOR"
    assert published["effective_utc"] == NOR_EFFECTIVE_UTC
    assert published["amends_document_id"] is None

    now_open = read_regatta(opened["id"])
    assert now_open["status"] == "NOR_PUBLISHED", "the same payload, from the right role"
    assert now_open["nor_revision"] == 1
    assert now_open["version"] == 2


LICENCE_NUMBER = "M-101"


def test_the_credential_patch_is_the_club_office_key_that_unlocks_a_measurer(api):
    """PRD 2.1: "A `Measurer` whose `ClubMember` row has a null `measurer_license_id` is
    refused every certificate operation with `ERR_MEASURER_NOT_LICENSED`."

    PRD 3.1 fixes what an enrolment leaves behind and who may revise it: "Three
    credential fields are optional at enrolment and default to nothing:
    `measurer_license_id` defaults to null, `judge_certification_level` defaults to
    `NONE`, and `safety_course_expiry_utc` defaults to null." and "Those same three
    credential fields are the only mutable ones: a `ClubAdmin` may revise a licence
    number, a certification level or a safety-course expiry at any time, and each such
    revision advances the member's `version`."

    PRD 3.1 also fixes the version the first creation must echo: "A newly registered
    boat's `version` is 1, which is the value the first certificate creation must echo."

    PRD 3.2 fixes what the unlocked creation then mints: "The filed row is minted in
    status `DRAFT`, its `measured_by_member_id` is set from the acting measurer's
    identity, `suspension_reason_code` and `supersedes_certificate_id` both start null,
    and the boat's `version` advances by one."

    Design: Corner/rbac/club_admin_exclusive_credential_patch_unlocks_the_measurer
    """
    trainee = enrol_member("Ella Frost")
    owner = enrol_member("Bram Oakes")

    assert trainee["measurer_license_id"] is None
    assert trainee["judge_certification_level"] == "NONE"
    assert trainee["assigned_duty_minutes"] == 0
    assert trainee["version"] == 1

    boat = register_boat(owner["id"])
    assert boat["version"] == 1
    filing = create_certificate_payload(boat["id"], 1, **MEASUREMENT_A)

    validate_error(
        api.create_certificate(filing, make_measurer_headers(trainee["id"])),
        ApiErrorId.ERR_MEASURER_NOT_LICENSED,
        expected_status=403,
    )

    _, empty = validate_paginated(api.list_certificates(ADMIN, {"boat_id": boat["id"]}))
    assert empty["total_count"] == 0, "the licence refusal filed no measurement at all"
    assert read_boat(boat["id"])["version"] == 1, (
        "so the version the client already holds is still current"
    )

    licensed = validate_success(
        api.patch_club_member(trainee["id"], {"measurer_license_id": LICENCE_NUMBER}, ADMIN)
    )

    assert licensed["measurer_license_id"] == LICENCE_NUMBER
    assert licensed["judge_certification_level"] == "NONE", "one field revised, not three"
    assert licensed["safety_course_expiry_utc"] is None
    assert licensed["assigned_duty_minutes"] == 0
    assert licensed["version"] == 2

    filed = validate_success(
        api.create_certificate(filing, make_measurer_headers(trainee["id"])),
        expected_status=201,
    )

    assert filed["status"] == "DRAFT", "the identical payload, now from a licensed hand"
    assert filed["rating_value"] == RATING_A
    assert filed["measured_by_member_id"] == trainee["id"]
    assert filed["suspension_reason_code"] is None
    assert filed["supersedes_certificate_id"] is None
    assert read_boat(boat["id"])["version"] == 2

    re_credentialled = validate_success(
        api.patch_club_member(
            trainee["id"], {"safety_course_expiry_utc": SAFETY_COURSE_OK_UNTIL}, ADMIN
        )
    )

    assert re_credentialled["safety_course_expiry_utc"] == SAFETY_COURSE_OK_UNTIL
    assert re_credentialled["measurer_license_id"] == LICENCE_NUMBER, (
        "a patch of one credential leaves the others standing"
    )
    assert re_credentialled["judge_certification_level"] == "NONE"
    assert re_credentialled["version"] == 3


MORNING_WATCH = ("2026-08-05T12:00:00Z", "2026-08-05T14:00:00Z")
AFTERNOON_WATCH = ("2026-08-05T14:00:00Z", "2026-08-05T15:00:00Z")
TWO_JUDGE_QUORUM = 2


def test_a_seated_judge_reaches_the_start_line_only_once_the_seat_is_vacated(api, roster):
    """PRD 2.10: "A member who is seated and not recused on a `SEATED` panel of a regatta
    may not be the helm of any entry of that regatta, may not appear on any
    `crew_manifest` of that regatta, and may not hold a `CONFIRMED` duty assignment with
    `position` `PRO` for that regatta."

    PRD 3.6 fixes which hop of the duty lifecycle carries that check, and that the
    ledgers are already settled before it runs: "Confirmation puts the volunteer on
    station: `PROPOSED → CONFIRMED`. Neither ledger moves at confirmation, precisely
    because the `PROPOSED` row already counted" and "Confirmation of a duty whose
    `position` is `PRO` is blocked when that member currently occupies a non-recused seat
    on any `SEATED` jury panel of the same regatta, and the refusal is
    `ERR_JURY_CONFLICT_OF_INTEREST`."

    PRD 3.6 fixes the arithmetic of the two windows: "A proposed duty already counts in
    both ledgers. Its `duty_minutes` is the number of whole minutes between
    `window_start_utc` and `window_end_utc`; that figure is added to the volunteer's
    `assigned_duty_minutes` and, when a mark boat is named, to that boat's
    `committed_minutes`." and "Because the window is half-open, two back-to-back duties
    on the same volunteer that touch at exactly one instant do **not** collide; any
    genuine overlap of two non-released windows on the same `member_id` is refused with
    `ERR_MEMBER_DUTY_OVERLAP`."

    PRD 3.10 fixes the release of the conflict: "Recusal is the reverse, and it is the
    one panel operation reserved to the `JuryChair` of that panel. Naming a seated
    `member_id`, hop one marks that `seats` element's `recused` flag true and decrements
    `seated_member_count`. Hop two, caused by the first, moves the panel `SEATED →
    FORMING` when the refreshed count has fallen below the regatta's
    `jury_quorum_required`."

    Design: Corner/rbac/segregation_of_duties_blocks_confirming_a_seated_judge_as_principal_race_officer
    """
    chair_id = roster["chair"]["id"]
    judge_chair_id = roster["judge_chair"]["id"]
    double_hatted_id = roster["judge_member"]["id"]
    regatta = open_regatta(chair_id, jury_quorum_required=TWO_JUDGE_QUORUM)
    publish_nor(regatta["id"], chair_id)
    publish_si(regatta["id"], chair_id)
    panel = form_panel(regatta["id"], chair_id, judge_chair_id)
    seated = seat_judge(panel["id"], chair_id, double_hatted_id)

    assert seated["status"] == "SEATED"
    assert seated["seated_member_count"] == TWO_JUDGE_QUORUM

    principal = propose_duty(
        regatta["id"], chair_id, double_hatted_id, "PRO",
        window_start_utc=MORNING_WATCH[0], window_end_utc=MORNING_WATCH[1],
    )

    assert principal["status"] == "PROPOSED", "the proposal itself is never conflict-tested"
    assert principal["duty_minutes"] == 120
    assert read_member(double_hatted_id)["assigned_duty_minutes"] == 120

    chair = make_regatta_chair_headers(chair_id)
    validate_error(
        api.confirm_duty_assignment(principal["id"], chair),
        ApiErrorId.ERR_JURY_CONFLICT_OF_INTEREST,
        expected_status=409,
    )

    assert read_duty(principal["id"])["status"] == "PROPOSED", "the refusal held it back"
    assert read_member(double_hatted_id)["assigned_duty_minutes"] == 120, (
        "and it neither added nor subtracted a minute"
    )

    timekeeper = propose_duty(
        regatta["id"], chair_id, double_hatted_id, "TIMEKEEPER",
        window_start_utc=AFTERNOON_WATCH[0], window_end_utc=AFTERNOON_WATCH[1],
    )

    assert timekeeper["duty_minutes"] == 60, "14:00 to 15:00 touches the morning watch"
    confirmed = confirm_duty(timekeeper["id"], chair_id)

    assert confirmed["status"] == "CONFIRMED", "only the PRO position carries the conflict"
    assert read_member(double_hatted_id)["assigned_duty_minutes"] == 180, (
        "both creates booked their minutes and neither confirmation moved the ledger"
    )

    recused = validate_success(
        api.recuse_judge(
            panel["id"], recuse_payload(double_hatted_id),
            make_jury_chair_headers(judge_chair_id),
        )
    )

    assert recused["status"] == "FORMING", "one seat below a quorum of two"
    assert recused["seated_member_count"] == 1
    vacated = [seat for seat in recused["seats"] if seat["member_id"] == double_hatted_id]
    assert len(vacated) == 1
    assert vacated[0]["recused"] is True, "the seat is stood down, not deleted"

    on_station = validate_success(api.confirm_duty_assignment(principal["id"], chair))

    assert on_station["status"] == "CONFIRMED", "a recused seat taints nothing"
    assert on_station["position"] == "PRO"
    assert read_member(double_hatted_id)["assigned_duty_minutes"] == 180, (
        "the second confirmation is as much a ledger no-op as the first"
    )


BIGGER_RIG = {**MEASUREMENT_A, "sail_area_m2": 68.5}
BIGGEST_RIG = {**MEASUREMENT_A, "sail_area_m2": 69.0}


def test_a_boat_version_read_once_goes_stale_at_every_certificate_write(api, roster):
    """PRD 2.6: "Creating a rating certificate — `POST /rating-certificates` — requires
    the non-optional field `expected_boat_version`, carrying the client's last observed
    `version` of the `Boat` named by `boat_id`. If that value does not equal the boat's
    current `version`, the create is rejected with `ERR_STALE_BOAT_VERSION` and HTTP 412.
    Every certificate create, issue, suspend and reinstate increments `Boat.version` by
    1"

    PRD 2.6 also fixes that a second filing is not itself the fault: "A second
    certificate create against the same boat is perfectly valid behaviour when the
    client's view is current."

    PRD 3.1 fixes the opening value: "A newly registered boat's `version` is 1, which is
    the value the first certificate creation must echo."

    PRD 3.2 fixes the rating each filing mints: "Under `TOD_PHRF`, multiply
    `raw_speed_index` by 380.0, subtract that product from 420.0, round half-up to one
    decimal place, and then confine the result to the closed range from −30.0 to 300.0"

    Design: Corner/complexity_layers/stale_expected_boat_version_on_certificate_create_returns_412
    """
    measurer = make_measurer_headers(roster["measurer"]["id"])
    boat = register_boat(roster["helm_1"]["id"])
    first_seen = boat["version"]
    assert first_seen == 1

    first = validate_success(
        api.create_certificate(
            create_certificate_payload(boat["id"], first_seen, **MEASUREMENT_A), measurer
        ),
        expected_status=201,
    )

    assert first["status"] == "DRAFT"
    assert first["rating_value"] == RATING_A
    assert read_boat(boat["id"])["version"] == 2, "the create advanced the parent"

    validate_error(
        api.create_certificate(
            create_certificate_payload(boat["id"], first_seen, **BIGGER_RIG), measurer
        ),
        ApiErrorId.ERR_STALE_BOAT_VERSION,
        expected_status=412,
    )

    assert read_boat(boat["id"])["version"] == 2, (
        "the refusal wrote nothing, so the value just read stays current"
    )
    _, one_row = validate_paginated(api.list_certificates(ADMIN, {"boat_id": boat["id"]}))
    assert one_row["total_count"] == 1

    second_seen = validate_success(api.get_boat(boat["id"], measurer))["version"]
    assert second_seen == 2

    second = validate_success(
        api.create_certificate(
            create_certificate_payload(boat["id"], second_seen, **BIGGER_RIG), measurer
        ),
        expected_status=201,
    )

    assert second["rating_value"] == 170.4, "half a square metre of sail is 0.9 seconds"
    assert second["status"] == "DRAFT", "the identical payload, on a re-read version"
    assert read_boat(boat["id"])["version"] == 3

    issued = validate_success(api.issue_certificate(first["id"], measurer))

    assert issued["status"] == "ISSUED"
    assert read_boat(boat["id"])["version"] == 4, "an issue bumps the parent like a create"

    validate_error(
        api.create_certificate(
            create_certificate_payload(boat["id"], second_seen, **BIGGEST_RIG), measurer
        ),
        ApiErrorId.ERR_STALE_BOAT_VERSION,
        expected_status=412,
    )

    _, still_two = validate_paginated(api.list_certificates(ADMIN, {"boat_id": boat["id"]}))
    assert still_two["total_count"] == 2, "the version re-read once is now two writes behind"
    assert read_boat(boat["id"])["version"] == 4


NOR_AMENDMENT_EFFECTIVE_UTC = "2026-07-20T00:00:00Z"


def test_each_publication_invalidates_the_regatta_version_the_last_one_was_read_at(api, roster):
    """PRD 2.6: "Publishing a race document — `POST /race-documents` — requires the
    non-optional field `expected_regatta_version`, carrying the client's last observed
    `version` of the `Regatta` named by `regatta_id`. If that value does not equal the
    regatta's current `version`, the publication is rejected with
    `ERR_STALE_REGATTA_VERSION` and HTTP 412."

    PRD 2.6 gives the reason the precondition is not merely bookkeeping: "a stale version
    merely proves that the publisher has not seen the revision that landed in between,
    which would otherwise renumber revisions and point `amends_document_id` at a row that
    is already superseded."

    PRD 3.3 fixes each publication's effect on the parent: "Publishing the first `NOR`
    moves the regatta `DRAFT → NOR_PUBLISHED` and sets `nor_revision` to 1" and
    "Publishing the first `SI` requires the regatta to be in `NOR_PUBLISHED` with
    `nor_revision` of at least 1, and moves it `NOR_PUBLISHED → SI_PUBLISHED` with
    `si_revision` set to 1." and "Each of these publications advances the regatta's
    `version` by one."

    PRD 3.3 fixes what a landed amendment does: "When the amendment lands, the amended
    row moves `PUBLISHED → SUPERSEDED`, the new row takes the amended row's revision plus
    one, and the regatta's `nor_revision` or `si_revision` is set to the new revision."

    Design: Corner/complexity_layers/stale_then_current_expected_regatta_version_on_document_publish
    """
    chair_id = roster["chair"]["id"]
    chair = make_regatta_chair_headers(chair_id)
    regatta = open_regatta(chair_id)
    first_seen = regatta["version"]

    assert first_seen == 1
    assert regatta["nor_revision"] == 0
    assert regatta["si_revision"] == 0

    notice = validate_success(
        api.create_race_document(
            create_race_document_payload(regatta["id"], first_seen), chair
        ),
        expected_status=201,
    )

    assert notice["revision"] == 1
    assert notice["status"] == "PUBLISHED"
    opened = read_regatta(regatta["id"])
    assert opened["status"] == "NOR_PUBLISHED"
    assert opened["nor_revision"] == 1
    assert opened["version"] == 2

    instructions = create_race_document_payload(
        regatta["id"], first_seen,
        doc_type="SI", body_summary="Sailing instructions revision 1",
        effective_utc=SI_EFFECTIVE_UTC,
    )
    validate_error(
        api.create_race_document(instructions, chair),
        ApiErrorId.ERR_STALE_REGATTA_VERSION,
        expected_status=412,
    )

    unmoved = read_regatta(regatta["id"])
    assert unmoved["si_revision"] == 0, (
        "the version read before the notice is stale for the instructions"
    )
    assert unmoved["version"] == 2, "and the refusal advanced nothing"

    second_seen = validate_success(api.get_regatta(regatta["id"], chair))["version"]
    assert second_seen == 2

    sailed = validate_success(
        api.create_race_document(
            {**instructions, "expected_regatta_version": second_seen}, chair
        ),
        expected_status=201,
    )

    assert sailed["revision"] == 1, "the first SI is revision 1 in its own series"
    assert sailed["status"] == "PUBLISHED"
    instructed = read_regatta(regatta["id"])
    assert instructed["status"] == "SI_PUBLISHED"
    assert instructed["si_revision"] == 1
    assert instructed["version"] == 3

    amendment = create_race_document_payload(
        regatta["id"], second_seen,
        body_summary="Notice of race amendment 1",
        effective_utc=NOR_AMENDMENT_EFFECTIVE_UTC,
        amends_document_id=notice["id"],
    )
    validate_error(
        api.create_race_document(amendment, chair),
        ApiErrorId.ERR_STALE_REGATTA_VERSION,
        expected_status=412,
    )

    assert read_document(notice["id"])["status"] == "PUBLISHED", "nothing was superseded"
    assert read_regatta(regatta["id"])["nor_revision"] == 1

    third_seen = validate_success(api.get_regatta(regatta["id"], chair))["version"]
    assert third_seen == 3

    amended = validate_success(
        api.create_race_document(
            {**amendment, "expected_regatta_version": third_seen}, chair
        ),
        expected_status=201,
    )

    assert amended["revision"] == 2, "one more than the revision it amends"
    assert amended["status"] == "PUBLISHED"
    assert amended["amends_document_id"] == notice["id"]
    assert read_document(notice["id"])["status"] == "SUPERSEDED"

    settled = read_regatta(regatta["id"])
    assert settled["nor_revision"] == 2
    assert settled["si_revision"] == 1
    assert settled["status"] == "SI_PUBLISHED", "an amendment moves no phase"
    assert settled["version"] == 4

    documents, page = validate_paginated(
        api.list_race_documents(ADMIN, {"regatta_id": regatta["id"]})
    )
    assert page["total_count"] == 3, "the two refused publications wrote nothing"
    assert sorted(document["revision"] for document in documents) == [1, 1, 2]


UNASSIGNED_PAIR = (
    {
        "key": "A",
        "helm": "helm_1",
        "measurement": MEASUREMENT_A,
        "crew": [],
        "inspect": None,
        "assign": False,
        "accept": False,
    },
    {
        "key": "B",
        "helm": "helm_2",
        "measurement": MEASUREMENT_B,
        "crew": [],
        "inspect": None,
        "assign": False,
        "accept": False,
    },
)


def test_every_counter_a_write_moves_is_already_in_the_response_that_moved_it(api):
    """PRD 3.5: "The first candidate becomes the entry's `division_id`, both of that
    division's counts are refreshed, and the entry's `version` advances."

    PRD 3.4 fixes the parent counter the confirmation refreshes: "Confirmation is the
    chair's declaration that a real fleet exists. It is permitted only from
    `PROVISIONAL`, only while the regatta is in `NOR_PUBLISHED` or `SI_PUBLISHED`, and
    only when the division's `assigned_entry_count` has reached the greater of its own
    `min_entries` and the regatta's `fleet_minimum`" and "On success the division moves
    `PROVISIONAL → CONFIRMED`, the regatta's `confirmed_division_count` is refreshed and
    its `version` advances".

    Design: Corner/consistency_model/derived_counters_are_visible_in_the_same_response_that_moves_them
    """
    world = build_racing_world(
        regatta_overrides={"fleet_minimum": 2},
        publish="nor",
        divisions=TWO_BOAT_DIVISION,
        entrants=UNASSIGNED_PAIR,
        confirm_division_codes=(),
    )
    division_id = world["divisions"]["A"]["id"]
    chair = world["h"]["chair"]

    assert read_division(division_id)["assigned_entry_count"] == 0

    assigned = validate_success(api.assign_division(world["entries"]["A"]["id"], chair))

    assert assigned["division_id"] == division_id, (
        "the selector's own answer is in the response that computed it"
    )
    assert assigned["registration_status"] == "SUBMITTED"
    assert assigned["version"] == 2

    after_one = validate_success(api.get_division(division_id, chair))

    assert after_one["assigned_entry_count"] == 1, "no second write moved this counter"
    assert after_one["accepted_entry_count"] == 0
    assert after_one["status"] == "PROVISIONAL", "one entry is short of a floor of two"

    validate_success(api.assign_division(world["entries"]["B"]["id"], chair))
    confirmed = validate_success(api.confirm_division(division_id, chair))

    assert confirmed["assigned_entry_count"] == 2, (
        "the second assignment is visible on the confirm response with no refresh between"
    )
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["accepted_entry_count"] == 0, "assignment is not admission"

    parent = validate_success(api.get_regatta(world["regatta_id"], chair))

    assert parent["confirmed_division_count"] == 1, (
        "the parent counter was written inside the confirm request itself"
    )
    assert parent["status"] == "NOR_PUBLISHED"
