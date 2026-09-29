"""The non-CRUD surface: a computed read, a link create, the clock and the bulk run.

These operations are the ones whose contract lives in the response body rather than
in a stored row, so each test reads the answer and then proves what did or did not
change underneath it.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_conferral_notation,
    assert_graduation_clearance,
    assert_instant,
    assert_outstanding_items_in_fixed_order,
)
from test_helpers.factories import (
    create_committee_member_payload,
    create_committee_payload,
    create_thesis_payload,
)
from test_helpers.test_users import TEST_USERS, make_student_headers

REGISTRAR = TEST_USERS["registrar_headers"]
ANALYST_TWO = TEST_USERS["analyst_two_headers"]
UNKNOWN_FACULTY_ID = "11111111-1111-4111-8111-111111111111"


def test_readiness_rehearses_the_deposit_without_touching_a_single_row(
    api: ApiClient,
) -> None:
    """Two items outstanding in the fixed order, no fee yet, and the next blocker named.

    PRD §3.8: "A read-only readiness projection replays the clearance evaluation and the late-fee arithmetic against the current logical clock and reports `thesis_id`, the current `workflow_state`, the `projection_variant` that would apply, the `outstanding_items` array, the `projected_late_fee_cents` a deposit would incur right now, and `next_blocking_error_id` — the identifier of the error the next deposit attempt would raise, or null when the deposit would succeed."

    Design: Corner/endpoints/deposit_readiness_read_lists_outstanding_items_in_the_fixed_order
    """
    world = fx.setup_passed_defense(thesis_overrides={"title": "Readiness Probe"})
    embargo = fx.request_embargo(
        world,
        reason_code="PATENT_PENDING",
        requested_months=12,
        justification="Provisional patent application filed",
    )
    world["format_review"] = fx.open_format_cycle(world, clock="2026-10-05T09:00:00Z")
    fx.record_screening(world, similarity_pct=5.0)
    fx.decide_format_review(
        world, world["format_review"], clock="2026-10-12T09:00:00Z"
    )
    fx.set_clock("2026-11-02T10:00:00Z")

    readiness = get_success_data(
        api.get_deposit_readiness(world["thesis"]["id"], ANALYST_TWO), 200
    )
    assert readiness["thesis_id"] == world["thesis"]["id"]
    assert readiness["workflow_state"] == "FORMAT_ACCEPTED"
    assert readiness["projection_variant"] == "PROVISIONAL"
    assert readiness["outstanding_items"] == ["EMBARGO_DECISION", "DEPOSIT"]
    assert_outstanding_items_in_fixed_order(readiness["outstanding_items"])
    assert readiness["projected_late_fee_cents"] == 0
    assert readiness["next_blocking_error_id"] == "ERR_EMBARGO_UNDECIDED"

    clearance = get_success_data(
        api.list_student_graduation_clearances(world["student"]["id"], REGISTRAR)
    )[0]
    assert_graduation_clearance(clearance)
    assert clearance["status"] == "PENDING_ITEMS"

    assert (
        get_success_data(api.get_embargo_request(embargo["id"], REGISTRAR))["status"]
        == "REQUESTED"
    )
    assert (
        get_success_data(
            api.get_thesis_repository_deposit(world["thesis"]["id"], REGISTRAR)
        )
        == []
    )


def test_a_seat_cannot_be_linked_to_a_faculty_row_that_does_not_exist(
    api: ApiClient,
) -> None:
    """The body foreign key is resolved before the seat is created, and 404 leaves nothing.

    PRD §2.5: "**Body foreign-key resolution**, validated in the order the fields appear in the operation's input list, reporting `ERR_STUDENT_NOT_FOUND`, `ERR_TERM_NOT_FOUND`, `ERR_THESIS_NOT_FOUND`, `ERR_FACULTY_NOT_FOUND` or `ERR_ROOM_NOT_FOUND` according to which referenced record could not be found."

    Design: Corner/endpoints/committee_member_link_requires_an_existing_faculty_row
    """
    world = fx.setup_draft_thesis(thesis_overrides={"title": "Link Integrity"})
    committee = get_success_data(
        api.create_committee(
            create_committee_payload(world["thesis"]["id"]), world["student_headers"]
        ),
        201,
    )

    validate_error(
        api.create_committee_member(
            committee["id"],
            create_committee_member_payload(UNKNOWN_FACULTY_ID, "CHAIR"),
            world["student_headers"],
        ),
        "ERR_FACULTY_NOT_FOUND",
        404,
    )
    assert (
        get_success_data(api.get_thesis_committee(world["thesis"]["id"], REGISTRAR))[0][
            "member_count"
        ]
        == 0
    )

    seat = get_success_data(
        api.create_committee_member(
            committee["id"],
            create_committee_member_payload(world["chair"]["id"], "CHAIR"),
            world["student_headers"],
        ),
        201,
    )
    assert seat["committee_id"] == committee["id"]
    assert seat["faculty_id"] == world["chair"]["id"]

    assert (
        get_success_data(api.get_thesis_committee(world["thesis"]["id"], REGISTRAR))[0][
            "member_count"
        ]
        == 1
    )
    rows, _ = validate_paginated(
        api.list_committee_members(REGISTRAR, params={"committee_id": committee["id"]})
    )
    assert len(rows) == 1


def test_moving_the_clock_stamps_the_next_write_and_nothing_already_written(
    api: ApiClient,
) -> None:
    """The echoed instant governs later rows while earlier rows keep their old stamps.

    PRD §2.4: "A `Registrar` may move it with the test-driving capability described in §4, which takes a single `to_iso8601` instant and answers with the resulting `current_utc`; setting the clock mutates no entity and fires no cascade."

    Design: Corner/endpoints/clock_action_sets_the_logical_clock_without_mutating_entities
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    term = fx.create_term()
    student = fx.create_student()

    moved = get_success_data(api.set_clock("2026-08-03T08:00:00Z", REGISTRAR), 200)
    assert_instant(moved["current_utc"], "2026-08-03T08:00:00Z", "current_utc")

    unchanged_student = get_success_data(
        api.get_student(student["id"], make_student_headers(student["id"]))
    )
    assert_instant(
        unchanged_student["updated_at"], "2026-08-01T00:00:00Z", "student updated_at"
    )
    assert unchanged_student["version"] == 1

    unchanged_term = get_success_data(api.get_term(term["id"], REGISTRAR))
    assert_instant(
        unchanged_term["updated_at"], "2026-08-01T00:00:00Z", "term updated_at"
    )

    thesis = get_success_data(
        api.create_thesis(
            create_thesis_payload(student["id"], term["id"], title="Clock Stamped"),
            make_student_headers(student["id"]),
        ),
        201,
    )
    assert_instant(thesis["created_at"], "2026-08-03T08:00:00Z", "thesis created_at")


def test_conferral_skips_the_unready_candidate_rather_than_rolling_back(
    api: ApiClient,
) -> None:
    """One run confers the deposited candidate, counts the drafting one and stops there.

    PRD §3.9: "The term's `conferred_count` is then set to the number of clearances that reached `CONFERRED` in this run, and the term itself moves `DEPOSIT_CLOSED → CONFERRED`, which is terminal. The run answers with the `term_id` together with `conferred_count`, `withheld_count` and `pending_count` — the three tallies of candidates conferred, withheld and left with items outstanding."

    Design: Corner/endpoints/confer_degrees_reports_conferred_and_pending_counts_and_writes_notations
    """
    world = fx.setup_deposited_thesis(
        cycle_clock="2026-10-05T09:00:00Z",
        similarity_pct=5.0,
        excluded_quoted_pct=None,
        decision_clock="2026-10-12T09:00:00Z",
        deposit_clock="2026-11-02T10:00:00Z",
        thesis_overrides={"title": "Conferred Candidate"},
        deposit_overrides={"abstract_word_count": 220},
    )
    drafting_student = fx.add_student(
        world,
        full_name="Ben Ruiz",
        email="ben@u.edu",
        degree_level="MASTERS",
        program_code="CS",
    )
    drafting_thesis = fx.open_thesis(
        drafting_student, world["term"], title="Still Drafting", page_count=90
    )

    fx.set_clock("2026-12-18T09:00:00Z")
    fx.close_term_deposit(world)

    run = get_success_data(api.confer_term_degrees(world["term"]["id"], REGISTRAR), 200)
    assert run["term_id"] == world["term"]["id"]
    assert run["conferred_count"] == 1
    assert run["withheld_count"] == 0
    assert run["pending_count"] == 1

    term = get_success_data(api.get_term(world["term"]["id"], REGISTRAR))
    assert term["status"] == "CONFERRED"
    assert term["conferred_count"] == 1

    conferred_thesis = get_success_data(
        api.get_thesis(world["thesis"]["id"], REGISTRAR)
    )
    assert conferred_thesis["workflow_state"] == "CONFERRED"

    graduate = get_success_data(api.get_student(world["student"]["id"], REGISTRAR))
    assert graduate["degree_conferred"] is True
    assert graduate["graduation_clearance_state"] == "CONFERRED"
    assert_conferral_notation(graduate["transcript_notation"], "THESIS", "2026-11-02")

    clearance = get_success_data(
        api.list_student_graduation_clearances(world["student"]["id"], REGISTRAR)
    )[0]
    assert clearance["status"] == "CONFERRED"
    assert clearance["projection_variant"] == "FINAL"
    assert_instant(
        clearance["conferral_posted_at"],
        "2026-12-18T09:00:00Z",
        "conferral_posted_at",
    )

    deposit = get_success_data(
        api.get_thesis_repository_deposit(world["thesis"]["id"], REGISTRAR)
    )[0]
    assert deposit["status"] == "DEPOSITED"

    skipped_thesis = get_success_data(api.get_thesis(drafting_thesis["id"], REGISTRAR))
    assert skipped_thesis["workflow_state"] == "DRAFT"

    skipped_student = get_success_data(
        api.get_student(drafting_student["id"], REGISTRAR)
    )
    assert skipped_student["degree_conferred"] is False
    assert skipped_student["transcript_notation"] is None

    skipped_clearance = get_success_data(
        api.list_student_graduation_clearances(drafting_student["id"], REGISTRAR)
    )[0]
    assert skipped_clearance["status"] == "BLOCKED"
