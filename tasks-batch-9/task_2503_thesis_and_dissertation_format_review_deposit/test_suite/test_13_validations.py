"""Input, aggregate, cross-entity and temporal guards on the write path.

Every test pairs the refusal with the neighbouring legal case wherever the PRD
draws the boundary inclusively, so the assertion pins the edge rather than merely
observing that something was rejected.
"""

import pytest
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.factories import (
    create_committee_member_payload,
    create_committee_payload,
    create_defense_event_payload,
    create_embargo_request_payload,
    create_permission_record_payload,
    create_thesis_payload,
)
from test_helpers.test_users import (
    DEAN_ONE_USER_ID,
    DEAN_TWO_USER_ID,
    TEST_USERS,
    make_dean_headers,
)

REGISTRAR = TEST_USERS["registrar_headers"]
ANALYST_ONE = TEST_USERS["analyst_headers"]
DEAN_TWO = TEST_USERS["dean_two_headers"]


def test_a_written_permission_needs_its_letter_but_public_domain_does_not(
    api: ApiClient,
) -> None:
    """The evidence rule fires for one rights basis and leaves the other alone.

    PRD §3.5: "When the claimed `rights_basis` is `WRITTEN_PERMISSION`, `document_uri` must be a non-empty string, or the create is refused with `ERR_PERMISSION_EVIDENCE_MISSING` (HTTP 422)."

    Design: Corner/validations/written_permission_without_document_uri_rejected
    """
    world = fx.setup_draft_thesis(
        thesis_overrides={"title": "Two Reused Items", "third_party_item_count": 2}
    )
    thesis_id = world["thesis"]["id"]
    version = fx.thesis_version(thesis_id)

    validate_error(
        api.create_permission_record(
            create_permission_record_payload(
                thesis_id,
                version,
                material_type="FIGURE",
                rights_basis="WRITTEN_PERMISSION",
                page_reference="p. 8",
            ),
            world["student_headers"],
        ),
        "ERR_PERMISSION_EVIDENCE_MISSING",
        422,
    )
    assert (
        get_success_data(api.list_thesis_permission_records(thesis_id, REGISTRAR)) == []
    )

    accepted = get_success_data(
        api.create_permission_record(
            create_permission_record_payload(
                thesis_id,
                version,
                material_type="FIGURE",
                rights_basis="PUBLIC_DOMAIN",
                page_reference="p. 9",
            ),
            world["student_headers"],
        ),
        201,
    )
    assert accepted["status"] == "SUBMITTED"
    assert accepted["document_uri"] is None

    thesis = get_success_data(api.get_thesis(thesis_id, REGISTRAR))
    assert thesis["documented_permission_count"] == 0


def test_a_four_hundred_word_excerpt_passes_and_four_hundred_and_one_does_not(
    api: ApiClient,
) -> None:
    """The fair-use word bound is inclusive, and the accepted create bumps the parent.

    PRD §3.5: "When the claimed basis is `FAIR_USE_ASSERTION`, the reused `excerpt_word_count` may not exceed 400 words, or the create is refused with `ERR_FAIR_USE_LIMIT_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/fair_use_excerpt_at_the_word_limit_passes_and_one_word_over_is_rejected
    """
    world = fx.setup_draft_thesis(
        thesis_overrides={"title": "Quoted Passages", "third_party_item_count": 2}
    )
    thesis_id = world["thesis"]["id"]
    version_before = fx.thesis_version(thesis_id)

    at_the_limit = get_success_data(
        api.create_permission_record(
            create_permission_record_payload(
                thesis_id,
                version_before,
                material_type="EXCERPT",
                rights_basis="FAIR_USE_ASSERTION",
                page_reference="pp. 30-31",
                excerpt_word_count=400,
            ),
            world["student_headers"],
        ),
        201,
    )
    assert at_the_limit["excerpt_word_count"] == 400
    assert at_the_limit["status"] == "SUBMITTED"

    version_after = fx.thesis_version(thesis_id)
    assert version_after > version_before

    validate_error(
        api.create_permission_record(
            create_permission_record_payload(
                thesis_id,
                version_after,
                material_type="EXCERPT",
                rights_basis="FAIR_USE_ASSERTION",
                page_reference="pp. 44-45",
                excerpt_word_count=401,
            ),
            world["student_headers"],
        ),
        "ERR_FAIR_USE_LIMIT_EXCEEDED",
        422,
    )

    records = get_success_data(api.list_thesis_permission_records(thesis_id, REGISTRAR))
    assert len(records) == 1


def test_two_legal_seats_still_miss_the_masters_three_member_floor(
    api: ApiClient,
) -> None:
    """The collective count is what fails, so the submission is refused entirely.

    PRD §3.3: "For a `THESIS` the committee needs at least three members, exactly one `CHAIR` seat, and no `GRADUATE_REPRESENTATIVE` seat at all."

    Design: Corner/validations/masters_committee_with_only_two_confirmed_members_rejected_on_submit
    """
    world = fx.setup_committee_with_seats(
        seat_roles=["CHAIR", "MEMBER"],
        thesis_overrides={"title": "Two Readers Only"},
    )

    validate_error(
        api.submit_committee(world["committee"]["id"], world["student_headers"]),
        "ERR_COMMITTEE_COMPOSITION_INVALID",
        422,
    )

    committee = get_success_data(api.get_thesis_committee(world["thesis"]["id"], REGISTRAR))[0]
    assert committee["status"] == "DRAFT"
    assert committee["member_count"] == 2

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["workflow_state"] == "DRAFT"

    chair = get_success_data(api.get_faculty_member(world["chair"]["id"], REGISTRAR))
    assert chair["active_chair_load"] == 0


def test_an_uncertified_adjunct_may_serve_but_may_not_chair(api: ApiClient) -> None:
    """The eligibility rule guards the chair role only, not committee service.

    PRD §3.3: "A `CHAIR` or `CO_CHAIR` seat may only be given to a faculty member whose `appointment_type` is `TENURED` or `TENURE_TRACK`, whose `graduate_faculty_certified` flag is true, and whose current `active_chair_load` is strictly below four; violating any of the three is `ERR_CHAIR_NOT_ELIGIBLE` (HTTP 422)."

    Design: Corner/validations/chair_seat_for_uncertified_adjunct_faculty_rejected
    """
    world = fx.setup_draft_thesis(thesis_overrides={"title": "Adjunct Chair Attempt"})
    committee = get_success_data(
        api.create_committee(
            create_committee_payload(world["thesis"]["id"]), world["student_headers"]
        ),
        201,
    )
    adjunct = world["member_2"]

    validate_error(
        api.create_committee_member(
            committee["id"],
            create_committee_member_payload(adjunct["id"], "CHAIR"),
            world["student_headers"],
        ),
        "ERR_CHAIR_NOT_ELIGIBLE",
        422,
    )

    seat = get_success_data(
        api.create_committee_member(
            committee["id"],
            create_committee_member_payload(adjunct["id"], "MEMBER"),
            world["student_headers"],
        ),
        201,
    )
    assert seat["role"] == "MEMBER"
    assert seat["status"] == "CONFIRMED"

    committee = get_success_data(api.get_thesis_committee(world["thesis"]["id"], REGISTRAR))[0]
    assert committee["member_count"] == 1

    faculty = get_success_data(api.get_faculty_member(adjunct["id"], REGISTRAR))
    assert faculty["active_chair_load"] == 0


def test_the_same_faculty_member_cannot_take_a_second_seat_in_another_role(
    api: ApiClient,
) -> None:
    """One confirmed seat per person per committee, whatever the role asked for.

    PRD §3.3: "Three further seat rules are enforced together and all report `ERR_COMMITTEE_SEAT_CONFLICT` (HTTP 409): the same faculty member may not hold two `CONFIRMED` seats on one committee, a committee may not gain a second `CHAIR` seat, it may not gain a second `GRADUATE_REPRESENTATIVE` seat, and an `EXTERNAL_MEMBER` seat may be given only to a faculty member whose `appointment_type` is `EXTERNAL`."

    Design: Corner/validations/second_confirmed_seat_for_the_same_faculty_rejected
    """
    world = fx.setup_draft_thesis(thesis_overrides={"title": "Double Seated"})
    committee = get_success_data(
        api.create_committee(
            create_committee_payload(world["thesis"]["id"]), world["student_headers"]
        ),
        201,
    )
    world["committee"] = committee
    first_seat = fx.seat_member(world, world["member_1"], "MEMBER")

    validate_error(
        api.create_committee_member(
            committee["id"],
            create_committee_member_payload(world["member_1"]["id"], "CO_CHAIR"),
            REGISTRAR,
        ),
        "ERR_COMMITTEE_SEAT_CONFLICT",
        409,
    )

    committee = get_success_data(api.get_thesis_committee(world["thesis"]["id"], REGISTRAR))[0]
    assert committee["member_count"] == 1

    seat = get_success_data(api.get_committee_member(first_seat["id"], REGISTRAR))
    assert seat["role"] == "MEMBER"

    rows, _ = validate_paginated(
        api.list_committee_members(REGISTRAR, params={"committee_id": committee["id"]})
    )
    assert len(rows) == 1


def test_a_candidate_cannot_open_a_second_live_document_in_one_term(
    api: ApiClient,
) -> None:
    """The DRAFT original is non-terminal, so the second attempt is refused.

    PRD §3.2: "If the acting student already has another `Thesis` in the same term whose `workflow_state` is anything other than `DEFENSE_FAILED`, `TERMINATED` or `CONFERRED`, the create is refused with `ERR_DUPLICATE_THESIS_FOR_TERM` (HTTP 409); a failed or terminated attempt therefore leaves the candidate free to start again in the same term."

    Design: Corner/validations/second_active_thesis_for_the_same_term_rejected
    """
    world = fx.setup_draft_thesis(thesis_overrides={"title": "First Attempt"})

    validate_error(
        api.create_thesis(
            create_thesis_payload(
                world["student"]["id"],
                world["term"]["id"],
                title="Second Attempt",
                page_count=120,
            ),
            world["student_headers"],
        ),
        "ERR_DUPLICATE_THESIS_FOR_TERM",
        409,
    )

    original = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert original["workflow_state"] == "DRAFT"
    assert original["title"] == "First Attempt"

    rows, meta = validate_paginated(
        api.list_theses(REGISTRAR, params={"student_id": world["student"]["id"]})
    )
    assert len(rows) == 1
    assert meta["total_count"] == 1


def test_the_masters_patent_cap_is_twelve_months_not_twenty_four(
    api: ApiClient,
) -> None:
    """Thirteen months breaks the halved cap while exactly twelve is accepted.

    PRD §3.7: "For a `MASTERS` candidate each cap is halved and any fraction discarded, giving 12, 6, 18 and 6 months. A `requested_months` above the applicable cap is refused with `ERR_EMBARGO_DURATION_EXCEEDS_CAP` (HTTP 422); a request for exactly the cap is accepted."

    Design: Corner/validations/masters_patent_embargo_request_of_thirteen_months_rejected
    """
    world = fx.setup_passed_defense(thesis_overrides={"title": "Patentable Method"})
    thesis_id = world["thesis"]["id"]
    version = fx.thesis_version(thesis_id)

    validate_error(
        api.create_embargo_request(
            create_embargo_request_payload(
                thesis_id,
                version,
                reason_code="PATENT_PENDING",
                requested_months=13,
                justification="Patent counsel asked for thirteen months",
            ),
            world["student_headers"],
        ),
        "ERR_EMBARGO_DURATION_EXCEEDS_CAP",
        422,
    )
    assert (
        get_success_data(api.list_thesis_embargo_requests(thesis_id, REGISTRAR)) == []
    )

    at_the_cap = get_success_data(
        api.create_embargo_request(
            create_embargo_request_payload(
                thesis_id,
                version,
                reason_code="PATENT_PENDING",
                requested_months=12,
                justification="Trimmed to the masters cap",
            ),
            world["student_headers"],
        ),
        201,
    )
    assert at_the_cap["requested_months"] == 12
    assert at_the_cap["status"] == "REQUESTED"

    rows = get_success_data(api.list_thesis_embargo_requests(thesis_id, REGISTRAR))
    assert len(rows) == 1


def test_a_partial_approval_must_actually_shorten_the_embargo(api: ApiClient) -> None:
    """Twelve of twelve is refused; six of twelve is the terminal partial grant.

    PRD §3.7: "The body value must be present, at least 1, and strictly less than `requested_months`"

    Design: Corner/validations/partial_approval_equal_to_the_requested_duration_rejected
    """
    world = fx.setup_passed_defense(
        dean_user_id=DEAN_ONE_USER_ID, thesis_overrides={"title": "Shortened Hold"}
    )
    embargo = fx.request_embargo(
        world,
        reason_code="PATENT_PENDING",
        requested_months=12,
        justification="Provisional patent application filed",
    )

    validate_error(
        api.decide_embargo_request(
            embargo["id"],
            {
                "decision": "PARTIALLY_APPROVE",
                "approved_months": 12,
                "decision_note": "Same length as requested",
            },
            DEAN_TWO,
        ),
        "ERR_EMBARGO_DURATION_EXCEEDS_CAP",
        422,
    )

    unchanged = get_success_data(api.get_embargo_request(embargo["id"], REGISTRAR))
    assert unchanged["status"] == "REQUESTED"
    assert unchanged["approved_months"] is None

    shortened = get_success_data(
        api.decide_embargo_request(
            embargo["id"],
            {
                "decision": "PARTIALLY_APPROVE",
                "approved_months": 6,
                "decision_note": "Shortened to six months",
            },
            make_dean_headers(DEAN_TWO_USER_ID),
        ),
        200,
    )
    assert shortened["status"] == "PARTIALLY_APPROVED"
    assert shortened["approved_months"] == 6
    assert shortened["decided_by_user_id"] == DEAN_TWO_USER_ID
    assert shortened["release_date"] is None


def test_a_maintenance_room_and_a_twenty_minute_slot_share_one_refusal(
    api: ApiClient,
) -> None:
    """Both room-availability clauses report the same identifier before the booking lands.

    PRD §3.4: "The room must not be in `MAINTENANCE`, and the occupation length — `scheduled_end` minus `scheduled_start` — must be at least 30 and at most 240 whole minutes; either failure is `ERR_ROOM_UNAVAILABLE` (HTTP 409)."

    Design: Corner/validations/defense_in_maintenance_room_or_shorter_than_thirty_minutes_rejected
    """
    world = fx.setup_approved_committee(thesis_overrides={"title": "Room Rules"})
    closed_room = fx.add_defense_room(
        world, code="R102", building="Graduate Hall", status="MAINTENANCE"
    )
    open_room = world["room"]

    validate_error(
        api.create_defense_event(
            create_defense_event_payload(world["thesis"]["id"], closed_room["id"]),
            world["student_headers"],
        ),
        "ERR_ROOM_UNAVAILABLE",
        409,
    )

    validate_error(
        api.create_defense_event(
            create_defense_event_payload(
                world["thesis"]["id"],
                open_room["id"],
                scheduled_end="2026-09-25T14:20:00Z",
            ),
            world["student_headers"],
        ),
        "ERR_ROOM_UNAVAILABLE",
        409,
    )

    event = get_success_data(
        api.create_defense_event(
            create_defense_event_payload(world["thesis"]["id"], open_room["id"]),
            world["student_headers"],
        ),
        201,
    )
    assert event["status"] == "DRAFT"

    assert (
        get_success_data(api.get_defense_room(open_room["id"], REGISTRAR))[
            "booked_minutes_total"
        ]
        == 120
    )
    assert (
        get_success_data(api.get_defense_room(closed_room["id"], REGISTRAR))[
            "booked_minutes_total"
        ]
        == 0
    )

    rows, _ = validate_paginated(
        api.list_defense_events(REGISTRAR, params={"thesis_id": world["thesis"]["id"]})
    )
    assert len(rows) == 1


def test_a_defense_may_be_booked_neither_in_the_past_nor_past_the_deadline(
    api: ApiClient,
) -> None:
    """The two temporal guards read different reference points and report differently.

    PRD §3.4: "`scheduled_start` must be strictly after the logical clock, so a defense may not be booked into the past or at the present instant; otherwise `ERR_DEFENSE_START_IN_PAST` (HTTP 422). And `scheduled_start` must be no later than the term's `defense_deadline`, which is inclusive — a defense starting exactly at the deadline instant is accepted, one starting a second later is refused with `ERR_DEFENSE_AFTER_TERM_DEADLINE` (HTTP 422)."

    Design: Corner/validations/defense_start_in_the_past_or_after_the_term_deadline_rejected
    """
    world = fx.setup_approved_committee(thesis_overrides={"title": "Out Of Window"})

    validate_error(
        api.create_defense_event(
            create_defense_event_payload(
                world["thesis"]["id"],
                world["room"]["id"],
                scheduled_start="2026-07-20T14:00:00Z",
                scheduled_end="2026-07-20T16:00:00Z",
            ),
            world["student_headers"],
        ),
        "ERR_DEFENSE_START_IN_PAST",
        422,
    )

    validate_error(
        api.create_defense_event(
            create_defense_event_payload(
                world["thesis"]["id"],
                world["room"]["id"],
                scheduled_start="2026-11-20T14:00:00Z",
                scheduled_end="2026-11-20T16:00:00Z",
            ),
            world["student_headers"],
        ),
        "ERR_DEFENSE_AFTER_TERM_DEADLINE",
        422,
    )

    room = get_success_data(api.get_defense_room(world["room"]["id"], REGISTRAR))
    assert room["booked_minutes_total"] == 0

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["workflow_state"] == "COMMITTEE_APPROVED"

    rows, meta = validate_paginated(
        api.list_defense_events(REGISTRAR, params={"thesis_id": world["thesis"]["id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_a_resubmission_one_day_past_the_revision_window_is_refused(
    api: ApiClient,
) -> None:
    """The bounded revision loop closes at revision_due_at and stays closed.

    PRD §3.5: "A resubmission after that instant is refused with `ERR_REVISION_WINDOW_EXPIRED` (HTTP 409), which is what makes the `UNDER_FORMAT_REVIEW → FORMAT_REVISIONS_REQUIRED → UNDER_FORMAT_REVIEW` loop bounded rather than infinite; `cycle_number` strictly increases with every turn of it, so the loop is always observable in the record."

    Design: Corner/validations/format_resubmission_after_the_revision_window_closed_rejected
    """
    world = fx.setup_open_format_cycle(
        cycle_clock="2026-10-05T09:00:00Z",
        with_screening=False,
        thesis_overrides={"title": "Missed Window"},
    )
    review = fx.decide_format_review(
        world,
        world["format_review"],
        decision="RETURN_REVISIONS",
        critical_defect_count=1,
        clock="2026-10-06T09:00:00Z",
        review_note="One critical defect",
    )
    fx.set_clock("2026-10-21T09:00:00Z")

    validate_error(
        api.create_format_submission(world["thesis"]["id"], world["student_headers"]),
        "ERR_REVISION_WINDOW_EXPIRED",
        409,
    )

    review = get_success_data(api.get_format_review(review["id"], REGISTRAR))
    assert review["revision_due_at"] is not None
    assert review["severity_weighted_defect_score"] == pytest.approx(3.43, abs=0.001)
    assert review["status"] == "REVISIONS_REQUIRED"

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["format_cycle_count"] == 1
    assert thesis["workflow_state"] == "FORMAT_REVISIONS_REQUIRED"

    reviews = get_success_data(
        api.list_thesis_format_reviews(world["thesis"]["id"], REGISTRAR)
    )
    assert len(reviews) == 1
