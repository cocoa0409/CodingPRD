"""Field-level contracts on the rows the registrar and the candidate create.

Declared defaults, computed openings, enum membership and the not-found answer on
a read are all properties of the row itself rather than of any workflow.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_defense_room,
    assert_faculty_member,
    assert_instant,
    assert_student,
    assert_term,
    assert_thesis,
)
from test_helpers.factories import (
    create_committee_member_payload,
    create_defense_room_payload,
    create_faculty_member_payload,
    create_student_payload,
    create_term_payload,
    create_thesis_payload,
)
from test_helpers.test_users import TEST_USERS, make_student_headers

REGISTRAR = TEST_USERS["registrar_headers"]
UNKNOWN_ID = "00000000-0000-0000-0000-0000000000aa"
UNKNOWN_COMMITTEE_ID = "00000000-0000-0000-0000-0000000000bb"


def test_term_create_echoes_every_deadline_and_opens_the_counter(
    api: ApiClient,
) -> None:
    """The created term is OPEN, has conferred nobody and echoes all three deadlines.

    PRD §3.1: "A newly created term is `OPEN`, and its `conferred_count` starts at 0."

    Design: Corner/entities/term_create_returns_201_with_all_declared_fields
    """
    fx.set_clock("2026-08-01T00:00:00Z")

    term = get_success_data(api.create_term(create_term_payload(), REGISTRAR), 201)
    assert_term(term)

    assert term["code"] == "2026FA"
    assert term["status"] == "OPEN"
    assert term["conferred_count"] == 0
    assert term["announcement_lead_business_days"] == 10
    assert_instant(term["defense_deadline"], "2026-11-13T23:59:59Z", "defense_deadline")
    assert_instant(
        term["format_review_deposit_deadline"],
        "2026-12-04T17:00:00Z",
        "format_review_deposit_deadline",
    )
    assert_instant(
        term["degree_conferral_date"],
        "2026-12-18T00:00:00Z",
        "degree_conferral_date",
    )
    assert term["version"] == 1


def test_omitted_announcement_lead_stores_ten_rather_than_null(api: ApiClient) -> None:
    """A term created without the override carries the declared lead of ten.

    PRD §3.1: "Creating a graduation term takes its `code`, its `defense_deadline`, its `format_review_deposit_deadline` and its `degree_conferral_date`, and optionally an `announcement_lead_business_days` override; when that override is omitted the term is created with a lead requirement of 10 business days, and any supplied value must be at least 1."

    Design: Corner/entities/term_omitted_announcement_lead_defaults_to_ten_business_days
    """
    fx.set_clock("2026-08-01T00:00:00Z")

    payload = create_term_payload(
        code="2027SP",
        defense_deadline="2027-04-16T23:59:59Z",
        format_review_deposit_deadline="2027-05-07T17:00:00Z",
        degree_conferral_date="2027-05-21T00:00:00Z",
    )
    payload.pop("announcement_lead_business_days")

    term = get_success_data(api.create_term(payload, REGISTRAR), 201)
    assert term["announcement_lead_business_days"] == 10
    assert term["code"] == "2027SP"
    assert term["status"] == "OPEN"


def test_faculty_certification_flag_defaults_to_false_with_no_load(
    api: ApiClient,
) -> None:
    """An uncertified faculty member is stored as such and carries no chair load.

    PRD §3.1: "Registering a faculty member takes `full_name`, `email` and `appointment_type`, plus an optional `graduate_faculty_certified` flag that defaults to false."

    Design: Corner/entities/faculty_member_graduate_faculty_certified_defaults_to_false
    """
    fx.set_clock("2026-08-01T00:00:00Z")

    payload = create_faculty_member_payload(
        full_name="Hal Iyer", email="hal@u.edu", appointment_type="TENURED"
    )
    payload.pop("graduate_faculty_certified")

    faculty = get_success_data(api.create_faculty_member(payload, REGISTRAR), 201)
    assert_faculty_member(faculty)

    assert faculty["graduate_faculty_certified"] is False
    assert faculty["active_chair_load"] == 0
    assert faculty["appointment_type"] == "TENURED"


def test_student_read_returns_the_blocked_unconferred_row(api: ApiClient) -> None:
    """The candidate reads back exactly what was registered, clearance still blocked.

    PRD §3.1: "A freshly registered candidate has `graduation_clearance_state` of `BLOCKED`, `degree_conferred` false and `transcript_notation` null — the notation stays null until either a conferral or an integrity withhold writes it."

    Design: Corner/entities/student_get_by_id_returns_stored_row
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    created = get_success_data(
        api.create_student(create_student_payload(), REGISTRAR), 201
    )

    student = get_success_data(
        api.get_student(created["id"], make_student_headers(created["id"])), 200
    )
    assert_student(student)

    assert student["full_name"] == "Ada Stone"
    assert student["email"] == "ada@u.edu"
    assert student["degree_level"] == "MASTERS"
    assert student["program_code"] == "CS"
    assert student["graduation_clearance_state"] == "BLOCKED"
    assert student["degree_conferred"] is False
    assert student["transcript_notation"] is None


def test_thesis_list_pages_one_row_at_a_time_with_a_total_of_two(
    api: ApiClient,
) -> None:
    """Each single-row page reports the full total and the correct has_more flag.

    PRD §2.3: "Every list response reports `limit`, `offset`, `total_count` and `has_more` inside `meta`, where `total_count` is the number of rows matching the filter before pagination is applied and `has_more` is true exactly when rows remain beyond the returned page."

    Design: Corner/entities/theses_list_returns_paginated_envelope_with_total_count_and_has_more
    """
    world = fx.setup_draft_thesis(thesis_overrides={"title": "First Thesis"})
    second_student = fx.add_student(
        world,
        full_name="Ben Ruiz",
        email="ben@u.edu",
        degree_level="MASTERS",
        program_code="CS",
    )
    second_thesis = fx.open_thesis(second_student, world["term"], title="Second Thesis")

    page_one, meta_one = validate_paginated(
        api.list_theses(
            REGISTRAR,
            params={"term_id": world["term"]["id"], "limit": 1, "offset": 0},
        )
    )
    assert len(page_one) == 1
    assert meta_one["total_count"] == 2
    assert meta_one["has_more"] is True
    assert page_one[0]["id"] == world["thesis"]["id"]

    page_two, meta_two = validate_paginated(
        api.list_theses(
            REGISTRAR,
            params={"term_id": world["term"]["id"], "limit": 1, "offset": 1},
        )
    )
    assert len(page_two) == 1
    assert meta_two["total_count"] == 2
    assert meta_two["has_more"] is False
    assert page_two[0]["id"] == second_thesis["id"]


def test_unknown_thesis_id_on_a_read_answers_not_found(api: ApiClient) -> None:
    """A well-formed but unresolvable path id is a 404, not an empty envelope.

    PRD §2.5: "**Path identifier resolution**, validated left to right along the URL so that the leftmost unresolvable segment is the one reported: `ERR_TERM_NOT_FOUND`, `ERR_STUDENT_NOT_FOUND`, `ERR_FACULTY_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`, `ERR_THESIS_NOT_FOUND`, `ERR_COMMITTEE_NOT_FOUND`, `ERR_COMMITTEE_MEMBER_NOT_FOUND`, `ERR_DEFENSE_NOT_FOUND`, `ERR_FORMAT_REVIEW_NOT_FOUND`, `ERR_EMBARGO_REQUEST_NOT_FOUND`, `ERR_PERMISSION_RECORD_NOT_FOUND` and `ERR_SCREENING_NOT_FOUND` are each HTTP 404."

    Design: Corner/entities/thesis_get_with_unknown_id_returns_not_found
    """
    fx.set_clock("2026-08-01T00:00:00Z")

    validate_error(api.get_thesis(UNKNOWN_ID, REGISTRAR), "ERR_THESIS_NOT_FOUND", 404)


def test_student_create_without_an_email_is_a_malformed_request(
    api: ApiClient,
) -> None:
    """The missing required field is refused and no row is left behind.

    PRD §2.5: "**Payload shape** — every required body field present, every value of the declared type, every enum value a legal member, every integer respecting its stated minimum, and `limit` inside 1 through 100: otherwise `ERR_INVALID_REQUEST`."

    Design: Corner/entities/student_create_missing_required_email_rejected
    """
    fx.set_clock("2026-08-01T00:00:00Z")

    payload = create_student_payload()
    payload.pop("email")
    validate_error(api.create_student(payload, REGISTRAR), "ERR_INVALID_REQUEST", 400)

    # Student email addresses are unique, so the same address being free proves the
    # refused create persisted nothing.
    repeated = get_success_data(
        api.create_student(create_student_payload(), REGISTRAR), 201
    )
    assert repeated["email"] == "ada@u.edu"


def test_student_create_with_a_degree_level_outside_the_pair_is_refused(
    api: ApiClient,
) -> None:
    """POSTDOC is not one of the two legal degree levels.

    PRD §3.1: "`degree_level` is either `MASTERS` or `DOCTORAL`, and it is load-bearing twice over: it drives the committee composition minimums and it halves the embargo duration caps."

    Design: Corner/entities/student_create_with_illegal_degree_level_enum_rejected
    """
    fx.set_clock("2026-08-01T00:00:00Z")

    validate_error(
        api.create_student(
            create_student_payload(degree_level="POSTDOC"), REGISTRAR
        ),
        "ERR_INVALID_REQUEST",
        400,
    )

    repeated = get_success_data(
        api.create_student(create_student_payload(), REGISTRAR), 201
    )
    assert repeated["degree_level"] == "MASTERS"


def test_thesis_create_with_a_page_count_of_zero_is_refused(api: ApiClient) -> None:
    """A zero page count breaks the declared minimum before any state check runs.

    PRD §3.2: "`page_count` must be at least 1 and reappears twice later: it drives the defect density factor of every format review, and a long document earns extra revision time."

    Design: Corner/entities/thesis_create_with_page_count_zero_rejected
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    term = fx.create_term()
    student = fx.create_student()

    validate_error(
        api.create_thesis(
            create_thesis_payload(
                student["id"], term["id"], title="Zero Pages", page_count=0
            ),
            make_student_headers(student["id"]),
        ),
        "ERR_INVALID_REQUEST",
        400,
    )

    rows, meta = validate_paginated(api.list_theses(REGISTRAR))
    assert rows == []
    assert meta["total_count"] == 0


def test_new_thesis_opens_every_counter_at_zero_with_a_blocked_clearance(
    api: ApiClient,
) -> None:
    """A fresh document is DRAFT and NOT_SCREENED with all three counters at zero.

    PRD §3.2: "On success the row is born with `workflow_state` `DRAFT` and `integrity_state` `NOT_SCREENED`, with `format_cycle_count`, `documented_permission_count` and `analyst_turnaround_bdays_total` all at 0, and with `accepted_at` null — that instant is written only when the document reaches `FORMAT_ACCEPTED`."

    Design: Corner/entities/thesis_computed_counters_and_states_initialised_on_create
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    term = fx.create_term()
    student = fx.create_student()

    payload = create_thesis_payload(student["id"], term["id"], title="Fresh Thesis")
    payload.pop("third_party_item_count")
    thesis = get_success_data(
        api.create_thesis(payload, make_student_headers(student["id"])), 201
    )
    assert_thesis(thesis)

    assert thesis["workflow_state"] == "DRAFT"
    assert thesis["integrity_state"] == "NOT_SCREENED"
    assert thesis["format_cycle_count"] == 0
    assert thesis["documented_permission_count"] == 0
    assert thesis["analyst_turnaround_bdays_total"] == 0
    assert thesis["accepted_at"] is None
    assert thesis["third_party_item_count"] == 0
    assert thesis["version"] == 1

    clearance = get_success_data(
        api.list_student_graduation_clearances(student["id"], REGISTRAR)
    )[0]
    assert clearance["status"] == "BLOCKED"


def test_seating_under_an_unknown_committee_reports_the_committee_not_found(
    api: ApiClient,
) -> None:
    """The path segment is resolved before the body faculty reference is considered.

    PRD §2.5: "**Path identifier resolution**, validated left to right along the URL so that the leftmost unresolvable segment is the one reported: `ERR_TERM_NOT_FOUND`, `ERR_STUDENT_NOT_FOUND`, `ERR_FACULTY_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`, `ERR_THESIS_NOT_FOUND`, `ERR_COMMITTEE_NOT_FOUND`, `ERR_COMMITTEE_MEMBER_NOT_FOUND`, `ERR_DEFENSE_NOT_FOUND`, `ERR_FORMAT_REVIEW_NOT_FOUND`, `ERR_EMBARGO_REQUEST_NOT_FOUND`, `ERR_PERMISSION_RECORD_NOT_FOUND` and `ERR_SCREENING_NOT_FOUND` are each HTTP 404."

    Design: Corner/entities/committee_member_create_under_unknown_committee_returns_not_found
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    chair = fx.create_faculty_member()

    validate_error(
        api.create_committee_member(
            UNKNOWN_COMMITTEE_ID,
            create_committee_member_payload(chair["id"], "CHAIR"),
            REGISTRAR,
        ),
        "ERR_COMMITTEE_NOT_FOUND",
        404,
    )

    faculty = get_success_data(api.get_faculty_member(chair["id"], REGISTRAR))
    assert faculty["active_chair_load"] == 0


def test_new_room_starts_empty_with_the_declared_buffer_and_status(
    api: ApiClient,
) -> None:
    """No input can seed the booked minutes, and both room defaults hold.

    PRD §3.1: "`turnover_buffer_minutes` is the minimum clear gap that must separate two occupations of that room; it defaults to 30 and may be 0 or more. `status` is either `AVAILABLE` or `MAINTENANCE` and defaults to `AVAILABLE`. A new room begins with `booked_minutes_total` of 0."

    Design: Corner/entities/defense_room_booked_minutes_total_is_system_managed_and_starts_zero
    """
    fx.set_clock("2026-08-01T00:00:00Z")

    payload = create_defense_room_payload()
    payload.pop("turnover_buffer_minutes")

    room = get_success_data(api.create_defense_room(payload, REGISTRAR), 201)
    assert_defense_room(room)

    assert room["booked_minutes_total"] == 0
    assert room["turnover_buffer_minutes"] == 30
    assert room["status"] == "AVAILABLE"
    assert room["seat_capacity"] == 40
