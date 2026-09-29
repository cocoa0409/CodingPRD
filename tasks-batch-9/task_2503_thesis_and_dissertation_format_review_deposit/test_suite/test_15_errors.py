"""Error identifiers, their HTTP statuses and the ladder order they fire in.

Where the PRD stacks several refusals on one endpoint, the test walks the ladder
rung by rung and finishes on the accepted call, so the order is pinned rather than
merely the individual codes.
"""

import pytest
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import assert_instant
from test_helpers.factories import (
    create_defense_event_payload,
    create_repository_deposit_payload,
    format_review_decision_payload,
)
from test_helpers.test_users import TEST_USERS, make_headers

REGISTRAR = TEST_USERS["registrar_headers"]
ANALYST_ONE = TEST_USERS["analyst_headers"]
ANALYST_TWO = TEST_USERS["analyst_two_headers"]
DEAN_TWO = TEST_USERS["dean_two_headers"]
INTEGRITY_OFFICER = TEST_USERS["integrity_officer_headers"]

MISSING_TERM_ID = "22222222-2222-4222-8222-222222222201"
MISSING_STUDENT_ID = "22222222-2222-4222-8222-222222222202"
MISSING_FACULTY_ID = "22222222-2222-4222-8222-222222222203"
MISSING_ROOM_ID = "22222222-2222-4222-8222-222222222204"
MISSING_THESIS_ID = "22222222-2222-4222-8222-222222222205"
MISSING_SEAT_ID = "22222222-2222-4222-8222-222222222206"
MISSING_DEFENSE_ID = "22222222-2222-4222-8222-222222222207"
MISSING_REVIEW_ID = "22222222-2222-4222-8222-222222222208"
MISSING_EMBARGO_ID = "22222222-2222-4222-8222-222222222209"
MISSING_COMMITTEE_ID = "22222222-2222-4222-8222-222222222210"
MISSING_PERMISSION_ID = "22222222-2222-4222-8222-222222222211"
MISSING_SCREENING_ID = "22222222-2222-4222-8222-222222222212"
ABSENT_STUDENT_ID = "22222222-2222-4222-8222-222222222299"


def test_a_headerless_read_and_an_invented_role_both_answer_unauthenticated(
    api: ApiClient,
) -> None:
    """401 rather than 403, because the caller never authenticated in the first place.

    PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the six roles named below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/request_missing_x_user_role_header_returns_unauthenticated
    """
    fx.set_clock("2026-08-01T00:00:00Z")

    anonymous = validate_error(
        api.list_theses({}), "ERR_UNAUTHENTICATED", 401
    )
    assert anonymous["message"].strip() != ""

    invented = validate_error(
        api.list_theses(make_headers("prov-1", "Provost")),
        "ERR_UNAUTHENTICATED",
        401,
    )
    assert invented["message"].strip() != ""


def test_a_limit_of_one_hundred_and_one_is_malformed_while_one_hundred_is_not(
    api: ApiClient,
) -> None:
    """The page-size bound is inclusive at 100 and validated like any other input.

    PRD §2.3: "A `limit` outside the inclusive range 1 through 100 is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/errors/theses_list_with_limit_above_the_maximum_rejected
    """
    fx.setup_draft_thesis(thesis_overrides={"title": "Paged Thesis"})

    validate_error(
        api.list_theses(REGISTRAR, params={"limit": 101}), "ERR_INVALID_REQUEST", 400
    )

    rows, meta = validate_paginated(
        api.list_theses(REGISTRAR, params={"limit": 100, "offset": 0})
    )
    assert len(rows) == 1
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_every_entity_family_owns_its_own_not_found_identifier(api: ApiClient) -> None:
    """Twelve unresolvable ids produce twelve distinct 404 codes, never a shared one.

    PRD §2.5: "**Path identifier resolution**, validated left to right along the URL so that the leftmost unresolvable segment is the one reported: `ERR_TERM_NOT_FOUND`, `ERR_STUDENT_NOT_FOUND`, `ERR_FACULTY_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`, `ERR_THESIS_NOT_FOUND`, `ERR_COMMITTEE_NOT_FOUND`, `ERR_COMMITTEE_MEMBER_NOT_FOUND`, `ERR_DEFENSE_NOT_FOUND`, `ERR_FORMAT_REVIEW_NOT_FOUND`, `ERR_EMBARGO_REQUEST_NOT_FOUND`, `ERR_PERMISSION_RECORD_NOT_FOUND` and `ERR_SCREENING_NOT_FOUND` are each HTTP 404."

    Design: Corner/errors/unknown_ids_return_the_matching_not_found_error
    """
    fx.set_clock("2026-08-01T00:00:00Z")

    validate_error(api.get_term(MISSING_TERM_ID, REGISTRAR), "ERR_TERM_NOT_FOUND", 404)
    validate_error(
        api.get_student(MISSING_STUDENT_ID, REGISTRAR), "ERR_STUDENT_NOT_FOUND", 404
    )
    validate_error(
        api.get_faculty_member(MISSING_FACULTY_ID, REGISTRAR),
        "ERR_FACULTY_NOT_FOUND",
        404,
    )
    validate_error(
        api.get_defense_room(MISSING_ROOM_ID, REGISTRAR), "ERR_ROOM_NOT_FOUND", 404
    )
    validate_error(
        api.get_thesis(MISSING_THESIS_ID, REGISTRAR), "ERR_THESIS_NOT_FOUND", 404
    )
    validate_error(
        api.get_committee_member(MISSING_SEAT_ID, REGISTRAR),
        "ERR_COMMITTEE_MEMBER_NOT_FOUND",
        404,
    )
    validate_error(
        api.get_defense_event(MISSING_DEFENSE_ID, REGISTRAR),
        "ERR_DEFENSE_NOT_FOUND",
        404,
    )
    validate_error(
        api.get_format_review(MISSING_REVIEW_ID, REGISTRAR),
        "ERR_FORMAT_REVIEW_NOT_FOUND",
        404,
    )
    validate_error(
        api.get_embargo_request(MISSING_EMBARGO_ID, REGISTRAR),
        "ERR_EMBARGO_REQUEST_NOT_FOUND",
        404,
    )
    validate_error(
        api.submit_committee(
            MISSING_COMMITTEE_ID, make_headers(ABSENT_STUDENT_ID, "Student")
        ),
        "ERR_COMMITTEE_NOT_FOUND",
        404,
    )
    validate_error(
        api.review_permission_record(
            MISSING_PERMISSION_ID, {"decision": "ACCEPT"}, ANALYST_ONE
        ),
        "ERR_PERMISSION_RECORD_NOT_FOUND",
        404,
    )
    validate_error(
        api.act_on_integrity_screening(
            MISSING_SCREENING_ID, {"action": "REFER"}, INTEGRITY_OFFICER
        ),
        "ERR_SCREENING_NOT_FOUND",
        404,
    )


def test_the_term_transitions_and_the_closed_window_report_different_codes(
    api: ApiClient,
) -> None:
    """Wrong-transition guards say STATE_INVALID; candidate work after closing says CLOSED.

    PRD §2.9: "The two term transitions are themselves state-guarded, and a mismatch is `ERR_TERM_STATE_INVALID` (HTTP 409): closing the deposit window requires `status` to be `OPEN`, and posting conferral requires `status` to be `DEPOSIT_CLOSED`."

    PRD §2.9: "Once it leaves `OPEN`, eighteen operations are refused with `ERR_TERM_DEPOSIT_CLOSED` (HTTP 409): opening a committee record, seating a committee member, releasing a committee seat, submitting the composition, ruling on the composition, scheduling a defense, announcing a defense, recording a defense outcome, cancelling a defense, submitting a format review cycle, deciding a format review, documenting a permission record, reviewing a permission record, requesting an embargo, ruling on an embargo, supplementing an embargo request, recording an integrity screening, and creating a repository deposit."

    Design: Corner/errors/term_lifecycle_errors_on_confer_and_on_writes_after_close
    """
    world = fx.setup_draft_thesis(thesis_overrides={"title": "Lifecycle Guards"})
    term_id = world["term"]["id"]
    fx.set_clock("2026-12-05T09:00:00Z")

    validate_error(
        api.confer_term_degrees(term_id, REGISTRAR), "ERR_TERM_STATE_INVALID", 409
    )
    assert get_success_data(api.get_term(term_id, REGISTRAR))["status"] == "OPEN"

    closed = get_success_data(api.close_term_deposit(term_id, REGISTRAR), 200)
    assert closed["status"] == "DEPOSIT_CLOSED"

    validate_error(
        api.create_format_submission(world["thesis"]["id"], world["student_headers"]),
        "ERR_TERM_DEPOSIT_CLOSED",
        409,
    )
    assert (
        get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))[
            "format_cycle_count"
        ]
        == 0
    )

    validate_error(
        api.close_term_deposit(term_id, REGISTRAR), "ERR_TERM_STATE_INVALID", 409
    )

    term = get_success_data(api.get_term(term_id, REGISTRAR))
    assert term["status"] == "DEPOSIT_CLOSED"
    assert term["conferred_count"] == 0


def test_the_accept_ladder_asks_for_the_screening_before_the_permission_dossier(
    api: ApiClient,
) -> None:
    """Screening first, then permissions, and once accepted the cycle refuses a redo.

    PRD §3.5: "The document must have been screened at all: an `integrity_state` of `NOT_SCREENED` is refused with `ERR_SCREENING_REQUIRED` (HTTP 409)."

    PRD §3.5: "Every permission record for the document must have reached `ACCEPTED` or `WAIVED`, and `documented_permission_count` must be at least `third_party_item_count`; a still-`SUBMITTED` or `DEFICIENT` record, or a shortfall against the declared item count, is refused with `ERR_PERMISSIONS_INCOMPLETE` (HTTP 422)."

    PRD §3.5: "It is legal only while the target cycle is `PENDING_REVIEW`; any other cycle status is `ERR_FORMAT_REVIEW_STATE_INVALID` (HTTP 409)."

    Design: Corner/errors/format_accept_rejects_missing_screening_then_incomplete_permissions
    """
    world = fx.setup_passed_defense(
        thesis_overrides={"title": "Gated Accept", "third_party_item_count": 1}
    )
    record = fx.document_permission(
        world,
        material_type="FIGURE",
        rights_basis="WRITTEN_PERMISSION",
        page_reference="p. 42",
        document_uri="https://repo.u.edu/permissions/fig-42.pdf",
    )
    review = fx.open_format_cycle(world, clock="2026-10-05T09:00:00Z")
    fx.set_clock("2026-10-12T09:00:00Z")
    accept = format_review_decision_payload("ACCEPT", 0, 0, 0)

    validate_error(
        api.decide_format_review(review["id"], accept, ANALYST_ONE),
        "ERR_SCREENING_REQUIRED",
        409,
    )

    screening = fx.record_screening(world, similarity_pct=5.0)
    assert screening["status"] == "CLEARED"

    validate_error(
        api.decide_format_review(review["id"], accept, ANALYST_ONE),
        "ERR_PERMISSIONS_INCOMPLETE",
        422,
    )
    assert (
        get_success_data(api.get_format_review(review["id"], REGISTRAR))["status"]
        == "PENDING_REVIEW"
    )

    fx.review_permission(
        world, record, decision="ACCEPT", review_note="Signed letter on file"
    )
    assert (
        get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))[
            "documented_permission_count"
        ]
        == 1
    )

    accepted = get_success_data(
        api.decide_format_review(review["id"], accept, ANALYST_ONE), 200
    )
    assert accepted["status"] == "ACCEPTED"
    assert (
        get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))[
            "workflow_state"
        ]
        == "FORMAT_ACCEPTED"
    )

    validate_error(
        api.decide_format_review(
            review["id"],
            format_review_decision_payload("RETURN_REVISIONS", 1, 0, 0),
            ANALYST_ONE,
        ),
        "ERR_FORMAT_REVIEW_STATE_INVALID",
        409,
    )

    final = get_success_data(api.get_format_review(review["id"], REGISTRAR))
    assert final["decision"] == "ACCEPT"
    assert final["critical_defect_count"] == 0


def test_the_deposit_ladder_runs_metadata_then_fee_then_duplicate(
    api: ApiClient,
) -> None:
    """0.7000 metadata, then an unowed 2500 cents, then a second deposit of the same row.

    PRD §3.8: "The repository requires at least 0.8500, so exactly 0.8500 passes and anything lower is refused with `ERR_METADATA_INCOMPLETE` (HTTP 422)."

    PRD §3.8: "The tendered `late_fee_paid_cents` must equal that computed figure exactly; any other amount, high or low, is refused with `ERR_LATE_FEE_MISMATCH` (HTTP 402)."

    PRD §3.8: "The document must be `FORMAT_ACCEPTED`, or the attempt is `ERR_THESIS_STATE_INVALID`."

    PRD §2.5 puts stage 11 ("Entity state preconditions ... `ERR_THESIS_STATE_INVALID`")
    ahead of stage 16 (`ERR_DEPOSIT_ALREADY_EXISTS`), and a successful deposit advances the
    document `FORMAT_ACCEPTED → DEPOSITED`, so the second attempt on the same row is
    reported by the thesis-state gate.

    Design: Corner/errors/deposit_rejects_incomplete_metadata_wrong_fee_and_duplicate
    """
    world = fx.setup_format_accepted_thesis(
        cycle_clock="2026-10-05T09:00:00Z",
        similarity_pct=5.0,
        excluded_quoted_pct=None,
        decision_clock="2026-10-12T09:00:00Z",
        thesis_overrides={"title": "Deposit Gates"},
    )
    thesis_id = world["thesis"]["id"]
    fx.set_clock("2026-11-02T10:00:00Z")
    keywords = ["a", "b", "c"]

    validate_error(
        api.create_repository_deposit(
            create_repository_deposit_payload(
                thesis_id,
                abstract_word_count=150,
                subject_keywords=keywords,
                late_fee_paid_cents=0,
            ),
            ANALYST_TWO,
        ),
        "ERR_METADATA_INCOMPLETE",
        422,
    )

    validate_error(
        api.create_repository_deposit(
            create_repository_deposit_payload(
                thesis_id,
                abstract_word_count=150,
                subject_keywords=keywords,
                late_fee_paid_cents=2500,
                advisor_name="Cara Cho",
                department_code="CS",
            ),
            ANALYST_TWO,
        ),
        "ERR_LATE_FEE_MISMATCH",
        402,
    )
    assert get_success_data(api.get_thesis_repository_deposit(thesis_id, REGISTRAR)) == []

    settled = create_repository_deposit_payload(
        thesis_id,
        abstract_word_count=150,
        subject_keywords=keywords,
        late_fee_paid_cents=0,
        advisor_name="Cara Cho",
        department_code="CS",
    )
    deposit = get_success_data(
        api.create_repository_deposit(settled, ANALYST_TWO), 201
    )
    assert deposit["metadata_completeness_score"] == pytest.approx(1.0000, abs=0.0001)
    assert deposit["late_fee_cents"] == 0

    validate_error(
        api.create_repository_deposit(settled, ANALYST_TWO),
        "ERR_THESIS_STATE_INVALID",
        409,
    )

    rows = get_success_data(api.get_thesis_repository_deposit(thesis_id, REGISTRAR))
    assert len(rows) == 1
    assert (
        get_success_data(api.get_thesis(thesis_id, REGISTRAR))["workflow_state"]
        == "DEPOSITED"
    )


def test_a_supplement_is_legal_only_once_the_dean_has_asked_for_information(
    api: ApiClient,
) -> None:
    """The same call is refused on a REQUESTED row and accepted on a MORE_INFO_REQUIRED one.

    PRD §3.7: "The candidate answers an information request by supplying a replacement `justification`, which is legal only while the request is `MORE_INFO_REQUIRED` — a supplement against a request in any other status is refused with `ERR_EMBARGO_STATE_INVALID` — and returns it to `REQUESTED` with the old narrative overwritten."

    Design: Corner/errors/supplement_on_a_requested_embargo_rejected
    """
    world = fx.setup_passed_defense(thesis_overrides={"title": "Embargo Loop"})
    embargo = fx.request_embargo(
        world,
        reason_code="PUBLISHER_AGREEMENT",
        requested_months=6,
        justification="Chapter 3 is under review at a journal.",
    )

    validate_error(
        api.supplement_embargo_request(
            embargo["id"],
            {"justification": "Adding the acceptance letter reference."},
            world["student_headers"],
        ),
        "ERR_EMBARGO_STATE_INVALID",
        409,
    )

    untouched = get_success_data(api.get_embargo_request(embargo["id"], REGISTRAR))
    assert untouched["status"] == "REQUESTED"
    assert untouched["justification"] == "Chapter 3 is under review at a journal."
    assert untouched["info_request_count"] == 0

    pushed_back = get_success_data(
        api.decide_embargo_request(
            embargo["id"],
            {
                "decision": "REQUEST_INFO",
                "decision_note": "Name the journal and the expected issue date.",
            },
            DEAN_TWO,
        ),
        200,
    )
    assert pushed_back["status"] == "MORE_INFO_REQUIRED"

    supplemented = get_success_data(
        api.supplement_embargo_request(
            embargo["id"],
            {"justification": "Journal of Systems, issue expected 2027-03."},
            world["student_headers"],
        ),
        200,
    )
    assert supplemented["status"] == "REQUESTED"
    assert supplemented["justification"] == "Journal of Systems, issue expected 2027-03."
    assert supplemented["info_request_count"] == 1
    assert supplemented["decided_at"] is None


def test_nine_business_days_of_lead_is_short_and_ten_is_enough(api: ApiClient) -> None:
    """One day earlier than the requirement is refused; rescheduling one day later announces.

    PRD §3.4: "The gate is the announcement lead, measured as the number of business days between the current logical instant and the event's `scheduled_start`, and the announcement is refused when that count is fewer than the term's `announcement_lead_business_days`; a lead of exactly the required number of business days passes. A short lead is `ERR_ANNOUNCEMENT_LEAD_TOO_SHORT` (HTTP 422)."

    Design: Corner/errors/announcement_lead_of_nine_business_days_rejected
    """
    world = fx.setup_scheduled_defense(
        term_overrides={
            "defense_deadline": "2026-12-11T23:59:59Z",
            "format_review_deposit_deadline": "2027-01-15T17:00:00Z",
            "degree_conferral_date": "2027-01-29T00:00:00Z",
        },
        schedule_clock="2026-11-16T09:00:00Z",
        scheduled_start="2026-12-01T14:00:00Z",
        scheduled_end="2026-12-01T16:00:00Z",
        thesis_overrides={"title": "Lead Boundary"},
    )
    short_event = world["defense_event"]

    validate_error(
        api.announce_defense_event(short_event["id"], ANALYST_ONE),
        "ERR_ANNOUNCEMENT_LEAD_TOO_SHORT",
        422,
    )

    still_draft = get_success_data(api.get_defense_event(short_event["id"], REGISTRAR))
    assert still_draft["status"] == "DRAFT"
    assert still_draft["announced_at"] is None
    assert (
        get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))[
            "workflow_state"
        ]
        == "DEFENSE_SCHEDULED"
    )

    get_success_data(
        api.cancel_defense_event(
            short_event["id"],
            {"cancellation_reason": "Rescheduled to satisfy the announcement lead."},
            ANALYST_ONE,
        ),
        200,
    )

    rescheduled = get_success_data(
        api.create_defense_event(
            create_defense_event_payload(
                world["thesis"]["id"],
                world["room"]["id"],
                scheduled_start="2026-12-02T14:00:00Z",
                scheduled_end="2026-12-02T16:00:00Z",
            ),
            world["student_headers"],
        ),
        201,
    )

    announced = get_success_data(
        api.announce_defense_event(rescheduled["id"], ANALYST_ONE), 200
    )
    assert announced["status"] == "ANNOUNCED"
    assert announced["announcement_lead_bdays"] == 10
    assert_instant(announced["announced_at"], "2026-11-16T09:00:00Z", "announced_at")

    assert (
        get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))[
            "workflow_state"
        ]
        == "DEFENSE_ANNOUNCED"
    )
    assert (
        get_success_data(api.get_defense_room(world["room"]["id"], REGISTRAR))[
            "booked_minutes_total"
        ]
        == 120
    )
