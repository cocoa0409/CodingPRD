"""Refusals taken in the order the server declares them: the two authentication
gates, the role list, the measurer licence, the pagination bounds, the acting
party, the mark-boat pairing rule, the amendment target and its clock, the phase
gate, the uniqueness rules and the certificate validity window — each refusal
followed by the corrected request that proves the gate, not the endpoint, was
what stood in the way.
"""

from prd_bench_local_runner.testing import (
    build_user_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    CERT_VALID_FROM,
    DUTY_WINDOW_END,
    DUTY_WINDOW_START,
    NOR_EFFECTIVE_UTC,
    UNKNOWN_UUID,
    ApiErrorId,
    add_crew_payload,
    charter_mark_boat,
    create_boat_payload,
    create_certificate_payload,
    create_club_member_payload,
    create_division_payload,
    create_duty_assignment_payload,
    create_race_document_payload,
    enrol_member,
    file_and_issue_certificate,
    make_club_admin_headers,
    make_competitor_headers,
    make_headers_without_user_id,
    make_measurer_headers,
    make_regatta_chair_headers,
    open_regatta,
    patch_club_member_payload,
    publish_nor,
    publish_si,
    read_boat,
    read_document,
    read_entry,
    read_mark_boat,
    read_member,
    read_regatta,
    register_boat,
    submit_entry,
)

ADMIN = make_club_admin_headers()


def test_both_authentication_gates_outrank_the_role_list_on_a_member_listing(api):
    """PRD 2.7 item 1: "Both authentication headers are present and `X-User-Role` is
    one of the six declared roles, else `ERR_UNAUTHENTICATED`."

    PRD 2.7 item 2: "For a member-backed role, `X-User-ID` resolves to an existing
    `ClubMember` row, else `ERR_UNKNOWN_ACTOR`. This check applies to every endpoint
    except member enrolment."

    PRD 2.1 fixes that the opaque role carries no member at all: "When `X-User-Role`
    is `ClubAdmin`, `X-User-ID` is an opaque operator identifier not tied to any
    persisted entity; the server neither resolves it to a `ClubMember` row nor
    compares it to any entity's `id`."

    Design: Corner/validations/missing_x_user_id_header_returns_unauthenticated
    """
    only_member = enrol_member(full_name="Piers Holt")

    validate_error(
        api.list_club_members(make_headers_without_user_id("ClubAdmin"), {"limit": 10}),
        ApiErrorId.ERR_UNAUTHENTICATED,
        expected_status=401,
    )
    validate_error(
        api.list_club_members(build_user_headers("ops-desk-1", "Commodore"), {"limit": 10}),
        ApiErrorId.ERR_UNAUTHENTICATED,
        expected_status=401,
    )
    validate_error(
        api.list_club_members(make_regatta_chair_headers(UNKNOWN_UUID), {"limit": 10}),
        ApiErrorId.ERR_UNKNOWN_ACTOR,
        expected_status=403,
    )

    rows, pagination = validate_paginated(api.list_club_members(ADMIN, {"limit": 10}))

    assert pagination["total_count"] == 1, "no rejected read wrote anything"
    assert rows[0]["id"] == only_member["id"]
    assert read_member(only_member["id"])["version"] == 1


def test_a_competitor_is_turned_away_from_open_racing_before_the_phase_is_examined(api):
    """PRD 2.7 item 3: "The acting role is listed against the endpoint in section 4,
    else `ERR_FORBIDDEN_ROLE`."

    PRD 2.7 fixes that the earlier check answers alone: "A single malformed or
    ill-timed request frequently violates several rules at once. The server therefore
    evaluates its checks in one strict, global order and answers with the **first**
    failing check — never with a later one, and never with a collection of them."

    PRD 2.7 item 11 names the answer the authorised caller earns instead: "The target
    row is in a state from which the requested transition exists, on the dimension
    that endpoint advances, else `ERR_INVALID_STATE`. This check applies to every
    action endpoint — that is, every operation that names a verb on a single
    resource."

    Design: Corner/validations/competitor_calling_open_racing_returns_forbidden_role
    """
    chair = enrol_member(full_name="Nadia Reyes")
    competitor = enrol_member(full_name="Owen Clay")
    regatta = open_regatta(chair["id"])

    validate_error(
        api.open_racing(regatta["id"], build_user_headers(competitor["id"], "Competitor")),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        expected_status=403,
    )
    validate_error(
        api.open_racing(regatta["id"], make_regatta_chair_headers(chair["id"])),
        ApiErrorId.ERR_INVALID_STATE,
        expected_status=409,
    )

    unmoved = validate_success(api.get_regatta(regatta["id"], ADMIN))
    assert unmoved["status"] == "DRAFT", "neither refusal advanced the phase"
    assert unmoved["version"] == 1
    assert unmoved["si_revision"] == 0
    assert unmoved["confirmed_division_count"] == 0


def test_the_licence_check_stands_between_an_unlicensed_measurer_and_a_rating(api):
    """PRD 2.7 item 4: "When the acting role is `Measurer`, the acting member's
    `measurer_license_id` is non-null, else `ERR_MEASURER_NOT_LICENSED`. This check
    applies to certificate creation and to every certificate action — issue, suspend
    and reinstate."

    PRD 3.1 makes the licence a revisable credential rather than a fixed property:
    "Those same three credential fields are the only mutable ones: a `ClubAdmin` may
    revise a licence number, a certification level or a safety-course expiry at any
    time, and each such revision advances the member's `version`."

    Design: Corner/validations/unlicensed_measurer_blocked_from_certificate_create
    """
    unlicensed = enrol_member(full_name="Delia Marsh")
    owner = enrol_member(full_name="Owen Clay")
    boat = register_boat(owner["id"])
    assert unlicensed["measurer_license_id"] is None

    validate_error(
        api.create_certificate(
            create_certificate_payload(boat["id"], 1),
            make_measurer_headers(unlicensed["id"]),
        ),
        ApiErrorId.ERR_MEASURER_NOT_LICENSED,
        expected_status=403,
    )
    assert read_boat(boat["id"])["version"] == 1, "the refusal bumped nothing"
    _, empty = validate_paginated(api.list_certificates(ADMIN, {"boat_id": boat["id"]}))
    assert empty["total_count"] == 0

    licensed = validate_success(
        api.patch_club_member(
            unlicensed["id"], patch_club_member_payload(measurer_license_id="M-777"), ADMIN
        )
    )
    assert licensed["measurer_license_id"] == "M-777"
    assert licensed["version"] == 2

    filed = validate_success(
        api.create_certificate(
            create_certificate_payload(boat["id"], 1),
            make_measurer_headers(unlicensed["id"]),
        ),
        expected_status=201,
    )

    assert filed["status"] == "DRAFT"
    assert filed["measured_by_member_id"] == unlicensed["id"]
    assert filed["raw_speed_index"] == 0.6545
    assert filed["rating_value"] == 171.3
    assert read_boat(boat["id"])["version"] == 2, "the accepted create is the only bump"


def test_the_page_window_bounds_admit_their_edges_and_refuse_everything_outside(api):
    """PRD 2.3: "Every collection read accepts two optional query parameters. `limit`
    is an integer with a default of 10, a minimum of 1 and a maximum of 100. `offset`
    is an integer with a default of 0 and a minimum of 0; it has no upper bound. A
    `limit` outside the inclusive range 1 to 100, or a negative `offset`, or a
    non-integer value for either, is rejected with `ERR_INVALID_PAGINATION`."

    PRD 2.3 also fixes what the accepted windows must report: "List responses carry
    `limit`, `offset`, `total_count` and `has_more` in `meta`, where `total_count` is
    the number of rows matching the filters before the page window is applied and
    `has_more` states whether any matching row remains after the current window."

    Design: Corner/validations/pagination_limit_and_offset_boundaries_pass_before_out_of_range_values_fail
    """
    owner = enrol_member(full_name="Owen Clay")
    first = register_boat(owner["id"])
    second = register_boat(owner["id"])

    wide, wide_meta = validate_paginated(api.list_boats(ADMIN, {"limit": 100, "offset": 0}))
    assert wide_meta["limit"] == 100, "the upper edge of the range is admitted"
    assert wide_meta["offset"] == 0
    assert wide_meta["total_count"] == 2
    assert wide_meta["has_more"] is False
    assert sorted(row["id"] for row in wide) == sorted([first["id"], second["id"]])

    tail, tail_meta = validate_paginated(api.list_boats(ADMIN, {"limit": 1, "offset": 1}))
    assert tail_meta["limit"] == 1, "and so is the lower edge"
    assert tail_meta["offset"] == 1
    assert tail_meta["total_count"] == 2, "counted before the window was applied"
    assert tail_meta["has_more"] is False, "nothing remains after the second row"
    assert len(tail) == 1

    for window in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
        validate_error(
            api.list_boats(ADMIN, window),
            ApiErrorId.ERR_INVALID_PAGINATION,
            expected_status=400,
        )

    defaulted, default_meta = validate_paginated(api.list_boats(ADMIN))
    assert default_meta["limit"] == 10
    assert default_meta["offset"] == 0
    assert default_meta["total_count"] == 2
    assert default_meta["has_more"] is False
    assert len(defaulted) == 2


INTRUDER_SAIL_NUMBER = "USA-9100"


def _two_helms_world():
    """A regatta with its notice of race out and one submitted, crewless entry for
    each of two helms, so every version below starts at 1."""
    chair = enrol_member(full_name="Nadia Reyes")
    measurer = enrol_member(full_name="Delia Marsh", measurer_license_id="M-101")
    first_helm = enrol_member(full_name="Owen Clay")
    second_helm = enrol_member(full_name="Rhea Voss")
    regatta = open_regatta(chair["id"])
    publish_nor(regatta["id"], chair["id"])
    entries = {}
    for key, helm in (("A", first_helm), ("B", second_helm)):
        boat = register_boat(helm["id"])
        certificate = file_and_issue_certificate(boat["id"], measurer["id"])
        entries[key] = submit_entry(
            regatta["id"], boat["id"], certificate["id"], helm["id"]
        )
    return {
        "regatta": regatta,
        "first_helm": first_helm,
        "second_helm": second_helm,
        "entries": entries,
    }


def test_a_helm_may_not_touch_another_helms_entry_or_register_another_members_boat(api):
    """PRD 2.1: "A `Competitor` registers boats, submits entries, maintains the crew
    manifest, withdraws, files protests and submits evidence, and acts only on its own
    boats and the entries it helms. Its `X-User-ID` must equal `owner_member_id` of the
    boat being registered, `helm_member_id` of the entry being acted on, or
    `helm_member_id` of the entry named as `protestor_entry_id` when filing a protest.
    Any other case is rejected with `ERR_NOT_ACTING_PARTY`."

    PRD 2.7 item 5 fixes that all three of these operations are inside the check:
    "Acting-party identity as described in section 2.1, else `ERR_NOT_ACTING_PARTY`.
    This check applies to exactly twelve operations: boat registration, entry
    submission, crew addition, crew removal, entry withdrawal, protest filing, evidence
    filing, hearing scheduling, holding a hearing, deciding a protest, reopening a
    protest, invalidating a protest, and jury recusal."

    Design: Corner/validations/competitor_acting_on_another_helms_entry_returns_not_acting_party
    """
    world = _two_helms_world()
    target_id = world["entries"]["A"]["id"]
    owner_id = world["first_helm"]["id"]
    intruder_id = world["second_helm"]["id"]
    intruder = make_competitor_headers(intruder_id)

    validate_error(
        api.withdraw_entry(target_id, intruder),
        ApiErrorId.ERR_NOT_ACTING_PARTY,
        expected_status=403,
    )
    validate_error(
        api.add_crew(
            target_id, add_crew_payload(intruder_id, position="TRIM", weight_kg=79.0), intruder
        ),
        ApiErrorId.ERR_NOT_ACTING_PARTY,
        expected_status=403,
    )
    validate_error(
        api.create_boat(
            create_boat_payload(owner_id, sail_number=INTRUDER_SAIL_NUMBER), intruder
        ),
        ApiErrorId.ERR_NOT_ACTING_PARTY,
        expected_status=403,
    )

    untouched = read_entry(target_id)
    assert untouched["registration_status"] == "SUBMITTED"
    assert untouched["registered_crew_count"] == 0
    assert untouched["version"] == 1, "not one of the three refusals left a mark"
    rows, pagination = validate_paginated(api.list_boats(ADMIN, {"limit": 100}))
    assert pagination["total_count"] == 2, "the boat named for another owner was never made"
    assert INTRUDER_SAIL_NUMBER not in [row["sail_number"] for row in rows]

    withdrawn = validate_success(
        api.withdraw_entry(target_id, make_competitor_headers(owner_id))
    )

    assert withdrawn["registration_status"] == "WITHDRAWN", "the helm itself was always able to"
    assert withdrawn["version"] == 2
    sibling = read_entry(world["entries"]["B"]["id"])
    assert sibling["registration_status"] == "SUBMITTED"
    assert sibling["version"] == 1


EIGHT_HOURS = 480


def test_a_duty_must_name_a_mark_boat_only_when_it_should_and_only_of_its_own_regatta(api):
    """PRD 3.6: "`mark_boat_id` must be present when `position` is `MARK_BOAT_DRIVER`
    or `SAFETY_BOAT` and absent for every other position, and the boat named must be
    chartered for the same regatta; otherwise `ERR_MARK_BOAT_ASSIGNMENT_INVALID`."

    PRD 3.6 fixes what the accepted proposal must move: "A proposed duty already
    counts in both ledgers. Its `duty_minutes` is the number of whole minutes between
    `window_start_utc` and `window_end_utc`; that figure is added to the volunteer's
    `assigned_duty_minutes` and, when a mark boat is named, to that boat's
    `committed_minutes`."

    Design: Corner/validations/mark_boat_of_other_regatta_rejected
    """
    chair = enrol_member(full_name="Nadia Reyes")
    volunteer = enrol_member(full_name="Owen Clay")
    home = open_regatta(chair["id"])
    away = open_regatta(chair["id"])
    home_boat = charter_mark_boat(home["id"], chair["id"])
    away_boat = charter_mark_boat(away["id"], chair["id"])
    chair_headers = make_regatta_chair_headers(chair["id"])

    for position, mark_boat_id in (
        ("MARK_BOAT_DRIVER", None),
        ("PRO", home_boat["id"]),
        ("SAFETY_BOAT", away_boat["id"]),
    ):
        payload = create_duty_assignment_payload(
            home["id"], volunteer["id"], position,
            DUTY_WINDOW_START, DUTY_WINDOW_END,
        )
        if mark_boat_id is not None:
            payload["mark_boat_id"] = mark_boat_id
        validate_error(
            api.create_duty_assignment(payload, chair_headers),
            ApiErrorId.ERR_MARK_BOAT_ASSIGNMENT_INVALID,
            expected_status=422,
        )

    assert read_mark_boat(home_boat["id"])["committed_minutes"] == 0
    assert read_mark_boat(away_boat["id"])["committed_minutes"] == 0
    assert read_member(volunteer["id"])["assigned_duty_minutes"] == 0, (
        "no refused proposal touched either ledger"
    )

    proposed = validate_success(
        api.create_duty_assignment(
            create_duty_assignment_payload(
                home["id"], volunteer["id"], "MARK_BOAT_DRIVER",
                DUTY_WINDOW_START, DUTY_WINDOW_END, mark_boat_id=home_boat["id"],
            ),
            chair_headers,
        ),
        expected_status=201,
    )

    assert proposed["status"] == "PROPOSED"
    assert proposed["mark_boat_id"] == home_boat["id"]
    assert proposed["duty_minutes"] == EIGHT_HOURS
    assert read_mark_boat(home_boat["id"])["committed_minutes"] == EIGHT_HOURS
    assert read_member(volunteer["id"])["assigned_duty_minutes"] == EIGHT_HOURS
    assert read_mark_boat(away_boat["id"])["committed_minutes"] == 0, (
        "the other regatta's boat was never committed"
    )


NOR_AMENDMENT_EFFECTIVE_UTC = "2026-07-11T00:00:00Z"


def test_an_amendment_needs_a_live_target_of_its_own_type_and_a_strictly_later_clock(api):
    """PRD 3.3: "Amendments work through `amends_document_id`, which names the
    currently `PUBLISHED` revision being superseded. That field must be present exactly
    when a published document of the same type already exists for the regatta, and
    absent exactly when none does; it must name a document of the same `regatta_id` and
    the same `doc_type`, and that document must still be `PUBLISHED` rather than already
    superseded. A violation of any of those conditions is `ERR_AMENDMENT_TARGET_INVALID`.
    An amendment's `effective_utc` must additionally fall strictly later than the
    `effective_utc` of the document it amends; otherwise `ERR_AMENDMENT_NOT_LATER`. When
    the amendment lands, the amended row moves `PUBLISHED → SUPERSEDED`, the new row
    takes the amended row's revision plus one, and the regatta's `nor_revision` or
    `si_revision` is set to the new revision."

    Design: Corner/validations/nor_amendment_without_target_then_not_later_rejected
    """
    chair = enrol_member(full_name="Nadia Reyes")
    regatta = open_regatta(chair["id"])
    notice = publish_nor(regatta["id"], chair["id"])
    instructions = publish_si(regatta["id"], chair["id"])
    assert notice["effective_utc"] == NOR_EFFECTIVE_UTC
    assert read_regatta(regatta["id"])["version"] == 3
    chair_headers = make_regatta_chair_headers(chair["id"])

    orphan = create_race_document_payload(
        regatta["id"], 3, doc_type="NOR",
        body_summary="Notice of race revision 2",
        effective_utc=NOR_AMENDMENT_EFFECTIVE_UTC,
    )
    validate_error(
        api.create_race_document(orphan, chair_headers),
        ApiErrorId.ERR_AMENDMENT_TARGET_INVALID,
        expected_status=409,
    )
    validate_error(
        api.create_race_document(
            {**orphan, "amends_document_id": instructions["id"]}, chair_headers
        ),
        ApiErrorId.ERR_AMENDMENT_TARGET_INVALID,
        expected_status=409,
    )
    validate_error(
        api.create_race_document(
            {
                **orphan,
                "amends_document_id": notice["id"],
                "effective_utc": NOR_EFFECTIVE_UTC,
            },
            chair_headers,
        ),
        ApiErrorId.ERR_AMENDMENT_NOT_LATER,
        expected_status=422,
    )

    amendment = validate_success(
        api.create_race_document(
            {**orphan, "amends_document_id": notice["id"]}, chair_headers
        ),
        expected_status=201,
    )

    assert amendment["revision"] == 2, "the amended row's revision plus one"
    assert amendment["status"] == "PUBLISHED"
    assert amendment["amends_document_id"] == notice["id"]
    assert amendment["effective_utc"] == NOR_AMENDMENT_EFFECTIVE_UTC
    assert read_document(notice["id"])["status"] == "SUPERSEDED"
    assert read_document(instructions["id"])["status"] == "PUBLISHED", (
        "the sailing instructions were never a target"
    )

    final = read_regatta(regatta["id"])
    assert final["nor_revision"] == 2
    assert final["si_revision"] == 1, "only the amended type's counter moved"
    assert final["status"] == "SI_PUBLISHED"
    assert final["version"] == 4, "three refusals and one publication"


def test_a_division_may_not_be_drawn_up_before_the_notice_of_race_is_out(api):
    """PRD 3.4: "Divisions may only be created while the regatta is in `NOR_PUBLISHED`
    or `SI_PUBLISHED`."

    PRD 2.7 item 12: "The regatta is in the phase the operation requires, else
    `ERR_REGATTA_PHASE_INVALID`. Division creation requires `NOR_PUBLISHED` or
    `SI_PUBLISHED`; entry submission requires that the regatta is no longer `DRAFT`,
    the too-late cases being handled by the next check; starting a sequence, recording
    a result and scoring a race all require `RACING`."

    PRD 3.4 also fixes the shape the admitted division opens with: "A division opens
    in status `PROVISIONAL` with `assigned_entry_count` and `accepted_entry_count` both
    0 and `merged_into_division_id` null."

    Design: Corner/validations/division_created_before_notice_of_race_returns_regatta_phase_invalid
    """
    chair = enrol_member(full_name="Nadia Reyes")
    regatta = open_regatta(chair["id"])
    chair_headers = make_regatta_chair_headers(chair["id"])
    payload = create_division_payload(regatta["id"], code="A")

    validate_error(
        api.create_division(payload, chair_headers),
        ApiErrorId.ERR_REGATTA_PHASE_INVALID,
        expected_status=409,
    )
    _, empty = validate_paginated(
        api.list_divisions(chair_headers, {"regatta_id": regatta["id"]})
    )
    assert empty["total_count"] == 0, "the refused creation left no row behind"

    published = publish_nor(regatta["id"], chair["id"])
    assert published["status"] == "PUBLISHED"
    opened = read_regatta(regatta["id"])
    assert opened["status"] == "NOR_PUBLISHED"
    assert opened["nor_revision"] == 1

    division = validate_success(api.create_division(payload, chair_headers), expected_status=201)

    assert division["status"] == "PROVISIONAL"
    assert division["code"] == "A"
    assert division["assigned_entry_count"] == 0
    assert division["accepted_entry_count"] == 0
    assert division["merged_into_division_id"] is None
    assert division["version"] == 1

    settled = read_regatta(regatta["id"])
    assert settled["confirmed_division_count"] == 0, "a provisional division is not confirmed"
    assert settled["version"] == 2, "only the publication moved the regatta"


DUPLICATE_SAIL_NUMBER = "USA-4410"
FRESH_SAIL_NUMBER = "USA-4411"


def test_a_repeated_sail_number_and_a_repeated_address_are_both_duplicate_records(api):
    """PRD 3.1: "A registration carries a `sail_number` unique across every boat in
    the register — again compared case-insensitively, between 3 and 12 characters, and
    refused with `ERR_DUPLICATE_RECORD` on collision — a `boat_name`, an
    `owner_member_id` naming the member of record who may submit entries for that boat,
    a `boat_type` of `MONOHULL`, `MULTIHULL` or `KEELBOAT_SPORT`, and a declared
    `loa_meters` greater than 0 and at most 40."

    PRD 3.1 states the same rule for the roster: "A `ClubAdmin` enrols a club member
    with a `full_name` and an `email`; the address must contain an at sign and is unique
    across all members, compared without regard to letter case, so a second enrolment on
    the same address is refused with `ERR_DUPLICATE_RECORD`."

    Design: Corner/validations/duplicate_sail_number_rejected
    """
    first_owner = validate_success(
        api.create_club_member(
            create_club_member_payload(
                full_name="Owen Clay", email="owen.clay@example-yacht-club.test"
            ),
            ADMIN,
        ),
        expected_status=201,
    )
    second_owner = enrol_member(full_name="Rhea Voss")
    original = validate_success(
        api.create_boat(
            create_boat_payload(
                first_owner["id"], sail_number=DUPLICATE_SAIL_NUMBER,
                boat_name="Windward Rose",
            ),
            make_competitor_headers(first_owner["id"]),
        ),
        expected_status=201,
    )

    validate_error(
        api.create_boat(
            create_boat_payload(
                second_owner["id"], sail_number=DUPLICATE_SAIL_NUMBER,
                boat_name="Second Wind", boat_type="MULTIHULL",
            ),
            make_competitor_headers(second_owner["id"]),
        ),
        ApiErrorId.ERR_DUPLICATE_RECORD,
        expected_status=409,
    )
    validate_error(
        api.create_club_member(
            create_club_member_payload(
                full_name="Owen Clay the Second", email="owen.clay@example-yacht-club.test"
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_DUPLICATE_RECORD,
        expected_status=409,
    )

    fresh = validate_success(
        api.create_boat(
            create_boat_payload(first_owner["id"], sail_number=FRESH_SAIL_NUMBER),
            make_competitor_headers(first_owner["id"]),
        ),
        expected_status=201,
    )

    assert fresh["sail_number"] == FRESH_SAIL_NUMBER
    assert fresh["version"] == 1
    boats, boat_meta = validate_paginated(api.list_boats(ADMIN, {"limit": 100}))
    assert boat_meta["total_count"] == 2, "the collided registration was never stored"
    assert sorted(row["id"] for row in boats) == sorted([original["id"], fresh["id"]])
    _, member_meta = validate_paginated(api.list_club_members(ADMIN, {"limit": 100}))
    assert member_meta["total_count"] == 2, "and neither was the collided enrolment"


VALID_UNTIL_ONE_SECOND_LATER = "2026-01-01T00:00:01Z"


def test_a_certificate_window_that_does_not_open_is_out_of_range(api):
    """PRD 3.2: "The validity window is declared with `valid_from` and `valid_until`,
    and `valid_until` must fall strictly after `valid_from`. Any measured quantity
    outside its range, or a window whose end does not strictly follow its start, is
    refused with `ERR_MEASUREMENT_OUT_OF_RANGE`."

    PRD 3.2 also fixes what the accepted filing does to the boat: "The filed row is
    minted in status `DRAFT`, its `measured_by_member_id` is set from the acting
    measurer's identity, `suspension_reason_code` and `supersedes_certificate_id` both
    start null, and the boat's `version` advances by one."

    Design: Corner/validations/certificate_valid_until_not_after_valid_from_rejected
    """
    measurer = enrol_member(full_name="Delia Marsh", measurer_license_id="M-101")
    owner = enrol_member(full_name="Owen Clay")
    boat = register_boat(owner["id"])
    measurer_headers = make_measurer_headers(measurer["id"])

    validate_error(
        api.create_certificate(
            create_certificate_payload(
                boat["id"], 1, valid_from=CERT_VALID_FROM, valid_until=CERT_VALID_FROM
            ),
            measurer_headers,
        ),
        ApiErrorId.ERR_MEASUREMENT_OUT_OF_RANGE,
        expected_status=422,
    )
    assert read_boat(boat["id"])["version"] == 1, "a window of zero length wrote nothing"

    admitted = validate_success(
        api.create_certificate(
            create_certificate_payload(
                boat["id"], 1,
                valid_from=CERT_VALID_FROM, valid_until=VALID_UNTIL_ONE_SECOND_LATER,
            ),
            measurer_headers,
        ),
        expected_status=201,
    )

    assert admitted["valid_from"] == CERT_VALID_FROM
    assert admitted["valid_until"] == VALID_UNTIL_ONE_SECOND_LATER, (
        "one second of validity is strictly later, and that is the whole test"
    )
    assert admitted["status"] == "DRAFT"
    assert admitted["rating_value"] == 171.3
    assert admitted["supersedes_certificate_id"] is None
    assert read_boat(boat["id"])["version"] == 2
